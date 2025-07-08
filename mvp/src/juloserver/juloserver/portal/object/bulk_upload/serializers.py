"""
serializer.py

"""
from __future__ import division
from numpy import require
from past.utils import old_div
from builtins import object
from rest_framework import serializers
from django.utils import timezone

import re

from juloserver.julo.models import (
    Customer, Application,
    ProductLine, Loan
)
from juloserver.julo.partners import PartnerConstant
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag
from juloserver.sdk.models import AxiataCustomerData, AxiataRepaymentData, AxiataTemporaryData
from juloserver.apiv2.services import get_latest_app_version
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.merchant_financing.utils import get_partner_product_line
from juloserver.julocore.python2.utils import py2round
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import Partner
from juloserver.julo.utils import verify_nik
from juloserver.grab.models import GrabLoanData
from juloserver.grab.utils import GrabUtils
from juloserver.grab.models import GrabCustomerData


class IcareApplicationSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    partner = serializers.CharField(required=True)


class ApprovalContentSerializer(serializers.Serializer):
    delivered_date = serializers.DateField(required=True, input_formats=["%Y-%m-%d"])
    sphp_sign_date = serializers.DateField(input_formats=["%Y-%m-%d"], required=True)
    net_amount = serializers.IntegerField(required=True)
    bast_dn_number = serializers.CharField(required=True)
    first_installment_date = serializers.DateField(input_formats=["%Y-%m-%d"], required=True)
    application_xid = serializers.IntegerField(required=True)

    def validate(self, attrs):
        """
        Check that application is available
        """
        application = Application.objects.get_or_none(
            application_xid=attrs['application_xid'],
            partner__name='icare'
        )
        if not application:
            raise serializers.ValidationError({'Validation': 'Application not found'})
        if application.status != ApplicationStatusCodes.FORM_GENERATED:
            raise serializers.ValidationError({'Validation': 'App status is not available'})
        return attrs


class DisbursementContentSerializer(serializers.Serializer):
    application_xid = serializers.IntegerField(required=True)
    fullname = serializers.CharField(required=True)
    dob = serializers.DateField(input_formats=["%Y-%m-%d"], required=True)

    def validate(self, attrs):
        """
        Check that application is alive and available status
        """
        application = Application.objects.get_or_none(
            application_xid=attrs['application_xid'],
            fullname=attrs['fullname'],
            dob=attrs['dob'],
            partner__name__in=['icare', 'axiata']
            # customer__is_deleted=False
        )

        if not application:
            raise serializers.ValidationError({'Validation': 'Application not found'})
        if application.status != ApplicationStatusCodes.FUND_DISBURSAL_ONGOING:
            raise serializers.ValidationError({'Validation': 'App status is not available'})
        return attrs


class CustomerSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Customer
        # we don't want to show all fields to client.
        exclude = (
            'id', 'is_email_verified', 'country', 'email_verification_key',
            'advertising_id', 'can_reapply_date',
            'email_key_exp_date', 'reset_password_key', 'is_phone_verified', 'appsflyer_device_id',
            'reset_password_exp_date', 'user', 'is_review_submitted', 'disabled_reapply_date',
            'potential_skip_pv_dv', 'google_access_token', 'google_refresh_token',
            'application_status', 'onboarding', 'product_line', 'partner', 'workflow',
            'name_bank_validation', 'current_device', 'application_merchant',
            'application_company'
        )


class ApplicationPartnerUpdateSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        if attrs.get('payday', 1) > 28:
            attrs['payday'] = 28

        if not attrs.get('app_version'):
            attrs['app_version'] = get_latest_app_version()

        if not attrs.get('income_1'):
            attrs['income_1'] = 0

        if not attrs.get('income_2'):
            attrs['income_2'] = 0

        if not attrs.get('income_3'):
            attrs['income_3'] = 0

        if not attrs.get('monthly_income'):
            attrs['monthly_income'] = 0

        return attrs

    class Meta(object):
        model = Application
        exclude = ('id', 'application_status', 'device',
                   'product_line', 'partner', 'mantri', 'workflow',
                   'line_of_credit', 'customer', 'customer_credit_limit', 'account',
                   'name_bank_validation', 'merchant', 'company', 'onboarding')

    def validate_email(self, value):
        return value.strip().lower()


class RejectionContentSerializer(serializers.Serializer):
    ktp = serializers.CharField(required=True)
    fullname = serializers.CharField(required=True)
    dob = serializers.DateField(input_formats=["%Y-%m-%d"])
    verdict = serializers.ChoiceField(choices=['no', 'NO', 'No'], required=True)

    def validate(self, attrs):
        """
        Check that application is available
        """
        application = Application.objects.get_or_none(
            ktp=attrs['ktp'],
            fullname=attrs['fullname'],
            dob=attrs['dob'],
            partner__name='icare'
        )
        if not application:
            raise serializers.ValidationError({'Validation': 'Application not found'})
        if application.status != ApplicationStatusCodes.FORM_GENERATED:
            raise serializers.ValidationError({'Validation': 'App status is not available'})
        return attrs


class AxiataCustomerDataSerializer(serializers.ModelSerializer):
    ktp = serializers.CharField(required=True)
    fullname = serializers.CharField(required=True)
    dob = serializers.DateField(required=True)
    first_payment_date = serializers.DateField(required=True)
    acceptance_date = serializers.DateTimeField(required=True)
    phone_number = serializers.CharField(required=True)
    marital_status = serializers.CharField(required=True)
    gender = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    birth_place = serializers.CharField(required=True)
    distributor = serializers.CharField(required=True)
    axiata_temporary_data_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    user_type = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    income = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_education = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    home_status = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    certificate_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    certificate_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    npwp = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    kin_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    kin_mobile_phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta(object):
        model = AxiataCustomerData

    def validate(self, data):
        from juloserver.portal.object.bulk_upload.utils import (  # noqa
            validate_last_education,
            validate_home_status,
            validate_income,
            validate_certificate_number,
            validate_certificate_date,
            validate_npwp,
            validate_kin_name,
            validate_kin_mobile_phone,
        )

        partner = Partner.objects.filter(name=PartnerConstant.AXIATA_PARTNER).last()
        field_flag = PartnershipFlowFlag.objects.filter(
            partner_id=partner.id, name=PartnershipFlag.FIELD_CONFIGURATION
        ).last()
        config = field_flag.configs

        # validate user_type
        if config['fields'].get('user_type'):
            if not data.get('user_type'):
                raise serializers.ValidationError(
                    {'Error': [{'Jenis Pengguna': [u'jenis pengguna tidak boleh kosong']}]}
                )

            if data.get('user_type', '').lower() not in ['perorangan', 'lembaga']:
                raise serializers.ValidationError(
                    {
                        'Error': [
                            {
                                'Jenis Pengguna': [
                                    u'jenis pengguna tidak sesuai, mohon isi sesuai master perorangan, lembaga'
                                ]
                            }
                        ]
                    }
                )

        # Additional list for pusdafil 2.0
        additional_field_list = [
            'income',
            'certificate_number',
            'certificate_date',
            'npwp',
            'last_education',
            'home_status',
            'kin_name',
            'kin_mobile_phone',
        ]
        for field in additional_field_list:
            validate_func = eval('validate_{}'.format(field))
            is_mandatory = config['fields'].get(field, False)
            is_valid, error_notes = validate_func(value=data.get(field), is_mandatory=is_mandatory)

            if not is_valid:
                # if required field for current user type and not valid should throw an error
                user_type_field_set = config.get(data.get('user_type', '').lower(), [])
                if field in user_type_field_set:
                    raise serializers.ValidationError({'Error': [{field: [error_notes]}]})
                else:
                    if is_mandatory:
                        raise serializers.ValidationError({'Error': [{field: [error_notes]}]})
                    else:
                        # if not required field for current user type and not valid
                        # we can still upload and don't need to read the field (None)
                        data[field] = None

        customer = Customer.objects.filter(nik=data['ktp']).last()
        if customer:
            loan = Loan.objects.filter(customer=customer).paid_off().first()
            product_line_codes = ProductLineCodes.axiata()
            product_line = ProductLine.objects.filter(product_line_code__in=product_line_codes)
            product_line_list = product_line.repeat_lines() if loan else \
                product_line.first_time_lines()
        else:
            product_line_codes = ProductLineCodes.axiata()
            product_line = ProductLine.objects.filter(product_line_code__in=product_line_codes)
            product_line_list = product_line.first_time_lines()

        _product_line, product_lookup = get_partner_product_line(
            data['interest_rate'],
            data['origination_fee'],
            data['admin_fee'],
            product_line_list.first().product_line_code
        )

        if not product_lookup:
            raise serializers.ValidationError(
                {'Error': [
                    {'Profit/Interest Rate': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                    {'Provisi': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                    {'Biaya Admin': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                    {'Late Fee': [u'Tidak sesuai dengan nilai yang didaftarkan']},
                ]}
            )

        return data

    def validate_email(self, value):
        return value.strip().lower()


class AxiataTemporaryDataSerializer(serializers.ModelSerializer):
    ktp = serializers.CharField(required=True)
    fullname = serializers.CharField(required=True)
    dob = serializers.DateField(required=True)
    phone_number = serializers.CharField(required=True)
    marital_status = serializers.CharField(required=True)
    gender = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    birth_place = serializers.CharField(required=True)

    class Meta(object):
        model = AxiataTemporaryData

    def validate_email(self, value):
        return value.strip().lower()


class RepaymentDataSerializer(serializers.ModelSerializer):
    application_xid = serializers.IntegerField(required=False)
    payment_amount = serializers.IntegerField(required=True)
    payment_number = serializers.IntegerField(required=True)
    due_date = serializers.DateField(required=True)
    payment_date = serializers.DateField(required=True)
    partner_application_id = serializers.CharField(required=False)

    class Meta(object):
        model = AxiataRepaymentData

    def validate(self, data):
        if not (data.get('application_xid') or data.get('partner_application_id')):
            raise serializers.ValidationError(
                {
                    'Error': 'application_xid and partner_application_id can not be null together'
                }
            )

        return data


class MerchantFinancingUploadRegisterSerializer(serializers.Serializer):
    ktp_photo = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('KTP doc')
    )
    selfie_photo = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Selfie doc')
    )
    fullname = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Name')
    )
    mobile_phone_1 = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Phone#')
    )
    ktp = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('KTP #')
    )
    fullname = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Name')
    )
    gender = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Jenis Kelamin')
    )
    birth_place = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tempat Lahir')
    )
    dob = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tanggal Lahir')
    )
    marital_status = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Status Pernikahan')
    )
    close_kin_name = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Nama Ibu Kandung / spouse (if married)')
    )
    address_provinsi = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Nama Propinsi')
    )
    address_kabupaten = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Nama Kota/Kabupaten')
    )
    address_kecamatan = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Kelurahan')
    )
    address_kodepos = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Kode Pos Rumah')
    )
    address_street_num = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Detail Alamat')
    )
    loan_purpose = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tujuan pinjaman')
    )
    monthly_income = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Omset penjualan perbulan')
    )
    monthly_expenses = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Pengeluaran perbulan')
    )
    usaha = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Tipe usaha')
    )
    approved_limit = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required('Approved Limit')
    )
    provision = serializers.FloatField(
        required=False,
        allow_null=True,
        error_messages=custom_error_messages_for_required('Percentage')
    )
    bank_account_number = serializers.CharField(
        allow_null=True, allow_blank=True
    )
    pegawai = serializers.CharField(
        allow_null=True, allow_blank=True
    )

    def validate_ktp(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError("KTP # tidak valid")
        return value

    def validate_mobile_phone_1(self, value):
        phone_regex = re.compile(r'^(\+62|62)?[\s-]?0?8[1-9]{1}\d{1}[\s-]?\d{4}[\s-]?\d{2,5}$')
        if not phone_regex.match(value):
            raise serializers.ValidationError('Nomor Handphone (Phone#) tidak valid')
        return value

    def validate_monthly_income(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Omset penjualan perbulan harus angka')
        return value

    def validate_monthly_expenses(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Pengeluaran perbulan harus angka')
        return value

    def validate_approved_limit(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Approved Limit harus angka')
        return value

    def validate_bank_account_number(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('No rek bank harus angka')
        return value

    def validate_pegawai(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('Jumlah pegawai harus angka')
        return value


class LoanHaltResumeSerializer(serializers.Serializer):
    loan_xid = serializers.IntegerField(required=True)
    date = serializers.DateField(
        format="%Y.%m.%d",
        input_formats=['%Y.%m.%d'],
        required=False,
        default=timezone.localtime(
            timezone.now()
        ).date()
    )
    action = serializers.CharField(required=True)
    action_key = serializers.CharField()
    partner = serializers.CharField()

    def validate(self, data):
        if not data.get('loan_xid'):
            raise serializers.ValidationError(
                {
                    'Error': 'loan_xid is null'
                }
            )
        loan = Loan.objects.filter(loan_xid=data.get('loan_xid')).last()

        if data.get('action') not in ['resume', 'halt']:
            raise serializers.ValidationError(
                {
                    'Error': 'not a valid action'
                }
            )
        if data.get('action_key') == 'Resume':
            if loan.status != LoanStatusCodes.HALT:
                raise serializers.ValidationError(
                    {
                        'Error': 'Loan not in Halt status'
                    }
                )
            grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
            if not grab_loan_data:
                raise serializers.ValidationError(
                    {
                        'Error': 'Grab Customer Data doesnt exist for loan'
                    }
                )
            halt_date = grab_loan_data.loan_halt_date

            if data.get('date') and data.get('date') < halt_date:
                raise serializers.ValidationError(
                    {
                        'Error': 'Date is earlier than Halt date'
                    }
                )

        if data.get('action_key') == 'Halt':
            if loan.status == LoanStatusCodes.HALT:
                raise serializers.ValidationError(
                    {
                        'Error': 'Loan Already Halted'
                    }
                )
        account = loan.account
        partner = Partner.objects.filter(name=data.get('partner')).last()
        if account and partner:
            application = account.last_application
            if partner != application.partner:
                raise serializers.ValidationError(
                    {
                        'Error': 'Partner does not match application'
                    }
                )
        else:
            raise serializers.ValidationError(
                {
                    'Error': 'Invalid account or partner'
                }
            )

        return data


class LoanGrabRestructureSerializer(serializers.Serializer):
    loan_xid = serializers.IntegerField(required=True)
    action = serializers.CharField(required=True)
    action_key = serializers.CharField()
    partner = serializers.CharField()

    def validate(self, data):
        if not data.get('loan_xid'):
            raise serializers.ValidationError(
                {
                    'Error': 'loan_xid is null'
                }
            )
        loan = Loan.objects.filter(loan_xid=data.get('loan_xid')).last()
        if not loan:
            raise serializers.ValidationError(
                {
                    'Error': 'Loan doesnt exist'
                }
            )
        if data.get('action') not in ['restructure', 'revert']:
            raise serializers.ValidationError(
                {
                    'Error': 'not a valid action'
                }
            )
        if loan.status in {
            LoanStatusCodes.HALT, LoanStatusCodes.PAID_OFF,
            LoanStatusCodes.RENEGOTIATED, LoanStatusCodes.DRAFT,
            LoanStatusCodes.LENDER_APPROVAL, LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.INACTIVE, LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.SPHP_EXPIRED, LoanStatusCodes.FUND_DISBURSAL_FAILED,
            LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING, LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.GRAB_AUTH_FAILED, LoanStatusCodes.TRANSACTION_FAILED
        }:
            raise serializers.ValidationError(
                {
                    'Error': 'Loan Status Not Supported'
                }
            )
        grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
        if not grab_loan_data:
            raise serializers.ValidationError(
                {
                    'Error': 'Grab Customer Data doesnt exist for loan'
                }
            )

        account = loan.account
        partner = Partner.objects.filter(name=data.get('partner')).last()
        if account and partner:
            application = account.last_application
            if partner != application.partner:
                raise serializers.ValidationError(
                    {
                        'Error': 'Partner does not match application'
                    }
                )
        else:
            raise serializers.ValidationError(
                {
                    'Error': 'Invalid account or partner'
                }
            )
        if data.get('action_key') == 'Revert':
            if not grab_loan_data.is_repayment_capped:
                raise serializers.ValidationError(
                    {
                        'Error': 'Loan Not Capped'
                    }
                )
        elif data.get('action_key') == 'Restructure':
            if grab_loan_data.is_repayment_capped:
                raise serializers.ValidationError(
                    {
                        'Error': 'Loan Already restructured'
                    }
                )
        return data


class LoanGrabEarlyWriteOffSerializer(serializers.Serializer):
    loan_xid = serializers.IntegerField(required=True)
    action = serializers.CharField(required=True)
    action_key = serializers.CharField()
    partner = serializers.CharField()

    def validate_loan_xid(self, value):
        if not value:
            raise serializers.ValidationError(
                {
                    'Error': 'loan_xid is null'
                }
            )
        loan = Loan.objects.filter(loan_xid=value).last()
        if not loan:
            raise serializers.ValidationError(
                {
                    'Error': 'Loan doesnt exist'
                }
            )
        if loan.status in {
            LoanStatusCodes.HALT, LoanStatusCodes.PAID_OFF,
            LoanStatusCodes.RENEGOTIATED, LoanStatusCodes.DRAFT,
            LoanStatusCodes.LENDER_APPROVAL, LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.INACTIVE, LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.SPHP_EXPIRED, LoanStatusCodes.FUND_DISBURSAL_FAILED,
            LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING, LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.GRAB_AUTH_FAILED, LoanStatusCodes.TRANSACTION_FAILED
        }:
            raise serializers.ValidationError(
                {
                    'Error': 'Loan Status Not Supported'
                }
            )
        account = loan.account
        if not account:
            raise serializers.ValidationError(
                {
                    'Error': 'Invalid account'
                }
            )
        grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
        if not grab_loan_data:
            raise serializers.ValidationError(
                {
                    'Error': 'Grab Customer Data doesnt exist for loan'
                }
            )
        return value

    def validate_action(self, value):
        if value not in ['early_write_off', 'revert']:
            raise serializers.ValidationError(
                {
                    'Error': 'not a valid action'
                }
            )
        return value

    def validate_partner(self, value):
        partner = Partner.objects.filter(name=value).last()
        if not partner:
            raise serializers.ValidationError(
                {
                    'Error': 'Invalid account or partner'
                }
            )
        return value

    def validate_action_key(self, value):
        if value not in ('Revert', 'Early Write Off'):
            raise serializers.ValidationError(
                {
                    'Error': 'Action Key is not Valid'
                }
            )
        return value

    def validate(self, data):
        loan = Loan.objects.filter(loan_xid=data.get('loan_xid')).last()
        account = loan.account
        partner = Partner.objects.filter(name=data.get('partner')).last()
        application = account.last_application
        if partner != application.partner:
            raise serializers.ValidationError(
                {
                    'Error': 'Partner does not match application'
                }
            )
        grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
        if data.get('action_key') == 'Revert':
            if not grab_loan_data.is_early_write_off:
                raise serializers.ValidationError(
                    {
                        'Error': 'Loan not on Early Write off'
                    }
                )
        elif data.get('action_key') == 'Early Write Off':
            if grab_loan_data.is_early_write_off:
                raise serializers.ValidationError(
                    {
                        'Error': 'Loan Already Early Write Off'
                    }
                )
        return data


class GrabReferralSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True)
    action = serializers.CharField(required=True)
    action_key = serializers.CharField()
    partner = serializers.CharField()

    def validate_phone_number(self, value):
        error_message = 'phone_number'
        value, error_message = GrabUtils.validate_phone_number(value, error_message)
        if error_message:
            raise serializers.ValidationError(
                {
                    'Error': error_message
                }
            )
        if not value:
            raise serializers.ValidationError(
                {
                    'Error': 'loan_xid is null'
                }
            )
        grab_customer_data = GrabCustomerData.objects.filter(
            customer__isnull=False,
            phone_number=value
        ).last()
        if not grab_customer_data:
            raise serializers.ValidationError(
                {
                    'Error': 'Grab customer data doesnt exist'
                }
            )

        customer = grab_customer_data.customer
        if not customer:
            raise serializers.ValidationError(
                {
                    'Error': 'Customer doesnt exist'
                }
            )
        if not customer.application_set.filter(
            product_line__product_line_code__in=ProductLineCodes.grab(),
            application_status_id=ApplicationStatusCodes.LOC_APPROVED
        ).exists():
            raise serializers.ValidationError(
                {
                    'Error': '190 application missing'
                }
            )
        if customer.loan_set.filter(
            loan_status_id__in=set(
                LoanStatusCodes.grab_current_until_180_dpd() + (
                    LoanStatusCodes.PAID_OFF,)
            )
        ).count() < 1:
            raise serializers.ValidationError(
                {
                    'Error': 'No active loans'
                }
            )
        return value

    def validate_action(self, value):
        if value != 'referral':
            raise serializers.ValidationError(
                {
                    'Error': 'not a valid action'
                }
            )
        return value

    def validate_partner(self, value):
        partner = Partner.objects.filter(name=value).last()
        if not partner:
            raise serializers.ValidationError(
                {
                    'Error': 'Invalid account or partner'
                }
            )
        return value

    def validate_action_key(self, value):
        if value not in {'Referral w/o updating whitelist', 'Referral'}:
            raise serializers.ValidationError(
                {
                    'Error': 'Action Key is not Valid'
                }
            )
        return value


class MerchantFinancingCSVUploadUpgradeSerializer(serializers.Serializer):
    application_xid = serializers.IntegerField()
    limit_upgrading = serializers.IntegerField()

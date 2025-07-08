import io
import os
import logging
import pyotp
import time
import csv

from datetime import date
from typing import Tuple, Dict, Union
from collections import namedtuple
from datetime import timedelta, datetime

from django.core.files import File
from django.db.models import Q
from django_bulk_update.helper import bulk_update
from django.conf import settings

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import AuthUser as User, ApplicationNote
from django.template.loader import render_to_string
from django.utils import timezone
from django.db import connections
from django.db import transaction
from PIL import Image as Imagealias
from rest_framework import status

from juloserver.account.models import AccountLimit
from juloserver.account.models import AccountTransaction
from juloserver.account.services.credit_limit import (
    get_salaried,
    get_is_proven,
    is_inside_premium_area,
    get_proven_threshold,
    get_voice_recording,
    store_account_property_history,
)
from juloserver.account.models import AccountProperty
from juloserver.account_payment.models import AccountPayment
from juloserver.dana.utils import round_half_up
from juloserver.fdc.files import TempDir
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
    VendorConst,
    XidIdentifier,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Application,
    Bank,
    Customer,
    ProductLine,
    Partner,
    Workflow,
    MobileFeatureSetting,
    OtpRequest,
    SmsHistory,
    Image,
    Document,
    PaymentMethod,
    UploadAsyncState,
)

from juloserver.julo.models import SphpTemplate
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import Loan
from juloserver.julo.models import Payment
from juloserver.julo.models import PaymentEvent
from juloserver.julo.models import ProductLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tasks import send_sms_otp_token
from juloserver.merchant_financing.constants import (
    MF_STANDARD_REGISTER_UPLOAD_HEADER,
    MF_COMPLIANCE_REGISTER_UPLOAD_MAPPING_FIELDS,
    MFComplianceRegisterUpload,
    ADDITIONAL_MF_STANDARD_REGISTER_UPLOAD_HEADER,
    ADDITIONAL_MF_COMPLIANCE_REGISTER_UPLOAD_MAPPING_FIELDS,
)
from juloserver.merchant_financing.web_app.serializers import MfMerchantRegisterSerializer
from juloserver.partnership.models import (
    PartnershipDistributor,
    PartnershipCustomerData,
    PartnershipApplicationData,
    PartnerLoanRequest,
    PartnershipDocument,
    PartnershipImage,
    PartnershipFlowFlag,
)
from juloserver.merchant_financing.web_app.constants import (
    AXIATA_MAX_LATE_FEE_APPLIED,
    PARTNERSHIP_PREFIX_IDENTIFIER,
    PARTNERSHIP_SUFFIX_EMAIL,
    WebAppErrorMessage,
    MFStandardMerchantStatus,
    MFStandardImageType,
    MFStandardDocumentType,
)
from juloserver.merchant_financing.web_app.utils import (
    create_partnership_email,
    create_partnership_nik,
    create_temporary_partnership_user_nik,
    masking_axiata_web_app_phone_number,
    mf_standard_generate_onboarding_document,
)
from juloserver.partnership.constants import (
    DOCUMENT_TYPE,
    PAYMENT_METHOD_NAME_BCA,
    PartnershipHttpStatusCode,
    PartnershipImageStatus,
    PartnershipImageProductType,
    PartnershipXIDGenerationMethod,
    PartnershipFlag,
)
from juloserver.merchant_financing.web_portal.constants import (
    DISTRIBUTOR_UPLOAD_MAPPING_FIELDS
)
from juloserver.disbursement.constants import NameBankValidationStatus
import juloserver.merchant_financing.services as mf_services
from juloserver.otp.constants import SessionTokenAction
from juloserver.partnership.services.web_services import get_merchant_skrtp_agreement
from juloserver.partnership.services.services import partnership_generate_xid
from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
from juloserver.personal_data_verification.clients.dukcapil_fr_client import DukcapilFRClient
from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.pin.constants import OtpResponseMessage
from juloserver.julo.utils import (
    upload_file_to_oss,
    generate_email_key,
    upload_file_as_bytes_to_oss,
    construct_remote_filepath,
)
from juloserver.merchant_financing.web_app.utils import (
    success_response_web_app,
    error_response_web_app,
    no_content_response_web_app,
)
from juloserver.pin.constants import PinResetReason
import juloserver.pin.services as password_services
from juloserver.apiv2.constants import FDCFieldsName
from juloserver.julo.services import process_application_status_change
from juloserver.apiv2.tasks import populate_zipcode
from juloserver.merchant_financing.api_response import (
    error_response as mf_error_response,
    success_response as mf_success_response,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountCategory, BankAccountDestination
from juloserver.disbursement.models import NameBankValidation
from juloserver.sdk.models import AxiataCustomerData
from juloserver.julo.banks import BankManager

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def create_partnership_user(payload_data: Dict, partner_name: str) -> Tuple:
    """
    This function create:
    - User
    - Customer
    - Application
    - Update Partnership Customer Data
    """
    pii_partner_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': partner_name})
    partner = Partner.objects.filter(is_active=True, **pii_partner_filter_dict).last()

    # Create Partnership Customer Data
    data = {
        'nik': payload_data['nik'],
        'email': payload_data['email'],
        'partner': partner,
    }

    pii_nik_filter_dict = generate_pii_filter_query_partnership(
        Customer, {'nik': payload_data['nik']}
    )
    old_customer_id = (
        Customer.objects.filter(**pii_nik_filter_dict).values_list('id', flat=True).last()
    )
    if old_customer_id:
        pii_partner_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': PartnerConstant.AXIATA_PARTNER}
        )
        partner_old_axiata = Partner.objects.filter(**pii_partner_filter_dict).last()

        existed_axiata_application = Application.objects.filter(
            customer_id=old_customer_id,
            partner=partner_old_axiata,
            application_status_id=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        ).exists()
        if existed_axiata_application:
            data['customer_id_old'] = old_customer_id

    partnership_customer_data = PartnershipCustomerData.objects.create(**data)

    # temporary nik user
    temp_nik = create_temporary_partnership_user_nik(payload_data.get('nik'))

    user_email = create_partnership_email(payload_data.get('nik'), partner_name)

    user = User(username=temp_nik, email=user_email)
    user.set_password(payload_data['password'])
    user.save()

    # We still use existing flow for forgot password
    customer_password_service = password_services.CustomerPinService()
    customer_password_service.init_customer_pin(user)

    # create customer
    customer = Customer.objects.create(
        user=user,
        email=user_email,
        appsflyer_device_id=None,
        advertising_id=None,
        mother_maiden_name=None,
    )

    workflow = Workflow.objects.get(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
    partnership_product_line = ProductLine.objects.get(
        pk=ProductLineCodes.AXIATA_WEB
    )
    web_version = "0.0.1"
    application = Application.objects.create(
        customer=customer,
        email=user_email,
        partner=partnership_customer_data.partner,
        workflow=workflow,
        product_line=partnership_product_line,
        web_version=web_version,
    )

    # User partnership NIK
    user_nik = create_partnership_nik(application.id)

    # Update user, customer, application nik
    user.username = user_nik
    user.save(update_fields=['username'])

    customer.nik = user_nik
    customer.save(update_fields=['nik'])

    application.ktp = user_nik
    application.save(update_fields=['ktp'])

    # Update partnership customer data
    partnership_customer_data.customer = customer
    partnership_customer_data.application = application
    partnership_customer_data.save(update_fields=['customer', 'application'])
    PartnershipApplicationData.objects.create(
        partnership_customer_data=partnership_customer_data,
        application=application,
        email=payload_data['email'],
        web_version=web_version
    )
    # Set application STATUS to 100
    process_application_status_change(
        application.id,
        ApplicationStatusCodes.FORM_CREATED,
        change_reason='customer_triggered'
    )
    partnership_data = namedtuple(
        'PartnershipCustomerData', [
            'user',
            'application_xid',
            'nik',
            'email',
        ]
    )
    partnership_application_data = partnership_data(
        user,
        application.application_xid,
        payload_data.get('nik'),
        payload_data.get('email'),
    )

    return partnership_application_data


def distributor_format_data(raw_data):
    formated_data = {}
    for raw_field, formated_field in DISTRIBUTOR_UPLOAD_MAPPING_FIELDS:
        formated_data[formated_field] = raw_data.get(raw_field)

    return formated_data


def validate_and_insert_distributor_data(data_reader, partnership_user):
    invalid_rows = {}
    partnership_distributors_list = []
    is_success_all = True
    is_payment_gateway_service = False
    pii_partner_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerNameConstant.AXIATA_WEB}
    )
    partner_id = (
        Partner.objects.filter(**pii_partner_filter_dict).values_list('id', flat=True).last()
    )
    partnership_flow_flag = (
        PartnershipFlowFlag.objects.filter(
            partner_id=partner_id,
            name=PartnershipFlag.PAYMENT_GATEWAY_SERVICE,
        )
        .values_list('configs', flat=True)
        .last()
    )
    if partnership_flow_flag and partnership_flow_flag.get('payment_gateway_service', True):
        is_payment_gateway_service = True
    # checking row value
    row_number = 1
    for data in data_reader:
        list_column_errors = []
        formated_data = distributor_format_data(data)
        distributor_code = formated_data.get('distributor_code')
        distributor_name = formated_data.get('distributor_name')
        distributor_bank_name = formated_data.get('distributor_bank_name')
        bank_account = formated_data.get('bank_account')
        bank_name = formated_data.get('bank_name')
        bank_code = formated_data.get('bank_code')
        is_valid_bank = False
        bank = None

        # DISTRIBUTOR_CODE validation
        if not distributor_code:
            list_column_errors.append('distributor_code: tidak boleh kosong')

        if distributor_code and not distributor_code.isdigit():
            list_column_errors.append('distributor_code: harus menggunakan angka')
        else:
            is_distributor_exists = PartnershipDistributor.objects.filter(
                distributor_id=distributor_code, is_deleted=False
            ).exists()
            if is_distributor_exists:
                list_column_errors.append('distributor_code: telah terdaftar')
        if row_number > 1:
            # Check if the current value is already in the list of seen values
            # because list starts from 0 so we reduced with 2 for get value rows
            last_row = row_number - 2
            check_distributor_code_last_row = data_reader[last_row].get('distributor code')
            if check_distributor_code_last_row == distributor_code:
                list_column_errors.append('distributor_code: harus unique')

        # DISTRIBUTOR_NAME validation
        if not distributor_name:
            list_column_errors.append('distributor_name: tidak boleh kosong')

        # DISTRIBUTOR_BANK_NAME validation
        if not distributor_bank_name:
            list_column_errors.append('distributor_bank_name: tidak boleh kosong')

        # BANK_NAME validation
        if not bank_name:
            list_column_errors.append('bank_name: tidak boleh kosong')

        if bank_name:
            if is_payment_gateway_service:
                bank = BankManager.get_by_name_or_none(bank_name)
                if not bank:
                    list_column_errors.append('bank_name: nama Bank tidak ditemukan')
                is_valid_bank = True
            else:
                bank = (
                    Bank.objects.values('xfers_bank_code', 'bank_code')
                    .filter(bank_name=bank_name)
                    .first()
                )
                if not bank:
                    list_column_errors.append('bank_name: nama bank tidak sesuai')
                is_valid_bank = True

        # BANK_ACCOUNT validation
        if not bank_account:
            list_column_errors.append('bank_account: tidak boleh kosong')

        if bank_account and not bank_account.isdigit():
            list_column_errors.append('bank_account: format tidak sesuai, harus mengggunakan angka')

        # BANK_NAME validation
        if not bank_name:
            list_column_errors.append('bank_name: tidak boleh kosong')

        # BANK_CODE validation
        if not bank_code:
            list_column_errors.append('bank_code: tidak boleh kosong')

        if bank_code and not bank_code.isdigit():
            list_column_errors.append('bank_code: format tidak sesuai, harus mengggunakan angka')

        # Process Bank Name Validation
        if (
            distributor_code
            and distributor_code.isdigit()
            and bank_account
            and bank_account.isdigit()
            and distributor_bank_name
            and is_valid_bank
            and bank
        ):
            bank_account_services = mf_services.BankAccount()
            is_bank_valid = False

            if is_payment_gateway_service:
                response = bank_account_services.validate_bank_account(
                    bank_id=bank.id,
                    bank_code=bank.bank_code,
                    bank_account_number=bank_account,
                    phone_number="08111111111",
                    name_in_bank=distributor_bank_name,
                )
                if response['status'] != NameBankValidationStatus.SUCCESS:
                    list_column_errors.append('bank_name: {}'.format(response['reason']))
                else:
                    is_bank_valid = True
            else:
                response = bank_account_services.inquiry_bank_account(
                    bank_code=bank['xfers_bank_code'],
                    bank_account_number=bank_account,
                    phone_number="08111111111",
                    name_in_bank=distributor_bank_name,
                )
                if response['status'] != NameBankValidationStatus.SUCCESS:
                    list_column_errors.append('bank_name: {}'.format(response['reason']))
                elif response['validated_name'].lower() != distributor_bank_name.lower():
                    list_column_errors.append('bank_name: nama pemilik rekening tidak sesuai')
                else:
                    is_bank_valid = True

            if is_bank_valid:
                partnership_distributor_data = {
                    'distributor_id': distributor_code,
                    'distributor_name': distributor_name,
                    'distributor_bank_account_number': bank_account,
                    'distributor_bank_account_name': distributor_bank_name,
                    'bank_code': bank_code,
                    'bank_name': bank_name,
                    'partner': partnership_user.partner,
                    'is_deleted': False,
                    'created_by_user_id': partnership_user.user_id,
                }
                partnership_distributors_list.append(
                    PartnershipDistributor(**partnership_distributor_data)
                )

        if list_column_errors:
            result_errors = ', '.join(list_column_errors)
            error_details = {'row_{}'.format(row_number): [result_errors]}
            invalid_rows.update(error_details)
            is_success_all = False

        row_number += 1

    """
        If 1 of 2 data inside the row is invalid we cancel to save the data
        We only save data if all data is valid
    """
    if is_success_all:
        PartnershipDistributor.objects.bulk_create(partnership_distributors_list)
        return no_content_response_web_app()

    return error_response_web_app(
        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY, errors=invalid_rows
    )


def web_app_send_sms_otp(
    phone_number: str,
    application: Application,
    action_type: str = SessionTokenAction.PHONE_REGISTER
) -> Dict:
    mfs = MobileFeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.MOBILE_PHONE_1_OTP
    )
    if not mfs:
        logger.error(
            {
                'action': 'web_app_feature_settings_mobile_phone_1_otp_not_found',
                'message': 'Mobile feature setting mobile_phone_1_otp is not found',
            }
        )
        data = {
            "success": False,
            "content": {
                "active": False,
                "message": "Maaf, ada kesalahan di sistem kami. Silakan klik 'Coba Lagi' "
                           "untuk proses validasi pengiriman kode OTP kamu, ya.",
            },
        }
        return data

    if not mfs.is_active:
        logger.error(
            {
                'action': 'web_app_mobile_feature_settings_mobile_phone_1_otp_not_active',
                'message': 'Mobile feature setting mobile_phone_1_otp is not active',
            }
        )

        data = {
            "success": False,
            "content": {
                "active": mfs.is_active,
                "parameters": mfs.parameters,
                "message": "Verifikasi kode tidak aktif",
            },
        }
        return data

    pii_filter_dict = generate_pii_filter_query_partnership(
        OtpRequest, {'phone_number': phone_number}
    )

    existing_otp_request = (
        OtpRequest.objects.filter(is_used=False, action_type=action_type, **pii_filter_dict)
        .order_by('id')
        .last()
    )

    change_sms_provide = False
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = mfs.parameters['wait_time_seconds']
    otp_max_request = mfs.parameters['otp_max_request']
    otp_resend_time = mfs.parameters['otp_resend_time']
    data = {
        "otp_content": {
            "parameters": {
                'otp_max_request': otp_max_request,
                'wait_time_seconds': otp_wait_seconds,
                'otp_resend_time': otp_resend_time,
            },
            "message": OtpResponseMessage.SUCCESS,
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "otp_max_request_status": False,
            "otp_send_sms_status": True,
            "retry_count": 0,
            "current_time": curr_time,
        }
    }
    if existing_otp_request and existing_otp_request.is_active:
        sms_history = existing_otp_request.sms_history
        prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = (
            SmsHistory.objects.filter(cdate__gte=existing_otp_request.cdate)
            .exclude(status='UNDELIV')
            .count()
        )
        retry_count += 1

        data['otp_content']['expired_time'] = expired_time
        data['otp_content']['resend_time'] = resend_time
        data['otp_content']['retry_count'] = retry_count
        if sms_history and sms_history.status == 'Rejected':
            data['otp_content']['resend_time'] = expired_time
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_content']['otp_send_sms_status'] = False
            logger.warning(
                'sms send is rejected, phone_number={}, otp_request_id={}'.format(
                    phone_number, existing_otp_request.id
                )
            )
            return data
        if retry_count > otp_max_request:
            waiting_time = timezone.localtime(prev_time) + timedelta(seconds=otp_wait_seconds)
            current_datetime = timezone.localtime(timezone.now())
            countdown_time = waiting_time - current_datetime
            countdown_minutes = countdown_time.seconds // 60
            countdown_seconds = countdown_time.seconds % 60
            formatted_message = "Silahkan coba lagi setelah {} menit {} detik".format(
                countdown_minutes,
                countdown_seconds
            )
            data['otp_content']['message'] = formatted_message
            data['otp_content']['resend_time'] = waiting_time
            data['otp_content']['otp_send_sms_status'] = False
            data['otp_content']['otp_max_request_status'] = True
            logger.warning(
                'exceeded the max request, '
                'phone_number={}, otp_request_id={}, retry_count={}, '
                'otp_max_request={}'.format(
                    phone_number, existing_otp_request.id, retry_count, otp_max_request
                )
            )
            return data

        if curr_time < resend_time:
            data['otp_content']['message'] = OtpResponseMessage.FAILED
            data['otp_content']['otp_send_sms_status'] = False
            logger.warning(
                'requested OTP less than resend time, '
                'phone_number={}, otp_request_id={}, current_time={}, '
                'resend_time={}'.format(
                    phone_number, existing_otp_request.id, curr_time, resend_time
                )
            )
            return data

        if not sms_history:
            change_sms_provide = True
        else:
            if (
                curr_time > resend_time
                and sms_history
                and sms_history.comms_provider
                and sms_history.comms_provider.provider_name
            ):
                if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                    change_sms_provide = True

        otp_request = existing_otp_request
    else:
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(phone_number) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))

        otp_request = OtpRequest.objects.create(
            request_id=postfixed_request_id,
            otp_token=otp,
            phone_number=phone_number,
            action_type=action_type,
            customer=application.customer,
            application=application,
        )
        data['otp_content']['otp_send_sms_status'] = True
        data['otp_content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        data['otp_content']['retry_count'] = 1
        data['otp_content']['message'] = OtpResponseMessage.SUCCESS

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token}
    )

    send_sms_otp_token.delay(
        phone_number, text_message, application.customer.id, otp_request.id, change_sms_provide
    )
    data['otp_content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
        seconds=otp_resend_time
    )

    return data


def web_app_verify_sms_otp(data: Dict) -> Dict:
    mfs = MobileFeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.MOBILE_PHONE_1_OTP
    )
    if not mfs:
        logger.error(
            {
                'action': 'web_app_feature_settings_mobile_phone_1_otp_not_found',
                'message': 'Mobile feature setting mobile_phone_1_otp is not found',
            }
        )
        data = {
            "success": False,
            "content": {
                "active": False,
                "message": "Maaf, ada kesalahan di sistem kami. Silakan klik 'Coba Lagi' "
                           "untuk proses validasi ulang kode OTP kamu, ya.",
            },
        }
        return data
    if not mfs.is_active:
        logger.error(
            {
                'action': 'web_app_feature_settings_mobile_phone_1_otp_not_active',
                'message': 'Mobile feature setting mobile_phone_1_otp is not active',
            }
        )

        data = {
            "success": True,
            "content": {
                "active": mfs.is_active,
                "parameters": mfs.parameters,
                "message": "Maaf, ada kesalahan di sistem kami. Silakan klik 'Coba Lagi' "
                           "untuk proses validasi ulang kode OTP kamu, ya.",
            },
        }
        return data

    otp_token = data.get('otp')
    phone_number = data.get('phone_number')

    pii_filter_dict = generate_pii_filter_query_partnership(
        OtpRequest, {'phone_number': phone_number}
    )
    otp_data = OtpRequest.objects.filter(
        otp_token=otp_token,
        is_used=False,
        action_type=SessionTokenAction.PHONE_REGISTER,
        **pii_filter_dict
    ).last()
    data = {
        "success": False,
        "content": {
            "message": "Kode verifikasi tidak valid",
        },
    }
    if not otp_data:
        return data

    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    valid_token = hotp.verify(otp_token, int(otp_data.request_id))
    if not valid_token:
        return data

    if not otp_data.is_active:
        data = {
            "success": False,
            "content": {
                "message": "Kode verifikasi kadaluarsa",
            },
        }
        return data

    otp_data.is_used = True
    otp_data.save()
    data = {
        "success": True,
        "content": {
            "active": mfs.is_active,
            "message": "Kode verifikasi berhasil diverifikasi",
        },
    }
    return data


def store_account_property_mf_partnership(application: Application, set_limit: int) -> None:
    is_proven = get_is_proven()

    input_params = dict(
        account=application.account,
        pgood=0.0,
        p0=0.0,
        is_salaried=get_salaried(application.job_type),
        is_proven=is_proven,
        is_premium_area=is_inside_premium_area(application),
        proven_threshold=get_proven_threshold(set_limit),
        voice_recording=get_voice_recording(is_proven),
        concurrency=True,
    )

    account_property = AccountProperty.objects.create(**input_params)

    # create history
    store_account_property_history(input_params, account_property)


def generate_csv_for_new_merchant(
    partnership_applications: PartnershipApplicationData,
    tempdir: str
) -> str:
    now_time = timezone.localtime(timezone.now())
    file_name = "new_merchant_{}.csv".format(now_time.strftime("%Y_%m_%d"))
    header = ['application_xid', 'nik', 'email', 'full_name', 'application_status']

    applications_update_list = []
    temp_dir = tempdir.path
    try:
        file_path = os.path.join(temp_dir, file_name)
        with open(file_path, "w") as csvfile:
            cr = csv.writer(csvfile)
            cr.writerow(header)
            for partnership_application in partnership_applications.iterator():
                # Update partnership_application mark as sended
                partnership_application.is_sended_to_email = True
                applications_update_list.append(partnership_application)
                # Create Row Csv
                cr.writerow([
                    partnership_application.application.application_xid,
                    partnership_application.partnership_customer_data.nik,
                    partnership_application.partnership_customer_data.email,
                    partnership_application.fullname,
                    'Approved'
                ])
        csvfile.close()
    except ValueError as error:
        raise JuloException(error)

    with transaction.atomic():
        bulk_update(applications_update_list, update_fields=['is_sended_to_email'], batch_size=100)

    return file_name, file_path, temp_dir


def process_upload_document(document_file: File, document, data):
    document_file.seek(0)
    document_bytes = document_file.read()
    document_remote_filepath = "cust_{}/application_{}/{}_{}{}".format(
        data['customer_id'], document.application_xid, data['type'],
        document.id, data['extension']
    )
    upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, document_bytes, document_remote_filepath)
    document.url = document_remote_filepath
    document.save()


def process_upload_file(data, application):
    try:
        """
        First we will upload both images(ktp, selfie) and
        documents (company_photo, financial_document, cashflow_report, other_document, nib) to
        image table. Documents will be stored on document table also.
        After uploading image we will update the url field in image table
        After uploading documents we will update the url field in document table
        and delete the data from image table.  Documents are added in image table first
        because to prevent the error no such directory or file in /tmp folder
        """
        file_name = data['file'].name
        image = Image.objects.create(image_type=data['type'],
                                     image_source=application.id)
        if data['type'] in {'ktp', 'selfie'}:
            process_image_upload(image, image_file=data['file'], suffix=data['file_name'])
            image.refresh_from_db()
            response = {
                "url": image.image_url_api,
                "id": str(image.id) + '_img',
                "file_name": file_name
            }
        else:
            document = Document.objects.create(document_source=application.id,
                                               document_type=data['type'],
                                               filename=file_name,
                                               application_xid=application.application_xid)
            data['customer_id'] = application.customer_id
            process_upload_document(data['file'], document, data)
            document.refresh_from_db()
            response = {
                "url": document.document_url,
                "id": document.id,
                "file_name": file_name

            }
        return success_response_web_app(data=response)

    except Exception as e:
        return error_response_web_app(status=status.HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))


def check_image_upload(application_id) -> Tuple[bool, Dict]:
    get_images = Image.objects.filter(
        image_type__in={'ktp', 'selfie'},
        image_source=application_id,
        image_status=Image.CURRENT,
    )

    if not get_images:
        field_validation_errors = {"ktp": ["ktp diperlukan"], "selfie": ["selfie diperlukan"]}
        return False, field_validation_errors

    if get_images and len(get_images) < 2:
        field_validation_errors = {}
        for image in get_images:
            field_validation_errors.update(
                {image.image_type: ["{} diperlukan".format(image.image_type)]}
            )

        return False, field_validation_errors

    return True, None


def check_document_upload(application_id) -> Tuple[bool, Dict]:
    get_documents = Document.objects.filter(
        document_type__in=DOCUMENT_TYPE,
        document_source=application_id
    )

    if not get_documents:
        field_validation_errors = {}
        field_validation_errors = {
            "nib": ["nib diperlukan"],
            "financial_document": ["financial_document diperlukan"],
            "company_photo": ["company_photo diperlukan"],
            "cashflow_report": ["cashflow_report diperlukan"],
        }
        return False, field_validation_errors

    if get_documents and len(get_documents) < 2:
        field_validation_errors = {}
        for document in get_documents:
            field_validation_errors.update(
                {document.image_type: ["{} diperlukan".format(document.document_type)]}
            )

        return False, field_validation_errors

    return True, None


def update_application_reject_reason(application_id, reason_detail):
    partnership_application_data = PartnershipApplicationData.objects.filter(
        application_id=application_id).last()
    if partnership_application_data:
        reject_reason = partnership_application_data.reject_reason
        if not reject_reason:
            reject_reason = []

        reject_reason.append(reason_detail)
        partnership_application_data.update_safely(reject_reason=reject_reason)


def process_reset_password_request(email: str) -> Dict:
    from juloserver.merchant_financing.web_app.tasks import web_app_send_reset_password_email

    pii_filter_dict = generate_pii_filter_query_partnership(
        PartnershipCustomerData, {'email': email}
    )
    partnership_customer_data = PartnershipCustomerData.objects.filter(**pii_filter_dict).last()

    if not partnership_customer_data:
        logger.error(
            {
                'action': 'web_app_reset_password',
                'message': 'failed get PartnershipCustomerData from email',
            }
        )
        data = {
            "success": False,
            "message": "Maaf, ada kesalahan di sistem kami. "
                       "Silakan Coba Lagi Beberapa saat lagi"
        }
        return data

    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partnership_customer_data.partner,
        customer_xid=None,
        fields_param=['name'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )

    password_type = 'password'
    new_key_needed = False
    customer_password_change_service = password_services.CustomerPinChangeService()
    customer = partnership_customer_data.customer
    partner = detokenize_partner.name

    if not customer:
        logger.error(
            {
                'action': 'web_app_reset_password',
                'message': 'failed get customer data',
            }
        )
        data = {
            "success": False,
            "message": "Maaf, ada kesalahan di sistem kami. "
                       "Silakan Coba Lagi Beberapa saat lagi"
        }
        return data

    if customer.reset_password_exp_date is None:
        new_key_needed = True
    else:
        if customer.has_resetkey_expired():
            new_key_needed = True
        elif not customer_password_change_service.check_key(
            customer.reset_password_key
        ):
            new_key_needed = True

    if new_key_needed:
        reset_pin_key = generate_email_key(email)
        customer.reset_password_key = reset_pin_key
        reset_pin_exp_date = datetime.now() + timedelta(minutes=30)
        customer.reset_password_exp_date = reset_pin_exp_date
        customer.save()
        # treat the reset password like a reset pin
        customer_pin = customer.user.pin
        customer_password_change_service.init_customer_pin_change(
            email=email,
            phone_number=None,
            expired_time=reset_pin_exp_date,
            customer_pin=customer_pin,
            change_source='Forget PIN',
            reset_key=reset_pin_key,
        )
        logger.info(
            {
                'action': 'web_app_reset_password',
                'status': 'just_generated_reset_%s' % password_type,
                'email': email,
                'phone_number': None,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
                'reset_%s_exp_date' % password_type: reset_pin_exp_date,
            }
        )

    reset_pin_key = customer.reset_password_key
    web_app_send_reset_password_email.delay(email, partner, reset_pin_key)

    data = {
        "success": True,
        "message": "Pengajuan Ganti Kata Sandi Terkirim"
    }
    return data


def process_confirm_new_password_web_app(
    customer: Customer,
    email: str,
    password: str,
    reset_key: str,
) -> None:
    user = customer.user
    user.set_password(password)
    user.save()

    # remove_reset_key customer
    customer.reset_password_key = None
    customer.reset_password_exp_date = None
    customer.save()

    customer_pin = user.pin
    verify_password_process = password_services.VerifyPinProcess()
    verify_password_process.capture_pin_reset(customer_pin, PinResetReason.FORGET_PIN)
    verify_password_process.reset_attempt_pin(customer_pin)
    verify_password_process.reset_pin_blocked(customer_pin)

    customer_password_change_service = password_services.CustomerPinChangeService()
    customer_password_change_service.update_email_status_to_success(reset_key, user.password)


def get_fdc_data_for_application(application_id):
    data = []
    with connections['bureau_db'].cursor() as cursor:
        query = "select kualitas_pinjaman, count(*)" \
                " from ops.fdc_inquiry fi" \
                " left join ops.fdc_inquiry_loan fil on fi.fdc_inquiry_id = fil.fdc_inquiry_id" \
                " where application_id = {} and"\
                " fi.inquiry_reason = '1 - Applying loan via Platform'" \
                " group by fil.kualitas_pinjaman".format(application_id)
        cursor.execute(query)
        for detail in cursor.fetchall():
            inquiry_reason = None
            if detail[0] == FDCFieldsName.TIDAK_LANCAR:
                inquiry_reason = {
                    "name": "tidak_lancar",
                    "label": "Tidak Lancar"
                }
            elif detail[0] in {FDCFieldsName.MACET, 'Macet ( >90 )'}:
                inquiry_reason = {
                    "name": "macet",
                    "label": "Macet"
                }
            elif detail[0] == FDCFieldsName.LANCAR:
                inquiry_reason = {
                    "name": "lancar",
                    "label": "Lancar"
                }

            if inquiry_reason:
                if detail[1] > 0 and detail[0]:
                    inquiry_reason.update({"count": detail[1]})

                data.append(inquiry_reason)

    return data


def run_mf_web_app_register_upload_csv(
    customer_data: Dict,
    partner: Partner
) -> Tuple[bool, str]:
    """
    This function To do:
    - Create User
    - Create Application if not exists and reapply
    - Create Customer if not exists, Update Customer if exists (Reapply)
    - Create Partnership Customer Data
    - Create Partnership Application Data
    - Move Application status 0 -> 100 -> 105 -> 121
    """
    is_success = True
    message = ''
    try:
        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )

        with transaction.atomic():
            # Create Partnership Customer Data
            data = {
                'nik': customer_data['nik_number'],
                'email': customer_data['email_borrower'],
                'partner': partner,
                'phone_number': customer_data['handphone_number'],
                'npwp': customer_data['npwp'],
                'certificate_number': customer_data['certificate_number'],
                'certificate_date': customer_data['certificate_date'],
                'user_type': customer_data['user_type'],
            }

            pii_nik_filter_dict = generate_pii_filter_query_partnership(
                Customer, {'nik': customer_data['nik_number']}
            )
            old_customer_id = (
                Customer.objects.filter(**pii_nik_filter_dict).values_list('id', flat=True).last()
            )
            if old_customer_id:
                pii_partner_filter_dict = generate_pii_filter_query_partnership(
                    Partner, {'name': PartnerConstant.AXIATA_PARTNER}
                )
                partner_old_axiata = Partner.objects.filter(**pii_partner_filter_dict).last()

                existed_axiata_application = Application.objects.filter(
                    customer_id=old_customer_id,
                    partner=partner_old_axiata,
                    application_status_id=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                ).exists()
                if existed_axiata_application:
                    data['customer_id_old'] = old_customer_id

            partnership_customer_data = PartnershipCustomerData.objects.create(**data)
            # temporary nik user
            temp_nik = create_temporary_partnership_user_nik(partnership_customer_data.nik)
            user_email = create_partnership_email(
                partnership_customer_data.nik, detokenize_partner.name
            )
            user = User(username=temp_nik, email=user_email)
            password = User.objects.make_random_password()
            user.set_password(password)
            user.save()

            # We still use existing flow for forgot password
            customer_password_service = password_services.CustomerPinService()
            customer_password_service.init_customer_pin(user)

            workflow = Workflow.objects.get(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
            partnership_product_line = ProductLine.objects.get(
                pk=ProductLineCodes.AXIATA_WEB
            )
            web_version = "0.0.1"
            masked_phone_no = masking_axiata_web_app_phone_number(
                customer_data['handphone_number']
            )
            monthly_income = int(customer_data['total_revenue_per_year']) / 12
            # create customer
            customer = Customer.objects.create(
                user=user,
                email=user_email,
                appsflyer_device_id=None,
                advertising_id=None,
                mother_maiden_name=None,
                phone=masked_phone_no,
                dob=customer_data['date_of_birth'],
                fullname=customer_data['customer_name'],
                gender=customer_data['gender'],
            )
            application = Application.objects.create(
                customer=customer,
                email=user_email,
                partner=partnership_customer_data.partner,
                workflow=workflow,
                product_line=partnership_product_line,
                web_version=web_version,
                fullname=customer_data['customer_name'],
                birth_place=customer_data['place_of_birth'],
                dob=customer_data['date_of_birth'],
                gender=customer_data['gender'],
                address_street_num=customer_data['address'],
                address_provinsi=customer_data['provinsi'],
                address_kabupaten=customer_data['kabupaten'],
                address_kodepos=customer_data['zipcode'],
                marital_status=customer_data['marital_status'],
                mobile_phone_1=masked_phone_no,
                last_education=customer_data['education'],
                monthly_income=monthly_income,
                company_name=customer_data['company_name'],
                job_type='Pengusaha',
                job_industry=customer_data['business_category'],
                kin_name=customer_data['kin_name'],
                kin_mobile_phone=customer_data['kin_mobile_phone'],
                home_status=customer_data['home_status'],
            )

            # User NIK
            user_nik = create_partnership_nik(application.id)

            # Update user, customer, application nik
            user.username = user_nik
            user.save(update_fields=['username'])

            customer.nik = user_nik
            customer.save(update_fields=['nik'])

            application.ktp = user_nik
            application.save(update_fields=['ktp'])

            # Update customer data
            partnership_customer_data.customer = customer
            partnership_customer_data.application = application
            partnership_customer_data.save(update_fields=['customer', 'application'])
            PartnershipApplicationData.objects.create(
                partnership_customer_data=partnership_customer_data,
                application=application,
                email=customer_data['email_borrower'],
                web_version=web_version,
                fullname=customer_data['customer_name'],
                birth_place=customer_data['place_of_birth'],
                dob=customer_data['date_of_birth'],
                gender=customer_data['gender'],
                address_street_num=customer_data['address'],
                address_provinsi=customer_data['provinsi'],
                address_kabupaten=customer_data['kabupaten'],
                address_kodepos=customer_data['zipcode'],
                marital_status=customer_data['marital_status'],
                mobile_phone_1=customer_data['handphone_number'],
                job_type='Pengusaha',
                total_revenue_per_year=customer_data['total_revenue_per_year'],
                job_industry=customer_data['business_category'],
                company_name=customer_data['company_name'],
                last_education=customer_data['education'],
                proposed_limit=customer_data['proposed_limit'],
                product_line=customer_data['product_line'],
                business_category=customer_data['business_category'],
                nib=customer_data['nib_number'],
                kin_name=customer_data['kin_name'],
                kin_mobile_phone=customer_data['kin_mobile_phone'],
                home_status=customer_data['home_status'],
                business_entity=customer_data['business_entity'],
            )

            # Set application STATUS to 100
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='system_triggered'
            )
            validate_step(
                application,
                ApplicationStatusCodes.FORM_CREATED
            )
            populate_zipcode(application.id)
            # set application status to 105 and will be automated to 121
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_PARTIAL,
                change_reason='system_triggered'
            )
            validate_step(
                application, ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            )

            message = 'Success Create Application'
            return is_success, message
    except Exception as error:
        logger.error(
            {
                'action': 'run_mf_web_app_register_upload_csv',
                'message': str(error),
            }
        )
        sentry_client.captureException()
        is_success = False
        message = 'Failed Register User Application'
        return is_success, message


def validate_step(application: Application, status: int) -> None:
    application.refresh_from_db()
    if application.application_status_id != status:
        msg = 'Failed change status, application ID {} status {}'.format(
            application.id, application.application_status_id
        )
        raise JuloException(msg)


def get_axiata_loan_agreement_template(loan, application, is_new_digisign=False) -> bool:
    partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).last()
    if not partner_loan_request:
        err_message = 'PartnerLoanRequest not found'
        raise ValueError(err_message)

    product_name = PartnerConstant.AXIATA_PARTNER_SCF
    if partner_loan_request.loan_type.upper() == 'IF':
        product_name = PartnerConstant.AXIATA_PARTNER_IF

    html_template = SphpTemplate.objects.filter(product_name=product_name).last()
    if not html_template:
        err_message = 'SphpTemplate not found'
        raise ValueError(err_message)

    account_limit = AccountLimit.objects.filter(account=application.account).last()
    if not account_limit:
        err_message = 'AccountLimit not found'
        raise ValueError(err_message)

    partnership_application_data = PartnershipApplicationData.objects.filter(
        application_id=loan.application_id2
    ).last()
    if not partnership_application_data:
        err_message = 'PartnershipApplicationData not found'
        raise ValueError(err_message)

    distributor = PartnershipDistributor.objects.filter(
        id=partner_loan_request.partnership_distributor.id
    ).last()
    if not distributor:
        err_message = 'PartnershipDistributor not found'
        raise ValueError(err_message)

    payment_method = PaymentMethod.objects.filter(
        customer_id=application.customer,
        is_shown=True,
        payment_method_name=PAYMENT_METHOD_NAME_BCA,
    ).last()
    if not payment_method:
        raise ValueError('PaymentMethod not found')

    content_skrtp = get_merchant_skrtp_agreement(
        loan,
        application,
        partner_loan_request,
        html_template,
        account_limit,
        partnership_application_data,
        distributor,
        payment_method,
        is_new_digisign,
    )

    return content_skrtp


def axiata_update_late_fee_amount(payment_id: int):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)

        if payment.status in PaymentStatusCodes.paid_status_codes():
            return

        if payment.late_fee_applied >= AXIATA_MAX_LATE_FEE_APPLIED:
            return
        today = date.today()
        dpd = (today - payment.due_date).days
        if dpd <= 0:
            return
        due_amount_before = payment.due_amount
        installment_amount = payment.installment_principal - payment.paid_principal

        product_code = Loan.objects.filter(
            id=payment.loan_id
        ).values_list('product__product_code', flat=True).first()
        late_fee_pct = ProductLookup.objects.filter(
            product_line__product_line_code=ProductLineCodes.AXIATA_WEB,
            product_code=product_code
        ).values_list('late_fee_pct', flat=True).first()
        late_fee_rate = late_fee_pct / 30

        if dpd > AXIATA_MAX_LATE_FEE_APPLIED:
            return
        raw_late_fee = installment_amount * late_fee_rate
        rounded_late_fee = int(round_half_up(raw_late_fee))
        if rounded_late_fee <= 0:
            return

        event_payment = rounded_late_fee
        payment.apply_late_fee(event_payment)
        payment_event = PaymentEvent.objects.create(
            payment=payment,
            event_payment=-event_payment,
            event_due_amount=due_amount_before,
            event_date=today,
            event_type='late_fee',
        )
        account_payment = AccountPayment.objects.select_for_update().get(
            pk=payment.account_payment_id
        )
        account_payment.update_late_fee_amount(payment_event.event_payment)
        account_transaction, created = AccountTransaction.objects.get_or_create(
            account=account_payment.account,
            transaction_date=payment_event.event_date,
            transaction_type='late_fee',
            defaults={
                'transaction_amount': 0,
                'towards_latefee': 0,
                'towards_principal': 0,
                'towards_interest': 0,
                'accounting_date': payment_event.event_date,
            },
        )
        if created:
            account_transaction.transaction_amount = payment_event.event_payment
            account_transaction.towards_latefee = payment_event.event_payment
        else:
            account_transaction.transaction_amount += payment_event.event_payment
            account_transaction.towards_latefee += payment_event.event_payment
        account_transaction.save(update_fields=['transaction_amount', 'towards_latefee'])
        payment_event.account_transaction = account_transaction
        payment_event.save(update_fields=['account_transaction'])


def validate_and_insert_distributor_data_v2(data_reader, partnership_user, is_precheck=True):
    invalid_rows = {}
    partnership_distributors_list = []
    is_success_all = True

    # checking row value
    row_number = 1
    success_row = 0
    fail_row = 0
    partner = partnership_user.partner
    partnership_flow_flag = (
        PartnershipFlowFlag.objects.filter(
            partner=partner,
            name=PartnershipFlag.PAYMENT_GATEWAY_SERVICE,
        )
        .values_list('configs', flat=True)
        .last()
    )
    is_payment_gateway_service = False
    if partnership_flow_flag and partnership_flow_flag.get('payment_gateway_service', True):
        is_payment_gateway_service = True

    for data in data_reader:
        list_column_errors = []
        formated_data = distributor_format_data(data)
        distributor_code = formated_data.get('distributor_code')
        distributor_name = formated_data.get('distributor_name')
        distributor_bank_name = formated_data.get('distributor_bank_name')
        bank_account = formated_data.get('bank_account')
        bank_name = formated_data.get('bank_name')
        bank_code = formated_data.get('bank_code')
        is_valid_bank = False
        bank = None
        # DISTRIBUTOR_CODE validation
        if not distributor_code:
            list_column_errors.append('distributor_code: tidak boleh kosong')

        if distributor_code and not distributor_code.isdigit():
            list_column_errors.append('distributor_code: harus menggunakan angka')
        else:
            is_distributor_exists = PartnershipDistributor.objects.filter(
                distributor_id=distributor_code, is_deleted=False
            ).exists()
            if is_distributor_exists:
                list_column_errors.append('distributor_code: telah terdaftar')
        if row_number > 1:
            # Check if the current value is already in the list of seen values
            # because list starts from 0 so we reduced with 2 for get value rows
            last_row = row_number - 2
            check_distributor_code_last_row = data_reader[last_row].get('distributor code')
            if check_distributor_code_last_row == distributor_code:
                list_column_errors.append('distributor_code: harus unique')

        # DISTRIBUTOR_NAME validation
        if not distributor_name:
            list_column_errors.append('distributor_name: tidak boleh kosong')

        # DISTRIBUTOR_BANK_NAME validation
        if not distributor_bank_name:
            list_column_errors.append('distributor_bank_name: tidak boleh kosong')

        # BANK_ACCOUNT validation
        if not bank_account:
            list_column_errors.append('bank_account: tidak boleh kosong')

        if bank_account and not bank_account.isdigit():
            list_column_errors.append('bank_account: format tidak sesuai, harus mengggunakan angka')

        # BANK_NAME validation
        if not bank_name:
            list_column_errors.append('bank_name: tidak boleh kosong')

        if bank_name:
            if is_payment_gateway_service:
                bank = BankManager.get_by_name_or_none(bank_name)
                if not bank:
                    list_column_errors.append('bank_name: nama Bank tidak ditemukan')
                is_valid_bank = True
            else:
                bank = (
                    Bank.objects.values('xfers_bank_code', 'id').filter(bank_name=bank_name).first()
                )
                if not bank:
                    list_column_errors.append('bank_name: nama Bank tidak ditemukan')
                is_valid_bank = True

        # BANK_CODE validation
        if not bank_code:
            list_column_errors.append('bank_code: tidak boleh kosong')

        if bank_code and not bank_code.isdigit():
            list_column_errors.append('bank_code: format tidak sesuai, harus mengggunakan angka')

        # Process Bank Name Validation xfers
        # If not precheck process we skip bank validation
        if (
            distributor_code
            and distributor_code.isdigit()
            and bank_account
            and bank_account.isdigit()
            and distributor_bank_name
            and is_valid_bank
            and bank
            and is_precheck
        ):
            bank_account_services = mf_services.BankAccount()
            if is_payment_gateway_service:
                response = bank_account_services.validate_bank_account(
                    bank_id=bank.id,
                    bank_code=bank.bank_code,
                    bank_account_number=bank_account,
                    phone_number="08111111111",
                    name_in_bank=distributor_bank_name,
                )
                if response['status'] != NameBankValidationStatus.SUCCESS:
                    list_column_errors.append('bank_name: {}'.format(response['reason']))
            else:
                response = bank_account_services.inquiry_bank_account(
                    bank_code=bank['xfers_bank_code'],
                    bank_account_number=bank_account,
                    phone_number="08111111111",
                    name_in_bank=distributor_bank_name,
                )
                if response['status'] == NameBankValidationStatus.NAME_INVALID:
                    list_column_errors.append(
                        'bank_name: gagal melakukan validasi, nama tidak sesuai'
                    )
                elif response['status'] == NameBankValidationStatus.FAILED:
                    list_column_errors.append('bank_name: gagal melakukan validasi')
                elif response['status'] != NameBankValidationStatus.SUCCESS and response[
                    'status'
                ] not in {NameBankValidationStatus.NAME_INVALID, NameBankValidationStatus.SUCCESS}:
                    list_column_errors.append(
                        'bank_name: terjadi kesalahan sistem,gagal melakukan validasi'
                    )
                    logger.error(
                        {
                            'action': 'validate_and_insert_distributor_data_v2',
                            'status': response['status'],
                            'error': response['reason'],
                        }
                    )
                elif response['validated_name'].lower() != distributor_bank_name.lower():
                    list_column_errors.append('bank_name: nama pemilik rekening tidak sesuai')
        else:
            # We Skip save data, if precheck is TRUE
            if not is_precheck:
                user_bank_code = None
                bank_id = None
                if is_payment_gateway_service:
                    user_bank_code = bank.bank_code
                    bank_id = bank.id
                else:
                    user_bank_code = bank['xfers_bank_code']
                    bank_id = bank['id']

                name_bank_validation = (
                    NameBankValidation.objects.filter(
                        bank_code=user_bank_code,
                        account_number=bank_account,
                        name_in_bank=distributor_bank_name,
                        validation_status=NameBankValidationStatus.SUCCESS,
                    )
                    .values_list('id', flat=True)
                    .last()
                )
                # if name_bank_validation not found we will skip process save data
                # and return error
                if name_bank_validation:
                    partnership_distributor_data = {
                        'distributor_id': distributor_code,
                        'distributor_name': distributor_name,
                        'distributor_bank_account_number': bank_account,
                        'distributor_bank_account_name': distributor_bank_name,
                        'bank_code': bank_code,
                        'bank_name': bank_name,
                        'partner': partner,
                        'name_bank_validation_id': name_bank_validation,
                        'bank_id': bank_id,
                        'created_by_user_id': partnership_user.user_id,
                    }
                    partnership_distributors_list.append(partnership_distributor_data)
                else:
                    list_column_errors.append('bank_name: nama pemilik rekening tidak valid')

        if list_column_errors:
            result_errors = ', '.join(list_column_errors)
            error_details = {'Baris nomor {}'.format(row_number): [result_errors]}
            invalid_rows.update(error_details)
            is_success_all = False
            fail_row += 1
        else:
            success_row += 1
        row_number += 1

    """
        If 1 of 2 data inside the row is invalid we cancel to save the data
        We only save data if all data is valid
    """
    if is_success_all:
        meta = {
            "success_row": success_row,
            "fail_row": fail_row,
        }
        if not is_precheck and partnership_distributors_list:
            # We Skip save data, if precheck is TRUE
            try:
                with transaction.atomic():
                    bank_account_category = BankAccountCategory.objects.filter(
                        category=BankAccountCategoryConst.SELF
                    ).last()
                    for distributor_data in partnership_distributors_list:
                        partner = distributor_data['partner']
                        distributor_id = distributor_data['distributor_id']
                        distributor_name = distributor_data['distributor_name']
                        distributor_bank_account_number = distributor_data[
                            'distributor_bank_account_number'
                        ]
                        distributor_bank_account_name = distributor_data[
                            'distributor_bank_account_name'
                        ]
                        bank_code = distributor_data['bank_code']
                        bank_name = distributor_data['bank_name']
                        name_bank_validation_id = distributor_data['name_bank_validation_id']
                        bank_id = distributor_data['bank_id']
                        partnership_distributor = PartnershipDistributor.objects.create(
                            distributor_id=distributor_id,
                            distributor_name=distributor_name,
                            distributor_bank_account_number=distributor_bank_account_number,
                            distributor_bank_account_name=distributor_bank_account_name,
                            bank_code=bank_code,
                            bank_name=bank_name,
                            partner=partner,
                            is_deleted=False,
                            created_by_user_id=partnership_user.user_id,
                        )
                        """
                            we genereta user and customer to create bank account destination
                            for distributor
                        """
                        # generate random username with combination
                        # distributor_id + partner id + current date
                        current_date = datetime.now()
                        timestamp = int(time.mktime(current_date.timetuple()))
                        username = "{}_{}_{}".format(distributor_id, partner.id, timestamp)
                        user_email = "{}{}".format(username, PARTNERSHIP_SUFFIX_EMAIL)
                        user = User.objects.create_user(username=username, email=user_email)
                        customer = Customer.objects.create(
                            user=user, fullname=distributor_name, email=user_email
                        )
                        bank_account_destination = BankAccountDestination.objects.create(
                            bank_account_category=bank_account_category,
                            customer=customer,
                            bank_id=bank_id,
                            account_number=distributor_bank_account_number,
                            name_bank_validation_id=name_bank_validation_id,
                        )
                        partnership_distributor.bank_account_destination_id = (
                            bank_account_destination.id
                        )
                        partnership_distributor.save(update_fields=['bank_account_destination_id'])
            except Exception as error:
                logger.error(
                    {
                        "action": "validate_and_insert_distributor_data_v2",
                        "error": str(error),
                    }
                )
                return mf_error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
                )
        return mf_success_response(meta=meta)

    meta = {
        "success_row": success_row,
        "fail_row": fail_row,
    }
    return mf_error_response(
        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
        errors=invalid_rows,
        meta=meta,
    )


def process_merchant_upload(
    upload_async_state: UploadAsyncState, partner: Partner, created_by_user_id: int
):
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    upload_file = upload_async_state.file
    freader = io.StringIO(upload_file.read().decode('utf-8'))
    reader = csv.DictReader(freader, delimiter=',')
    is_success_all = True
    local_file_path = upload_async_state.file.path
    # Process read and validate csv data
    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            header = list(MF_STANDARD_REGISTER_UPLOAD_HEADER)
            mapping_fields = list(MF_COMPLIANCE_REGISTER_UPLOAD_MAPPING_FIELDS)
            has_uploaded_file = any(field_name == "File Upload" for field_name in reader.fieldnames)
            if has_uploaded_file:
                header += ADDITIONAL_MF_STANDARD_REGISTER_UPLOAD_HEADER
                mapping_fields += ADDITIONAL_MF_COMPLIANCE_REGISTER_UPLOAD_MAPPING_FIELDS

            header.append("note")  # add note column on header
            write.writerow(header)
            for row in reader:
                formated_data = {}
                for raw_field, formated_field in mapping_fields:
                    formated_data[formated_field] = row.get(raw_field)

                register_serializer = MfMerchantRegisterSerializer(
                    data=formated_data, context={'partner_name': detokenize_partner.name}
                )

                # construct new csv row content
                row_content = [
                    formated_data.get("proposed_limit", 'null'),
                    formated_data.get("distributor_code", 'null'),
                    formated_data.get("fullname", 'null'),
                    formated_data.get("mobile_phone_1", 'null'),
                    formated_data.get("marital_status", 'null'),
                    formated_data.get("gender", 'null'),
                    formated_data.get("birth_place", 'null'),
                    formated_data.get("dob", 'null'),
                    formated_data.get("home_status", 'null'),
                    formated_data.get("spouse_name", 'null'),
                    formated_data.get("spouse_mobile_phone", 'null'),
                    formated_data.get("kin_name", 'null'),
                    formated_data.get("kin_mobile_phone", 'null'),
                    formated_data.get("address_provinsi", 'null'),
                    formated_data.get("address_kabupaten", 'null'),
                    formated_data.get("address_kelurahan", 'null'),
                    formated_data.get("address_kecamatan", 'null'),
                    formated_data.get("address_kodepos", 'null'),
                    formated_data.get("address_street_num", 'null'),
                    formated_data.get("bank_name", 'null'),
                    formated_data.get("bank_account_number", 'null'),
                    formated_data.get("loan_purpose", 'null'),
                    formated_data.get("monthly_income", 'null'),
                    formated_data.get("monthly_expenses", 'null'),
                    formated_data.get("pegawai", 'null'),
                    formated_data.get("business_type", 'null'),
                    formated_data.get("ktp", 'null'),
                    formated_data.get("last_education", 'null'),
                    formated_data.get("npwp", 'null'),
                    formated_data.get("email", 'null'),
                    formated_data.get("user_type", 'null'),
                    formated_data.get("business_entity", 'null'),
                    formated_data.get("certificate_number", 'null'),
                    formated_data.get("certificate_date", 'null'),
                ]
                if has_uploaded_file:
                    row_content += [
                        formated_data.get(MFComplianceRegisterUpload.FILE_UPLOAD_KEY, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.KTP_IMAGE, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.SELFIE_KTP_IMAGE, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.AGENT_MERCHANT_IMAGE, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.NPWP_IMAGE, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.NIB_IMAGE, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE, 'null'),
                        formated_data.get(MFComplianceRegisterUpload.CASHFLOW_REPORT, 'null'),
                    ]

                if register_serializer.is_valid():
                    """
                    if data is valid, we create
                    - User
                    - Customer (masked email, nik, fullname)
                    - Application (masked email, nik, fullname)
                    - Create Partnership Customer Data
                    - Create Partnership Application Data
                    - Run Happy Path Flow 100
                    """
                    validated_data = dict(register_serializer.validated_data)

                    logger.info(
                        {
                            "action": "mf_standard_process_merchant_upload_service",
                            "validated_data": validated_data,
                        }
                    )

                    # Process register
                    is_success, message = mf_register_merchant_upload_csv(
                        merchant_data=validated_data,
                        partner=partner,
                        created_by_user_id=created_by_user_id,
                    )
                    if not is_success:
                        is_success_all = False

                    # Add notes
                    row_content.append(message)
                    write.writerow(row_content)
                else:
                    is_success_all = False

                    # Add error notes
                    row_content.append(register_serializer.errors)
                    write.writerow(row_content)

        # Process upload csv data to oss
        if file_path:
            local_file_path = file_path
        else:
            local_file_path = upload_async_state.file.path
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        dest_name = "mf_web_app/{}/{}".format(
            upload_async_state.id, file_name_elements[-1] + extension
        )
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

        if os.path.isfile(local_file_path):
            local_dir = os.path.dirname(local_file_path)
            upload_async_state.file.delete()
            if not file_path:
                os.rmdir(local_dir)

        upload_async_state.update_safely(url=dest_name)

    return is_success_all


def mf_register_merchant_upload_csv(
    merchant_data: Dict, partner: Partner, created_by_user_id: int
) -> Tuple[bool, str]:
    """Function to create merchant:
    - User (masked email, nik)
    - Customer (masked email, nik, fullname)
    - Application (masked email, nik, fullname)
    - Create Partnership Customer Data
    - Create Partnership Application Data
    - Run Happy Path Flow 100
    """
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    # temporary nik user, email and phone
    prefix = PARTNERSHIP_PREFIX_IDENTIFIER
    product_code = ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT

    temp_nik = '{}{}{}'.format(prefix, product_code, merchant_data.get("ktp"))
    user_email = '{}_{}{}'.format(
        merchant_data.get("ktp"), detokenize_partner.name, PARTNERSHIP_SUFFIX_EMAIL
    )
    masked_phone = '{}{}'.format(product_code, merchant_data['mobile_phone_1'])

    workflow = Workflow.objects.get(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
    partnership_product_line = ProductLine.objects.get(product_line_code=product_code)
    web_version = "0.2.0"

    # Check if email/phone exists on partnership customer data
    pii_filter_partnership_customer_data_dict = generate_pii_filter_query_partnership(
        PartnershipCustomerData,
        {
            'phone_number': merchant_data.get('mobile_phone_1'),
            'nik': merchant_data.get('ktp'),
            'email': merchant_data.get('email'),
        },
    )
    existing_partnership_customer = PartnershipCustomerData.objects.filter(
        Q(partner_id=partner.id)
        & (
            Q(email=pii_filter_partnership_customer_data_dict.get('email'))
            | Q(nik=pii_filter_partnership_customer_data_dict.get('ktp'))
            | Q(phone_number=pii_filter_partnership_customer_data_dict.get('mobile_phone_1'))
        )
    ).exists()
    if existing_partnership_customer:
        return False, "No KTP/Alamat email/No HP Borrower sudah terdaftar"

    try:
        with transaction.atomic():
            # create user
            user = User(username=temp_nik, email=user_email)
            password = User.objects.make_random_password()
            user.set_password(password)
            user.save()

            # create customer
            customer = Customer.objects.create(
                user=user,
                email=user_email,
                appsflyer_device_id=None,
                advertising_id=None,
                mother_maiden_name=None,
                phone=masked_phone,
                dob=merchant_data.get('dob'),
                fullname=merchant_data.get('fullname'),
                gender=merchant_data.get('gender'),
            )

            # create application
            application_xid_generated = partnership_generate_xid(
                table_source=XidIdentifier.APPLICATION.value,
                method=PartnershipXIDGenerationMethod.DATETIME.value,
            )

            application = Application.objects.create(
                application_xid=application_xid_generated,
                customer=customer,
                email=user_email,
                partner=partner,
                workflow=workflow,
                product_line=partnership_product_line,
                web_version=web_version,
                fullname=merchant_data.get('fullname'),
                mobile_phone_1=masked_phone,
                birth_place=merchant_data.get('birth_place'),
                dob=merchant_data.get('dob'),
                gender=merchant_data.get('gender'),
                last_education=merchant_data.get('last_education'),
                home_status=merchant_data.get('home_status'),
                address_street_num=merchant_data.get('address_street_num'),
                address_provinsi=merchant_data.get('address_provinsi'),
                address_kabupaten=merchant_data.get('address_kabupaten'),
                address_kelurahan=merchant_data.get('address_kelurahan'),
                address_kecamatan=merchant_data.get('address_kecamatan'),
                address_kodepos=merchant_data.get('address_kodepos'),
                marital_status=merchant_data.get('marital_status'),
                spouse_name=merchant_data.get('spouse_name'),
                spouse_mobile_phone=merchant_data.get('spouse_mobile_phone'),
                kin_name=merchant_data.get('kin_name'),
                kin_mobile_phone=merchant_data.get('kin_mobile_phone'),
                bank_name=merchant_data.get('bank_name'),
                bank_account_number=merchant_data.get('bank_account_number'),
                monthly_income=merchant_data.get('monthly_income'),
                monthly_expenses=merchant_data.get('monthly_expenses'),
                job_type='Pengusaha',
                loan_purpose=merchant_data.get('loan_purpose'),
                number_of_employees=merchant_data.get('pegawai'),
            )

            name_bank_validation = NameBankValidation.objects.filter(
                account_number=merchant_data.get('bank_account_number'),
                mobile_phone=merchant_data.get('mobile_phone_1'),
                name_in_bank=merchant_data.get('fullname'),
            ).last()
            if name_bank_validation:
                application.name_bank_validation = name_bank_validation
                application.save(update_fields=['name_bank_validation'])
                #  create bank account destination
                category = BankAccountCategory.objects.get(category=BankAccountCategoryConst.SELF)
                bank = Bank.objects.get(bank_name__iexact=merchant_data['bank_name'])
                BankAccountDestination.objects.get_or_create(
                    bank_account_category=category,
                    customer=customer,
                    bank=bank,
                    account_number=merchant_data["bank_account_number"],
                    name_bank_validation=application.name_bank_validation,
                )

            # User NIK
            user_nik = '{}{}{}'.format(prefix, product_code, application.id)

            # Update user, customer, application nik
            user.username = user_nik
            user.save(update_fields=['username'])

            customer.nik = user_nik
            customer.save(update_fields=['nik'])

            application.ktp = user_nik
            application.save(update_fields=['ktp'])

            # Get old customer id
            old_customer_id = None
            old_application = (
                Application.objects.filter(
                    ktp=merchant_data.get('ktp'),
                    partner=partner,
                )
                .distinct('customer_id')
                .values('customer_id', 'ktp')
            )
            if old_application.exists():
                old_customer_id = old_application[0].get('customer_id')

            # create partnership customer data
            partnership_customer_data = PartnershipCustomerData.objects.create(
                nik=merchant_data.get('ktp'),
                email=merchant_data.get('email'),
                partner=partner,
                phone_number=merchant_data.get('mobile_phone_1'),
                customer=customer,
                application=application,
                npwp=merchant_data.get('npwp'),
                certificate_number=merchant_data.get('certificate_number'),
                certificate_date=merchant_data.get('certificate_date'),
                user_type=merchant_data.get('user_type'),
                customer_id_old=old_customer_id,
            )

            # create partnership application data
            PartnershipApplicationData.objects.create(
                partnership_customer_data=partnership_customer_data,
                application=application,
                email=merchant_data.get('email'),
                web_version=web_version,
                fullname=merchant_data.get('fullname'),
                mobile_phone_1=merchant_data.get('mobile_phone_1'),
                birth_place=merchant_data.get('birth_place'),
                dob=merchant_data.get('dob'),
                gender=merchant_data.get('gender'),
                last_education=merchant_data.get('last_education'),
                home_status=merchant_data.get('home_status'),
                address_street_num=merchant_data.get('address_street_num'),
                address_provinsi=merchant_data.get('address_provinsi'),
                address_kabupaten=merchant_data.get('address_kabupaten'),
                address_kelurahan=merchant_data.get('address_kelurahan'),
                address_kecamatan=merchant_data.get('address_kecamatan'),
                address_kodepos=merchant_data.get('address_kodepos'),
                marital_status=merchant_data.get('marital_status'),
                spouse_name=merchant_data.get('spouse_name'),
                spouse_mobile_phone=merchant_data.get('spouse_mobile_phone'),
                kin_name=merchant_data.get('kin_name'),
                kin_mobile_phone=merchant_data.get('kin_mobile_phone'),
                job_type='Pengusaha',
                monthly_income=merchant_data.get('monthly_income'),
                monthly_expenses=merchant_data.get('monthly_expenses'),
                business_type=merchant_data.get('business_type'),
                loan_purpose=merchant_data.get('loan_purpose'),
                bank_name=merchant_data.get('bank_name'),
                bank_account_number=merchant_data.get('bank_account_number'),
                proposed_limit=merchant_data.get('proposed_limit'),
                product_line=partnership_product_line,
                reject_reason={},
                business_entity=merchant_data.get('business_entity'),
            )

            # Set application STATUS to 100
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.FORM_CREATED,
                change_reason='system_triggered',
            )

            # upload image if the key = 'aktif'
            if (
                merchant_data.get(MFComplianceRegisterUpload.FILE_UPLOAD_KEY)
                and merchant_data.get(MFComplianceRegisterUpload.FILE_UPLOAD_KEY).strip().lower()
                == 'aktif'
            ):
                # having this variable to be tested on unit test
                ktp_image_path = merchant_data.get(MFComplianceRegisterUpload.KTP_IMAGE)
                selfie_ktp_image_path = merchant_data.get(
                    MFComplianceRegisterUpload.SELFIE_KTP_IMAGE
                )
                agent_merchant_image_path = merchant_data.get(
                    MFComplianceRegisterUpload.AGENT_MERCHANT_IMAGE
                )
                if not ktp_image_path or not selfie_ktp_image_path or not agent_merchant_image_path:
                    raise Exception('Foto KTP/Foto Selfie KTP/Foto Agent Merchant not found')

                application_id = application.id
                customer_id = customer.id
                mf_standard_generate_onboarding_document(
                    ktp_image_path,
                    file_type=MFStandardImageType.KTP,
                    application_id=application_id,
                    customer_id=customer_id,
                    created_by_user_id=created_by_user_id,
                )
                mf_standard_generate_onboarding_document(
                    selfie_ktp_image_path,
                    file_type=MFStandardImageType.KTP_SELFIE,
                    application_id=application_id,
                    customer_id=customer_id,
                    created_by_user_id=created_by_user_id,
                )
                mf_standard_generate_onboarding_document(
                    agent_merchant_image_path,
                    file_type=MFStandardImageType.AGENT_MERCHANT_SELFIE,
                    application_id=application_id,
                    customer_id=customer_id,
                    created_by_user_id=created_by_user_id,
                )

                if merchant_data.get(MFComplianceRegisterUpload.NPWP_IMAGE):
                    mf_standard_generate_onboarding_document(
                        merchant_data.get(MFComplianceRegisterUpload.KTP_IMAGE),
                        file_type=MFStandardImageType.NPWP,
                        application_id=application_id,
                        customer_id=customer_id,
                        created_by_user_id=created_by_user_id,
                    )

                if merchant_data.get(MFComplianceRegisterUpload.NIB_IMAGE):
                    mf_standard_generate_onboarding_document(
                        merchant_data.get(MFComplianceRegisterUpload.NIB_IMAGE),
                        file_type=MFStandardImageType.NIB,
                        application_id=application_id,
                        customer_id=customer_id,
                        created_by_user_id=created_by_user_id,
                    )

                if merchant_data.get(MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE):
                    mf_standard_generate_onboarding_document(
                        merchant_data.get(MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE),
                        file_type=MFStandardImageType.COMPANY_PHOTO,
                        application_id=application_id,
                        customer_id=customer_id,
                        created_by_user_id=created_by_user_id,
                    )

                if merchant_data.get(MFComplianceRegisterUpload.CASHFLOW_REPORT):
                    # this one is partnership document
                    mf_standard_generate_onboarding_document(
                        merchant_data.get(MFComplianceRegisterUpload.CASHFLOW_REPORT),
                        file_type=MFStandardDocumentType.CASHFLOW_REPORT,
                        application_id=application_id,
                        customer_id=customer_id,
                        created_by_user_id=created_by_user_id,
                        is_image=False,
                    )

                # move status to 105 because the image already uploaded
                process_application_status_change(
                    application_id,
                    ApplicationStatusCodes.FORM_PARTIAL,
                    change_reason='system_triggered',
                )

            is_success = True
            message = "Success register merchant application"
            return is_success, message

    except Exception:
        sentry_client.captureException()
        is_success = False
        message = "Failed register merchant application"
        return is_success, message


def upload_merchant_financing_onboarding_document(
    data: Dict, customer_data: dict, is_multiple: bool
) -> Tuple[Union[Dict, list], bool]:
    LIST_IMAGE_FILE_TYPE = {
        'ktp',
        'ktp_selfie',
        'npwp',
        'nib',
        'agent_with_merchant_selfie',
        'company_photo',
    }
    LIST_DOCUMENT_FILE_TYPE = {'cashflow_report'}
    application_id = customer_data.get('application_id')
    customer_id = customer_data.get('customer_id')
    all_file_types = LIST_IMAGE_FILE_TYPE.union(LIST_DOCUMENT_FILE_TYPE)
    source_file = None
    file_type = None

    for all_file_type in all_file_types:
        if data.get(all_file_type):
            source_file = data.get(all_file_type)
            file_type = all_file_type
            break

    if not source_file or not file_type:
        result = "File tidak boleh kosong"
        return result, False

    if not is_multiple:
        try:
            _, file_extension = os.path.splitext(source_file.name)
            filename = "mf-std-{}-{}{}".format(file_type, application_id, file_extension)
            with TempDir() as tempdir:
                dir_path = tempdir.path
                file_path = os.path.join(dir_path, filename)
                with open(file_path, "wb+") as destination:
                    for chunk in source_file.chunks():
                        destination.write(chunk)

                    destination.seek(0)
                    file_byte = destination.read()

                with transaction.atomic():
                    if file_type in LIST_IMAGE_FILE_TYPE:
                        file_data = PartnershipImage.objects.create(
                            application_image_source=application_id,
                            image_type=file_type,
                            thumbnail_url=filename,
                            image_status=PartnershipImageStatus.INACTIVE,
                            product_type=PartnershipImageProductType.MF_API,
                            user_id=customer_data.get('created_by_user_id'),
                        )
                    else:
                        file_data = PartnershipDocument.objects.create(
                            document_source=application_id,
                            document_type=file_type,
                            filename=filename,
                            document_status=PartnershipImageStatus.INACTIVE,
                            user_id=customer_data.get('created_by_user_id'),
                        )
                    file_data.url = "mf_cust_{}/application_{}/{}".format(
                        customer_id, application_id, filename
                    )
                    upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, file_byte, file_data.url)
                    file_data.save()

                if file_type in LIST_IMAGE_FILE_TYPE:
                    file_url = file_data.image_url
                else:
                    file_url = file_data.document_url_api

                result = {
                    'file_id': file_data.id,
                    'file_name': filename,
                    'file_url': file_url,
                }
                return result, True

        except Exception as e:
            logger.exception(
                {
                    'action': 'upload_merchant_financing_onboarding_document',
                    'application_id': application_id,
                    'customer_id': customer_id,
                    'file': source_file,
                    'file_type': file_type,
                    'error': e,
                }
            )
            message = 'File tidak dapat diproses, silahkan coba beberapa saat lagi'
            return message, False
    else:
        list_results = []
        is_success_all = True
        index = 1
        with transaction.atomic():
            """
            If during process upload we have error/trouble
            we will cancel save all document into database
            """
            for item in source_file:
                try:
                    file = item
                    file_type = file_type
                    _, file_extension = os.path.splitext(file.name)
                    filename = "mf-std-{}-{}-{}{}".format(
                        file_type, index, application_id, file_extension
                    )
                    with TempDir() as tempdir:
                        dir_path = tempdir.path
                        file_path = os.path.join(dir_path, filename)
                        with open(file_path, "wb+") as destination:
                            for chunk in file.chunks():
                                destination.write(chunk)

                            destination.seek(0)
                            file_byte = destination.read()

                        if file_type in LIST_IMAGE_FILE_TYPE:
                            file_data = PartnershipImage.objects.create(
                                application_image_source=application_id,
                                image_type=file_type,
                                product_type=PartnershipImageProductType.MF_API,
                                image_status=PartnershipImageStatus.INACTIVE,
                                user_id=customer_data.get('created_by_user_id'),
                            )
                        else:
                            file_data = PartnershipDocument.objects.create(
                                document_source=application_id,
                                document_type=file_type,
                                filename=filename,
                                document_status=PartnershipImageStatus.INACTIVE,
                                user_id=customer_data.get('created_by_user_id'),
                            )
                        file_data.url = "mf_cust_{}/application_{}/{}".format(
                            customer_id, application_id, filename
                        )
                        upload_file_as_bytes_to_oss(
                            settings.OSS_MEDIA_BUCKET, file_byte, file_data.url
                        )
                        file_data.save()

                        if file_type in LIST_IMAGE_FILE_TYPE:
                            file_url = file_data.image_url
                        else:
                            file_url = file_data.document_url_api
                        list_results.append(
                            {
                                'file_id': file_data.id,
                                'file_name': filename,
                                'file_url': file_url,
                            }
                        )
                except Exception as e:
                    logger.exception(
                        {
                            'action': 'upload_merchant_financing_onboarding_document',
                            'application_id': application_id,
                            'customer_id': customer_id,
                            'file': item,
                            'file_type': file_type,
                            'error': e,
                        }
                    )
                    is_success_all = False
                    message = 'File tidak dapat diproses, silahkan coba beberapa saat lagi'
                    return message, is_success_all
                index += 1
        return list_results, is_success_all


def get_fdc_data_for_application_v2(application_id):
    data = []
    with connections['bureau_db'].cursor() as cursor:
        query = (
            "select kualitas_pinjaman, count(*)"
            " from ops.fdc_inquiry fi"
            " left join ops.fdc_inquiry_loan fil on fi.fdc_inquiry_id = fil.fdc_inquiry_id"
            " where application_id = {} and"
            " fi.inquiry_reason = '1 - Applying loan via Platform'"
            " group by fil.kualitas_pinjaman".format(application_id)
        )
        cursor.execute(query)
        for detail in cursor.fetchall():
            inquiry_reason = None
            if detail[0] == FDCFieldsName.TIDAK_LANCAR:
                inquiry_reason = {"name": "late", "label": "Tidak Lancar"}
            elif detail[0] in {FDCFieldsName.MACET, 'Macet ( >90 )'}:
                inquiry_reason = {"name": "non_performing", "label": "Macet"}
            elif detail[0] == FDCFieldsName.LANCAR:
                inquiry_reason = {"name": "good", "label": "Lancar"}

            if inquiry_reason:
                if detail[1] > 0 and detail[0]:
                    inquiry_reason['label'] = "{} ({})".format(
                        inquiry_reason.get('label'), detail[1]
                    )

                data.append(inquiry_reason)

    if not data:
        data = [{'name': 'not_found', 'label': 'Tidak Ditemukan'}]

    return data


def mapping_merchant_financing_standard_status(application_status):
    in_progress_application_status = {
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
    }
    rejected_application_status = {
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    }
    if application_status == ApplicationStatusCodes.LOC_APPROVED:
        merchant_status = MFStandardMerchantStatus.APPROVED
    elif application_status in rejected_application_status:
        merchant_status = MFStandardMerchantStatus.REJECTED
    elif application_status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        merchant_status = MFStandardMerchantStatus.DOCUMENT_RESUBMIT
    elif application_status == ApplicationStatusCodes.FORM_CREATED:
        merchant_status = MFStandardMerchantStatus.DOCUMENT_REQUIRED
    elif application_status in in_progress_application_status:
        merchant_status = MFStandardMerchantStatus.IN_PROGRESS
    else:
        merchant_status = None

    return merchant_status


def generate_axiata_customer_data(loan):
    axiata_customer_data = AxiataCustomerData.objects.filter(loan_xid=loan.loan_xid).first()
    if axiata_customer_data:
        return None, "axiata_customer_data already exist"

    application = loan.get_application
    if not application:
        return None, "application not found"

    detokenize_application = partnership_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['fullname'],
    )

    partnership_customer_data = application.partnership_customer_data
    if not partnership_customer_data:
        return None, "partnership_customer_data not found"

    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        application.customer.customer_xid,
        ['phone_number', 'email', 'nik'],
    )

    partnership_applicatioin_data = application.partnershipapplicationdata_set.first()
    if not partnership_applicatioin_data:
        return None, "partnership_applicatioin_data not found"

    account_limit = loan.account.accountlimit_set.first()
    if not account_limit:
        return None, "account_limit not found"

    partner_loan_request = loan.partnerloanrequest_set.first()
    if not partner_loan_request:
        return None, "partner_loan_request not found"

    days_delta_each_payment = (
        partner_loan_request.financing_tenure / partner_loan_request.installment_number
    )
    first_payment_date = partner_loan_request.loan_request_date + timedelta(
        days=days_delta_each_payment
    )
    disbursement_date = None
    disbursement_time = None
    if loan.fund_transfer_ts:
        disbursement_date = loan.fund_transfer_ts.date()
        disbursement_time = loan.fund_transfer_ts.time()

    new_axiata_customer_data = AxiataCustomerData(
        application=application,
        disbursement_date=disbursement_date,
        disbursement_time=disbursement_time,
        first_payment_date=first_payment_date,
        funder=partner_loan_request.funder,
        partner_product_line=application.product_line,
        fullname=detokenize_application.fullname,
        ktp=detokenize_partnership_customer_data.nik,
        brand_name=application.company_name,
        company_name=application.company_name,
        company_registration_number=partnership_applicatioin_data.nib,
        business_category=partnership_applicatioin_data.business_category,
        type_of_business=partnership_applicatioin_data.business_entity,
        phone_number=detokenize_partnership_customer_data.phone_number,
        email=detokenize_partnership_customer_data.email,
        dob=application.dob,
        birth_place=application.birth_place,
        marital_status=application.marital_status,
        gender=application.gender,
        address_street_num=application.address_street_num,
        distributor=partner_loan_request.partnership_distributor.distributor_id,
        partner_id=application.partner.id,
        interest_rate=loan.product.interest_rate,
        loan_amount=loan.loan_amount,
        loan_duration=loan.loan_duration,
        loan_duration_unit="days",
        origination_fee=loan.product.origination_fee_pct,
        admin_fee=loan.product.admin_fee,
        invoice_id=partner_loan_request.invoice_number,
        date_of_establishment=application.dob,
        limit=account_limit.available_limit,
        npwp=partnership_customer_data.npwp,
        loan_xid=loan.loan_xid,
        address_provinsi=application.address_provinsi,
        address_kabupaten=application.address_kabupaten,
        address_kodepos=application.address_kodepos,
        loan_purpose=partnership_applicatioin_data.loan_purpose,
        user_type=partnership_customer_data.user_type,
        income=application.monthly_income,
        last_education=application.last_education,
        home_status=application.home_status,
        certificate_number=partnership_customer_data.certificate_number,
        certificate_date=partnership_customer_data.certificate_date,
        kin_name=application.kin_name,
        kin_mobile_phone=application.kin_mobile_phone,
    )

    return new_axiata_customer_data, None


def validate_dukcapil_fr_partnership(application, setting):
    fr_data = DukcapilFaceRecognitionCheck.objects.filter(
        application_id=application.id,
        response_code__isnull=False,
    ).last()

    if not fr_data:
        logger.info(
            {
                "message": "validate_dukcapil_fr_partnership, not fr_data",
                "application_id": application.id,
            }
        )
        note = "User bypassed to 190 due to no fr data found"

        ApplicationNote.objects.create(application_id=application.id, note_text=note)
        return True

    score = float(fr_data.response_score)

    if int(fr_data.response_code) == DukcapilFRClient.InternalStatus.NIK_NOT_FOUND:
        process_application_status_change(
            application,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            "Dukcapil FR NIK Not Found",
        )
        return False

    elif int(fr_data.response_code) != DukcapilFRClient.InternalStatus.SUCCESS:
        logger.info(
            {
                "message": "validate_dukcapil_fr_partnership, bad response code",
                "application_id": application.id,
                "response_code": fr_data.response_code,
            }
        )
        note = "User bypassed to 190 due to dukcapil fr doesn't found the nik"

        ApplicationNote.objects.create(application_id=application.id, note_text=note)
        return True

    very_high_threshold = float(setting.get("very_high", 0))
    high_threshold = float(setting.get("high", 0))

    logger.info(
        {
            "message": "validate_dukcapil_fr_partnership, decision",
            "application_id": application.id,
            "score": score,
        }
    )

    if score == 0:
        note = "User bypassed to 190 due to 0 score"
        ApplicationNote.objects.create(application_id=application.id, note_text=note)
        return True
    elif score >= very_high_threshold:
        process_application_status_change(application, 133, "Failed Dukcapil FR too high")
        return False
    elif score < high_threshold:
        process_application_status_change(application, 133, "Failed Dukcapil FR too low")
        return False

    return True


def process_image_upload(
    image, image_file: File, thumbnail=True, delete_if_last_image=False, suffix=None
):
    function_name = "mf webapp process_image_upload"
    try:
        application = Application.objects.get_or_none(pk=image.image_source)
        cust_id = application.customer_id
        if not application:
            logger.info(
                {
                    'action': function_name,
                    'status': 'image source/application not found',
                    'application_id': image.image_source,
                    'image_type': image.image_type,
                }
            )
            raise JuloException("Application id=%s not found" % image.image_source)

        subfolder = 'application_' + str(image.image_source)
        filename_without_path = os.path.basename(image_file.name)
        _, file_extension = os.path.splitext(filename_without_path)
        if suffix:
            filename = "%s_%s_%s%s" % (image.image_type, str(image.id), suffix, file_extension)
        else:
            filename = "%s_%s%s" % (image.image_type, str(image.id), file_extension)

        image_remote_filepath = '/'.join(['cust_' + str(cust_id), subfolder, filename])
        image_file.seek(0)
        file_byte = image_file.read()
        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, file_byte, image_remote_filepath)
        image.update_safely(url=image_remote_filepath)

        logger.info(
            {
                'action': function_name,
                'status': 'successfull upload image to s3',
                'image_remote_filepath': image_remote_filepath,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )

        # mark all other images with same type as 'deleted'
        image_query = (
            Image.objects.exclude(id=image.id)
            .exclude(image_status=Image.DELETED)
            .filter(image_source=image.image_source, image_type=image.image_type)
        )

        images = list(image_query)
        mark_delete_images = True
        if delete_if_last_image:
            last_image = Image.objects.filter(
                image_source=image.image_source, image_type=image.image_type
            ).last()
            mark_delete_images = True if last_image.id == image.id else False

        if mark_delete_images:
            for img in images:
                logger.info({'action': 'marking_deleted', 'image': img.id})
                img.update_safely(image_status=Image.DELETED)

        if image.image_ext != '.pdf' and thumbnail:

            # create thumbnail
            image_file.seek(0)
            im = Imagealias.open(image_file)
            im = im.convert('RGB')
            size = (150, 150)
            im.thumbnail(size, Imagealias.ANTIALIAS)

            # Save the thumbnail to a BytesIO object (in-memory file)
            thumbnail_buffer = io.BytesIO()
            # Determine format based on original file extension, default to JPEG
            img_format = im.format if im.format else 'JPEG'
            im.save(thumbnail_buffer, format=img_format)
            thumbnail_buffer.seek(0)  # Rewind the buffer to the beginning

            # upload thumbnail to s3
            thumbnail_dest_name = construct_remote_filepath(cust_id, image, suffix='thumbnail')
            upload_file_as_bytes_to_oss(
                settings.OSS_MEDIA_BUCKET, thumbnail_buffer, image_remote_filepath
            )
            image.update_safely(thumbnail_url=thumbnail_dest_name)

            logger.info(
                {
                    'action': function_name,
                    'status': 'successfull upload thumbnail to s3',
                    'thumbnail_dest_name': thumbnail_dest_name,
                    'application_id': image.image_source,
                    'image_type': image.image_type,
                }
            )

    except Exception as err:
        logger.error(
            {
                'action': function_name,
                'status': "failed process image upload",
                'application_id': image.image_source,
                'image_type': image.image_type,
                'error': err,
            }
        )

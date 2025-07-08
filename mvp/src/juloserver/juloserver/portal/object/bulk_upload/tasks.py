"""
tasks.py
"""
from __future__ import division
from future import standard_library

from juloserver.merchant_financing.constants import MFFeatureSetting
from juloserver.monitors.notifications import notify_max_3_platform_check_axiata

standard_library.install_aliases()
from builtins import str
from builtins import range
from past.utils import old_div

from builtins import str
from builtins import range
from past.utils import old_div
import os
import logging
import string
import random
import pytz
import tempfile
import pdfkit
import base64

from babel.dates import format_date

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.conf import settings
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from django.template.loader import render_to_string
from collections import defaultdict


from celery import task

from juloserver.julo.constants import EmailDeliveryAddress, FeatureNameConst
from juloserver.julo.services2 import get_advance_ai_service
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.clients.constants import BlacklistCheckStatus

from juloserver.julo.models import Application, FeatureSetting, Image
from juloserver.julo.models import Customer
from juloserver.julo.models import Loan
from juloserver.julo.models import Partner
from juloserver.julo.models import PartnerBankAccount
from juloserver.julo.models import PartnerReferral
from juloserver.julo.models import Workflow
from juloserver.julo.models import PaybackTransaction
from juloserver.julo.models import Payment
from juloserver.julo.models import StatusLookup
from juloserver.julo.models import (
    EmailHistory,
    PaymentMethod
)

from juloserver.account.models import CreditLimitGeneration

from juloserver.julo.exceptions import JuloException
from juloserver.merchant_financing.constants import MFFeatureSetting
from juloserver.monitors.notifications import notify_max_3_platform_check_axiata
from juloserver.partnership.constants import PartnershipImageProductType, PartnershipImageType
from juloserver.partnership.models import PartnershipImage

from juloserver.sdk.services import get_partner_productline

from juloserver.julo.services import create_application_checklist
from juloserver.julo.services import process_application_status_change
from juloserver.julo.services import change_due_dates, update_payment_fields
from juloserver.julo.services import process_partial_payment
from juloserver.julo.services import process_payment_status_change
from juloserver.julo.services import assign_lender_to_disburse
from juloserver.julo.services import update_customer_data
from juloserver.julo.statuses import ApplicationStatusCodes as AppStatus
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes

from juloserver.grab.services.grab_payment_flow import process_grab_repayment_trx

from juloserver.sdk.models import AxiataCustomerData, AxiataTemporaryData
from juloserver.sdk.models import AxiataRepaymentData
from juloserver.loan.models import LoanAdjustedRate
from juloserver.julo.models import (
    EmailHistory,
    PaymentMethod,
)

from juloserver.loan.services.adjusted_loan_matrix import get_daily_max_fee

from .serializers import AxiataTemporaryDataSerializer, CustomerSerializer
from .serializers import ApplicationPartnerUpdateSerializer

from juloserver.api_token.authentication import make_never_expiry_token

from juloserver.julo.product_lines import ProductLineCodes
from juloserver.apiv1.data.loan_purposes import get_loan_purpose_dropdown_by_product_line
from math import ceil
from juloserver.julo.utils import display_rupiah
from juloserver.julo.clients import get_julo_email_client
from django.conf import settings

from babel.dates import format_date
from django.template.loader import render_to_string
from juloserver.grab.models import (
    GrabLoanData,
    GrabPaymentData,
    GrabCustomerReferralWhitelistHistory,
    GrabReferralWhitelistProgram,
)
from juloserver.loan.services.loan_related import (
    update_loan_status_and_loan_history,
)
from juloserver.grab.services.loan_related import update_payments_for_resumed_loan
from juloserver.account_payment.tasks import update_account_payment_status_subtask
from juloserver.julo.tasks import update_payment_status_subtask
from juloserver.grab.services.services import update_loan_status_for_halted_or_resumed_loan
from juloserver.account_payment.models import AccountPayment
from datetime import datetime, timedelta
from juloserver.account_payment.services.payment_flow import update_account_payment_paid_off_status
from juloserver.account_payment.services.earning_cashback import (
    make_cashback_available
)
from juloserver.grab.tasks import trigger_grab_refinance_email
from juloserver.grab.services.services import GrabAccountPageService
from juloserver.julo.utils import format_nexmo_voice_phone_number
from juloserver.grab.models import GrabCustomerData
from juloserver.grab.tasks import trigger_grab_loan_sync_api_async_task
from juloserver.portal.object.bulk_upload.serializers import GrabReferralSerializer

# Create your views here.
from .utils import validate_axiata_max_interest_with_ojk_rule

logger = logging.getLogger(__name__)


@task(name='generate_application_axiata_async', queue='partner_axiata_global_queue')
def generate_application_axiata_async(axiata_data, partner_id):
    from juloserver.portal.object.bulk_upload.services import axiata_mtl_fill_data_for_pusdafil

    axiata_temporary_data_id = ""
    if "axiata_temporary_data_id" in axiata_data and axiata_data["axiata_temporary_data_id"] != "":
        axiata_temporary_data_id = axiata_data["axiata_temporary_data_id"]
        del axiata_data["axiata_temporary_data_id"]

    if 'certificate_date' in axiata_data and axiata_data.get('certificate_date'):
        try:
            axiata_data['certificate_date'] = datetime.strptime(
                axiata_data['certificate_date'], "%m/%d/%Y"
            )
        except:
            axiata_data['certificate_date'] = None

    if 'income' in axiata_data and axiata_data.get('income'):
        try:
            axiata_data['income'] = int(axiata_data['income'])
        except:
            axiata_data['income'] = None

    if 'user_type' in axiata_data and axiata_data.get('user_type'):
        axiata_data['user_type'] = axiata_data['user_type'].lower()

    if 'home_status' in axiata_data and axiata_data.get('home_status'):
        axiata_data['home_status'] = axiata_data['home_status'].capitalize()

    if 'last_education' in axiata_data and axiata_data.get('last_education'):
        axiata_data['last_education'] = axiata_data['last_education'].upper()
        if axiata_data['last_education'] == 'DIPLOMA':
            axiata_data['last_education'] = axiata_data['last_education'].capitalize()

    if 'kin_name' in axiata_data and axiata_data.get('kin_name'):
        axiata_data['kin_name'] = axiata_data['kin_name']

    if 'kin_mobile_phone' in axiata_data and axiata_data.get('kin_mobile_phone'):
        axiata_data['kin_mobile_phone'] = axiata_data['kin_mobile_phone']

    axiata_customer_data = AxiataCustomerData.objects.create(**axiata_data)
    logger.info({
        'action': "create_axiata_customer_data",
        'data': axiata_data,
        'partner': partner_id
    })
    application_serializer = ApplicationPartnerUpdateSerializer(data=axiata_data)

    if not application_serializer.is_valid():
        logger.error({
            'message': "error serialzer",
            'data': str(application_serializer.errors)
        })
        return

    loan_purpose = get_loan_purpose_dropdown_by_product_line(ProductLineCodes.AXIATA1)

    application_data = application_serializer.data
    application_data['loan_amount_request'] = axiata_data['loan_amount']
    application_data['loan_duration_request'] = axiata_data['loan_duration']
    application_data['loan_purpose'] = loan_purpose['results'][0]
    application_data['mobile_phone_1'] = axiata_data['phone_number']
    application_data['kin_name'] = axiata_data.get('kin_name')
    application_data['kin_mobile_phone'] = axiata_data.get('kin_mobile_phone')

    # get axiata bank data
    partner = Partner.objects.get_or_none(pk=partner_id)
    axiata_bank_data = PartnerBankAccount.objects.filter(partner=partner).last()
    if axiata_bank_data:
        application_data['bank_name'] = axiata_bank_data.bank_name
        application_data['bank_account_number'] = axiata_bank_data.bank_account_number
        application_data['name_in_bank'] = axiata_bank_data.name_in_bank

    # generate application axiata until 148
    is_success, message = generate_application_async(
        application_data, partner_id, axiata_customer_data
    )
    if not is_success:
        notify_max_3_platform_check_axiata(message)
        return
    loan_requested = dict(
        loan_amount=axiata_customer_data.loan_amount,
        due_date=axiata_customer_data.first_payment_date,
        duration_type=axiata_customer_data.loan_duration_unit,
        interest_rate=axiata_customer_data.interest_rate,
        origination_fee=axiata_customer_data.origination_fee,
        admin_fee_amount=axiata_customer_data.admin_fee
    )
    admin_fee = axiata_customer_data.admin_fee
    origination_fee = old_div(axiata_customer_data.origination_fee, 100)
    interest_rate = axiata_customer_data.interest_rate / 100.0
    disbursement_amount = axiata_customer_data.loan_amount - (
        origination_fee * axiata_customer_data.loan_amount) - admin_fee
    installment_amount = axiata_customer_data.loan_amount + ceil(
        axiata_customer_data.loan_amount * interest_rate
    )
    additional_loan_data = {
        'is_exceed': False,
        'max_fee_ojk': 0.0,
        'simple_fee': 0.0,
        'provision_fee_rate': 0.0,
        'new_interest_rate': 0.0
    }
    daily_max_fee_from_ojk = get_daily_max_fee()
    if daily_max_fee_from_ojk:
        additional_loan_data = validate_axiata_max_interest_with_ojk_rule(
            loan_requested, additional_loan_data, daily_max_fee_from_ojk
        )
        if additional_loan_data['is_exceed']:
            disbursement_amount = axiata_customer_data.loan_amount - (
                additional_loan_data['provision_fee_rate'] * axiata_customer_data.loan_amount)
            installment_amount = axiata_customer_data.loan_amount + ceil(
                axiata_customer_data.loan_amount * additional_loan_data['new_interest_rate']
            )
    # approve directly
    with transaction.atomic():
        axiata_customer_data.refresh_from_db()
        application = axiata_customer_data.application
        loan = application.loan
        loan.sphp_sent_ts = axiata_customer_data.acceptance_date
        loan.sphp_accepted_ts = axiata_customer_data.acceptance_date
        loan.loan_amount = axiata_customer_data.loan_amount
        loan.installment_amount = installment_amount
        if additional_loan_data['is_exceed']:
            loan.first_installment_amount = installment_amount
        loan.loan_disbursement_amount = disbursement_amount
        loan.save()

        # make payment method as loan level for axita
        loan.paymentmethod_set.update(loan_id=None)

        new_due_date = axiata_customer_data.first_payment_date
        change_due_dates(loan, new_due_date, partner.name)
        update_payment_fields(loan, axiata_customer_data, additional_loan_data)
        if additional_loan_data['is_exceed']:
            LoanAdjustedRate.objects.create(
                loan=loan,
                adjusted_monthly_interest_rate=additional_loan_data['new_interest_rate'],
                adjusted_provision_rate=additional_loan_data['provision_fee_rate'],
                max_fee=additional_loan_data['max_fee_ojk'],
                simple_fee=additional_loan_data['simple_fee']
            )
        process_application_status_change(application.id,
                                          AppStatus.FUND_DISBURSAL_ONGOING,
                                          change_reason='approval by script')

        axiata_mtl_fill_data_for_pusdafil(partner, application, loan)

    if is_success:
        notify_max_3_platform_check_axiata("", application.fullname, application.id)
    if axiata_temporary_data_id:
        axiata_temporary_data = AxiataTemporaryData.objects.filter(
            id=axiata_temporary_data_id
        ).last()
        serializer = AxiataTemporaryDataSerializer(
            axiata_temporary_data, data=model_to_dict(axiata_customer_data)
        )
        serializer.is_valid()
        serializer.validated_data["is_uploaded"] = True
        serializer.validated_data["axiata_customer_data"] = axiata_customer_data
        serializer.save()

        for image_type in {PartnershipImageType.KTP_SELF, PartnershipImageType.SELFIE}:
            temp_image = PartnershipImage.objects.filter(
                product_type=PartnershipImageProductType.AXIATA,
                image_type=image_type,
                application_image_source=axiata_temporary_data_id
            ).last()

            if not temp_image:
                continue

            Image.objects.create(
                image_source=application.id,
                image_type=image_type,
                url=temp_image.url,
                thumbnail_url=temp_image.thumbnail_url,
                service=temp_image.service
            )

        send_sign_axiata_sphp_email.delay(application.id)


@task(name='generate_application_async', queue='partner_axiata_global_queue')
def generate_application_async(application_data, partner_id, axiata_customer_data=None):
    from juloserver.portal.object.bulk_upload.services import (
        get_mtl_parameters_fs_check_other_active_platforms_using_fdc,
        is_apply_check_other_active_platforms_using_fdc_mtl,
        is_eligible_other_active_platforms_for_mtl,
        insert_data_to_fdc,
    )

    """bulk generate application from excel file"""
    message = ""
    is_success = True

    ktp = application_data.get('ktp')
    partner = Partner.objects.get_or_none(pk=partner_id)
    if not partner:
        logger.error({
            'message': "partner not found",
            'data': application_data
        })
        raise JuloException("partner not found")

    customer = Customer.objects.get_or_none(nik=ktp)
    if customer:
        last_application = customer.application_set.last()
        multiple_loan_axiata = FeatureSetting.objects.get_or_none(
            is_active=True,
            feature_name=FeatureNameConst.AXIATA_MULTIPLE_LOAN)

        if multiple_loan_axiata and axiata_customer_data:
            # check if data axiata duplicate
            axiata_data_exist = AxiataCustomerData.objects.filter(
                ktp=axiata_customer_data.ktp,
                partner_application_date=axiata_customer_data.partner_application_date,
                disbursement_time=axiata_customer_data.disbursement_time,
                first_payment_date=axiata_customer_data.first_payment_date,
                application__isnull=False).first()

            if axiata_data_exist:
                try:
                    loan = axiata_data_exist.application.loan
                except Exception as e:
                    loan = None
                if loan:
                    axiata_customer_data.update_safely(reject_reason='duplicate loan')
                    return
        else:
            if last_application and last_application.is_active():
                if last_application.status == AppStatus.FUND_DISBURSAL_SUCCESSFUL:
                    last_loan = Loan.objects.filter(application_id=last_application.id).last()
                    if last_loan and last_loan.is_active:
                        logger.error({
                            'message': "Customer has active loan",
                            'data': application_data
                        })

                        if axiata_customer_data:
                            axiata_customer_data.update_safely(
                                reject_reason="Customer has active loan")

                        raise JuloException("Customer with customer_id {} can't reapply".format(
                            str(customer.id)
                        ))
                else:
                    logger.error({
                        'message': "Customer has ongoing application",
                        'data': application_data
                    })

                    if axiata_customer_data:
                        axiata_customer_data.update_safely(
                            reject_reason="Customer has ongoing application")

                    raise JuloException("Customer with customer_id {} can't reapply".format(
                        str(customer.id)
                    ))

        if last_application:
            application_data['application_number'] = (last_application.application_number or 0) + 1
        else:
            application_data['application_number'] = 1

        if not customer.can_reapply and not axiata_customer_data:
            logger.error({
                'message': "Customer can't reapply",
                'data': application_data
            })

            raise JuloException("Customer with customer_id {} can't reapply".format(
                str(customer.id)
            ))

    try:
        with transaction.atomic():
            if not customer:
                user = User.objects.filter(username=ktp).first()
                if not user:
                    # generate random password
                    password = ''.join(random.choice(string.ascii_lowercase +
                                                     string.digits) for _ in range(8))
                    user = User(username=ktp)
                    user.set_password(password)
                    user.save()
                    make_never_expiry_token(user)

                customer_data = CustomerSerializer(application_data).data
                customer_data['user'] = user
                customer_data['nik'] = ktp
                customer_data['phone'] = application_data.get('mobile_phone_1', None)
                customer_data['kin_name'] = application_data.get('kin_name', None)
                customer_data['kin_mobile_phone'] = application_data.get('kin_mobile_phone', None)
                # block notify to ICare client
                customer_data['can_notify'] = False
                customer = Customer.objects.create(**customer_data)
                application_data['application_number'] = 1

            application_serializer = ApplicationPartnerUpdateSerializer(application_data)
            application_data = application_serializer.data
            application_data['customer'] = customer
            application_data['partner'] = partner
            application = Application.objects.create(**application_data)
            update_customer_data(application)

            workflow = Workflow.objects.get(name='PartnerWorkflow')
            product_line = get_partner_productline(application, application.partner).first()
            # assign more data to application
            application.workflow = workflow
            application.product_line = product_line
            application.save()

            # save FDC data via FDC API
            insert_data_to_fdc(application)

            if axiata_customer_data:
                # assign application to axiata_data
                axiata_customer_data.update_safely(application=application)

            # create partner_referral
            partner_referral = PartnerReferral(cust_nik=ktp)
            partner_referral.partner = partner
            partner_referral.customer = customer
            logger.info({
                'action': 'create_link_partner_referral_to_customer',
                'customer_id': customer.id,
                'partner_id': partner_referral.partner,
                'nik': ktp
            })
            partner_referral.save()

            # check max 3 creditor check
            is_axiata_max_3_platform_check = FeatureSetting.objects.filter(
                feature_name=MFFeatureSetting.MAX_3_PLATFORM_FEATURE_NAME,
                is_active=True,
            ).last()
            if is_axiata_max_3_platform_check:
                parameters = get_mtl_parameters_fs_check_other_active_platforms_using_fdc()
                if is_apply_check_other_active_platforms_using_fdc_mtl(application, parameters):
                    if not is_eligible_other_active_platforms_for_mtl(
                        application,
                        parameters['fdc_data_outdated_threshold_days'],
                        parameters['number_of_allowed_platforms'],
                    ):
                        message = (
                            'Failed loan creation happened for {}, application_id: {} - '
                            'User has active loan on at least 3 other platforms'
                        ).format(application.fullname, application.id)
                        is_success = False

                        # update application status to 106
                        application.update_safely(
                            application_status=StatusLookup(
                                status_code=AppStatus.FORM_PARTIAL_EXPIRED
                            ),
                        )
                        return is_success, message

            process_application_status_change(application.id, AppStatus.FORM_GENERATED,
                                              change_reason='generate from excel')
            create_application_checklist(application)

            # if partner axiata don't run advance ai
            if not axiata_customer_data:
                # reject application if have in blacklist
                blacklist_status = get_advance_ai_service().run_blacklist_check(application)
                if blacklist_status == BlacklistCheckStatus.REJECT:
                    # block reapply for 3 months
                    process_application_status_change(application.id,
                                                      AppStatus.APPLICATION_DENIED,
                                                      change_reason='failed_dv_identity')
                elif blacklist_status != BlacklistCheckStatus.PASS:
                    # can reapply immediately
                    process_application_status_change(
                        application.id,
                        AppStatus.APPLICATION_DENIED,
                        change_reason='reject by script',
                    )

        return is_success, message

    except Exception as e:
        if axiata_customer_data:
            axiata_customer_data.update_safely(reject_reason=str(e))

        raise JuloException("error: {}".format(
            str(e)
        ))

@task(name='approval_application_async', queue='partner_axiata_global_queue')
@transaction.atomic
def approval_application_async(invoice_data, partner_id):
    """
    approval application process with data from invoice data, only using for ICare client
    """
    application = Application.objects.get_or_none(
        application_xid=invoice_data['application_xid'],
        partner_id=partner_id,
        application_status__status_code=AppStatus.FORM_GENERATED
    )
    if not application:
        logger.error({
            'action': 'approval application async',
            'application_xid': invoice_data['application_xid'],
            'error': 'application not found'
        })
        raise JuloException("application not found")
    loan = Loan.objects.get_or_none(application_id=application.id)
    if not loan:
        logger.error({
            'action': 'approval application async',
            'application_xid': invoice_data['application_xid'],
            'error': 'loan not found'
        })
        raise JuloException("loan not found")

    # assign to lender
    lender = assign_lender_to_disburse(application)
    loan.lender = lender
    if lender:
        loan.partner = lender.user.partner

    # update loan info with invoice data
    loan.sphp_sent_ts = invoice_data['delivered_date']
    loan.sphp_accepted_ts = invoice_data['sphp_sign_date']
    loan.loan_disbursement_amount = invoice_data['net_amount']
    loan.referral_code = invoice_data['bast_dn_number']
    loan.save()
    new_due_date = datetime.strptime(invoice_data['first_installment_date'], "%Y-%m-%d").date()
    change_due_dates(loan, new_due_date)

    # update application info with invoice data
    application.referral_code = invoice_data['bast_dn_number']
    application.save()
    process_application_status_change(application.id,
                                      AppStatus.LENDER_APPROVAL,
                                      change_reason='approval by script')


@task(name='loan_disbursement_async', queue='partner_axiata_global_queue')
@transaction.atomic
def loan_disbursement_async(application_data, partner_id):
    """disbursement script for ICare client from excel data
       change status from 177 to 180 for application
    """
    application_xid = application_data.get('application_xid')
    application = Application.objects.get_or_none(
        application_xid=application_xid,
        application_status__status_code=AppStatus.FUND_DISBURSAL_ONGOING,
        partner_id=partner_id
    )
    if not application:
        logger.error({
            'message': "Application not found",
            'data': application_data
        })
        raise JuloException("Application not found")

    process_application_status_change(application.id,
                                      AppStatus.FUND_DISBURSAL_SUCCESSFUL,
                                      change_reason='disbursement by script')

@task(name='reject_application_async', queue='partner_axiata_global_queue')
@transaction.atomic
def reject_application_async(application_data, partner_id):
    """reject application script for ICare client from excel data
       change status from 148 to 135 for application
       reject application that exist in rejected list
    """

    application = Application.objects.filter(
        ktp=application_data['ktp'],
        application_status__status_code=AppStatus.FORM_GENERATED,
        partner_id=partner_id
    ).order_by('cdate').last()

    if not application:
        logger.error({
            'message': "Application not found",
            'data': application_data
        })
        raise JuloException("Application not found")

    process_application_status_change(application.id,
                                      AppStatus.APPLICATION_DENIED,
                                      change_reason='reject by script')


@task(name='repayment_application_async', queue='partner_axiata_global_queue')
def repayment_async(axiata_repayment_data, partner_id):
    collected_by = axiata_repayment_data['collected_by']
    user = User.objects.get(pk=collected_by)
    axiata_repayment_data.pop('collected_by')
    axiata_repayment_data = AxiataRepaymentData.objects.create(**axiata_repayment_data)
    logger.info({
        'action': "create_axiata_repayment_data",
        'data': axiata_repayment_data,
        'partner': partner_id
    })

    axiata_repayment_data.refresh_from_db()

    # new handle for Axiata new flow
    if axiata_repayment_data.partner_application_id:
        new_axiata_repayment(axiata_repayment_data, axiata_repayment_data.partner_application_id)
        return

    application_xid = axiata_repayment_data.application_xid
    application = Application.objects.get_or_none(application_xid=application_xid)
    customer = application.customer
    loan_data = application.loan

    payment = loan_data.payment_set.filter(
        payment_number=axiata_repayment_data.payment_number).first()
    if payment.payment_status.status_code in PaymentStatusCodes.paid_status_codes():
        axiata_repayment_data.update_safely(messages="Payment has already paid")
        raise JuloException(
            "Payment with payment_id {} is already paid".format(str(payment.payment_id)))
    if axiata_repayment_data.payment_amount > payment.due_amount:
        axiata_repayment_data.update_safely(messages="Paid amount exceed total due amount")
        raise JuloException("Paid amount exceed total due amount")
    else:
        axiata_repayment_data.update_safely(messages="Success")

    try:
        with transaction.atomic():
            process_partial_payment(payment,
                                    axiata_repayment_data.payment_amount,
                                    paid_date=axiata_repayment_data.payment_date,
                                    note=None,
                                    collected_by=user)

            # force to can reapply directly for axiata
            loan_data.refresh_from_db()
            if loan_data.status == LoanStatusCodes.PAID_OFF:
                customer.update_safely(
                    can_reapply=True
                )

    except Exception as e:
        logger.error({"action": "axiata_repayment", "errors": e})
        raise JuloException(e)


def new_axiata_repayment(axiata_repayment_data, partner_application_id):
    axiata_customer_data = AxiataCustomerData.objects.get(
        partner_application_id=partner_application_id)
    loan = Loan.objects.get(loan_xid=axiata_customer_data.loan_xid)

    application = axiata_customer_data.application
    paid_date = axiata_repayment_data.payment_date
    paid_date = paid_date.strftime('%d-%m-%Y')
    amount = axiata_repayment_data.payment_amount
    account = application.account
    customer = application.customer
    account_payment = account.get_oldest_unpaid_account_payment()

    if not account_payment:
        axiata_repayment_data.update_safely(messages="Payment has already paid")
        raise JuloException("Payment has already paid")

    local_timezone = pytz.timezone('Asia/Jakarta')
    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer=customer,
            payback_service='bulk upload',
            status_desc='bulk upload by crm',
            transaction_date=local_timezone.localize(datetime.strptime(paid_date, '%d-%m-%Y')),
            amount=amount,
            account=account_payment.account,
            loan=loan,
        )
        payment_processed = process_grab_repayment_trx(payback_transaction, over_paid=False)
        if payment_processed:
            axiata_repayment_data.update_safely(messages="Success")
        else:
            axiata_repayment_data.update_safely(
                messages="Something wrong when processing repayment")


@task(name='send_email_at_190_for_pilot_product_csv_upload', queue='partner_mf_global_queue')
def send_email_at_190_for_pilot_product_csv_upload(application_id, limit, provision=None):
    def prepare_email_context(partner_name, limit, provision=None):
        email_from = application.partner.sender_email_address_for_190_application
        if not email_from:
            message = "{} sender_email_address_for_190_application not found".format(partner_name)
            raise Exception(message)

        if partner_name == 'BukuWarung':
            limit = int(limit)
            provision = float(provision)
            provision_max = limit * provision
            provision_max_int = int(provision_max)
            context = {
                'fullname': application.fullname_with_title,
                'account_set_limit': display_rupiah(limit),
                'cdate_190': x190_history.cdate,
                'provision_max': display_rupiah(provision_max_int),
                'provision': round(provision * 100, 2),
            }

            email_template = render_to_string('email_template_mf_bukuwarung.html', context=context)
            email_to = application.email
            if not email_to:
                message = "{} recipients application.email not found".format(partner_name)
                raise Exception(message)
        else:
            context = {
                'fullname': application.fullname_with_title,
                'account_set_limit': display_rupiah(limit),
                'cdate_190': x190_history.cdate
            }
            email_template = render_to_string('email_template_mf.html', context=context)

            if application.partner.is_email_send_to_customer:
                email_to = application.email
            else:
                recipients_email_address_for_190_application = \
                    application.partner.recipients_email_address_for_190_application
                if not recipients_email_address_for_190_application:
                    message = "{} recipients_email_address_for_190_application not found".format(partner_name)
                    raise Exception(message)
                email_to = recipients_email_address_for_190_application

        email_cc = application.partner.cc_email_address_for_190_application
        email_context = {
            'email_template': email_template,
            'email_from': email_from,
            'email_to': email_to,
            'email_cc': email_cc
        }
        return email_context

    application = Application.objects.get(id=application_id)
    x190_history = application.applicationhistory_set.get(status_new=190)
    email_context = prepare_email_context(application.partner.name, limit, provision)
    email_template = email_context['email_template']
    email_from = email_context['email_from']
    email_to = email_context['email_to']
    email_cc = email_context['email_cc']

    subject = "{} - Pengajuan Kredit Limit JULO telah disetujui, balas YA untuk melanjutkan".format(
        application.email)

    def get_sphp_attachment():
        attachment_name = "%s-%s.pdf" % (application.fullname, application.application_xid)
        attachment_string = get_sphp_template(application)
        pdf_content = get_pdf_content_from_html(attachment_string, attachment_name)
        attachment_dict = {
            "content": pdf_content,
            "filename": attachment_name,
            "type": "application/pdf"
        }
        return attachment_dict, "text/html"

    attachment_dict, content_type = get_sphp_attachment()
    julo_email_client = get_julo_email_client()

    msg = email_template
    julo_email_client.send_email(
        subject, msg, email_to, email_from=email_from, email_cc=email_cc,
        attachment_dict=attachment_dict, content_type=content_type)
    EmailHistory.objects.create(
        customer_id=application.customer_id,
        application_id=application.id,
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code='{}_190_email'.format(application.partner.name)
    )


def get_sphp_template(application):
    credit_limit = CreditLimitGeneration.objects.get(application=application)

    payment_method = PaymentMethod.objects.get(
        is_primary=True,
        customer_id=application.customer_id)

    bank_name = payment_method.payment_method_name
    bank_code = payment_method.bank_code if 'BCA' not in bank_name else None

    sphp_date = timezone.now().date()
    context = {
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'julo_bank_code': bank_code,
        'julo_bank_name': bank_name,
        'julo_bank_account_number': payment_method.virtual_account,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'account_set_limit': display_rupiah(credit_limit.set_limit)
    }
    sphp_template = render_to_string('sphp_pilot_merchant_financing_application_upload_template.html', context=context)

    return sphp_template


def get_pdf_content_from_html(html_content, filename):
    temp_dir = tempfile.mkdtemp()
    options = {
        'page-size': 'A4',
        'margin-top': '0in',
        'margin-right': '0in',
        'margin-bottom': '0in',
        'margin-left': '0in',
        'encoding': "UTF-8",
        'no-outline': None,
    }
    file_path = os.path.join(temp_dir, filename)
    pdfkit.from_string(html_content, file_path, options=options)
    with open(file_path, 'rb') as f:
        data = f.read()
        f.close()
    encoded = base64.b64encode(data)
    if os.path.exists(file_path):
        os.remove(file_path)
    return encoded.decode()


@task(name='loan_halt_task', queue='grab_halt_queue')
def loan_halt_task(data, partner_id):
    loan = Loan.objects.filter(loan_xid=data['loan_xid']).last()
    halt_date = datetime.strptime(data['date'], '%Y.%m.%d')
    if not loan:
        return

    application = loan.account.last_application
    if application.partner.id != partner_id:
        raise JuloException('Application partner does not match')
    if 'action' in data and data['action'].lower() != 'halt':
        return
    agent_user_id = data['agent_user_id']
    logger.info({
        "action": 'loan_halt_task',
        "loan_xid": loan.loan_xid,
        "halt_date": halt_date
    })
    grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
    grab_loan_data.loan_halt_date = halt_date
    grab_loan_data.save(update_fields=['loan_halt_date'])


@task(name='loan_resume_task', queue='grab_resume_queue')
def loan_resume_task(data, partner_id):
    loan = Loan.objects.filter(loan_xid=data['loan_xid']).last()
    resume_date = datetime.strptime(data['date'], '%Y.%m.%d').date()
    if not loan or loan.status != LoanStatusCodes.HALT:
        return
    application = loan.account.last_application
    if application.partner.id != partner_id:
        raise JuloException('Application partner does not match')
    resume_time = resume_date + timedelta(hours=2)
    if 'action' in data and data['action'].lower() != 'resume':
        return
    agent_user_id = data['agent_user_id']
    logger.info({
        "action": 'loan_resume_task',
        "loan_xid": loan.loan_xid,
        "resume_time": resume_time
    })

    grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
    grab_loan_data.loan_resume_date = resume_date
    grab_loan_data.save(update_fields=['loan_resume_date'])


@task(name='loan_halt_task_subtask_async', queue='grab_halt_queue')
def loan_halt_task_subtask_async(loan_id, halt_date, changed_by_user):

    today_date = timezone.localtime(timezone.now()).date()
    tomorrow_date = timezone.localtime(timezone.now() + timedelta(
        days=1)).date()
    if halt_date not in {today_date, tomorrow_date}:
        return

    loan = Loan.objects.filter(id=loan_id).exclude(
        loan_status=LoanStatusCodes.HALT).last()
    if not loan:
        return
    payment = Payment.objects.filter(
        due_date__gte=halt_date,
        loan=loan
    ).last()
    if not payment:
        return

    if halt_date == tomorrow_date:
        if Payment.objects.filter(
            due_date=today_date,
            loan=loan,
            payment_status__in={
                PaymentStatusCodes.PAYMENT_NOT_DUE, PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_5DPD,
                PaymentStatusCodes.PAYMENT_30DPD, PaymentStatusCodes.PAYMENT_60DPD,
                PaymentStatusCodes.PAYMENT_90DPD, PaymentStatusCodes.PAYMENT_120DPD,
                PaymentStatusCodes.PAYMENT_150DPD, PaymentStatusCodes.PAYMENT_180DPD
            }
        ).exists():
            return

    payments = Payment.objects.filter(loan=loan).select_related(
        'loan', 'payment_status', 'account_payment').not_paid_active().order_by('payment_number')
    grab_payment_data_list = []
    for payment in payments.iterator():
        grab_payment_data = GrabPaymentData()
        grab_payment_data.loan_id = payment.loan.id
        grab_payment_data.payment_status_id = payment.payment_status.id
        grab_payment_data.payment_number = payment.payment_number
        grab_payment_data.due_date = payment.due_date
        grab_payment_data.ptp_date = payment.ptp_date
        grab_payment_data.ptp_robocall_template_id = payment.ptp_robocall_template.id
        grab_payment_data.is_ptp_robocall_active = payment.is_ptp_robocall_active
        grab_payment_data.due_amount = payment.due_amount
        grab_payment_data.installment_principal = payment.installment_principal
        grab_payment_data.installment_interest = payment.installment_interest
        grab_payment_data.paid_date = payment.paid_date
        grab_payment_data.paid_amount = payment.paid_amount
        grab_payment_data.redeemed_cashback = payment.redeemed_cashback
        grab_payment_data.cashback_earned = payment.cashback_earned
        grab_payment_data.late_fee_amount = payment.late_fee_amount
        grab_payment_data.late_fee_applied = payment.late_fee_applied
        grab_payment_data.discretionary_adjustment = payment.discretionary_adjustment
        grab_payment_data.is_robocall_active = payment.is_robocall_active
        grab_payment_data.is_success_robocall = payment.is_success_robocall
        grab_payment_data.is_collection_called = payment.is_collection_called
        grab_payment_data.uncalled_date = payment.uncalled_date
        grab_payment_data.reminder_call_date = payment.reminder_call_date
        grab_payment_data.is_reminder_called = payment.is_reminder_called
        grab_payment_data.is_whatsapp = payment.is_whatsapp
        grab_payment_data.is_whatsapp_blasted = payment.is_whatsapp_blasted
        grab_payment_data.paid_interest = payment.paid_interest
        grab_payment_data.paid_principal = payment.paid_principal
        grab_payment_data.paid_late_fee = payment.paid_late_fee
        grab_payment_data.ptp_amount = payment.ptp_amount
        grab_payment_data.change_due_date_interest = payment.change_due_date_interest
        grab_payment_data.is_restructured = payment.is_restructured
        grab_payment_data.account_payment_id = payment.account_payment.id
        grab_payment_data.payment_id = payment.id
        grab_payment_data.description = 'loan is halted'
        grab_payment_data_list.append(grab_payment_data)
    GrabPaymentData.objects.bulk_create(grab_payment_data_list, batch_size=30)
    new_status_code = LoanStatusCodes.HALT
    update_loan_status_and_loan_history(
        loan_id, new_status_code, changed_by_user, 'loan_halt_triggered')

    logger.info({
        "action": "loan_halt_task_subtask_async",
        "loan_id": loan_id,
        "halt_date": halt_date,
        "changed_by_user": changed_by_user
    })


@task(name='loan_resume_task_subtask_async', queue='grab_resume_queue')
def loan_resume_task_subtask_async(loan_id, resume_date, changed_by_user):
    current_time = timezone.localtime(timezone.now())

    if resume_date != current_time.date():
        return

    loan = Loan.objects.select_related('account', 'loan_status', 'customer').filter(
        id=loan_id, loan_status=LoanStatusCodes.HALT).last()
    if not loan:
        return

    with transaction.atomic():
        grab_loan_data = GrabLoanData.objects.filter(loan=loan).only('loan_halt_date').last()

        halt_date = grab_loan_data.loan_halt_date

        update_payments_for_resumed_loan(loan, resume_date, halt_date)
        halt_status = StatusLookup.objects.filter(status_code=LoanStatusCodes.HALT).last()

        payments = Payment.objects.filter(loan_id=loan.id).select_related(
            'loan', 'payment_status', 'account_payment').not_paid_active()
        grab_payment_data_list = []
        for payment in payments.iterator():
            update_payment_status_subtask.delay(payment.id)
            update_account_payment_status_subtask.delay(payment.account_payment.id)

            payment.refresh_from_db()
            grab_payment_data = GrabPaymentData()
            grab_payment_data.loan_id = payment.loan.id
            grab_payment_data.payment_status_id = payment.payment_status.id
            grab_payment_data.payment_number = payment.payment_number
            grab_payment_data.due_date = payment.due_date
            grab_payment_data.ptp_date = payment.ptp_date
            grab_payment_data.ptp_robocall_template_id = payment.ptp_robocall_template
            grab_payment_data.is_ptp_robocall_active = payment.is_ptp_robocall_active
            grab_payment_data.due_amount = payment.due_amount
            grab_payment_data.installment_principal = payment.installment_principal
            grab_payment_data.installment_interest = payment.installment_interest
            grab_payment_data.paid_date = payment.paid_date
            grab_payment_data.paid_amount = payment.paid_amount
            grab_payment_data.redeemed_cashback = payment.redeemed_cashback
            grab_payment_data.cashback_earned = payment.cashback_earned
            grab_payment_data.late_fee_amount = payment.late_fee_amount
            grab_payment_data.late_fee_applied = payment.late_fee_applied
            grab_payment_data.discretionary_adjustment = payment.discretionary_adjustment
            grab_payment_data.is_robocall_active = payment.is_robocall_active
            grab_payment_data.is_success_robocall = payment.is_success_robocall
            grab_payment_data.is_collection_called = payment.is_collection_called
            grab_payment_data.uncalled_date = payment.uncalled_date
            grab_payment_data.reminder_call_date = payment.reminder_call_date
            grab_payment_data.is_reminder_called = payment.is_reminder_called
            grab_payment_data.is_whatsapp = payment.is_whatsapp
            grab_payment_data.is_whatsapp_blasted = payment.is_whatsapp_blasted
            grab_payment_data.paid_interest = payment.paid_interest
            grab_payment_data.paid_principal = payment.paid_principal
            grab_payment_data.paid_late_fee = payment.paid_late_fee
            grab_payment_data.ptp_amount = payment.ptp_amount
            grab_payment_data.change_due_date_interest = payment.change_due_date_interest
            grab_payment_data.is_restructured = payment.is_restructured
            grab_payment_data.account_payment_id = payment.account_payment.id
            grab_payment_data.payment_id = payment.id
            grab_payment_data.description = 'loan is resumed'
            grab_payment_data_list.append(grab_payment_data)
        GrabPaymentData.objects.bulk_create(grab_payment_data_list, batch_size=30)
        loan.loan_status = halt_status
        loan.save(update_fields=['loan_status'])
        update_loan_status_for_halted_or_resumed_loan(loan)

    logger.info({
        "action": "loan_resume_task_subtask_async",
        "loan_id": loan_id,
        "resume_date": resume_date,
        "changed_by_user": changed_by_user
    })


@task(name='run_loan_halt_periodic_task', queue='grab_halt_queue')
def run_loan_halt_periodic_task():
    """
    This Version of HALT and resume is Depricated.
    """
    today = timezone.localtime(timezone.now()).date()
    tomorrow = timezone.localtime(timezone.now() + timedelta(days=1)).date()
    grab_loan_ids = GrabLoanData.objects.filter(
        loan_halt_date__in={today, tomorrow}).values_list('loan_id', 'loan_halt_date')
    for loan_halt_id, loan_halt_date in grab_loan_ids:
        loan = Loan.objects.filter(id=loan_halt_id).last()
        if loan.status == LoanStatusCodes.HALT:
            continue
        loan_halt_task_subtask_async.delay(loan_halt_id, loan_halt_date, None)


@task(name='run_loan_resume_periodic_task', queue='grab_resume_queue')
def run_loan_resume_periodic_task():
    """
    This Version of HALT and resume is Depricated.
    """
    today = timezone.localtime(timezone.now()).date()
    grab_loan_ids = GrabLoanData.objects.filter(
        loan_resume_date=today).values_list('loan_id', flat=True)
    for loan_resume_id in grab_loan_ids:
        loan = Loan.objects.filter(id=loan_resume_id).last()
        if loan.status != LoanStatusCodes.HALT:
            continue
        loan_resume_task_subtask_async.delay(loan_resume_id, today, None)


@task(name='update_double_account_payment_details', queue='grab_resume_queue')
def update_double_account_payment_details(account_id):
    paid_status_codes = [PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                         PaymentStatusCodes.PAID_LATE,
                         PaymentStatusCodes.PAID_ON_TIME]
    loan_ids = Loan.objects.filter(
        account_id=account_id,
        loan_status__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD, LoanStatusCodes.PAID_OFF,
            LoanStatusCodes.HALT
        }
    ).values_list('id', flat=True)
    grab_loan_ids = GrabLoanData.objects.filter(
        loan_id__in=loan_ids, loan_halt_date__isnull=False,
        loan_resume_date__isnull=False).values_list('loan_id', flat=True)
    payment_due_dates = Payment.objects.filter(
        loan_id__in=list(grab_loan_ids)).only('due_date').values_list(
        'due_date', flat=True)
    account_payment_set = Payment.objects.filter(
        loan_id__in=list(grab_loan_ids)).only('account_payment_id').order_by(
        'account_payment_id').values_list('account_payment_id', flat=True)

    due_dates = list(set(payment_due_dates))
    account_payment_set = list(set(account_payment_set))
    due_dates.sort()
    paid_off_status = StatusLookup.objects.get_or_none(status_code=PaymentStatusCodes.PAID_ON_TIME)
    unpaid_status = StatusLookup.objects.get_or_none(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
    max_index = 0
    start_date = datetime(2024, 1, 1)
    with transaction.atomic():
        for idx, due_date in enumerate(due_dates):
            max_index = idx
            payment_qs = Payment.objects.select_related('account_payment').filter(
                due_date=due_date, loan_id__in=loan_ids).only(
                'due_amount', 'installment_principal', 'installment_interest',
                'paid_amount', 'late_fee_amount', 'paid_interest', 'paid_principal',
                'paid_late_fee', 'id', 'account_payment_id'
            )
            payment_set = {
                'due_amount__sum': 0,
                'installment_principal__sum': 0,
                'installment_interest__sum': 0,
                'late_fee_amount__sum': 0,
                'paid_amount__sum': 0,
                'paid_principal__sum': 0,
                'paid_interest__sum': 0,
                'paid_late_fee__sum': 0
            }

            for payment in payment_qs:
                payment_set['due_amount__sum'] += payment.due_amount
                payment_set['installment_principal__sum'] += payment.installment_principal
                payment_set['installment_interest__sum'] += payment.installment_interest
                payment_set['late_fee_amount__sum'] += payment.late_fee_amount
                payment_set['paid_amount__sum'] += payment.paid_amount
                payment_set['paid_principal__sum'] += payment.paid_principal
                payment_set['paid_interest__sum'] += payment.paid_interest
                payment_set['paid_late_fee__sum'] += payment.paid_late_fee

            account_payment_id = account_payment_set[idx]
            account_payment = AccountPayment.objects.select_for_update().get(id=account_payment_id)
            account_payment.due_date = due_date
            account_payment.due_amount = float(payment_set['due_amount__sum'])
            account_payment.principal_amount = float(payment_set['installment_principal__sum'])
            account_payment.interest_amount = float(payment_set['installment_interest__sum'])
            account_payment.late_fee_amount = float(payment_set['late_fee_amount__sum'])
            account_payment.paid_amount = float(payment_set['paid_amount__sum'])
            account_payment.paid_principal = float(payment_set['paid_principal__sum'])
            account_payment.paid_interest = float(payment_set['paid_interest__sum'])
            account_payment.paid_late_fee = float(payment_set['paid_late_fee__sum'])
            if account_payment.status_id in paid_status_codes:
                account_payment.status = unpaid_status
            account_payment.save(update_fields=[
                'due_date', 'due_amount', 'principal_amount', 'interest_amount',
                'late_fee_amount', 'paid_amount', 'paid_principal',
                'paid_interest', 'paid_late_fee', 'status'
            ])
            if payment_set['due_amount__sum'] == 0:
                update_account_payment_paid_off_status(account_payment)
            else:
                update_account_payment_status_subtask(account_payment.id)
            payment_qs.update(account_payment=account_payment)
        remaining_account_payment_set = account_payment_set[max_index+1:len(account_payment_set)]
        for index, account_payment_id in enumerate(remaining_account_payment_set):
            future_date = start_date + timedelta(days=index)
            AccountPayment.objects.filter(pk=account_payment_id).update(
                due_date=future_date.date(),
                due_amount=0,
                principal_amount=0,
                interest_amount=0,
                late_fee_amount=0,
                paid_amount=0,
                paid_principal=0,
                paid_interest=0,
                paid_late_fee=0,
                late_fee_applied=0,
                status=paid_off_status
            )
        active_loan_ids = Loan.objects.filter(
            account_id=account_id,
            loan_status__in={
                LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
                LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
                LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
                LoanStatusCodes.LOAN_180DPD
            }
        )
        for loan in active_loan_ids.iterator():
            unpaid_payments = list(Payment.objects.filter(loan=loan).not_paid())
            if len(unpaid_payments) == 0:  # this mean loan is paid_off
                update_loan_status_and_loan_history(loan_id=loan.id,
                                                    new_status_code=LoanStatusCodes.PAID_OFF,
                                                    change_by_id=None,
                                                    change_reason="Loan paid off")
                loan.refresh_from_db()
                if loan.product.has_cashback:
                    make_cashback_available(loan)


@task(name='grab_loan_restructure_task', queue='grab_halt_queue')
def grab_loan_restructure_task(data, partner_id):
    from juloserver.grab.services.services import GrabRestructureHistoryLogService

    loan = Loan.objects.select_related('account').filter(
        loan_xid=data['loan_xid'],
        loan_status_id__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD
        }
    ).last()
    if not loan:
        raise JuloException("Loan not found for restructure")

    grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
    if not grab_loan_data:
        raise JuloException("Grab Loan Data not found for restructure loan-{}".format(loan.id))

    application = loan.account.last_application
    if application.partner.id != partner_id:
        raise JuloException('Application partner does not match')
    if 'action' in data and data['action'].lower() != 'restructure':
        return
    logger.info({
        "action": 'grab_loan_restructure_task',
        "loan_xid": loan.loan_xid,
        "halt_date": "Restructuring Loan"
    })
    grab_loan_data.is_repayment_capped = True
    grab_loan_data.restructured_date = timezone.localtime(timezone.now())
    grab_loan_data.save(update_fields=['is_repayment_capped', 'udate',
                                       'restructured_date'])
    tomorrow_trigger_time = timezone.localtime(timezone.now() + timedelta(
        days=1)).replace(hour=1, minute=0)
    trigger_grab_refinance_email.apply_async((loan.id,), eta=tomorrow_trigger_time)
    trigger_grab_loan_sync_api_async_task.apply_async((loan.id,))

    service = GrabRestructureHistoryLogService()
    restructure_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S+0700")
    service.create_restructure_history_entry_bulk(
        datas=[{"loan_id": loan.id, "restructure_date": restructure_date}],
        is_restructured=True
    )


@task(name='grab_loan_restructure_revert_task', queue='grab_halt_queue')
def grab_loan_restructure_revert_task(data, partner_id):
    from juloserver.grab.services.services import GrabRestructureHistoryLogService

    loan = Loan.objects.filter(
        loan_xid=data['loan_xid'],
        loan_status_id__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD
        }
    ).last()
    if not loan:
        raise JuloException("Loan not found for restructure")

    grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
    if not grab_loan_data:
        raise JuloException("Grab Loan Data not found for restructure loan-{}".format(loan.id))

    application = loan.account.last_application
    if application.partner.id != partner_id:
        raise JuloException('Application partner does not match')
    if 'action' in data and data['action'].lower() != 'revert':
        return
    logger.info({
        "action": 'grab_loan_restructure_task',
        "loan_xid": loan.loan_xid,
        "halt_date": "Restructuring Loan"
    })
    if not grab_loan_data.is_repayment_capped:
        return
    grab_loan_data.is_repayment_capped = False
    grab_loan_data.save(update_fields=['is_repayment_capped', 'udate'])

    service = GrabRestructureHistoryLogService()
    service.create_restructure_history_entry_bulk(
        datas=[{"loan_id": loan.id, "restructure_date": None}],
        is_restructured=False
    )


@task(queue='grab_halt_queue')
def grab_early_write_off_task(data, partner_id):
    loan = Loan.objects.select_related('account').filter(
        loan_xid=data['loan_xid'],
        loan_status_id__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD
        }
    ).last()
    if not loan:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "Loan Not found with matching parameters",
            "data": data
        })
        raise JuloException("Loan not found for restructure")

    grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
    if not grab_loan_data:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "Grab Loan Data not found for loan_id",
            "loan_id": loan.id
        })
        raise JuloException("Grab Loan Data not found for restructure loan-{}".format(loan.id))

    application = loan.account.last_application
    if application.partner.id != partner_id:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "application_partner doesn't match with partner_id",
            "application_partner": application.partner.id,
            "partner_id": partner_id
        })
        raise JuloException('Application partner does not match')
    if 'action' in data and data['action'].lower() != 'early_write_off':
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "Invalid Action for write off"
        })
        return
    logger.info({
        "task": 'grab_early_write_off_task',
        "loan_xid": loan.loan_xid,
        "action": "Early Write Off triggered"
    })
    grab_loan_data.is_early_write_off = True
    grab_loan_data.early_write_off_date = timezone.localtime(timezone.now())
    grab_loan_data.save(update_fields=['is_early_write_off', 'udate',
                                       'early_write_off_date'])
    trigger_grab_loan_sync_api_async_task.apply_async((loan.id,))
    logger.info({
        "task": 'grab_early_write_off_task',
        "loan_xid": loan.loan_xid,
        "action": "Early Write Off Finished"
    })


@task(queue='grab_halt_queue')
def grab_early_write_off_revert_task(data, partner_id):
    loan = Loan.objects.select_related('account').filter(
        loan_xid=data['loan_xid'],
        loan_status_id__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD
        }
    ).last()
    if not loan:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "Loan Not found with matching parameters",
            "data": data
        })
        raise JuloException("Loan not found for restructure")

    grab_loan_data = GrabLoanData.objects.filter(loan=loan).last()
    if not grab_loan_data:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "Grab Loan Data not found for loan_id",
            "loan_id": loan.id
        })
        raise JuloException("Grab Loan Data not found for restructure loan-{}".format(loan.id))

    application = loan.account.last_application
    if application.partner.id != partner_id:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "application_partner doesn't match with partner_id",
            "application_partner": application.partner.id,
            "partner_id": partner_id
        })
        raise JuloException('Application partner does not match')
    if 'action' in data and data['action'].lower() != 'revert':
        logger.exception({
            "task": 'grab_early_write_off_task',
            "loan_xid": loan.loan_xid,
            "action": "Invalid Action for write off",
            "data": data
        })
        return
    logger.info({
        "task": 'grab_early_write_off_task',
        "loan_xid": loan.loan_xid,
        "action": "Early Write Off Revert triggered"
    })
    grab_loan_data.is_early_write_off = False
    grab_loan_data.save(update_fields=['is_early_write_off', 'udate'])
    logger.info({
        "task": 'grab_early_write_off_task',
        "loan_xid": loan.loan_xid,
        "action": "Early Write Off Revert Finished"
    })


@task(queue="grab_halt_queue")
def grab_referral_program_task(row_data):
    serializer = GrabReferralSerializer(data=row_data)
    if serializer.is_valid():
        data = serializer.data
        partner_id = row_data['partner_id']
    else:
        logger.info({
            "action": "grab_referral_program_task",
            "status": "grab_referral_program_task_failed_serializer",
            "row_data": row_data,
            "serializer_valid": serializer.is_valid(),
            "serialized_errors": serializer.errors
        })
        return
    phone_number = format_nexmo_voice_phone_number(data['phone_number'])
    grab_customer_data = GrabCustomerData.objects.filter(
        phone_number=phone_number,
        customer_id__isnull=False
    ).last()
    if not grab_customer_data:
        logger.exception({
            "task": 'grab_referral_program_task',
            "customer_id": data['phone_number'],
            "action": "Grab customer data Not found with matching parameters",
            "data": data
        })
        raise JuloException("Grab Customer with {} is not "
                            "found for referral Program".format(phone_number))
    customer = grab_customer_data.customer
    if not customer:
        logger.exception({
            "task": 'grab_referral_program_task',
            "customer_id": data['phone_number'],
            "action": "Customer Not found with matching parameters",
            "data": data
        })
        raise JuloException('Customer with {} is not '
                            'found for referral Program'.format(phone_number))

    last_grab_application = customer.application_set.select_related(
        'partner').filter(
        product_line__product_line_code__in=ProductLineCodes.grab()
    ).last()
    if not last_grab_application:
        logger.exception({
            "task": 'grab_referral_program_task',
            "customer_id": data['phone_number'],
            "action": "Application 190 Not found with matching parameters",
            "data": data
        })
        raise JuloException("Application not found for Grab "
                            "referral Program with customer_id: {}".format(customer.id))

    if last_grab_application.partner.id != partner_id:
        logger.exception({
            "task": 'grab_early_write_off_task',
            "application_id": last_grab_application.id,
            "action": "application_partner doesn't match with partner_id",
            "application_partner": last_grab_application.partner.id,
            "partner_id": partner_id
        })
        raise JuloException('Application({}) partner does not match for Referral '
                            'Program partner({})'.format(last_grab_application.partner.id, partner_id))

    if 'action' in data and data['action'].lower() != 'referral':
        logger.exception({
            "task": 'grab_referral_program_task',
            "customer_id": customer.id,
            "action": "Invalid Action for referral",
            "data": data
        })
        return

    current_whitelist = GrabReferralWhitelistProgram.objects.filter(is_active=True).last()
    if current_whitelist:
        GrabCustomerReferralWhitelistHistory.objects.get_or_create(
            grab_referral_whitelist_program=current_whitelist,
            customer=customer
        )
        GrabAccountPageService().check_and_generate_referral_code(
            customer, is_creation_flag=True)

@task(queue='partner_axiata_global_queue')
def send_sign_axiata_sphp_email(application_id):
    application = Application.objects.filter(id=application_id).last()
    if not application:
        logger.error({
            'task': "send_sign_axiata_sphp_email",
            'message': "application not found",
            'application_id': application_id
        })
        return

    julo_email_client = get_julo_email_client()
    subject = "Setujui Perjanjian Kamu Sekarang"
    name_from = 'JULO'
    email_from = EmailDeliveryAddress.CS_JULO
    email_to = application.email
    reply_to = EmailDeliveryAddress.CS_JULO

    loan_xid = application.loan.loan_xid

    # TODO: should move to env variable
    sign_link = "https://axiata-staging.julo.co.id/sphp"
    if settings.ENVIRONMENT == "staging":
        sign_link = "https://axiata-staging.julo.co.id/sphp"
    elif settings.ENVIRONMENT == "uat":
        sign_link = "https://axiata-uat.julo.co.id/sphp"
    elif settings.ENVIRONMENT == "prod":
        sign_link = "https://axiata.julo.co.id/sphp"

    sign_link = sign_link + "?loan_xid={}".format(loan_xid)
    name = application.first_name_only
    email_context = {
        "name": name,
        "sign_link": sign_link,
    }
    email_template = render_to_string("email_axiata_sphp_sign.html", context=email_context)
    status, _, headers = julo_email_client.send_email(
        subject,
        email_template,
        email_to,
        email_from=email_from,
        name_from=name_from,
        reply_to=reply_to
    )
    EmailHistory.objects.create(
        status=status,
        sg_message_id=headers['X-Message-Id'],
        customer_id=application.customer_id,
        application_id=application.id,
        to_email=email_to,
        subject=subject,
        message_content=email_template,
        template_code='{}_177_email'.format(application.partner.name)
    )

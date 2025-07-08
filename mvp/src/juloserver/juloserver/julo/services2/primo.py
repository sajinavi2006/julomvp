from builtins import str
from builtins import object
import logging

from django.conf import settings
from django.db import transaction
from django.contrib.auth.models import User

from app_status.models import ApplicationLockedMaster, ApplicationLocked
from celery import task

from ..clients import get_primo_client
from ..statuses import ApplicationStatusCodes, PaymentStatusCodes
from ..models import PrimoDialerRecord, Skiptrace, ApplicationHistory, Payment
from ..utils import format_national_phone_number, display_rupiah

logger = logging.getLogger(__name__)

BASE_URL = settings.BASE_URL


class PrimoLeadStatus(object):

    SENT = 'SENT'
    FAILED = 'FAILED'
    DELETED = 'DELETED'
    COMPLETED = 'COMPLETED'
    INITIATED = 'INITIATED'
    DEPRECATED = 'DEPRECATED'


MAPPING_CALL_RESULT = {
    'N': 4,
    'WPC': 5,
    'RPC': 6
}


PRIMO_LIST_ENV_MAPPING = {
    "dev": {
        ApplicationStatusCodes.DOCUMENTS_VERIFIED: 1007,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING: 1007,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL: 1004,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER: 1005,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER: 1010,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING: 1010,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL: 1003,
        PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS: 9001
    },
    "staging": {
        ApplicationStatusCodes.DOCUMENTS_VERIFIED: 1007,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING: 1007,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL: 1004,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER: 1005,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER: 1010,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING: 1010,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL: 1003,
        PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS: 9001
    },
    "prod": {
        ApplicationStatusCodes.DOCUMENTS_VERIFIED: 1007,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING: 1007,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL: 1004,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER: 1005,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER: 1006,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING: 1006,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL: 1003,
        PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS: 1201
    }
}


def construct_primo_data(application, phone_number):
    list_id = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][application.status]
    data = {
        'function': 'add_lead',
        'phone_number': phone_number,
        'alt_phone': phone_number,
        'email': application.email,
        'custom_fields': 'Y',
        'list_id': list_id,
        'comments': 'NoComments',
        'Due_Date': None,
        'Due_Amount': None,
        'Disbursement_Date': None,
        'genderiden': application.gender,
        'Loan_Purpose_Desc': application.loan_purpose_desc,
        'Application_ID': application.application_xid,
        'Fullname': application.fullname_with_title,
        'Loan_Purpose': application.loan_purpose,
        'Application_Status': application.status,
        'CRM_Link': ''.join([BASE_URL, '/app_status/redirect/', str(application.id)])
    }

    if application.status >= ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        due_date = application.loan.payment_set.first().due_date
        data['Due_Date'] = due_date.strftime('%d-%m-%Y')
        data['Due_Amount'] = application.loan.payment_set.first().due_amount

    if application.status >= ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
        data['Disbursement_Date'] = application.loan.fund_transfer_ts.strftime('%d-%m-%Y')

    if application.status < ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        data['Loan_Amount'] = application.loan_amount_request
        data['Loan_Duration'] = application.loan_duration_request
    else:
        data['Loan_Amount'] = application.loan.loan_amount
        data['Loan_Duration'] = application.loan.loan_duration

    if application.status == ApplicationStatusCodes.DOCUMENTS_VERIFIED:
        data['Company_Name'] = application.company_name

    return data

def construct_primo_data_payment(payment, status, phone_number, contact_source):
    list_id = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][status]
    loan = payment.loan
    application = loan.application
    data = {
        'function': 'add_lead',
        'list_id': list_id,
        'custom_fields': 'Y',
        'CRM_Link': ''.join([BASE_URL, '/payment_status/change_status/', str(payment.id)]),
        'Application_ID': application.application_xid,
        'comments': 'NoComments',
        'phone_number': phone_number,
        'alt_phone': phone_number,
        'fullname': application.fullname_with_title,
        'product_line': str(application.product_line.product_line_type),
        'due_amount': display_rupiah(payment.due_amount),
        'due_date': payment.due_date.strftime("%d %B %Y"),
        'contact_source': str(contact_source)
    }

    return data


def primo_locked_app(application, user):
    with transaction.atomic():
        ret_master = ApplicationLockedMaster.create(
            user=user, application=application, locked=True)
        if ret_master:
            ApplicationLocked.create(
                application=application, user=user,
                status_code_locked=application.application_status.status_code)
            logger.info({
                "action": "lock_application_from_primo",
                "application_id": application.id,
                "status": "success"
            })
            return True
    logger.warn({
        "action": "lock_application_from_primo",
        "application_id": application.id,
        "status": "failed"
    })
    return False

def primo_locked_payment(payment, user):
    with transaction.atomic():
        ret_master = PaymentLockedMaster.create(
            user=user, payment=payment, locked=True)
        if ret_master:
            PaymentLocked.create(
                payment=payment, user=user,
                status_code_locked=payment.payment_status.status_code)
            logger.info({
                "action": "lock_payment_from_primo",
                "payment_id": payment.id,
                "status": "success"
            })
            return True
    logger.warn({
        "action": "lock_payment_from_primo",
        "payment_id": payment.id,
        "status": "failed"
    })
    return False

def primo_unlocked_app(app_obj, user_obj):
    app_locked_master = ApplicationLockedMaster.objects.get_or_none(application=app_obj)

    with transaction.atomic():
        if app_locked_master:
            app_locked = ApplicationLocked.objects.filter(
                application=app_obj, user_lock=user_obj, locked=True).last()

            if app_locked:
                app_locked.locked = False
                app_locked.user_unlock = user_obj
                app_locked.save()
                # delete master locked
                app_locked_master.delete()
                logger.info({
                    "action": "unlock_application_from_primo",
                    "application_id": app_obj.id,
                    "status": "success"
                })
                return True
    logger.warn({
        "action": "unlock_application_from_primo",
        "application_id": app_obj.id,
        "status": "failed"
    })
    return False

def primo_unlocked_payment(payment, user):
    payment_locked_master = PaymentLockedMaster.objects.get_or_none(payment=payment)

    with transaction.atomic():
        if payment_locked_master:
            payment_locked = PaymentLocked.objects.filter(
                payment=payment, user_lock=user, locked=True).last()

            if payment_locked:
                payment_locked.locked = False
                payment_locked.user_unlock = user
                payment_locked.save()
                # delete master locked
                payment_locked_master.delete()
                logger.info({
                    "action": "unlock_payment_from_primo",
                    "payment_id": payment.id,
                    "status": "success"
                })
                return True
    logger.warn({
        "action": "unlock_payment_from_primo",
        "payment_id": payment.id,
        "status": "failed"
    })
    return False

def get_recomendation_skiptrace(app_obj):
    customer_phone = Skiptrace.objects.filter(customer_id=app_obj.customer_id)\
        .order_by('id','-effectiveness')\
        .exclude(effectiveness__lt=-15)
    if app_obj.status in [
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
        ApplicationStatusCodes.PRE_REJECTION
    ]:
        phones = customer_phone.filter(
            contact_source__in=['mobile_phone_number_1',
                                'mobile_phone',
                                'mobile_phone_1',
                                'mobile_phone_2',
                                'mobile_phone_3',
                                'mobile phone',
                                'mobile phone 1',
                                'mobile phone 2',
                                'mobile_phone_lain',
                                'mobile_phone1',
                                'mobile_phone2',
                                'mobile',
                                'mobile 1',
                                'mobile 2',
                                'mobile2',
                                'mobile 3',
                                'mobile aktif',
                                'App mobile phone',
                                'App_mobile_phone'])

    if app_obj.status in [ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING]:
        phones = customer_phone.filter(
            contact_source__contains='company')

    return phones.first()

def get_recomendation_skiptrace_payment(customer):
    customer_phone = Skiptrace.objects.filter(customer=customer)\
        .order_by('id','-effectiveness')\
        .exclude(effectiveness__lt=-20)
    phones = customer_phone.filter(
        contact_source__in=['mobile phone 1',
                            'mobile_phone1',
                            'mobile_phone 1',
                            'mobile_phone_1',
                            'Mobile phone 1',
                            'Mobile_phone_1',
                            'Mobile_Phone_1',
                            'mobile_phone1_1',
                            'mobile phone 2',
                            'mobile_phone2',
                            'mobile_phone 2',
                            'mobile_phone_2',
                            'Mobile phone 2',
                            'Mobile_phone2',
                            'Mobile_phone_2',
                            'MOBILE_PHONE_2'])
    # get alternative phone number mobile_phone_xx
    if phones:
        phones = customer_phone.filter(contact_source__istartswith='mobile_phone_')
    return phones.first()

def send_data_payment(payment, status):
    loan = payment.loan
    customer = loan.customer
    skiptrace = get_recomendation_skiptrace_payment(customer)
    phone_number = format_national_phone_number(str(skiptrace.phone_number))
    lead_data = construct_primo_data_payment(payment, status, phone_number, skiptrace.contact_source)
    primo_client = get_primo_client()
    results = primo_client.upload_leads([lead_data])
    list_id = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][status]
    for result in results:  # should only be 1 item
        PrimoDialerRecord.objects.create(
            application=loan.application,
            payment=payment,
            payment_status=payment.payment_status,
            phone_number=phone_number,
            lead_status=PrimoLeadStatus.SENT,
            list_id=list_id,
            lead_id=result['lead_id'],
            skiptrace=skiptrace)

def delete_from_primo_courtesy_calls(application):
    list_id = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL]
    primo_dialer_record = PrimoDialerRecord.objects.filter(
        application=application, list_id=list_id, lead_status=PrimoLeadStatus.SENT
    ).last()
    if primo_dialer_record:
        primo_client = get_primo_client()
        primo_client.delete_lead(primo_dialer_record.lead_id)
        primo_dialer_record.lead_status = PrimoLeadStatus.DELETED
        primo_dialer_record.save()

def delete_from_primo_payment(payment, status):
    list_id = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][status]
    primo_dialer_record = PrimoDialerRecord.objects.filter(
        payment=payment, list_id=list_id, lead_status=PrimoLeadStatus.SENT,
        payment_status=status).last()
    if primo_dialer_record:
        primo_client = get_primo_client()
        primo_client.delete_lead(primo_dialer_record.lead_id)
        primo_dialer_record.lead_status = PrimoLeadStatus.DELETED
        primo_dialer_record.save()

def process_callback_primo_payment(data, record, payment):
    user = User.objects.filter(username=data['agent_id'].lower()).last()
    with transaction.atomic():
        if user:
            if data['call_status'] == 'CONNECTED':
                primo_locked_payment(payment, user)
            else:
                primo_unlocked_payment(payment, user)
                primo_update_skiptrace(record, user, data['call_status'])
                if data['call_status'] in ['RPC','WPC','NA','B']:
                    delete_from_primo_payment(payment, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS)
                if data['call_status'] in ['RPC']:
                    payment.is_collection_called = True
                elif data['call_status'] in ['WPC','NA','B']:
                    other_phone = get_recomendation_skiptrace_payment(payment.loan.customer)
                    if other_phone:
                        send_data_payment(payment, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS)
                    else:
                        payment.is_whatsapp = True
                record.lead_status = PrimoLeadStatus.COMPLETED
                payment.save(update_fields=['is_collection_called',
                                            'is_whatsapp',
                                            'udate'])
        else:
            if data['call_status'] != 'DROP':
                record.retry_times += 1

        record.call_status = data['call_status']
        record.agent = data['agent_id']
        record.save()

# --------------------- Schedule Primo ----------------------------

@task(name='scheduled_send_courtesy_call_data')
def scheduled_send_courtesy_call_data():

    # All applications for courtesy calls today

    courtesy_calls_history = ApplicationHistory.objects.uncalled_app_list(
        status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
    courtesy_calls_application_ids = [courtesy.application.id for courtesy in courtesy_calls_history]

    # Delete leads in primo not in range for courtesy calls today

    primo_records = PrimoDialerRecord.objects.filter(
        lead_status=PrimoLeadStatus.SENT,
        application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
    for record in primo_records:
        if record.application_id not in courtesy_calls_application_ids:
            record.lead_status = PrimoLeadStatus.DELETED
            record.save()
            if record.lead_id:
                primo_client = get_primo_client()
                primo_client.delete_primo_lead_data(record.lead_id)

    # Get remaining leads in primo

    primo_records = PrimoDialerRecord.objects.filter(
        lead_status=PrimoLeadStatus.SENT,
        application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
    courtesy_calls_applications = [
        courtesy.application for courtesy in courtesy_calls_history]
    current_applications_in_primo = [record.application for record in primo_records]

    # Upload phone number to primo and add lead in the DB

    for application in courtesy_calls_applications:
        if application not in current_applications_in_primo:

            skiptrace = get_recomendation_skiptrace(application)
            phone_number = format_national_phone_number(str(skiptrace.phone_number))
            lead_data = construct_primo_data(application, phone_number)
            primo_client = get_primo_client()
            results = primo_client.upload_leads([lead_data])
            list_id = PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL]
            for result in results:  # should only be 1 item
                PrimoDialerRecord.objects.create(
                    application=application,
                    application_status=application.application_status,
                    phone_number=phone_number,
                    lead_status=PrimoLeadStatus.SENT,
                    list_id=list_id,
                    lead_id=result['lead_id'],
                    skiptrace=skiptrace)


@task(name='scheduled_send_t_minus_one_data')
def scheduled_send_t_minus_one_data():

    # Delete leads in primo not in due_date T - 1
    primo_records = PrimoDialerRecord.objects.filter(
        lead_status=PrimoLeadStatus.SENT,
        payment_status=PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS)
    for record in primo_records:
        record.lead_status = PrimoLeadStatus.DELETED
        record.save()
        if record.lead_id:
            primo_client = get_primo_client()
            primo_client.delete_primo_lead_data(record.lead_id)

    # All payment T - 1
    qs = Payment.objects.normal()
    payments =  qs.dpd_to_be_called().due_soon(due_in_days=1)

    # Upload phone number to primo and add lead in the DB
    for payment in payments:
        send_data_payment(payment, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS)

@task(name='delete_courtesy_call_data')
def delete_courtesy_call_data():
    primo_client = get_primo_client()
    response = primo_client.delete_primo_list_data(
        PRIMO_LIST_ENV_MAPPING[settings.ENVIRONMENT][ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL])

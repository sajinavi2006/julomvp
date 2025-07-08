from builtins import range
from juloserver.julo.models import SmsHistory, Application
from ..constants import SmsStatusType, SmsStreamsStatus
from juloserver.julo.utils import format_e164_indo_phone_number
from django.utils import timezone
import logging
logger = logging.getLogger(__name__)


def update_sms_details(data, is_stream=False):
    if not data:
        return

    if not is_stream:
        if data['event_code'] not in list(SmsStatusType.keys()):
            return
        status = SmsStatusType[data['event_code']]
    else:
        if data['event_code'] not in list(SmsStreamsStatus.keys()):
            return
        status = SmsStreamsStatus[data['event_code']]
    application_id = data['application_id']
    data['phone_number_type'] = None
    list_account_payment_id = [data['account_payment_id']]
    if data['account_payment_id']:
        flag_account_payment = True
    else:
        flag_account_payment = False
    for i in range(1, 6):
        list_account_payment_id.append(data['account{}_payment_id'.format(i)])
        if data['account{}_payment_id'.format(i)]:
            flag_account_payment = True
    for account_payment_id in list_account_payment_id:
        if not account_payment_id:
            continue
        update_sms(data, application_id, status, account_payment_id)
    if not flag_account_payment:
        update_sms(data, application_id, status)


def update_sms(data, application_id, status, account_payment_id=None):
    if application_id and data['to_mobile_phone']:
        application = Application.objects.get_or_none(id=application_id)
        if application:
            phone_types = ['mobile_phone_1', 'new_mobile_phone', 'mobile_phone_2',
                           'kin_mobile_phone', 'close_kin_mobile_phone',
                           'spouse_mobile_phone', 'landlord_mobile_phone',
                           'additional_contact_1_number', 'additional_contact_2_number',
                           'company_phone_number']
            for phone_type in phone_types:
                if eval('format_e164_indo_phone_number(application.' + phone_type + ')') == \
                        format_e164_indo_phone_number(data['to_mobile_phone']):
                    data['phone_number_type'] = phone_type
    if not data['phone_number_type']:
        data['phone_number_type'] = 'other'
    sms_history_qs = SmsHistory.objects.filter(customer_id=data['customer_id'],
                                               template_code=data['template_code'])
    if data['to_mobile_phone']:
        sms_history_qs = sms_history_qs.filter(to_mobile_phone=format_e164_indo_phone_number(
                                                data['to_mobile_phone']))
    if account_payment_id:
        sms_history_qs = sms_history_qs.filter(account_payment_id=account_payment_id)
    sms_history = sms_history_qs.last()
    if sms_history and sms_history.cdate.date() != timezone.localtime(timezone.now()).date():
        sms_history = None
    if not sms_history:
        SmsHistory.objects.create(
            status=status,
            template_code=data['template_code'],
            to_mobile_phone=format_e164_indo_phone_number(data['to_mobile_phone']),
            phone_number_type=data['phone_number_type'],
            application_id=data['application_id'] or None,
            customer_id=data['customer_id'],
            payment_id=data['payment_id'],
            delivery_error_code=None,
            comms_provider_id=None,
            is_otp=False,
            source=data['event_source'],
            message_id=None,
            message_content=None,
            account_payment_id=account_payment_id
        )
    else:
        sms_history.update_safely(status=status)

import pickle
from builtins import str
import json
import logging
import re
import time
from celery import task
from dateutil.relativedelta import relativedelta
from datetime import timedelta, date
import datetime

from django.db import connection
from django.forms import model_to_dict
from django.utils import timezone
from django.db.models import F, Q, Prefetch
from django.template.loader import render_to_string

from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.account.models import ExperimentGroup

from ..clients import (
    get_voice_client,
    get_voice_client_v2,
    get_julo_pn_client,
    get_julo_sentry_client,
    get_julo_sms_client,
)

from ..clients.voice import VoiceApiError
from ..constants import (
    ExperimentConst,
    VoiceTypeStatus,
    VendorConst,
    ReminderTypeConst,
    AddressPostalCodeConst,
    NexmoRobocallConst,
    FeatureNameConst,
    WorkflowConst,
)
from ..exceptions import JuloException, VoiceNotSent
from ..models import (
    ExperimentSetting,
    Payment,
    PaymentExperiment,
    VoiceCallRecord,
    RobocallTemplate,
    SmsHistory,
    VendorDataHistory,
    Loan,
    CommsBlocked,
    FeatureSetting,
)

from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.constants import CovidRefinancingConst

from juloserver.loan_refinancing.services.loan_related import (get_payments_refinancing_pending_by_dpd,
                                                               get_payments_refinancing_pending_by_date_approved)
from juloserver.streamlined_communication.models import StreamlinedCommunication
from ..product_lines import ProductLineCodes
from ..services2 import encrypt
from ..services2.experiment import (
    bulk_payment_robocall_experiment,
    get_experiment_setting_by_code,
    get_payment_experiment_ids,
)
from ..services2.reminders import Reminder
from ..statuses import PaymentStatusCodes
from ..utils import display_rupiah, format_e164_indo_phone_number
from ..helpers.reminders import parse_template_reminders
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from django.conf import settings
from juloserver.julo.services2.sms import create_sms_history
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    RobocallType,
    CardProperty,
)
from juloserver.streamlined_communication.services import (
    process_streamlined_comm_without_filter,
    process_convert_params_to_data,
    filter_streamlined_based_on_partner_selection,
    exclude_experiment_excellent_customer_from_robocall,
    get_list_account_ids_late_fee_experiment,
    process_streamlined_comm,
    determine_julo_gold_for_streamlined_communication,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.pause_reminder import \
    check_account_payment_is_blocked_comms
from juloserver.julo.services import (
    check_payment_is_blocked_comms,
    get_application_phone_number,
    is_last_payment_status_notpaid,
)
from juloserver.streamlined_communication.tasks import record_customer_excellent_experiment
from juloserver.monitors.notifications import send_slack_bot_message
from juloserver.streamlined_communication.utils import (
    payment_reminder_execution_time_limit,
    check_payment_reminder_time_limit,
)
from juloserver.autodebet.models import AutodebetAccount
from juloserver.julo.constants import WorkflowConst
from juloserver.minisquad.constants import ExperimentConst as ExperimentConstMiniSquad
from juloserver.grab.services.robocall_services import filter_payments_based_on_c_score, \
    filter_based_on_feature_setting_robocall
from juloserver.account.constants import AccountConstant
from ...grab.constants import GrabRobocallConstant
from ...grab.models import GrabLoanData
from juloserver.credgenics.services.utils import (
    is_comms_block_active,
    get_credgenics_account_ids,
    is_account_payment_owned_by_credgenics_customer,
)
from juloserver.credgenics.constants.feature_setting import CommsType
from juloserver.pii_vault.constants import PiiSource
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    is_account_payment_owned_by_omnichannel_customer,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()
product_line_codes = ProductLineCodes.mtl() + ProductLineCodes.stl() + ProductLineCodes.pede() + \
    ProductLineCodes.julo_one() + ProductLineCodes.dana() + ProductLineCodes.turbo()
# T-3 three time robocall experiment
ROBO_TMIN3_EXPERIMENT_CRITERIA = ['4', '5', '6']
# send sms success robocall experiment criteria last loan_id
ROBO_SEND_SMS_CRITERIA = ['7', '8', '9']
COMMUNICATION_PLATFORM = CommunicationPlatform.ROBOCALL

NEXMO_DELAY_PER_TASK = 0.133    # 8 RPS per tasks


class VoiceServiceError(JuloException):
    pass


def get_template_tag(templates, context):
    result_list = []
    for template in templates:
        parameters = re.findall(r'<(.*?)>', template)
        for parameter in parameters:
            template = template.replace('<{}>'.format(parameter), str(context[parameter]))
        result_list.append(template)
    result = '.'.join(result_list)
    return {"action": "talk", "voiceName": "Damayanti", "text": result}


def get_promo_messages(main_context):
    now = timezone.localtime(timezone.now())
    promo_messages = RobocallTemplate.objects.filter(
        start_date__lte=now, end_date__gte=now,
        template_category=RobocallTemplate.PROMOTIONAL_MESSAGES).order_by('cdate')
    if not promo_messages:
        return None
    else:
        messages = []
        for message in promo_messages:
            template = message.text.split('.')
            formatted_message = get_template_tag(template, main_context)
            messages.append(formatted_message)
    return messages


def get_voice_template(
    voice_type, identifier, streamlined_id=None,
    test_robocall_content=None, is_j1=False, is_grab=False,
    is_jturbo=False,
):
    if is_j1 or is_jturbo:
        account_payment = AccountPayment.objects.get_or_none(pk=identifier)
        if not account_payment:
            return None
    elif is_grab:
        payment = Payment.objects.get_or_none(pk=identifier)
        if not payment:
            return None
        account_payment = payment.account_payment
    else:
        payment = Payment.objects.get_or_none(pk=identifier)
        if not payment:
            return None

    allowed_voice_types = (
        VoiceTypeStatus.PAYMENT_REMINDER,
        VoiceTypeStatus.PTP_PAYMENT_REMINDER,
    )
    if voice_type not in allowed_voice_types:
        return None

    grab_dpd = 0
    cashback_counter_for_customer = 0
    if is_j1 or is_grab or is_jturbo:
        account = account_payment.account
        loan = account.loan_set.last()
        product_type = ''
        cashback_counter_for_customer = account.cashback_counter_for_customer
        app_set = account.application_set
        if is_jturbo:
            product_type = 'JTurbo'
            application = app_set.filter(workflow__name=WorkflowConst.JULO_STARTER).last()
            due_date = account_payment.due_date
            due_amount = account_payment.due_amount
            payment_or_account_payment = account_payment
            extra_url = "?product=" + product_type
        elif is_grab:
            product_type = 'GRAB'
            loan = payment.loan
            application = app_set.last()
            due_date = payment.due_date
            due_amount = payment.due_amount
            payment_or_account_payment = account_payment
            grab_dpd = int(payment.due_late_days_grab)
            extra_url = "?product=" + product_type
        else:
            product_type = 'J1'
            application = app_set.last()
            due_date = account_payment.due_date
            due_amount = account_payment.due_amount
            payment_or_account_payment = account_payment
            extra_url = "?product=" + product_type

    else:
        loan = payment.loan
        due_date = payment.due_date
        due_amount = payment.due_amount
        application = payment.loan.application
        product_type = str(payment.loan.application.product_line.product_line_type)[:-1]
        # handle PEDE template as requirement
        if payment.loan.application.product_line_id in ProductLineCodes.pede():
            product_type = 'STL'
        payment_or_account_payment = payment
        extra_url = ''

    application_detokenized = collection_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['fullname'],
    )
    fullname = application_detokenized.fullname
    first_name_only = application.first_name_only_by_str(fullname)
    first_name_with_title = application.first_name_with_title_by_str(fullname)

    main_context = {
        'firstname': first_name_only,
        'fullname': fullname,
        'name_with_title': first_name_with_title if first_name_with_title else first_name_only,
        'cashback_multiplier': payment_or_account_payment.cashback_multiplier,
        'payment_number': payment_or_account_payment.payment_number,
        'due_date': due_date.strftime('%d-%m-%Y'),
        'due_date_with_bonus': (due_date - relativedelta(days=4)).strftime('%d-%m-%Y'),
        'julo_bank_name': loan.julo_bank_name,
        'due_amount': due_amount,
        'robocall_cashback_counter': cashback_counter_for_customer,
    }
    if is_grab:
        main_context['card_grab_dpd'] = int(grab_dpd)
        main_context['grab_due_amount'] = loan.get_total_outstanding_due_amount()

    if voice_type == VoiceTypeStatus.PAYMENT_REMINDER:
        template = ''

        today_date = timezone.localtime(timezone.now()).date()
        dayplus5 = today_date + relativedelta(days=5)
        dayplus3 = today_date + relativedelta(days=3)
        current_time = timezone.localtime(timezone.now()).strftime('%H')
        if int(current_time) < 12:
            greet = 'pagi'
        elif int(current_time) < 18:
            greet = 'siang'
        else:
            greet = 'sore'

        if streamlined_id:
            streamline = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
            dpd = streamline.dpd
            days_before_due_date = None
            if is_grab:
                days_before_due_date = (due_date - today_date).days
            elif dpd > 0:
                days_before_due_date = dpd
            elif dpd is not None:
                days_before_due_date = abs(dpd)
        else:
            if due_date == dayplus5:
                days_before_due_date = 5
            else:
                days_before_due_date = 3

        template = parse_template_reminders(due_date, product_type)
        # voice call record update is experiment
        # voice_call_record = VoiceCallRecord.objects.filter(voice_identifier=payment.id).order_by('cdate').last()
        # if voice_call_record:
        #     voice_call_record.update_safely(is_experiment=False)
        # today = timezone.now().date()
        # No Robocall experiment for particular loan /payment id's  this season so commenting the below code snippet.
        # use experiment template if experiment
        # roboscript_experiment_ids = get_payment_experiment_ids(today, ExperimentConst.ROBOCALL_SCRIPT)
        # if payment.id in roboscript_experiment_ids:
        #     payment_experiment = PaymentExperiment.objects.filter(payment=payment, cdate__date=today).last()
        #     experiment_setting = payment_experiment.experiment_setting
        #     start_date = datetime.datetime(experiment_setting.start_date.year,
        #                                    experiment_setting.start_date.month,
        #                                    experiment_setting.start_date.day).date()
        #     end_date = datetime.datetime(experiment_setting.end_date.year,
        #                                  experiment_setting.end_date.month,
        #                                  experiment_setting.end_date.day).date()
        #     if start_date <= today_date <= end_date and \
        #             (payment.due_date == dayplus3 or payment.due_date == dayplus5) and \
        #             int(str(loan_id)[-1:]) in [7, 8, 9]:
        #         template = parse_template_reminders(period + '_' + product_type)
        #
        #     voice_call_record.is_experiment = True
        #     voice_call_record.experiment_id = payment_experiment.experiment_setting_id

        # TO-DO it should have extra params for J1
        input_webhook_url = ''.join([settings.BASE_URL,
                                     '/api/integration/v1/callbacks/voice-call/',
                                     VoiceTypeStatus.PAYMENT_REMINDER,
                                     '/',
                                     str(identifier),
                                     extra_url,
                                     ])
        context = {
            'firstname': first_name_only,
            'fullname': fullname,
            'name_with_title': first_name_with_title,
            'cashback_multiplier': payment_or_account_payment.cashback_multiplier,
            'payment_number': payment_or_account_payment.payment_number,
            'due_date': due_date.strftime('%d-%m-%Y'),
            'due_date_with_bonus': (due_date - relativedelta(days=4)).strftime('%d-%m-%Y'),
            'julo_bank_name': loan.julo_bank_name,
            'due_amount': due_amount,
            'input_webhook_url': input_webhook_url,
            'greet': greet,
            'days_before_due_date': days_before_due_date
        }

        if is_grab:
            context['card_grab_dpd'] = int(grab_dpd)
            context['grab_due_amount'] = loan.get_total_outstanding_due_amount()
        else:
            context['card_grab_dpd'] = 0
            context['grab_due_amount'] = 0
        if streamlined_id:
            streamline = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
            if not streamline:
                return None
            result = process_streamlined_comm_without_filter(streamline, context)
        else:
            if test_robocall_content:
                result = process_convert_params_to_data(test_robocall_content, context)
            else:
                if not template:
                    return None
                result = render_to_string(template + '.txt', context=context)
        ncco_object = json.loads(result)
        for inner_dict in ncco_object:
            for key, value in list(inner_dict.items()):
                if str(key) != 'action' or str(value) != 'input':
                    continue
                if streamlined_id:
                    if streamline.time_out_duration:
                        inner_dict["timeOut"] = streamline.time_out_duration
                    else:
                        streamline.time_out_duration = NexmoRobocallConst.TIME_OUT_DURATION
                        streamline.save()
                else:
                    inner_dict["timeOut"] = NexmoRobocallConst.TIME_OUT_DURATION
        promotional_messages = get_promo_messages(main_context)
        if promotional_messages:
            call_back = ncco_object.pop()
            confirmation_text = ncco_object.pop()
            for promos in promotional_messages:
                ncco_object.append(promos)
            ncco_object.append(confirmation_text)
            ncco_object.append(call_back)
        # add recording option
        record_callback_url = settings.BASE_URL + '/api/integration/v1/callbacks/voice-call-recording-callback'
        record_json_params = {"action": "record",
                              "eventUrl": [record_callback_url]}

        ncco_object.insert(0, record_json_params)

        return ncco_object
    elif voice_type == VoiceTypeStatus.PTP_PAYMENT_REMINDER:
        result = []
        if not is_j1:
            ptp_robocall_template = payment.ptp_robocall_template
        else:
            oldest_payment = account_payment.payment_set.filter(
                due_amount__gt=0
            ).order_by('payment_number').first()
            ptp_robocall_template = oldest_payment.ptp_robocall_template
        ptp_robocall_template.save()
        templates = ptp_robocall_template.text.split('.')
        # TO-DO it should have extra params for J1
        input_webhook_url = ''.join([settings.BASE_URL,
                                     '/api/integration/v1/callbacks/voice-call/',
                                     VoiceTypeStatus.PTP_PAYMENT_REMINDER,
                                     '/',
                                     str(identifier),
                                     extra_url,
                                     ])
        # parameters
        name_with_title = first_name_with_title
        cashback_multiplier = payment_or_account_payment.cashback_multiplier
        payment_number = payment_or_account_payment.payment_number
        due_date_with_bonus = (due_date - relativedelta(days=4)).strftime('%d-%m-%Y')
        due_date = due_date.strftime('%d-%m-%Y')
        julo_bank_name = loan.julo_bank_name

        for template in templates:
            parameters = re.findall(r'<(.*?)>', template)
            for parameter in parameters:
                template = template.replace('<{}>'.format(parameter), str(eval(parameter)))
            text = template
            result.append({"action": "talk", "voiceName": "Damayanti", "text": text})

        # add recording option
        # TO-DO it should have extra params for J1
        record_callback_url = settings.BASE_URL + \
            '/api/integration/v1/callbacks/voice-call-recording-callback'
        record_json_params = {"action": "record", "eventUrl": [record_callback_url]}
        result.append({"action": "input", "eventUrl": [input_webhook_url],
                       "maxDigits": 1, "timeOut": NexmoRobocallConst.TIME_OUT_DURATION})
        result.insert(0, record_json_params)

        return json.loads(json.dumps(result))


def get_covid_campaign_voice_template(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None
    template = "Halo {}, ada promo diskon 40% bunga JULO yang berlaku sampai 15 April. Untuk info lebih lanjut, cek email Anda."

    application = loan.application
    if not application:
        application = loan.account.application_set.last()

    text = template.format(application.first_name_with_title)
    return [{"action": "talk", "voiceName": "Damayanti", "text": text}]


def check_robocall_active_or_not(payment):
    if payment.payment_number == 2 and payment.loan.payment_set.filter( \
            payment_number__lt=payment.payment_number).last().status == \
            PaymentStatusCodes.PAID_ON_TIME:
        return True
    elif payment.payment_number >= 3 and payment.loan.payment_set.filter(
            payment_number__in=[(payment.payment_number - 1), (payment.payment_number - 2)],
            payment_status=330).count() == 2:
        return True
    # for experiment
    elif date(2018, 7, 25) <= payment.due_date <= date(2018, 8, 6) and \
            int(str(payment.id)[-1:]) in [1, 2, 3, 4, 5]:
        # first payment experiment
        if payment.payment_number == 1:
            return True
        # bad customer experiment
        elif payment.payment_number >= 2 and payment.loan.payment_set.filter(
                payment_number__lt=payment.payment_number,\
                payment_status__gte=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD):
            return True
        else:
            return False
    else:
        return False


def bypass_agentcall_experimention(payments):
    # get experiment setting bypass agentcall
    today = timezone.localtime(timezone.now()).date()
    payment_experiment_ids = []
    bypass_agentcall_experiment = ExperimentSetting.objects.filter(
        code=ExperimentConst.AGENT_CALL_BYPASS, is_active=True,
        start_date__lte=today, end_date__gte=today).last()
    if bypass_agentcall_experiment:
        criteria = bypass_agentcall_experiment.criteria
        if 'loan_id' in criteria:
            criteria_ids = []
            splicing = None
            items = criteria['loan_id'].split(':')
            if items[0] == '#last':
                splicing = int(items[1])
                end = 10
                start = end - (splicing - 1)
                criteria_ids = items[2].split(',')
            if len(criteria_ids) > 0:
                payments = payments.extra(
                    where=["SUBSTRING(CAST(payment.loan_id as Varchar), %s, %s) in %s"],
                    params=[start, end, tuple(criteria_ids)])

        if 'dpd' in criteria:
            for dpd in criteria['dpd']:
                payment_experiment_ids += list(payments.dpd(int(dpd)).values_list('id', flat=True))

        bulk_payment_robocall_experiment(
            bypass_agentcall_experiment, payment_experiment_ids)


@task(queue='collection_high')
def mark_voice_payment_reminder(dpd_list):
    """
     init marking robocall
    """
    payments_with_robocall = Payment.objects.normal().filter(is_robocall_active__isnull=False)
    payments_with_robocall.update(is_robocall_active=None,
                                  is_success_robocall=None,
                                  is_whatsapp=False,
                                  is_whatsapp_blasted=False)

    time.sleep(2)

    payments = Payment.objects.tobe_robocall_payments(product_line_codes, dpd_list)
    # get active experiment settings
    today = timezone.localtime(timezone.now()).date()
    experiments = ExperimentSetting.objects.filter(
        code__in=[ExperimentConst.UNSET_ROBOCALL, ExperimentConst.ROBOCALL_SCRIPT],
        is_active=True, start_date__lte=today, end_date__gte=today)

    for experiment in experiments:
        criteria = experiment.criteria
        if 'loan_id' in criteria:
            criteria_ids = []
            splicing = None
            items = criteria['loan_id'].split(':')
            if items[0] == '#last':
                splicing = int(items[1])
                end = 10
                start = end - (splicing - 1)
                criteria_ids = items[2].split(',')
            if len(criteria_ids) > 0:
                payment_experiments = payments.extra(where=["right(payment.loan_id::text, %s) in %s"],
                    params=[items[1], tuple(criteria_ids)])
                if experiment.code == ExperimentConst.UNSET_ROBOCALL:
                    payments = payments.extra(
                        where=["SUBSTRING(CAST(payment_id as Varchar), %s, %s) not in %s"],
                        params=[start, end, tuple(criteria_ids)])
                bulk_payment_robocall_experiment(
                    experiment, payment_experiments.values_list('id', flat=True))

    bypass_agentcall_experimention(payments)

    logger.info({
        'action': 'mark_robocall_is_active',
        'dpd_list': dpd_list,
        'payment_ids': list(p.id for p in payments)
    })
    payments.update(is_robocall_active=True)


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def send_voice_payment_reminder(attempt, attempt_hour, product_lines, streamlined_id):
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    due_date = None
    today = timezone.localtime(timezone.now()).date()
    dpd = streamlined.dpd
    if dpd > 0:
        due_date = today - relativedelta(days=abs(dpd))
    elif dpd is not None:
        due_date = today + relativedelta(days=abs(dpd))

    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE + AddressPostalCodeConst.WITA_POSTALCODE \
        + AddressPostalCodeConst.WIT_POSTALCODE
    hour = timezone.localtime(timezone.now()).hour
    today_minus_4 = today - relativedelta(days=4)
    dpd_exclude = [
        today_minus_4,
    ]

    payments_id_exclude_pending_refinancing = get_payments_refinancing_pending_by_dpd(dpd_exclude)
    if hour == attempt_hour and attempt == 0:
        robocall_active = Payment.objects.select_related('loan').normal().filter(
            is_robocall_active=True,
            loan__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE,
            loan__application__product_line__product_line_code__in=product_lines,
            due_date=due_date
        ).exclude(id__in=payments_id_exclude_pending_refinancing)
    elif hour == attempt_hour and attempt == 1:
        robocall_active = Payment.objects.select_related('loan').normal().filter(
            is_robocall_active=True,
            loan__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE,
            loan__application__product_line__product_line_code__in=product_lines,
            due_date=due_date
        ).exclude(id__in=payments_id_exclude_pending_refinancing)
    elif hour == attempt_hour and attempt == 2:
        robocall_active = Payment.objects.select_related('loan').normal().filter(
            Q(is_robocall_active=True) &
            (Q(loan__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
             Q(loan__application__address_kodepos=None) | ~Q(loan__application__address_kodepos__in=all_postal_code)),
            loan__application__product_line__product_line_code__in=product_lines, due_date=due_date)\
            .exclude(id__in=payments_id_exclude_pending_refinancing)
    else:
        robocall_active = []

    risk_payment_data = []
    if streamlined.exclude_risky_customer:
        robocall_active, risk_payment_data = excluding_risky_payment_dpd_minus(robocall_active)

    from juloserver.nexmo.tasks import store_risk_payment_data
    if risk_payment_data:
        store_risk_payment_data.delay(risk_payment_data)

    voice_client = get_voice_client_v2()

    logger.info({
        'action': 'send_voice_payment_reminder',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
        'payment_ids': list(p.id for p in robocall_active)
    })

    for payment in robocall_active:
        if check_payment_is_blocked_comms(payment, 'robocall'):
            continue
        if payment.status >= PaymentStatusCodes.PAID_ON_TIME or is_last_payment_status_notpaid(payment):
            continue
        try:
            application = payment.loan.application
            if not application:
                application = payment.loan.account.application_set.last()

            application_detokenized = collection_detokenize_sync_object_model(
                PiiSource.APPLICATION,
                application,
                application.customer.customer_xid,
                ['mobile_phone_1'],
            )
            phone_number = application_detokenized.mobile_phone_1
            reminder = Reminder()
            reminder.create_reminder_history(payment, None, streamlined.template_code, VendorConst.NEXMO,
                                             ReminderTypeConst.ROBOCALL_TYPE_REMINDER)
            response = voice_client.payment_reminder(phone_number, payment.id,
                                                     streamlined_id=streamlined_id,
                                                     template_code=streamlined.template_code)
            time.sleep(1)
        except VoiceNotSent as e:
            logger.warn({
                'action': 'send_voice_payment_remainder_failed',
                'payment_id': payment.id,
                'phone_number': phone_number,
                'errors': e
            })
            continue
    slack_message = "*Template: {}* - send_voice_payment_reminder (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('alerts-comms-prod-nexmo', slack_message)

    # only on MTL
    #commenting the code as part of ENH-144
    # mtl_robocall_active = robocall_active.filter(
    #     loan__application__product_line_id__in=ProductLineCodes.mtl())
    # pn_client = get_julo_pn_client()
    # for payment in mtl_robocall_active:
    #     loan = payment.loan
    #     dpd = payment.due_late_days
    #     type = 'MTL'
    #     try:
    #         pn_client.inform_robocall_notification(loan.customer, loan.application_id, payment.id, dpd , type)
    #     except JuloException as e:
    #         logger.warn({
    #             'action': 'inform_robocall_notification',
    #             'payment_id': payment.id,
    #             'errors': e
    #         })
    #         continue


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def retry_send_voice_payment_reminder1(attempt, attempt_hour, product_lines, streamlined_id):
    """
     send robocall for uncalled and failed robocall in T-3 and T-5
    """
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    dpd = streamlined.dpd
    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE + AddressPostalCodeConst.WITA_POSTALCODE \
        + AddressPostalCodeConst.WIT_POSTALCODE
    hour = timezone.localtime(timezone.now()).hour
    if hour == attempt_hour and attempt == 0:
        failed_robo_payments = Payment.objects.failed_automated_robocall_payments(product_lines, dpd)\
            .select_related('loan').filter(
            loan__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE)
    elif hour == attempt_hour and attempt == 1:
        failed_robo_payments = Payment.objects.failed_automated_robocall_payments(product_lines, dpd)\
            .select_related('loan').filter(
            loan__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE)
    elif hour == attempt_hour and attempt == 2:
        failed_robo_payments = Payment.objects.failed_automated_robocall_payments(
            product_lines, dpd).select_related('loan').filter(
                Q(loan__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
                Q(loan__application__address_kodepos=None) | ~Q(
                    loan__application__address_kodepos__in=all_postal_code))
    else:
        failed_robo_payments = []

    if streamlined.exclude_risky_customer:
        failed_robo_payments, _ = excluding_risky_payment_dpd_minus(failed_robo_payments)

    voice_client = get_voice_client_v2()
    for payment in failed_robo_payments:
        if check_payment_is_blocked_comms(payment, 'robocall'):
            continue
        if payment.status >= PaymentStatusCodes.PAID_ON_TIME or is_last_payment_status_notpaid(payment):
            continue
        application = payment.loan.application
        if not application:
            application = payment.loan.account.application_set.last()
        application_detokenized = collection_detokenize_sync_object_model(
            PiiSource.APPLICATION,
            application,
            application.customer.customer_xid,
            ['mobile_phone_1'],
        )
        phone_number = application_detokenized.mobile_phone_1
        payment.is_robocall_active = True
        payment.save(update_fields=['udate', 'is_robocall_active'])
        try:
            reminder = Reminder()
            reminder.create_reminder_history(payment, None, streamlined.template_code, VendorConst.NEXMO,
                                             ReminderTypeConst.ROBOCALL_TYPE_REMINDER)
            response = voice_client.payment_reminder(phone_number, payment.id,
                                                     streamlined_id=streamlined_id,
                                                     template_code=streamlined.template_code)
            time.sleep(0.5)
        except VoiceNotSent as e:
            logger.warn({
                'action': 'retry_send_voice_payment_remainder_failed',
                'payment_id': payment.id,
                'phone_number': phone_number,
                'errors': e
            })
            continue
    slack_message = "*Template: {}* - retry_send_voice_payment_reminder1 (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('alerts-comms-prod-nexmo', slack_message)

@task(queue='collection_high')
@payment_reminder_execution_time_limit
def retry_send_voice_payment_reminder2(attempt, attempt_hour, product_lines, streamlined_id):
    """
        send robocall for uncalled and failed robocall in T-3 and T-5 after retry #1
        failed condition: is_success_robocall=False/Null and is_agent_called=False/Null
    """
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    dpd = streamlined.dpd
    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE + AddressPostalCodeConst.WITA_POSTALCODE \
        + AddressPostalCodeConst.WIT_POSTALCODE
    hour = timezone.localtime(timezone.now()).hour
    if hour == attempt_hour and attempt == 0:
        failed_robo_payments = Payment.objects.failed_automated_robocall_payments(product_lines, dpd)\
            .select_related('loan').filter(
            loan__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE)
    elif hour == attempt_hour and attempt == 1:
        failed_robo_payments = Payment.objects.failed_automated_robocall_payments(product_lines, dpd)\
            .select_related('loan').filter(
            loan__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE)
    elif hour == attempt_hour and attempt == 2:
        failed_robo_payments = Payment.objects.failed_automated_robocall_payments(product_lines, dpd)\
        .select_related('loan').filter(Q(loan__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
               Q(loan__application__address_kodepos=None) | ~Q(loan__application__address_kodepos__in=all_postal_code))
    else:
        failed_robo_payments = []

    if streamlined.exclude_risky_customer:
        failed_robo_payments, _ = excluding_risky_payment_dpd_minus(failed_robo_payments)

    voice_client = get_voice_client_v2()
    for payment in failed_robo_payments:
        if check_payment_is_blocked_comms(payment, 'robocall'):
            continue
        if payment.status >= PaymentStatusCodes.PAID_ON_TIME or is_last_payment_status_notpaid(payment):
            continue
        # if payment.due_late_days == -3:
        #     loan_id = payment.loan.id
        #     today_date = timezone.localtime(timezone.now()).date()
        #     if date(2019, 5, 24) <= today_date <= date(2019, 7, 5):
        #         if int(str(loan_id)[-1:]) in [0, 1, 2, 3, 7, 8, 9] \
        #                 and date(2019, 5, 24) <= today_date <= date(2019, 7, 5):
        #             update_fields = ['udate', 'is_robocall_active', 'is_success_robocall']
        #             payment.is_robocall_active = False
        #             payment.is_success_robocall = False
        #             payment.save(update_fields=update_fields)
        #             continue
        #         elif int(str(loan_id)[-1:]) in [4, 5, 6] \
        #                 and date(2019, 5, 24) <= today_date <= date(2019, 7, 5):
        #             payment.is_robocall_active = True
        #     else:
        #         update_fields = ['udate', 'is_robocall_active', 'is_success_robocall']
        #         payment.is_robocall_active = False
        #         payment.is_success_robocall = False
        #         payment.save(update_fields=update_fields)
        #         continue
        application = payment.loan.application
        if not application:
            application = payment.loan.account.application_set.last()
        application_detokenized = collection_detokenize_sync_object_model(
            PiiSource.APPLICATION,
            application,
            application.customer.customer_xid,
            ['mobile_phone_1'],
        )
        phone_number = application_detokenized.mobile_phone_1
        payment.is_robocall_active = True
        payment.save(update_fields=['udate', 'is_robocall_active'])
        try:
            reminder = Reminder()
            reminder.create_reminder_history(payment, None, streamlined.template_code, VendorConst.NEXMO,
                                             ReminderTypeConst.ROBOCALL_TYPE_REMINDER)
            response = voice_client.payment_reminder(phone_number, payment.id,
                                                     streamlined_id=streamlined_id,
                                                     template_code=streamlined.template_code)
            time.sleep(1)
        except VoiceNotSent as e:
            logger.warn({
                'action': 'retry_send_voice_payment_remainder_failed',
                'payment_id': payment.id,
                'phone_number': phone_number,
                'errors': e
            })
            continue
    slack_message = "*Template: {}* - retry_send_voice_payment_reminder2 (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('alerts-comms-prod-nexmo', slack_message)

@task(queue='collection_high')
def send_voice_ptp_payment_reminder():
    next_3day = date.today() + relativedelta(days=3)
    ptp_robocall_active_list = Payment.objects.normal().filter(
        is_ptp_robocall_active=True, ptp_date=next_3day)
    voice_client = get_voice_client_v2()
    template_code = 'ptp_payment_reminder_-3'
    for payment in ptp_robocall_active_list:
        if payment.status >= PaymentStatusCodes.PAID_ON_TIME:
            continue

        application_detokenized = collection_detokenize_sync_object_model(
            PiiSource.APPLICATION,
            payment.loan.application,
            payment.loan.application.customer.customer_xid,
            ['mobile_phone_1'],
        )
        phone_number = application_detokenized.mobile_phone_1

        try:
            _ = voice_client.ptp_payment_reminder(
                phone_number=phone_number,
                payment_id=payment.id,
                template_code=template_code
            )

            time.sleep(1)

        except VoiceApiError:
            sentry_client.captureException()
            continue

@task(name='mark_whatsapp_failed_robocall')
def mark_whatsapp_failed_robocall():
    today = timezone.now().date()
    failed_robocall_payments = Payment.objects.failed_robocall_payments(product_line_codes).dpd(-3)

    logger.warn({
        'action': 'mark_whatsapp_failed_robocall',
        'failed_robo_payments': failed_robocall_payments.count(),
    })

    for payment in failed_robocall_payments:
        if payment.status >= PaymentStatusCodes.PAID_ON_TIME:
            continue
        if payment.is_collection_called:
            continue
        if str(payment.loan_id)[-1] in ROBO_TMIN3_EXPERIMENT_CRITERIA:
            continue

        payment.is_whatsapp = True
        payment.is_robocall_active = False
        payment.is_success_robocall = False
        payment.save(update_fields=['is_whatsapp',
                                    'is_robocall_active',
                                    'is_success_robocall',
                                    'udate'])


@task(queue='collection_high')
def send_sms_robocall_success(payment_id):
    start_date = date(2019, 4, 22)
    end_date = date(2019, 5, 5)
    today = timezone.localtime(timezone.now()).date()
    if end_date < today or today < start_date:
        return
    payment = Payment.objects.select_related('loan').get(pk=payment_id)
    if str(payment.loan.id)[-1] not in ROBO_SEND_SMS_CRITERIA:
        return
    logger.info({
        'action': 'send_sms_robocall_success',
        'payment_id': payment_id,
        'loan_id': payment.loan.id
    })
    application = payment.loan.application
    if not application:
        application = payment.loan.account.application_set.last()
    if application.is_grab():
        return
    customer = application.customer
    template_code = "sms_notif_robo_success"
    application_detokenized = collection_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['mobile_phone_1'],
    )
    mobile_phone_1 = application_detokenized.mobile_phone_1
    encrypttext = encrypt()
    encoded_payment_id = encrypttext.encode_string(str(payment.id))
    url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
    shortened_url = shorten_url(url)
    sms_client = get_julo_sms_client()
    context = {
        'due_amount': display_rupiah(payment.due_amount),
        'julo_bank_name': payment.loan.julo_bank_name,
        'virtual_account': payment.loan.julo_bank_account_number,
        'due_date': payment.due_date.strftime('%d/%m'),
        'payment_page_url': shortened_url
    }
    try:
        txt_msg, response = sms_client.blast_custom(mobile_phone_1,
                                                    template_code,
                                                    context=context)
    except Exception as e:
        sentry_client.captureException()
        return

    if response['status'] != '0':
        sentry_client.captureException({
            'send_status': response['status'],
            'payment_id': payment.id,
            'message_id': response.get('message-id'),
            'sms_client_method_name': 'blast_custom',
            'error_text': response.get('error-text'),
        })
        return
    create_sms_history(response=response,
                       customer=customer,
                       application=application,
                       payment=payment,
                       template_code=template_code,
                       message_content=txt_msg,
                       phone_number_type='mobile_phone_1',
                       to_mobile_phone=format_e164_indo_phone_number(response['to']))

@task(queue='collection_high')
def make_nexmo_test_call():
    try:
        voice_client = get_voice_client_v2()
        voice_client.test_nexmo_call()

    except VoiceApiError:
        sentry_client.captureException()


def mapping_payment_by_time_zone_for_refinancing_pending(payment_id, attempt, attempt_hour, hour, all_postal_code,
                                                         failed_automated_robocall=False):
    payments = []
    if hour == attempt_hour and attempt == 0:
        payments = Payment.objects.select_related('loan').normal().filter(
            id__in=payment_id,
            loan__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE,
        )
    elif hour == attempt_hour and attempt == 1:
        payments = Payment.objects.select_related('loan').normal().filter(
            id__in=payment_id,
            loan__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE,
        )
    elif hour == attempt_hour and attempt == 2:
        payments = Payment.objects.select_related('loan').normal().filter(
            Q(id__in=payment_id) &
            (Q(loan__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
             Q(loan__application__address_kodepos=None) | ~Q(loan__application__address_kodepos__in=all_postal_code)),
        )

    if payments:
        if failed_automated_robocall:
            payments = payments.exclude(Q(is_success_robocall=True) | Q(is_collection_called=True))
        else:
            payments = payments.filter(is_robocall_active=True)
    return payments


def get_payment_by_template_code_refinancing_pending(template_code):
    today = timezone.localtime(timezone.now()).date()
    today_minus_3 = today - relativedelta(days=3)
    payments_pending_refinancing = None
    if template_code == 'nexmo_robocall_mtl_ref_pending_dpd_3':
        payments_pending_refinancing = get_payments_refinancing_pending_by_date_approved(today_minus_3, True)
    return payments_pending_refinancing


def excluding_risky_payment_dpd_minus(payments):
    if payments == []:
        return payments, []
    payment_ids = payments.values_list('id', flat=True)
    payment_ids_wo_risk, risk_payment_data = PdCollectionModelResult.objects.filter_risky_payment_on_dpd_minus(
        payment_ids)
    payment_queryset = Payment.objects.filter(id__in=payment_ids_wo_risk)
    return payment_queryset, risk_payment_data


def excluding_risky_account_payment_dpd_minus(account_payments):
    if not account_payments:
        return account_payments
    account_payments = account_payments.values_list('id', flat=True)
    account_payments_ids_wo_risk = PdCollectionModelResult.objects.filter_risky_account_payment_on_dpd_minus(
        account_payments)
    account_payment_queryset = AccountPayment.objects.filter(id__in=account_payments_ids_wo_risk)
    return account_payment_queryset


def excluding_autodebet_account_payment_dpd_minus(account_payments):
    if not account_payments:
        return account_payments

    account_payment_no_autodebet = account_payments.exclude(
        Q(account__autodebetaccount__is_use_autodebet=True) &
        Q(account__autodebetaccount__is_deleted_autodebet=False)
    )

    return account_payment_no_autodebet


def is_last_account_payment_status_notpaid(account_payment):
    account = account_payment.account
    last_account_payment = account.accountpayment_set.normal().exclude(
        due_date__gte=account_payment.due_date).order_by('due_date').last()
    if not last_account_payment:
        return False
    return last_account_payment.status.status_code not in PaymentStatusCodes.paid_status_codes()


@task(queue='collection_high')
def mark_voice_account_payment_reminder(dpd_list):
    """
    Mark and unmark account payment reminder eligible for robocalls.

    Args:
        dpd_list (list): List of dpd to scan account payments.
    """
    account_payments_with_robocall = AccountPayment.objects.normal().filter(
        is_robocall_active__isnull=False,
    ).exclude(account__account_lookup__workflow__name=WorkflowConst.GRAB)
    account_payments_with_robocall.update(
        is_robocall_active=None,
        is_success_robocall=None,
    )

    time.sleep(2)

    account_payments = AccountPayment.objects.tobe_robocall_account_payments(
        product_line_codes, dpd_list)
    # get active experiment settings
    bypass_agentcall_experimention(account_payments)

    logger.info({
        'action': 'mark_robocall_is_active',
        'dpd_list': dpd_list,
        'account_payment_ids': list(p.id for p in account_payments)
    })
    account_payments.update(is_robocall_active=True)


@task(queue='collection_high')
def mark_voice_account_payment_reminder_grab(dpd_list: list):
    from juloserver.julo.services2 import get_redis_client
    """
    Mark and unmark account payment reminder eligible for robocalls.

    Args:
        dpd_list (list): List of dpd to scan account payments.
    """
    logger.info({
        "task": "mark_voice_account_payment_reminder_grab",
        "status": "starting task",
        "dpd_list": dpd_list
    })
    account_payments_with_robocall = AccountPayment.objects.normal().filter(
        is_robocall_active__isnull=False,
        account__account_lookup__workflow__name=WorkflowConst.GRAB
    )
    account_payments_with_robocall.update(
        is_robocall_active=None,
        is_success_robocall=None,
    )

    time.sleep(2)
    logger.info({
        "task": "mark_voice_account_payment_reminder_grab",
        "status": "start running custom sql query",
        "dpd_list": dpd_list
    })

    custom_sql_query = """
        WITH cte AS
            (
                SELECT p.loan_id, p.payment_id, ROW_NUMBER() OVER (PARTITION BY p.loan_id ORDER BY 
                p.due_date asc) AS rn from ops.loan l join ops.payment p on p.loan_id = l.loan_id 
                join ops.account a on a.account_id = l.account_id
                join ops.account_lookup al  on al.account_lookup_id = a.account_lookup_id 
                join ops.workflow w on w.workflow_id = al.workflow_id
                where l.loan_purpose = 'Grab_loan_creation' and l.loan_status_code >= 220 
                and l.loan_status_code < 250 and p.payment_status_code < 330 
                and p.is_restructured = false and w.name = 'GrabWorkflow'
                group by p.loan_id, p.payment_id order by p.due_date asc
            )
        SELECT *
        FROM cte
        WHERE rn = 1
    """
    # SQL to get the oldest unpaid payment and loan ID for all grab loans(active)
    redis_set_rows = list()
    rows = None
    with connection.cursor() as cursor:
        cursor.execute(custom_sql_query)
        rows = cursor.fetchall()

    total_number_of_loans = len(rows) if rows else 0
    logger.info({
        "task": "mark_voice_account_payment_reminder_grab",
        "status": "successful run custom query",
        "total_number_of_loans": total_number_of_loans
    })
    robocall_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
        is_active=True
    )

    default_batch_values = GrabRobocallConstant.ROBOCALL_BATCH_SIZE
    if robocall_feature_setting:
        default_batch_values = int(robocall_feature_setting.parameters.get('robocall_batch_size', GrabRobocallConstant.ROBOCALL_BATCH_SIZE))

    set_of_payments_at_dpd = set()
    for iterator in list(range(0, total_number_of_loans, default_batch_values)):
        batch_payments = set()
        for loan_id, payment_id, _ in rows[
            iterator: iterator + default_batch_values
        ]:
            batch_payments.add(payment_id)
        grab_loan_data_set = GrabLoanData.objects.only(
            'id', 'loan_id', 'account_halt_status', 'account_halt_info'
        )
        prefetch_grab_loan_data = Prefetch('loan__grabloandata_set', to_attr='grab_loan_data_set',
                                           queryset=grab_loan_data_set)
        prefetch_join_tables = [
            prefetch_grab_loan_data
        ]
        # Since we use new calculation we need the grab_loan_data
        payments = Payment.objects.select_related('loan').prefetch_related(
            *prefetch_join_tables).filter(id__in=batch_payments)
        for payment in payments:
            if payment.get_grab_dpd in dpd_list:
                redis_set_rows.append((payment.loan_id, payment.id, 1))
                set_of_payments_at_dpd.add(payment.id)

    account_payment_ids = Payment.objects.filter(
        id__in=set_of_payments_at_dpd).not_paid_active().values_list(
        'account_payment_id', flat=True)

    # Set in Redis
    redis_key = GrabRobocallConstant.REDIS_KEY_FOR_ROBOCALL
    logger.info({
        "task": "mark_voice_account_payment_reminder_grab",
        "action": "attempt setting rows to redis"
    })
    try:
        redis_client = get_redis_client()
        redis_client.set(
            redis_key, pickle.dumps(redis_set_rows), timedelta(hours=20)
        )
    except Exception as e:
        logger.exception(
            {
                "action": "mark_voice_account_payment_reminder_grab "
                          "data_set in redis",
                "message": "error redis {}".format(str(e)),
                "key": redis_key,
            }
        )

    logger.info({
        "task": "mark_voice_account_payment_reminder_grab",
        "action": "success setting rows to redis"
    })

    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids)
    account_payments.update(is_robocall_active=True)

    logger.info({
        "task": "mark_voice_account_payment_reminder_grab",
        "action": "update account_payment is_robocall_active=True",
        "account_payment_ids": account_payment_ids,
        "dpd_list": dpd_list
    })

    logger.info({
        'action': 'mark_voice_account_payment_reminder_grab',
        'dpd_list': dpd_list,
        'status': 'success updation'
    })


@task(queue='nexmo_robocall')
@payment_reminder_execution_time_limit
def trigger_account_payment_reminder(account_payment_id, streamlined_id, retry=0):

    # omnichannel customer exclusion
    omnichannel_exclusion_request = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.ONE_WAY_ROBOCALL
    )

    account_payment = AccountPayment.objects.get(id=account_payment_id)

    if (
        omnichannel_exclusion_request.is_excluded
        and is_account_payment_owned_by_omnichannel_customer(
            exclusion_req=omnichannel_exclusion_request,
            account_payment=account_payment,
        )
    ):
        return

    voice_client = get_voice_client_v2()
    logger_data = {
        'action': 'trigger_account_payment_reminder',
        'streamlined_id': streamlined_id
    }

    try:
        streamlined = StreamlinedCommunication.objects.get(pk=streamlined_id)
        logger.info({
            'message': 'Processing trigger_account_payment_reminder',
            'account_payment': model_to_dict(account_payment, fields=('id', 'status')),
            'retry_count': str(retry),
            **logger_data
        })

        # Conditional check to avoid triggering robocall for already handled account payments
        if account_payment.is_success_robocall or account_payment.is_collection_called:
            return

        if check_account_payment_is_blocked_comms(account_payment, 'robocall'):
            return

        if account_payment.status.status_code >= PaymentStatusCodes.PAID_ON_TIME or \
                is_last_account_payment_status_notpaid(account_payment):
            return

        app_set = account_payment.account.application_set
        if streamlined.product == 'nexmo_turbo':
            application = app_set.filter(workflow__name=WorkflowConst.JULO_STARTER).last()
        else:
            application = app_set.last()

        phone_number = get_application_phone_number(application)
        if retry > 0:
            account_payment.is_robocall_active = True
            account_payment.save(update_fields=['udate', 'is_robocall_active'])
        reminder = Reminder()
        reminder.create_j1_reminder_history(
            account_payment, application.customer, streamlined.template_code, VendorConst.NEXMO,
            ReminderTypeConst.ROBOCALL_TYPE_REMINDER,
        )
        voice_client.account_payment_reminder(
            phone_number, account_payment.id, streamlined_id=streamlined_id,
            template_code=streamlined.template_code, is_grab=False,
        )
    except Exception as e:
        logger.error({
            'action': 'error processing send_voice_account_payment_reminder',
            'retry_count': str(retry),
            'account_payment_id': account_payment_id,
            'error_message': e,
            **logger_data
        })
        raise e


@task(queue='nexmo_robocall')
@payment_reminder_execution_time_limit
def trigger_account_payment_reminder_grab(payment_id, streamlined_id, retry=0):
    voice_client = get_voice_client_v2()
    logger_data = {
        'action': 'trigger_account_payment_reminder_grab',
        'streamlined_id': streamlined_id
    }

    try:
        payment = Payment.objects.get(id=payment_id)
        account_payment = payment.account_payment
        streamlined = StreamlinedCommunication.objects.get(pk=streamlined_id)
        if not streamlined:
            logger.exception({
                'action': 'send_voice_payment_reminder_grab',
                'message': "Streamlined Communication not found for id {}".format(streamlined_id)
            })
            return

        logger.info({
            'message': 'Processing trigger_account_payment_reminder',
            'account_payment': model_to_dict(payment, fields=('id', 'status')),
            'retry_count': str(retry),
            **logger_data
        })

        # Conditional check to avoid triggering robocall for already handled account payments
        if account_payment.is_success_robocall or account_payment.is_collection_called:
            return

        if check_account_payment_is_blocked_comms(account_payment, 'robocall'):
            return

        if account_payment.status.status_code >= PaymentStatusCodes.PAID_ON_TIME:
            return

        application = account_payment.account.application_set.last()
        if not application:
            logger.exception({
                'action': 'send_voice_payment_reminder_grab',
                'message': "Application not found for account payment {}".format(account_payment.pk)
            })
            return
        phone_number = get_application_phone_number(application)
        if retry > 0:
            account_payment.is_robocall_active = True
            account_payment.save(update_fields=['udate', 'is_robocall_active'])
        reminder = Reminder()
        reminder.create_j1_reminder_history(
            account_payment, application.customer, streamlined.template_code, VendorConst.NEXMO,
            ReminderTypeConst.ROBOCALL_TYPE_REMINDER,
        )
        voice_client.account_payment_reminder_grab(
            phone_number, payment.id, streamlined_id=streamlined_id,
            template_code=streamlined.template_code, is_grab=True, is_j1=False
        )
    except Exception as e:
        logger.error({
            'action': 'error processing trigger_account_payment_reminder_grab',
            'retry_count': str(retry),
            'payment_id': payment_id,
            'error_message': e,
            **logger_data
        })
        raise e


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def send_voice_payment_reminder_grab(attempt, attempt_hour, product_lines, streamlined_id):
    from juloserver.grab.services.robocall_services import \
        get_payments_from_grab_robocall

    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        logger.exception({
            'action': 'send_voice_payment_reminder_grab',
            'message': "Streamlined Communication not found for id {}".format(streamlined_id)
        })
        return
    dpd = streamlined.dpd
    hour = timezone.localtime(timezone.now()).hour

    if streamlined.product != 'nexmo_grab':
        logger.exception({
            'action': 'send_voice_payment_reminder_grab',
            'streamlined': streamlined.id,
            'message': "Product is not grab Product",
        })
        return

    # Get relevant Grab Payments
    payments_will_be_called_qs = get_payments_from_grab_robocall(
        dpd, attempt_hour, attempt, product_lines)

    # filter based on C score Robocall or None C score
    payments_will_be_called_qs = filter_payments_based_on_c_score(
        payments_will_be_called_qs, streamlined)

    # Filter based on feature setting
    payments_will_be_called_qs = filter_based_on_feature_setting_robocall(
        payments_will_be_called_qs, streamlined
    )

    logger_data = {
        'action': 'send_voice_account_payment_reminder',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
    }
    total_count = 0
    for payment in payments_will_be_called_qs.iterator():
        total_count += 1
        reminder_task = trigger_account_payment_reminder_grab.delay(
            payment.id, streamlined_id)
        logger.info({
            'reminder_task_id': reminder_task.id,
            'account_payment_id': payment.id,
            **logger_data
        })

    logger.info({
        'message': 'finish send_voice_account_payment_reminder',
        'total_account_payments': total_count,
        **logger_data,
    })
    slack_message = "*Template: {}* - send_voice_payment_reminder_grab " \
                    "(streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id),
               str(attempt), str(attempt_hour))
    send_slack_bot_message('grab-general-alerts', slack_message)


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def send_voice_account_payment_reminder(attempt, attempt_hour, product_lines, streamlined_id):
    # import here, because circular import
    from juloserver.loan.constants import TimeZoneName
    from juloserver.loan.services.robocall import get_start_time_and_end_time
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    due_date = None
    today = timezone.localtime(timezone.now()).date()
    dpd = streamlined.dpd
    if dpd is not None:
        if dpd > 0:
            due_date = today - relativedelta(days=abs(dpd))
        else:
            due_date = today + relativedelta(days=abs(dpd))

    if streamlined.product == 'nexmo_grab':
        return
    current_time = timezone.localtime(timezone.now())
    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE \
        + AddressPostalCodeConst.WITA_POSTALCODE + AddressPostalCodeConst.WIT_POSTALCODE
    hour = timezone.localtime(timezone.now()).hour
    # today_minus_4 = today - relativedelta(days=4)
    # dpd_exclude = [today_minus_4,]
    # payments_id_exclude_pending_refinancing = get_payments_refinancing_pending_by_dpd(dpd_exclude)
    if hour == attempt_hour and attempt == 0:
        robocall_active = AccountPayment.objects.select_related('account').normal().filter(
            is_robocall_active=True,
            account__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE,
            account__application__product_line__product_line_code__in=product_lines,
            due_date=due_date
        ).exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WIT, attempt_hour, current_time, 18
        )
    elif hour == attempt_hour and attempt == 1:
        robocall_active = AccountPayment.objects.select_related('account').normal().filter(
            is_robocall_active=True,
            account__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE,
            account__application__product_line__product_line_code__in=product_lines,
            due_date=due_date
        ).exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WITA, attempt_hour, current_time, 19
        )
    elif hour == attempt_hour and attempt == 2:
        robocall_active = AccountPayment.objects.select_related('account').normal().filter(
            Q(is_robocall_active=True) & (
                Q(account__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
                Q(account__application__address_kodepos=None) | ~Q(
                    account__application__address_kodepos__in=all_postal_code)),
            account__application__product_line__product_line_code__in=product_lines,
            due_date=due_date).exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WIB, attempt_hour, current_time, 20
        )
    else:
        robocall_active = AccountPayment.objects.none()
        end_time = current_time.replace(hour=20, minute=0, second=0)

    if robocall_active and streamlined.product == 'nexmo_turbo':
        # The purpose of this line is to exclude jturbo call because we already call as j1.
        robocall_active = robocall_active.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER)

    if robocall_active and streamlined.product == 'nexmo_j1':
        # The purpose of this line is to exclude j1 call because we already call as jturbo.
        robocall_active = robocall_active.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE)

        robocall_active, should_process = filter_account_payments_for_robocall_collection_tailor_experiment(robocall_active, streamlined)
        if not should_process:
            logger.info({
                'action': 'send_voice_account_payment_reminder',
                'streamlined': streamlined.id,
                'message': "experiment_setting is not active or experiment_group data is not found",
            })
            return

    if robocall_active and streamlined.product in ['nexmo_j1', 'nexmo_turbo']:
        # handle for late fee earlier experiment
        robocall_active = filtering_late_fee_earlier_experiment_for_nexmo(
            robocall_active, streamlined)

    if streamlined.exclude_risky_customer:
        robocall_active = excluding_risky_account_payment_dpd_minus(robocall_active)

    if streamlined.dpd < 0:
        robocall_active = excluding_autodebet_account_payment_dpd_minus(robocall_active)

    if robocall_active and streamlined.product == 'nexmo_j1' and streamlined.dpd in (-3, -5):
        robocall_active = excluding_risky_account_payment_dpd_minus(robocall_active)
        record_experiment_key = "{}_{}".format(RobocallType.NEXMO_J1, streamlined_id)
        robocall_active = exclude_experiment_excellent_customer_from_robocall(
            robocall_active, record_type=record_experiment_key)
        record_customer_excellent_experiment.apply_async((record_experiment_key,), countdown=5)


    robocall_active = filter_streamlined_based_on_partner_selection(streamlined, robocall_active)
    robocall_active = determine_julo_gold_for_streamlined_communication(
        streamlined.julo_gold_status, robocall_active
    )

    logger_data = {
        'action': 'send_voice_account_payment_reminder',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
    }
    total_count = 0
    for account_payment in robocall_active.distinct().iterator():
        total_count += 1
        reminder_task = trigger_account_payment_reminder.apply_async(
            (account_payment.id, streamlined_id,), expires=end_time)
        logger.info({
            'reminder_task_id': reminder_task.id,
            'account_payment_id': account_payment.id,
            **logger_data
        })

    logger.info({
        'message': 'finish send_voice_account_payment_reminder',
        'total_account_payments': total_count,
        **logger_data,
    })
    slack_message = "*Template: {}* - send_voice_account_payment_reminder (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('alerts-comms-prod-nexmo', slack_message)

@task(queue='collection_high')
@payment_reminder_execution_time_limit
def retry_send_voice_account_payment_reminder1(
        attempt, attempt_hour, product_lines, streamlined_id):
    """
     send robocall for uncalled and failed robocall in T-3 and T-5
    """
    # import here, because circular import
    from juloserver.loan.constants import TimeZoneName
    from juloserver.loan.services.robocall import get_start_time_and_end_time
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    dpd = streamlined.dpd
    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE \
        + AddressPostalCodeConst.WITA_POSTALCODE + AddressPostalCodeConst.WIT_POSTALCODE
    current_time = timezone.localtime(timezone.now())
    hour = current_time.hour
    if hour == attempt_hour and attempt == 0:
        failed_robo_payments = AccountPayment.objects.failed_automated_robocall_account_payments(
            product_lines, dpd).select_related('account').filter(
            account__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE).exclude(
            account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WIT, attempt_hour, current_time, 18
        )
    elif hour == attempt_hour and attempt == 1:
        failed_robo_payments = AccountPayment.objects.failed_automated_robocall_account_payments(
            product_lines, dpd).select_related('account').filter(
                account__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE).exclude(
            account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WITA, attempt_hour, current_time, 19
        )
    elif hour == attempt_hour and attempt == 2:
        failed_robo_payments = AccountPayment.objects.failed_automated_robocall_account_payments(
            product_lines, dpd).select_related('account').filter(
                Q(account__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
                Q(account__application__address_kodepos=None) | ~Q(
                    account__application__address_kodepos__in=all_postal_code)).exclude(
            account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WIB, attempt_hour, current_time, 20
        )
    else:
        failed_robo_payments = AccountPayment.objects.none()
        end_time = current_time.replace(hour=20, minute=0, second=0)

    if failed_robo_payments and streamlined.product == 'nexmo_turbo':
        # The purpose of this line is to exclude jturbo call because we already call as j1.
        failed_robo_payments = failed_robo_payments.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER)

    if failed_robo_payments and streamlined.product == 'nexmo_j1':
        # The purpose of this line is to exclude j1 call because we already call as jturbo.
        failed_robo_payments = failed_robo_payments.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE)

        failed_robo_payments, should_process = filter_account_payments_for_robocall_collection_tailor_experiment(failed_robo_payments, streamlined)
        if not should_process:
            logger.info({
                'action': 'retry_send_voice_account_payment_reminder1',
                'streamlined': streamlined.id,
                'message': "experiment_setting is not active or experiment_group data is not found",
            })
            return

    if failed_robo_payments and streamlined.product in ['nexmo_j1', 'nexmo_turbo']:
        # handle for late fee earlier experiment
        failed_robo_payments = filtering_late_fee_earlier_experiment_for_nexmo(
            failed_robo_payments, streamlined)

    if streamlined.exclude_risky_customer:
        failed_robo_payments = excluding_risky_account_payment_dpd_minus(failed_robo_payments)

    if streamlined.dpd < 0:
        failed_robo_payments = excluding_autodebet_account_payment_dpd_minus(failed_robo_payments)

    if failed_robo_payments and streamlined.product == 'nexmo_grab':
        failed_robo_payments = failed_robo_payments.filter(account__account_lookup__name__icontains='grab')

    failed_robo_payments = filter_streamlined_based_on_partner_selection(
        streamlined, failed_robo_payments)

    if failed_robo_payments and streamlined.product == 'nexmo_j1' and streamlined.dpd in (-3, -5):
        failed_robo_payments = excluding_risky_account_payment_dpd_minus(failed_robo_payments)
        failed_robo_payments = exclude_experiment_excellent_customer_from_robocall(
            failed_robo_payments)

    failed_robo_payments = determine_julo_gold_for_streamlined_communication(
        streamlined.julo_gold_status, failed_robo_payments
    )

    logger_data = {
        'action': 'retry_send_voice_account_payment_reminder1',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
    }
    total_count = 0
    for account_payment in failed_robo_payments.distinct().iterator():
        total_count += 1

        reminder_task = trigger_account_payment_reminder.apply_async(
            (account_payment.id, streamlined_id, 1), expires=end_time
        )
        logger.info({
            'reminder_task_id': reminder_task.id,
            'account_payment_id': account_payment.id,
            **logger_data
        })

    logger.info({
        'message': 'finish retry_send_voice_account_payment_reminder1',
        'total_account_payments': total_count,
        **logger_data,
    })

    slack_message = "*Template: {}* - retry_send_voice_account_payment_reminder1 (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('alerts-comms-prod-nexmo', slack_message)


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def retry_send_voice_payment_reminder_grab1(
        attempt, attempt_hour, product_lines, streamlined_id):
    """
     send robocall for uncalled and failed robocall in T-3 and T-5
    """
    from juloserver.grab.services.robocall_services import \
        get_payments_from_grab_robocall
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    dpd = streamlined.dpd

    hour = timezone.localtime(timezone.now()).hour

    if streamlined.product != 'nexmo_grab':
        logger.info({
            'action': 'retry_send_voice_payment_reminder_grab1',
            'streamlined': streamlined.id,
            'message': "Product is not grab Product",
        })
        return

    # Get relevant Grab Payments
    robocall_failed_payments = get_payments_from_grab_robocall(
        dpd, attempt_hour, attempt, product_lines, is_retry=True)

    # filter based on C score Robocall or None C score
    robocall_failed_payments = filter_payments_based_on_c_score(
        robocall_failed_payments, streamlined)

    # Filter based on feature setting
    robocall_failed_payments = filter_based_on_feature_setting_robocall(
        robocall_failed_payments, streamlined
    )

    logger_data = {
        'action': 'retry_send_voice_payment_reminder_grab1',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
    }
    total_count = 0
    for payment in robocall_failed_payments.distinct().iterator():
        total_count += 1
        reminder_task = trigger_account_payment_reminder_grab.delay(
            payment.id, streamlined_id)
        logger.info({
            'reminder_task_id': reminder_task.id,
            'account_payment_id': payment.id,
            **logger_data
        })

    logger.info({
        'message': 'finish retry_send_voice_payment_reminder_grab1',
        'total_account_payments': total_count,
        **logger_data,
    })
    slack_message = "*Template: {}* - retry_send_voice_payment_reminder_grab1 " \
                    "(streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id),
               str(attempt), str(attempt_hour))
    send_slack_bot_message('grab-general-alerts', slack_message)


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def retry_send_voice_account_payment_reminder2(
        attempt, attempt_hour, product_lines, streamlined_id):
    """
        send robocall for uncalled and failed robocall in T-3 and T-5 after retry #1
        failed condition: is_success_robocall=False/Null and is_agent_called=False/Null
    """
    # import here, because circular import
    from juloserver.loan.constants import TimeZoneName
    from juloserver.loan.services.robocall import get_start_time_and_end_time
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    dpd = streamlined.dpd
    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE \
        + AddressPostalCodeConst.WITA_POSTALCODE + AddressPostalCodeConst.WIT_POSTALCODE
    current_time = timezone.localtime(timezone.now())
    hour = current_time.hour
    if hour == attempt_hour and attempt == 0:
        failed_robo_payments = AccountPayment.objects.failed_automated_robocall_account_payments(
            product_lines, dpd).select_related('account').filter(
                account__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE).exclude(
            account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WIT, attempt_hour, current_time, 18
        )
    elif hour == attempt_hour and attempt == 1:
        failed_robo_payments = AccountPayment.objects.failed_automated_robocall_account_payments(
            product_lines, dpd).select_related('account').filter(
                account__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE).exclude(
            account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WITA, attempt_hour, current_time, 19
        )
    elif hour == attempt_hour and attempt == 2:
        failed_robo_payments = AccountPayment.objects.failed_automated_robocall_account_payments(
            product_lines, dpd).select_related('account').filter(
                Q(account__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
                Q(account__application__address_kodepos=None) | ~Q(
                    account__application__address_kodepos__in=all_postal_code)).exclude(
            account__status_id=AccountConstant.STATUS_CODE.sold_off)
        start_time, end_time = get_start_time_and_end_time(
            TimeZoneName.WIB, attempt_hour, current_time, 20
        )
    else:
        failed_robo_payments = AccountPayment.objects.none()
        end_time = current_time.replace(hour=20, minute=0, second=0)

    if failed_robo_payments and streamlined.product == 'nexmo_turbo':
        # The purpose of this line is to exclude jturbo call because we already call as j1.
        failed_robo_payments = failed_robo_payments.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER)

    if failed_robo_payments and streamlined.product == 'nexmo_j1':
        # The purpose of this line is to exclude j1 call because we already call as jturbo.
        failed_robo_payments = failed_robo_payments.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE)

        failed_robo_payments, should_process = filter_account_payments_for_robocall_collection_tailor_experiment(failed_robo_payments, streamlined)
        if not should_process:
            logger.info({
                'action': 'retry_send_voice_account_payment_reminder2',
                'streamlined': streamlined.id,
                'message': "experiment_setting is not active or experiment_group data is not found",
            })
            return

    if failed_robo_payments and streamlined.product in ['nexmo_j1', 'nexmo_turbo']:
        # handle for late fee earlier experiment
        failed_robo_payments = filtering_late_fee_earlier_experiment_for_nexmo(
            failed_robo_payments, streamlined)

    if streamlined.exclude_risky_customer:
        failed_robo_payments = excluding_risky_account_payment_dpd_minus(failed_robo_payments)

    if streamlined.dpd < 0:
        failed_robo_payments = excluding_autodebet_account_payment_dpd_minus(failed_robo_payments)

    if failed_robo_payments and streamlined.product == 'nexmo_grab':
        failed_robo_payments = failed_robo_payments.filter(account__account_lookup__name__icontains='grab')

    failed_robo_payments = filter_streamlined_based_on_partner_selection(
        streamlined, failed_robo_payments)

    if failed_robo_payments and streamlined.product == 'nexmo_j1' and streamlined.dpd in (-3, -5):
        failed_robo_payments = excluding_risky_account_payment_dpd_minus(failed_robo_payments)
        failed_robo_payments = exclude_experiment_excellent_customer_from_robocall(
            failed_robo_payments)

    failed_robo_payments = determine_julo_gold_for_streamlined_communication(
        streamlined.julo_gold_status, failed_robo_payments
    )

    logger_data = {
        'action': 'retry_send_voice_account_payment_reminder2',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
    }
    total_count = 0
    for account_payment in failed_robo_payments.distinct().iterator():
        total_count += 1
        reminder_task = trigger_account_payment_reminder.apply_async(
            (account_payment.id, streamlined_id, 2), expires=end_time
        )
        logger.info({
            'reminder_task_id': reminder_task.id,
            'account_payment_id': account_payment.id,
            **logger_data
        })

    logger.info({
        'message': 'finish retry_send_voice_account_payment_reminder2',
        'total_account_payments': total_count,
        **logger_data,
    })

    slack_message = "*Template: {}* - retry_send_voice_account_payment_reminder2 (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('alerts-comms-prod-nexmo', slack_message)


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def retry_send_voice_payment_reminder_grab2(
        attempt, attempt_hour, product_lines, streamlined_id):
    """
        send robocall for uncalled and failed robocall in T-3 and T-5 after retry #1
        failed condition: is_success_robocall=False/Null and is_agent_called=False/Null
    """
    from juloserver.grab.services.robocall_services import \
        get_payments_from_grab_robocall
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
    if not streamlined:
        return
    dpd = streamlined.dpd

    hour = timezone.localtime(timezone.now()).hour

    if streamlined.product != 'nexmo_grab':
        logger.info({
            'action': 'retry_send_voice_payment_reminder_grab1',
            'streamlined': streamlined.id,
            'message': "Product is not grab Product",
        })
        return

    # Get relevant Grab Payments
    robocall_failed_payments = get_payments_from_grab_robocall(
        dpd, attempt_hour, attempt, product_lines, is_retry=True)

    # filter based on C score Robocall or None C score
    robocall_failed_payments = filter_payments_based_on_c_score(
        robocall_failed_payments, streamlined)

    # Filter based on feature setting
    robocall_failed_payments = filter_based_on_feature_setting_robocall(
        robocall_failed_payments, streamlined
    )

    logger_data = {
        'action': 'retry_send_voice_payment_reminder_grab1',
        'hour': hour,
        'attempt': attempt,
        'attempt_hour': attempt_hour,
        'product_lines': product_lines,
        'streamlined_id': streamlined_id,
    }
    total_count = 0
    for payment in robocall_failed_payments.distinct().iterator():
        total_count += 1
        reminder_task = trigger_account_payment_reminder_grab.delay(
            payment.id, streamlined_id)
        logger.info({
            'reminder_task_id': reminder_task.id,
            'account_payment_id': payment.id,
            **logger_data
        })

    logger.info({
        'message': 'finish retry_send_voice_payment_reminder_grab1',
        'total_account_payments': total_count,
        **logger_data,
    })
    slack_message = "*Template: {}* - retry_send_voice_payment_reminder_grab2 (streamlined_id - {}, attempt - {}, attempt-hour - {})".\
        format(str(streamlined.template_code), str(streamlined_id), str(attempt), str(attempt_hour))
    send_slack_bot_message('grab-general-alerts', slack_message)



def filter_account_payments_for_robocall_collection_tailor_experiment(robocall_account_payments, streamlined):
    today = timezone.localtime(timezone.now()).date()
    experiment_setting = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConstMiniSquad.COLLECTION_TAILORED_EXPERIMENT_ROBOCALL
    ).filter(
        (Q(start_date__date__lte=today) & Q(end_date__date__gte=today))
        | Q(is_permanent=True)
    ).last()

    if streamlined.extra_conditions == CardProperty.J1_NEXMO_ROBOCALL_COLLECTION_TAILORED and not experiment_setting:
        return robocall_account_payments, False

    if streamlined.extra_conditions != CardProperty.J1_NEXMO_ROBOCALL_COLLECTION_TAILORED and not experiment_setting:
        return robocall_account_payments, True

    if streamlined.extra_conditions != CardProperty.J1_NEXMO_ROBOCALL_COLLECTION_TAILORED and experiment_setting:
        robocall_account_payments = exclude_account_payments_for_robocall_collection_tailor_experiment(robocall_account_payments, streamlined.dpd, experiment_setting)
        return robocall_account_payments, True

    segment = streamlined.criteria.get('segment')
    experiment_group_list = ExperimentGroup.objects.filter(
        cdate__date=today, experiment_setting=experiment_setting, segment=segment, group='experiment')

    if not experiment_group_list:
        return robocall_account_payments, False

    not_eligibile_account_payments = []
    for experiment_group in experiment_group_list:
        dpd = (today - experiment_group.account_payment.due_date).days
        if (dpd == -5) and (experiment_group.segment == 'hamster' or experiment_group.segment == 'elephant'):
            not_eligibile_account_payments.append(experiment_group.account_payment_id)
        elif (dpd == -3) and (experiment_group.segment == 'hamster'):
            not_eligibile_account_payments.append(experiment_group.account_payment_id)

    if not_eligibile_account_payments:
        experiment_group_list = experiment_group_list.exclude(account_payment_id__in=not_eligibile_account_payments)

    robocall_account_payments = robocall_account_payments.filter(
        id__in=list(experiment_group_list.values_list('account_payment_id', flat=True))
    )
    return robocall_account_payments, True


def exclude_account_payments_for_robocall_collection_tailor_experiment(robocall_account_payments, dpd, experiment_setting ):
    eligible_dpd_params = experiment_setting.criteria.get('eligible_dpd')
    today = timezone.localtime(timezone.now()).date()
    eligible_dpd = []
    for eligible_dpd_param in eligible_dpd_params:
        eligible_dpd.append(eligible_dpd_param["checking_dpd_at"])

    if dpd not in eligible_dpd:
        return robocall_account_payments

    experiment_group_list = ExperimentGroup.objects.filter(
        cdate__date=today, experiment_setting=experiment_setting, segment__isnull=False, group='experiment')

    robocall_account_payments = robocall_account_payments.exclude(
        id__in=list(experiment_group_list.values_list('account_payment_id', flat=True))
    )
    return robocall_account_payments


def filtering_late_fee_earlier_experiment_for_nexmo(account_payment_qs, streamlined_comms):
    if not account_payment_qs:
        return AccountPayment.objects.none()

    is_nexmo_for_experiment = True if CardProperty.LATE_FEE_EARLIER_EXPERIMENT == \
        streamlined_comms.extra_conditions else False
    late_fee_experiment = get_experiment_setting_by_code(
        ExperimentConstMiniSquad.LATE_FEE_EARLIER_EXPERIMENT)
    experiment_account_ids = []

    if is_nexmo_for_experiment and late_fee_experiment:
        experiment_account_ids = get_list_account_ids_late_fee_experiment(
            'experiment', late_fee_experiment)
        account_payment_qs = account_payment_qs.filter(account_id__in=experiment_account_ids)
        return account_payment_qs
    if not is_nexmo_for_experiment and late_fee_experiment:
        experiment_account_ids = get_list_account_ids_late_fee_experiment(
            'experiment', late_fee_experiment)
        account_payment_qs = account_payment_qs.exclude(account_id__in=experiment_account_ids)
        return account_payment_qs
    if is_nexmo_for_experiment and not late_fee_experiment:
        return AccountPayment.objects.none()
    if not is_nexmo_for_experiment and not late_fee_experiment:
        return account_payment_qs


class MinisquadFeatureSettings:
    pass



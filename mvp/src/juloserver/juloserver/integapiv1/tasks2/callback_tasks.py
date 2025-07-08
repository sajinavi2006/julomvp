from __future__ import print_function
from builtins import str
import logging

from datetime import date
from dateutil.relativedelta import relativedelta

from celery import task

from django.utils import timezone

from juloserver.julo.models import VoiceCallRecord
from juloserver.julo.models import Payment
from juloserver.julo.models import PaymentNote
from juloserver.loan.services.robocall import check_and_send_sms_after_robocall
from juloserver.reminder.models import CallRecordUrl

from juloserver.julo.constants import (VoiceTypeStatus,
                                       VOICE_CALL_SUCCESS_THRESHOLD)
from juloserver.integapiv1.constants import (
    NOT_RETRY_ROBOCALL_STATUS,
    VonageOutboundCall,
)

from juloserver.julo.services2.voice import send_sms_robocall_success
from juloserver.loan.services.robocall import retry_blast_robocall
from juloserver.account_payment.models import (
    AccountPayment,
    AccountPaymentNote,
    AccountPaymentStatusHistory,
)
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.streamlined_communication.tasks import (
    save_status_detail_for_vonage_outbound_call,
    sms_after_robocall_experiment_trigger,
)

LOGGER = logging.getLogger(__name__)


@task(name="update_voice_call_record")
def update_voice_call_record(data):
    """update voice call table"""
    conversation_uuid = data['conversation_uuid']

    # client_call_uid comes from communication-service as temporary id
    client_call_uid = data.get('client_call_uid')
    if client_call_uid:
        voice_call_record = VoiceCallRecord.objects.get_or_none(uuid=client_call_uid)
        if voice_call_record:
            voice_call_record.uuid = data['uuid']
            voice_call_record.conversation_uuid = conversation_uuid
            voice_call_record.direction = data.get('direction')
            voice_call_record.status = data.get('status')
    else:
        voice_call_record = VoiceCallRecord.objects.get_or_none(conversation_uuid=conversation_uuid)

    if not voice_call_record:
        LOGGER.error(
            {
                'error': 'Voice Call Record not found',
                'client_call_uid': client_call_uid,
                'conversation_uuid': conversation_uuid,
            }
        )
        return

    success_threshold = VOICE_CALL_SUCCESS_THRESHOLD
    voice_call_record.call_from = data['from']
    voice_call_record.call_to = data['to']
    if data['status'] and data['status'] != 'completed':
        voice_call_record.status = data['status']
        # retry blasting robocall if status != ['answered', 'ringing'] for loan robocall
        is_promo_campaign = 'promo_code' in str(voice_call_record.template_code)
        if data['status'] not in NOT_RETRY_ROBOCALL_STATUS and is_promo_campaign:
            retry_blast_robocall(voice_call_record)

    if data['status'] == "completed":
        voice_call_record.duration = data['duration']
        voice_call_record.start_time = data['start_time']
        voice_call_record.end_time = data.get('end_time')
        voice_call_record.call_rate = data['rate']
        voice_call_record.call_price = data['price']
        voice_call_record.success_threshold = success_threshold
    voice_call_record.save()

    if data['status'] in VonageOutboundCall.STATUS_WITH_DETAIL:
        save_status_detail_for_vonage_outbound_call.delay(voice_call_record.pk, data['detail'])

    is_loan_robocall_campaign = "promo_code" in str(voice_call_record.template_code)
    if is_loan_robocall_campaign and data['status'] != "completed":  
        check_and_send_sms_after_robocall(voice_call_record)
    # skip for covid campaign
    if voice_call_record.event_type == VoiceTypeStatus.COVID_CAMPAIGN:
        return
    loan_id = 0
    payment = None
    account_payment = None
    if voice_call_record.account_payment:
        account_payment = AccountPayment.objects.get_or_none(
            pk=voice_call_record.account_payment.id)
        if not account_payment:
            return
        payment_or_account_payment = account_payment
    else:
        payment = Payment.objects.get_or_none(pk=voice_call_record.voice_identifier)
        if not payment:
            return
        loan_id = payment.loan.id
        payment_or_account_payment = payment
    current_time = timezone.localtime(timezone.now()).strftime('%H')
    today_date = timezone.localtime(timezone.now()).date()
    # dayplus5 = today_date + relativedelta(days=5)
    dayplus3 = today_date + relativedelta(days=3)
    second_attempt_hour = 10
    third_attempt_hour = 12
    is_trigger_robocall_experiment = False
    if account_payment:
        attempt_count = VoiceCallRecord.objects.filter(
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            account_payment_id=account_payment.id, cdate__gte=timezone.localtime(
                timezone.now()).date()
        ).exclude(status__in=('started', 'ringing')).count()
        streamlined_config = StreamlinedCommunication.objects.filter(
            communication_platform=CommunicationPlatform.ROBOCALL,
            dpd=account_payment.dpd, type='Payment Reminder', extra_conditions__isnull=False).last()
        max_attempt = 3 if not streamlined_config else streamlined_config.attempts
        is_trigger_robocall_experiment = attempt_count >= max_attempt
    if data['status'] == "completed" and int(data['duration']) >= 8:
        if voice_call_record.event_type == VoiceTypeStatus.PAYMENT_REMINDER:
            # get_payment_experiment_ids
            # today = timezone.now().date()
            # roboscript_experiment_ids = get_payment_experiment_ids(
            #    today,
            #    ExperimentConst.ROBOCALL_SCRIPT)
            # success robocall payment reminder
            if data['duration'] and int(data['duration']) >= success_threshold:
                note_text = '{}{}{}{}{}'.format(
                    'call via robocall to ', data['to'],
                    ' with duration ', data['duration'], 's')
                payment_or_account_payment.is_robocall_active = True
                payment_or_account_payment.is_success_robocall = True
                payment_or_account_payment.save(update_fields=['is_robocall_active',
                                            'is_success_robocall',
                                            'udate'])
                if payment:
                    PaymentNote.objects.create(payment=payment,note_text=note_text)
                    LOGGER.info({
                        'action': 'call send_sms_robocall_success',
                        'payment_id': payment.id
                    })
                else:
                    account_payment_status_history = AccountPaymentStatusHistory.objects.filter(
                        account_payment=account_payment
                    ).last()
                    AccountPaymentNote.objects.create(
                        account_payment_status_history=account_payment_status_history,
                        note_text=note_text
                    )
                    payment = account_payment.payment_set.first()
                    LOGGER.info({
                        'action': 'call send_sms_robocall_success',
                        'account_payment_id': account_payment.id
                    })
                    # trigger sms after robocall
                    is_trigger_robocall_experiment = True

                if payment:
                    send_sms_robocall_success.delay(payment.id)
            # failed robocall payment reminder (duration < 28)
            else:
                if int(current_time) >= third_attempt_hour \
                        and payment_or_account_payment.due_date == dayplus3 and \
                        int(str(loan_id)[-1:]) in [4, 5, 6] \
                        and date(2019, 5, 24) <= today_date \
                        <= date(2019, 7, 5):
                    payment_or_account_payment.is_robocall_active = True
                elif int(current_time) >= second_attempt_hour \
                        and payment_or_account_payment.due_date == dayplus3 and \
                        int(str(loan_id)[-1:]) \
                        in [0, 1, 2, 3, 7, 8, 9] \
                        and date(2019, 5, 24) <= today_date\
                        <= date(2019, 7, 5):
                    payment_or_account_payment.is_robocall_active = False
                payment_or_account_payment.save(update_fields=['is_robocall_active', 'udate'])
        elif voice_call_record.event_type == \
                VoiceTypeStatus.PTP_PAYMENT_REMINDER:
            note_text = '{}{}{}{}{}'.format(
                'robocall ptp_reminder to ', data['to'], ' with duration ',
                data['duration'], 's')
            PaymentNote.objects.create(payment=payment, note_text=note_text)
            payment.is_collection_called = True
            payment.is_ptp_robocall_active = True
            payment.save(update_fields=['is_collection_called',
                                        'is_ptp_robocall_active',
                                        'udate'])
    elif voice_call_record.status not in ['started', 'ringing', 'answered']:
        if voice_call_record.event_type == VoiceTypeStatus.PAYMENT_REMINDER:
            if int(current_time) >= third_attempt_hour and \
                    payment_or_account_payment.due_date == dayplus3 and \
                    int(str(loan_id)[-1:]) in [4, 5, 6] \
                    and date(2019, 5, 24) <= today_date <= date(2019, 7, 5):
                payment_or_account_payment.is_robocall_active = True
            elif int(current_time) >= second_attempt_hour \
                    and payment_or_account_payment.due_date == dayplus3 and \
                    int(str(loan_id)[-1:]) in [0, 1, 2, 3, 7, 8, 9] \
                    and date(2019, 5, 24) <= today_date \
                    <= date(2019, 7, 5):
                payment_or_account_payment.is_robocall_active = False
            payment_or_account_payment.is_success_robocall = False
            payment_or_account_payment.save(update_fields=['is_robocall_active',
                                        'is_success_robocall',
                                        'udate'])
        elif voice_call_record.event_type == \
                VoiceTypeStatus.PTP_PAYMENT_REMINDER:
            payment.is_ptp_robocall_active = False
            payment.save(update_fields=['is_ptp_robocall_active', 'udate'])

    if is_trigger_robocall_experiment and account_payment:
        sms_after_robocall_experiment_trigger.delay(account_payment.id)


@task(name='store_voice_recording_data')
def store_voice_recording_data(data):
    conversation_uuid = data['conversation_uuid']
    data = dict(recording_uuid=data['recording_uuid'],
                rec_start_time=data['start_time'],
                rec_end_time=data['end_time'],
                recording_url=data['recording_url']
                )
    call_record_url = CallRecordUrl.objects.get_or_none(conversation_uuid=conversation_uuid)
    if call_record_url:
        current_data = call_record_url.__dict__
        call_record_url.update_safely(**data)
        LOGGER.info({
            "task": "store_voice_recording_data",
            "status": "exist conversation_uuid found updating data",
            "current_data": current_data,
            "new data": data
        })
    else:
        CallRecordUrl.objects.create(conversation_uuid=conversation_uuid, **data)
        LOGGER.info({
            "task": "store_voice_recording_data",
            "status": "create new record",
            "new data": data
        })

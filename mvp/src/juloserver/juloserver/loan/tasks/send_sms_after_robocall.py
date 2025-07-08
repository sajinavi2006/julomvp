import logging

from celery import task
from django.utils import timezone

from juloserver.julo.clients import get_julo_sms_after_robocall
from juloserver.julo.models import StatusLookup, Loan, SmsHistory, VoiceCallRecord
from juloserver.loan.constants import SMSStatus
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model

logger = logging.getLogger(__name__)


@task(queue='loan_robocall')
def send_sms_after_robocall(voice_call_record_pk, message):
    voice_call_record = VoiceCallRecord.objects.get(id=voice_call_record_pk)
    voice_call_record_detokenized = collection_detokenize_sync_object_model(
        PiiSource.VOICE_CALL_RECORD,
        voice_call_record,
        None,
        ['call_to'],
        PiiVaultDataType.KEY_VALUE,
    )
    # Filter loan >= 220, then do nothing
    loan_exists = Loan.objects.filter(
        account_id=voice_call_record.application.account_id,
        loan_status__gte=StatusLookup.CURRENT_CODE,
        cdate__gt=voice_call_record.udate,
        cdate__lt=timezone.now(),
    ).exists()
    if loan_exists:
        return

    # Request API to send SMS
    sms_client = get_julo_sms_after_robocall()
    xid = sms_client.send_sms(
        voice_call_record_detokenized.call_to, message, voice_call_record.template_code
    )

    # If send successfully, check status after sending SMS, delay = 5s
    if xid:
        check_status_send_sms.apply_async((xid,), countdown=5)


@task(queue='loan_robocall')
def check_status_send_sms(xid):
    # Request to check status
    sms_client = get_julo_sms_after_robocall()
    status = sms_client.check_status(xid)

    if status:
        sms_history = SmsHistory.objects.get(message_id=xid)
        sms_history.update_safely(status=status)
        if status != SMSStatus.DELIVERED:
            logger.info({
                'action': "check_status_send_sms.status_different_delivered",
                'status': status,
                'sms_history': sms_history,
            })

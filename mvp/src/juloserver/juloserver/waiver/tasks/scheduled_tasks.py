from celery import task
from datetime import timedelta
from django.db.models import Q
from django.utils import timezone

from juloserver.loan_refinancing.services.comms_channels import (
    get_account_ids_for_specific_indonesia_timezone,
    get_loan_ids_for_specific_indonesia_timezone
)
from juloserver.payback.constants import WaiverConst
from juloserver.payback.models import WaiverTemp
from juloserver.waiver.tasks.notification_tasks import send_email_multiple_ptp_expired_plus_1


@task(name="send_email_for_multiple_ptp_waiver_expired_plus_1_wib")
def send_email_for_multiple_ptp_waiver_expired_plus_1_wib():
    send_email_for_multiple_ptp_waiver_expired_plus_1.delay('WIB')


@task(name="send_email_for_multiple_ptp_waiver_expired_plus_1_wit")
def send_email_for_multiple_ptp_waiver_expired_plus_1_wit():
    send_email_for_multiple_ptp_waiver_expired_plus_1.delay('WIT')


@task(name="send_email_for_multiple_ptp_waiver_expired_plus_1_wita")
def send_email_for_multiple_ptp_waiver_expired_plus_1_wita():
    send_email_for_multiple_ptp_waiver_expired_plus_1.delay('WITA')


@task(name="send_email_for_multiple_ptp_waiver_expired_plus_1")
def send_email_for_multiple_ptp_waiver_expired_plus_1(timezone_part):
    account_ids_specific_timezone = get_account_ids_for_specific_indonesia_timezone(
        timezone_part)
    loan_ids_specific_timezone = get_loan_ids_for_specific_indonesia_timezone(
        timezone_part)
    today = timezone.localtime(timezone.now()).date()
    expired_plus_1 = today - timedelta(days=1)
    eligible_waiver_requests = WaiverTemp.objects.filter(
        Q(account_id__in=account_ids_specific_timezone) |
        Q(loan_id__in=loan_ids_specific_timezone)
    ).filter(
        waiver_request__isnull=False,
        status=WaiverConst.EXPIRED_STATUS,
        valid_until=expired_plus_1,
        waiver_request__is_multiple_ptp_payment=True,
    )
    for waiver_temp in eligible_waiver_requests:
        send_email_multiple_ptp_expired_plus_1.delay(
            waiver_temp.waiver_request.id)

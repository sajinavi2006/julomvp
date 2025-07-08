from celery import task
from datetime import timedelta
from babel.dates import format_date
from django.utils import timezone
from django.conf import settings
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User

from ..models import MultiplePaymentPTP
from ..services.notification_related import MultiplePaymentPTPEmail, WaiverRequestExpiredEmail

from juloserver.loan_refinancing.models import WaiverRequest
from juloserver.monitors.notifications import get_slack_bot_client


@task(name="send_slack_notification_for_j1_waiver_approver")
def send_slack_notification_for_j1_waiver_approver(account_id):
    today_date = timezone.localtime(timezone.now()).date()
    waiver_request = WaiverRequest.objects.filter(
        account_id=account_id, is_approved__isnull=True,
        is_automated=False, waiver_validity_date__gte=today_date
    ).order_by('cdate').last()
    if not waiver_request:
        return

    if not waiver_request.approver_group_name:
        return

    link = "{}{}?portal_type=approver_portal&account_id={}".format(
        settings.NEW_CRM_BASE_URL, reverse('waiver:collection-offer-j1'),
        account_id
    )
    message = (
        "Waiver untuk {} menunggu approval Anda. Silakan klik {} untuk melakukan "
        "pengecekan lebih lanjut. Mohon approve sebelum {}, jika terlambat, "
        "program customer akan hangus."
    ).format(
        account_id, link,
        format_date(waiver_request.waiver_validity_date, 'd MMMM yyyy', locale='id_ID')
    )

    users = User.objects.filter(is_active=True, groups__name=waiver_request.approver_group_name)
    for user in users:
        if user.email:
            slack_user = get_slack_bot_client().api_call("users.lookupByEmail", email=user.email)
            if slack_user["ok"]:
                get_slack_bot_client().api_call(
                    "chat.postMessage", channel=slack_user['user']['id'], text=message)


@task(name="send_all_multiple_payment_ptp_minus_reminder")
def send_all_multiple_payment_ptp_minus_reminder():
    multiple_payment_ptp = MultiplePaymentPTP.objects.filter(
        is_fully_paid=False,
        promised_payment_date=timezone.localtime(timezone.now()).date() + timedelta(days=1))
    for payment_ptp in multiple_payment_ptp:
        send_email_multiple_payment_ptp_minus_reminder.delay(payment_ptp.id)


@task(name="send_all_multiple_payment_ptp_reminder")
def send_all_multiple_payment_ptp_reminder():
    multiple_payment_ptp = MultiplePaymentPTP.objects.filter(
        is_fully_paid=False, promised_payment_date=timezone.localtime(timezone.now()).date())
    for payment_ptp in multiple_payment_ptp:
        send_email_multiple_payment_ptp_reminder.delay(payment_ptp.id)


@task(name="send_email_multiple_payment_ptp_minus_reminder")
def send_email_multiple_payment_ptp_minus_reminder(multiple_payment_ptp_id):
    multiple_payment_ptp = MultiplePaymentPTP.objects.get(pk=multiple_payment_ptp_id)
    MultiplePaymentPTPEmail(multiple_payment_ptp).send_multiple_payment_ptp_email_minus_reminder()


@task(name="send_email_multiple_payment_ptp_reminder")
def send_email_multiple_payment_ptp_reminder(multiple_payment_ptp_id):
    multiple_payment_ptp = MultiplePaymentPTP.objects.get(pk=multiple_payment_ptp_id)
    MultiplePaymentPTPEmail(multiple_payment_ptp).send_multiple_payment_ptp_email_reminder()


@task(name="send_email_multiple_ptp_expired_plus_1")
def send_email_multiple_ptp_expired_plus_1(waiver_request_id):
    waiver_request = WaiverRequest.objects.get(pk=waiver_request_id)
    WaiverRequestExpiredEmail(waiver_request).send_email_for_multiple_ptp_and_expired_plus_1()

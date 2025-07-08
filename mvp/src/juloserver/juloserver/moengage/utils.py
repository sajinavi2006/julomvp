from builtins import str
from builtins import range
from contextlib import contextmanager
from datetime import datetime
import math
from typing import List

from babel.dates import format_date
from django.db.models import Sum

from juloserver.account_payment.models import AccountPayment
from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.email_delivery.utils import email_status_prioritization
from juloserver.julo.clients import get_julo_sentry_client
from datetime import datetime
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.account_payment.models import AccountPayment
from django.db.models import Sum
from juloserver.julo.models import (
    Payment,
    Loan
)
from babel.dates import format_date

from juloserver.moengage.constants import MAX_EVENT


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


@contextmanager
def exception_captured(moengage_upload_id, status, reraise=True):
    from juloserver.moengage.models import MoengageUpload
    moengage_upload = MoengageUpload.objects.get(pk=moengage_upload_id)
    try:
        yield
    except Exception as e:
        moengage_upload.update_safely(
            status=status,
            error="%s: %s" % (type(e).__name__, str(e)))
        if not reraise:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
        else:
            raise


class SendToMoengageManager:
    """
    Handle the moengage bulk send by split the data if too many. Will chunk the data depends on
    `juloserver.moengage.constants.MAX_EVENT`

    ```
    with SendToMoengageManager() as moengage_manager:
        for customer_id in customer_list:
            moengage_upload = MoengageUpload.objects.create(...)
            user_attributes = construct_data(customer_id)

            moengage_manager.add(moengage_upload.id, [user_attributes])
    ```
    """
    def __init__(self):
        self.moengage_send_data = {}

    def __enter__(self):
        return self

    def __exit__(self, ctx_type, ctx_value, traceback):
        self.send()

    def add(self, moengage_upload_ids, elements):
        self.moengage_send_data[moengage_upload_ids] = elements
        if len(self.moengage_send_data) >= MAX_EVENT:
            self.send()

    def send(self):
        from juloserver.moengage.services.use_cases import send_to_moengage
        if len(self.moengage_send_data) == 0:
            return

        moengage_upload_ids = list(self.moengage_send_data.keys())
        data_to_send = sum(map(
            lambda moengage_upload_id: self.moengage_send_data[moengage_upload_id],
            moengage_upload_ids
        ), [])
        send_to_moengage.delay(moengage_upload_ids, data_to_send)
        self.moengage_send_data = {}


def day_on_status(cdate):
    if isinstance(cdate, datetime):
        cdate_obj = cdate
    else:
        cdate_obj = datetime.strptime(cdate, "%Y-%m-%d %H:%M:%S")
    current_day = datetime.today().date()
    difference = current_day - cdate_obj.date()
    return difference.days


def get_total_due_amount(account):
    account_details = AccountPayment.objects.filter(
        account=account,
        status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        due_amount__isnull=False
    ).aggregate(Sum('due_amount'))

    return account_details['due_amount__sum']


def total_of_cashback_amount(account):
    unpaid_account_payment_ids = account.get_unpaid_account_payment_ids()
    unpaid_payment_loan_ids = Payment.objects.select_related('loan').filter(
        account_payment_id__in=unpaid_account_payment_ids
    ).only('due_date', 'loan__loan_amount', 'loan__loan_duration')

    total_cashback_amount_account_level = 0
    for payment in unpaid_payment_loan_ids:
        loan = payment.loan
        payment_cashback_amount = (0.01 / loan.loan_duration) * loan.loan_amount
        total_cashback_amount = int(payment.cashback_multiplier * payment_cashback_amount)
        total_cashback_amount_account_level += total_cashback_amount

    return total_cashback_amount_account_level


def get_due_date_account_payment(account_payment):
    due_date = account_payment.due_date
    due_date_short = format_date(account_payment.due_date, 'd-MMM', locale='id_ID')
    due_date_long = format_date(account_payment.due_date, 'd MMMM yyyy', locale='id_ID')
    month_due_date = format_date(due_date, 'MMMM', locale='id_ID')
    month_and_year_due_date = format_date(due_date, 'M/YYYY', locale='id_ID')

    return due_date_short, due_date_long, month_due_date, month_and_year_due_date, due_date


def search_and_remove_postfix_data(data_to_check, search_key):
    formated_data = ""
    if search_key in data_to_check:
        partition_list = data_to_check.partition(search_key)
        formated_data = partition_list[0].strip()
        return formated_data
    return data_to_check


def format_money_to_rupiah(number):
    units = {
        1000000000: "Miliar",
        1000000: "Juta",
        1000: "Ribu",
    }
    for divisor, unit in units.items():
        if number >= divisor:
            result = number / divisor
            # Handling special case 1000
            if result == 1 and unit == "Ribu":
                return "Seribu"

            formatted = int(result) if result.is_integer() else math.floor(result * 10) / 10
            # Prevent writing of 15.0 Juta instead of 15 Juta
            formatted = int(formatted) if formatted % int(formatted) == 0 else formatted
            # Handling other special case like 1030, 10xx
            # if formatted == 1 and unit == "Ribu":
            # return "Seribu"
            if unit == "Ribu":
                if int(formatted) == 1:
                    return "Seribu"
                return f"{int(formatted)} {unit}"
            return f"{formatted} {unit}"

    return str(number)


def preprocess_moengage_stream(payload: List):
    # This will hold the latest email event for each unique combination of uid, campaign_id, email_id, and campaign_name
    latest_emails_by_key = {}
    # This will hold non-email events (SMS, PN, etc.) to return later
    non_email_events = []

    for event in payload:
        event_code = event.get('event_code')

        if event_code in EmailStatusMapping['MoEngageStream']:
            uid = event.get('uid')
            event_attributes = event.get('event_attributes', {})
            campaign_id = event_attributes.get('campaign_id')
            email_id = event.get('email_id')
            campaign_name = event_attributes.get('campaign_name')

            email_key = (uid, campaign_id, email_id, campaign_name)
            current_status = EmailStatusMapping['MoEngageStream'][event_code]
            if email_key in latest_emails_by_key:
                existing_event = latest_emails_by_key[email_key]
                existing_status = EmailStatusMapping['MoEngageStream'][existing_event['event_code']]

                final_status = email_status_prioritization(existing_status, current_status)
                # If the new event has a higher priority, replace the existing event
                if final_status == current_status:
                    latest_emails_by_key[email_key] = event
            else:
                latest_emails_by_key[email_key] = event
        else:
            non_email_events.append(event)

    sanitized_events = list(latest_emails_by_key.values()) + non_email_events

    return sanitized_events

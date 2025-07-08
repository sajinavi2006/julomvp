from builtins import str
import logging
from datetime import datetime, date, timedelta, time
import re

from django.db.models import Sum

from juloserver.julo.models import PaymentEvent, BankVirtualAccount, Payment
from juloserver.julo.services import process_partial_payment
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from .models import PaymentLocked
from app_status.models import ApplicationLocked
from django.forms.models import model_to_dict
from juloserver.followthemoney.models import LenderReversalTransaction


logger = logging.getLogger(__name__)


def validate_cashback_earned(payment_obj, paid_date_str, partial_payment):

    passed = False

    #get payment event for this
    sum_event_amount = PaymentEvent.objects.filter(
        payment=payment_obj).aggregate(Sum('event_payment'))

    paid_datetime = datetime.strptime(paid_date_str, "%d-%m-%Y")
    paid_date = paid_datetime.date()

    if 'event_payment__sum' in sum_event_amount and \
        sum_event_amount['event_payment__sum']:
        partial_payment += sum_event_amount['event_payment__sum']

    if payment_obj.loan.installment_amount > partial_payment:
        return passed

    if paid_date > payment_obj.due_date:
        return passed

    passed = True
    return passed


def payment_locked_data_user(request):
    if request.user.is_authenticated():
        result = PaymentLocked.objects.select_related('payment', 'payment__loan').filter(
            locked=True, status_obsolete=False, user_lock=request.user
        ).order_by("status_code_locked", "ts_locked")
        return result
    else:
        return None


def payment_and_app_locked_data_all(request):
    if request.user.is_authenticated():
        app_locked_users = ApplicationLocked.objects.order_by("user_lock_id").exclude(user_lock=request.user)\
            .distinct("user_lock_id").values_list("user_lock_id", flat=True)
        payment_locked_users = PaymentLocked.objects.order_by("user_lock_id").exclude(user_lock=request.user)\
            .distinct("user_lock_id").values_list("user_lock_id", flat=True)

        locked_users = list(set(list(app_locked_users) + list(payment_locked_users)))

        all_item_locked = []
        for user in locked_users:
            locked_apps = ApplicationLocked.objects.filter(
                locked=True, status_obsolete=False, user_lock=user
            ).order_by("status_code_locked")
            locked_payments = PaymentLocked.objects.filter(
                locked=True, status_obsolete=False, user_lock=user
            ).order_by("status_code_locked")
            all_item_locked.append({"user": user, "data": [locked_apps, locked_payments]})
        return all_item_locked
    else:
        return None

def save_payment_event_from_csv(data):
    data["Payment_Id"] = ""
    data["Email"] = ""
    data["Name"] = ""
    valid = validate_payment_event_data(data)
    if not valid:
        data["Updated"] = "Gagal"
        return data

    va = BankVirtualAccount.objects.get_or_none(virtual_account_number=data["VA"])
    if not va:
        data["Updated"] = "Gagal"
        data["Message"] = "Nomor VA tidak ditemukan"
        return data
    if not va.loan:
        data["Updated"] = "Gagal"
        data["Message"] = "VA tidak mempunyai Loan"
        return data

    payment_obj = va.loan.payment_set.not_paid_active().first()
    if not payment_obj:
        data["Updated"] = "Gagal"
        data["Message"] = "Payment tidak ditemukan"
        return data

    payment_event_saved = process_partial_payment(payment_obj,
                                            float(data["Amount"]),
                                            data["Payment Note / Bank Name"],
                                            paid_date_str=data["Payment Date"])
    if payment_event_saved:
        data["Updated"] = "Sukses"
        data["Message"] = ""
        data["Payment_Id"] = payment_obj.id
    else:
        data["Updated"] = "Gagal"
        data["Message"] = "Kesalahan disisi server"
    customer = payment_obj.loan.customer
    data["Email"] = customer.email
    data["Name"] = customer.fullname
    return data

def validate_payment_event_data(data):
    data["Message"] = ""
    if not re.match(r"^(\d{11}|\d{16})$", data["VA"]):
        data["Message"] = "VA tidak valid"
        return False
    if not data["Amount"].isdigit():
        data["Message"] = "Amount tidak valid"
        return False
    try:
        datetime_payment_date = datetime.strptime(data["Payment Date"], "%d-%m-%Y")
        if (datetime_payment_date.date() - datetime.now().date()).days > 0:
            data["Message"] = "Payment Date tidak valid"
            return False
    except ValueError:
        data["Message"] = "Payment Date tidak valid"
        return False
    if not data["Payment Note / Bank Name"]:
        data["Message"] = "Payment Note / Bank Name tidak boleh kosong"
        return False
    return True

def check_change_due_date_active(payment, loan_obj, status_current):
    if payment.late_fee_amount > 0:
        return False

    if status_current.status_code >= PaymentStatusCodes.PAID_ON_TIME:
        return False

    if payment.paid_amount > 0:
        return False

    first_unpaid_payment = loan_obj.payment_set.filter(
        payment_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME).order_by(
        'payment_number').first()
    if payment.payment_number > first_unpaid_payment.payment_number:
        return False

    late_paid_count = 1 if (payment.due_date < date.today()) else 0

    late_paid = payment.loan.payment_set.filter(
        payment_status__status_code__in=(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                                         PaymentStatusCodes.PAID_LATE)
    )
    late_paid_count += len(late_paid)
    if late_paid_count > 2:
        return False

    return True

def check_first_installment_btn_active(payment_obj, application=None):
    loan_obj = payment_obj.loan
    if not application:
        application = loan_obj.application
    if application.product_line_code in ProductLineCodes.stl():
        if loan_obj.loan_status.status_code < LoanStatusCodes.CURRENT:
            return True
    else:
        if loan_obj.loan_status.status_code < LoanStatusCodes.PAID_OFF:
            return True
    return False

def check_first_installment_btn_active_account_payment(loan_obj):
    if loan_obj.loan_status.status_code < LoanStatusCodes.PAID_OFF:
        return True
    return False

def create_reversal_transaction(payment_event_origin, payment_dest_id):
    lender_dest = None
    bank_name = None
    account_number = None
    loan_desc = str(payment_event_origin.payment.loan.id)
    if payment_dest_id:
        payment_dest = Payment.objects.get(pk=payment_dest_id)
        lender_dest = payment_dest.loan.lender
        lba = lender_dest.lenderbankaccount_set.filter(bank_account_type='repayment_va').last()
        bank_name = lba.bank_name
        account_number = lba.account_number
        loan_desc += ' to %s' % payment_dest.loan.id

    LenderReversalTransaction.objects.create(
        source_lender=payment_event_origin.payment.loan.lender,
        amount=abs(payment_event_origin.event_payment),
        destination_lender=lender_dest,
        bank_name=bank_name,
        va_number=account_number,
        voided_payment_event=payment_event_origin,
        loan_description=loan_desc
    )

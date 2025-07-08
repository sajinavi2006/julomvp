import logging
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from juloserver.cashback.constants import OverpaidConsts
from juloserver.cashback.models import CashbackEarned, CashbackOverpaidVerification
from juloserver.cashback.utils import chunker
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import CustomerWalletHistory

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def compute_cashback_expiry_date(cdate, today):
    end_of_year = date(today.year, month=12, day=31)
    if cdate.year < today.year:
        return end_of_year

    end_of_next_year = date(today.year + 1, month=12, day=31)

    if (cdate.month - 1) // 3 < 3:
        return end_of_year
    else:
        return end_of_next_year


def get_wallet_histories_by_customer(customer):
    return CustomerWalletHistory.objects.select_related('customer').filter(customer=customer)\
        .select_for_update().order_by('id')


def handling_verification_cashback_overpaid_reason(wallet_history,
                                                   wallet_history_list,
                                                   cashback_earned_list,
                                                   cashback_amount,
                                                   today):
    verified = True
    cashback_earned = wallet_history.cashback_earned
    overpaid_verification = CashbackOverpaidVerification.objects.get_or_none(
        wallet_history=wallet_history
    )
    if overpaid_verification and overpaid_verification.status != OverpaidConsts.Statuses.ACCEPTED:
        verified = False

    if cashback_earned:
        cashback_earned.current_balance = cashback_amount
        cashback_earned.expired_on_date = compute_cashback_expiry_date(
            wallet_history.cdate, today
        )
        cashback_earned.verified = verified
        cashback_earned.udate = timezone.localtime(timezone.now())
    else:
        cashback_earned = CashbackEarned.objects.create(
            current_balance=cashback_amount,
            expired_on_date=compute_cashback_expiry_date(
                wallet_history.cdate,
                today
            ),
            verified=verified
        )
    wallet_history.cashback_earned = cashback_earned
    wallet_history_list.append(wallet_history)
    # adding flag=True only for cashback_overpaid case
    cashback_earned_list.append((cashback_earned, True, cashback_amount))


def handling_for_other_cashback_reason(wallet_history,
                                       wallet_history_list,
                                       cashback_earned_list,
                                       cashback_amount,
                                       today):
    verified = True
    cashback_earned = wallet_history.cashback_earned
    if cashback_earned:
        cashback_earned.current_balance = cashback_amount
        cashback_earned.expired_on_date = compute_cashback_expiry_date(
            wallet_history.cdate, today
        )
        cashback_earned.verified = verified
        cashback_earned.udate = timezone.localtime(timezone.now())
    else:
        cashback_earned = CashbackEarned.objects.create(
            current_balance=cashback_amount,
            expired_on_date=compute_cashback_expiry_date(
                wallet_history.cdate,
                today
            ),
            verified=verified
        )
    wallet_history.cashback_earned = cashback_earned
    wallet_history_list.append(wallet_history)
    cashback_earned_list.append((cashback_earned, False, cashback_amount))


def handling_overpaid_verification_refund_reason(cashback_earned_list, cashback_amount):
    for cashback_earned_obj, is_overpaid, original_amount in cashback_earned_list:
        if is_overpaid and abs(original_amount) == abs(cashback_amount):
            cashback_earned_obj.current_balance = cashback_amount
            cashback_earned_obj.udate = timezone.localtime(timezone.now())
            return
    raise Exception('cashback_overpaid case is not found')


def handling_verifying_overpaid_and_overpaid_void_reason(cashback_earned_list, cashback_amount):
    for cashback_earned_obj, is_overpaid, original_amount in cashback_earned_list:
        if is_overpaid and cashback_earned_obj is not None \
                and abs(original_amount) == abs(cashback_amount):
            current_balance = cashback_earned_obj.current_balance
            current_balance += cashback_amount
            cashback_earned_obj.current_balance = current_balance
            cashback_earned_obj.udate = timezone.localtime(timezone.now())
            return
    raise Exception('cashback_overpaid case is not found')


def handling_cashback_deduction(cashback_earned_list,
                                cashback_amount):
    validated_cashback_earned_list = lookup_wallet_history_for_deduction(cashback_earned_list)

    for cashback_earned in validated_cashback_earned_list:
        current_balance = cashback_earned.current_balance
        current_balance += cashback_amount
        cashback_amount = current_balance
        if current_balance < 0:
            current_balance = 0
        cashback_earned.current_balance = current_balance
        cashback_earned.udate = timezone.localtime(timezone.now())
        if cashback_amount >= 0:
            break


def lookup_wallet_history_for_deduction(cashback_earned_list):
    validated_cashback_earned_list = []

    for cashback_earned_obj, is_overpaid, original_amount in cashback_earned_list:
        if cashback_earned_obj and cashback_earned_obj.current_balance > 0 \
                and cashback_earned_obj.verified is True:
            validated_cashback_earned_list.append(cashback_earned_obj)

    return validated_cashback_earned_list


class Command(BaseCommand):
    help = """correcting cashback_earned and cashback_balance of customers"""

    def handle(self, *args, **kwargs):
        from juloserver.cashback.tasks import update_cashback_earned_and_cashback_balance
        queryset = CustomerWalletHistory.objects.distinct(
            'customer_id'
        ).values_list('customer_id', flat=True)
        today = timezone.localtime(timezone.now()).date()
        ids_counter = 0
        for ids in chunker(queryset.iterator()):
            ids_counter += len(ids)
            update_cashback_earned_and_cashback_balance.delay(ids, today)
            self.stdout.write("Finished the process of updating %i of ids." % ids_counter)

        self.stdout.write("Retroload is run successfully.")

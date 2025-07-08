import json
import logging
import itertools
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.db.models import Prefetch
from django.db import transaction
from django.utils import timezone

from juloserver.grab.models import GrabLoanData
from juloserver.grab.services.services import graveyard_loan_statuses
from juloserver.grab.models import GrabLoanData
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.models import Payment, Loan, StatusLookup, Application, ApplicationNote
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from collections import defaultdict
from juloserver.grab.exceptions import GrabHaltResumeError

logger = logging.getLogger(__name__)


def retro_account_payment_due_date(account_id):
    """
    This script needs to be run on those accounts which needs a fix for account payment:
    Case to check:
    1. Number of unique payment_due_date <= no of unique account payment due_date
    Example:
        account_ids = [123, 456, 789]
        retro_account_payment_due_date(account_ids)
    """
    failed_account = []
    payment_queryset_all = Payment.objects.select_related('account_payment').all().order_by('payment_number')
    prefetch_payments_all = Prefetch(
        'payment_set', to_attr="prefetch_payments_all", queryset=payment_queryset_all
    )

    join_payment_tables = [
        prefetch_payments_all,
    ]

    loan_query_set = Loan.objects.filter(loan_status_id__in={
        LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD, LoanStatusCodes.LOAN_5DPD,
        LoanStatusCodes.LOAN_30DPD, LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
        LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD, LoanStatusCodes.LOAN_180DPD,
        LoanStatusCodes.PAID_OFF, LoanStatusCodes.HALT
    }).prefetch_related(*join_payment_tables)
    prefetch_loans = Prefetch('loan_set', to_attr="prefetch_loans", queryset=loan_query_set)

    account_payment_all_queryset = AccountPayment.objects.select_related('account').filter(
        is_restructured=False).order_by('id')
    prefetch_account_payments_all = Prefetch(
        'accountpayment_set', to_attr="prefetch_accountpayments_all",
        queryset=account_payment_all_queryset)

    join_tables = [
        prefetch_loans,
        prefetch_account_payments_all
    ]
    account = Account.objects.prefetch_related(*join_tables).filter(id=account_id).last()
    paid_off_status = StatusLookup.objects.filter(status_code=330).last()
    unpaid_status = StatusLookup.objects.filter(status_code=310).last()

    # Map due_date with the due_amount, paid_amount, etc, per payment.
    # Will aggregate all payment for paid and unpaid (>220)
    # The key is due_date
    payment_dict_outer = defaultdict()
    for loan in account.prefetch_loans:
        for payment in loan.prefetch_payments_all:
            payment_dict_outer = update_payment_dict(payment_dict_outer, payment)

    # Store the list of due_date and account_payment_id in account_payment
    account_payment_due_dates_all = set()
    account_payment_ids_all = set()
    for account_payment in account.prefetch_accountpayments_all:
        account_payment_due_dates_all.add(account_payment.due_date)
        account_payment_ids_all.add(account_payment.id)

    # Need to sort because we will iterate this based on account_payment.
    payment_due_dates = list(payment_dict_outer.keys())
    payment_due_dates.sort()
    try:
        with transaction.atomic():
            # Iterate all account_payment (order by due_date) for an account
            for i, account_payment in enumerate(account.prefetch_accountpayments_all):
                # ???if There is no payment for account_payment
                # then set the status of account_payment
                # Can we just call check_status(account_payment)?
                if i >= len(payment_due_dates):
                    continue

                due_date_added = payment_due_dates[i]
                if account_payment.due_date == due_date_added:
                    if payment_dict_outer[due_date_added]['due_amount'] == account_payment.due_amount:
                        if account_payment.due_amount == 0 and account_payment.status_id not in {
                            PaymentStatusCodes.PAID_ON_TIME,
                            PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                            PaymentStatusCodes.PAID_LATE
                        }:
                            account_payment.status = paid_off_status
                        elif account_payment.due_amount > 0 and account_payment.status_id in {
                            PaymentStatusCodes.PAID_ON_TIME,
                            PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                            PaymentStatusCodes.PAID_LATE
                        }:
                            account_payment.status = unpaid_status
                            check_status(account_payment)

                        update_account_payment_on_payment(payment_dict_outer, account_payment, due_date_added)
                        account_payment_ids_all.remove(account_payment.id)
                        # Why need to update this?
                        account_payment.save(update_fields=[
                            'due_amount', 'principal_amount', 'interest_amount',
                            'late_fee_amount', 'paid_amount', 'paid_principal',
                            'paid_interest', 'paid_late_fee', 'status'
                        ])
                        continue

                # If account_payment.due_date is different from first due_date of payment.
                account_payment.due_date = due_date_added

                # Update change all payment with the same due_date to this account_payment.
                update_account_payment_based_on_payment_dict(
                    payment_dict_outer, account_payment, due_date_added, unpaid_status, paid_off_status)
                update_account_payment_on_payment(payment_dict_outer, account_payment, due_date_added)
                check_status(account_payment)
                if account_payment.id in account_payment_ids_all:
                    account_payment_ids_all.remove(account_payment.id)
            if len(payment_due_dates) >= len(account.prefetch_accountpayments_all):
                for due_date in payment_due_dates:
                    if due_date <= due_date_added:
                        continue
                    else:
                        account_payment = AccountPayment.objects.create(
                            account=account,
                            late_fee_amount=0,
                            due_date=due_date,
                            status_id=330,
                        )
                        update_account_payment_based_on_payment_dict(
                            payment_dict_outer, account_payment, due_date, unpaid_status, paid_off_status)
                        update_account_payment_on_payment(payment_dict_outer, account_payment, due_date)
                        check_status(account_payment)
                        if account_payment.id in account_payment_ids_all:
                            account_payment_ids_all.remove(account_payment.id)
            # I don't think we will have this case.
            else:
                AccountPayment.objects.filter(id__in=account_payment_ids_all).update(
                    due_amount=0,
                    principal_amount=0,
                    interest_amount=0,
                    late_fee_amount=0,
                    paid_late_fee=0,
                    paid_interest=0,
                    paid_principal=0,
                    paid_amount=0,
                    status=paid_off_status,
                    is_restructured=True
                )
    except SyntaxError as e:
        print('{} - {}'.format(account.id, e))
        failed_dict = {"account_id": account.id, "error": str(e)}
        failed_account.append(failed_dict)
    return failed_account


def assert_account_payment(account_id):
    """
    Validate if the account_payment is okay or not. Raise AssertionError is not valid.
    :param account_id:
    :return: Boolean
    """
    now = timezone.localtime(timezone.now())
    account_payments = AccountPayment.objects.filter(account_id=account_id).order_by('due_date')
    logger_data = {
        'account_id': account_id
    }
    for account_payment in account_payments.iterator():
        logger_data.update(
            account_payment_id=account_payment.id,
            account_payment_due_date=account_payment.due_date,
            account_payment_status_id=account_payment.status_id,
        )

        # check status
        if account_payment.due_amount == 0:
            if account_payment.paid_date is not None:
                if (
                    account_payment.paid_date > account_payment.due_date
                    and account_payment.status_id not in (
                        PaymentStatusCodes.PAID_LATE,
                        PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                    )
                ):
                    raise AssertionError('Account Payment Status is not late', logger_data)

            if account_payment.status_id not in (PaymentStatusCodes.PAID_ON_TIME,):
                raise AssertionError('Account payment status is not on time x330', logger_data)

        # check payment
        payment_count_data = {
            "due_amount": 0,
            "principal_amount": 0,
            "interest_amount": 0,
            "late_fee_amount": 0,
            "paid_amount": 0,
            "paid_principal": 0,
            "paid_interest": 0,
            "paid_late_fee": 0,
        }
        extra = {
            "total_payment": 0,
            "payment_infos": []
        }
        for payment in account_payment.payment_set.iterator():
            payment_logger_data = {
                "payment_id": payment.id,
                "payment_status_code": payment.payment_status_id,
                "payment_due_date": payment.due_date,
                **logger_data
            }
            if payment.due_date != account_payment.due_date:
                raise AssertionError("Payment due_date is not same account payment due_date", payment_logger_data)

            if (
                account_payment.status_id in PaymentStatusCodes.paid_status_codes()
                and payment.payment_status_id not in PaymentStatusCodes.paid_status_codes()
            ):
                raise AssertionError(
                    "Payment status code is not paid off but account payment is paid off", payment_logger_data
                )

            payment_count_data["due_amount"] += payment.due_amount
            payment_count_data["principal_amount"] += payment.installment_principal
            payment_count_data["interest_amount"] += payment.installment_interest
            payment_count_data["late_fee_amount"] += payment.late_fee_amount
            payment_count_data["paid_amount"] += payment.paid_amount
            payment_count_data["paid_principal"] += payment.paid_principal
            payment_count_data["paid_interest"] += payment.paid_interest
            payment_count_data["paid_late_fee"] += payment.paid_late_fee
            extra["total_payment"] += 1
            extra["payment_infos"].append((payment.id, payment.due_date, payment.payment_status_id))

        ap_count_data = {field_name: getattr(account_payment, field_name) for field_name in payment_count_data.keys()}
        for field_name in payment_count_data.keys():
            if getattr(account_payment, field_name) != payment_count_data[field_name]:
                raise AssertionError(f"Account payment {field_name} is not correct", {
                    "account_payment_count_data": ap_count_data,
                    "payment_count_data": payment_count_data,
                    "extra": extra,
                    **logger_data
                })

    return True


def assert_loan(loan_id):
    """
    Validate if loan and payment data is correct. Raise AssertionError is not valid.
    :param loan_id:
    :return: Boolean
    """
    from juloserver.grab.services.services import graveyard_loan_statuses
    loan = Loan.objects.get(id=loan_id)
    grab_loan_data = GrabLoanData.objects.filter(loan_id=loan_id).last()
    halt_date = grab_loan_data.loan_halt_date if grab_loan_data else None
    resume_date = grab_loan_data.loan_resume_date if grab_loan_data else None

    logger_data = {
        'loan_id': loan.id,
        'account_id': loan.account_id,
        'loan_status_code': loan.loan_status_id,
        'grab_loan_data': grab_loan_data.id if grab_loan_data else None,
        'halt_date': halt_date,
        'resume_date': resume_date,
    }

    # Skip is the loan status is graveyard
    if (
        loan.loan_status_id in itertools.chain(graveyard_loan_statuses, [LoanStatusCodes.HALT])
        or loan.loan_status_id < LoanStatusCodes.CURRENT
    ):
        return True

    if halt_date and not resume_date:
        raise AssertionError("No resume date in GrabLoanData")

    # Check if there is any unpaid payment but the loan is paid
    if loan.loan_status_id in PaymentStatusCodes.paid_status_codes():
        unpaid_payments = loan.payment_set.exclude(payment_status_id__in=PaymentStatusCodes.paid_status_codes())
        if unpaid_payments.count() > 0:
            raise AssertionError("There are some payment that are not paid off. (Loan is paid off)", {
                'count_unpaid_payment': unpaid_payments.count(),
                'unpaid_payment_ids': [unpaid_payment.id for unpaid_payment in unpaid_payments.iterator()],
                **logger_data
            })
        return True

    # Check all the payment for unpaid loan
    # 1. Check first due_date is greater than loan.cdate+3
    due_dates = []
    for payment in loan.payment_set.order_by('payment_number').iterator():
        logger_data.update(
            payment_id=payment.id,
            payment_number=payment.payment_number,
            payment_due_date=payment.due_date,
            payment_status_id=payment.payment_status_id,
        )
        if payment.payment_number == 1 and (loan.cdate.date() - payment.due_date).days > 3:
            raise AssertionError("Payment first due date is < loan.cdate + 3", logger_data)

        if (
            resume_date
            and halt_date
            and halt_date <= payment.due_date < resume_date
        ):
            raise AssertionError("Payment due date is in halt period", logger_data)

        if (
            payment.due_amount == 0
            and payment.payment_status_id not in PaymentStatusCodes.paid_status_codes()
        ):
            raise AssertionError("Payment is not paid off but due_amount is 0.", {
                'payment_due_amount': payment.due_amount,
                **logger_data,
            })

        if payment.account_payment and payment.due_date != payment.account_payment.due_date:
            raise AssertionError("Payment is unsync with Account Payment due_date.", {
                'account_payment_id': payment.account_payment_id,
                'account_payment_due_date': payment.account_payment.due_date,
                **logger_data,
            })

        if payment.due_date in due_dates:
            raise AssertionError("Payment double due_date.", logger_data)

        due_dates.append(payment.due_date)

    if due_dates != sorted(due_dates):
        raise AssertionError("Payment is not sorted based on payment_number.", {
            'due_dates': due_dates,
            **logger_data,
        })

    return True


def update_payment_dict(payment_dict, payment):
    if payment.due_date in set(payment_dict.keys()):
        return update_payment_data_dict(payment_dict, payment)

    payment_dict[payment.due_date] = format_payment_data(payment)
    return payment_dict


def update_payment_data_dict(my_dict_outer, payment):
    my_dict = my_dict_outer[payment.due_date]
    my_dict['due_amount'] += payment.due_amount
    my_dict['paid_amount'] += payment.paid_amount
    my_dict['installment_principal'] += payment.installment_principal
    my_dict['installment_interest'] += payment.installment_interest
    my_dict['paid_principal'] += payment.paid_principal
    my_dict['paid_interest'] += payment.paid_interest
    my_dict['late_fee_amount'] += payment.late_fee_amount
    my_dict['paid_late_fee'] += payment.paid_late_fee
    my_dict['payment_ids'].add(payment.id)
    my_dict['account_payment_ids'].add(payment.account_payment.id)
    my_dict_outer[payment.due_date] = my_dict
    return my_dict_outer


def format_payment_data(payment):
    my_dict = dict()
    my_dict['due_amount'] = payment.due_amount
    my_dict['paid_amount'] = payment.paid_amount
    my_dict['installment_principal'] = payment.installment_principal
    my_dict['installment_interest'] = payment.installment_interest
    my_dict['paid_principal'] = payment.paid_principal
    my_dict['paid_interest'] = payment.paid_interest
    my_dict['late_fee_amount'] = payment.late_fee_amount
    my_dict['paid_late_fee'] = payment.paid_late_fee
    my_dict['payment_ids'] = {payment.id}
    my_dict['account_payment_ids'] = {payment.account_payment.id}
    return my_dict


def check_status(account_payment):
    from juloserver.account_payment.services.payment_flow import update_account_payment_paid_off_status
    from juloserver.account_payment.tasks import update_account_payment_status_subtask
    """
    Update the account_payment status_code based on due_amount and due_date
    :param account_payment: AccountPayment Object
    :return: None
    """
    if account_payment.due_amount == 0:
        update_account_payment_paid_off_status(account_payment)
        account_payment.save(update_fields=['status', 'udate'])
        return

    update_account_payment_status_subtask(account_payment.id)


def update_account_payment_based_on_payment_dict(
        payment_dict_outer, account_payment, due_date_added, unpaid_status, paid_off_status):
    payment_qs = Payment.objects.filter(
        id__in=list(payment_dict_outer[due_date_added]['payment_ids'])
    )
    payment_qs.update(account_payment=account_payment)

    account_payment.due_amount = float(
        payment_dict_outer[due_date_added]['due_amount'])
    account_payment.principal_amount = float(
        payment_dict_outer[due_date_added]['installment_principal'])
    account_payment.interest_amount = float(
        payment_dict_outer[due_date_added]['installment_interest'])
    account_payment.late_fee_amount = float(
        payment_dict_outer[due_date_added]['late_fee_amount'])
    account_payment.paid_amount = float(
        payment_dict_outer[due_date_added]['paid_amount'])
    account_payment.paid_principal = float(
        payment_dict_outer[due_date_added]['paid_principal'])
    account_payment.paid_interest = float(
        payment_dict_outer[due_date_added]['paid_interest'])
    account_payment.paid_late_fee = float(
        payment_dict_outer[due_date_added]['paid_late_fee'])
    if float(payment_dict_outer[due_date_added]['due_amount']) > 0:
        account_payment.status = unpaid_status
    else:
        account_payment.status = paid_off_status
    account_payment.save(update_fields=[
        'due_amount', 'principal_amount', 'interest_amount',
        'late_fee_amount', 'paid_amount', 'paid_principal',
        'paid_interest', 'paid_late_fee', 'due_date', 'status'
    ])


def update_account_payment_on_payment(payment_dict_outer, account_payment, due_date_added):
    payment_qs = Payment.objects.filter(
        id__in=list(payment_dict_outer[due_date_added]['payment_ids'])
    )
    payment_qs.update(account_payment=account_payment)


def update_loan_payments_for_loan_halt_v2(loan, halt_date):
    from juloserver.grab.tasks import update_grab_payment_data_for_halt_resume_v2
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    logger.info({
        "task": "update_loan_payments_for_loan_halt_v2",
        "loan_halt": halt_date,
        "action": "starting_loan_updation",
        "loan_id": loan.id
    })
    try:
        grab_loan_data = loan.grab_loan_data_set[0]
        if not grab_loan_data:
            logger.info({
                "task": "update_loan_payments_for_loan_halt_v2",
                "loan_halt": halt_date,
                "action": "error_due_to_no_grab_data",
                "loan_id": loan.id,
                "message": "missing grab loan data"
            })
            raise GrabHaltResumeError('Grab Loan Data not found')
    except AttributeError as err:
        logger.info({
            "task": "update_loan_payments_for_loan_halt_v2",
            "loan_halt": halt_date,
            "action": "error_due_to_no_grab_data",
            "loan_id": loan.id,
            "message": str(err)
        })
        raise GrabHaltResumeError('Grab Loan Data not found')

    grab_loan_data.update_safely(loan_halt_date=halt_date, refresh=False)
    update_grab_payment_data_for_halt_resume_v2.apply_async(
        (loan.id,), {'is_description_flag': False},
        eta=timezone.localtime(timezone.now()) + timedelta(minutes=10))
    new_status_code = LoanStatusCodes.HALT
    if loan.loan_status_id != LoanStatusCodes.HALT:
        update_loan_status_and_loan_history(
            loan.id, new_status_code, None, 'loan_halt_triggered')

    logger.info({
        "task": "update_loan_payments_for_loan_halt_v2",
        "loan_halt": halt_date,
        "action": "ending_loan_updation_and_status",
        "loan_id": loan.id
    })


def update_loan_payments_for_loan_resume_v2(loan, loan_resume_date, loan_halt_date):
    logger.info({
        "task": "update_loan_payments_for_loan_resume_v2",
        "loan_resume_date": loan_resume_date,
        "action": "starting_loan_updation",
        "loan_id": loan.id
    })
    try:
        grab_loan_data = loan.grab_loan_data_set[0]
        if not grab_loan_data:
            logger.info({
                "task": "update_loan_payments_for_loan_resume_v2",
                "loan_halt": loan_resume_date,
                "action": "error_due_to_no_grab_data",
                "loan_id": loan.id,
                "message": "missing grab loan data"
            })
            raise GrabHaltResumeError('Grab Loan Data not found')
    except AttributeError as err:
        logger.info({
            "task": "update_loan_payments_for_loan_resume_v2",
            "loan_halt": loan_resume_date,
            "action": "error_due_to_no_grab_data",
            "loan_id": loan.id,
            "message": str(err)
        })
        raise GrabHaltResumeError('Grab Loan Data not found')

    update_payments_for_resumed_loan_v2(loan, loan_resume_date, loan_halt_date)
    grab_loan_data.update_safely(loan_resume_date=loan_resume_date, refresh=False)
    logger.info({
        "task": "update_loan_payments_for_loan_resume_v2",
        "loan_resume_date": loan_resume_date,
        "action": "ending_loan_payment_updation",
        "loan_id": loan.id
    })


def update_payments_for_resumed_loan_v2(loan, resume_date, halt_date):
    logger.info({
        "task": "update_payments_for_resumed_loan_v2",
        "status": "starting_process"
    })
    payments = Payment.objects.select_related('loan__loan_status', 'loan__account').filter(
        loan_id=loan.id).not_paid_active().filter(
        due_date__gte=halt_date).order_by('payment_number')

    days_diff = (resume_date - halt_date).days

    for payment in payments.iterator():
        due_date = payment.due_date + relativedelta(days=days_diff)
        payment.update_safely(due_date=due_date, refresh=False)
    logger.info({
        "task": "update_payments_for_resumed_loan_v2",
        "status": "ending_process"
    })


def update_loan_halt_and_resume_date(grab_loan_data, loan_halt_date, loan_resume_date):
    logger.info({
        "task": "update_loan_halt_and_resume_date",
        "status": "starting_process"
    })
    account_halt_info = grab_loan_data.account_halt_info
    if account_halt_info:
        account_halt_info = account_halt_info
    if not account_halt_info:
        account_halt_info = []
    if account_halt_info:
        for account_halt_info_check in account_halt_info:
            existing_halt_date, existing_resume_date = account_halt_info_check['account_halt_date'], \
                account_halt_info_check['account_resume_date']
            if existing_halt_date == loan_halt_date.strftime('%Y-%m-%d') and \
                    existing_resume_date == loan_resume_date.strftime('%Y-%m-%d'):
                return

    data_to_update = {
        "account_halt_date": loan_halt_date.strftime('%Y-%m-%d'),
        "account_resume_date": loan_resume_date.strftime('%Y-%m-%d')
    }
    account_halt_info.append(data_to_update)
    grab_loan_data.update_safely(account_halt_info=account_halt_info)
    logger.info({
        "task": "update_loan_halt_and_resume_date",
        "status": "ending_process"
    })


def get_loan_halt_and_resume_dates(grab_loan_data):
    account_halt_info = grab_loan_data.account_halt_info
    if account_halt_info:
        account_halt_info = account_halt_info
    if not account_halt_info:
        return []
    account_halt_info = account_halt_info
    for account_halt_data in account_halt_info:
        account_halt_data['account_halt_date'] = datetime.strptime(
            account_halt_data['account_halt_date'], '%Y-%m-%d').date()
        account_halt_data['account_resume_date'] = datetime.strptime(
            account_halt_data['account_resume_date'], '%Y-%m-%d').date()
    return account_halt_info

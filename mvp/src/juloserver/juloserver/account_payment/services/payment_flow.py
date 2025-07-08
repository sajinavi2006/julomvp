import json
import logging
from datetime import timedelta
from celery import chain

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from django.utils.datetime_safe import datetime

from juloserver.account.constants import CheckoutPaymentType, AccountTransactionNotes
from juloserver.account.models import AccountTransaction
from juloserver.account.services.credit_limit import update_account_limit
from juloserver.account_payment.models import (
    AccountPayment,
    AccountPaymentNote,
    AccountPaymentPreRefinancing,
    CheckoutRequest,
)
from juloserver.collectionbucket.models import CollectionRiskVerificationCallList
from juloserver.early_limit_release.services import update_or_create_release_tracking, \
    get_delay_seconds_call_from_repayment
from juloserver.julo.partners import PartnerConstant
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.omnichannel.tasks import process_repayment_event_for_omnichannel
from juloserver.waiver.models import WaiverAccountPaymentRequest
from juloserver.account_payment.services.earning_cashback import (
    j1_update_cashback_earned,
)
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.julo.constants import (
    MAX_PAYMENT_OVER_PAID,
    NewCashbackReason,
    NewCashbackConst,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    PTP,
    Payment,
    PaymentEvent,
    PaymentNote,
    CootekRobocall,
    FeatureSetting,
    CashbackCounterHistory,
)
from juloserver.julo.utils import display_rupiah, execute_after_transaction_safely
from juloserver.monitors.notifications import get_slack_client
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.account_payment.tasks.scheduled_tasks import send_early_repayment_experience_pn

from juloserver.minisquad.tasks2.intelix_task import (
    delete_paid_payment_from_intelix_if_exists_async_for_j1)
from juloserver.minisquad.services import insert_data_into_commission_table_for_j1

from juloserver.account_payment.services.collection_related import (
    update_ptp_for_paid_off_account_payment,
    ptp_update_for_j1,
    get_cashback_claim_experiment,
)
from juloserver.julo.services import get_grace_period_days, record_data_for_cashback_new_scheme
from juloserver.collection_vendor.task import process_unassignment_when_paid_for_j1
from juloserver.julo.services import (
    update_is_proven_account_payment_level,
)
from juloserver.cootek.tasks import cancel_phone_call_for_payment_paid_off
from juloserver.rentee import services as rentee_service
from juloserver.collection_field_automation.task import process_unassignment_field_assignment
from juloserver.minisquad.tasks2.google_calendar_task import set_google_calendar_when_paid
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account_payment.tasks import update_checkout_request_status_to_finished
from juloserver.minisquad.services2.dialer_related import \
    delete_temp_bucket_base_on_account_payment_ids_and_bucket
from juloserver.minisquad.tasks2.dialer_system_task import (
    delete_paid_payment_from_dialer,
    handle_manual_agent_assignment_payment,
)

from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.early_limit_release.tasks import check_and_release_early_limit
from juloserver.early_limit_release.constants import FeatureNameConst
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.credgenics.tasks.loans import update_credgenics_loan_task
from juloserver.minisquad.tasks import sent_webhook_to_field_collection_service_by_category
from juloserver.account_payment.constants import FeatureNameConst as AccountPaymentFeatureNameConst


sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def consume_payment_for_principal(
    payments, remaining_amount, account_payment, waiver_request=None, waiver_amount=None
):
    total_paid_principal = 0
    for payment in payments:
        logger.info(
            {
                'action': 'consume_payment_for_principal',
                'status': 'pre-comsume',
                'waiver_request': waiver_request,
                'waiver_amount': waiver_amount,
                'payment': payment.__dict__,
            }
        )

        if payment.paid_principal == payment.installment_principal:
            continue
        remaining_principal = payment.installment_principal - payment.paid_principal
        if not waiver_request:
            if remaining_amount > remaining_principal:
                paid_principal = remaining_principal
            else:
                paid_principal = remaining_amount
        else:
            waiver_approval = waiver_request.waiverapproval_set.last()
            if waiver_approval:
                waiver_payment = waiver_approval.waiverpaymentapproval_set.filter(
                    payment=payment
                ).last()
                if not waiver_payment:
                    break
                paid_principal = waiver_payment.approved_principal_waiver_amount
            else:
                waiver_payment = waiver_request.waiverpaymentrequest_set.filter(
                    payment=payment
                ).last()
                if not waiver_payment:
                    break
                paid_principal = waiver_payment.requested_principal_waiver_amount

            if paid_principal > waiver_amount:
                paid_principal = waiver_amount
            waiver_amount -= paid_principal

        payment.paid_amount += paid_principal
        payment.due_amount -= paid_principal
        payment.paid_principal += paid_principal

        account_payment.paid_amount += paid_principal
        account_payment.due_amount -= paid_principal
        account_payment.paid_principal += paid_principal

        logger.info(
            {
                'action': 'consume_payment_for_principal',
                'status': 'consumed',
                'waiver_request': waiver_request,
                'waiver_amount': waiver_amount,
                'payment': payment.__dict__,
            }
        )

        remaining_amount -= paid_principal
        total_paid_principal += paid_principal
        if remaining_amount == 0:
            break
    return remaining_amount, total_paid_principal


def consume_payment_for_interest(
    payments, remaining_amount, account_payment, waiver_request=None, waiver_amount=None
):
    total_paid_interest = 0
    for payment in payments:
        logger.info(
            {
                'action': 'consume_payment_for_interest',
                'status': 'pre-comsume',
                'waiver_request': waiver_request,
                'waiver_amount': waiver_amount,
                'payment': payment.__dict__,
            }
        )

        if payment.paid_interest == payment.installment_interest:
            continue
        remaining_interest = payment.installment_interest - payment.paid_interest
        if not waiver_request:
            if remaining_amount > remaining_interest:
                paid_interest = remaining_interest
            else:
                paid_interest = remaining_amount
        else:
            waiver_approval = waiver_request.waiverapproval_set.last()
            if waiver_approval:
                waiver_payment = waiver_approval.waiverpaymentapproval_set.filter(
                    payment=payment
                ).last()
                if not waiver_payment:
                    break
                paid_interest = waiver_payment.approved_interest_waiver_amount
            else:
                waiver_payment = waiver_request.waiverpaymentrequest_set.filter(
                    payment=payment
                ).last()
                if not waiver_payment:
                    break
                paid_interest = waiver_payment.requested_interest_waiver_amount

            if paid_interest > waiver_amount:
                paid_interest = waiver_amount
            waiver_amount -= paid_interest

        payment.paid_amount += paid_interest
        payment.due_amount -= paid_interest
        payment.paid_interest += paid_interest

        account_payment.paid_amount += paid_interest
        account_payment.due_amount -= paid_interest
        account_payment.paid_interest += paid_interest

        logger.info(
            {
                'action': 'consume_payment_for_interest',
                'status': 'consumed',
                'waiver_request': waiver_request,
                'waiver_amount': waiver_amount,
                'payment': payment.__dict__,
            }
        )

        remaining_amount -= paid_interest
        total_paid_interest += paid_interest
        if remaining_amount == 0:
            break
    return remaining_amount, total_paid_interest


def consume_payment_for_late_fee(
    payments, remaining_amount, account_payment, waiver_request=None, waiver_amount=None
):
    total_paid_late_fee = 0
    for payment in payments:
        logger.info(
            {
                'action': 'consume_payment_for_late_fee',
                'status': 'pre-comsume',
                'waiver_request': waiver_request,
                'waiver_amount': waiver_amount,
                'payment': payment.__dict__,
            }
        )

        if payment.paid_late_fee == payment.late_fee_amount:
            continue
        remaining_late_fee = payment.late_fee_amount - payment.paid_late_fee
        if not waiver_request:
            if remaining_amount > remaining_late_fee:
                paid_late_fee = remaining_late_fee
            else:
                paid_late_fee = remaining_amount
        else:
            waiver_approval = waiver_request.waiverapproval_set.last()
            if waiver_approval:
                waiver_payment = waiver_approval.waiverpaymentapproval_set.filter(
                    payment=payment
                ).last()
                if not waiver_payment:
                    break
                paid_late_fee = waiver_payment.approved_late_fee_waiver_amount
            else:
                waiver_payment = waiver_request.waiverpaymentrequest_set.filter(
                    payment=payment
                ).last()
                if not waiver_payment:
                    break
                paid_late_fee = waiver_payment.requested_late_fee_waiver_amount

            if paid_late_fee > waiver_amount:
                paid_late_fee = waiver_amount
            waiver_amount -= paid_late_fee

        payment.paid_amount += paid_late_fee
        payment.due_amount -= paid_late_fee
        payment.paid_late_fee += paid_late_fee

        account_payment.paid_amount += paid_late_fee
        account_payment.due_amount -= paid_late_fee
        account_payment.paid_late_fee += paid_late_fee

        logger.info(
            {
                'action': 'consume_payment_for_late_fee',
                'status': 'consumed',
                'waiver_request': waiver_request,
                'waiver_amount': waiver_amount,
                'payment': payment.__dict__,
            }
        )

        remaining_amount -= paid_late_fee
        total_paid_late_fee += paid_late_fee
        if remaining_amount == 0:
            break
    return remaining_amount, total_paid_late_fee


def store_calculated_payments(
    payment_list,
    paid_date,
    payment_receipt,
    payment_method,
    old_paid_amount_list,
    using_cashback,
    loan_statuses_list: list,
    event_type=None,
    note='',
    new_cashback_dict=dict(),
):
    from juloserver.followthemoney.services import create_manual_transaction_mapping

    payment_events = []
    grouped_payments_by_loans = {}
    for payment in payment_list:
        total_paid_amount = payment.paid_amount - old_paid_amount_list[payment.id]
        if total_paid_amount > 0:
            if not event_type:
                event_type = 'customer_wallet' if using_cashback else 'payment'
            payment_event = PaymentEvent.objects.create(
                payment=payment,
                event_payment=total_paid_amount,
                event_due_amount=payment.due_amount + total_paid_amount,
                event_date=paid_date,
                event_type=event_type,
                payment_receipt=payment_receipt,
                payment_method=payment_method,
                can_reverse=False,  # reverse (void) must be via account payment level
            )
            loan = payment.loan
            payment_events.append(payment_event)
            if event_type == "payment":
                old_payment_detail = old_paid_amount_list["%s_detail" % payment.id]
                paid_principal = payment.paid_principal - old_payment_detail["paid_principal"]
                paid_interest = payment.paid_interest - old_payment_detail["paid_interest"]
                paid_late_fee = payment.paid_late_fee - old_payment_detail["paid_late_fee"]
                create_manual_transaction_mapping(
                    payment.loan, payment_event, paid_principal, paid_interest, paid_late_fee
                )

                # this for GOSEL Repayment to update the limit
                if (
                        loan.status in {
                            LoanStatusCodes.CURRENT,
                            LoanStatusCodes.LOAN_1DPD,
                            LoanStatusCodes.LOAN_5DPD,
                            LoanStatusCodes.LOAN_30DPD,
                            LoanStatusCodes.LOAN_60DPD,
                            LoanStatusCodes.LOAN_90DPD,
                            LoanStatusCodes.LOAN_120DPD,
                            LoanStatusCodes.LOAN_150DPD,
                            LoanStatusCodes.LOAN_180DPD,
                            LoanStatusCodes.LOAN_4DPD,
                            LoanStatusCodes.RENEGOTIATED,
                            LoanStatusCodes.HALT
                        }
                        and loan.get_application.partner
                        and loan.get_application.partner.name == PartnerConstant.GOSEL
                ):
                    update_account_limit(paid_principal, loan.account_id)

                    update_or_create_release_tracking(
                        loan_id=payment.loan_id,
                        account_id=payment.loan.account_id,
                        limit_release_amount=payment.paid_principal,
                        payment_id=payment.id,
                        tracking_type=PartnerConstant.GOSEL)

            payment.paid_date = paid_date
            payment_update_fields = [
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_amount',
                'due_amount',
                'paid_date',
                'udate',
            ]

            if payment.due_amount == 0:
                grouped_payments_by_loans.setdefault(loan.id, []).append(payment.id)
                payment_history = {
                    'payment_old_status_code': payment.status,
                    'loan_old_status_code': payment.loan.status,
                }

                update_payment_paid_off_status(payment)
                payment_update_fields.append('payment_status')

                # check cashback earning
                if payment.paid_late_days <= 0 and loan.product.has_cashback_pmt:
                    _, is_cashback_experiment = get_cashback_claim_experiment(
                        paid_date, loan.account
                    )
                    j1_update_cashback_earned(
                        payment,
                        new_cashback_dict=new_cashback_dict,
                        is_cashback_experiment=is_cashback_experiment,
                    )
                    loan.update_cashback_earned_total(payment.cashback_earned)
                    loan.save()
                    payment_update_fields.append('cashback_earned')
                elif new_cashback_dict.get('is_eligible_new_cashback', False):
                    if payment.paid_late_days > 0:
                        # handle if do repayment passed dpd 0
                        # cashback counter need to reset if status refinancing/waiver/passed due
                        new_cashback_dict['status'] = NewCashbackConst.PASSED_STATUS
                        new_cashback_dict['cashback_counter'] = 0
                        record_data_for_cashback_new_scheme(
                            payment, None, 0, NewCashbackReason.PAID_AFTER_TERMS
                        )
                    elif not loan.product.has_cashback_pmt:
                        # handle if customer loan doesn't have cashback pct
                        new_cashback_dict['status'] = NewCashbackConst.ZERO_PERCENTAGE_STATUS

            payment.save(update_fields=payment_update_fields)

            # take care loan level
            unpaid_payments = list(Payment.objects.select_for_update().by_loan(loan).not_paid())
            if payment.account_payment:
                changed_by_id = None
            else:
                changed_by_id = payment_event.added_by.id if payment_event.added_by else None

            if len(unpaid_payments) == 0:  # This mean if loan is paid_off
                loan_statuses_list.append(
                    dict(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.PAID_OFF,
                        change_by_id=changed_by_id,
                        change_reason="Loan paid off",
                    )
                )
            elif payment.due_amount == 0:
                current_loan_status = loan.status
                loan.update_status(record_history=False)
                if current_loan_status != loan.status:
                    loan_statuses_list.append(
                        dict(
                            loan_id=loan.id,
                            new_status_code=loan.status,
                            change_by_id=changed_by_id,
                            change_reason="update loan status after payment paid off",
                        )
                    )

            # create payment history regarding to loan status as well
            if payment.due_amount == 0:
                payment.create_payment_history(payment_history)

            note = ',\nnote: %s' % note
            note_payment_method = ',\n'
            if payment_method:
                note_payment_method += (
                    'payment_method: %s,\n\
                            payment_receipt: %s'
                    % (payment_method.payment_method_name, payment_event.payment_receipt)
                )
            template_note = (
                '[Add Event %s]\n\
                        amount: %s,\n\
                        date: %s%s%s.'
                % (
                    event_type,
                    display_rupiah(payment_event.event_payment),
                    payment_event.event_date.strftime("%d-%m-%Y"),
                    note_payment_method,
                    note,
                )
            )

            PaymentNote.objects.create(note_text=template_note, payment=payment)

    if check_early_limit_repayment_fs():
        early_limit_release_data = []
        for loan_id, payment_ids in grouped_payments_by_loans.items():
            payment_ids.sort()
            early_limit_release_data.append({'loan_id': loan_id, 'payment_ids': payment_ids})
        if early_limit_release_data:
            countdown = get_delay_seconds_call_from_repayment()
            execute_after_transaction_safely(
                lambda: check_and_release_early_limit.apply_async(
                    kwargs={'loan_payments_list': early_limit_release_data}, countdown=countdown
                )
            )

    return payment_events


def get_and_update_latest_loan_status(loan_statuses):
    """
    Get the supposedly the lastest loan status for each loan status change attempted.

    Args:
        loan_statuses (list): The list Loan Status Dict for loan status change attempted.
    Loan Status Dict:
        loan_id (int): The ID of the loan.
        new_status_code (int): To specify the new new loan status,
                               have to be lower than the current.
        change_by_id (int, optional): To identify the user who did the change.
        change_reason (str, optional): To specify the reason for the status update.

    Returns:
        None

    """
    from juloserver.loan.tasks.loan_related import repayment_update_loan_status

    try:
        loan_status_dict = {}
        for loan_status in loan_statuses:
            loan_status_dict.setdefault(loan_status['loan_id'], loan_status)
            # If paid off status will be updated or
            # if last updated status is not paid off and
            # new status have lower dpd than the previous status
            last_status = loan_status_dict[loan_status['loan_id']].get('new_status_code')
            new_status = loan_status.get('new_status_code')
            if new_status == LoanStatusCodes.PAID_OFF or (
                last_status != LoanStatusCodes.PAID_OFF
                and LoanStatusCodes.LoanStatusesDPD.get(new_status)
                < LoanStatusCodes.LoanStatusesDPD.get(last_status)
            ):
                loan_status_dict[loan_status['loan_id']] = loan_status
        for change_loan_status_kwargs in loan_status_dict.values():
            execute_after_transaction_safely(
                lambda kwargs=change_loan_status_kwargs: repayment_update_loan_status.delay(
                    **kwargs
                )
            )
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'get_and_update_latest_loan_status',
                'param': loan_statuses,
                'message': str(e),
            }
        )


def construct_old_paid_amount_list(payments):
    old_paid_amount_list = {}
    for payment in payments:
        old_paid_amount_list[payment.id] = payment.paid_amount
        old_paid_amount_list["%s_detail" % payment.id] = {
            "paid_late_fee": payment.paid_late_fee,
            "paid_principal": payment.paid_principal,
            "paid_interest": payment.paid_interest,
        }
        old_paid_amount_list["%s_status" % payment.id] = payment.payment_status_id
    return old_paid_amount_list


def update_payment_paid_off_status(payment):
    if payment.paid_late_days <= 0:
        payment.change_status(PaymentStatusCodes.PAID_ON_TIME)
    elif payment.paid_late_days < get_grace_period_days(payment):
        payment.change_status(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD)
    else:
        payment.change_status(PaymentStatusCodes.PAID_LATE)


def update_account_payment_paid_off_status(account_payment):
    if account_payment.paid_late_days <= 0:
        account_payment.change_status(PaymentStatusCodes.PAID_ON_TIME)
    elif account_payment.paid_late_days < get_grace_period_days(account_payment, is_j1=True):
        account_payment.change_status(PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD)
    else:
        account_payment.change_status(PaymentStatusCodes.PAID_LATE)

    if 1 <= account_payment.paid_late_days <= 10:
        account_payment.is_paid_within_dpd_1to10 = True

    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account_id__isnull=False, account=account_payment.account,
        status=CovidRefinancingConst.STATUSES.activated
    ).last()
    if loan_refinancing_request:
        if loan_refinancing_request.product_type in ['R1', 'R2', 'R3']:
            pre_refinancing = AccountPaymentPreRefinancing.objects.filter(
                account_payment=account_payment
            ).exists()
            if pre_refinancing:
                account_payment.paid_during_refinancing = True
        elif loan_refinancing_request.product_type in ['R4', 'R5', 'R6']:
            waiver_account_payment_request = WaiverAccountPaymentRequest.objects.filter(
                account_payment=account_payment
            ).exists()
            if waiver_account_payment_request:
                account_payment.paid_during_refinancing = True


def process_repayment_trx(
    payback_transaction_obj, note=None, using_cashback=False, from_refinancing=False
):
    from juloserver.account_payment.tasks.repayment_tasks import (
        update_latest_payment_method_task,
        update_collection_risk_bucket_paid_first_installment_task,
    )
    from juloserver.account.tasks.account_task import update_cashback_counter_account_task
    from juloserver.account_payment.services.earning_cashback import (
        get_paramters_cashback_new_scheme,
    )
    from juloserver.account_payment.tasks.repayment_tasks import primary_ptp_update_for_j1_async
    from juloserver.account_payment.tasks.cashback_tasks import create_eligible_cashback
    from juloserver.payback.tasks.payback_tasks import send_email_payment_success_task

    if payback_transaction_obj.is_processed:
        raise JuloException("can't process payback transaction that has been processed")
    customer = payback_transaction_obj.customer
    account = customer.account
    unpaid_account_payment_ids = account.get_unpaid_account_payment_ids()
    remaining_amount = payback_transaction_obj.amount
    payment_events = []
    paid_off_account_payment_ids = []
    updated_account_payment_ids = []  # with paid off and partially account_payment_id
    payment_event_ids = []
    account_payment_payments = {}
    local_trx_date = timezone.localtime(payback_transaction_obj.transaction_date).date()
    max_counter = NewCashbackConst.MAX_CASHBACK_COUNTER
    due_date, percentage_mapping = get_paramters_cashback_new_scheme()
    new_cashback_dict = dict(
        # status here for identifier customer paid with
        # refinancing/waiver/normal payment
        # so can easier to detemine cashback counter need to reset or not
        status=NewCashbackConst.NORMAL_STATUS,
        cashback_counter=account.cashback_counter,
        is_eligible_new_cashback=account.is_eligible_for_cashback_new_scheme,
        account_status=account.status_id,
        due_date=due_date,
        percentage_mapping=percentage_mapping,
    )
    with transaction.atomic():
        towards_principal = 0
        towards_interest = 0
        towards_latefee = 0
        transaction_type = 'customer_wallet' if using_cashback else 'payment'
        loan_statuses_list = []
        today = timezone.localtime(timezone.now()).date()
        lrr = LoanRefinancingRequest.objects.filter(
            Q(account=account)
            & (
                Q(
                    status__in=[
                        CovidRefinancingConst.STATUSES.offer_selected,
                        CovidRefinancingConst.STATUSES.approved,
                    ]
                )
                | Q(status=CovidRefinancingConst.STATUSES.activated, offer_activated_ts__date=today)
            )
        ).exists()
        for account_payment_id in unpaid_account_payment_ids:
            if remaining_amount == 0:
                break
            account_payment = AccountPayment.objects.select_for_update().get(pk=account_payment_id)
            if from_refinancing or lrr:
                pass
            else:
                automate_late_fee_void(
                    account_payment, payback_transaction_obj.transaction_date, remaining_amount
                )
            account_payment.refresh_from_db()
            payments = list(
                Payment.objects.select_for_update()
                .not_paid_active_julo_one()
                .filter(account_payment=account_payment)
                .order_by('loan_id')
            )
            old_paid_amount_list = construct_old_paid_amount_list(payments)
            remaining_amount, total_paid_principal = consume_payment_for_principal(
                payments, remaining_amount, account_payment
            )
            total_paid_interest = 0
            if remaining_amount > 0:
                remaining_amount, total_paid_interest = consume_payment_for_interest(
                    payments, remaining_amount, account_payment
                )
            total_paid_late_fee = 0
            if remaining_amount > 0:
                remaining_amount, total_paid_late_fee = consume_payment_for_late_fee(
                    payments, remaining_amount, account_payment
                )
            payment_events += store_calculated_payments(
                payments,
                local_trx_date,
                payback_transaction_obj.transaction_id,
                payback_transaction_obj.payment_method,
                old_paid_amount_list,
                using_cashback,
                loan_statuses_list,
                note=note,
                new_cashback_dict=new_cashback_dict,
            )
            ptp_date = account_payment.ptp_date
            account_payment.paid_date = local_trx_date
            account_payment_payments[account_payment_id] = {
                'payments': [payment.id for payment in payments],
            }

            if account_payment.due_amount == 0:
                history_data = {'status_old': account_payment.status, 'change_reason': 'paid_off'}
                update_account_payment_paid_off_status(account_payment)
                # delete account_payment bucket 3 data on collection table
                # logic paid off
                delete_temp_bucket_base_on_account_payment_ids_and_bucket([account_payment.id])
                account_payment.create_account_payment_status_history(history_data)
                if new_cashback_dict['is_eligible_new_cashback']:
                    if new_cashback_dict['status'] == NewCashbackConst.NORMAL_STATUS:
                        if new_cashback_dict['cashback_counter'] < max_counter:
                            new_cashback_dict['cashback_counter'] += 1
                        else:
                            new_cashback_dict['cashback_counter'] = max_counter
                    else:
                        last_counter_history = (
                            CashbackCounterHistory.objects.filter(
                                account_payment_id=account_payment.id
                            )
                            .values('counter')
                            .last()
                        )
                        new_cashback_dict['cashback_counter'] = (
                            last_counter_history.get('counter') if last_counter_history else 0
                        )

            account_payment.save(
                update_fields=[
                    'due_amount',
                    'paid_amount',
                    'paid_principal',
                    'paid_interest',
                    'paid_late_fee',
                    'paid_date',
                    'status',
                    'udate',
                    'paid_during_refinancing',
                    'is_paid_within_dpd_1to10'
                ]
            )

            note = ',\nnote: %s' % note
            note_payment_method = ',\n'
            if payback_transaction_obj.payment_method:
                note_payment_method += (
                    'payment_method: %s,\n\
                                        payment_receipt: %s'
                    % (
                        payback_transaction_obj.payment_method.payment_method_name,
                        payback_transaction_obj.transaction_id,
                    )
                )
            template_note = (
                '[Add Event %s]\n\
                                    amount: %s,\n\
                                    date: %s%s%s.'
                % (
                    transaction_type,
                    display_rupiah(
                        total_paid_principal + total_paid_interest + total_paid_late_fee
                    ),
                    payback_transaction_obj.transaction_date.strftime("%d-%m-%Y"),
                    note_payment_method,
                    note,
                )
            )

            AccountPaymentNote.objects.create(
                note_text=template_note, account_payment=account_payment
            )

            updated_account_payment_ids.append(account_payment_id)

            if account_payment.due_amount == 0:
                update_ptp_for_paid_off_account_payment(account_payment)
                paid_off_account_payment_ids.append(account_payment.id)
                # this will update ptp_status
                today = timezone.localtime(timezone.now()).date()
                ptp = PTP.objects.filter(
                    ptp_date__gte=today, account_payment=account_payment
                ).last()
                if ptp:
                    ptp.update_safely(ptp_status='Paid')
            else:
                # this will handle partial account payment updates
                ptp_update_for_j1(account_payment.id, account_payment.ptp_date)

            towards_principal += total_paid_principal
            towards_interest += total_paid_interest
            towards_latefee += total_paid_late_fee

            total_paid_amount = 0
            for payment_event in payment_events:
                total_paid_amount += payment_event.event_payment

            execute_after_transaction_safely(
                lambda account_payment_param=account_payment.id, ptp_date_param=ptp_date, total_paid_amount_param=total_paid_amount: primary_ptp_update_for_j1_async.delay(  # noqa
                    account_payment_id=account_payment_param,
                    ptp_date=ptp_date_param,
                    total_paid_amount=total_paid_amount_param,
                )
            )

        if remaining_amount > 0:
            # handle if paid off account do repayment
            if len(payment_events) > 0:
                cashback_payment_event = payment_events[-1]
            else:
                cashback_payment_event = None

            if not account.get_unpaid_account_payment_ids():
                account_payment = account.accountpayment_set.last()

            notify_account_payment_over_paid(account_payment, remaining_amount)
            customer.change_wallet_balance(
                change_accruing=remaining_amount,
                change_available=remaining_amount,
                reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                account_payment=account_payment,
                payment_event=cashback_payment_event,
            )
        payback_transaction_obj.update_safely(is_processed=True)
        account_transaction_data = dict(
            account=account,
            payback_transaction=payback_transaction_obj,
            transaction_date=payback_transaction_obj.transaction_date,
            transaction_amount=payback_transaction_obj.amount,
            transaction_type=transaction_type,
            towards_principal=towards_principal,
            towards_interest=towards_interest,
            towards_latefee=towards_latefee,
        )
        if from_refinancing:
            account_transaction_data.update(
                account_transaction_note=AccountTransactionNotes.ReinputRefinancing
            )

        account_trx = AccountTransaction.objects.create(**account_transaction_data)
        for payment_event in payment_events:
            payment_event.update_safely(account_transaction=account_trx)
            # collect all payment event ids
            payment_event_ids.append(payment_event.id)

        if payment_events:
            insert_data_into_commission_table_for_j1(payment_events)

        get_and_update_latest_loan_status(loan_statuses_list)
        update_is_proven_account_payment_level(account)

    if account_payment:
        execute_after_transaction_safely(
            lambda account_payment_param=account_payment.id, is_reversal_param=False, paid_date_param=local_trx_date, counter_param=new_cashback_dict[  # noqa
                'cashback_counter'
            ]: update_cashback_counter_account_task(
                account_payment_id=account_payment_param,
                is_reversal=is_reversal_param,
                paid_date=paid_date_param,
                cashback_counter=counter_param,
            )
        )

    for paid_off_account_payment_id in paid_off_account_payment_ids:
        set_google_calendar_when_paid.delay(paid_off_account_payment_id=paid_off_account_payment_id)
        process_unassignment_when_paid_for_j1.delay(paid_off_account_payment_id)
        execute_after_transaction_safely(
            lambda paid_off_id=paid_off_account_payment_id: delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(  # noqa
                paid_off_id
            )
        )
        execute_after_transaction_safely(
            lambda
                paid_off_id=paid_off_account_payment_id: delete_paid_payment_from_dialer.delay(
                # noqa
                paid_off_id
            )
        )
        process_unassignment_field_assignment.delay(paid_off_account_payment_id)
        account_payment_form_cootek = CootekRobocall.objects.filter(
            account_payment_id=paid_off_account_payment_id
        ).last()

        if account_payment_form_cootek:
            cancel_phone_call_for_payment_paid_off.delay(account_payment_form_cootek.id)

    # use chain for cashback eligibility and email notification
    # to avoid race condition between cashback processing and email sending
    execute_after_transaction_safely(
        lambda: chain(
            create_eligible_cashback.s(account_trx.id, paid_off_account_payment_ids),
            send_email_payment_success_task.s(payback_transaction_obj.id).set(immutable=True),
        ).delay()
    )

    # Upload to Credgenics Data
    execute_after_transaction_safely(
        lambda updated_account_payment_ids=updated_account_payment_ids, customer_id=customer.id, amount=payback_transaction_obj.amount, payback_transaction_id=payback_transaction_obj.id: update_credgenics_loan_task.delay(  # noqa
            updated_account_payment_ids, customer_id, amount, payback_transaction_id
        )
    )

    # Upload Omnichannel Customer Data
    execute_after_transaction_safely(
        lambda customer_id=customer.id, account_payment_ids=updated_account_payment_ids, payback_transaction_id=payback_transaction_obj.id: process_repayment_event_for_omnichannel.delay(  # noqa
            customer_id,
            account_payment_ids,
            payback_transaction_id,
        )
    )
    # Update data to Field Collection Service
    execute_after_transaction_safely(
        lambda: sent_webhook_to_field_collection_service_by_category.delay(
            category='payment_event',
            account_xid=account.id,
            payback_transaction_id=payback_transaction_obj.id,
        )
    )

    # Update data from manual assignment if there's a paid off payment found
    if paid_off_account_payment_ids:
        execute_after_transaction_safely(
            lambda: handle_manual_agent_assignment_payment.delay(
                account_id=account.id,
            )
        )

    send_early_repayment_experience_pn.delay(account_payment_payments, account.id)

    checkout_request = CheckoutRequest.objects.filter(
        account_id=account,
        status=CheckoutRequestCons.ACTIVE,
        expired_date__gt=timezone.localtime(timezone.now()),
    ).last()
    if checkout_request:
        checkout_payment_event_ids = []
        # filter payment event data if account_payment on checkout_request.account_payment_ids list
        payment_events_on_checkout_request = PaymentEvent.objects.filter(
            pk__in=payment_event_ids
        ).filter(
            Q(payment__cdate__lt=checkout_request.cdate)
            & Q(payment__account_payment_id__in=checkout_request.account_payment_ids)
        )

        if checkout_request.type == CheckoutPaymentType.REFINANCING:
            payment_events_on_checkout_request = PaymentEvent.objects.filter(
                pk__in=payment_event_ids
            )

        total_payments = 0
        for payment_event in payment_events_on_checkout_request:
            total_payments += payment_event.event_payment
            checkout_payment_event_ids.append(payment_event.id)
        cashback_used = total_payments
        if not using_cashback:
            cashback_used = 0
        update_checkout_request_by_process_repayment(
            checkout_request,
            checkout_payment_event_ids,
            total_payments,
            cashback_used,
            payback_transaction_obj.amount,
        )
    update_latest_payment_method_task.delay(payback_transaction_obj.id)

    # collection risk bucket paid first installment update
    update_collection_risk_bucket_paid_first_installment_task.delay(account.id, account_payment.id)

    # autodebet payment offer
    from juloserver.autodebet.tasks import update_autodebet_payment_offer

    execute_after_transaction_safely(lambda: update_autodebet_payment_offer.delay(account.id))
    return account_trx


def update_collection_risk_bucket_paid_first_installment(
    account_id: int, account_payment_id: int
) -> None:
    account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
    collection_risk_bucket = CollectionRiskVerificationCallList.objects.filter(
        account_id=account_id, is_paid_first_installment=False
    ).last()
    if collection_risk_bucket and account_payment.due_amount == 0:
        try:
            is_first_payment_paid = AccountTransaction.objects.filter(
                account_id=account_id
            ).exists()
            collection_risk_bucket.update_safely(is_paid_first_installment=is_first_payment_paid)
        except Exception as err:
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'process_repayment_trx',
                    'state': 'collection risk bucket paid first installment update',
                    'error': str(err),
                }
            )


def reversal_update_collection_risk_bucket_paid_first_installment(account_id: int) -> None:
    # check if there is payment without reversal

    collection_risk_bucket = CollectionRiskVerificationCallList.objects.filter(
        account_id=account_id, is_paid_first_installment=True
    ).last()
    is_valid_payment = AccountTransaction.objects.filter(
        account_id=account_id, transaction_type='payment', reversal_transaction_id=None
    ).exists()

    if collection_risk_bucket and (
        not is_valid_payment or collection_risk_bucket.account_payment.due_amount != 0
    ):
        # reverse is_paid_first_installment status
        collection_risk_bucket.update_safely(is_paid_first_installment=False)


def notify_account_payment_over_paid(account_payment, amount):
    if settings.ENVIRONMENT != 'prod':
        return
    if MAX_PAYMENT_OVER_PAID > amount:
        return
    data = {
        'action': 'account_payment_over_paid',
        'amount': display_rupiah(amount),
        'customer_id': account_payment.account.customer_id,
        'account_payment_id': account_payment.id,
    }
    logger.info(data)
    slack_client = get_slack_client()
    slack_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_DEV_FINANCE,
        text="```%s```" % json.dumps(data, indent=2),
    )


def process_rentee_deposit_trx(payback_transaction_obj):
    if payback_transaction_obj.is_processed:
        raise JuloException("can't process payback transaction that has been processed")
    customer = payback_transaction_obj.customer
    account = customer.account
    remaining_amount = payback_transaction_obj.amount
    payment_deposit_list = rentee_service.get_payment_deposit_pending(account)
    if not payment_deposit_list:
        return None

    for payment_deposit in payment_deposit_list:
        remaining_amount = rentee_service.process_payment_deposit(payment_deposit, remaining_amount)
        if remaining_amount == 0:
            break

    if remaining_amount > 0:
        customer.change_wallet_balance(
            change_accruing=remaining_amount,
            change_available=remaining_amount,
            reason='cashback_over_paid on rentee deposit',
        )
    payback_transaction_obj.update_safely(is_processed=True)

    return payback_transaction_obj


def update_checkout_request_by_process_repayment(
    checkout_request, payment_event_ids, total_payments, cashback_used, actual_transaction_amount=0
):
    from juloserver.account_payment.tasks.scheduled_tasks import send_checkout_experience_pn
    from juloserver.integapiv1.services import get_bni_payment_method

    with transaction.atomic():
        checkout_payment_event_ids = []
        checkout_request = CheckoutRequest.objects.select_for_update().get(pk=checkout_request.id)
        remaining_total_payment = checkout_request.total_payments
        if checkout_request.payment_event_ids:
            checkout_payment_event_ids = checkout_request.payment_event_ids
        checkout_payment_event_ids += payment_event_ids
        if total_payments >= checkout_request.total_payments:
            checkout_request.update_safely(
                status=CheckoutRequestCons.REDEEMED,
                total_payments=checkout_request.total_payments - total_payments,
                payment_event_ids=checkout_payment_event_ids,
                cashback_used=checkout_request.cashback_used + cashback_used,
            )
            update_checkout_request_status_to_finished.apply_async(
                (checkout_request.id,), countdown=3600
            )
        else:
            checkout_request.update_safely(
                total_payments=checkout_request.total_payments - total_payments,
                payment_event_ids=checkout_payment_event_ids,
                cashback_used=checkout_request.cashback_used + cashback_used,
            )
        _, is_bni_payment_method_exist = get_bni_payment_method(checkout_request.account_id)
        if is_bni_payment_method_exist:
            update_va_bni_transaction.delay(
                checkout_request.account_id.id,
                'account_payment.services.payment_flow.update_checkout_'
                'request_by_process_repayment',
                checkout_request.total_payments,
            )
        send_checkout_experience_pn.delay(
            [checkout_request.account_id.customer_id],
            CheckoutRequestCons.PAID_CHECKOUT,
            actual_paid_amount=actual_transaction_amount,
            checkout_request_id=checkout_request.id,
            total_payment_before_updated=remaining_total_payment,
        )


def check_early_limit_repayment_fs():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE_REPAYMENT_SIDE, is_active=True
    ).exists()


def automate_late_fee_void(
    account_payment: AccountPayment, paid_datetime: datetime, paid_amount: int
) -> None:
    from juloserver.account_payment.services.reversal import process_late_fee_reversal

    try:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=AccountPaymentFeatureNameConst.AUTOMATE_LATE_FEE_VOID, is_active=True
        ).last()
        if not feature_setting:
            return
        days_threshold = feature_setting.parameters.get('days_threshold', 3)
        today_date = timezone.localtime(timezone.now()).date()
        date_late_fee_void = paid_datetime.date() + timedelta(days=days_threshold)

        if paid_datetime.date() >= today_date >= date_late_fee_void:
            return

        if not account_payment.late_fee_amount or account_payment.late_fee_amount <= 0:
            return

        if paid_amount < (account_payment.due_amount - account_payment.late_fee_amount):
            return
        account_transactions = AccountTransaction.objects.filter(
            account=account_payment.account,
            transaction_date__date__gt=paid_datetime.date(),
            transaction_date__date__lte=date_late_fee_void,
            transaction_type='late_fee',
            can_reverse=True,
        )
        for account_transaction in account_transactions:
            process_late_fee_reversal(account_transaction, 'automate_late_fee_void')
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'automate_late_fee_void',
                'message': str(e),
                'account_payment_id': account_payment.id,
                'paid_datetime': paid_datetime,
            }
        )

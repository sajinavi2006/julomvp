import logging
from django.db import transaction
from django.db.models import Q

from juloserver.account.models import AutodebetAccount, ExperimentGroup
from juloserver.account_payment.models import (
    AccountPayment,
    CashbackClaim,
    CashbackClaimPayment,
)
from juloserver.julo.models import (
    CollectionPrimaryPTP,
    ExperimentSetting,
    Payment,
    PTP,
)

from juloserver.julo.constants import NewCashbackReason
from juloserver.account_payment.constants import CashbackClaimConst
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConst
from juloserver.julo.statuses import PaymentStatusCodes

from datetime import date, datetime

logger = logging.getLogger(__name__)


def ptp_update_for_j1(account_payment_id, ptp_date):
    """
    update ptp table in reference to AccountPayment table
    """
    if ptp_date is not None:
        paid_status_codes = [PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                             PaymentStatusCodes.PAID_LATE,
                             PaymentStatusCodes.PAID_ON_TIME]
        account_payment = AccountPayment.objects.get(pk=account_payment_id)

        ptp_status = None
        agent = None

        if account_payment.paid_date is not None and account_payment.paid_amount != 0:
            if account_payment.status_id in paid_status_codes:
                if account_payment.paid_date > ptp_date:
                    ptp_status = "Paid after ptp date"
                elif account_payment.paid_date <= ptp_date and account_payment.due_amount != 0:
                    ptp_status = "Partial"
                else:
                    ptp_status = "Paid"
            elif account_payment.due_amount != 0:
                ptp_status = "Partial"
        else:
            ptp_status = "Not Paid"

        if ptp_status is not None:
            ptp_object = PTP.objects.filter(
                account_payment=account_payment, ptp_date=ptp_date, ptp_status__isnull=True).last()
            if not ptp_object:
                if agent is None:
                    ptp_object = PTP.objects.filter(
                        account_payment=account_payment,
                        ptp_date=ptp_date,
                        agent_assigned_id__isnull=False).last()
                    if ptp_object:
                        agent = ptp_object.agent_assigned
                ptp_parent = PTP.objects.filter(
                    account_payment=account_payment,
                    ptp_date=ptp_date,
                    ptp_amount=account_payment.ptp_amount).first()
                PTP.objects.create(
                    account_payment=account_payment,
                    account=account_payment.account,
                    agent_assigned=agent,
                    ptp_date=ptp_date,
                    ptp_status=ptp_status,
                    ptp_amount=account_payment.ptp_amount,
                    ptp_parent=ptp_parent,
                )
            else:
                if agent is None:
                    agent = ptp_object.agent_assigned
                ptp_object.update_safely(
                    agent_assigned=agent,
                    ptp_status=ptp_status,
                    ptp_amount=account_payment.ptp_amount
                )


def update_ptp_for_paid_off_account_payment(account_payment):
    if account_payment.due_date is None and account_payment.paid_date is None:
        logger.warn({
            'due_date': account_payment.due_date,
            'paid_date': account_payment.paid_date,
            'account_payment_id': account_payment.id
        })
        return

    ptp_date = account_payment.ptp_date

    with transaction.atomic():
        account_payment.update_safely(ptp_date=None)
        ptp_update_for_j1(account_payment.id, ptp_date)


def primary_ptp_update_for_j1(
    account_payment_id: int, ptp_date: date = None, total_paid_amount: int = 0
) -> None:
    """
    update primary ptp table in reference to AccountPayment table
    """
    account_payment = AccountPayment.objects.filter(pk=account_payment_id).last()
    if not account_payment or not ptp_date:
        return

    current_primary_ptp = CollectionPrimaryPTP.objects.filter(
        account_payment=account_payment, ptp_date=ptp_date
    ).last()
    if not current_primary_ptp:
        return

    total_paid_amount += current_primary_ptp.paid_amount
    ptp_status = "Not Paid"
    if total_paid_amount > 0:
        if account_payment.paid_date > ptp_date:
            ptp_status = "Paid after ptp date"
        elif total_paid_amount < current_primary_ptp.ptp_amount:
            ptp_status = "Partial"
        else:
            ptp_status = "Paid"

    current_primary_ptp.update_safely(
        ptp_status=ptp_status,
        paid_amount=total_paid_amount,
        latest_paid_date=account_payment.paid_date,
    )


def get_cashback_claim_experiment(date=None, account=None):
    """
    Get cashback claim experiment setting with account eligibilty for the experiment.

    Args:
        date (date): current date or date when the transaction is executed.
        account (Account): check if the account is categorized as 'group' or 'experiment'.
    Returns:
        cashback_experiment (ExperimentSetting): ExperimentSetting of the cashback experiment.
        is_cashback_experiment (bool): Whether the account is in the cashback experiment.
    """
    if not date:
        date = datetime.now().date()

    cashback_experiment = (
        ExperimentSetting.objects.filter(
            is_active=True, code=MinisquadExperimentConst.CASHBACK_CLAIM_EXPERIMENT
        )
        .filter(
            (Q(start_date__date__lte=date) & Q(end_date__date__gte=date)) | Q(is_permanent=True)
        )
        .last()
    )
    if cashback_experiment and account:
        autodebet_account_exists = AutodebetAccount.objects.filter(
            account=account,
            is_use_autodebet=True,
            is_deleted_autodebet=False,
            is_suspended=False,
        ).exists()
        if autodebet_account_exists:
            return cashback_experiment, False

        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=cashback_experiment,
            account=account,
        ).last()
        if not experiment_group:
            account_id_tail = cashback_experiment.criteria.get('account_id_tail')
            if account_id_tail:
                experiment_group = (
                    'experiment'
                    if account.id % 10 in account_id_tail.get("experiment")
                    else 'control'
                )
                experiment_group = ExperimentGroup.objects.create(
                    account_id=account.id,
                    experiment_setting=cashback_experiment,
                    group=experiment_group,
                )

        return cashback_experiment, True if experiment_group.group == 'experiment' else False

    return cashback_experiment, False


def void_cashback_claim_payment_experiment(
    payment, is_eligible_new_cashback=False, counter=0, new_cashback_percentage=0
):
    from juloserver.julo.services import record_data_for_cashback_new_scheme
    with transaction.atomic(using='collection_db'):
        cashback_claim_payment = (
            CashbackClaimPayment.objects.select_for_update()
            .filter(
                payment_id=payment.id,
            )
            .exclude(
                status__in=[
                    CashbackClaimConst.STATUS_VOID,
                    CashbackClaimConst.STATUS_VOID_CLAIM,
                    CashbackClaimConst.STATUS_EXPIRED,
                ]
            )
            .last()
        )
        if not cashback_claim_payment:
            return

        if cashback_claim_payment.status == CashbackClaimConst.STATUS_CLAIMED:
            void_status = CashbackClaimConst.STATUS_VOID_CLAIM
        else:
            void_status = CashbackClaimConst.STATUS_VOID
            if is_eligible_new_cashback:
                reason = NewCashbackReason.PAYMENT_REVERSE
                record_data_for_cashback_new_scheme(
                    payment, None, counter, reason, new_cashback_percentage
                )

        cashback_claim_payment.update_safely(status=void_status)
        cashback_claim = cashback_claim_payment.cashback_claim
        if cashback_claim:
            cashback_claim.update_safely(
                total_cashback_amount=cashback_claim.total_cashback_amount
                - cashback_claim_payment.cashback_amount
            )


def void_cashback_claim_experiment(unpaid_account_payment_ids):
    with transaction.atomic(using='collection_db'):
        cashback_claim = CashbackClaim.objects.filter(
            status__in=[
                CashbackClaimConst.STATUS_ELIGIBLE,
                CashbackClaimConst.STATUS_CLAIMED,
            ]
        ).last()
        if not cashback_claim:
            return

        payment_ids = list(
            Payment.objects.filter(
                account_payment_id__in=unpaid_account_payment_ids,
            ).values_list('id', flat=True)
        )

        cashback_claim_payments = CashbackClaimPayment.objects.filter(
            cashback_claim=cashback_claim,
            status__in=[
                CashbackClaimConst.STATUS_PENDING,
                CashbackClaimConst.STATUS_ELIGIBLE,
                CashbackClaimConst.STATUS_CLAIMED,
            ]
        )
        tobe_pending_cashback_claim_payments = cashback_claim_payments.filter(
            payment_id__in=payment_ids
        )

        pending_total_amount = 0
        for tobe_pending_cashback_claim_payment in tobe_pending_cashback_claim_payments:
            tobe_pending_cashback_claim_payment.update_safely(
                status=CashbackClaimConst.STATUS_PENDING,
                cashback_claim_id=None,
            )
            pending_total_amount += tobe_pending_cashback_claim_payment.cashback_amount

        updated_cashback_fields = {}
        if pending_total_amount:
            updated_cashback_fields['total_cashback_amount'] = (
                cashback_claim.total_cashback_amount - pending_total_amount
            )

        if not cashback_claim_payments.exists():
            if cashback_claim.status == CashbackClaimConst.STATUS_CLAIMED:
                updated_cashback_fields['status'] = CashbackClaimConst.STATUS_VOID_CLAIM
            else:
                updated_cashback_fields['status'] = CashbackClaimConst.STATUS_VOID

        if updated_cashback_fields:
            cashback_claim.update_safely(**updated_cashback_fields)

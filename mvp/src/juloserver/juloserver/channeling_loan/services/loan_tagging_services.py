import logging
from django.db import transaction, connection
from django.db.models import F
from django_bulk_update.helper import bulk_update
from django.utils import timezone

from juloserver.julocore.python2.utils import py2round
from juloserver.channeling_loan.constants import (
    ChannelingLenderLoanLedgerConst,
    LoanTaggingConst,
)
from juloserver.channeling_loan.models import (
    LenderLoanLedger,
    LenderLoanLedgerHistory,
    LenderOspAccount,
    LenderOspBalanceHistory,
    LoanLenderTaggingDpdTemp,
)
from juloserver.channeling_loan.utils import sum_value_per_key_to_dict
from juloserver.julo.models import (
    FeatureSetting,
)
from juloserver.julo.constants import FeatureNameConst
from django.db.models import Sum
from juloserver.ana_api.models import LoanLenderTaggingDpd
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)


def execute_replenishment_matchmaking():
    # need to requery in case previous account is not fulfilled
    logger.info({
        "action": "juloserver.channeling_loan.tasks.execute_replenishment_matchmaking",
        "info": "started",
    })
    try:
        lender_osp_accounts = LenderOspAccount.objects.all().order_by('priority')
        for lender_osp_account in lender_osp_accounts:
            need_replenishment_lender = (
                lender_osp_account.balance_amount - lender_osp_account.fund_by_lender
            )
            withdraw_percentage = lender_osp_account.lender_withdrawal_percentage
            need_to_fund_julo = (
                lender_osp_account.balance_amount * (withdraw_percentage - 100) / 100
            )
            need_replenishment_julo = need_to_fund_julo - lender_osp_account.fund_by_julo
            execute_find_replenishment_loan_payment_by_user(
                lender_osp_account_id=lender_osp_account.id,
                need_replenishment_lender=need_replenishment_lender,
                need_replenishment_julo=need_replenishment_julo,
            )
    except Exception as e:
        logger.error({
            "action": "juloserver.channeling_loan.tasks.execute_replenishment_matchmaking",
            "error": str(e),
        })


def execute_replenishment_loan_payment_by_user_process():
    payments = LenderLoanLedger.objects.filter(
        tag_type__in=[
            ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
        ]
    ).annotate(
        loan_amount=F('loan__loan_amount'),
        paid_principal=Sum('loan__payment__paid_principal'),
    )

    if not payments:
        return

    # CHECK IS USER PAID MORE THAN PREVIOUS RUN,
    # IF YES, CALCULATE ADDITIONAL PAID AMOUNT (SEPARATE FUND BY JULO & LENDER) TO REPLENISH,
    # AND UPDATE OSP OF LEDGER
    total_replenishment_amount_fund_by_lender_per_lender_osp_account = {}
    total_replenishment_amount_fund_by_julo_per_lender_osp_account = {}
    lender_loan_ledgers = []
    lender_loan_ledger_histories = []
    update_date = timezone.localtime(timezone.now())
    for payment in payments.iterator():
        # so lenderloanledger can duplicate when we join Payment with LenderLoanLedger
        # we need to make sure we only process lender loan ledger once
        lender_loan_ledger = payment

        old_osp_amount = lender_loan_ledger.osp_amount
        new_osp_amount = payment.loan_amount - payment.paid_principal
        # skip if OSP does not have any changes, means no new payment
        if new_osp_amount == old_osp_amount:
            continue

        # only need to replenishment the difference since the previous OSP
        # Eg: 1st: OSP=100, 2nd: OSP=60, => need to replenish 40
        replenishment_amount = old_osp_amount - new_osp_amount

        lender_osp_account_id = lender_loan_ledger.lender_osp_account_id
        if not lender_loan_ledger.is_fund_by_julo:
            sum_value_per_key_to_dict(
                dictionary=total_replenishment_amount_fund_by_lender_per_lender_osp_account,
                key=lender_osp_account_id,
                value_added_to=replenishment_amount,
            )
        else:
            sum_value_per_key_to_dict(
                dictionary=total_replenishment_amount_fund_by_julo_per_lender_osp_account,
                key=lender_osp_account_id,
                value_added_to=replenishment_amount,
            )

        lender_loan_ledger.osp_amount = new_osp_amount
        lender_loan_ledger.udate = update_date
        lender_loan_ledger_histories.append(
            LenderLoanLedgerHistory(
                lender_loan_ledger_id=lender_loan_ledger.id,
                field_name='osp_amount',
                old_value=old_osp_amount,
                new_value=new_osp_amount,
            )
        )

        if new_osp_amount == 0:
            # instead using tag, using osp amount now,
            # if all amount is paid, will be marked as paid off.
            lender_loan_ledger_histories.append(
                LenderLoanLedgerHistory(
                    lender_loan_ledger_id=lender_loan_ledger.id,
                    field_name='tag_type',
                    old_value=lender_loan_ledger.tag_type,
                    new_value=ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF,
                )
            )
            lender_loan_ledger.tag_type = ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF

        lender_loan_ledgers.append(lender_loan_ledger)

    with transaction.atomic():
        # bulk update dont update auto_now, so udate need to be updated manually
        bulk_update(
            lender_loan_ledgers,
            update_fields=['osp_amount', 'tag_type', 'udate'],
            batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE
        )
        LenderLoanLedgerHistory.objects.bulk_create(
            lender_loan_ledger_histories,
            batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE,
        )

        if total_replenishment_amount_fund_by_lender_per_lender_osp_account:
            for lender_osp_account_id, total_replenishment_amount in (
                total_replenishment_amount_fund_by_lender_per_lender_osp_account.items()
            ):
                lender_osp_account = LenderOspAccount.objects.get_or_none(
                    pk=lender_osp_account_id
                )
                # need to update the tagged loan dirst before releasing
                # since new matchmaking process are using lender_osp_account total
                if lender_osp_account:
                    update_replenishment_amount_and_lender_balance(
                        lender_osp_account=lender_osp_account,
                        total_replenishment_tagged_loan=total_replenishment_amount * -1,
                        reason="repayment_by_user_tag",
                        is_fund_by_julo=False,
                    )

        if total_replenishment_amount_fund_by_julo_per_lender_osp_account:
            for lender_osp_account_id, total_replenishment_amount in (
                total_replenishment_amount_fund_by_julo_per_lender_osp_account.items()
            ):
                lender_osp_account = LenderOspAccount.objects.get_or_none(
                    pk=lender_osp_account_id
                )
                # need to update the tagged loan dirst before releasing
                # since new matchmaking process are using lender_osp_account total
                if lender_osp_account:
                    update_replenishment_amount_and_lender_balance(
                        lender_osp_account=lender_osp_account,
                        total_replenishment_tagged_loan=total_replenishment_amount * -1,
                        reason="repayment_by_user_tag",
                        is_fund_by_julo=True,
                    )

    logger.info(
        {
            "action": "juloserver.channeling_loan.tasks."
            + "execute_replenishment_loan_payment_by_user_process",
            "info": "success",
            "data": {
                "lender_osp": total_replenishment_amount_fund_by_lender_per_lender_osp_account,
                "julo_osp": total_replenishment_amount_fund_by_julo_per_lender_osp_account,
            },
        }
    )
    return (
        total_replenishment_amount_fund_by_lender_per_lender_osp_account,
        total_replenishment_amount_fund_by_julo_per_lender_osp_account
    )


def execute_find_replenishment_loan_payment_by_user(
    lender_osp_account_id, need_replenishment_lender, need_replenishment_julo
):
    """
    There are 2 type of loans that we can tag as replenishment_tag:
    1. loan status = 220 that never been initial tagged or replenishment tagged previously.
    2. loan is released because of released_by_lender, OSP > 0, have not hit DPD 90 (status 234),
    and have different lender osp account
    We prioritize type 1 than type 2
    :param lender_osp_account_id:
    :param total_replenishment_amount: total amount need to be replenished
    """
    total_replenishment_amount = need_replenishment_lender + need_replenishment_julo
    if need_replenishment_lender <= 0 and need_replenishment_julo <= 0:
        return

    lender_osp_account = LenderOspAccount.objects.get_or_none(
        pk=lender_osp_account_id
    )
    if not lender_osp_account:
        raise Exception('lender_osp_account with id {} not found'.format(
            lender_osp_account_id
        ))

    # find loans type 1. loan status = 220, and never been initial tagged or replenishment tagged
    tagged_loan_220_never_tagged, total_loan_lender, total_loan_julo = loan_tagging_process(
        lender_osp_account_id=lender_osp_account_id
    )
    total_tagged_loan_220_never_tagged = total_loan_lender + total_loan_julo

    # prioritize type 1 than type 2, so only find type 2 if not enough loan type 1
    total_tagged_loan_not_234_released_by_lender_and_have_osp = 0
    total_tagged_loan_not_234_released_by_lender = 0
    total_tagged_loan_not_234_released_by_julo = 0
    tagged_loan_not_234_released_by_lender_and_have_osp = {}
    if total_loan_lender < need_replenishment_lender or total_loan_julo < need_replenishment_julo:
        # find loans type 2. loan is released because of released_by_lender, OSP > 0,
        # have not hit DPD 90 (status 234), and have different lender osp account
        # pass need to fund minus tagged loan with 220 status
        (
            total_tagged_loan_not_234_released_by_lender,
            total_tagged_loan_not_234_released_by_julo,
            tagged_loan_not_234_released_by_lender_and_have_osp
        ) = loan_tagging_process_extend_for_replenishment(
            lender_osp_account_id=lender_osp_account_id,
            total_lender=need_replenishment_lender - total_loan_lender,
            total_julo=need_replenishment_julo - total_loan_julo,
        )
        total_tagged_loan_not_234_released_by_lender_and_have_osp = (
            total_tagged_loan_not_234_released_by_lender
            + total_tagged_loan_not_234_released_by_julo
        )

    total_tagged_loan = (
        total_tagged_loan_220_never_tagged
        + total_tagged_loan_not_234_released_by_lender_and_have_osp
    )
    tagged_loan = tagged_loan_220_never_tagged
    tagged_loan.update(tagged_loan_not_234_released_by_lender_and_have_osp)
    if not total_tagged_loan and not tagged_loan:
        logger.warning(
            {
                "action": "juloserver.channeling_loan.services.execute_find_replenishment_loan",
                "lender_osp_account": lender_osp_account_id,
                "message": (
                    "Not found suitable loans to replenish. "
                    "total_replenishment_amount={}".format(
                        total_replenishment_amount
                    )
                ),
            }
        )
        # No need to update the value here since we saving the total
        return

    total_replenishment_tagged_loan = 0
    replenishment_lender_loan_ledgers = []
    for loan_id, loan in tagged_loan.items():
        replenishment_lender_loan_ledgers.append(
            LenderLoanLedger(
                lender_osp_account=lender_osp_account,
                application_id=loan["application_id"],
                loan_xid=loan["loan_xid"],
                loan_id=loan_id,
                osp_amount=loan["amount"],
                tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
                notes=loan['notes'],
                is_fund_by_julo=loan['is_fund_by_julo'],
            )
        )
        total_replenishment_tagged_loan += loan["amount"]

    # FOUND SUITABLE LOAN TO REPLENISH,
    # SO WE NEED TO ADD SOME NEW LenderLoanLedgers,
    # DEDUCT THE AMOUNT NOT FOUND TO THE PROCESSED_BALANCE_AMOUNT, OSP, AND ADD TO BALANCE_AMOUNT
    with transaction.atomic():
        # insert loan tagging
        LenderLoanLedger.objects.bulk_create(
            replenishment_lender_loan_ledgers,
            batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE
        )
        _, need_to_fund_lender, need_to_fund_julo = get_outstanding_withdraw_amount(
            lender_osp_account
        )

        # update lender balance
        total_replenishment_lender = (
            total_loan_lender + total_tagged_loan_not_234_released_by_lender
        )
        update_replenishment_amount_and_lender_balance(
            lender_osp_account=lender_osp_account,
            total_replenishment_tagged_loan=total_replenishment_lender,
            reason="replenishment_tag",
            is_fund_by_julo=False,
        )
        # update julo balance
        total_replenishment_julo = total_loan_julo + total_tagged_loan_not_234_released_by_julo
        update_replenishment_amount_and_lender_balance(
            lender_osp_account=lender_osp_account,
            total_replenishment_tagged_loan=total_replenishment_julo,
            reason="replenishment_tag",
            is_fund_by_julo=True,
        )

        total_not_found_replenishment_amount = need_to_fund_lender + need_to_fund_julo
        if need_to_fund_lender > 0 or need_to_fund_julo > 0:
            message = (
                "Not found enough loans to replenish. "
                "total_not_found_replenishment_amount={}"
            ).format(total_not_found_replenishment_amount)
        elif need_to_fund_lender == 0 and need_to_fund_julo == 0:
            message = (
                "Found enough loans to replenish. "
                "total_not_found_replenishment_amount={}"
            ).format(total_not_found_replenishment_amount)
        else:
            message = (
                "Found more loans to replenish than total need to replenish (not exceed margin). "
                "total_not_found_replenishment_amount={}"
            ).format(0)

        logger.warning(
            {
                "action": "juloserver.channeling_loan.services.execute_find_replenishment_loan",
                "lender_osp_account_id": lender_osp_account_id,
                "message": message,
            }
        )


def loan_tagging_process_extend_for_replenishment(
    lender_osp_account_id, total_lender, total_julo
):
    """
    loan is released because of released_by_lender, OSP > 0, have not hit DPD 90 (status 234),
    and have different lender osp account
    :param lender_osp_account_id:
    :param hard_outstanding_withdraw_amount: find loans with specific amount for replenishment
    :param reduced_margin_amount: to reduce margin amount for replenishment
    Eg: lender withdraw batch has:
            - balance_amount = 9.000
            - margin = 1.000
            - processed_balance_amount = 9.200 -> margin amount that already processed is 200
        So when we need to replenish 500, we only use margin = 800 (reduce margin amount to 200)
        to make sure this lender withdraw batch doesn't exceed the allowed margin
    """
    lender_osp_account = LenderOspAccount.objects.get_or_none(
        pk=lender_osp_account_id,
    )
    if not lender_osp_account:
        return None, None, None

    # no need to do further matchmaking
    if total_lender <= 0 and total_julo <= 0:
        return None, None, None

    lender_osp_account_name = lender_osp_account.lender_account_name

    feature_setting = get_loan_tagging_feature_setting()
    lenders = get_loan_tagging_feature_setting_lenders(feature_setting)
    lenders = lenders.get(lender_osp_account_name)

    get_loans_query = get_replenishment_tag_query()
    param = [
        ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
        ChannelingLenderLoanLedgerConst.RELEASED_BY_REFINANCING,
        ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
        lender_osp_account.id,
        lenders,
    ]

    tagged_loan, total_loan_lender, total_loan_julo = loan_logic_process(
        get_loans_query,
        param,
        total_lender,
        total_julo,
        feature_setting,
        lender_osp_account.lender_account_name
    )
    return total_loan_lender, total_loan_julo, tagged_loan


def update_replenishment_amount_and_lender_balance(
    lender_osp_account, total_replenishment_tagged_loan, reason, is_fund_by_julo,
):
    with transaction.atomic():
        # update lender withdraw batch processed amount & replenishment amount for next checking
        new_processed_balance_amount = (
            lender_osp_account.total_outstanding_principal + total_replenishment_tagged_loan
        )
        new_fund_by_julo = lender_osp_account.fund_by_julo
        new_fund_by_lender = lender_osp_account.fund_by_lender

        if is_fund_by_julo:
            new_fund_by_julo += total_replenishment_tagged_loan
        else:
            new_fund_by_lender += total_replenishment_tagged_loan

        # insert history
        update_lender_osp_balance(
            lender_osp_account,
            lender_osp_account.balance_amount,
            new_fund_by_lender,
            new_fund_by_julo,
            reason=reason,
        )

        # update fund by julo/lender
        if is_fund_by_julo:
            lender_osp_account.update_safely(
                fund_by_julo=new_fund_by_julo,
                total_outstanding_principal=new_processed_balance_amount,
            )
        else:
            lender_osp_account.update_safely(
                fund_by_lender=new_fund_by_lender,
                total_outstanding_principal=new_processed_balance_amount,
            )


def release_loan_tagging_dpd_90():
    """
    This function only releasing lender_loan_ledgers,
    will still need to update the withdraw_batch and lender_osp_balance separately
    """
    lender_loan_ledgers = LenderLoanLedger.objects.filter(
        loan__loanlendertaggingdpdtemp__loan_dpd=90,
        tag_type__in=[
            ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
        ]
    )
    lender_loan_ledger_histories = []
    lender_osp_account__lender_loan_ledger = {}
    for lender_loan_ledger in lender_loan_ledgers:
        lender_osp_account_id = lender_loan_ledger.lender_osp_account_id
        if lender_osp_account_id not in lender_osp_account__lender_loan_ledger:
            lender_osp_account__lender_loan_ledger[lender_osp_account_id] = {
                'total_lender': 0,
                'total_julo': 0,
                'lender_osp_account': lender_loan_ledger.lender_osp_account,
            }
        # map to update the amount later
        if lender_loan_ledger.is_fund_by_julo:
            lender_osp_account__lender_loan_ledger[
                lender_osp_account_id
            ]['total_julo'] += lender_loan_ledger.osp_amount
        else:
            lender_osp_account__lender_loan_ledger[
                lender_osp_account_id
            ]['total_lender'] += lender_loan_ledger.osp_amount

        lender_loan_ledger_histories.append(
            LenderLoanLedgerHistory(
                lender_loan_ledger=lender_loan_ledger,
                field_name='tag_type',
                old_value=lender_loan_ledger.tag_type,
                new_value=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90,
            )
        )

    with transaction.atomic():
        # update balance based on map
        for key, value in lender_osp_account__lender_loan_ledger.items():
            lender_osp_account = lender_osp_account__lender_loan_ledger[key]['lender_osp_account']
            total_lender = lender_osp_account__lender_loan_ledger[key]['total_lender']
            total_julo = lender_osp_account__lender_loan_ledger[key]['total_julo']

            new_total_julo = lender_osp_account.fund_by_julo - total_julo
            new_total_lender = lender_osp_account.fund_by_lender - total_lender

            # insert history if lender balance
            update_lender_osp_balance(
                lender_osp_account,
                lender_osp_account.balance_amount,
                new_total_lender,
                new_total_julo,
                reason="release_loan_tagging_dpd_90",
            )

            # update fund lender & fund julo, and total
            lender_osp_account.update_safely(
                fund_by_lender=new_total_lender,
                fund_by_julo=new_total_julo,
                total_outstanding_principal=new_total_lender + new_total_julo
            )
            lender_osp_account.fund_by_lender -= total_lender

        # update lender_loan_ledger tag
        lender_loan_ledgers.update(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90
        )
        # insert lender_loan_ledger history
        LenderLoanLedgerHistory.objects.bulk_create(
            lender_loan_ledger_histories,
            batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE,
        )

    logger.info({
        "action": "juloserver.channeling_loan.tasks.release_loan_tagging_dpd_90",
        "info": "success"
    })
    return lender_loan_ledgers


def execute_repayment_process_service(lender_osp_account_id, repayment_amount):
    """
    total repayment cannot exceed repayment_amount
    after releasing the lender value (100%), we release the 15% of the julo value
    """
    lender_osp_account = LenderOspAccount.objects.get_or_none(
        pk=lender_osp_account_id
    )
    if not lender_osp_account:
        return

    lender_loan_ledgers = []

    if lender_osp_account.balance_amount <= repayment_amount:
        # release all
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account_id=lender_osp_account_id,
            tag_type__in=[
                ChannelingLenderLoanLedgerConst.INITIAL_TAG,
                ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            ],
        )
        lender_osp_account.balance_amount = 0
        lender_osp_account.fund_by_lender = 0
        lender_osp_account.fund_by_julo = 0
        lender_osp_account.total_outstanding_principal = 0
    else:
        lender_loan_ledgers, total_lender, total_julo = repayment_logic_process(
            lender_osp_account,
            repayment_amount
        )
        lender_osp_account.balance_amount -= repayment_amount
        lender_osp_account.fund_by_lender -= total_lender
        lender_osp_account.fund_by_julo -= total_julo
        total_lender_and_julo = total_lender + total_julo
        lender_osp_account.total_outstanding_principal -= total_lender_and_julo

    lender_loan_ledger_histories = []
    for lender_loan_ledger in lender_loan_ledgers:
        lender_loan_ledger_histories.append(
            LenderLoanLedgerHistory(
                lender_loan_ledger=lender_loan_ledger,
                field_name='tag_type',
                old_value=lender_loan_ledger.tag_type,
                new_value=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            )
        )
        lender_loan_ledger.tag_type = ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT

    # requery loan
    old_lender_osp_account = LenderOspAccount.objects.get_or_none(
        pk=lender_osp_account_id
    )
    with transaction.atomic():
        # update the lender withdraw batchs
        update_lender_osp_balance(
            old_lender_osp_account,
            lender_osp_account.balance_amount,
            lender_osp_account.fund_by_lender,
            lender_osp_account.fund_by_julo,
            reason="released_by_repayment",
        )
        lender_osp_account.save()

        # update the lender loan ledger
        if lender_loan_ledgers:
            bulk_update(
                lender_loan_ledgers,
                update_fields=[
                    'tag_type',
                ],
                batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE,
            )

        # insert lender loan ledger history
        if lender_loan_ledger_histories:
            LenderLoanLedgerHistory.objects.bulk_create(
                lender_loan_ledger_histories,
                batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE,
            )


def repayment_logic_process(lender_osp_account, repayment_amount):
    """
    margin a little bit different with loan_logic_process
    total amount must be less than repayment amount,
    but more than repayment - margin
    """
    if repayment_amount <= 0:
        # if repayment amount is 0, no need for this process
        return [], 0, 0

    # calculate julo percentage & amount
    julo_withdraw_percentage = (
        lender_osp_account.lender_withdrawal_percentage - 100
    )
    julo_repayment_amount = julo_withdraw_percentage * repayment_amount / 100

    # value can be negative to show use margin
    _, need_to_fund_lender, need_to_fund_julo = get_outstanding_withdraw_amount(
        lender_osp_account
    )
    need_to_fund_lender = need_to_fund_lender if need_to_fund_lender >= 0 else 0
    need_to_fund_julo = need_to_fund_julo if need_to_fund_julo >= 0 else 0
    """
    decrease by need to replenish amount,
    in case withdraw loan not fully fulfilled, may no need to release
    ex withdraw 50M and only fulfilled 30M (need replenish 20M)
    and then released by 30M
    so only need to find 10M (30M - 20M)
    """
    julo_repayment_amount -= need_to_fund_julo
    repayment_amount -= need_to_fund_lender

    # find for non julo first
    total_lender = 0
    total_julo = 0
    released_lender_loan_ledger = []
    if repayment_amount > 0:
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=lender_osp_account,
            is_fund_by_julo=False,
            tag_type__in=[
                ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
                ChannelingLenderLoanLedgerConst.INITIAL_TAG
            ]
        )
        total_lender = 0
        for lender_loan_ledger in lender_loan_ledgers:
            total_lender += lender_loan_ledger.osp_amount
            released_lender_loan_ledger.append(lender_loan_ledger)

            if total_lender >= repayment_amount:
                break

    if julo_repayment_amount > 0:
        # release the JULO loan
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=lender_osp_account,
            is_fund_by_julo=True,
            tag_type__in=[
                ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
                ChannelingLenderLoanLedgerConst.INITIAL_TAG
            ]
        )
        total_julo = 0
        for lender_loan_ledger in lender_loan_ledgers:
            total_julo += lender_loan_ledger.osp_amount
            released_lender_loan_ledger.append(lender_loan_ledger)

            if total_julo >= julo_repayment_amount:
                break

    return released_lender_loan_ledger, total_lender, total_julo


def update_lender_osp_balance(
    lender_osp_account,
    balance_amount,
    fund_by_lender,
    fund_by_julo,
    reason=None,
):
    # record the history
    try:
        with transaction.atomic():
            histories = []
            balance_amount_old = lender_osp_account.balance_amount
            if balance_amount_old != balance_amount:
                histories.append(
                    LenderOspBalanceHistory(
                        lender_osp_account=lender_osp_account,
                        old_value=balance_amount_old,
                        new_value=balance_amount,
                        field_name='balance_amount',
                        reason=reason,
                    )
                )

            fund_by_lender_old = lender_osp_account.fund_by_lender
            if fund_by_lender_old != fund_by_lender:
                histories.append(
                    LenderOspBalanceHistory(
                        lender_osp_account=lender_osp_account,
                        old_value=fund_by_lender_old,
                        new_value=fund_by_lender,
                        field_name='fund_by_lender',
                        reason=reason,
                    )
                )

            fund_by_julo_old = lender_osp_account.fund_by_julo
            if fund_by_julo_old != fund_by_julo:
                histories.append(
                    LenderOspBalanceHistory(
                        lender_osp_account=lender_osp_account,
                        old_value=fund_by_julo_old,
                        new_value=fund_by_julo,
                        field_name='fund_by_julo',
                        reason=reason,
                    )
                )
            if histories:
                LenderOspBalanceHistory.objects.bulk_create(histories)

    except Exception as e:
        logger.error({
            "action": "juloserver.channeling_loan.services."
                      "loan_tagging_services.update_lender_osp_balance",
            "info": e,
        })
        return False
    return True


def get_outstanding_withdraw_amount(lender_osp_account):
    # get withdraw_amount based on percentage withdraw on lender_osp_account
    # need_fund value cannot be less than 0 (negative value mean exceeding margin used)
    balance_amount = lender_osp_account.balance_amount

    # total 115% of balance_amount
    withdraw_balance = (
        balance_amount * lender_osp_account.lender_withdrawal_percentage
        / 100
    )

    # lender_withdraw_amount is total loan value that need to be found for lender
    need_to_fund_lender = int(
        py2round(balance_amount - lender_osp_account.fund_by_lender)
    )
    # need_to_fund_lender = need_to_fund_lender if need_to_fund_lender > 0 else 0

    # find the 15% for julo
    total_balance_julo = withdraw_balance - balance_amount
    need_to_fund_julo = int(
        py2round(total_balance_julo - lender_osp_account.fund_by_julo)
    )
    # need_to_fund_julo = need_to_fund_julo if need_to_fund_julo > 0 else 0

    return withdraw_balance, need_to_fund_lender, need_to_fund_julo


def loan_tagging_process(
    lender_osp_account_id
):
    """
    Main logic for tagging process
    1. get amount that haven't been processed from LenderOspTransaction
    2. find loan_xids that already used in loan tagging (initial_tag)
    3. get all JTP loans that are 220 and not haven't been used to tagging process[2]
    4. sum total loan per batch [feature setting] until LenderOspTransaction amount,
       and then save loan_id and loan_amount on dict
    :param lender_osp_account_id:
    :param hard_outstanding_withdraw_amount: find loans with specific amount for replenishment
    :param reduced_margin_amount: to reduce margin amount for replenishment
    Eg: lender withdraw batch has:
            - balance_amount = 9.000
            - margin = 1.000
            - processed_balance_amount = 9.200 -> margin amount that already processed is 200
        So when we need to replenish 500, we only use margin = 800 (reduce margin amount to 200)
        to make sure this lender withdraw batch doesn't exceed the allowed margin
    """
    lender_osp_account = LenderOspAccount.objects.get_or_none(
        pk=lender_osp_account_id
    )
    if not lender_osp_account:
        return {}, 0, 0

    feature_setting = get_loan_tagging_feature_setting()

    # jackson function no longer needed since he will update total?
    _, need_to_fund_lender, need_to_fund_julo =\
        get_outstanding_withdraw_amount(
            lender_osp_account
        )

    if need_to_fund_lender <= 0 and need_to_fund_julo <= 0:
        # fulfilled, no need to matchmaking
        return {}, 0, 0

    lender_osp_account_name = lender_osp_account.lender_account_name

    lenders = []
    if feature_setting:
        lenders = feature_setting.parameters["lenders_match_for_lender_osp_account"].get(
            lender_osp_account_name
        )

    if not lenders:
        lenders = LoanTaggingConst.LENDERS_MATCH_FOR_LENDER_OSP_ACCOUNT.get(
            lender_osp_account_name
        )

    get_loans_query = get_initial_tag_query()
    param = [
        ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
        ChannelingLenderLoanLedgerConst.RELEASED_BY_REFINANCING,
        ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
        lender_osp_account_id,
        lenders,
    ]

    processed_loan, total_loan_lender, total_loan_julo = loan_logic_process(
        get_loans_query,
        param,
        need_to_fund_lender,
        need_to_fund_julo,
        feature_setting,
        lender_osp_account.lender_account_name
    )

    return processed_loan, total_loan_lender, total_loan_julo


def get_loans_cursor(sql_query, params, batch_size=1000):
    cursor = connection.cursor()
    cursor.execute(sql_query, params)
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        yield rows

    cursor.close()


def get_initial_tag_query():
    # RAW QUERY
    # moved to function so can be mocked for testing purpose
    loans_initial_tag_query = """
        SELECT loan.loan_id, loan.application_id, loan.loan_amount,
        loan.loan_xid, loan.application_id2
        FROM ops.loan
        INNER JOIN ops.lender ON (loan.lender_id = lender.lender_id)
        INNER JOIN ops.loan_lender_tagging_loan_dpd_temp ON (
            loan.loan_id = loan_lender_tagging_loan_dpd_temp.loan_id
        )
        LEFT JOIN ops.lender_loan_ledger ON (
            loan.loan_id = lender_loan_ledger.loan_id
            and (
                lender_loan_ledger.tag_type IN (%s, %s, %s)
                or (
                    lender_loan_ledger.tag_type = %s
                    and lender_loan_ledger.lender_osp_account_id = %s
                )
            )
        )
        WHERE lender.lender_name = ANY(%s)
        AND loan_lender_tagging_loan_dpd_temp.loan_dpd <= 0
        AND lender_loan_ledger.loan_id is null
    """
    return loans_initial_tag_query


def get_replenishment_tag_query():
    """
    RAW QUERY
    moved to function so can be mocked for testing purpose
    for this process 2, only tagged loan that RELEASED_BY_REPAYMENT by other lender
    this process will only for loan with dpd 1-89
    also make sure current loan is not active as initial_tag/replenishment
    joining to lender_loan_ledger to check the loan that need to be skipped
    if lender_loan_ledger exist, meaning loan have to be skipped,
    hence lender_loan_ledger.loan_id is null check is have to be done on queries
    """
    loans_replenishment_tag_query = """
        SELECT loan.loan_id, loan.application_id, loan.loan_amount,
        loan.loan_xid, loan.application_id2
        FROM ops.loan
        INNER JOIN ops.lender ON (loan.lender_id = lender.lender_id)
        INNER JOIN ops.loan_lender_tagging_loan_dpd_temp ON (
            loan.loan_id = loan_lender_tagging_loan_dpd_temp.loan_id
        )
        LEFT JOIN ops.lender_loan_ledger ON (
            loan.loan_id = lender_loan_ledger.loan_id
            and (
                lender_loan_ledger.tag_type IN (%s, %s, %s)
                or (
                    lender_loan_ledger.tag_type = %s
                    and lender_loan_ledger.lender_osp_account_id = %s
                )
            )
        )
        WHERE lender.lender_name = ANY(%s)
        AND loan_lender_tagging_loan_dpd_temp.loan_dpd > 0
        AND loan_lender_tagging_loan_dpd_temp.loan_dpd < 90
        AND lender_loan_ledger.loan_id is null
    """
    return loans_replenishment_tag_query


def loan_logic_process(
    get_loans_query,
    param,
    need_to_fund_lender,
    need_to_fund_julo,
    feature_setting,
    lender_osp_account_name,
):
    processed_loan = {}
    # will be used for repayment too
    margin = LoanTaggingConst.DEFAULT_MARGIN
    batch_size = LoanTaggingConst.DEFAULT_LOAN_QUERY_BATCH_SIZE

    if feature_setting:
        # if feature setting not found, will use default value
        margin = feature_setting.parameters["margin"]
        batch_size = feature_setting.parameters["loan_query_batch_size"]

    used_margin = 0
    # used margin will be resulting minus on need_to_fund
    if need_to_fund_lender < 0:
        used_margin -= need_to_fund_lender

    if need_to_fund_julo < 0:
        used_margin -= need_to_fund_julo

    margin -= used_margin

    total_loan_lender = 0
    total_loan_julo = 0
    """
    loan_slices are on tupple with index:
    0 : loan_id
    1 : application_id
    2 : loan_amount
    3 : loan_xid
    4 : application_id2
    """
    for loan_slices in get_loans_cursor(get_loans_query, param, batch_size=batch_size):
        loan_amount_index = 2
        total_sliced_loans = sum(loan[loan_amount_index] for loan in loan_slices)
        if total_sliced_loans < (need_to_fund_lender - total_loan_lender):
            notes = "{} Fund".format(lender_osp_account_name)
            for loan in loan_slices:
                loan_id, application_id, loan_amount, loan_xid, application_id2 = loan
                processed_loan[loan_id] = {
                    "amount": loan_amount,
                    "loan_xid": loan_xid,
                    "application_id": application_id
                    if application_id
                    else application_id2,
                    "notes": notes,
                    "is_fund_by_julo": False,
                }
            total_loan_lender += total_sliced_loans
        else:
            # total sliced loan is less than that
            notes = "{} funded by JULO Equity".format(lender_osp_account_name)
            is_lender_equity = False
            if (need_to_fund_lender - total_loan_lender) > 0:
                notes = "{} Fund".format(lender_osp_account_name)
                is_lender_equity = True

            for loan in loan_slices:
                loan_id, application_id, loan_amount, loan_xid, application_id2 = loan
                if is_lender_equity:
                    # go to lender
                    if loan_amount > (need_to_fund_lender - total_loan_lender) + margin:
                        continue
                    total_loan_lender += loan_amount
                else:
                    # go to julo
                    if loan_amount > (need_to_fund_julo - total_loan_julo) + margin:
                        continue
                    total_loan_julo += loan_amount

                processed_loan[loan_id] = {
                    "amount": loan_amount,
                    "loan_xid": loan_xid,
                    "application_id": application_id
                    if application_id
                    else application_id2,
                    "notes": notes,
                    "is_fund_by_julo": not is_lender_equity,
                }

                # change to julo equity now
                if (
                    is_lender_equity
                    and total_loan_lender >= need_to_fund_lender
                    and need_to_fund_julo > 0
                ):
                    notes = "{} funded by JULO Equity".format(lender_osp_account_name)
                    # reduce exceeding margin
                    margin -= total_loan_lender - need_to_fund_lender
                    is_lender_equity = False

                if (
                    total_loan_lender >= need_to_fund_lender
                    and total_loan_julo >= need_to_fund_julo
                ):
                    break

    return processed_loan, total_loan_lender, total_loan_julo


def get_loan_tagging_feature_setting():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOAN_TAGGING_CONFIG, is_active=True
    ).last()

    return feature_setting


def daily_checker_loan_tagging_clone_table():
    # run once per day
    feature_setting = get_loan_tagging_feature_setting()
    daily_checker_active = False
    if feature_setting:
        daily_checker_active = feature_setting.parameters.get("is_daily_checker_active")
    logger.info({
        "action": "juloserver.channeling_loan.tasks.daily_checker_loan_tagging",
        "info": "executing daily checker for Loan Tagging",
        "daily_checker_active": daily_checker_active,
    })
    if daily_checker_active:
        clone_ana_table()
        release_loan_tagging_dpd_90()


def daily_checker_loan_tagging():
    # every 3 hours
    feature_setting = get_loan_tagging_feature_setting()
    daily_checker_active = False
    if feature_setting:
        daily_checker_active = feature_setting.parameters.get("is_daily_checker_active")
    logger.info({
        "action": "juloserver.channeling_loan.tasks.daily_checker_loan_tagging",
        "info": "executing daily checker for Loan Tagging",
        "daily_checker_active": daily_checker_active,
    })
    if daily_checker_active:
        execute_replenishment_loan_payment_by_user_process()
        execute_replenishment_matchmaking()


def get_loan_tagging_feature_setting_lenders(feature_setting=None):
    if not feature_setting:
        feature_setting = get_loan_tagging_feature_setting()
    # default value from constant if feature setting not active
    lenders = LoanTaggingConst.LENDERS_MATCH_FOR_LENDER_OSP_ACCOUNT
    if feature_setting:
        lenders = feature_setting.parameters["lenders_match_for_lender_osp_account"]

    return lenders


def clone_ana_table():
    try:
        delete_temporary_dpd_table()
        loan_dpd_ana = LoanLenderTaggingDpd.objects.all()
        loan_dpd_temp = []
        for data in loan_dpd_ana.iterator():
            loan_dpd_temp.append(
                LoanLenderTaggingDpdTemp(
                    loan_id=data.loan_id,
                    loan_dpd=data.loan_dpd,
                )
            )

        if loan_dpd_temp:
            LoanLenderTaggingDpdTemp.objects.bulk_create(
                loan_dpd_temp,
                batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE,
            )
    except Exception as e:
        logger.exception({
            "action": "clone_ana_table",
            "message": str(e)
        })
        get_julo_sentry_client().captureException()
        return False

    return True


def delete_temporary_dpd_table():
    try:
        with transaction.atomic():
            cursor = connection.cursor()
            cursor.execute("TRUNCATE TABLE ops.loan_lender_tagging_loan_dpd_temp")
            cursor.close()

    except Exception as e:
        logger.exception({
            "action": "delete_temporary_dpd_table",
            "message": str(e)
        })
        cursor.close()

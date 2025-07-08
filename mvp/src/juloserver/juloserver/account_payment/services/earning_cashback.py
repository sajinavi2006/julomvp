from datetime import timedelta

import logging
from django.db.models import Sum
from django.db.models import Q
from django.utils import timezone

from juloserver.cashback.constants import CashbackChangeReason
from juloserver.waiver.models import WaiverRequest
from juloserver.payback.constants import WaiverConst
from juloserver.payback.models import WaiverTemp
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.julo.constants import NewCashbackReason, NewCashbackConst
from juloserver.julo.models import (
    FeatureSetting,
    Loan,
    Image,
    CustomerWalletHistory,
)
from juloserver.minisquad.constants import FeatureNameConst as MinisqaudFeatureNameConst
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.constants import AccountConstant
from juloserver.account_payment.models import CashbackClaimPayment
from juloserver.account_payment.constants import CashbackClaimConst
from juloserver.julo.constants import FeatureNameConst


logger = logging.getLogger(__name__)


def j1_update_cashback_earned(payment, new_cashback_dict=dict(), is_cashback_experiment=False):
    # new_cashback_dict, this parameter need to be mutable
    # we need bring the changes cross the function
    from juloserver.julo.services import record_data_for_cashback_new_scheme

    is_eligible_new_cashback = new_cashback_dict.get('is_eligible_new_cashback', False)
    if new_cashback_dict.get('account_status') == AccountConstant.STATUS_CODE.suspended:
        is_eligible_new_cashback = False
        new_cashback_dict['status'] = NewCashbackConst.ACCOUNT_STATUS_SUSPENDED
    due_date_cashback = new_cashback_dict.get('due_date', -3)
    paid_date_earlier_cashback_new_scheme = payment.due_date - timedelta(
        days=abs(due_date_cashback))
    counter = new_cashback_dict.get('cashback_counter', 0)
    new_cashback_percentage = 0  # default
    if (
        is_eligible_new_cashback or counter > 0
    ) and paid_date_earlier_cashback_new_scheme < payment.paid_date:
        logger.info(
            {
                'function': 'j1_update_cashback_earned',
                'payment_id': payment.id,
                'status': 'Failed',
                'reason': 'passed due date cashback new scheme',
            }
        )
        # cashback counter need to reset if status refinancing/waiver/passed due
        new_cashback_dict['status'] = NewCashbackConst.PASSED_STATUS
        new_cashback_dict['cashback_counter'] = 0
        record_data_for_cashback_new_scheme(payment, None, 0, NewCashbackReason.PAID_AFTER_TERMS)
        return

    if payment.loan.is_restructured:
        logger.info(
            {
                'function': 'j1_update_cashback_earned',
                'payment_id': payment.id,
                'status': 'Failed',
                'reason': 'because payment related to restructured loan',
            }
        )
        if is_eligible_new_cashback or counter > 0:
            # cashback counter need to reset if status refinancing/waiver
            new_cashback_dict['status'] = NewCashbackConst.REFINANCING_STATUS
            new_cashback_dict['cashback_counter'] = 0
            record_data_for_cashback_new_scheme(
                payment, None, 0, NewCashbackReason.PAID_REFINANCING)
        return

    if payment.change_due_date_interest == 0:
        cashback_earned = 0
        loan = payment.loan
        paid_date_3_days_earlier = payment.due_date - timedelta(days=3)
        paid_date_2_days_earlier = payment.due_date - timedelta(days=2)
        if is_eligible_new_cashback:
            if counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
                counter += 1
            else:
                counter = NewCashbackConst.MAX_CASHBACK_COUNTER
            new_cashback_percentage = new_cashback_dict.get('percentage_mapping').get(
                str(counter), 0
            )
            cashback_earned = loan.new_cashback_monthly(new_cashback_percentage)
            logger.info(
                {
                    'function': 'j1_update_new_cashback_earned',
                    'payment_id': payment.id,
                    'cashback_earned': cashback_earned,
                    'counter': counter,
                    'cashback_percentage': new_cashback_percentage,
                }
            )
        else:
            cashback_earned = loan.cashback_monthly
            logger.info(
                {
                    'function': 'j1_update_cashback_earned',
                    'payment_id': payment.id,
                    'cashback_earned': cashback_earned,
                }
            )
            if cashback_earned:
                if paid_date_3_days_earlier <= payment.paid_date <= paid_date_2_days_earlier:
                    cashback_earned *= 2
                elif paid_date_3_days_earlier > payment.paid_date:
                    cashback_earned *= 3

        if payment.account_payment:
            waiver_request = (
                WaiverRequest.objects.filter(
                    first_waived_account_payment__lte=payment.account_payment.id,
                    last_waived_account_payment__gte=payment.account_payment.id,
                    account=payment.account_payment.account,
                )
                .filter(Q(is_approved__isnull=True) | Q(is_approved=True))
                .last()
            )
            if waiver_request:
                if (
                    waiver_request.final_approved_waiver_program == "General Paid Waiver"
                    or waiver_request.final_approved_waiver_program is None
                ):
                    if is_eligible_new_cashback or counter > 0:
                        # cashback counter need to reset if status refinancing/waiver
                        new_cashback_dict['status'] = NewCashbackConst.WAIVER_STATUS
                        new_cashback_dict['cashback_counter'] = 0
                        record_data_for_cashback_new_scheme(
                            payment, None, 0, NewCashbackReason.PAID_WAIVER)
                    return
                else:
                    if WaiverTemp.objects.filter(
                        account=waiver_request.account, status=WaiverConst.IMPLEMENTED_STATUS
                    ).exists():
                        if is_eligible_new_cashback or counter > 0:
                            # cashback counter need to reset if status refinancing/waiver
                            new_cashback_dict['status'] = NewCashbackConst.WAIVER_STATUS
                            new_cashback_dict['cashback_counter'] = 0
                            record_data_for_cashback_new_scheme(
                                payment, None, 0, NewCashbackReason.PAID_WAIVER)
                        return

        cashback_earned = min(cashback_earned, payment.maximum_cashback)
        if not is_cashback_experiment:
            payment.cashback_earned += cashback_earned
            loan.customer.change_wallet_balance(
                change_accruing=cashback_earned,
                change_available=0,
                reason=CashbackChangeReason.PAYMENT_ON_TIME,
                payment=payment,
                account_payment=payment.account_payment,
                is_eligible_new_cashback=is_eligible_new_cashback,
                counter=counter,
                new_cashback_percentage=new_cashback_percentage,
            )
        else:
            cashback_claim_payment = CashbackClaimPayment.objects.filter(
                status__in=[CashbackClaimConst.STATUS_PENDING, CashbackClaimConst.STATUS_ELIGIBLE],
                payment_id=payment.id,
            ).last()
            if not cashback_claim_payment:
                CashbackClaimPayment.objects.create(
                    payment_id=payment.id,
                    status=CashbackClaimConst.STATUS_PENDING,
                    cashback_amount=cashback_earned,
                )
                if is_eligible_new_cashback:
                    record_data_for_cashback_new_scheme(
                        payment,
                        None,
                        counter,
                        NewCashbackReason.PAID_BEFORE_TERMS,
                        new_cashback_percentage,
                    )

        return cashback_earned
        # new_cashback_dict['status'] = NewCashbackConst.NORMAL_STATUS


def make_cashback_available(loan):
    cashback_payments = loan.payment_set.aggregate(total=Sum('cashback_earned'))['total']
    cashback_earned = cashback_payments + loan.initial_cashback
    customer = loan.customer
    customer.change_wallet_balance(
        change_accruing=0,
        change_available=cashback_earned,
        reason=CashbackChangeReason.LOAN_PAID_OFF,
        loan=loan,
    )


def reverse_cashback_available(loan):
    cashback_payments = loan.payment_set.aggregate(total=Sum('cashback_earned'))['total']
    cashback_earned = cashback_payments + loan.initial_cashback
    customer = loan.customer
    customer.change_wallet_balance(
        change_accruing=0,
        change_available=-cashback_earned,
        reason=CashbackChangeReason.LOAN_PAID_OFF_VOID,
        loan=loan,
    )


def check_cashback_for_paid_on_dpd_plus(payment):
    # this function to decide what reason for cashback history
    from juloserver.julo.services import record_data_for_cashback_new_scheme

    if payment.loan.is_restructured:
        record_data_for_cashback_new_scheme(
            payment, None, 0, NewCashbackReason.PAID_REFINANCING)
        return

    if payment.account_payment:
        waiver_request = (
            WaiverRequest.objects.filter(
                first_waived_account_payment__lte=payment.account_payment.id,
                last_waived_account_payment__gte=payment.account_payment.id,
                account=payment.account_payment.account,
            )
            .filter(Q(is_approved__isnull=True) | Q(is_approved=True))
            .last()
        )
        if waiver_request:
            if (
                waiver_request.final_approved_waiver_program == "General Paid Waiver"
                or waiver_request.final_approved_waiver_program is None
            ):
                record_data_for_cashback_new_scheme(
                    payment, None, 0, NewCashbackReason.PAID_WAIVER)
                return
            else:
                if WaiverTemp.objects.filter(
                    account=waiver_request.account, status=WaiverConst.IMPLEMENTED_STATUS
                ).exists():
                    record_data_for_cashback_new_scheme(
                        payment, None, 0, NewCashbackReason.PAID_WAIVER)
                    return

    record_data_for_cashback_new_scheme(
        payment, None, 0, NewCashbackReason.PAID_AFTER_TERMS)
    return


def get_potential_cashback_by_loan(loan):
    today = timezone.localtime(timezone.now()).date()
    potential_cashback = 0
    if not loan:
        return potential_cashback

    payments = loan.payment_set.filter(
        payment_status__lte=PaymentStatusCodes.PAID_ON_TIME,
        is_restructured=False,
    ).exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.grab())

    for payment in payments.iterator():
        if payment.status == PaymentStatusCodes.PAID_ON_TIME:
            customer_wallet_history = payment.customerwallethistory_set.last()
            if customer_wallet_history and \
                    customer_wallet_history.change_reason == CashbackChangeReason.PAYMENT_ON_TIME:
                potential_cashback += (customer_wallet_history.wallet_balance_accruing) - \
                    (customer_wallet_history.wallet_balance_accruing_old)
                continue
        elif payment.due_date < today:
            continue

        tmp_potential_cashback = loan.cashback_monthly
        paid_date_3_days_earlier = payment.due_date - timedelta(days=3)
        paid_date_2_days_earlier = payment.due_date - timedelta(days=2)
        if tmp_potential_cashback:
            if paid_date_3_days_earlier <= today <= paid_date_2_days_earlier:
                tmp_potential_cashback *= 2
            elif paid_date_3_days_earlier > today:
                tmp_potential_cashback *= 3

        potential_cashback += tmp_potential_cashback

    return potential_cashback


def is_cashback_new_scheme_experiment(payment):
    # handle grab haven't account payment
    if not payment.account_payment:
        return False

    account = payment.account_payment.account
    return get_cashback_experiment(account.id)


def get_cashback_experiment(account_id):
    '''
    consider if in the future we rollout 100% customer, we need to exclude partner
    '''
    from juloserver.minisquad.services2.growthbook import get_experiment_group_data_on_growthbook

    experiment_data = get_experiment_group_data_on_growthbook(
        MinisquadExperimentConstants.CASHBACK_NEW_SCHEME,
        account_id)
    if experiment_data and experiment_data.group == 'experiment':
        return True

    return False


def get_due_date_for_cashback_new_scheme():
    due_date_cashback = -3
    cashback_feature_setting = FeatureSetting.objects.filter(
        feature_name=MinisqaudFeatureNameConst.CASHBACK_NEW_SCHEME, is_active=True
    ).last()
    if cashback_feature_setting:
        due_date_cashback = cashback_feature_setting.parameters.get('due_date', -3)

    return due_date_cashback


def get_paramters_cashback_new_scheme(is_return_all_params: bool = False):
    due_date_cashback = -3
    cashback_counter_map = {'1': 1, '2': 1, '3': 2, '4': 2, '5': 4}
    cashback_new_scheme_params = dict()
    cashback_feature_setting = FeatureSetting.objects.filter(
        feature_name=MinisqaudFeatureNameConst.CASHBACK_NEW_SCHEME, is_active=True
    ).last()
    if cashback_feature_setting:
        due_date_cashback = cashback_feature_setting.parameters.get('due_date', due_date_cashback)
        cashback_counter_map = cashback_feature_setting.parameters.get(
            'cashback_counter_map', cashback_counter_map
        )
        cashback_new_scheme_params = cashback_feature_setting.parameters

    if not is_return_all_params:
        return due_date_cashback, cashback_counter_map
    else:
        return cashback_new_scheme_params


def get_cashback_drawer(customer):
    # check feature setting is active
    cashback_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CASHBACK_DRAWER_ENCOURAGEMENT,
        is_active=True,
    ).last()
    if not cashback_fs:
        return None

    # check has active loan
    unpaid_loan = Loan.objects.filter(
        customer=customer, loan_status_id__gte=220, loan_status_id__lt=250
    )
    if not unpaid_loan.exists():
        return None

    # check customer's dpd included
    cashback_dpd_list = cashback_fs.parameters.get("dpd")
    if not cashback_dpd_list:
        return None

    account = customer.account_set.last()
    if account.dpd not in cashback_dpd_list:
        return None

    # check customer has cashback balance to use
    customer_wallet = CustomerWalletHistory.objects.filter(
        customer=customer, latest_flag=True, wallet_balance_available__gt=0
    )
    if not customer_wallet.exists():
        return None

    # get image url
    image_url = None
    image_id = cashback_fs.parameters.get("image", {}).get("image_id")
    if image_id:
        image = Image.objects.get_or_none(
            id=image_id,
        )
        if image:
            image_url = image.image_url

    return {
        "image": image_url,
        "title": cashback_fs.parameters.get("title"),
        "message": cashback_fs.parameters.get("subtitle"),
        "action": {
            "action_type": "app_deeplink",
            "destination": cashback_fs.parameters.get("cta"),
        },
    }

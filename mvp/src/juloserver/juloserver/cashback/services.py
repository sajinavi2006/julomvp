from datetime import date
from dateutil.parser import parse
import logging
from babel.dates import format_date
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum

from juloserver.cashback.constants import (
    FeatureNameConst as CashbackFeatureNameConst,
    ReferralCashbackEventType,
    ReferralCashbackAction,
)
from juloserver.cashback.exceptions import (
    CashbackLessThanMinAmount,
    InvalidOverpaidStatus,
    InvalidCashbackEarnedVerified
)
from juloserver.cfs.constants import TierId
from juloserver.cfs.services.core_services import get_customer_tier_info, is_graduate_of
from juloserver.customer_module.models import CashbackBalance
from juloserver.cashback.models import (
    CashbackEarned,
    CashbackOverpaidVerification,
    OverpaidVerifyingHistory,
)
from juloserver.cashback.constants import (
    OverpaidConsts,
    CashbackExpiredConst,
    CashbackMethodName, CashbackChangeReason,
)
from juloserver.customer_module.services.customer_related import get_or_create_cashback_balance
from juloserver.referral.models import RefereeMapping, ReferralBenefitHistory
from juloserver.referral.constants import ReferralPersonTypeConst, ReferralBenefitConst
from juloserver.julo.banks import BankManager
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    CashbackTransferTransaction,
    FeatureSetting,
    Image,
    CustomerWalletHistory,
    Loan,
    Payment,
    Customer,
    MobileFeatureSetting,
)
from juloserver.julo.constants import (
    CashbackTransferConst,
    FeatureNameConst,
    MobileFeatureNameConst,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.cashback import CashbackRedemptionService
from juloserver.julo.utils import display_rupiah
from juloserver.moengage.services.use_cases import (
    trigger_moengage_after_freeze_unfreeze_cashback,
    send_event_moengage_cashback_injection,
)
from juloserver.account_payment.services.collection_related import get_cashback_claim_experiment

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class CashbackExpiredSetting:
    @classmethod
    def get_reminder_days(cls):
        setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION)
        if not setting or not setting.is_active:
            return CashbackExpiredConst.DEFAULT_REMINDER_DAYS

        return setting.parameters.get('reminder_days', CashbackExpiredConst.DEFAULT_REMINDER_DAYS)


def update_wallet_earned(customer_wallet_history, cashback_amount):
    if customer_wallet_history.change_reason in OverpaidConsts.Reason.non_cashback_earned():
        return

    with transaction.atomic():
        customer = customer_wallet_history.customer
        today = timezone.localtime(timezone.now()).date()

        cashback_expire_date = compute_cashback_expiry_date(today)
        verified = True
        if cashback_amount > 0:
            change_reason = customer_wallet_history.change_reason
            if change_reason == CashbackChangeReason.CASHBACK_OVER_PAID:
                verified = check_overpaid_cashback_verified(cashback_amount)
            elif change_reason in CashbackChangeReason.PROMO_REFERRALS:
                action = get_referral_cashback_action(
                    event_type=ReferralCashbackEventType.CASHBACK_EARNED
                )
                verified = (action != ReferralCashbackAction.FREEZE)

            cashback_earned = CashbackEarned.objects.create(
                current_balance=cashback_amount,
                expired_on_date=cashback_expire_date,
                verified=verified,
            )
            customer_wallet_history.update_safely(cashback_earned=cashback_earned)

        elif cashback_amount < 0:
            if customer_wallet_history.change_reason == \
                    CashbackChangeReason.CASHBACK_OVER_PAID_VOID:
                customer_wallet_history = customer.wallet_history.get(
                    change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
                    cashback_earned__isnull=False,
                    cashback_earned__current_balance=abs(cashback_amount)
                )
                current_balance = customer_wallet_history.cashback_earned.current_balance
                current_balance += cashback_amount
                customer_wallet_history.cashback_earned.update_safely(
                    current_balance=current_balance
                )
                return

            customer_wallet_histories = customer.wallet_history.get_queryset()\
                .cashback_earned_available().order_by(
                'cashback_earned__expired_on_date', 'id'
            )
            for customer_wallet_history in customer_wallet_histories.iterator():
                current_balance = customer_wallet_history.cashback_earned.current_balance
                current_balance += cashback_amount
                cashback_amount = current_balance
                if current_balance < 0:
                    current_balance = 0
                customer_wallet_history.cashback_earned.update_safely(
                    current_balance=current_balance
                )
                if cashback_amount >= 0:
                    break


def get_cashback_options_info_v1(application):
    options_response = get_cashback_options_response(application)
    return {
        'cashback_balance': options_response['cashback_balance'],
        'expiry_info': options_response['expiry_info'],
        'payment_enable': options_response['payment']['is_active'],
        'xendit_enable': options_response['xendit']['is_active'],
        'sepulsa_enable': options_response['sepulsa']['is_active'],
        'gopay_enable': options_response['gopay']['is_active'],
    }


def get_cashback_options_response(application):
    cashback_feature = FeatureSetting.objects.get(feature_name='cashback')

    cashback_balance = CashbackBalance.objects.get_or_none(customer=application.customer)
    _, tier_info = get_customer_tier_info(application)

    balance = cashback_balance.cashback_balance if cashback_balance else 0

    parameters = cashback_feature.parameters

    def turn_off_method(methods):
        for method in methods:
            if not parameters.get(method, {}):
                continue
            parameters[method]['is_active'] = False

    if application.is_julover():
        turn_off_method([
            CashbackMethodName.PAYMENT,
            CashbackMethodName.TADA
        ])

    if tier_info and not tier_info.pencairan_cashback:
        turn_off_method([
            CashbackMethodName.XENDIT,
            CashbackMethodName.SEPULSA,
            CashbackMethodName.GOPAY
        ])
    result = {
        'cashback_balance': balance,
        'expiry_info': get_cashback_expiry_info(application.customer_id),
    }
    result.update(parameters)
    return result


def get_cashback_expiry_info(customer_id):
    expired_date, expired_amount = get_expired_date_and_cashback(customer_id)
    reminder_days = CashbackExpiredSetting.get_reminder_days()
    today = timezone.localtime(timezone.now()).date()
    if expired_date is None or expired_amount <= 0 or (expired_date - today).days > reminder_days:
        return None

    return CashbackExpiredConst.Message.EXPIRY_INFO.format(
        expired_date=format_date(expired_date, 'd MMMM yyyy', locale='id_ID'),
        expired_amount=display_rupiah(expired_amount)
    )


def is_cashback_enabled(application):
    result = False
    old_product_codes = [
        *ProductLineCodes.mtl(),
        *ProductLineCodes.stl(),
        *ProductLineCodes.bri(),
        *ProductLineCodes.ctl(),
    ]
    if (
        application.is_julo_one_product() or
        application.is_julover() or
        application.is_julo_starter() or
        application.product_line_code in old_product_codes
    ):
        result = True

    return result


def generate_cashback_overpaid_case(customer_wallet_history):
    old_balance = customer_wallet_history.wallet_balance_available_old
    new_balance = customer_wallet_history.wallet_balance_available

    overpaid_amount = new_balance - old_balance
    if overpaid_amount < OverpaidConsts.MINIMUM_AMOUNT:
        return

    CashbackOverpaidVerification.objects.create(
        overpaid_amount=overpaid_amount,
        status=OverpaidConsts.Statuses.UNPROCESSED,
        customer=customer_wallet_history.customer,
        application=customer_wallet_history.application,
        wallet_history=customer_wallet_history,
    )


def process_decision_overpaid_case(case_id, agent, note, decision):
    """
        Find the overpaid case and update it to REJECTED/ACCEPTED,
        And store this decision in the history table,
        If there is an error, it's captured in the history as well
    """
    cashback_service = CashbackRedemptionService()
    error_message = ""
    processed_status = OverpaidConsts.Statuses.PROCESSING_FAILED

    sentry_client = get_julo_sentry_client()
    try:
        with transaction.atomic():
            case = CashbackOverpaidVerification.objects.select_for_update().get(pk=case_id)
            if case.status != OverpaidConsts.Statuses.PENDING:
                raise InvalidOverpaidStatus("Status is not PENDING. Processing failed.")

            cashback_earned = case.wallet_history.cashback_earned
            if cashback_earned and cashback_earned.verified:
                raise InvalidCashbackEarnedVerified("Verified can not be TRUE at this step")

            case.customer.change_wallet_balance(
                change_accruing=case.overpaid_amount,
                change_available=case.overpaid_amount,
                reason=CashbackChangeReason.OVERPAID_VERIFICATION_REFUNDED,
            )

            if decision == OverpaidConsts.Statuses.ACCEPTED:
                if cashback_earned:
                    cashback_earned.current_balance = case.overpaid_amount
                    cashback_earned.verified = True
                    cashback_earned.save()

                    update_customer_cashback_balance(case.customer)

                if case.application.eligible_for_cfs:
                    # check champion:
                    is_champion = is_graduate_of(case.application, TierId.CHAMPION)
                    is_enough_for_transfer = (
                        case.overpaid_amount >=
                        CashbackTransferConst.MIN_TRANSFER
                    )
                    if not is_champion and is_enough_for_transfer:
                        # create a transfer cashback request for non-champion
                        cashback_transfer = create_cashback_transfer_transaction(
                            case.application, case.overpaid_amount
                        )
                        cashback_service.process_transfer_reduction_wallet_customer(
                            case.customer, cashback_transfer
                        )

            case.status = decision
            case.save()
            processed_status = OverpaidConsts.Statuses.PROCESSING_SUCCESS
    except CashbackOverpaidVerification.DoesNotExist as e:
        sentry_client.captureException()
        return
    except InvalidOverpaidStatus as e:
        error_message = str(e)
    except Exception as e:
        sentry_client.captureException()
        error_message = str(e)

    OverpaidVerifyingHistory.objects.create(
        agent=agent,
        processed_status=processed_status,
        error_message=error_message,
        agent_note=note,
        decision=decision,
        overpaid_verification=case,
    )


def map_cases_to_images(case_img_map, customer):
    """
    Param: is a dict with keys (overpaid-case ids) & values (image ids)

    This maps cases to images, ignores invalid cases (non PENDING status) if --
    they are in params
    Example params:
        {
            32: 103,
            33: 105,
        }
    """

    valid_statuses = [OverpaidConsts.Statuses.REJECTED, OverpaidConsts.Statuses.UNPROCESSED]
    with transaction.atomic():
        cases = CashbackOverpaidVerification.objects.select_for_update().filter(
            id__in=case_img_map.keys(),
            status__in=valid_statuses,
            overpaid_amount__gt=0,
        )
        for case in cases:
            # map image id + set status to pending
            image = Image.objects.get(pk=case_img_map[case.id])
            case.image = image
            case.status = OverpaidConsts.Statuses.PENDING
            case.save()

            customer.change_wallet_balance(
                change_accruing=-case.overpaid_amount,
                change_available=-case.overpaid_amount,
                reason=CashbackChangeReason.VERIFYING_OVERPAID,
            )


def overpaid_status_sorting_func(case):
    sorting_precedence = (
        case.status != OverpaidConsts.Statuses.PENDING,
        case.status != OverpaidConsts.Statuses.REJECTED,
        case.status,
    )
    return sorting_precedence


def get_pending_overpaid_apps(return_count=False):
    pending_overpaid_apps = CashbackOverpaidVerification.objects.filter(
        status=OverpaidConsts.Statuses.PENDING,
    ).order_by().values_list('application').distinct()
    if return_count:
        return pending_overpaid_apps.count()
    return pending_overpaid_apps


def has_ineligible_overpaid_cases(customer):
    return CashbackOverpaidVerification.objects.\
        get_ineligible_cases().\
        filter(customer=customer).\
        exists()


def create_cashback_transfer_transaction(application, redeem_amount):
    if redeem_amount < CashbackTransferConst.MIN_TRANSFER:
        raise CashbackLessThanMinAmount

    transfer_amount = redeem_amount - CashbackTransferConst.ADMIN_FEE
    bank = BankManager.get_by_name_or_none(application.bank_name)
    partner_transfer = CashbackTransferConst.METHOD_XFERS
    if 'bca' in application.bank_name.lower():
        partner_transfer = CashbackTransferConst.METHOD_BCA
    cashback_transfer = CashbackTransferTransaction.objects.create(
        customer=application.customer,
        application=application,
        transfer_amount=transfer_amount,
        redeem_amount=redeem_amount,
        transfer_status=CashbackTransferConst.STATUS_REQUESTED,
        bank_name=application.bank_name,
        bank_code=bank.bank_code,
        bank_number=application.bank_account_number,
        name_in_bank=application.name_in_bank,
        partner_transfer=partner_transfer,
    )
    return cashback_transfer


def compute_cashback_expiry_date(d):
    # end of year if < October
    # else end of next year

    end_of_year = date(d.year, month=12, day=31)
    end_of_next_year = date(d.year + 1, month=12, day=31)

    # if less than last quarter of year
    if (d.month - 1) // 3 < 3:
        return end_of_year
    else:
        return end_of_next_year


def get_expired_date_and_cashback(customer_id):
    """
        Get next expired_date & the
        total amount of expired cashback up to that date
    """
    total_expired_cashback = 0
    next_expired_date = None
    today = timezone.localtime(timezone.now()).date()

    # this query returns:
    #   (<next_expired_date>,<total_expired_amount>)
    cashback_earned = CashbackEarned.objects.filter(
        customerwallethistory__customer_id=customer_id,
        current_balance__gt=0,
        verified=True,
        expired_on_date__gt=today,
    ).values(
        'expired_on_date'
    ).annotate(
        total_expired_cashback=Sum('current_balance'),
    ).values_list(
        'expired_on_date',
        'total_expired_cashback',
    ).order_by(
        'expired_on_date',
    ).first()

    if cashback_earned:
        next_expired_date, total_expired_cashback = cashback_earned

    return next_expired_date, total_expired_cashback


def update_customer_cashback_balance(customer):
    with transaction.atomic():
        cashback_balance = get_or_create_cashback_balance(customer)

        cashback_before = cashback_balance.cashback_balance
        locked_cashback_balance = CashbackBalance.objects.select_for_update().get(customer=customer)
        locked_cashback_balance.cashback_balance = customer.wallet_balance_available
        locked_cashback_balance.save()

        cashback_after = locked_cashback_balance.cashback_balance

        logger.info({
            'actions': 'customer_cashback_balance_before_after_update',
            'cashback_before': cashback_before,
            'cashback_after': cashback_after,
            'customer': customer
        })
        return cashback_after


def is_cashback_method_active(method_name):
    cashback_feature = FeatureSetting.objects.get(feature_name='cashback')
    parameters = cashback_feature.parameters
    method = parameters[method_name]
    return method['is_active']


def check_overpaid_cashback_verified(cashback_amount):
    return cashback_amount < OverpaidConsts.MINIMUM_AMOUNT


def get_referral_cashback_fs():
    return FeatureSetting.objects.get_or_none(
        feature_name=CashbackFeatureNameConst.CASHBACK_TEMPORARY_FREEZE,
        is_active=True
    )


def get_referral_cashback_action(event_type):
    # Event types for freezing/unfreezing referral cashbacks
    # Event 1: Cashback earned when referee create x220 loan
    # Event 2: Signal from 1st repayment
    # Event 3: Cronjob to run daily

    fs = get_referral_cashback_fs()
    if not fs:
        return ReferralCashbackAction.DO_NOTHING
    try:
        params = fs.parameters
        first_repayment_logic = params['first_repayment_logic']
        period_logic = params['period_logic']

        # Get feature setting parameters to determine action of event
        first_repayment_on = first_repayment_logic['is_active']
        period_logic_on = period_logic['is_active']
        start_date = parse(period_logic['start_date']).date()
        end_date = parse(period_logic['end_date']).date()

        if event_type == ReferralCashbackEventType.CASHBACK_EARNED:
            return get_action_for_cashback_event(
                first_repayment_on, period_logic_on, start_date, end_date
            )
        elif event_type == ReferralCashbackEventType.FIRST_REPAYMENT:
            return get_action_for_repayment_event(
                first_repayment_on, period_logic_on, start_date, end_date
            )
        elif event_type == ReferralCashbackEventType.CRONJOB:
            return get_action_for_cronjob_event(first_repayment_on, period_logic_on)
        else:
            sentry_client.captureMessage("Event type for referral cashback not found!")
            return ReferralCashbackAction.DO_NOTHING
    except Exception:
        sentry_client.captureException()
        return ReferralCashbackAction.DO_NOTHING


def get_action_for_cashback_event(first_repayment_on, period_on, start_date, end_date):
    today = timezone.localtime(timezone.now()).date()
    if not first_repayment_on and not period_on:
        return ReferralCashbackAction.DO_NOTHING
    if first_repayment_on or (period_on and start_date <= today <= end_date):
        return ReferralCashbackAction.FREEZE
    return ReferralCashbackAction.UNFREEZE


def get_action_for_repayment_event(first_repayment_on, period_on, start_date, end_date):
    today = timezone.localtime(timezone.now()).date()
    if not first_repayment_on:
        return ReferralCashbackAction.DO_NOTHING
    if period_on and start_date <= today <= end_date:
        return ReferralCashbackAction.FREEZE
    return ReferralCashbackAction.UNFREEZE


def get_action_for_cronjob_event(first_repayment_on, period_on):
    if not period_on:
        return ReferralCashbackAction.DO_NOTHING
    if first_repayment_on:
        return ReferralCashbackAction.UNFREEZE_FIRST_REPAYMENT
    return ReferralCashbackAction.UNFREEZE


def get_first_referral_wallet_history(benefit_histories, referral_person_type, change_reason):
    benefit_history = benefit_histories.filter(
        referral_person_type=referral_person_type
    ).last()
    if not benefit_history:
        return None

    return CustomerWalletHistory.objects.select_related(
        'customer', 'cashback_earned'
    ).filter(
        customer=benefit_history.customer,
        change_reason=change_reason,
        cashback_earned__verified=False,
        cashback_earned__current_balance=benefit_history.amount
    ).first()


def unfreeze_referrer_and_referree_cashback(referee):
    with transaction.atomic():
        referee_mapping = RefereeMapping.objects.filter(referee=referee).last()
        if not referee_mapping:
            return

        benefit_histories = ReferralBenefitHistory.objects.filter(
            benefit_unit=ReferralBenefitConst.CASHBACK,
            referee_mapping=referee_mapping
        )
        if not benefit_histories:
            return

        moengage_data = []
        referee_history = get_first_referral_wallet_history(
            benefit_histories,
            ReferralPersonTypeConst.REFEREE,
            CashbackChangeReason.PROMO_REFERRAL_FRIEND
        )
        if referee_history:
            cashback_earned = referee_history.cashback_earned
            cashback_earned.update_safely(verified=True)
            update_customer_cashback_balance(referee_history.customer)
            moengage_data.append({
                'customer_id': referee_history.customer.id,
                'cashback_earned': cashback_earned.current_balance,
                'referral_type': ReferralPersonTypeConst.REFEREE
            })

        referrer_history = get_first_referral_wallet_history(
            benefit_histories,
            ReferralPersonTypeConst.REFERRER,
            CashbackChangeReason.PROMO_REFERRAL
        )
        if referrer_history:
            cashback_earned = referrer_history.cashback_earned
            cashback_earned.update_safely(verified=True)
            update_customer_cashback_balance(referrer_history.customer)
            moengage_data.append({
                'customer_id': referrer_history.customer.id,
                'cashback_earned': cashback_earned.current_balance,
                'referral_type': ReferralPersonTypeConst.REFERRER
            })

        trigger_moengage_after_freeze_unfreeze_cashback.delay(
            moengage_data, is_freeze=False
        )


def check_and_inject_cashback_to_customer(customer_id, loan_id, promo_code_string, promo_code_id):
    customer = Customer.objects.get(pk=customer_id)
    loan = Loan.objects.get(pk=loan_id)

    # Check all payments of loan x330
    not_on_time_payments = (
        Payment.objects.by_loan(loan)
        .exclude(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        .exists()
    )

    # Check if user received cashback from this campaign before
    change_reason = 'promo:' + promo_code_string + '_' + str(promo_code_id)
    old_wallet_history = CustomerWalletHistory.objects.filter(
        customer=customer,
        change_reason=change_reason,
    ).exists()

    if not not_on_time_payments and not old_wallet_history:
        last_payment = loan.payment_set.last()
        cashback_amount = last_payment.installment_principal + last_payment.installment_interest
        # Inject cashback
        new_wallet_history = customer.change_wallet_balance(
            change_accruing=cashback_amount,
            change_available=cashback_amount,
            reason=change_reason,
        )
        # Send event to ME
        send_event_moengage_cashback_injection.delay(
            customer_id, loan.id, promo_code_string, new_wallet_history.cashback_earned
        )


def is_valid_overpaid_cases_images(cases_images_map, customer):
    """Check if cases and images in request belong to customer"""
    case_ids, image_ids = cases_images_map.keys(), cases_images_map.values()
    return (
        is_valid_overpaid_cases(case_ids, customer) and
        is_valid_images(image_ids, customer)
    )


def is_valid_overpaid_cases(case_ids, customer):
    requested_overpaid_cases = (
        CashbackOverpaidVerification.objects
        .filter(customer_id=customer.id, id__in=case_ids)
        .count()
    )
    return requested_overpaid_cases == len(case_ids)


def is_valid_images(image_ids, customer):
    application = customer.get_active_application()
    if not application:
        return False

    requested_images = (
        Image.objects
        .filter(image_source=application.id, id__in=image_ids)
        .count()
    )
    return requested_images == len(image_ids)


def determine_cashback_faq_experiment(account, default_feature_setting):
    """
    Returns experiment FAQ feature setting if account is in experiment,
    else returns the default.
    """
    if not account:
        return default_feature_setting

    _, is_experiment = get_cashback_claim_experiment(account=account)
    if not is_experiment:
        return default_feature_setting

    experiment_setting = MobileFeatureSetting.objects.get_or_none(
        feature_name=MobileFeatureNameConst.CASHBACK_CLAIM_FAQS
    )
    return experiment_setting or default_feature_setting

import logging
from typing import Optional, Callable, Tuple
from django.utils import timezone
from juloserver.julocore.python2.utils import py2round

from juloserver.apiv2.models import PdBscoreModelResult
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import (
    display_rupiah,
)
from juloserver.ana_api.models import CustomerSegmentationComms
from juloserver.julo.models import (
    Loan, Customer, Application,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeMessage,
    PromoCodeCriteriaTxnHistory,
)
from juloserver.promo.exceptions import (
    BenefitTypeDoesNotExist,
    NoBenefitForPromoCode,
)
from juloserver.promo.models import (
    CriteriaControlList,
    PromoCodeCriteria,
    PromoHistory,
    PromoCode,
)
from juloserver.promo.services import is_passed_check_application_approved_day, \
    get_times_promo_code_used, get_customer_times_promo_code_used, get_failed_criteria_message
from juloserver.sales_ops.models import SalesOpsAccountSegmentHistory, SalesOpsRMScoring
from juloserver.payment_point.models import TransactionMethod


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def check_promo_code_and_get_message_v2(application, promo_code, loan_amount,
                                        transaction_method_id, loan_duration):
    """
    Return value: (valid, message, failed_criterion) in which:
        - valid: True/False
        - message: for the Android UI -- could be error or success message
        - failed_criterion: The criterion object that failed, or None if valid
    """

    benefit = promo_code.promo_code_benefit
    if not benefit:
        raise NoBenefitForPromoCode

    message = get_benefit_message_v2(promo_code, loan_amount)

    if not message:
        raise BenefitTypeDoesNotExist

    today = timezone.localtime(timezone.now())
    start_date = timezone.localtime(promo_code.start_date)
    end_date = timezone.localtime(promo_code.end_date)
    if start_date > today or end_date < today:
        return False, PromoCodeMessage.ERROR.INVALID

    failed_criterion = check_failed_criteria_v2(
        loan_amount=loan_amount,
        promo_code=promo_code,
        application=application,
        transaction_method_id=transaction_method_id,
        loan_duration=loan_duration,
    )
    if failed_criterion:
        message = get_failed_criteria_message(failed_criterion)

    return failed_criterion, message


def get_benefit_message_v2(promo_code, loan_amount):
    benefit = promo_code.promo_code_benefit
    cashback_message = PromoCodeMessage.BENEFIT.CASHBACK
    message = ""
    handler = PromoCodeHandlerV2(promo_code)

    if benefit.type == PromoCodeBenefitConst.FIXED_CASHBACK:
        amount = handler.get_fixed_benefit_amount()
        message = cashback_message.format(
            amount=display_rupiah(amount),
        )
    elif benefit.type == PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT:
        amount = handler.get_cashback_from_loan_amount_benefit_amount(loan_amount)
        message = cashback_message.format(
            amount=display_rupiah(amount)
        )
    elif benefit.type == PromoCodeBenefitConst.VOUCHER:
        message = promo_code.promo_code
    elif benefit.type == PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT:
        provision_message = PromoCodeMessage.BENEFIT.FIXED_PROVISION_DISCOUNT
        amount = handler.get_fixed_benefit_amount()
        message = provision_message.format(
            amount=display_rupiah(amount),
        )
    elif benefit.type == PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT:
        provision_message = PromoCodeMessage.BENEFIT.PERCENT_PROVISION_DISCOUNT
        percentage, max_amount = handler.get_percentage_provision_discount_benefit()
        max_amount_note = f", up to {display_rupiah(max_amount)}" if max_amount else ""
        message = provision_message.format(
            percentage=percentage,
            max_amount_note=max_amount_note,
        )

    return message


def check_failed_criteria_v2(loan_amount, promo_code, application, transaction_method_id,
                             loan_duration):
    criteria = PromoCodeCriteria.objects.filter(
        id__in=promo_code.criteria,
    )
    customer = application.customer
    failed = None
    for criterion in criteria:
        if criterion.type == PromoCodeCriteriaConst.APPLICATION_PARTNER:
            if application.partner_id not in criterion.value['partners']:
                failed = PromoCodeCriteriaConst.APPLICATION_PARTNER
                break
        elif criterion.type == PromoCodeCriteriaConst.CREDIT_SCORE:
            score, _ = application.credit_score
            if score not in criterion.value['credit_scores']:
                failed = PromoCodeCriteriaConst.CREDIT_SCORE
                break
        elif criterion.type == PromoCodeCriteriaConst.PRODUCT_LINE:
            if application.product_line_code not in criterion.value['product_line_codes']:
                failed = PromoCodeCriteriaConst.PRODUCT_LINE
                break
        elif criterion.type == PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER:
            times_code_used = get_customer_times_promo_code_used(promo_code, criterion, customer)
            if times_code_used >= criterion.value['limit']:
                failed = PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER
                break
        elif criterion.type == PromoCodeCriteriaConst.TRANSACTION_METHOD:
            if transaction_method_id not in criterion.value['transaction_method_ids']:
                failed = PromoCodeCriteriaConst.TRANSACTION_METHOD
                break
            transaction_history = criterion.value.get('transaction_history')
            if transaction_history:
                is_exists_txn = Loan.objects.filter(
                    account=application.account,
                    loan_status__gte=LoanStatusCodes.CURRENT,
                    transaction_method_id=transaction_method_id
                ).exists()
                if transaction_history == PromoCodeCriteriaTxnHistory.NEVER and \
                        is_exists_txn:
                    failed = PromoCodeCriteriaConst.TRANSACTION_METHOD
                    break
                if transaction_history == PromoCodeCriteriaTxnHistory.EVER and \
                        not is_exists_txn:
                    failed = PromoCodeCriteriaConst.TRANSACTION_METHOD
                    break

        elif criterion.type == PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT:
            if loan_amount < criterion.value['minimum_loan_amount']:
                failed = PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT
                break
        elif criterion.type == PromoCodeCriteriaConst.R_SCORE:
            account_id = application.account_id
            account_segment_history = SalesOpsAccountSegmentHistory.objects.filter(
                account_id=account_id
            ).last()
            r_score = None
            if account_segment_history:
                r_score = SalesOpsRMScoring.objects.filter(
                    id=account_segment_history.r_score_id
                ).last()
            if not r_score or r_score.score not in criterion.value['r_scores']:
                failed = PromoCodeCriteriaConst.R_SCORE
                break
        elif criterion.type == PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE:
            times_code_used = get_times_promo_code_used(promo_code, criterion)
            if times_code_used >= criterion.value['limit_per_promo_code']:
                failed = PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE
                break
        elif criterion.type == PromoCodeCriteriaConst.MINIMUM_TENOR:
            if loan_duration < criterion.value['minimum_tenor']:
                failed = PromoCodeCriteriaConst.MINIMUM_TENOR
                break
        elif criterion.type == PromoCodeCriteriaConst.WHITELIST_CUSTOMERS:
            is_in_whitelist = CriteriaControlList.objects.filter(
                customer_id=application.customer_id,
                promo_code_criteria_id=criterion.id,
                is_deleted=False
            ).exists()
            if not is_in_whitelist:
                failed = PromoCodeCriteriaConst.WHITELIST_CUSTOMERS
                break
        elif criterion.type == PromoCodeCriteriaConst.CHURN_DAY:
            cust_seg_comms = CustomerSegmentationComms.objects.filter(
                customer_id=application.customer_id
            ).last()
            if not (cust_seg_comms and cust_seg_comms.extra_params.get('churn_day')):
                failed = PromoCodeCriteriaConst.CHURN_DAY
                break

            cust_seg_comms_churn_day = cust_seg_comms.extra_params['churn_day']
            min_churn_day = criterion.value['min_churn_day']
            max_churn_day = criterion.value['max_churn_day']
            if not (min_churn_day <= cust_seg_comms_churn_day <= max_churn_day):
                failed = PromoCodeCriteriaConst.CHURN_DAY
                break
        elif criterion.type == PromoCodeCriteriaConst.APPLICATION_APPROVED_DAY:
            if not is_passed_check_application_approved_day(criterion, application):
                failed = PromoCodeCriteriaConst.APPLICATION_APPROVED_DAY
                break
        elif criterion.type == PromoCodeCriteriaConst.B_SCORE:
            b_score_customer = PdBscoreModelResult.objects.filter(
                customer_id=customer.id
            ).last()
            if not b_score_customer or b_score_customer.pgood < criterion.value['b_score']:
                failed = PromoCodeCriteriaConst.B_SCORE
                break

    return criterion if failed else None


def get_apply_promo_code_benefit_handler_v2(promo_code):
    """
        Only supports V2 promo code version.
    """
    promo_code_benefit = promo_code.promo_code_benefit
    if promo_code_benefit.type not in PromoCodeBenefitConst.PROMO_CODE_BENEFIT_TYPE_V2_SUPPORT:
        raise Exception(
            "Apply Promo code handler is only defined for V2.",
            {
                'promo_code_id': promo_code.id,
                'promo_code_benefit_id': promo_code.promo_code_benefit.id,
                'benefit_type': promo_code.promo_code_benefit.type,
            }
        )

    promo_code_handler = PromoCodeHandlerV2(promo_code=promo_code)
    handler_map = {
        PromoCodeBenefitConst.FIXED_CASHBACK:
            promo_code_handler.apply_fixed_cashback_benefit,
        PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT:
            promo_code_handler.apply_cashback_from_loan_amount_benefit,
        PromoCodeBenefitConst.VOUCHER:
            promo_code_handler.apply_voucher_benefit,
        PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT:
            promo_code_handler.apply_provision_discount_benefit,
        PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT:
            promo_code_handler.apply_provision_discount_benefit,
    }

    handler = handler_map.get(promo_code_benefit.type)
    if not handler:
        raise Exception("Apply Promo code handler is not defined.", {
            'promo_code_id': promo_code.id,
            'promo_code_benefit_id': promo_code_benefit.id,
            'benefit_type': promo_code_benefit.type
        })

    return handler


class PromoCodeHandlerV2:
    def __init__(self, promo_code):
        self.promo_code = promo_code
        self.promo_code_benefit = self.promo_code.promo_code_benefit

    @property
    def promo_type(self):
        strings = [
            'promo_code',
            self.promo_code.code
        ]
        return ':'.join(strings)

    def get_fixed_benefit_amount(self, **kwargs):
        return self.promo_code_benefit.get_value('amount', to_type=int)

    def get_percentage_provision_discount_benefit(self, **kwargs):
        percentage = self.promo_code_benefit.get_value('percentage_provision_rate_discount', to_type=float)
        # Handle for max amount is None
        max_amount_raw = self.promo_code_benefit.get_value('max_amount')
        max_amount = int(max_amount_raw) if max_amount_raw is not None else None
        return percentage, max_amount

    def get_cashback_from_loan_amount_benefit_amount(self, loan_amount, **kwargs):
        cashback_percentage = self.promo_code_benefit.get_value('percent', to_type=int)
        max_cashback = self.promo_code_benefit.get_value('max_cashback', to_type=int)

        # Round to 100,
        # 201 - 249 -> 200
        # 250 - 299 -> 300
        cashback_amount = int(round(loan_amount * cashback_percentage/100, -2))

        return cashback_amount if cashback_amount < max_cashback else max_cashback

    def apply_fixed_cashback_benefit(self, promo_code_usage):
        # Calculate the cashback amount
        total_cashback = self.get_fixed_benefit_amount()

        # Apply the benefit
        self._apply_cashback_benefit(total_cashback, promo_code_usage)

    def _apply_cashback_benefit(self, total_cashback, promo_code_usage):
        self._apply_promo_code_usage(promo_code_usage, total_cashback)

        customer = Customer.objects.get(id=promo_code_usage.customer_id)
        loan = Loan.objects.get(id=promo_code_usage.loan_id)
        customer.change_wallet_balance(
            change_accruing=total_cashback,
            change_available=total_cashback,
            reason=self.promo_type,
            loan=loan,
        )
        PromoHistory.objects.create(
            customer_id=promo_code_usage.customer_id,
            loan_id=promo_code_usage.loan_id,
            account_id=loan.account_id,
            promo_type=self.promo_type,
        )

    def _apply_promo_code_usage(self, promo_code_usage, benefit_amount):
        promo_code_usage.benefit_amount = benefit_amount
        promo_code_usage.applied_at = timezone.localtime(timezone.now())
        promo_code_usage.cancelled_at = None

        promo_code_benefit = self.promo_code.promo_code_benefit
        promo_code_usage.promo_code_benefit_id = promo_code_benefit.id
        promo_code_usage.configuration_log = {
            'promo_code_benefit': {
                'id': promo_code_benefit.id,
                'type': promo_code_benefit.type,
                'value': promo_code_benefit.value,
            }
        }
        promo_code_usage.save(update_fields=[
            'benefit_amount', 'applied_at', 'cancelled_at', 'promo_code_benefit_id',
            'configuration_log'
        ])

    def apply_cashback_from_loan_amount_benefit(self, promo_code_usage):
        # Calculate the cashback amount
        loan = Loan.objects.get(id=promo_code_usage.loan_id)
        total_cashback = self.get_cashback_from_loan_amount_benefit_amount(loan.loan_amount)
        # Apply the benefit
        self._apply_cashback_benefit(total_cashback, promo_code_usage)

    def apply_voucher_benefit(self, promo_code_usage):
        self._apply_promo_code_usage(promo_code_usage, 0)
    
    def apply_provision_discount_benefit(self, loan_amount: int, provision_rate: float) -> Tuple[int, int]:
        benefit_type = self.promo_code.promo_code_benefit.type

        if benefit_type == PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT:
            return self._calculate_fixed_provision_discount(loan_amount, provision_rate)
        elif benefit_type == PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT:
            return self._calculate_percent_provision_discount(loan_amount, provision_rate)

    def _calculate_fixed_provision_discount(self, loan_amount: int, provision_rate: float) -> Tuple[int, int]:
        """
        Returns:
            tuple[int, int]: A tuple containing (discount_amount, adjusted_provision_fee_amount)
        Example: provision_discount_amount from config = 20_000
                 original_provision_fee_amount = 10_000
            ==> Expected return: (discount_amount, adjust_provision_fee_amount) = (10_000, 0)
        """
        provision_discount_amount = self.get_fixed_benefit_amount()
        original_provision_fee_amount = int(py2round(loan_amount * (provision_rate or 0)))
        adjusted_provision_fee_amount = max(original_provision_fee_amount - provision_discount_amount, 0)
        discount_applied = original_provision_fee_amount - adjusted_provision_fee_amount

        return discount_applied, adjusted_provision_fee_amount

    def _calculate_percent_provision_discount(self, loan_amount: int, provision_rate: float) -> Tuple[int, int]:
        """
        Returns:
            tuple[int, int]: A tuple containing (discount_amount, adjusted_provision_fee_amount)
        Example: rate_discount = 0.03, original_rate = 0.08 --> adjusted_provision_rate = 0.05
                max_discount_amount = 20_000
                loan_amount = 1_000_000
        Expected return: (discount_amount, adjust_provision_fee_amount) = (20_000, 60_000)
        """
        original_provision_fee_amount = int(py2round(loan_amount * (provision_rate or 0)))
        rate_discount, max_provision_discount_amount = self.get_percentage_provision_discount_benefit()

        # Ensure the provision fee cannot be negative
        adjusted_provision_rate = max(provision_rate - rate_discount, 0)

        adjusted_provision_fee_amount = int(py2round(loan_amount * adjusted_provision_rate))

        if max_provision_discount_amount is None:
            discount_applied = original_provision_fee_amount - adjusted_provision_fee_amount
        else:
            discount_applied = min(
                original_provision_fee_amount - adjusted_provision_fee_amount,
                max_provision_discount_amount
            )

        adjusted_provision_fee_amount = original_provision_fee_amount - discount_applied

        return discount_applied, adjusted_provision_fee_amount


def get_promo_code_super_type(promo_code):
    benefit_type = promo_code.promo_code_benefit.type
    CASHBACK_TYPES = [
        PromoCodeBenefitConst.FIXED_CASHBACK,
        PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
    ]
    if benefit_type in CASHBACK_TYPES:
        return 'cashback'
    return benefit_type

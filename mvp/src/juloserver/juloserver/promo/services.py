import json
import logging
from functools import cmp_to_key

from django.conf import settings
from django.db.models import F, Q
from datetime import datetime, timedelta
from django.db import transaction
from django.utils import timezone

from juloserver.apiv2.models import PdBscoreModelResult
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import (
    display_rupiah,
    execute_after_transaction_safely
)
from juloserver.ana_api.models import CustomerSegmentationComms
from juloserver.account.constants import AccountConstant
from juloserver.julo.models import (
    Loan,
    PaymentEvent,
    PaymentNote,
    FeatureSetting,
    Customer,
    ApplicationHistory,
    Application,
)
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from juloserver.promo.clients.promo_cms import PromoCMSClient
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeMessage,
    PromoCodeTypeConst,
    PromoPageConst,
    PromoCodeCriteriaTxnHistory,
    FeatureNameConst,
    PromoCMSRedisConstant,
    PromoCMSCategory,
    PromoCodeTimeConst,
    DEFAULT_DATETIME_FORMAT,
    EXPIRE_PROMO_CMS_SEARCH_EXPIRY_DAYS_DEFAULT,
    PromoCodeVersion,
)
from juloserver.promo.exceptions import (
    BenefitTypeDoesNotExist,
    NoBenefitForPromoCode,
    NoPromoPageFound,
    PromoCodeException,
    PromoCodeBenefitTypeNotSupport,
)
from juloserver.promo.models import (
    CriteriaControlList,
    PromoHistory,
    PromoCodeCriteria,
    PromoCodeUsage,
    PromoCode,
    PromoPage,
    WaivePromo,
)
from django.template.loader import render_to_string
from juloserver.account.models import (
    AccountTransaction,
)
from juloserver.account_payment.models import (
    AccountPayment,
)
from juloserver.sales_ops.models import SalesOpsAccountSegmentHistory, SalesOpsRMScoring
from juloserver.moengage.services.use_cases import (
    send_event_for_active_loan_to_moengage
)
from juloserver.moengage.constants import MoengageEventType
from rest_framework import exceptions
from juloserver.promo.tasks import fetch_promo_cms
from juloserver.promo.utils import chunker_list

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def get_promo_cms_client():
    return PromoCMSClient(
        base_url=settings.CMS_BASE_URL
    )


def amount_from_percent(percent, amount, max_amount=None):
    # return INT
    result = int((amount * percent) / 100)
    if not max_amount:
        return result
    else:
        return max_amount if result > max_amount else result


def get_existing_promo_code(promo_code_string):
    """
    Type loan
    """
    result = PromoCode.objects.filter(
        promo_code__iexact=promo_code_string.strip(),
        type=PromoCodeTypeConst.LOAN,
        is_active=True,
    ).last()

    return result


def check_promo_code_and_get_message(promo_code, loan):
    """
    Return value: (valid, message) in which:
        - valid: True/False,
        - message: for the Android UI -- could be error or sucess message

    """
    is_valid, message = True, ""

    application = loan.customer.application_set.regular_not_deletes().last()
    benefit = promo_code.promo_code_benefit
    if not benefit:
        raise NoBenefitForPromoCode

    message = get_benefit_message(promo_code, loan)

    if not message:
        return False, PromoCodeMessage.ERROR.PROMO_CODE_BENEFIT_NOT_SUPPORT

    # some initial checks:
    today = timezone.localtime(timezone.now())
    start_date = timezone.localtime(promo_code.start_date)
    end_date = timezone.localtime(promo_code.end_date)
    if (start_date > today or end_date < today):
        return False, PromoCodeMessage.ERROR.INVALID

    # check against criteria
    failed_criterion = check_failed_criteria(
        loan=loan,
        promo_code=promo_code,
        application=application,
    )
    if failed_criterion:
        is_valid = False
        message = get_failed_criteria_message(failed_criterion)

    return is_valid, message


def get_benefit_message(promo_code, loan):
    benefit = promo_code.promo_code_benefit
    cashback_message = PromoCodeMessage.BENEFIT.CASHBACK
    message = ""
    handler = PromoCodeHandler(promo_code)

    if benefit.type == PromoCodeBenefitConst.FIXED_CASHBACK:
        amount = handler.get_fixed_cashback_benefit_amount()
        message = cashback_message.format(
            amount=display_rupiah(amount),
        )
    elif benefit.type == PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT:
        amount = handler.get_cashback_from_loan_amount_benefit_amount(loan)
        message = cashback_message.format(
            amount=display_rupiah(amount)
        )
    elif benefit.type == PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT:
        amount = handler.get_cashback_from_installment_benefit_amount(loan)
        message = cashback_message.format(
            amount=display_rupiah(amount)
        )
    elif benefit.type == PromoCodeBenefitConst.INSTALLMENT_DISCOUNT:
        amount = handler.get_total_installment_principal_discount_benefit(loan)
        message = PromoCodeMessage.BENEFIT.INSTALLMENT_DISCOUNT.format(
            amount=display_rupiah(amount)
        )
    elif benefit.type == PromoCodeBenefitConst.INTEREST_DISCOUNT:
        amount = handler.get_total_interest_discount_benefit(loan)
        message = PromoCodeMessage.BENEFIT.INTEREST_DISCOUNT.format(
            amount=display_rupiah(amount)
        )
    elif benefit.type == PromoCodeBenefitConst.VOUCHER:
        message = promo_code.promo_code

    return message


def check_failed_criteria(loan, promo_code, application=None):
    from juloserver.promo.services_v3 import check_failed_criteria_v2
    # return first fail criterion constants
    if not application:
        application = loan.customer.application_set.regular_not_deletes().last()

    return check_failed_criteria_v2(
        loan_amount=loan.loan_amount,
        promo_code=promo_code,
        application=application,
        transaction_method_id=loan.transaction_method_id,
        loan_duration=loan.loan_duration,
    )


def get_customer_times_promo_code_used(promo_code, criterion, customer):
    filter_kwargs = {
        'cancelled_at__isnull': True,
        'promo_code': promo_code,
        'customer_id': customer.id,
    }
    # If criterion value_times is None, will treat it as all_time
    if criterion.value.get('times') == PromoCodeTimeConst.DAILY:
        today = timezone.localtime(timezone.now()).date()
        filter_kwargs['cdate__date'] = today

    return PromoCodeUsage.objects.filter(**filter_kwargs).count()


def get_times_promo_code_used(promo_code, criterion):
    # If criterion value_times is None, will treat it as all_time
    if criterion.value.get('times') == PromoCodeTimeConst.DAILY:
        return promo_code.promo_code_daily_usage_count
    else:
        return promo_code.promo_code_usage_count


def get_failed_criteria_message(criteria):
    """
    returns the message for a failed criterion for promo code
    """
    result = PromoCodeMessage.ERROR.INVALID
    criterion_const = criteria.type
    if criterion_const == PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER:
        result = PromoCodeMessage.ERROR.USED
    elif criterion_const == PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT:
        result = PromoCodeMessage.ERROR.MINIMUM_LOAN_AMOUNT.format(
            minimum_amount=display_rupiah(criteria.value['minimum_loan_amount'])
        )
    elif criterion_const == PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE:
        result = PromoCodeMessage.ERROR.LIMIT_PER_PROMO_CODE
    elif criterion_const == PromoCodeCriteriaConst.MINIMUM_TENOR:
        minimum_tenor = str(criteria.value['minimum_tenor']) if criteria else ''
        result = PromoCodeMessage.ERROR.MINIMUM_TENOR.format(minimum_tenor=minimum_tenor)
    elif criterion_const == PromoCodeCriteriaConst.WHITELIST_CUSTOMERS:
        result = PromoCodeMessage.ERROR.WHITELIST_CUSTOMER
    elif criterion_const == PromoCodeCriteriaConst.CHURN_DAY:
        result = PromoCodeMessage.ERROR.CHURN_DAY
    elif criterion_const == PromoCodeCriteriaConst.APPLICATION_APPROVED_DAY:
        result = PromoCodeMessage.ERROR.APPLICATION_APPROVED_DAY
    elif criterion_const == PromoCodeCriteriaConst.B_SCORE:
        result = PromoCodeMessage.ERROR.INVALID_B_SCORE

    return result


def create_promo_code_usage(loan, promo_code, version=None):
    customer = loan.customer
    application = customer.application_set.regular_not_deletes().last()
    benefit = promo_code.promo_code_benefit

    if not benefit:
        raise NoBenefitForPromoCode

    return PromoCodeUsage.objects.create(
        promo_code=promo_code,
        loan_id=loan.id,
        customer_id=customer.id,
        application_id=application.id,
        promo_code_benefit_id=benefit.id,
        version=version,
    )


def return_promo_code_usage_count(loan):
    promo_code_usage = get_promo_code_usage(loan)
    now = timezone.localtime(timezone.now())

    if promo_code_usage:
        promo_code_usage.cancelled_at = now
        promo_code = promo_code_usage.promo_code

        # Return back the daily usage count if loan disbursement failed in the same day
        if promo_code_usage.cdate.date() == now.date():
            promo_code.promo_code_daily_usage_count -= 1
        promo_code.promo_code_usage_count -= 1
        promo_code.save()
        promo_code_usage.save()


def get_promo_code_usage(loan):
    promo_code_usage = PromoCodeUsage.objects.filter(
        loan_id=loan.id,
        cancelled_at__isnull=True,
        applied_at__isnull=True,
    ).last()

    return promo_code_usage


def get_promo_code_usage_on_loan_details(loan):
    promo_code_usage = PromoCodeUsage.objects.filter(loan_id=loan.id).last()
    if not promo_code_usage:
        return

    configuration_log = promo_code_usage.configuration_log
    if not configuration_log:
        return '{}, {}'.format(
            promo_code_usage.promo_code.promo_code,
            display_rupiah(promo_code_usage.benefit_amount)
        )

    return '{}, {}, {}'.format(
        promo_code_usage.promo_code.promo_code,
        promo_code_usage.configuration_log['promo_code_benefit']['type'],
        display_rupiah(promo_code_usage.benefit_amount)
    )


def check_and_apply_promo_code_benefit(loan):
    if not loan.is_active:
        raise Exception(
            "Cannot applied promo code because the loan is not active",
            {
                'loan_id': loan.id,
                'loan_status': loan.loan_status_id,
            }
        )

    promo_code_usage = get_promo_code_usage(loan)

    if not promo_code_usage:
        return

    apply_benefit_service_handler = get_apply_promo_code_benefit_handler(
        promo_code_usage=promo_code_usage
    )
    execute_after_transaction_safely(
        lambda: send_event_for_active_loan_to_moengage.delay(
            loan.id,
            loan.status,
            MoengageEventType.PROMO_CODE_USAGE
        )
    )
    if apply_benefit_service_handler:
        apply_benefit_service_handler(promo_code_usage=promo_code_usage)


def get_apply_promo_code_benefit_handler(promo_code_usage):
    """
        Only supports V1 promo code version for now.
        Applies promo code v2 only for cashback benefits when loans reach x220.
        Does not raise an exception if no handler is found — 
            other V2 promo types (e.g., provision, interest) are handled elsewhere 
            and should not reapply benefits here.
    """
    from juloserver.promo.services_v3 import PromoCodeHandlerV2
    promo_code = promo_code_usage.promo_code
    if promo_code_usage.version == PromoCodeVersion.V2:
        promo_code_handler = PromoCodeHandlerV2(promo_code=promo_code)
        handler_map = {
            PromoCodeBenefitConst.FIXED_CASHBACK:
                promo_code_handler.apply_fixed_cashback_benefit,
            PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT:
                promo_code_handler.apply_cashback_from_loan_amount_benefit,
            PromoCodeBenefitConst.VOUCHER:
                promo_code_handler.apply_voucher_benefit,
        }
    else:
        promo_code_handler = PromoCodeHandler(promo_code=promo_code)
        handler_map = {
            PromoCodeBenefitConst.FIXED_CASHBACK:
                promo_code_handler.apply_fixed_cashback_benefit,
            PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT:
                promo_code_handler.apply_cashback_from_loan_amount_benefit,
            PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT:
                promo_code_handler.apply_cashback_from_installment_benefit,
            PromoCodeBenefitConst.INSTALLMENT_DISCOUNT:
                promo_code_handler.apply_installment_discount_benefit,
            PromoCodeBenefitConst.INTEREST_DISCOUNT:
                promo_code_handler.apply_interest_discount_benefit,
            PromoCodeBenefitConst.VOUCHER:
                promo_code_handler.apply_voucher_benefit,
        }

    promo_code_benefit = promo_code.promo_code_benefit
    handler = handler_map.get(promo_code_benefit.type)

    return handler


def get_used_promo_code_for_loan(loan):
    promo_code_usage = PromoCodeUsage.objects.filter(
        loan_id=loan.id,
        cancelled_at__isnull=True,
        applied_at__isnull=False,
    ).last()

    return promo_code_usage

def get_interest_discount_promo_code_benifit_applied(loan):
    promo_code_usage = get_used_promo_code_for_loan(loan)
    if promo_code_usage:
        promo_code_benifit = promo_code_usage.promo_code_benefit
        if promo_code_benifit.type == PromoCodeBenefitConst.INTEREST_DISCOUNT:
            return promo_code_benifit

    return None

def get_interest_discount_on_promocode(payment_installment_interest, promo_code_benefit):
    discount_percentage = promo_code_benefit.get_value('percent', to_type=float)
    interest_discount_amount = round(payment_installment_interest * discount_percentage/100, 2)

    return interest_discount_amount

class PromoCodeHandler:
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

    def get_fixed_cashback_benefit_amount(self, **kwargs):
        return self.promo_code_benefit.get_value('amount', to_type=int)

    def apply_fixed_cashback_benefit(self, promo_code_usage):
        # Calculate the cashback amount
        total_cashback = self.get_fixed_cashback_benefit_amount()

        # Apply the benefit
        self._apply_cashback_benefit(total_cashback, promo_code_usage)

    def get_cashback_from_loan_amount_benefit_amount(self, loan, **kwargs):
        cashback_percentage = self.promo_code_benefit.get_value('percent', to_type=int)
        max_cashback = self.promo_code_benefit.get_value('max_cashback', to_type=int)

        loan_amount = loan.loan_amount
        # Round to 100,
        # 201 - 249 -> 200
        # 250 - 299 -> 300
        cashback_amount = int(round(loan_amount * cashback_percentage/100, -2))

        return cashback_amount if cashback_amount < max_cashback else max_cashback

    def apply_cashback_from_loan_amount_benefit(self, promo_code_usage):
        # Calculate the cashback amount
        loan = Loan.objects.get(id=promo_code_usage.loan_id)
        total_cashback = self.get_cashback_from_loan_amount_benefit_amount(
            loan=loan
        )

        # Apply the benefit
        self._apply_cashback_benefit(total_cashback, promo_code_usage)

    def get_cashback_from_installment_benefit_amount(self, loan, **kwargs):
        cashback_percentage = self.promo_code_benefit.get_value('percent', to_type=int)
        max_cashback = self.promo_code_benefit.get_value('max_cashback', to_type=int)
        first_payment = loan.payment_set.get(payment_number=1)
        installment_principal = first_payment.installment_principal
        cashback_amount = round(installment_principal * cashback_percentage/100, -2)

        return min(int(cashback_amount), max_cashback)

    def apply_cashback_from_installment_benefit(self, promo_code_usage):
        # Calculate the cashback amount
        loan = Loan.objects.get(id=promo_code_usage.loan_id)
        total_cashback = self.get_cashback_from_installment_benefit_amount(
            loan=loan
        )

        # Apply the benefit
        self._apply_cashback_benefit(total_cashback, promo_code_usage)

    def apply_installment_discount_benefit(self, promo_code_usage):
        raise NotImplementedError("Not implemented yet.")

    def _get_and_process_interest_discount_benefit(self, loan,  **kwargs):
        duration = self.promo_code_benefit.get_value('duration', to_type=int)
        discount_percentage = self.promo_code_benefit.get_value('percent', to_type=float)
        max_amount_per_payment = self.promo_code_benefit.value.get('max_amount')
        promo_details = 'PROMO_CODE_' +\
                         self.promo_code.promo_code + '_' + str(self.promo_code.promo_code_benefit_id)

        total_benefit, _ = process_interest_discount_benefit(
            loan=loan,
            duration=duration,
            discount_percentage=discount_percentage,
            max_amount_per_payment=max_amount_per_payment,
            promo_code=None,
            note_details=promo_details
        )

        return total_benefit

    def apply_interest_discount_benefit(self, promo_code_usage):
        from juloserver.loan.tasks.sphp import upload_sphp_to_oss

        loan = Loan.objects.get(id=promo_code_usage.loan_id)
        # get the promocode benefit
        total_benefit = self._get_and_process_interest_discount_benefit(loan)

        self._apply_promo_code_usage(promo_code_usage, total_benefit)

        PromoHistory.objects.create(
            customer_id=promo_code_usage.customer_id,
            loan_id=promo_code_usage.loan_id,
            account_id=loan.account_id,
            promo_type=self.promo_type,
        )
        # Rewrite sphp
        upload_sphp_to_oss.apply_async((promo_code_usage.loan_id,), countdown=30)

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

    def apply_voucher_benefit(self, promo_code_usage):
        self._apply_promo_code_usage(promo_code_usage, 0)

    def get_total_installment_principal_discount_benefit(self, loan):
        discount_percentage = self.promo_code_benefit.get_value('percent', to_type=float)
        max_amount_per_payment = self.promo_code_benefit.value.get('max_amount')

        payment = loan.payment_set.get(payment_number=1)
        discount_amount = round(payment.installment_principal * discount_percentage/100, 2)
        discount_amount = min(discount_amount, int(max_amount_per_payment)) \
            if max_amount_per_payment else discount_amount

        return int(round(discount_amount, -2))

    def get_total_interest_discount_benefit(self, loan):
        duration = self.promo_code_benefit.get_value('duration', to_type=int)
        discount_percentage = self.promo_code_benefit.get_value('percent', to_type=float)
        max_amount_per_payment = self.promo_code_benefit.value.get('max_amount')

        payments = loan.payment_set.all().order_by('id')[:duration]
        total_discount = 0
        for payment in payments:
            discount_amount = round(payment.installment_interest * discount_percentage/100, 2)
            total_discount += min(discount_amount, int(max_amount_per_payment)) \
                if max_amount_per_payment else discount_amount

        return int(round(total_discount, -2))


def check_and_apply_application_promo_code(loan):
    """
    Method to process promo code that is entered in the registration form.
    The promo code is stored in application.referral_code field.

    - Should not be updated anymore
    - if needed, should modify the logic based using PromoCodeService
    - Discuss with wico.chandra@julofinance.com
    """
    today = timezone.now()
    application = loan.account.last_application
    account = loan.account

    if account.status.status_code != AccountConstant.STATUS_CODE.active:
        return False

    # To reduce the number of queries, we are checking if there is referral_code
    if not application.referral_code:
        return False

    promo_active = PromoCode.objects.filter(
        promo_code__iexact=application.referral_code, is_active=True, start_date__lte=today,
        end_date__gte=today, type=PromoCodeTypeConst.APPLICATION,
    ).first()

    if not promo_active:
        return False

    is_ever_apply_loan = Loan.objects.filter(
        account=account,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
        loan_status_id__lte=LoanStatusCodes.PAID_OFF,
    ).exclude(pk=loan.id)

    if is_ever_apply_loan:
        return False

    if not promo_active.partner and not promo_active.product_line and \
            not promo_active.credit_score:
        return False

    if promo_active.credit_score and 'All' not in promo_active.credit_score \
            and not (application.creditscore.score in promo_active.credit_score):
        return False

    if promo_active.product_line and 'All' not in promo_active.product_line \
            and not (str(int(application.product_line_code)) in promo_active.product_line):
        return False

    if promo_active.partner and 'All' not in promo_active.partner \
            and not (application.partner_name in promo_active.partner):
        return False

    if promo_active.promo_benefit == 'cashback':
        application.customer.change_wallet_balance(
            change_accruing=0,
            change_available=promo_active.cashback_amount,
            reason='cashback_promo'
        )
        payment = loan.payment_set.last()
        PromoHistory.objects.create(
            customer=account.customer, loan=loan, promo_type=promo_active.promo_name,
            payment=payment, account=account
        )
        return True
    elif promo_active.promo_benefit == '0% INTEREST':
        remaining_installment_interest = 0
        payment = loan.payment_set.order_by('payment_number').first()
        payment.due_amount = payment.installment_principal
        payment.paid_amount = payment.installment_interest
        payment.paid_date = today
        payment.save()

        promo_name = 'promo_{}'.format(promo_active.promo_name)

        WaivePromo.objects.create(
            loan=loan, payment=payment,
            remaining_installment_principal=payment.installment_principal,
            remaining_installment_interest=remaining_installment_interest,
            remaining_late_fee=0, promo_event_type=promo_name
        )
        return True

    return False


# terms and conditions
def get_promo_code_benefit_tnc(promo_code):
    benefit_type = promo_code.promo_code_benefit.type
    if benefit_type == PromoCodeBenefitConst.INSTALLMENT_DISCOUNT:
        title = PromoPageConst.TNC_INSTALLMENT_DISCOUNT
    else:
        title = PromoPageConst.TNC_CASHBACK

    page = PromoPage.objects.filter(
        title=title,
        is_active=True,
    ).last()
    if not page:
        raise NoPromoPageFound

    start_date = timezone.localtime(promo_code.start_date).date().\
        strftime("%d-%m-%Y")
    end_date = timezone.localtime(promo_code.end_date).date().\
        strftime("%d-%m-%Y")
    format = {
        'start_date': start_date,
        'end_date': end_date,
    }
    page.content = page.content.format(**format)
    return render_to_string(
        template_name='promo/benefit_tnc.html',
        context={'page': page},
    )


def check_if_loan_has_promo_benefit_type(loan, benefit_type):
    # for promo that is applied & has benefit attached
    promo_usage = get_used_promo_code_for_loan(loan)
    if promo_usage and promo_usage.promo_code_benefit_id:
        current_benefit = promo_usage.promo_code_benefit.type
        return benefit_type == current_benefit

    return False


def process_interest_discount_benefit(
        loan, duration, discount_percentage, max_amount_per_payment, promo_code, note_details):
    total_benefit = 0

    with transaction.atomic():
        payments = loan.payment_set.select_for_update().order_by('payment_number')[:duration]
        payment_events, payment_notes = [], []
        event_type = 'waive_interest'
        local_time = timezone.localtime(timezone.now())
        for payment in payments:
            interest_discount_amount = round(payment.installment_interest * discount_percentage/100)
            interest_discount_amount = min(interest_discount_amount, max_amount_per_payment) if max_amount_per_payment else interest_discount_amount

            payment_note = '[Add Event Promocode Waive %s]\n\
                amount: %s,\n\
                date: %s,\n\
                note: %s.' % (event_type,
                display_rupiah(interest_discount_amount),
                local_time.date().strftime('%d-%m-%Y'),
                note_details
            )
            payment_event = PaymentEvent(
                payment=payment,
                event_payment=interest_discount_amount,
                event_due_amount=payment.due_amount,
                event_type=event_type,
                payment_receipt=note_details,
                payment_method=None,
                can_reverse=False,
                event_date=local_time.date(),
            )
            payment_events.append(payment_event)

            payment.update_safely(
                due_amount=F('due_amount') - interest_discount_amount,
                paid_interest=F('paid_interest') + interest_discount_amount,
                paid_amount=F('paid_amount') + interest_discount_amount
            )

            payment_notes.append(PaymentNote(note_text=payment_note, payment=payment))

            total_benefit += interest_discount_amount

        account_trx = AccountTransaction.objects.create(
            account=loan.account,
            payback_transaction=None,
            transaction_amount=total_benefit,
            transaction_type=event_type,
            towards_interest=total_benefit,
            transaction_date=local_time ,
            accounting_date=local_time.date()
        )

        for payment_event in payment_events:
            payment_event.account_transaction = account_trx

        PaymentEvent.objects.bulk_create(payment_events)
        PaymentNote.objects.bulk_create(payment_notes)

        log_info = {
            'action': '_get_and_process_interest_discount_benefit',
            'account_trx_id': account_trx.id,
            'loan': loan.id,
            'total_interest_discount': total_benefit,
            'message': 'apply_interest_discount_benefit'
        }
        if promo_code:
            log_info['promo_code'] = promo_code
        logger.info(log_info)

    return total_benefit, payment_events


class PromoCodeService:
    def __init__(self, promo_code_str, version=PromoCodeVersion.V1) -> None:
        self.version = version
        if isinstance(promo_code_str, str):
            self.promo_code_qs = PromoCode.objects.filter(
                promo_code__iexact=promo_code_str.strip(),
                type=PromoCodeTypeConst.LOAN,
                is_active=True
            )

        if not self.promo_code_qs:
            raise exceptions.NotFound('No promo code found')

        if self.version == PromoCodeVersion.V2:
            promo = self.promo_code_qs.last()
            if (promo.promo_code_benefit.type not in
                    PromoCodeBenefitConst.PROMO_CODE_BENEFIT_TYPE_V2_SUPPORT):
                raise PromoCodeBenefitTypeNotSupport

    def proccess_applied_with_loan(self, loan):
        with db_transactions_atomic(DbConnectionAlias.utilization()):
            promo_code = self.promo_code_qs.select_for_update().last()
            is_valid, message = check_promo_code_and_get_message(
                promo_code=promo_code,
                loan=loan,
            )

            if is_valid:
                create_promo_code_usage(
                    loan=loan,
                    promo_code=promo_code,
                    version=self.version
                )
                promo_code.promo_code_daily_usage_count += 1
                promo_code.promo_code_usage_count += 1
                promo_code.save()
            else:
                raise PromoCodeException(message)

    def get_valid_promo_code_v2(self, application: Application, loan_requested: dict):
        """
            Method to process promo code at loan x210, we dont have Loan object here,
            We check if the promo code is valid and then apply the benefit outside
            And we will create promo code usage after the benefit is applied
        """
        from juloserver.promo.services_v3 import check_promo_code_and_get_message_v2
        promo_code = self.promo_code_qs.last()
        failed_criterion, message = check_promo_code_and_get_message_v2(
            application=application,
            promo_code=promo_code,
            loan_amount=loan_requested.get('loan_amount'),
            transaction_method_id=loan_requested.get('transaction_method_id'),
            loan_duration=loan_requested.get('loan_duration_request'),
        )
        if failed_criterion:
            raise PromoCodeException(message)

        return promo_code, promo_code.promo_code_benefit.type

def check_promo_code_application_type_exist(promo_code: str, current_time: datetime):
    return PromoCode.objects.filter(
        promo_code__iexact=promo_code,
        type=PromoCodeTypeConst.APPLICATION,
        is_active=True,
        start_date__lte=current_time,
        end_date__gte=current_time,
    ).exists()


def is_eligible_promo_entry_page(application):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PROMO_ENTRY_PAGE,
        is_active=True
    ).last()
    if feature_setting and application.eligible_for_promo_entry_page:
        return True

    return False


def fill_cache_promo_cms():
    redis_client = get_redis_client()
    promo_cms_client = get_promo_cms_client()
    promo_list_res = promo_cms_client.promo_list()
    promo_codes = promo_list_res['promo_codes']

    ttl = PromoCMSRedisConstant.REDIS_CACHE_TTL_SECONDS_DEFAULT
    for promo_code in promo_codes:
        promo_cache_detail_key = PromoCMSRedisConstant.PROMO_CMS_DETAIL.format(
            promo_code["general"]["nid"]
        )
        redis_client.set(promo_cache_detail_key, json.dumps(promo_code), ttl)

    cache_value = {
        "header": promo_list_res['header'],
        "promo_codes": [promo_code["general"] for promo_code in promo_codes]
    }
    redis_client.set(PromoCMSRedisConstant.PROMO_CMS_LIST, json.dumps(cache_value), ttl)


def get_promo_cms_info(category):
    redis_client = get_redis_client()
    result = redis_client.get(PromoCMSRedisConstant.PROMO_CMS_LIST)
    if result is not None:
        result = json.loads(result)
        promo_codes = process_get_promo_cms_by_category(result["promo_codes"], category)
        result["promo_codes"] = promo_codes
        return result

    fetch_promo_cms.delay()
    return {}


def process_get_promo_cms_by_category(promo_codes, category):
    valid_promo_codes = []
    for promo_code in promo_codes:
        try:
            valid_promo_code = format_promo_date_to_datetime(promo_code)
            valid_promo_codes.append(valid_promo_code)
        except Exception:
            sentry_client.captureException()

    valid_promo_codes = get_promo_cms_by_category(valid_promo_codes, category)
    res_data = format_response_data(valid_promo_codes)
    return res_data


def format_promo_date_to_datetime(promo_code, format=DEFAULT_DATETIME_FORMAT):
    start_date, end_date = promo_code["start_date"], promo_code["end_date"]
    start_date = timezone.localtime(datetime.strptime(start_date, format))
    end_date = timezone.localtime(datetime.strptime(end_date, format))
    return {
        **promo_code,
        **{
            "formatted_start_date": start_date,
            "formatted_end_date": end_date
        }
    }


def format_response_data(promo_codes):
    res_data = []
    for promo_code in promo_codes:
        del promo_code['formatted_start_date']
        del promo_code['formatted_end_date']
        res_data.append(promo_code)

    return res_data

def get_promo_cms_by_category(promo_codes, category):
    now = timezone.localtime(timezone.now())
    promo_codes = filter_promo_cms_by_category(promo_codes, category, now)
    promo_codes = order_promo_cms_by_category(promo_codes, category, now)
    return promo_codes


def filter_promo_cms_by_category(promo_codes, category, now):
    parameters = get_promo_entry_page_parameters()
    search_categories = [
        search_category['category'] for search_category in parameters.get('search_categories', [])
        if search_category['is_active']
    ]
    if category not in search_categories:
        return []

    expiry_days = parameters.get('search_days_expiry', EXPIRE_PROMO_CMS_SEARCH_EXPIRY_DAYS_DEFAULT)
    filter_func = get_filter_func(category)
    if filter_func:
        return list(
            filter(
                lambda promo_code: filter_func(promo_code, now, expiry_days),
                promo_codes
            )
        )
    else:
        return []


def get_filter_func(category):
    filter_func_mapping = {
        PromoCMSCategory.ALL: filter_promo_cms_all,
        PromoCMSCategory.AVAILABLE: filter_promo_cms_available,
        PromoCMSCategory.EXPIRED: filter_promo_cms_expired,
    }
    return filter_func_mapping.get(category)


def filter_promo_cms_all(promo_code, now, expiry_days):
    expire_date = now - timedelta(days=expiry_days)
    return promo_code["formatted_end_date"] >= expire_date


def filter_promo_cms_available(promo_code, now, expiry_days=None):
    return promo_code["formatted_start_date"] <= now <= promo_code["formatted_end_date"]


def filter_promo_cms_expired(promo_code, now, expiry_days):
    expire_date = now - timedelta(days=expiry_days)
    return expire_date <= promo_code["formatted_end_date"] < now


def order_promo_cms_by_category(promo_codes, category, now):
    order_func = get_order_func(category)
    if order_func:
        return sorted(promo_codes, key=lambda promo_code: order_func(promo_code, now))
    else:
        return promo_codes


def get_order_func(category):
    default_order_func = order_promo_cms_by_availability_and_end_date
    order_func_mapping = {
        PromoCMSCategory.ALL: default_order_func,
        PromoCMSCategory.AVAILABLE: order_promo_cms_by_end_date,
        PromoCMSCategory.EXPIRED: order_promo_cms_by_end_date,
    }
    return order_func_mapping.get(category, default_order_func)


def order_promo_cms_by_availability_and_end_date(promo_code, now):
    availability = promo_code["formatted_start_date"] <= now <= promo_code["formatted_end_date"]
    # As using ascending sort order, availability needs to be reversed
    return not availability, promo_code["formatted_end_date"]


def order_promo_cms_by_end_date(promo_code, now):
    return promo_code["formatted_end_date"]


def get_promo_cms_detail(nid):
    redis_client = get_redis_client()
    cache_detail = redis_client.get(PromoCMSRedisConstant.PROMO_CMS_DETAIL.format(nid))
    if cache_detail is not None:
        promo_detail = json.loads(cache_detail)
        general = promo_detail["general"]
        promo_code = general["promo_code"]
        transaction_method_id = None
        if promo_code:
            transaction_method_ids = get_transaction_methods_criteria_by_promo(promo_code)
            if len(transaction_method_ids) == 1:
                transaction_method_id = transaction_method_ids[0]
        return {
            **general,
            "transaction_method_id": transaction_method_id,
            "detail": promo_detail["detail"],
        }

    fetch_promo_cms.delay()
    return {}


def get_transaction_methods_criteria_by_promo(promo_code):
    promo_code = PromoCode.objects.filter(
        promo_code__iexact=promo_code, type=PromoCodeTypeConst.LOAN
    ).last()

    if not promo_code:
        return []

    promo_criterias = PromoCodeCriteria.objects.filter(
        id__in=promo_code.criteria, type=PromoCodeCriteriaConst.TRANSACTION_METHOD
    )
    if not promo_criterias:
        return []

    transaction_method_ids = set()
    for promo_criteria in promo_criterias:
        transaction_method_ids.update(promo_criteria.value["transaction_method_ids"])

    return list(transaction_method_ids)


def sort_promo_code_list_highest_first(promo_codes):
    benefit_types = [benefit_type for benefit_type, _ in PromoCodeBenefitConst.CHOICES]

    def sort_strategy(promo_code_1, promo_code_2):
        benefit_val_1 = promo_code_1.promo_code_benefit.value
        benefit_val_2 = promo_code_2.promo_code_benefit.value
        benefit_type_1 = promo_code_1.promo_code_benefit.type
        benefit_type_2 = promo_code_2.promo_code_benefit.type

        type_1_idx = len(benefit_types) - benefit_types.index(benefit_type_1)
        type_2_idx = len(benefit_types) - benefit_types.index(benefit_type_2)

        eligible_1_idx = promo_code_1.is_eligible
        eligible_2_idx = promo_code_2.is_eligible

        val_1 = int(benefit_val_1.get('amount', 0)) or \
            (float(benefit_val_1.get('percent', 0)) * (int(benefit_val_1.get('duration', 0)) or 1))
        val_2 = int(benefit_val_2.get('amount', 0)) or \
            (float(benefit_val_2.get('percent', 0)) * (int(benefit_val_2.get('duration', 0)) or 1))

        if eligible_1_idx != eligible_2_idx:
            return eligible_1_idx - eligible_2_idx

        if type_1_idx != type_2_idx:
            return type_1_idx - type_2_idx

        return val_1 - val_2

    promo_codes.sort(key=cmp_to_key(sort_strategy), reverse=True)
    return promo_codes


def get_promo_code_super_type(promo_code):
    benefit_type = promo_code.promo_code_benefit.type
    CASHBACK_TYPES = [
        PromoCodeBenefitConst.FIXED_CASHBACK,
        PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
        PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT
    ]
    DISCOUNT_TYPES = [
        PromoCodeBenefitConst.INSTALLMENT_DISCOUNT,
        PromoCodeBenefitConst.INTEREST_DISCOUNT
    ]

    if benefit_type in CASHBACK_TYPES:
        return 'cashback'
    if benefit_type in DISCOUNT_TYPES:
        return 'discount'
    return benefit_type


def get_search_categories():
    parameters = get_promo_entry_page_parameters()
    if not parameters:
        return []

    search_categories = parameters.get('search_categories', [])
    if not search_categories:
        return []

    return [
        search_category['category'] for search_category in search_categories
        if search_category['is_active']
    ]


def get_promo_entry_page_parameters():
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PROMO_ENTRY_PAGE, is_active=True
    ).last()
    if not fs:
        return None
    return fs.parameters or {}


def is_valid_promo_code_whitelist(promo_code, customer_id):
    criteria = PromoCodeCriteria.objects.filter(
        id__in=promo_code.criteria,
        type=PromoCodeCriteriaConst.WHITELIST_CUSTOMERS
    )

    for criterion in criteria:
        is_in_whitelist = CriteriaControlList.objects.filter(
            customer_id=customer_id,
            promo_code_criteria_id=criterion.id,
            is_deleted=False
        ).exists()
        if not is_in_whitelist:
            return False

    return True


def group_customers_set(customers_new_set, customers_existed_set):
    '''
    insert set:
        - come from customers_new_set except common set between new and existed set \n
    common set (aka update_set):
        - customers are in both new and old set
        - will update is_deleted = False \n
    del set:
        - customers who are in db table, but not belong in new set,
        - will be deleted (is_deleted = True)
    '''
    customers_insert_set = customers_new_set
    customers_update_set = set()
    customers_del_set = set()
    if len(customers_existed_set):
        customers_insert_set = customers_new_set.difference(customers_existed_set)  # or new - exist
        customers_del_set = customers_existed_set.difference(customers_new_set)
        customers_update_set = customers_new_set.intersection(customers_existed_set)

    return customers_insert_set, customers_update_set, customers_del_set


def create_or_update_whitelist_criteria(
    customers_insert_set: set,
    customers_update_set: set,
    customers_del_set: set,
    criteria,
):
    criteria_id = criteria.id
    criteria_control_lst = []

    for batch_update_customers in chunker_list(list(customers_update_set)):
        CriteriaControlList.objects.filter(
            promo_code_criteria_id=criteria_id,
            customer_id__in=batch_update_customers
        ).update(is_deleted=False)

    for batch_del_customers in chunker_list(list(customers_del_set)):
        CriteriaControlList.objects.filter(
            promo_code_criteria_id=criteria_id,
            customer_id__in=batch_del_customers
        ).update(is_deleted=True)

    # insert by batch size
    for cust_id in customers_insert_set:
        criteria_control_lst.append(
            CriteriaControlList(
                customer_id=cust_id,
                promo_code_criteria_id=criteria_id,
            )
        )

    CriteriaControlList.objects.bulk_create(
        criteria_control_lst,
        batch_size=PromoCodeCriteriaConst.WHITELIST_BATCH_SIZE
    )


def construct_and_update_whitelist_customers_for_raven_criteria(
    customers_new_set,
    promo_code_criteria
):
    customers_existed_set = set(CriteriaControlList.objects.filter(
        promo_code_criteria_id=promo_code_criteria.id
    ).values_list('customer_id', flat=True))

    customers_insert_set, customers_update_set, customers_del_set =\
        group_customers_set(customers_new_set, customers_existed_set)

    create_or_update_whitelist_criteria(
        customers_insert_set, customers_update_set, customers_del_set, promo_code_criteria
    )


def is_passed_check_application_approved_day(criterion, application):
    min_days_before = criterion.value['min_days_before']
    max_days_before = criterion.value['max_days_before']
    today = timezone.localtime(timezone.now()).date()
    near_date = today - timedelta(days=min_days_before)
    further_date = today - timedelta(days=max_days_before)

    return ApplicationHistory.objects.filter(
        application_id=application.id,
        status_new=ApplicationStatusCodes.LOC_APPROVED,
        cdate__date__gte=further_date,
        cdate__date__lte=near_date
    ).exists()

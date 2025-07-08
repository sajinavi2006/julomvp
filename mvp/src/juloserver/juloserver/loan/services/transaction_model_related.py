from dataclasses import dataclass
import json
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import logging

from django.db import transaction
from django.db.models import Sum

from juloserver.account.models import Account, AccountLimit
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.constants import LoanJuloOneConstant, LoanRedisKey
from juloserver.loan.exceptions import TransactionModelException
from juloserver.loan.services.feature_settings import AnaTransactionModelSetting
from juloserver.julo.models import Loan
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from juloserver.loan.models import (
    TransactionModelCustomer,
    TransactionModelCustomerAnaHistory,
    TransactionModelCustomerHistory,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.ana_api.services import (
    LoanSelectionAnaAPIPayload,
    TransactionModelResult,
    predict_loan_selection,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.payment_point.models import TransactionMethod
from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@dataclass
class TransactionModelHistoryData:
    old_value: str
    new_value: str
    field_name: str
    transaction_model_customer_id: int


def create_transaction_model_history(data: List[TransactionModelHistoryData]):
    histories = []
    for item in data:
        history = TransactionModelCustomerHistory(
            transaction_model_customer_id=item.transaction_model_customer_id,
            old_value=item.old_value,
            new_value=item.new_value,
            field_name=item.field_name,
        )
        histories.append(history)

    TransactionModelCustomerHistory.objects.bulk_create(histories)


def get_customer_outstanding_cashloan_amount(
    customer_id: int, last_mercury_true_date: datetime = None
):
    """
    Get current customer's ountstand cashloan amount
    By finding sum of all loan_amount of ongoing loans
    Ongoing loan statuses where limit is subtracted:
        - all under 250
        - except: 209, 215, 216, 217, 219
    """
    query = (
        Loan.objects.filter(
            customer_id=customer_id,
            transaction_method_id__in=TransactionMethodCode.mercury_transaction_codes(),
        )
        .exclude(
            loan_status__in=LoanStatusCodes.limit_not_subtracted_loan_status(),
        )
        .exclude(
            loan_status__gte=LoanStatusCodes.PAID_OFF,
        )
    )

    if last_mercury_true_date:
        query = query.filter(
            cdate__gte=last_mercury_true_date,
        )

    active_cashloan_amount = query.aggregate(total=Sum("loan_amount"))["total"] or 0

    return active_cashloan_amount


class MercuryCustomerService:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.customer = account.customer
        self.transaction_model_customer = None
        self.fs = AnaTransactionModelSetting()

    def is_method_valid(self, method_code: int) -> bool:
        if method_code in TransactionMethodCode.mercury_transaction_codes():
            return True

        return False

    def is_method_name_valid(self, method_name: str) -> bool:
        if method_name in TransactionMethodCode.mercury_transaction_names():
            return True

        return False

    def is_mercury_customer_blocked(self) -> bool:
        """
        Check if current available cashloan limit is less than
        requested threshold for cashloan method
        """
        from juloserver.loan.services.views_related import get_loan_amount_default_fs

        loan_amount_fs = get_loan_amount_default_fs(self.customer.id)
        min_requested_loan_amount = loan_amount_fs.get(
            'min_amount_threshold', LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        )

        # we're supposed to pass in final loan amount
        # but to calculate it here is too much computation, so for now just use original amount
        return self.is_mercury_customer_blocked_from_amount(
            final_loan_amount=min_requested_loan_amount,
        )

    def is_mercury_customer_blocked_from_amount(self, final_loan_amount: int) -> bool:
        """
        Check if customer is blocked for further making cashloans

        *Make sure is_customer_eligible() or get_mercury_status_and_loan_tenure() is called first
        to see that user is mercury before using this function

        """
        current_available_cashloan_limit = self.calculate_ana_available_cashloan_amount()

        if final_loan_amount > current_available_cashloan_limit:
            return True

        return False

    def get_mercury_status_and_loan_tenure(
        self, transaction_method_id: int
    ) -> Tuple[bool, List[int]]:
        """
        We can use this func to check mercury status
        Get status & loan tenure for the view
        """
        is_mercury = False
        loan_tenure = []
        if self.is_method_valid(method_code=transaction_method_id) and self.is_customer_eligible():
            is_mercury, loan_tenure = self.is_customer_mercury()

        return is_mercury, loan_tenure

    def is_customer_eligible(self) -> bool:
        """

        Check if customer is valid, before continuing
        - J1/Turbo

        If eligible, set up objects, so must run before using service
        """
        # check for j1/turbo
        app = self.account.get_active_application()
        is_eligible = (
            app.product_line_id in [ProductLineCodes.J1]
            and app.application_status_id == ApplicationStatusCodes.LOC_APPROVED
            and self.fs.is_active
            and self.fs.is_customer_eligible(customer_id=self.customer.id)
        )
        if is_eligible:
            self._refresh_transaction_model_object()

        return is_eligible

    def _refresh_transaction_model_object(self) -> bool:
        """
        Set up objects
        """
        self.transaction_model_customer = TransactionModelCustomer.objects.filter(
            customer_id=self.customer.id,
        ).last()

    def is_customer_mercury(self) -> Tuple[bool, List]:
        # check if mercury is true, then apply loan_range

        is_mercury = False
        loan_tenure_range = []
        if self.transaction_model_customer:
            is_mercury = self.transaction_model_customer.is_mercury
            loan_tenure_range = self.transaction_model_customer.allowed_loan_duration

        return is_mercury, loan_tenure_range

    def calculate_ana_available_cashloan_amount(self) -> int:
        """
        1. find max allowed available cashloan amount from ana
        2. find ongoing loans from the last moment mercury is true
        => result is 1 minus 2
        """
        # 1
        model = self.transaction_model_customer
        max_allowed_available_cashloan = model.max_cashloan_amount

        last_time_mercury_is_set_true = TransactionModelCustomerHistory.objects.filter(
            transaction_model_customer_id=model.id,
            field_name='is_mercury',
            new_value='True',
        ).last()

        if not last_time_mercury_is_set_true:
            raise TransactionModelException(
                "Can not find transaction model record with mercury status True"
            )

        # 2
        outstanding_cash_loan_since_last_mercury = get_customer_outstanding_cashloan_amount(
            customer_id=self.customer.id,
            last_mercury_true_date=last_time_mercury_is_set_true.cdate,
        )

        result = max_allowed_available_cashloan - outstanding_cash_loan_since_last_mercury

        logger.info(
            {
                "action": "calculate_ana_available_cashloan_amount",
                "customer_id": self.customer.id,
                "max_allowed_available_cashloan": max_allowed_available_cashloan,
                "outstanding_cash_loan_since_last_mercury": (
                    outstanding_cash_loan_since_last_mercury
                ),
                "last_history_mercury_is_set_true": last_time_mercury_is_set_true,
                "last_date_mercury_is_set_true": last_time_mercury_is_set_true.cdate,
            }
        )

        return result

    def get_mercury_available_limit(
        self,
        account_limit: AccountLimit,
        min_duration: int,
        max_duration: int,
        transaction_type: str,
    ) -> Tuple[bool, int]:
        """
        Flow:
            https://drive.google.com/file/d/1IchNPknJ82zgM67V99usd3KtYkqqKEjs/view?usp=sharing

        - If customer is considered mercury:
            We return their respective ana available cashloan limit, based on outstanding cashloan

        - If customer is currently not mercury:
            We hit ana model & store its result to our Backend

        Returns:
            - is_applied_mercury (bool)
            - new_available_limit
        """

        logger.info(
            {
                "action": "MercuryCustomerService.get_mercury_available_limit",
                "account_limit": account_limit,
                "customer_id": self.customer.id,
                "min_duration": min_duration,
                "max_duration": max_duration,
                "transaction_type": transaction_type,
            }
        )

        self.account_limit = account_limit
        original_available_limit = account_limit.available_limit
        is_mercury, _ = self.is_customer_mercury()

        if is_mercury:
            outstanding_cashloan = get_customer_outstanding_cashloan_amount(
                customer_id=self.customer.id,
            )
            if outstanding_cashloan > 0:
                return True, self.calculate_ana_available_cashloan_amount()
            else:
                old_value = self.transaction_model_customer.is_mercury
                self.transaction_model_customer.is_mercury = False
                self.transaction_model_customer.save(update_fields=['is_mercury'])
                create_transaction_model_history(
                    [
                        TransactionModelHistoryData(
                            transaction_model_customer_id=self.transaction_model_customer.id,
                            field_name='is_mercury',
                            old_value=old_value,
                            new_value=False,
                        )
                    ]
                )
                return False, original_available_limit

        # if not mercury, hit ana
        # CASE HITTING ANA
        method = TransactionMethod.objects.get(method=transaction_type)
        transaction_model_result = self.hit_ana_loan_selection_api(
            payload=LoanSelectionAnaAPIPayload(
                customer_id=self.customer.id,
                min_loan_duration=min_duration,
                max_loan_duration=max_duration,
                available_limit=account_limit.available_limit,
                set_limit=account_limit.set_limit,
                transaction_method_id=method.id,
            ),
            account_limit=account_limit,
        )
        # if ana returns response & result is mercury, give user available cashloan limit
        if transaction_model_result and transaction_model_result.is_mercury:
            # transaction model object should be created
            self._refresh_transaction_model_object()
            return True, self.calculate_ana_available_cashloan_amount()

        return False, original_available_limit

    def update_or_create_transaction_model_customer(
        self, customer_id: int, ana_model_result: TransactionModelResult
    ) -> Tuple[bool, TransactionModelCustomer]:
        """
        This function should only be called when current mercury status is FALSE or not-existing

        Get object based on current ana result
        """
        ana_loan_duration = ana_model_result.allowed_loan_duration_amount['loan_duration_range']
        ana_cashloan_amount = ana_model_result.allowed_loan_duration_amount['max_cashloan_amount']
        ana_is_mercury = ana_model_result.is_mercury

        # prepare update data
        to_update_dict = {
            "is_mercury": ana_is_mercury,
            "allowed_loan_duration": ana_loan_duration,
            "max_cashloan_amount": ana_cashloan_amount,
        }
        is_created = False
        is_create_history = False
        fields_to_save_history = []
        with transaction.atomic():
            transaction_model = (
                TransactionModelCustomer.objects.select_for_update()
                .filter(
                    customer_id=self.customer.id,
                )
                .last()
            )
            if transaction_model:
                if transaction_model.is_mercury:
                    raise TransactionModelException("mercury status should not be true")

                # only update if transitioning 'mercury' status from FALSE to TRUE
                if not transaction_model.is_mercury and ana_model_result.is_mercury:
                    # check status mercury again
                    if not transaction_model:
                        logger.info(
                            {
                                "action": "update_or_create_transaction_model_customer",
                                "message": "mercury status switches to True before saving",
                                "transaction_model_customer_id": transaction_model.id,
                                "customer_id": self.customer.id,
                            }
                        )
                        return False, transaction_model

                    is_create_history = True
                    # update & create history data to create
                    for key, value in to_update_dict.items():
                        old_value = getattr(transaction_model, key, '')
                        if old_value != value:
                            setattr(transaction_model, key, value)
                            fields_to_save_history.append(
                                TransactionModelHistoryData(
                                    old_value=old_value,
                                    new_value=value,
                                    field_name=key,
                                    transaction_model_customer_id=transaction_model.id,
                                )
                            )

                    transaction_model.save(update_fields=list(to_update_dict))
            else:
                transaction_model = TransactionModelCustomer.objects.create(
                    customer_id=customer_id,
                    **to_update_dict,
                )
                is_created = True
                is_create_history = True
                for key, value in to_update_dict.items():
                    fields_to_save_history.append(
                        TransactionModelHistoryData(
                            old_value='',
                            new_value=value,
                            field_name=key,
                            transaction_model_customer_id=transaction_model.id,
                        )
                    )

            if is_create_history:
                TransactionModelCustomerAnaHistory.objects.create(
                    customer_id=self.customer.id,
                    ana_response=ana_model_result.__dict__,
                )
                create_transaction_model_history(fields_to_save_history)

        logger.info(
            {
                "action": "update_or_create_transaction_model_customer",
                "message": "finished update/create transaction model customer",
                "customer_id": self.customer.id,
                "ana_model_result": ana_model_result.__dict__,
                "is_created": is_created,
                "current_transaction_model": transaction_model,
            }
        )

        return is_created, transaction_model

    def hit_ana_loan_selection_api(
        self,
        payload: LoanSelectionAnaAPIPayload,
        account_limit: AccountLimit,
    ) -> Optional[TransactionModelResult]:
        """
        Check FS & Redis before hitting ana loan selection api to prevent spamming

        """
        fs = self.fs
        if not fs.is_active:
            return

        # check if customer is eligible/whitelisted (for whole feature)
        if not fs.is_customer_eligible(customer_id=payload.customer_id):
            return

        if not fs.is_hitting_ana:
            return

        # check minimum available limit
        available_limit = account_limit.available_limit
        if available_limit < fs.minimum_limit:
            logger.info(
                {
                    "action": "hit_ana_loan_selection_api",
                    "message": "available limit is less than configured minimum available limit",
                    "available_limit": available_limit,
                    "configured_minimum_limit": fs.minimum_limit,
                    "customer_id": payload.customer_id,
                    "account_limit_id": account_limit.id,
                }
            )
            return

        # prepare redis, cache to prevent hitting ana too many times
        payload_hash = hash(payload)
        redis_key = LoanRedisKey.ANA_TRANSACTION_MODEL_COOLDOWN.format(
            customer_id=payload.customer_id,
            payload_hash=payload_hash,
        )
        redis_client = get_redis_client()

        # if payload doesn't change and cache has not expired, just get cache
        if redis_client.exists(names=redis_key):
            cached_value = redis_client.get(key=redis_key)

            # case cached result is empty string (204 from ana)
            if not cached_value:
                return

            cached_dict = json.loads(cached_value)
            return TransactionModelResult(
                **cached_dict,
            )

        # run directly without async
        is_success, prediction_result = predict_loan_selection(
            payload=payload,
        )

        # only cache if success
        if is_success:
            cooldown_seconds = fs.cooldown_time

            # if there is prediction, cache & store it on table
            if prediction_result:
                ana_cashloan_amount = prediction_result.allowed_loan_duration_amount[
                    'max_cashloan_amount'
                ]
                if ana_cashloan_amount > account_limit.available_limit:
                    sentry_client.captureMessage(
                        {
                            "message": "Ana Max Limit is larger than current available limit",
                            "action": "update_or_create_transaction_model_customer",
                            "ana_max_available_cashloan_amount": ana_cashloan_amount,
                            "user_current_available_limit": account_limit.available_limit,
                            "account_limit_id": account_limit.id,
                            "customer_id": self.customer.id,
                        }
                    )
                    return

                self.update_or_create_transaction_model_customer(
                    customer_id=payload.customer_id,
                    ana_model_result=prediction_result,
                )

            # cache; even if there isn't prediction data,
            # still cache empty so won't call ana until expired
            redis_client.set(
                key=redis_key,
                value=json.dumps(prediction_result.__dict__) if prediction_result else '',
                expire_time=timedelta(seconds=cooldown_seconds),
            )

        return prediction_result

    def compute_mercury_tenures(
        self, final_tenures: List[int], mercury_loan_tenures: List[int]
    ) -> List[int]:
        """
        Returns a filtered list of tenures based on the overlap between final_tenures
        and mercury_loan_tenure.

        The result is a range from the minimum value in final_tenures up to the smaller
        of the max values in both lists — but only if:
        max(mercury_loan_tenure) <= min(final_tenures)

        Otherwise, it returns final_tenures unchanged.

        Examples:
        - final=[5,6,7,8,9], mercury=[4,5]         → [5]
        - final=[1,2],        mercury=[3,4]        → [1,2]
        - final=[3,4,5],      mercury=[2,3,4]      → [3,4]
        """

        if not final_tenures or not mercury_loan_tenures:
            return final_tenures

        min_final = min(final_tenures)
        max_mercury = max(mercury_loan_tenures)

        # Check for no-overlap
        if not (set(final_tenures) & set(mercury_loan_tenures)):
            return final_tenures

        max_range = min(max(final_tenures), max_mercury)

        mercury_tenures = list(range(min_final, max_range + 1))

        logger.info(
            {
                "action": "MercuryCustomerService.compute_mercury_tenures",
                "message": "computing mercury tenures from final tenures",
                "final_tenures": final_tenures,
                "mercury_loan_tenures": mercury_loan_tenures,
                "max_range": max_range,
                "customer_id": self.customer.id,
            }
        )
        return mercury_tenures

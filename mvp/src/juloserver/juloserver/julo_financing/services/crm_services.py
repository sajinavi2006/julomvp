import logging
from typing import Tuple, Optional, List
from juloserver.julo_financing.models import (
    JFinancingVerification,
    JFinancingVerificationHistory,
    JFinancingProduct,
)
from juloserver.julo_financing.constants import JFinancingStatus, JFinancingFeatureNameConst
from juloserver.julo_financing.exceptions import (
    JFinancingVerificationException,
    LoanAmountExceedAvailableLimit,
    CourierInfoIsEmpty,
    WrongPathStatusChange,
)
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.sphp import accept_julo_sphp
from django.db import transaction, DatabaseError
from juloserver.account.models import AccountLimit
from juloserver.loan.services.lender_related import julo_one_loan_disbursement_success
from juloserver.julo.models import Loan
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.moengage.services.use_cases import send_event_jfinancing_verification_status_change
from juloserver.julo.utils import execute_after_transaction_safely

logger = logging.getLogger(__name__)


def get_verification_status_changes(status_from: str):
    statuses = JFinancingStatus.change_to_status(status_from)
    bahasa_statuses = dict(JFinancingVerification.VALIDATION_STATUS_CHOICES)
    return [[status, bahasa_statuses[status]] for status in statuses]


class JFinancingVerificationStatusService:
    def __init__(self, verification: JFinancingVerification, agent_user_id: int = None):
        self.verification = verification
        self.loan = verification.loan
        self.agent_user_id = agent_user_id

        # using transaction.atomic
        self.status_actions = {
            JFinancingStatus.CONFIRMED: self._update_confirmed_status,
            JFinancingStatus.ON_DELIVERY: self._update_on_delivery_status,
            JFinancingStatus.COMPLETED: self._update_completed_status,
            JFinancingStatus.CANCELED: self._update_canceled_status,
        }

    def process_update_status(self, new_status: str) -> None:
        """Update the verification status based on the provided new status."""
        if new_status in self.status_actions:
            old_status = self.verification.validation_status
            self.status_actions[new_status]()
            self.create_verification_status_history(old_status, new_status)

        else:
            raise WrongPathStatusChange("Unhandled status: {}".format(new_status))

    def return_quantity_product(self, number: int) -> None:
        """
        Update the product quantity based on the provided number. if number is minus => -1 product
        """
        j_financing_product_id = self.verification.j_financing_checkout.j_financing_product_id
        product = JFinancingProduct.objects.select_for_update().get(pk=j_financing_product_id)
        stock = product.quantity + number
        product.update_safely(quantity=stock)

    def __update_verification_status(self, new_status: str) -> None:
        self.verification.update_safely(validation_status=new_status)

    def _update_confirmed_status(self) -> None:
        account_limit = AccountLimit.objects.select_for_update().get(
            account_id=self.loan.account_id
        )
        if self.loan.loan_amount > account_limit.available_limit:
            raise LoanAmountExceedAvailableLimit("Loan amount cannot exceed the available limit.")
        self.__update_verification_status(JFinancingStatus.CONFIRMED)
        update_loan_status_and_loan_history(
            self.loan.pk,
            new_status_code=LoanStatusCodes.INACTIVE,
            change_by_id=self.agent_user_id,
            change_reason="Inactive",
        )
        accept_julo_sphp(self.loan, "JULO")

    def _update_on_delivery_status(self) -> None:
        checkout = self.verification.j_financing_checkout
        if not checkout.courier_name or not checkout.courier_tracking_id:
            raise CourierInfoIsEmpty("Courier information is missing.")

        self.__update_verification_status(JFinancingStatus.ON_DELIVERY)
        self.send_event_verification_status_change()

    def _update_completed_status(self) -> None:
        self.__update_verification_status(JFinancingStatus.COMPLETED)
        self.send_event_verification_status_change()

    def _update_canceled_status(self) -> None:
        self.__update_verification_status(JFinancingStatus.CANCELED)
        self.return_quantity_product(1)
        update_loan_status_and_loan_history(
            self.loan.pk,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_by_id=self.agent_user_id,
            change_reason="Customer request to cancel",
        )

    def send_event_verification_status_change(self):
        execute_after_transaction_safely(
            lambda: send_event_jfinancing_verification_status_change.delay(
                self.loan.customer_id, self.verification.pk
            )
        )

    def create_verification_status_history(self, old_value: str, new_value: str) -> None:
        JFinancingVerificationHistory.objects.create(
            agent_id=self.verification.locked_by_id,
            field_name='validation_status',
            old_value=old_value,
            new_value=new_value,
            j_financing_verification_id=self.verification.pk,
        )

    def update_status_when_loan_get_failed(self) -> None:
        old_status = self.verification.validation_status
        if old_status == JFinancingStatus.CANCELED:
            return

        # we don't minus quantity when INITIAL status => CANCELED not update
        if old_status != JFinancingStatus.INITIAL:
            self.return_quantity_product(1)

        self.__update_verification_status(JFinancingStatus.CANCELED)
        self.create_verification_status_history(old_status, JFinancingStatus.CANCELED)


def update_julo_financing_verification_status(
    status_to: str, verification: JFinancingVerification, agent_user_id: int
) -> Tuple[bool, Optional[str]]:
    try:
        with transaction.atomic():
            verification = JFinancingVerification.objects.select_for_update(nowait=True).get(
                pk=verification.pk
            )
            verification_service = JFinancingVerificationStatusService(verification, agent_user_id)
            verification_service.process_update_status(status_to)
            return True, None

    except JFinancingVerificationException as e:
        return False, str(e)
    except DatabaseError:
        return False, "Duplicate requests detected."


def update_verification_note(verification: JFinancingVerification, new_note: str) -> None:
    new_note = new_note.strip()
    if new_note != verification.note:
        with transaction.atomic():
            old_note = verification.note
            verification.update_safely(note=new_note)
            JFinancingVerificationHistory.objects.create(
                agent_id=verification.locked_by_id,
                field_name='note',
                old_value=old_note,
                new_value=new_note,
                j_financing_verification_id=verification.pk,
            )


def update_courier_info_for_checkout(
    verification: JFinancingVerification, courier_info: dict
) -> None:
    logger.info(
        {
            'action': 'update_courier_info_for_checkout',
            'j_financing_checkout': verification.j_financing_checkout.pk,
            'old_courier_name': verification.j_financing_checkout.courier_name,
            'old_tracking_id': verification.j_financing_checkout.courier_tracking_id,
            'new_courier_info': courier_info,
        }
    )
    courier_name = courier_info['courier_name']
    courier_tracking_id = courier_info['courier_tracking_id']

    checkout = verification.j_financing_checkout
    checkout.update_safely(courier_name=courier_name, courier_tracking_id=courier_tracking_id)


def julo_financing_disbursement_process(loan: Loan) -> None:
    """
    We only update status to x212 -> x220. because we have no disbursement on Julo Financing
    """
    logger.info(
        {
            'action': 'julo_financing_disbursement_process',
            'loan_id': loan.pk,
        }
    )
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender",
    )
    julo_one_loan_disbursement_success(loan)


def update_jfinancing_verification_with_failed_loan(loan_id: int) -> None:
    with transaction.atomic():
        verification = JFinancingVerification.objects.select_for_update(nowait=True).get(
            loan_id=loan_id
        )
        verification_service = JFinancingVerificationStatusService(verification)
        verification_service.update_status_when_loan_get_failed()


def get_couriers() -> List[str]:
    fs = FeatureSettingHelper(
        feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION
    )
    couriers = fs.params.get('couriers_info', {})
    return couriers.keys()


def is_invalid_validation_status_change(status_to: str, validation_status: str):
    statuses_changes = get_verification_status_changes(validation_status)
    return status_to not in [status_change for status_change, _ in statuses_changes]

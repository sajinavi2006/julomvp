import math
import logging

from django.utils import timezone
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Customer, Loan, Partner, FeatureSetting
from juloserver.qris.exceptions import (
    HasNotSignedWithLender,
    QrisLinkageNotFound,
    QrisMerchantBlacklisted
)
from juloserver.qris.models import QrisPartnerLinkage, QrisPartnerTransaction
from juloserver.qris.serializers import QRISTransactionSerializer
from juloserver.qris.constants import QrisProductName, QrisLinkageStatus, QrisTransactionStatus
from juloserver.loan.services.loan_creation import (
    BaseLoanCreationService,
    BaseLoanCreationSubmitData,
)
from juloserver.loan.constants import TransactionMethodCode
from juloserver.followthemoney.models import LenderCurrent
from django.db import transaction
from juloserver.loan.tasks.lender_related import (
    julo_one_generate_auto_lender_agreement_document_task,
)
from juloserver.followthemoney.tasks import (
    generate_julo_one_loan_agreement,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.followthemoney.models import LenderBalanceCurrent
from juloserver.qris.services.core_services import (
    has_linkage_signed_with_current_lender,
)
from juloserver.qris.services.feature_settings import (
    QrisTenureFromLoanAmountHandler,
    QrisLoanEligibilitySetting,
)
from juloserver.qris.services.view_related import (
    check_qris_loan_eligibility,
    check_qris_blacklist_merchant
)

logger = logging.getLogger(__name__)


class TransactionConfirmationService:
    def __init__(self, request_data: QRISTransactionSerializer, partner_id: int):
        self.request_data = request_data
        self.partner_id = partner_id
        self.qris_partner_linkage = self.get_qris_partner_linkage()

        # convert totalAmount to integer, keep the rest for logging
        self.request_data['totalAmount'] = math.ceil(self.request_data['totalAmount'])

    def get_qris_partner_linkage(self):
        """
        filter any linkage to create qris transaction
        raise error later if linage is not success
        """
        linkage = QrisPartnerLinkage.objects.filter(
            to_partner_user_xid=self.request_data['partnerUserId'],
            partner_id=self.partner_id,
        ).last()

        return linkage

    def create_qris_partner_transaction(self, loan_id: str):
        return QrisPartnerTransaction.objects.create(
            qris_partner_linkage_id=self.qris_partner_linkage.pk,
            loan_id=loan_id,
            from_partner_transaction_xid=self.request_data['transactionId'],
            total_amount=self.request_data['totalAmount'],
            merchant_name=self.request_data['transactionDetail']['merchantName'],
            partner_transaction_request=self.request_data,
        )

    def construct_data_for_loan_creation(self) -> BaseLoanCreationSubmitData:
        loan_duration = QrisTenureFromLoanAmountHandler(
            amount=self.request_data['totalAmount'],
        ).get_tenure()

        return BaseLoanCreationSubmitData(
            loan_amount_request=self.request_data['totalAmount'],
            transaction_type_code=TransactionMethodCode.QRIS_1.code,
            loan_duration=loan_duration,
        )

    def _generate_qris_skrtp_and_p3pti(self, loan_id: int):
        execute_after_transaction_safely(lambda: generate_julo_one_loan_agreement.delay(loan_id))
        execute_after_transaction_safely(
            lambda: julo_one_generate_auto_lender_agreement_document_task.delay(loan_id)
        )

    def _process_loan_x210_to_x211(self, loan_id: int):
        update_loan_status_and_loan_history(
            loan_id,
            new_status_code=LoanStatusCodes.LENDER_APPROVAL,
            change_by_id=self.customer.user.id,
            change_reason="Digital signature succeed",
        )

    def _process_loan_x211_to_x212(self, loan_id: int):
        self._generate_qris_skrtp_and_p3pti(loan_id)
        update_loan_status_and_loan_history(
            loan_id,
            new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            change_by_id=self.customer.user.id,
            change_reason="Loan approved by lender",
        )

    def _is_enough_lender_balance(self, loan_amount: int, lender_id: int):
        return LenderBalanceCurrent.objects.get_or_none(
            lender_id=lender_id, available_balance__gte=loan_amount
        )

    def _process_failed_loan_creation(
        self, loan_id: int, qris_partner_transaction: QrisPartnerTransaction
    ):
        update_loan_status_and_loan_history(
            loan_id,
            new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
            change_by_id=self.customer.user.id,
            change_reason="Run out of Lender Balance",
        )
        qris_partner_transaction.update_safely(
            status=QrisTransactionStatus.FAILED,
        )

    def _process_finished_loan_creation(self, loan_id: int):
        self._process_loan_x210_to_x211(loan_id)
        self._process_loan_x211_to_x212(loan_id)


    def check_lender_eligibility(self) -> LenderCurrent:
        is_signed, lender = has_linkage_signed_with_current_lender(
            linkage=self.qris_partner_linkage
        )
        if not is_signed:
            logger.info(
                {
                    "action": "TransactionConfirmationService.check_lender_eligibility",
                    "message": f"Can not make qris loan, customer has not signed with lender. Probably due do lender switch",
                    "customer_id": self.qris_partner_linkage.customer_id,
                    "lender": lender.lender_name,
                }
            )
            raise HasNotSignedWithLender

        return lender

    @transaction.atomic
    def process_transaction_confirmation(self) -> dict:
        """
        1. check eligibility for loan creation
        2. create loan x210
        3. create qris partner transaction
        4. Check lender balance if not enough => x215
        5. Process loan creation x211 -> x212
        """
        # check linkage status
        if (
            not self.qris_partner_linkage
            or self.qris_partner_linkage.status != QrisLinkageStatus.SUCCESS
        ):
            raise QrisLinkageNotFound

        self.customer = Customer.objects.get(id=self.qris_partner_linkage.customer_id)

        # check eligibility for loan creation
        loan_creation_service = BaseLoanCreationService(
            customer=self.customer, submit_data=self.construct_data_for_loan_creation()
        )

        loan_creation_service.check_eligibility()
        check_qris_loan_eligibility(
            input_amount=self.request_data['totalAmount'],
        )

        # merchant check
        transaction_detail = self.request_data.get("transactionDetail", {})
        merchant_id = transaction_detail.get("merchantId", "").strip()
        merchant_name = transaction_detail.get("merchantName", "").strip()

        if check_qris_blacklist_merchant(merchant_id, merchant_name):
            raise QrisMerchantBlacklisted


        # get lender
        lender = self.check_lender_eligibility()

        # create loan
        loan = loan_creation_service.process_loan_creation(lender=lender)

        # create qris partner transaction
        qris_partner_transaction = self.create_qris_partner_transaction(loan.pk)

        loan.update_safely(sphp_accepted_ts=timezone.now())
        self._process_finished_loan_creation(loan.pk)

        return {
            "transactionInfo": {
                "cdate": timezone.localtime(loan.cdate),
                "loanAmount": loan.loan_amount,
                "currency": "IDR",
                "loanDuration": loan.loan_duration,
                "productId": QrisProductName.QRIS.code,
                "productName": QrisProductName.QRIS.name,
                "loanXID": loan.loan_xid,
                "totalAmount": self.request_data['totalAmount'],
                "transactionId": qris_partner_transaction.to_partner_transaction_xid,
                "partnerTransactionId": qris_partner_transaction.from_partner_transaction_xid,
            }
        }


def is_qris_loan_from_partner(loan: Loan, partner_name: str) -> bool:
    """
    Check if qris loan is of a particular qris partner
    """
    qris_transaction = (
        QrisPartnerTransaction.objects.filter(
            loan_id=loan.id,
        )
        .select_related('qris_partner_linkage')
        .last()
    )

    partner = Partner.objects.get(name=partner_name)

    return qris_transaction.qris_partner_linkage.partner_id == partner.id

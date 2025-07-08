from babel.dates import format_date
from typing import Dict

from django.conf import settings

from juloserver.ecommerce.juloshop_service import (
    get_juloshop_loan_product_details,
    get_juloshop_transaction_by_loan,
)
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.julo.models import AuthUser, Loan
from juloserver.julo.services import prevent_web_login_cases_check
from juloserver.loan.exceptions import LoanNotBelongToUser, LoanNotFound
from juloserver.loan.models import TransactionModelCustomer, TransactionModelCustomerLoan
from juloserver.loan.services.views_related import (
    get_loan_details,
    get_manual_signature,
    get_privy_bypass_feature,
    get_voice_record,
)
from juloserver.loan.services.loan_related import get_loan_transaction_detail


class LoanAgreementDetailsV3Service:
    """
    Service for /api/loan/v3/agreement/loan/{{loan_xid}}
    """

    def __init__(self, query_params: Dict, user: AuthUser, loan_xid: str) -> None:
        self.query_params = query_params
        self.loan_xid = loan_xid
        self.loan = Loan.objects.get_or_none(loan_xid=self.loan_xid)
        self.partner_name = self.query_params.get('partner_name', None)
        self.user = user

    def verify_loan_access(self) -> None:
        """
        Make sure user can access loan
        """
        user = self.user

        if not self.loan:
            raise LoanNotFound

        if user.id != self.loan.customer.user_id:
            raise LoanNotBelongToUser

    def get_response_data(self) -> Dict:
        response = dict()
        response['loan'] = get_loan_details(self.loan)
        response['voice_record'] = get_voice_record(self.loan)
        response['manual_signature'] = get_manual_signature(self.loan)
        response['privy_bypass'] = get_privy_bypass_feature(self.loan)

        login_check, error_message = prevent_web_login_cases_check(self.user, self.partner_name)
        response['eligible_access'] = dict(is_eligible=login_check, error_message=error_message)

        # loan agreement
        response['loan_agreement'] = self.loan_agreement

        # due date
        response['loan']['due_date'] = self._set_due_date()

        # juloshop
        juloshop_data = self._get_juloshop_response_data()
        response['loan'].update(juloshop_data)

        # loan details
        detail = get_loan_transaction_detail(self.loan.id)
        response['loan']['tax_fee'] = detail.get('tax_fee')
        response['loan']['admin_fee'] = detail.get('admin_fee')

        return response

    def _set_due_date(self) -> str:
        """
        add due date to loan response
        """
        oldest_payment = self.loan.payment_set.order_by('payment_number').first()
        return format_date(oldest_payment.due_date, 'd MMM yyyy', locale='id_ID')

    def _get_juloshop_response_data(self) -> Dict:
        """
        add juloshop response data
        """
        juloshop_transaction = get_juloshop_transaction_by_loan(self.loan)
        if juloshop_transaction:
            julo_shop_product = get_juloshop_loan_product_details(juloshop_transaction)
            julo_shop_data = {
                "product_name": julo_shop_product.get('productName'),
                "bank_name": settings.JULOSHOP_BANK_NAME,
                "bank_account_name": settings.JULOSHOP_ACCOUNT_NAME,
                "bank_account_number": settings.JULOSHOP_BANK_ACCOUNT_NUMBER,
            }
            return julo_shop_data

        return {}

    @property
    def loan_agreement(self):
        main_title = "Lihat Dokumen SKRTP dan RIPLAY"
        default_img = (
            settings.STATIC_ALICLOUD_BUCKET_URL + 'loan_agreement/default_document_logo.png'
        )
        return {
            "title": main_title,
            "types": [
                {
                    "type": LoanAgreementType.TYPE_SKRTP,
                    "displayed_title": LoanAgreementType.TYPE_SKRTP.upper(),
                    "text": LoanAgreementType.TEXT_SKRTP,
                    "image": default_img,
                },
                {
                    "type": LoanAgreementType.TYPE_RIPLAY,
                    "displayed_title": LoanAgreementType.TYPE_RIPLAY.upper(),
                    "text": LoanAgreementType.TEXT_RIPLAY,
                    "image": default_img,
                },
            ],
        }


def capture_mercury_loan(
    loan_id: int,
    is_mercury: bool,
    transaction_model_customer: TransactionModelCustomer,
    current_available_cashloan_limit: int,
    cm_max_tenure: int,
    cm_min_tenure: int,
) -> None:
    """
    Marking loan as mercury in db
    """
    if not is_mercury:
        return

    transaction_model_data = {
        "allowed_loan_duration": transaction_model_customer.allowed_loan_duration,
        "max_available_cashloan_amount": transaction_model_customer.max_cashloan_amount,
        "available_cashloan_limit_at_creation_time": current_available_cashloan_limit,
        "cm_max_tenure_at_creation_time": cm_max_tenure,
        "cm_min_tenure_at_creation_time": cm_min_tenure,
    }

    TransactionModelCustomerLoan.objects.create(
        transaction_model_customer_id=transaction_model_customer.id,
        loan_id=loan_id,
        transaction_model_data=transaction_model_data,
    )

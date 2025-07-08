from datetime import datetime, date

from django.test import TestCase
from mock import patch
from factory import Iterator

from juloserver.account.tests.factories import AccountFactory
from juloserver.balance_consolidation.tasks import (
    send_pn_balance_consolidation_verification_status_approved,
    fetch_balance_consolidation_fdc_data,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    LoanFactory,
    PaymentFactory,
    FDCInquiryLoanFactory,
    FeatureSettingFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.account.constants import AccountConstant
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
    BalanceConsolidationDelinquentFDCCheckingFactory,
    FintechFactory,
)
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    FeatureNameConst,
)


PACKAGE_NAME = 'juloserver.balance_consolidation.tasks'

class TestSendPNBalanceConsolidationVerification(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        account = AccountFactory(customer=self.application.customer)
        self.application.update_safely(account=account, application_status_id=190)

    @patch('juloserver.julo.clients.pn.JuloPNClient.pn_balance_consolidation_verification_approve')
    def test_send_pn(self, mock_pn_balance_consolidation):
        send_pn_balance_consolidation_verification_status_approved(self.application.customer)
        mock_pn_balance_consolidation.assert_called_once()


class TestBalanceConsolidationFDCCheckingTask(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LOC_APPROVED
            )
        )
        self.fintech = FintechFactory(is_active=True)
        self.balcon = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(
                status_code=LoanStatusCodes.CURRENT
            ),
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
                method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
            ),
        )
        self.balcon_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balcon,
            loan=self.loan,
            validation_status=BalanceConsolidationStatus.DISBURSED
        )
        self.payments = PaymentFactory.create_batch(
            3,
            loan=self.loan,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE),
            due_date=Iterator([
                date(2024, 3, 22),
                date(2024, 4, 22),
                date(2024, 5, 22)
            ]),
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.BALANCE_CONSOLIDATION_FDC_CHECKING,
            is_active=True,
            parameters={'start_date': "2024-04-15"}
        )

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    def test_fetch_balcon_fdc_data_fs_off(self, mock_fetch_fdc_data_task):
        self.feature_setting.update_safely(is_active=False)

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_not_called()

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    @patch('django.utils.timezone.now')
    def test_fetch_balcon_fdc_data_for_customer_success(
        self, mock_now, mock_fetch_fdc_data_task
    ):
        mock_now.return_value = datetime(2024, 4, 22, 15, 30, 30)
        self.balcon_verification.update_safely(cdate=datetime(2024, 4, 22, 15, 30, 30))

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_called_once_with(
            verification_id=self.balcon_verification.id,
            customer_id=self.customer.id
        )

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    @patch('django.utils.timezone.now')
    def test_fetch_balcon_fdc_data_for_customer_before_start_date(
        self, mock_now, mock_fetch_fdc_data_task
    ):
        mock_now.return_value = datetime(2024, 4, 22, 15, 30, 30)
        self.balcon_verification.update_safely(cdate=datetime(2024, 4, 10, 15, 30, 30))

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_not_called()

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    @patch('django.utils.timezone.now')
    def test_fetch_balcon_fdc_data_for_customer_loan_paid_off(
        self, mock_now, mock_fetch_fdc_data_task
    ):
        mock_now.return_value = datetime(2024, 4, 22, 15, 30, 30)
        self.balcon_verification.update_safely(cdate=datetime(2024, 4, 22, 15, 30, 30))
        self.balcon_verification.loan.update_safely(
            loan_status=StatusLookupFactory(
                status_code=LoanStatusCodes.PAID_OFF
            )
        )

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_not_called()

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    @patch('django.utils.timezone.now')
    def test_fetch_balcon_fdc_data_for_customer_not_payment_due_date(
        self, mock_now, mock_fetch_fdc_data_task
    ):
        mock_now.return_value = datetime(2024, 4, 25, 15, 30, 30)
        self.balcon_verification.update_safely(cdate=datetime(2024, 4, 22, 15, 30, 30))

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_not_called()

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    @patch('django.utils.timezone.now')
    def test_fetch_balcon_fdc_data_for_unpunished_customer(
        self, mock_now, mock_fetch_fdc_data_task
    ):
        mock_now.return_value = datetime(2024, 4, 22, 15, 30, 30)
        self.balcon_verification.update_safely(cdate=datetime(2024, 4, 22, 15, 30, 30))

        fdc_inquiry_loan = FDCInquiryLoanFactory(
            status_pinjaman='Outstanding',
            id_penyelenggara=self.fintech.id
        )
        BalanceConsolidationDelinquentFDCCheckingFactory(
            customer_id=self.customer.id,
            balance_consolidation_verification=self.balcon_verification,
            invalid_fdc_inquiry_loan_id=fdc_inquiry_loan.id,
            is_punishment_triggered=False
        )

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_called_once_with(
            verification_id=self.balcon_verification.id,
            customer_id=self.customer.id
        )

    @patch(f'{PACKAGE_NAME}.fetch_balance_consolidation_fdc_data_for_customer.delay')
    @patch('django.utils.timezone.now')
    def test_fetch_balcon_fdc_data_for_punished_customer(
        self, mock_now, mock_fetch_fdc_data_task
    ):
        mock_now.return_value = datetime(2024, 4, 22, 15, 30, 30)
        self.balcon_verification.update_safely(cdate=datetime(2024, 4, 22, 15, 30, 30))

        fdc_inquiry_loan = FDCInquiryLoanFactory(
            status_pinjaman='Outstanding',
            id_penyelenggara=self.fintech.id
        )
        BalanceConsolidationDelinquentFDCCheckingFactory(
            customer_id=self.customer.id,
            balance_consolidation_verification=self.balcon_verification,
            invalid_fdc_inquiry_loan_id=fdc_inquiry_loan.id,
            is_punishment_triggered=True
        )

        fetch_balance_consolidation_fdc_data()
        mock_fetch_fdc_data_task.assert_not_called()

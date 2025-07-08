from mock import patch

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    ImageFactory,
    ApplicationFactory,
    LoanFactory,
)
from juloserver.julo.statuses import (
    CreditCardCodes,
    LoanStatusCodes,
)

from juloserver.account.tests.factories import (
    AccountFactory,
    AddressFactory,
)

from juloserver.credit_card.tests.factiories import (
    CreditCardFactory,
    CreditCardApplicationFactory,
    CreditCardStatusFactory,
    CreditCardTransactionFactory,
)
from juloserver.credit_card.tasks.notification_tasks import (
    send_pn_incorrect_pin_warning,
    send_pn_change_tenor,
    send_pn_status_changed,
    send_pn_inform_first_transaction_cashback,
    send_pn_obtained_first_transaction_cashback,
    send_pn_transaction_completed,
)
from juloserver.credit_card.constants import (
    CreditCardStatusConstant,
    BSSTransactionConstant,
)

from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeTypeConst,
)
from juloserver.promo.tests.factories import (
    PromoCodeBenefitFactory,
    PromoCodeFactory,
)


class TestPushNotification(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED),
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=ImageFactory(image_source=3332, image_type='selfie'),
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.ASSIGNED
            ),
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="test ben",
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={
                'max_cashback': 200000,
                'percent': 50
            },
        )
        PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            promo_name='JULOCARDCASHBACK',
            promo_code='JULOCARDCASHBACK',
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
        )

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_send_incorrect_pin_wrong_pn_task(self, mock_get_julo_pn_client):
        send_pn_incorrect_pin_warning(self.customer.id)
        assert mock_get_julo_pn_client.return_value.credit_card_notification.called

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_send_change_tenor_pn_task(self, mock_get_julo_pn_client):
        send_pn_change_tenor(self.customer.id)
        assert mock_get_julo_pn_client.return_value.credit_card_notification.called

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_send_status_change_pn_task(self, mock_get_julo_pn_client):
        send_pn_status_changed(self.customer.id, CreditCardCodes.CARD_BLOCKED)
        assert mock_get_julo_pn_client.return_value.credit_card_notification.called

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_inform_first_transaction_cashback_should_success(self, mock_get_julo_pn_client):
        send_pn_inform_first_transaction_cashback(
            self.credit_card_application.id,
            self.fixed_cash_benefit.value.get('percent'),
            self.fixed_cash_benefit.value.get('max_cashback')
        )
        assert mock_get_julo_pn_client.return_value.credit_card_notification.called

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_inform_first_transaction_cashback_should_failed_when_already_do_transaction(
            self, mock_get_julo_pn_client
    ):
        loan = LoanFactory(
            account=self.account,
            disbursement_id=888,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            transaction_method_id=10,
        )
        CreditCardTransactionFactory(
            loan=loan,
            amount=1000000,
            fee=5000,
            transaction_date=timezone.localtime(timezone.now()),
            reference_number='001',
            bank_reference='bank',
            terminal_type='terminal_type',
            terminal_id='t01',
            terminal_location='bandung',
            merchant_id='a001',
            acquire_bank_code='1234',
            destination_bank_code='bca',
            destination_account_number='12314',
            destination_account_name='ani',
            biller_code='341',
            biller_name='abc',
            customer_id='014312',
            hash_code='er23423rdasasfse',
            transaction_status="success",
            transaction_type=BSSTransactionConstant.EDC,
            credit_card_application=self.credit_card_application,
        )
        send_pn_inform_first_transaction_cashback(
            self.credit_card_application.id,
            self.fixed_cash_benefit.value.get('percent'),
            self.fixed_cash_benefit.value.get('max_cashback')
        )
        assert mock_get_julo_pn_client.return_value.credit_card_notification.not_called

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_obtained_first_transaction_cashback_should_success(self, mock_get_julo_pn_client):
        send_pn_obtained_first_transaction_cashback(self.customer.id)
        assert mock_get_julo_pn_client.return_value.credit_card_notification.called

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    def test_send_transaction_completed_pn_task_should_success(self, mock_get_julo_pn_client):
        loan = LoanFactory(
            account=self.account,
            disbursement_id=888,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            transaction_method_id=10,
            loan_duration=1,
            loan_xid=33333333,
        )
        send_pn_transaction_completed(self.customer.id, loan.loan_duration, loan.loan_xid)
        assert mock_get_julo_pn_client.return_value.credit_card_notification.called

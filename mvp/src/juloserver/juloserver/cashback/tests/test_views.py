from datetime import (
    timedelta,
    datetime,
    date,
)
from unittest.mock import patch

from dateutil import parser
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from django.test.utils import override_settings
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.cashback import ERROR_MESSAGE_TEMPLATE_4
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    AuthUserFactory,
    StatusLookupFactory,
    WorkflowFactory,
    FeatureSettingFactory,
    ApplicationFactory,
    CustomerWalletHistoryFactory,
    CashbackTransferTransactionFactory,
    BankFactory,
    MobileFeatureSettingFactory,
    ProductLineFactory,
    ImageFactory,
    ExperimentSettingFactory,
    ExperimentFactory,
    ExperimentTestGroupFactory,
)
from juloserver.disbursement.exceptions import GopayServiceError
from juloserver.julo.models import (
    Customer,
    SepulsaProduct,
    SepulsaTransaction,
)
from juloserver.pin.tests.test_views import new_julo1_product_line
from juloserver.julo.exceptions import JuloException, DuplicateCashbackTransaction, \
    BlockedDeductionCashback
from juloserver.julo.constants import FeatureNameConst, MobileFeatureNameConst, WorkflowConst
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.cfs.tests.factories import (
    AgentFactory,
    PdClcsPrimeResultFactory,
    CfsTierFactory,
    CashbackBalanceFactory,
)
from juloserver.cashback.tests.factories import CashbackEarnedFactory
from juloserver.cashback.constants import OverpaidConsts, CashbackChangeReason
from juloserver.cashback.models import CashbackOverpaidVerification
from juloserver.cashback.services import process_decision_overpaid_case


PACKAGE_NAME = 'juloserver.cashback.views.api_views'


@override_settings(CELERY_ALWAYS_EAGER = True)
@override_settings(BROKER_BACKEND = 'memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCashBackToGopay(APITestCase):
    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c, mock_d, mock_e):
        self.client = APIClient()
        user_data = {
            "username": "1599110506026781",
            "pin": "122446",
            "email": "asdf123@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
            'manufacturer': 'test',
            'model': 'test'
        }
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry'
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id',
            value="#nth:-1:1",
            experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={'max_wait_time_mins': 60, 'max_retry_count': 3}
        )
        response = self.client.post('/api/pin/v1/register', data=user_data)
        self.customer = Customer.objects.get(email="asdf123@gmail.com")
        self.application = self.customer.application_set.regular_not_deletes().last()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.customer.user.auth_expiry_token.key)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                "gopay": {"is_active": True},
                "xendit": {"is_active": True},
                "payment": {"is_active": True},
                "sepulsa": {"is_active": True}
            }
        )

    @patch('juloserver.cashback.views.api_views.GopayService')
    def test_gopay_service_error(self, mock_gopay_service):
        mock_gopay_service().process_cashback_to_gopay.side_effect = GopayServiceError()
        data = {
            'pin': 122446,
            'mobile_phone_number': '08987893218',
            'cashback_nominal': 100000
        }
        response = self.client.post('/api/cashback/v1/gopay', data=data)
        self.assertEqual(response.status_code, 400)

    def test_cashback_feature_off(self):
        data = {
            'pin': 122446,
            'mobile_phone_number': '08987893218',
            'cashback_nominal': 100000
        }
        self.cashback_feature.parameters = {"gopay": {"is_active": False}}
        self.cashback_feature.save()
        response = self.client.post('/api/cashback/v1/gopay', data=data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.cashback.views.api_views.GopayService')
    def test_gopay_service_success(self, mock_gopay_service):
        mock_gopay_service().process_cashback_to_gopay.return_value = 'success'
        data = {
            'pin': 122446,
            'mobile_phone_number': '08987893218',
            'cashback_nominal': 100000
        }
        response = self.client.post('/api/cashback/v1/gopay', data=data)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.cashback.views.api_views.GopayService')
    def test_gopay_service_success_julover(self, mock_gopay_service):
        mock_gopay_service().process_cashback_to_gopay.return_value = 'success'
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.application_status = application_status
        self.application.workflow = julover_workflow
        self.application.product_line = product_line
        self.application.save()

        data = {
            'pin': 122446,
            'mobile_phone_number': '08987893218',
            'cashback_nominal': 100000
        }
        response = self.client.post('/api/cashback/v1/gopay', data=data)
        self.assertEqual(response.status_code, 200)

    def test_gopay_with_overpaid_case(self):
        # triggers signal to create an unprocessed Overpaid Case
        # unprocessed
        CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available_old=20000,
            wallet_balance_available=20000 + OverpaidConsts.MINIMUM_AMOUNT,
        )
        data = {
            'pin': 122446,
            'mobile_phone_number': '08987893218',
            'cashback_nominal': 100000,
        }
        response = self.client.post('/api/cashback/v1/gopay', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], OverpaidConsts.Message.CASHBACK_LOCKED)

@override_settings(CELERY_ALWAYS_EAGER = True)
@override_settings(BROKER_BACKEND = 'memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCashbackPayment(APITestCase):
    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client = APIClient()
        user_data = {
            "username": "1599110506026781",
            "pin": "122446",
            "email": "asdf123@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
            'manufacturer': 'test',
            'model': 'test'
        }
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry'
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id',
            value="#nth:-1:1",
            experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={'max_wait_time_mins': 60, 'max_retry_count': 3}
        )
        self.client.post('/api/pin/v1/register', data=user_data)
        self.customer = Customer.objects.get(email="asdf123@gmail.com")
        self.application = self.customer.application_set.regular_not_deletes().last()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.customer.user.auth_expiry_token.key)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                "payment": {"is_active": True},
            }
        )

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_status_failed(self, mock_get_cashback_redemption_service):
        data = {
            'pin': 122446
        }
        mock_get_cashback_redemption_service.pay_next_loan_payment.return_value = None
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_exception(self, mock_get_cashback_redemption_service):
        data = {
            'pin': 122446
        }
        mock_get_cashback_redemption_service.pay_next_loan_payment.side_effect = (
            Exception()
        )
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 400)

        mock_get_cashback_redemption_service.pay_next_loan_payment.side_effect = (
            DuplicateCashbackTransaction()
        )
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'][0],
            'Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi.'
        )

        mock_get_cashback_redemption_service.pay_next_loan_payment.side_effect = \
            BlockedDeductionCashback()
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            response.data['errors'][0],
            'Mohon maaf, saat ini cashback tidak bisa digunakan karena program keringanan'
        )

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_success(self, mock_get_cashback_redemption_service):
        data = {
            'pin': 122446
        }
        mock_get_cashback_redemption_service.pay_next_loan_payment.return_value = 'completed'
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_success_julover(self, mock_get_cashback_redemption_service):
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.application_status = application_status
        self.application.workflow = julover_workflow
        self.application.product_line = product_line
        self.application.save()
        data = {
            'pin': 122446
        }
        mock_get_cashback_redemption_service.pay_next_loan_payment.return_value = 'completed'
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 200)

    def test_payment_with_overpaid_case(self):
        # triggers signal to create an unprocessed Overpaid Case
        # unprocessed
        CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available_old=20000,
            wallet_balance_available=20000 + OverpaidConsts.MINIMUM_AMOUNT,
        )
        data = {
            'pin': 122446
        }
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], OverpaidConsts.Message.CASHBACK_LOCKED)

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_payment_case_no_active_loan(self, mock_get_cashback_redemption_service):
        mock_get_cashback_redemption_service.pay_next_loan_payment.return_value = False
        data = {
            'pin': 122446
        }
        response = self.client.post('/api/cashback/v1/payment', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], ERROR_MESSAGE_TEMPLATE_4)


@override_settings(CELERY_ALWAYS_EAGER = True)
@override_settings(BROKER_BACKEND = 'memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCashbackSepulsa(APITestCase):
    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client = APIClient()
        user_data = {
            "username": "1599110506026781",
            "pin": "122446",
            "email": "asdf123@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
            'manufacturer': 'test',
            'model': 'test'
        }
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry'
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id',
            value="#nth:-1:1",
            experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={'max_wait_time_mins': 60, 'max_retry_count': 3}
        )
        response = self.client.post('/api/pin/v1/register', data=user_data)
        self.customer = Customer.objects.get(email="asdf123@gmail.com")
        self.application = self.customer.application_set.regular_not_deletes().last()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.customer.user.auth_expiry_token.key)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                "sepulsa": {"is_active": True}
            }
        )

    def test_cashback_feature_off(self):
        data = {
            'pin': 122446,
            'phone_number': '09993213321',
            'product_id': 111111,
            'meter_number': '21312312',
            'account_name': 'Tessssttt',
        }
        self.cashback_feature.parameters = {"sepulsa": {"is_active": False}}
        self.cashback_feature.save()
        response = self.client.post('/api/cashback/v1/sepulsa', data=data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_exception(self, mock_get_cashback_redemption_service):
        data = {
            'pin': 122446,
            'phone_number': '09993213321',
            'product_id': 111111,
            'meter_number': '21312312',
            'account_name': 'Tessssttt',
        }
        mock_get_cashback_redemption_service.trigger_partner_purchase.side_effect = JuloException()
        response = self.client.post('/api/cashback/v1/sepulsa', data=data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_success(self, mock_get_cashback_redemption_service):
        data = {
            'pin': 122446,
            'phone_number': '09993213321',
            'product_id': 111111,
            'meter_number': '21312312',
            'account_name': 'Tessssttt',
        }
        product = SepulsaProduct(id=1)
        sepulsa_transaction = SepulsaTransaction(
            id=1,
            product=product,
            customer=self.customer
        )
        mock_get_cashback_redemption_service.trigger_partner_purchase.return_value = \
            product, sepulsa_transaction, 10000
        response = self.client.post('/api/cashback/v1/sepulsa', data=data)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_success_julover(self, mock_get_cashback_redemption_service):
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.application_status = application_status
        self.application.workflow = julover_workflow
        self.application.product_line = product_line
        self.application.save()
        data = {
            'pin': 122446,
            'phone_number': '09993213321',
            'product_id': 111111,
            'meter_number': '21312312',
            'account_name': 'Tessssttt',
        }
        product = SepulsaProduct(id=1)
        sepulsa_transaction = SepulsaTransaction(
            id=1,
            product=product,
            customer=self.customer
        )
        mock_get_cashback_redemption_service.trigger_partner_purchase.return_value = \
            product, sepulsa_transaction, 10000
        response = self.client.post('/api/cashback/v1/sepulsa', data=data)
        self.assertEqual(response.status_code, 200)


    def test_selpusa_with_overpaid_case(self):
        # triggers signal to create an unprocessed Overpaid Case
        # unprocessed
        CustomerWalletHistoryFactory(
            customer=self.customer,
            application=self.application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available_old=20000,
            wallet_balance_available=20000 + OverpaidConsts.MINIMUM_AMOUNT,
        )
        data = {
            'pin': 122446,
            'phone_number': '09993213321',
            'product_id': 111111,
            'meter_number': '21312312',
            'account_name': 'Ned Stark',
        }
        response = self.client.post('/api/cashback/v1/sepulsa', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], OverpaidConsts.Message.CASHBACK_LOCKED)


@override_settings(CELERY_ALWAYS_EAGER = True)
@override_settings(BROKER_BACKEND = 'memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS = True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCashbackTransfer(APITestCase):
    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.pin.services.process_application_status_change')
    @patch('juloserver.pin.serializers.get_latest_app_version', return_value='2.2.2')
    def setUp(self, mock_a, mock_b, mock_c):
        self.client = APIClient()
        user_data = {
            "username": "1599110506026781",
            "pin": "122446",
            "email": "asdf123@gmail.com",
            "gcm_reg_id": "1231",
            "android_id": "1231",
            "latitude": 0.0,
            "longitude": 0.0,
            'appsflyer_device_id': 'sfsd',
            'advertising_id': 'test',
            'manufacturer': 'test',
            'model': 'test'
        }
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry'
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id',
            value="#nth:-1:1",
            experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            feature_name='pin_setting',
            parameters={'max_wait_time_mins': 60, 'max_retry_count': 3}
        )
        response = self.client.post('/api/pin/v1/register', data=user_data)
        self.customer = Customer.objects.get(email="asdf123@gmail.com")
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.customer.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 190
        self.application.save()
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.cashback_transfer_transaction = CashbackTransferTransactionFactory()
        self.bank = BankFactory()
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                "xendit": {"is_active": True},
            }
        )

    def test_amount_lt_min_transfer(self):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 43000
        self.customer_wallet_history.save()

        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})
        assert response.status_code == 400
        assert response.json()['errors'] == [
            'Mohon maaf, saldo cashback anda tidak cukup untuk melakukan pencairan, '
            'minimal saldo Rp 44.000']

    def test_cashback_transfer_have_current_cashback_transfer(self):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 44000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=44000)
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'not_final_statuses'
        self.cashback_transfer_transaction.bank_code = 'not_gopay'
        self.cashback_transfer_transaction.save()

        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 400
        assert response.json()['errors'] == [
            'Mohon maaf, Anda tidak dapat melakukan request cashback, silahkan '
            'tunggu sampai request cashback sebelumnya berhasil diproses.']

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_cashback_transferA_success_case_1(
            self, mock_get_cashback_redemption_service):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 74000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=74000)
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.bank.bank_code = '014'
        self.bank.save()

        mock_get_cashback_redemption_service.transfer_cashback.return_value = True
        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 200

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_cashback_transfer_success_case_2(
            self, mock_get_cashback_redemption_service):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 75000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=75000)
        self.customer_wallet_history.change_reason = 'Promo: test'
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.bank.bank_code = '008'
        self.bank.save()

        mock_get_cashback_redemption_service.transfer_cashback.return_value = True
        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 200

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_cashback_transfer_off(
            self, mock_get_cashback_redemption_service):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 75000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=75000)
        self.customer_wallet_history.change_reason = 'Promo: test'
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.bank.bank_code = '008'
        self.bank.save()

        self.cashback_feature.parameters = {"xendit": {"is_active": False}}
        self.cashback_feature.save()
        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 200

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_cashback_transfer_off(
            self, mock_get_cashback_redemption_service):

        self.application.save()
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 75000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=75000)
        self.customer_wallet_history.change_reason = 'Promo: test'
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.application_status = application_status
        self.application.workflow = julover_workflow
        self.application.product_line = product_line
        self.application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.bank.bank_code = '008'
        self.bank.save()

        self.cashback_feature.parameters = {"xendit": {"is_active": False}}
        self.cashback_feature.save()
        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 400

    @patch('juloserver.cashback.views.api_views.cashback_redemption_service')
    def test_cashback_transfer_cashback_transfer_failed(
            self, mock_get_cashback_redemption_service):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 75000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=75000)
        self.customer_wallet_history.change_reason = 'Promo: test'
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        self.application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.application.name_in_bank = 'test'
        self.application.bank_account_number = '123456'
        self.application.save()

        self.bank.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.bank.bank_code = '008'
        self.bank.save()

        mock_get_cashback_redemption_service.return_value.transfer_cashback.side_effect = Exception()
        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 200

    def test_cashback_transfer_transaction_creation_failed(self):
        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.wallet_balance_available = 44000
        self.customer_wallet_history.cashback_earned = CashbackEarnedFactory(current_balance=44000)
        self.customer_wallet_history.save()

        self.cashback_transfer_transaction.customer_id = self.customer.id
        self.cashback_transfer_transaction.transfer_status = 'COMPLETED'
        self.cashback_transfer_transaction.bank_code = 'gopay'
        self.cashback_transfer_transaction.save()

        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})

        assert response.status_code == 400
        assert response.json()['errors'] == [
            'Mohon maaf, terjadi kendala dalam proses pengajuan pencairan '
            'cashback, Silakan coba beberapa saat lagi.']

    def test_transfer_unprocessed_overpaid_exists(self):
        application = self.customer.application_set.regular_not_deletes().last()
        # triggers signal to create an unprocessed Overpaid Case
        # unprocessed
        CustomerWalletHistoryFactory(
            customer=self.customer,
            application=application,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            wallet_balance_available_old=20000,
            wallet_balance_available=20000 + OverpaidConsts.MINIMUM_AMOUNT,
        )
        response = self.client.post('/api/cashback/v1/xendit', data={'pin': 122446})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], OverpaidConsts.Message.CASHBACK_LOCKED)


class TestCashbackInformation(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' +
                                                   self.customer.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)
        self.account = AccountFactory(customer=self.customer)
        self.today = timezone.localtime(timezone.now()).date()
        CfsTierFactory(id=1, name='Starter', point=100)
        CfsTierFactory(id=2, name='Advanced', point=300)
        CfsTierFactory(id=3, name='Pro', point=600)
        CfsTierFactory(id=4, name='Champion', point=1000)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                'payment': {
                    'is_active': True,
                    'tag_info': {}
                },
                'xendit': {
                    'is_active': True,
                    'tag_info': {},
                },
                'sepulsa': {
                    'is_active': True,
                    'tag_info': {},
                },
                'gopay': {
                    'is_active': True,
                    'tag_info': {},
                },
                'tada': {
                    'is_active': True,
                    'tag_info': {
                        "name": "Akan datang",
                        "is_active": True,
                        "description": {
                            'title': 'Belum tersedia',
                            'message': 'Fitur masih belum tersedia saat ini'
                        }
                    }
                }
            }
        )

    @patch(f'{PACKAGE_NAME}.get_expired_date_and_cashback')
    @patch.object(timezone, 'now')
    def test_get_cashback_information(self, mock_now, mock_get_expired_date_and_cashback):
        mock_now.return_value = datetime(2020, 1, 1, 0, 0, 0)
        mock_get_expired_date_and_cashback.return_value = date(2020, 1, 2), 12000
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            is_active=True,
            parameters={'reminder_days': 1}
        )
        response = self.client.get('/api/cashback/v1/information')
        self.assertEqual(response.status_code, 200, response.content)

        json_data = response.json()
        self.assertEqual(12000, json_data['data']['cashback_amount'])
        self.assertEqual('2020-01-02', json_data['data']['cashback_expiry_date'])

    @patch(f'{PACKAGE_NAME}.get_expired_date_and_cashback')
    def test_get_cashback_information_no_expired_cashback(self, mock_get_expired_date_and_cashback):
        mock_get_expired_date_and_cashback.return_value = None, 0
        response = self.client.get('/api/cashback/v1/information')
        self.assertEqual(response.status_code, 200)

        json_data = response.json()
        self.assertIsNone(json_data['data'])

    @patch(f'{PACKAGE_NAME}.get_expired_date_and_cashback')
    @patch.object(timezone, 'now')
    def test_get_cashback_information_not_time_yet(self, mock_now, mock_get_expired_date_and_cashback):
        mock_now.return_value = datetime(2020, 1, 1, 0, 0, 0)
        mock_get_expired_date_and_cashback.return_value = date(2020, 1, 3), 12000
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            is_active=True,
            parameters={'reminder_days': 1}
        )
        response = self.client.get('/api/cashback/v1/information')
        self.assertEqual(response.status_code, 200, response.content)

        json_data = response.json()
        self.assertIsNone(json_data['data'])

    @patch(f'{PACKAGE_NAME}.get_expired_date_and_cashback')
    def test_get_cashback_information_no_expired_cashback(self, mock_get_expired_date_and_cashback):
        mock_get_expired_date_and_cashback.return_value = date(2020, 1, 2), 0
        response = self.client.get('/api/cashback/v1/information')
        self.assertEqual(response.status_code, 200)

        json_data = response.json()
        self.assertIsNone(json_data['data'])

    def test_cashback_options_info(self):
        today = timezone.localtime(timezone.now()).date()
        self.application.application_status_id = 190
        self.application.save()
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        response = self.client.get('/api/cashback/v1/options_info')
        self.assertEqual(response.status_code, 200)

    def test_cashback_options_info_v2(self):
        today = timezone.localtime(timezone.now()).date()
        self.application.application_status_id = 190
        self.application.save()
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        response = self.client.get('/api/cashback/v2/options_info')
        self.assertEqual(response.status_code, 200)
        json_response = response.json()
        self.assertTrue(json_response['data']['tada']['is_active'])
        self.assertEqual(json_response['data']['tada']['tag_info']['name'], 'Akan datang')
        self.assertEqual(json_response['data']['tada']['tag_info']['description'], {
            'title': 'Belum tersedia',
            'message': 'Fitur masih belum tersedia saat ini'
        })

    def test_cashback_options_info_with_mtl_user(self):
        client = APIClient()
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        client.credentials(HTTP_AUTHORIZATION='Token ' + customer.user.auth_expiry_token.key)
        application = ApplicationFactory(customer=customer)
        product_line = ProductLineFactory()
        product_line.product_line_code = ProductLineCodes.MTL1
        product_line.save()
        application.product_line = product_line
        application.save()
        today = timezone.localtime(timezone.now()).date()
        PdCreditModelResultFactory(application_id=application.id, pgood=0.8)
        PdClcsPrimeResultFactory(
            customer_id=customer.id, partition_date=today, clcs_prime_score=0.5
        )
        response = client.get('/api/cashback/v1/options_info')
        response_json = response.json()['data']
        self.assertEqual(response_json['xendit_enable'], True)
        self.assertEqual(response_json['sepulsa_enable'], True)
        self.assertEqual(response_json['gopay_enable'], True)

    def test_cashback_options_info_julover(self):
        client = APIClient()
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        client.credentials(HTTP_AUTHORIZATION='Token ' + customer.user.auth_expiry_token.key)
        application = ApplicationFactory(customer=customer)
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        application.workflow = julover_workflow
        application.application_status = application_status
        product_line.save()
        application.product_line = product_line
        application.save()
        today = timezone.localtime(timezone.now()).date()
        response = client.get('/api/cashback/v1/options_info')
        self.assertEqual(response.status_code, 200)
        response_json = response.json()['data']
        self.assertEqual(response_json['payment_enable'], False)
        self.assertEqual(response_json['xendit_enable'], True)
        self.assertEqual(response_json['sepulsa_enable'], True)
        self.assertEqual(response_json['gopay_enable'], True)

    @patch('juloserver.cashback.services.get_cashback_claim_experiment')
    def test_cashback_faqs(self, mock_cashback_claim_experiment):
        self.feature_setting = MobileFeatureSettingFactory(
            is_active=True,
            feature_name=MobileFeatureNameConst.CASHBACK_FAQS,
            parameters={
                'faqs': {
                    'header': 'test header',
                    'topics': [{'question': 'test no 1 question', 'answer': 'test no 1 answer'}],
                }
            },
        )

        self.feature_setting.save()
        mock_cashback_claim_experiment.return_value = (None, False)

        response = self.client.get(
            '/api/v2/mobile/feature-settings',
            {'feature_name': MobileFeatureNameConst.CASHBACK_FAQS},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['content']['paramater'],
            {
                'faqs': {
                    'header': 'test header',
                    'topics': [{'question': 'test no 1 question', 'answer': 'test no 1 answer'}],
                }
            },
        )

        # case cashback claim experiment
        self.feature_setting_experiment = MobileFeatureSettingFactory(
            is_active=True,
            feature_name=MobileFeatureNameConst.CASHBACK_CLAIM_FAQS,
            parameters={
                'faqs': {
                    'header': 'test header experiment',
                    'topics': [
                        {
                            'question': 'test no 1 question experiment',
                            'answer': 'test no 1 answer experiment',
                        }
                    ],
                }
            },
        )

        self.feature_setting_experiment.save()
        mock_cashback_claim_experiment.return_value = (None, True)

        response = self.client.get(
            '/api/v2/mobile/feature-settings',
            {'feature_name': MobileFeatureNameConst.CASHBACK_FAQS},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['content']['paramater'],
            {
                'faqs': {
                    'header': 'test header experiment',
                    'topics': [
                        {
                            'question': 'test no 1 question experiment',
                            'answer': 'test no 1 answer experiment',
                        }
                    ],
                }
            },
        )


class TestCashbackOptionsInfo(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.customer.user.auth_expiry_token.key)
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.cashback_balance = CashbackBalanceFactory(customer=self.customer, cashback_balance=10000)
        CfsTierFactory(id=1, name='Starter', point=0, pencairan_cashback=True)
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.9)
        self.cashback_feature = FeatureSettingFactory(
            feature_name='cashback',
            is_active=True,
            parameters={
                'payment': {
                    'is_active': True,
                    'tag_info': {}
                },
                'xendit': {
                    'is_active': True,
                    'tag_info': {},
                },
                'sepulsa': {
                    'is_active': True,
                    'tag_info': {},
                },
                'gopay': {
                    'is_active': True,
                    'tag_info': {},
                },
            }
        )

    @patch('juloserver.cashback.services.get_cashback_expiry_info')
    def test_options_info_does_not_have_expiry_info(self, mock_get_cashback_expiry_info):
        mock_get_cashback_expiry_info.return_value = None
        response = self.client.get('/api/cashback/v1/options_info')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['data']['expiry_info'])

    @patch('juloserver.cashback.services.get_cashback_expiry_info')
    def test_options_info_has_expiry_info(self, mock_get_cashback_expiry_info):
        mock_get_cashback_expiry_info.return_value = "Expiry Info"
        response = self.client.get('/api/cashback/v1/options_info')

        self.assertEqual(response.status_code, 200)
        self.assertEqual("Expiry Info", response.json()['data']['expiry_info'])

    @patch('juloserver.cashback.services.get_cashback_expiry_info')
    def test_key_error_when_remove_cashback_option(self, mock_get_cashback_expiry_info):
        mock_get_cashback_expiry_info.return_value = "Expiry Info"
        response = self.client.get('/api/cashback/v2/options_info')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['data'].get('tada'))


class TestCashbackOverpaid(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' +
                                                   self.customer.user.auth_expiry_token.key)
        self.application = ApplicationJ1Factory(
            customer=self.customer, name_in_bank='tom hanks',
        )
        self.cashback_balance = CashbackBalanceFactory(
            customer=self.customer, status=CashbackBalanceStatusConstant.UNFREEZE
        )
        self.customer.change_wallet_balance(50000, 50000, CashbackChangeReason.CASHBACK_OVER_PAID)
        self.customer.change_wallet_balance(40000, 40000, CashbackChangeReason.CASHBACK_OVER_PAID)
        cases = CashbackOverpaidVerification.objects.filter(
            customer=self.customer
        ).order_by('id').all()
        self.case_1 = cases[0]
        self.case_2 = cases[1]
        self.case_2.status = OverpaidConsts.Statuses.REJECTED
        self.case_2.save()
        self.bank = BankFactory()

    def test_submit_overpaid(self):
        image_1 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )
        image_2 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )

        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                },
                {
                    "case_id": self.case_2.id,
                    "image_id": image_2.id,
                },
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.case_1.refresh_from_db()
        self.case_2.refresh_from_db()
        self.assertEqual(self.case_1.status, OverpaidConsts.Statuses.PENDING)
        self.assertEqual(self.case_2.status, OverpaidConsts.Statuses.PENDING)
        self.assertEqual(self.customer.wallet_balance_available, 0)

    def test_submit_overpaid_case_duplicate_images(self):
        image_1 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )

        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                },
                {
                    "case_id": self.case_2.id,
                    "image_id": image_1.id,
                },
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_submit_overpaid_case_duplicate_case_id(self):
        image_1 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )
        image_2 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )

        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                },
                {
                    "case_id": self.case_1.id,
                    "image_id": image_2.id,
                },
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_submit_overpaid_case_unauthorized_data(self):
        # Image belong to different customer
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationJ1Factory(customer=customer)
        image_1 = ImageFactory(
            image_source=application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )
        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                }
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        # Overpaid case belongs to different customer
        image_1.update_safely(image_source=self.application.id)
        customer.change_wallet_balance(20000, 20000, CashbackChangeReason.CASHBACK_OVER_PAID)
        overpaid_case = CashbackOverpaidVerification.objects.filter(customer=customer).last()
        payload = {
            'overpaid_cases': [
                {
                    "case_id": overpaid_case.id,
                    "image_id": image_1.id,
                }
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_submit_overpaid_case_pending_or_accepted(self):
        self.case_1.status = OverpaidConsts.Statuses.ACCEPTED
        self.case_2.status = OverpaidConsts.Statuses.UNPROCESSED
        self.case_1.save()
        self.case_2.save()
        image_1 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )
        image_2 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )

        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                },
                {
                    "case_id": self.case_2.id,
                    "image_id": image_2.id,
                },
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.case_1.refresh_from_db()
        self.case_2.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.case_2.image, image_2)
        self.assertIsNone(self.case_1.image)

    def test_submit_overpaid_no_valid_cases(self):
        self.case_1.status = OverpaidConsts.Statuses.ACCEPTED
        old_status = self.case_1.status
        self.case_1.save()
        image_1 = ImageFactory(
            image_source=self.application.id, image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT
        )

        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                },
            ]
        }
        response = self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')
        self.case_1.refresh_from_db()
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.case_1.status, old_status)

    def test_signal_overpaid_generation(self):
        # These 2 won't trigger
        self.wallet_history_3 = CustomerWalletHistoryFactory(
            customer=self.customer,
            change_reason="cashback_over_paid_something",
            application=self.application,
            wallet_balance_available_old=50000,
            wallet_balance_available=90000,
        )
        self.wallet_history_4 = CustomerWalletHistoryFactory(
            customer=self.customer,
            change_reason=CashbackChangeReason.CASHBACK_OVER_PAID,
            application=self.application,
            wallet_balance_available_old=90000,
            wallet_balance_available=90000 + OverpaidConsts.MINIMUM_AMOUNT - 200,
        )
        cases = CashbackOverpaidVerification.objects.filter(
            customer=self.customer,
        ).order_by('cdate')

        self.assertEqual(cases.count(), 2) # only history 1 & 2
        self.assertEqual(cases[0].overpaid_amount, self.case_1.overpaid_amount)
        self.assertEqual(cases[1].overpaid_amount, self.case_2.overpaid_amount)

    def test_get_overpaid_cases_zero_amount(self):
        self.case_1.update_safely(overpaid_amount=0)
        self.case_2.update_safely(overpaid_amount=0)
        response = self.client.get('/api/cashback/v1/overpaid_verification')
        response_json = response.json()['data']
        self.assertEqual(response_json['overpaid_cases'], [])

    def test_get_overpaid_cases(self):
        self.case_1.cdate = parser.parse('2020-12-21 00:00+00:00')
        self.case_1.save()
        self.case_1.refresh_from_db()
        self.case_2.status = OverpaidConsts.Statuses.ACCEPTED
        self.case_2.save()
        self.customer.change_wallet_balance(40000, 40000, CashbackChangeReason.CASHBACK_OVER_PAID)
        case_3 = CashbackOverpaidVerification.objects.last()
        case_3.status = OverpaidConsts.Statuses.REJECTED
        case_3.save()
        case_3.refresh_from_db()

        expected_response = [
            {
                'case_id': self.case_1.id,
                'time': timezone.localtime(self.case_1.cdate).isoformat(),
                'amount': 50000,
            },
            {
                'case_id': case_3.id,
                'time': timezone.localtime(case_3.cdate).isoformat(),
                'amount': 40000,
            },
        ]
        response = self.client.get('/api/cashback/v1/overpaid_verification')
        response_json = response.json()['data']
        self.assertEqual(response_json['overpaid_cases'], expected_response)

    def test_process_decision_case_not_pending(self):
        agent = AgentFactory(user=self.user)
        note = "test"
        decision = OverpaidConsts.Statuses.ACCEPTED
        cashback_amount_old = self.case_2.customer.wallet_balance_available
        process_decision_overpaid_case(self.case_2.id, agent, note, decision)

        self.case_2.refresh_from_db()
        cashback_amount_new = self.case_2.customer.wallet_balance_available
        history = self.case_2.overpaid_history.last()
        self.assertEqual(history.processed_status, OverpaidConsts.Statuses.PROCESSING_FAILED)
        self.assertEqual(cashback_amount_old, cashback_amount_new)
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 0)

    @patch('juloserver.cashback.services.is_graduate_of')
    def test_process_decision_case_champion(self, mock_is_champion):
        mock_is_champion.return_value = True
        agent = AgentFactory(user=self.user)
        note = "test"

        #  verifying overpaid
        image_1 = ImageFactory(image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT)
        image_2 = ImageFactory(image_type=OverpaidConsts.ImageType.PAYMENT_RECEIPT)
        payload = {
            'overpaid_cases': [
                {
                    "case_id": self.case_1.id,
                    "image_id": image_1.id,
                },
                {
                    "case_id": self.case_2.id,
                    "image_id": image_2.id,
                },
            ]
        }
        self.client.post('/api/cashback/v1/submit_overpaid', data=payload, format='json')

        decision = OverpaidConsts.Statuses.ACCEPTED
        self.case_1.status = OverpaidConsts.Statuses.PENDING
        self.case_1.save()

        expected_amount = self.case_1.customer.wallet_balance_available + self.case_1.overpaid_amount
        process_decision_overpaid_case(self.case_1.id, agent, note, decision)

        self.case_1.refresh_from_db()

        cashback_amount_new = self.case_1.customer.wallet_balance_available
        history = self.case_1.overpaid_history.last()
        self.assertEqual(history.processed_status, OverpaidConsts.Statuses.PROCESSING_SUCCESS)
        self.assertEqual(expected_amount, cashback_amount_new)

        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 50000)

    def test_process_decision_case_non_julo1(self):
        agent = AgentFactory(user=self.user)
        note = "Any man who must say I am the king is no true king"
        decision = OverpaidConsts.Statuses.ACCEPTED
        self.case_1.status = OverpaidConsts.Statuses.PENDING
        self.case_1.save()
        mtl = ProductLineFactory(product_line_code=ProductLineCodes.MTL1)
        self.application.product_line = mtl
        self.application.save()

        expected_amount = self.case_1.customer.wallet_balance_available + self.case_1.overpaid_amount
        process_decision_overpaid_case(self.case_1.id, agent, note, decision)

        self.case_1.refresh_from_db()
        cashback_amount_new = self.case_1.customer.wallet_balance_available
        history = self.case_1.overpaid_history.last()
        self.assertEqual(history.processed_status, OverpaidConsts.Statuses.PROCESSING_SUCCESS)
        self.assertEqual(expected_amount, cashback_amount_new)

        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 50000)

    @patch('juloserver.cashback.services.is_graduate_of')
    @patch('juloserver.cashback.services.create_cashback_transfer_transaction')
    def test_process_decision_case_non_champion(self, mock_create_cashback_transfer_transaction,
                                            mock_is_champion):
        mock_is_champion.return_value = False
        agent = AgentFactory(user=self.user)
        note = "With great code comes great responsibility."

        decision = OverpaidConsts.Statuses.ACCEPTED
        history = self.customer.change_wallet_balance(
            20000, 20000, CashbackChangeReason.CASHBACK_OVER_PAID
        )
        case = CashbackOverpaidVerification.objects.get(wallet_history=history)
        case.update_safely(status=OverpaidConsts.Statuses.ACCEPTED)
        # not enough transfer
        process_decision_overpaid_case(case.id, agent, note, decision)
        mock_create_cashback_transfer_transaction.assert_not_called()

        # enough transfer
        case.overpaid_amount = 50000
        case.status = OverpaidConsts.Statuses.PENDING
        case.save()
        process_decision_overpaid_case(case.id, agent, note, decision)
        mock_create_cashback_transfer_transaction.assert_called_once_with(
            self.application, case.overpaid_amount
        )

        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 0)

    @patch('juloserver.cashback.services.is_graduate_of')
    @patch('juloserver.cashback.services.create_cashback_transfer_transaction')
    def test_process_decision_case_missing_cashback_earned(self,
                                                           mock_create_cashback_transfer_transaction,
                                                           mock_is_champion):
        # case accepted
        mock_is_champion.return_value = False
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        ApplicationFactory(customer=customer)
        agent = AgentFactory(user=user)
        note = "With great code comes great responsibility."
        decision = OverpaidConsts.Statuses.ACCEPTED
        cashback_balance = CashbackBalanceFactory(customer=customer)
        wallet_history = customer.change_wallet_balance(
            50000, 50000, CashbackChangeReason.CASHBACK_OVER_PAID
        )
        wallet_history.cashback_earned = None
        wallet_history.save()
        case = CashbackOverpaidVerification.objects.get(wallet_history=wallet_history)
        case.update_safely(status=OverpaidConsts.Statuses.PENDING)
        self.assertEqual(customer.wallet_balance_available, 0)
        process_decision_overpaid_case(case.id, agent, note, decision)

        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 0)

        case.refresh_from_db()
        self.assertEqual(case.status, OverpaidConsts.Statuses.ACCEPTED)
        history = case.overpaid_history.last()
        self.assertEqual(history.processed_status, OverpaidConsts.Statuses.PROCESSING_SUCCESS)

    def test_process_decision_case_rejected(self):
        # case rejected
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        ApplicationFactory(customer=customer)
        agent = AgentFactory(user=user)
        note = "With great code comes great responsibility."
        decision = OverpaidConsts.Statuses.REJECTED
        cashback_balance = CashbackBalanceFactory(customer=customer)
        wallet_history = customer.change_wallet_balance(
            0, 50000, CashbackChangeReason.CASHBACK_OVER_PAID
        )
        case = CashbackOverpaidVerification.objects.get(wallet_history=wallet_history)
        case.update_safely(status=OverpaidConsts.Statuses.PENDING)

        self.assertEqual(customer.wallet_balance_available, 0)
        process_decision_overpaid_case(case.id, agent, note, decision)
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 0)

        # reject still create cashback_earned from wallet_history, but verified = False
        history = case.overpaid_history.last()
        self.assertEqual(history.processed_status, OverpaidConsts.Statuses.PROCESSING_SUCCESS)
        cashback_earned = wallet_history.cashback_earned
        self.assertEqual(cashback_earned.current_balance, 50000)
        self.assertEqual(cashback_earned.verified, False)
        self.assertEqual(customer.wallet_balance_available, 0)

    @patch('juloserver.cashback.services.is_graduate_of')
    @patch('juloserver.cashback.services.create_cashback_transfer_transaction')
    def test_process_decision_case_accepted(self, mock_create_cashback_transfer_transaction,
                                            mock_is_champion):
        # case accepted
        mock_is_champion.return_value = False
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        cashback_balance = CashbackBalanceFactory(
            customer=customer, status=CashbackBalanceStatusConstant.UNFREEZE
        )
        ApplicationFactory(customer=customer)
        agent = AgentFactory(user=user)
        note = "With great code comes great responsibility."
        decision = OverpaidConsts.Statuses.ACCEPTED
        wallet_history = customer.change_wallet_balance(
            50000, 50000, CashbackChangeReason.CASHBACK_OVER_PAID
        )
        case = CashbackOverpaidVerification.objects.get(wallet_history=wallet_history)
        case.update_safely(status=OverpaidConsts.Statuses.PENDING)
        self.assertEqual(customer.wallet_balance_available, 0)
        process_decision_overpaid_case(case.id, agent, note, decision)

        # accepted still create cashback_earned from wallet_history, but verified = True
        history = case.overpaid_history.last()
        self.assertEqual(history.processed_status, OverpaidConsts.Statuses.PROCESSING_SUCCESS)
        cashback_earned = case.wallet_history.cashback_earned
        self.assertEqual(cashback_earned.current_balance, 50000)
        self.assertEqual(cashback_earned.verified, True)
        self.assertEqual(customer.wallet_balance_available, 50000)

        cashback_balance.refresh_from_db()
        self.assertEquals(cashback_balance.cashback_balance, 50000)

    def test_process_decision_case_no_overpaid_case(self):
        agent = AgentFactory(user=self.user)
        note = "test"
        decision = OverpaidConsts.Statuses.ACCEPTED
        non_existing_id = 23493270498
        process_decision_overpaid_case(non_existing_id, agent, note, decision)
        history = self.case_1.overpaid_history.last()
        self.assertIsNone(history)
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 0)

import datetime
import io
import json
import os
import tempfile

from PIL import Image as Imagealias
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from mock.mock import call
from unittest.mock import patch, MagicMock, Mock
from requests.exceptions import RequestException, Timeout
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from django.test.utils import override_settings

from juloserver.apiv2.models import PdWebModelResult
from juloserver.apiv2.services import check_iti_repeat, get_customer_category
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    Customer,
    FeatureSetting,
    CreditScore,
    HighScoreFullBypass,
    ITIConfiguration,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    PartnerFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
    ApplicationHistoryFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    GlobalPaymentMethodFactory,
    PaymentMethodFactory,
    PaymentMethodLookupFactory,
    PaymentFactory,
    PartnerPropertyFactory,
    PartnerBankAccountFactory,
    BankFactory,
    OtpRequestFactory,
    FeatureSettingFactory,
    CreditScoreFactory,
    ImageFactory,
    PartnershipApplicationDataFactory,
    PartnershipCustomerDataFactory,
)
from juloserver.julo.exceptions import JuloException
from juloserver.merchant_financing.models import MerchantApplicationReapplyInterval
from juloserver.merchant_financing.tests.factories import MerchantFactory
from juloserver.partnership.services.services import (
    process_register,
    process_register_merchant,
    is_able_to_reapply,
    get_account_payments_and_virtual_accounts,
    check_application_loan_status,
    check_application_account_status,
    get_partner_redirect_url,
    check_paylater_temporary_block_period_feature,
    whitelabel_paylater_link_account,
    check_active_account_limit_balance,
    update_paylater_transaction_status,
    track_partner_session_status,
    process_image_upload_partnership,
)
from juloserver.partnership.services.web_services import (calculate_loan_partner_simulations,
                                                          store_partner_simulation_data_in_redis)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.account.constants import AccountConstant
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.partnership.constants import (DEFAULT_PARTNER_REDIRECT_URL,
                                              PaylaterTransactionStatuses,
                                              PaylaterUserAction)
from juloserver.partnership.tests.factories import (PartnershipConfigFactory,
                                                    PartnershipTypeFactory,
                                                    PartnerLoanSimulationsFactory,
                                                    PaylaterTransactionFactory,
                                                    CustomerPinVerifyFactory,
                                                    PaylaterTransactionStatusFactory,
                                                    PartnershipFlowFlagFactory,
                                                    PartnershipApplicationFlagFactory,)
from juloserver.partnership.tests.test_views import get_paylater_initialization_credentials
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.partnership.constants import PartnershipFlag
from juloserver.apiv2.tests.factories import (
    PdWebModelResultFactory,
)
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.partnership.services.digisign import get_partnership_digisign_client


def update_pin_and_otp_data(cusomer_pin_verify: CustomerPinFactory,
                            otp_request: OtpRequestFactory,
                            date_time: datetime) -> None:
    expiry_time = date_time + timedelta(days=1)
    cusomer_pin_verify.expiry_time = expiry_time
    cusomer_pin_verify.save()
    otp_request.cdate = date_time + timedelta(minutes=5)
    otp_request.save()


class TestProcessRegister(TestCase):
    def setUp(self):
        super().setUp()
        self.partner = PartnerFactory(name=PartnerConstant.DOKU_PARTNER)
        self.customer_data = {
            'email': 'dummy@email.com',
            'username': '1234561212120002',
            'pin': '456789',
            'app_version': '5.15.0',
            'gcm_reg_id': 'gcm-reg-id',
            'android_id': 'android-id',
            'latitude': '6.12',
            'longitude': '12.6'
        }

    @patch('juloserver.partnership.services.services.generate_address_from_geolocation_async')
    @patch('juloserver.partnership.services.services.create_application_checklist_async')
    @patch('juloserver.apiv2.services.store_device_geolocation')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.partnership.services.services.assign_julo1_application')
    @patch('juloserver.partnership.services.services.update_customer_data')
    def test_minimal_data(self,
                          mock_update_customer_data,
                          mock_assign_julo1_application,
                          mock_process_application_status_change,
                          mock_store_device_geolocation,
                          mock_create_application_checklist_async,
                          mock_generate_address_from_geolocation_async):
        res = process_register(self.customer_data, self.partner)

        # Check if the expected data exists in DB
        res_customer = Customer.objects.filter(email=self.customer_data.get('email')).last()
        res_application = Application.objects.filter(email=self.customer_data.get('email'), customer_id=res_customer.id).last()
        res_geolocation = AddressGeolocation.objects.filter(application_id=res_application.id).last()
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)
        self.assertIsNotNone(res_geolocation)

        # Check if the dependencies services is called
        mock_assign_julo1_application.assert_called_once_with(res_application)
        mock_update_customer_data.assert_called_once_with(res_application)
        mock_process_application_status_change.assert_called_once_with(res_application.id,
                                                                       ApplicationStatusCodes.FORM_CREATED,
                                                                       change_reason='customer_triggered')
        mock_store_device_geolocation.assert_called_once_with(res_customer,
                                                              latitude=self.customer_data.get('latitude'),
                                                              longitude=self.customer_data.get('longitude'))

        # Check if async tasks generated)
        mock_generate_address_from_geolocation_async.delay.assert_called_once_with(res_geolocation.id)
        mock_create_application_checklist_async.delay.assert_called_once_with(res_application.id)

        # Check if the return value is expected
        self.assertEqual(self.customer_data['username'], res['ktp'])
        self.assertEqual(self.customer_data['email'], res['email'])
        self.assertIn('application_xid', res)


    @patch('juloserver.apiv2.services.store_device_geolocation')
    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.partnership.services.services.assign_julo1_application')
    @patch('juloserver.partnership.services.services.update_customer_data')
    def test_uppercase_email(self, *args):
        expectedEmail = 'dummy-test@email.com'
        self.customer_data['email'] = 'Dummy-TEST@Email.Com'
        res = process_register(self.customer_data, self.partner)

        res_customer = Customer.objects.filter(email=expectedEmail).last()
        res_application = Application.objects.filter(email=expectedEmail).last()
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)

        self.assertEquals(expectedEmail, res['email'])


class TestProcessRegisterMerchant(TestCase):
    def setUp(self):
        super().setUp()
        self.merchant = MerchantFactory(nik='1234561212120002', merchant_xid='123')
        self.partner = PartnerFactory(name=PartnerConstant.DOKU_PARTNER)
        self.customer_data = {
            'email': 'dummy@email.com',
            'pin': '456789',
            'app_version': '5.15.0',
            'gcm_reg_id': 'gcm-reg-id',
            'android_id': 'android-id',
            'latitude': '6.12',
            'longitude': '12.6',
            'merchant_xid': '123'
        }
        WorkflowFactory(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
        ProductLineFactory(product_line_code=ProductLineCodes.MF)

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.partnership.services.services.update_customer_data')
    def test_minimal_data(self, mock_update_customer_data, mock_process_application_status_change):
        res = process_register_merchant(self.customer_data, self.partner, self.merchant)

        # Check if the expected data exists in DB
        res_customer = Customer.objects.filter(email=self.customer_data.get('email')).last()
        res_application = Application.objects.filter(email=self.customer_data.get('email'), customer_id=res_customer.id).last()
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)

        # Check if the dependencies services is called
        mock_update_customer_data.assert_called_once_with(res_application)
        mock_process_application_status_change.assert_called_once_with(res_application.id,
                                                                       ApplicationStatusCodes.FORM_CREATED,
                                                                       change_reason='customer_triggered')

        # Check if the return value is expected
        self.assertEqual(self.merchant.nik, res['ktp'])
        self.assertEqual(self.customer_data['email'], res['email'])
        self.assertIn('application_xid', res)


    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.partnership.services.services.update_customer_data')
    def test_uppercase_email(self, *args):
        expectedEmail = 'dummy-test@email.com'
        self.customer_data['email'] = 'Dummy-TEST@Email.Com'
        res = process_register_merchant(self.customer_data, self.partner, self.merchant)

        res_customer = Customer.objects.filter(email=expectedEmail).last()
        res_application = Application.objects.filter(email=expectedEmail).last()
        self.assertIsNotNone(res_customer)
        self.assertIsNotNone(res_application)

        self.assertEquals(expectedEmail, res['email'])


class TestIsAbleToReapply(TestCase):
    def setUp(self):
        super().setUp()
        self.reject_application = ApplicationFactory(
            application_status=StatusLookupFactory(status_code=135))
        self.customer = self.reject_application.customer
        self.today = timezone.localtime(timezone.now())

    def test_allowed_to_reapply(self):
        self.customer.can_reapply_date = self.today + datetime.timedelta(days=-1)
        self.customer.save()
        is_allow, *not_allow_reason = is_able_to_reapply(self.reject_application)
        self.assertTrue(is_allow)
        self.assertEqual(not_allow_reason[0], '')

    def test_not_allowed_to_reapply(self):
        self.customer.can_reapply_date = self.today + datetime.timedelta(days=1)
        self.customer.save()
        is_allow, *not_allow_reason = is_able_to_reapply(self.reject_application)
        self.assertFalse(is_allow)


class TestPartnerAccountPaymentService(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        user = AuthUserFactory(username='testpartner')
        self.client.force_login(user)
        self.partner = PartnerFactory(user=user)
        self.status_lookup = StatusLookupFactory()
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.application_xid = 2594397666
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            partner=self.partner,
            application_xid=self.application_xid,
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='JULO1',
            payment_frequency='monthly'
        )

        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.application_status_id = 190
        self.application.save()
        today = timezone.localtime(timezone.now()).date()
        self.start_date = today - relativedelta(days=3)
        self.end_date = today + relativedelta(days=50)
        self.start_date1 = today + relativedelta(days=30)
        self.end_date1 = today - relativedelta(days=5)
        self.is_paid_off_true = 'true'
        self.is_paid_off_false = 'false'
        self.filter_type = 'due_date'
        self.filter_type1 = 'cdate'
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id=330
        self.account_payment.save()
        payment_method_code = '123'
        payment_method_name = 'Bank BCA 1'
        GlobalPaymentMethodFactory(
            feature_name='BCA', is_active=True, is_priority=True, impacted_type='Primary',
            payment_method_code=payment_method_code, payment_method_name=payment_method_name)
        self.bank_name1 = 'BCA'
        self.bank_name2 = ''
        self.payment_method_name = 'PERMATA'
        self.payment_method_code = PaymentMethodCodes.PERMATA
        self.payment_method_name1 = 'BCA'
        self.payment_method_code1 = PaymentMethodCodes.BCA
        self.payment_method_name2 = 'PERMATA'
        self.payment_method_code2 = PaymentMethodCodes.PERMATA1


    def test_get_account_payments_and_virtual_accounts(self):
        data = {
            "is_paid_off": self.is_paid_off_false
        }

        data1 = {
            "is_paid_off": self.is_paid_off_true
        }
        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data1)
        self.assertIsNotNone(account_payments)
        self.account_payment.status_id = 310
        self.account_payment.save()
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.payment.account_payment = self.account_payment
        self.payment.save()
        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data)
        self.assertIsNotNone(account_payments)
        self.assertIsNotNone(virtual_accounts)


class TestAccountandLoanStatus(TestCase):
    def setUp(self):
        super().setUp()
        user = AuthUserFactory()
        self.partner = PartnerFactory(user=user)
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.application_xid = 2594397686
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            partner=self.partner,
            application_xid=self.application_xid,
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='JULO1',
            payment_frequency='monthly'
        )

        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.application_status_id = 190
        self.application.save()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=10000000, loan_xid=1000003456)

    def test_check_application_loan_status(self):
        is_valid_application = check_application_loan_status(self.loan)
        self.assertEqual(is_valid_application, False)

        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        is_valid_application = check_application_loan_status(self.loan)
        self.assertEqual(is_valid_application, True)

    def test_check_application_account_status(self):
        is_valid_application = check_application_account_status(self.loan)
        self.assertEqual(is_valid_application, False)

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.status = active_status_code
        self.account.save()
        is_valid_application = check_application_account_status(self.loan)
        self.assertEqual(is_valid_application, True)


class TestPinPageRedirectUrl(TestCase):
    def setUp(self):
        super().setUp()
        user = AuthUserFactory()
        self.partner = PartnerFactory(user=user)
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.application_xid = 2594397686
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            application_xid=self.application_xid,
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='JULO1',
            payment_frequency='monthly'
        )

        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.save()
        self.partnership_type = PartnershipTypeFactory()


    def test_get_partner_redirect_url1(self):
        self.application.partner = self.partner
        self.application.save()
        redirect_url = get_partner_redirect_url(self.application)
        self.assertEqual(redirect_url, DEFAULT_PARTNER_REDIRECT_URL)

    def test_get_partner_redirect_url2(self):
        url = 'http://www.test1.com'
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            redirect_url=url,
            loan_duration=[3, 7, 14, 30]
        )
        self.application.partner = self.partner
        self.application.save()
        redirect_url = get_partner_redirect_url(self.application)
        self.assertEqual(redirect_url, url)

    def test_get_partner_redirect_url3(self):
        url = 'http://www.test2.com'
        self.partner_property = PartnerPropertyFactory(
            partner=self.partner,
            account=self.account,
            is_active=True
        )
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            redirect_url=url,
            loan_duration=[3, 7, 14, 30]
        )

        redirect_url = get_partner_redirect_url(self.application)
        self.assertEqual(redirect_url, url)


class TestLoanPartnerSimulation(TestCase):
    @patch('juloserver.partnership.models.get_redis_client')
    def setUp(self, _: MagicMock) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name='Whitelabel Paylater'
        )
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30],
            is_show_loan_simulations=True,
            is_show_interest_in_loan_simulations=False
        )
        self.partner_simulation = PartnerLoanSimulationsFactory(
            partnership_config=self.partnership_config,
            interest_rate=0.03, tenure=1,
            is_active=True,
            origination_rate=0.05)

    @patch('juloserver.partnership.services.web_services.get_redis_client')
    def test_calculate_loan_partner_simulations(self, mocked_redis: MagicMock) -> None:
        mocked_redis_mock = MagicMock()
        stored_data = '[{"id": 2, "origination_rate": 0.06, "interest_rate": 0.03, "tenure": 1}]'
        mocked_redis_mock.get.return_value = stored_data
        mocked_redis.return_value = mocked_redis_mock

        # string result
        result = calculate_loan_partner_simulations(self.partnership_config, 100_000)
        self.assertEqual(result['loan_offers_in_number'], [])
        self.assertEqual(result['loan_offers_in_str'][0]['tenure'],
                         '1 Bulan')
        self.assertEqual(result['loan_offers_in_str'][0]['monthly_installment'],
                         'Rp 109.000')

        # Number Result
        result = calculate_loan_partner_simulations(self.partnership_config, 100_000, is_number_result=True)
        self.assertEqual(result['loan_offers_in_str'], [])
        self.assertEqual(result['loan_offers_in_number'][0]['tenure'],
                         1)
        self.assertEqual(result['loan_offers_in_number'][0]['monthly_installment'],
                         109000)

        # show interest
        self.partnership_config.is_show_interest_in_loan_simulations = True
        self.partnership_config.save(update_fields=['is_show_interest_in_loan_simulations'])

        # string result
        result = calculate_loan_partner_simulations(self.partnership_config, 100_000)
        self.assertEqual(result['loan_offers_in_number'], [])
        self.assertEqual(result['loan_offers_in_str'][0]['tenure'],
                         '1 Bulan')
        self.assertEqual(result['loan_offers_in_str'][0]['monthly_interest_rate'],
                         'Bunga 3.0 %')
        self.assertEqual(result['loan_offers_in_str'][0]['monthly_installment'],
                         'Rp 109.000')

        # Number Result
        result = calculate_loan_partner_simulations(self.partnership_config, 100_000, is_number_result=True)
        self.assertEqual(result['loan_offers_in_str'], [])
        self.assertEqual(result['loan_offers_in_number'][0]['tenure'],
                         1)
        self.assertEqual(result['loan_offers_in_number'][0]['monthly_interest_rate'],
                         3.0)
        self.assertEqual(result['loan_offers_in_number'][0]['monthly_installment'],
                         109000)

        # test stored data interest rate 0.0, origination rate 50%
        stored_data = '[{"id": 2, "origination_rate": 0.5, "interest_rate": 0.0, "tenure": 5}]'
        mocked_redis_mock.get.return_value = stored_data
        mocked_redis.return_value = mocked_redis_mock
        result = calculate_loan_partner_simulations(self.partnership_config, 500_000,
                                                    is_number_result=True)

        # should be (500_000 + 500_000 * 0.5) / 5 = 750_000 / 5 = 150_000 
        self.assertEqual(result['loan_offers_in_number'][0]['monthly_installment'],
                         150_000)

    @patch('juloserver.partnership.services.web_services.get_redis_client')
    def test_store_partner_simulation_data_in_redis(self, _: MagicMock) -> None:
        partner_simulations = self.partnership_config.loan_simulations.filter(is_active=True)\
            .order_by('tenure')
        key = '%s_%s' % ("partner_simulation_key:", self.partner.id)
        result = store_partner_simulation_data_in_redis(key, partner_simulations)
        self.assertEqual(result[0]['origination_rate'],
                         self.partner_simulation.origination_rate)
        self.assertEqual(result[0]['interest_rate'],
                         self.partner_simulation.interest_rate)
        self.assertEqual(result[0]['tenure'],
                         self.partner_simulation.tenure)


class TestPaylaterPreLoginCheck(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id=67567567567,
            transaction_amount=50000,
            paylater_transaction_xid="1234567889",
            partner=self.partner)

    def test_check_paylater_temporary_block_period_without_feature_setting(self):
        paylater_temporary_period = check_paylater_temporary_block_period_feature()
        self.assertEqual(paylater_temporary_period.max_attempt, 3)
        self.assertEqual(paylater_temporary_period.blocking_hour, 1)

        paylater_temporary_period = check_paylater_temporary_block_period_feature()
        self.assertNotEqual(paylater_temporary_period.max_attempt, 2)
        self.assertNotEqual(paylater_temporary_period.blocking_hour, 4)

    def test_check_paylater_temporary_block_period_with_feature_setting(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.PAYLATER_PARTNER_TEMPORARY_BLOCK_PERIOD,
            parameters={
                'temporary_blocking_hour': 2,
                'temporary_blocking_attempt': 2,
            },
            )
        paylater_temporary_period = check_paylater_temporary_block_period_feature()
        self.assertEqual(paylater_temporary_period.max_attempt, 2)
        self.assertEqual(paylater_temporary_period.blocking_hour, 2)

        paylater_temporary_period = check_paylater_temporary_block_period_feature()
        self.assertNotEqual(paylater_temporary_period.max_attempt, 1)
        self.assertNotEqual(paylater_temporary_period.blocking_hour, 5)


class TestWhitelabelPaylaterLinkAccount(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(self.client)
        self.data = {
            "email": self.customer.email,
            "phone": self.customer.phone
        }
        self.application = self.customer.application_set.last()
        name_bank_validation = NameBankValidationFactory(
            bank_code='TEST-BANK',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        PartnerBankAccountFactory(
            partner=self.application.partner,
            name_bank_validation_id=name_bank_validation.id,
            bank_account_number=9999991
        )
        BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        customer_pin = CustomerPinFactory(user=self.customer.user)
        self.cusomer_pin_verify = CustomerPinVerifyFactory(
            customer=self.customer,
            is_pin_used=False,
            customer_pin=customer_pin)
        self.otp_request = OtpRequestFactory(
            customer=self.customer,
            is_used=True,
            application=self.application)

        self.account = self.application.account
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.save()
        self.partner_reference_id = '121213213'

    @patch('juloserver.partnership.services.services.notify_user_linking_account.delay')
    @patch('django.utils.timezone.localtime')
    def test_whitelabel_paylater_link_success(self, time_mocked: MagicMock,
                                              notify_linking_email_mock: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 8, 10, 16, 00)
        time_mocked.side_effect = [
            datetime_now,
            datetime_now,
        ]
        customer = self.customer
        application = self.application
        partner = self.application.partner
        partner_reference_id = self.partner_reference_id

        update_pin_and_otp_data(self.cusomer_pin_verify,
                                self.otp_request, datetime_now)
        result = whitelabel_paylater_link_account(customer, partner, partner_reference_id,
                                                  application)
        self.assertEqual(result['is_linked'], True)
        self.assertEqual(result['partner_reference'], self.partner_reference_id)

        # email sended
        notify_linking_email_mock.called_once()

    @patch('django.utils.timezone.localtime')
    def test_whitelabel_paylater_link_failed_application_not_found(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 17, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        customer = self.customer
        partner = self.application.partner
        partner_reference_id = self.partner_reference_id

        update_pin_and_otp_data(self.cusomer_pin_verify,
                                self.otp_request, datetime_now)

        # error application not found
        with self.assertRaises(JuloException):
            whitelabel_paylater_link_account(customer, partner, partner_reference_id,
                                             None)

    @patch('django.utils.timezone.localtime')
    def test_whitelabel_paylater_link_failed_no_verify_pin_and_otp(
        self, mocked_time2: MagicMock
    ) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 18, 00)
        mocked_time2.side_effect = [
            datetime_now,
            datetime_now
        ]
        customer = self.customer
        application = self.application
        partner = self.application.partner
        partner_reference_id = self.partner_reference_id

        update_pin_and_otp_data(self.cusomer_pin_verify,
                                self.otp_request, datetime_now)

        # error no otp request and verify pin
        self.otp_request.is_used = False
        self.otp_request.save()
        self.cusomer_pin_verify.is_pin_used = True
        self.cusomer_pin_verify.save()

        with self.assertRaises(JuloException):
            whitelabel_paylater_link_account(customer, partner, partner_reference_id,
                                             application)

    @patch('django.utils.timezone.localtime')
    def test_whitelabel_paylater_link_failed_no_account_active(self,
                                                               mocked_time3: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 19, 00)
        mocked_time3.side_effect = [
            datetime_now,
            datetime_now
        ]
        customer = self.customer
        application = self.application
        partner = self.application.partner
        partner_reference_id = self.partner_reference_id

        update_pin_and_otp_data(self.cusomer_pin_verify,
                                self.otp_request, datetime_now)

        self.account.status = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.deactivated
        )
        self.account.save()
        with self.assertRaises(JuloException):
            whitelabel_paylater_link_account(customer, partner, partner_reference_id,
                                             application)


class TestCheckActiveAccountLimitBalance(TestCase):
    def setUp(self) -> None:
        self.partner_user = AuthUserFactory(username='test_lead_gen_offer')
        self.customer = CustomerFactory(user=self.partner_user)
        self.account = AccountFactory(customer=self.customer,
                                      status=StatusLookupFactory(status_code=420))
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_xid=9999999887,
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()

    def test_check_active_account_limit_balance(self) -> None:
        has_insufficient = check_active_account_limit_balance(self.account, 10000000)
        self.assertEqual(has_insufficient, False)
        has_insufficient = check_active_account_limit_balance(self.account, 10000001)
        self.assertEqual(has_insufficient, True)



class TestUpdatePaylaterTransactionStatus(TestCase):
    def setUp(self) -> None:
        self.loan = LoanFactory()
        self.partner = PartnerFactory()
        self.paylater_transaction = PaylaterTransactionFactory(
            transaction_amount=500_000,
            partner_reference_id='99999999',
            paylater_transaction_xid=198765432,
            partner=self.partner
        )
        self.paylater_transaction_status = PaylaterTransactionStatusFactory(
            transaction_status=PaylaterTransactionStatuses.INITIATE,
            paylater_transaction=self.paylater_transaction
        )

    def test_update_paylater_transaction_status(self) -> None:
        self.assertEqual(self.paylater_transaction_status.transaction_status,
                         PaylaterTransactionStatuses.INITIATE)

        with self.assertRaises(Exception):
            # loan error
            self.loan.paylater_transaction_loan

        update_paylater_transaction_status(self.paylater_transaction,
                                           self.loan)

        self.paylater_transaction.refresh_from_db()

        # should be in progress
        self.assertEqual(self.paylater_transaction_status.transaction_status,
                         PaylaterTransactionStatuses.IN_PROGRESS)

        if hasattr(self.loan, 'paylater_transaction_loan'):
            have_transaction_loan = True
        else:
            have_transaction_loan = False
        self.assertEqual(have_transaction_loan, True)


class TestTrackPartnerSessionStatus(TestCase):
    def setUp(self):
        super().setUp()
        user = AuthUserFactory()
        self.partner = PartnerFactory(user=user)
        workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler')
        self.customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(customer=self.customer, workflow=workflow)
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id=123123123,
            transaction_amount=50000,
            paylater_transaction_xid="1234567889",
            partner=self.partner,
        )

    def test_track_partner_session_status_without_application_xid(self):
        status = track_partner_session_status(
            self.partner,
            PaylaterUserAction.CHECKOUT_INITIATED,
            123123123,
            "",
            self.paylater_transaction.paylater_transaction_xid,
        )
        self.assertEqual(status, True)

    def test_track_partner_session_status_without_partner_reference_id(self):
        status = track_partner_session_status(
            self.partner,
            PaylaterUserAction.CHECKOUT_INITIATED,
            "",
            self.application.application_xid,
            self.paylater_transaction.paylater_transaction_xid,
        )
        self.assertEqual(status, True)

    def test_track_partner_session_status_with_success_case(self):
        status = track_partner_session_status(
            self.partner,
            PaylaterUserAction.CHECKOUT_INITIATED,
            123123123,
            self.application.application_xid,
            self.paylater_transaction.paylater_transaction_xid,
        )
        self.assertEqual(status, True)

    def test_track_partner_session_status_invalid(self):
        status = track_partner_session_status(
            self.partner, PaylaterUserAction.CHECKOUT_INITIATED, "", ""
        )
        self.assertEqual(status, False)


class TestBypassBankValidationForGosel(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(is_active=True, name=PartnerConstant.GOSEL)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999980787,
            partner=self.partner,
            product_line=self.product_line,
            email='testing5_1email@gmail.com',
        )
        self.application.name_bank_validation_id = None
        self.application.save()
        self.partnership_flow_flag = PartnershipFlowFlagFactory(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION,
            configs={
                'close_kin_name': False,
                'close_kin_mobile_phone': False,
                'bank_name': False,
                'bank_account_number': False,
            },
        )
        BankFactory(
            bank_code='014',
            bank_name='BANK CENTRAL ASIA, Tbk (BCA)',
            xendit_bank_code='BCA',
            swift_bank_code='BCA',
        )

    def test_partner_gosel_bypass_process_bank_name_validation(self):
        from juloserver.julo.workflows2.tasks import process_validate_bank_task
        from juloserver.disbursement.models import NameBankValidation
        from juloserver.disbursement.constants import NameBankValidationStatus

        self.application.application_status_id = 105
        self.application.bank_name = None
        self.application.bank_account_number = None
        self.application.save()

        self.credit_model = PdWebModelResultFactory(application_id=self.application.id, pgood=0.65)
        PartnershipApplicationFlagFactory(
            application_id=self.application.id, name=PartnershipPreCheckFlag.APPROVED
        )
        process_validate_bank_task(self.application.id)
        self.application.refresh_from_db()
        name_bank_validation = NameBankValidation.objects.filter(
            pk=self.application.name_bank_validation_id
        ).last()
        bank_account_number = '{}{}{}'.format(
            '999', self.application.customer.nik, self.application.application_xid
        )
        self.assertEquals(name_bank_validation.bank_code, 'BCA')
        self.assertEquals(name_bank_validation.account_number, bank_account_number)
        self.assertEquals(name_bank_validation.name_in_bank, self.application.customer.fullname)
        self.assertEquals(name_bank_validation.mobile_phone, self.application.mobile_phone_1)
        self.assertEquals(name_bank_validation.validation_status, NameBankValidationStatus.SUCCESS)


class TestHighScoreFullBypassPartnershipAgentAssisted(TestCase):
    def setUp(self):
        self.partner_name = PartnerNameConstant.QOALA
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        product_line_code = ProductLineCodes.J1
        self.application = ApplicationFactory(
            partner=self.partner,
            monthly_income=1_000_000,
            workflow=self.workflow,
        )
        self.application.product_line = ProductLineFactory(product_line_code=product_line_code)
        self.application.save()
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.HIGH_SCORE_FULL_BYPASS,
            is_active=True,
        )
        self.threshold = 0.8
        self.pgood = 0.9
        self.inside_premium_area = True
        self.is_salaried = True
        self.is_bypass_dv_x121 = True

        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            inside_premium_area=self.inside_premium_area,
            model_version=2,
        )
        self.pd_web_model_result = PdWebModelResultFactory(
            application_id=self.application.id, pgood=self.pgood
        )
        self.high_score_full_bypass_partner = HighScoreFullBypass.objects.create(
            cm_version=2,
            threshold=self.threshold,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            bypass_dv_x121=True,
            customer_category=get_customer_category(self.application),
            parameters={"agent_assisted_partner_ids": [str(self.partner.id)]},
        )

    @patch('juloserver.apiv2.credit_matrix2.get_salaried')
    def test_success_agent_assisted_high_score_full_bypass_partnership(self, mock_get_salaried):
        mock_get_salaried.return_value = self.is_salaried
        result = feature_high_score_full_bypass(self.application)
        self.assertIsNotNone(result)

    @patch('juloserver.apiv2.credit_matrix2.get_salaried')
    def test_success_agent_assisted_high_score_full_bypass_partnership_without_partner(
        self, mock_get_salaried
    ):
        mock_get_salaried.return_value = self.is_salaried
        HighScoreFullBypass.objects.create(
            cm_version=2,
            threshold=self.threshold,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            bypass_dv_x121=True,
            customer_category=get_customer_category(self.application),
        )
        result = feature_high_score_full_bypass(self.application)
        self.assertEqual(result.id, self.high_score_full_bypass_partner.id)

    @patch('juloserver.julo.services2.high_score.get_salaried')
    def test_high_score_agent_assisted_full_bypass_partnership_not_found_and_use_j1(
        self, mock_get_salaried
    ):
        self.high_score_full_bypass_partner.delete()
        mock_get_salaried.return_value = self.is_salaried
        high_score_full_bypass = HighScoreFullBypass.objects.create(
            cm_version=2,
            threshold=self.threshold,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            bypass_dv_x121=True,
            customer_category=get_customer_category(self.application),
        )
        result = feature_high_score_full_bypass(self.application)
        self.assertEqual(result.id, high_score_full_bypass.id)


class TestCheckItiRepeatPartnershipAgentAssisted(TestCase):
    """
    QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
    """

    def setUp(self):
        self.partner_name = PartnerNameConstant.QOALA
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            partner=self.partner,
            monthly_income=100,
            workflow=self.workflow,
        )
        # setup iti configuration
        self.pgood = 0.9
        self.inside_premium_area = True
        self.is_salaried = True

        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            inside_premium_area=self.inside_premium_area,
        )
        self.pd_web_model_result = PdWebModelResultFactory(
            application_id=self.application.id, pgood=self.pgood
        )
        ITIConfiguration.objects.create(
            is_active=True,
            iti_version=123,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            customer_category=get_customer_category(self.application),
            min_threshold=self.pgood,
            max_threshold=1.0,
            min_income=self.application.monthly_income,
            max_income=self.application.monthly_income + 1,
            parameters={"agent_assisted_partner_ids": [str(self.partner.id)]},
        )

    # test happy case leadgen user, test non leadgen agent assisted users
    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_happy_flow_check_iti_partnership_agent_assisted(
        self, mock_check_app_cs_v20b, mock_get_salaried
    ):
        mock_check_app_cs_v20b.return_value = True
        mock_get_salaried.return_value = self.is_salaried

        result = check_iti_repeat(self.application.id)
        assert result != None

    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_another_iti_configuration_version_exists_with_not_partner_agent_assisted(
        self, mock_check_app_cs_v20b, mock_get_salaried
    ):
        mock_check_app_cs_v20b.return_value = True
        mock_get_salaried.return_value = self.is_salaried
        ITIConfiguration.objects.create(
            is_active=True,
            iti_version=124,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            customer_category=get_customer_category(self.application),
            min_threshold=self.pgood,
            max_threshold=1.0,
            min_income=self.application.monthly_income,
            max_income=self.application.monthly_income + 1,
        )

        result = check_iti_repeat(self.application.id)
        assert result != None

    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_partnership_but_non_parnter_agent_assisted_user(
        self, mock_check_app_cs_v20b, mock_get_salaried
    ):
        mock_check_app_cs_v20b.return_value = True
        mock_get_salaried.return_value = self.is_salaried
        partner_name = PartnerNameConstant.CERMATI
        partner = PartnerFactory(name=partner_name, is_active=True)
        new_non_leadgen_application = ApplicationFactory(
            partner=partner,
            monthly_income=100,
            workflow=self.workflow,
        )
        ITIConfiguration.objects.create(
            is_active=True,
            iti_version=124,
            is_premium_area=self.inside_premium_area,
            is_salaried=self.is_salaried,
            customer_category=get_customer_category(new_non_leadgen_application),
            min_threshold=self.pgood,
            max_threshold=1.0,
            min_income=new_non_leadgen_application.monthly_income,
            max_income=new_non_leadgen_application.monthly_income + 1,
        )

        CreditScore.objects.create(
            application_id=new_non_leadgen_application.id,
            inside_premium_area=self.inside_premium_area,
            score='C',
        )
        PdWebModelResult.objects.create(
            id=1,
            application_id=new_non_leadgen_application.id,
            customer_id=0,
            pgood=self.pgood,
            probability_fpd=self.pgood,
        )

        result = check_iti_repeat(new_non_leadgen_application.id)
        assert result != None


@override_settings(NEW_DIGISIGN_BASE_URL='https://api.example.com')
@override_settings(PARTNERSHIP_AXIATA_DIGISIGN_TOKEN='test_token_axiata')
class TestPartnershipDigisignClient(TestCase):
    def setUp(self):
        # Test data
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.AXIATA_WEB)
        self.application.product_line = product_line
        self.application.save()

    @patch('juloserver.partnership.services.digisign.PartnershipDigisignClient.make_request')
    def test_register_success_axiata_product(self, mock_post):
        """Test successful document signing"""
        expected_response = {
            "success": True,
            "error": "",
            "data": {
                "registration_status": 1,
                "reference_number": "sample",
                "error_code": "",
                "message": "",
                "verification_results": {
                    "liveness_present": False,
                    "fr_present": True,
                    "dukcapil_present": True,
                },
            },
        }
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "responses": [
                    {
                        "success": True,
                        "error": "",
                        "data": {
                            "registration_status": 1,
                            "reference_number": "sample",
                            "error_code": "",
                            "message": "",
                            "verification_results": {
                                "liveness_present": False,
                                "fr_present": True,
                                "dukcapil_present": True,
                            },
                        },
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        request_data = {"application_id": self.application.id}
        product_line_code = self.application.product_line_code
        digi_client = get_partnership_digisign_client(product_line_code)
        result = digi_client.register(request_data)
        response = result.json()
        self.assertEqual(expected_response, response.get('data').get('responses')[0])


class TestUploadImagePartnership(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.image = ImageFactory(image_source=self.application.id)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            application=self.application,
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data, application=self.application
        )

    @staticmethod
    def create_image(size=(100, 100), image_format='JPEG'):
        image = io.BytesIO()
        Imagealias.new('RGB', size).save(image, image_format)
        image.seek(0)
        return image

    @patch(
        'juloserver.partnership.services.services.upload_file_as_bytes_to_oss', return_value=None
    )
    def test_process_image_upload_partnership_from_upload(self, _):
        image = self.create_image()
        image_upload = SimpleUploadedFile('test.jpeg', image.getvalue(), content_type='image/jpeg')
        image_data = {
            'file_extension': '.jpeg',
            'image_file': image_upload,
        }
        process_image_upload_partnership(self.image, image_data)
        self.image.refresh_from_db()
        self.assertIsNotNone(self.image.url)
        self.assertIsNotNone(self.image.thumbnail_url)

    @patch(
        'juloserver.partnership.services.services.upload_file_as_bytes_to_oss', return_value=None
    )
    def test_process_image_upload_partnership_from_bytes(self, _):
        image = self.create_image()
        image_byte = image.getvalue()
        image_data = {
            'file_extension': '.jpeg',
            'image_byte_file': image_byte,
        }
        process_image_upload_partnership(self.image, image_data)
        self.image.refresh_from_db()
        self.assertIsNotNone(self.image.url)
        self.assertIsNotNone(self.image.thumbnail_url)

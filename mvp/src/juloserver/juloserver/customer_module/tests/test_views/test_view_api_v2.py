import pytz
from datetime import datetime
from django.contrib.auth.hashers import make_password
from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch
from rest_framework.test import APIClient

from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.customer_module.constants import (
    FeatureNameConst,
    BankAccountCategoryConst,
)
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import (
    BankNameValidationLogFactory,
    NameBankValidationFactory,
)
from juloserver.ecommerce.tests.factories import EcommerceConfigurationFactory
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CreditScoreFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    StatusLookupFactory,
    ProductLineFactory,
)
from juloserver.pin.tests.factories import CustomerPinFactory, TemporarySessionFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.limit_validity_timer.tests.factories import LimitValidityTimerCampaignFactory


class TestCreditInfo(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.credit_score = CreditScoreFactory(application_id=self.application.id, score='B-')
        self.loan = LoanFactory(account=self.account)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )

    def test_credit_info(self):
        response = self.client.get('/api/customer-module/v2/credit-info/')
        assert response.status_code == 200


class TestBankAccountDestinationEcommerce(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.loan = LoanFactory(account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='ecommerce', display_label='ecommerce', parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
            description='tokopedia',
        )

    @patch('juloserver.customer_module.views.views_api_v2.get_julo_one_is_proven')
    def test_get_bank_account_destination(self, mock_is_proven):
        mock_is_proven.return_value = False
        data = {'self_bank_account': 'false', 'ecommerceId': 'tokopedia'}
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.status_code == 200

        # the bank account is active
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.json()['data'] != []

        # the bank account is deleted
        self.bank_account_destination.is_deleted = True
        self.bank_account_destination.save()
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.json()['data'] == []

        # is_deleted is None
        self.bank_account_destination.is_deleted = None
        self.bank_account_destination.save()
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.json()['data'] != []

    @patch('juloserver.customer_module.views.views_api_v2.get_julo_one_is_proven')
    def test_verify_bank_account(self, mock_is_proven):
        mock_is_proven.return_value = False
        data = {}
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.status_code == 200

    @patch('juloserver.customer_module.views.views_api_v2.get_julo_one_is_proven')
    def test_get_bank_account_destination_is_proven(self, mock_is_proven):
        bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='self', parent_category_id=1
        )

        bank2 = BankFactory(
            bank_code='013', bank_name='BRI', xfers_bank_code='BRI', swift_bank_code='02'
        )
        bank3 = BankFactory(
            bank_code='013', bank_name='MANDIRI', xfers_bank_code='MANDIRI', swift_bank_code='03'
        )

        name_bank_validation2 = NameBankValidationFactory(
            bank_code='BRI',
            account_number='123456',
            name_in_bank='BRI',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674735',
            attempt=0,
        )
        name_bank_validation3 = NameBankValidationFactory(
            bank_code='MANDIRI',
            account_number='123456',
            name_in_bank='MANDIRI',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674735',
            attempt=0,
        )
        BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=bank2,
            name_bank_validation=name_bank_validation2,
            account_number='12345',
            is_deleted=False,
            description='tokopedia',
        )
        BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=bank3,
            name_bank_validation=name_bank_validation3,
            account_number='12343',
            is_deleted=False,
            description='shopee',
        )

        mock_is_proven.return_value = False
        data = {'self_bank_account': 'true'}
        self.application.name_bank_validation = self.name_bank_validation
        self.application.save()
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.status_code == 200
        self.assertEqual(res.json()['data'][0]['name'], 'MANDIRI')

        mock_is_proven.return_value = True
        data = {'self_bank_account': 'true'}
        res = self.client.get(
            '/api/customer-module/v2/bank-account-destination/{}'.format(self.customer.id),
            data=data,
        )
        assert res.status_code == 200
        self.assertEqual(len(res.json()['data']), 2)


class TestGoogleAnalyticsInstanceDataView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)

    def test_update_app_instance_id(self):
        data = {'app_instance_id': 'appinstanceid'}
        res = self.client.post('/api/customer-module/v2/update-analytics-data', data=data)
        assert res.status_code == 200

        res = self.client.post('/api/customer-module/v2/update-analytics-data', data={})
        assert res.status_code == 400

        res = self.client.get('/api/customer-module/v2/update-analytics-data', data={})
        assert res.status_code == 405


class TestDropDownList(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)

    def test_get_dropdownlist(self):
        response = self.client.get('/api/application_flow/web/v1/dropdown_list')
        assert response.status_code == 200


class TestChangeEmail(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()

    def test_change_email(self):
        data = {'email': 'newemail@gmail.com', 'pin': '123456'}

        # otp feature is off
        ## wrong password
        data['pin'] = '111123'
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 401

        ## success
        data['pin'] = '123456'
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 200

        # check expected data in DB
        expectedEmail = 'newemail@gmail.com'
        self.application.refresh_from_db()
        self.customer.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(expectedEmail, self.user.email)
        self.assertEqual(expectedEmail, self.application.email)
        self.assertEqual(expectedEmail, self.customer.email)

        # otp_feature is on
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={'wait_time_seconds': 400, 'otp_max_request': 3, 'otp_resend_time_sms': 180},
        )
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 400

        # invalid session token
        data['session_token'] = 'dasdasdasd7827321837'
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 403

        # success
        session = TemporarySessionFactory(user=self.customer.user)
        data['session_token'] = session.access_key
        data['email'] = 'test_email@gmail.com'
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 200

    def test_uppercase_email(self):
        expectedEmail = 'newemail@gmail.com'

        data = {'email': 'NewEMAIL@GmaIl.com', 'pin': '123456'}
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )

        self.application.refresh_from_db()
        self.customer.refresh_from_db()
        self.user.refresh_from_db()

        self.assertEqual(200, response.status_code, response.content)

        self.assertEqual(expectedEmail, self.user.email)
        self.assertEqual(expectedEmail, self.application.email)
        self.assertEqual(expectedEmail, self.customer.email)


class TestVerifyAccountDestination(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.EDUCATION,
            parent_category_id=7,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.j1_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.jturbo_upgrade_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        )
        self.jturbo_upgrade_accepted_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
            description='tokopedia',
        )

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    def test_forbid_all_j1_and_turbo_users_bank_account(
        self, mock_get_key_prefix_from_request, mock_fixed_window_rate_limit
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = False
        data = {
            'description': 'nothing',
            'category_id': self.bank_account_category.id,
            'bank_code': 'BCA',
            'account_number': '12345',
            'customer_id': self.customer.id,
            'is_forbid_all_j1_and_turbo_users_bank_account': True,
        }

        other_application = ApplicationFactory()

        for application in [self.application, other_application]:
            # application registered bank account number = 12345
            application.bank_account_number = data['account_number']
            application.save()

            for application_status in [self.j1_status,
                                       self.jturbo_upgrade_status,
                                       self.jturbo_upgrade_accepted_status]:
                application.application_status = application_status
                application.save()
                response = self.client.post(
                    '/api/customer-module/v4/verify-bank-account', data=data, format='json'
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.data['errors'][0],
                    'No. rekening / VA ini tidak valid untuk diinput'
                )

            application.bank_account_number = '654321'
            application.save()

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    @patch('juloserver.customer_module.views.views_api_v2.XfersService')
    def test_not_forbid_all_j1_and_turbo_users_bank_account(
        self, mock_xfer_service, mock_get_key_prefix_from_request, mock_fixed_window_rate_limit
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = False
        data = {
            'description': 'nothing',
            'category_id': self.bank_account_category.id,
            'bank_code': 'BCA',
            'account_number': '12345',
            'customer_id': self.customer.id,
        }
        self.application.bank_account_number = data['account_number']
        self.application.application_status = self.j1_status
        self.application.save()

        mock_xfer_service().validate.return_value = {
            'reason': 'SUCCESS',
            'validated_name': 'BCA',
            'account_no': '11111',
            'bank_abbrev': 'BCA',
            'id': '11111111111',
            'status': 'success',
        }
        response = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.ratelimit.decorator.fixed_window_rate_limit')
    @patch('juloserver.ratelimit.decorator.get_key_prefix_from_request')
    @patch('juloserver.customer_module.views.views_api_v2.XfersService')
    def test_name_invalid(
        self, mock_xfer_service, mock_get_key_prefix_from_request, mock_fixed_window_rate_limit
    ):
        mock_get_key_prefix_from_request.return_value = 'some_key'
        mock_fixed_window_rate_limit.return_value = False
        data = {
            'description': 'nothing',
            'category_id': self.bank_account_category.id,
            'bank_code': 'BCA',
            'account_number': '12345',
            'customer_id': self.customer.id,
        }
        self.application.bank_account_number = data['account_number']
        self.application.application_status = self.j1_status
        self.application.save()

        mock_xfer_service().validate.return_value = {
            'reason': 'NAME_INVALID',
            'validated_name': 'BCA',
            'account_no': '11111',
            'bank_abbrev': 'BCA',
            'id': '11111111111',
            'status': 'fail',
        }
        response = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['data']['reason'], 'No. rekening / VA salah atau tidak ditemukan'
        )

        # length of account number > 20
        data['account_number'] = '12332113321123321123321123321123321123'
        response_2 = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        assert response_2.json()['errors'] == ['Account_number No. rekening / VA Tidak Valid']

        # account number != numeric
        data['account_number'] = 'test_abc'
        response_2 = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        assert response_2.json()['errors'] == ['Account_number No. rekening / VA Tidak Valid']

        # len(account number) == 20
        data['account_number'] = '12332112332112311111'
        response_2 = self.client.post(
            '/api/customer-module/v4/verify-bank-account', data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['data']['reason'], 'No. rekening / VA salah atau tidak ditemukan'
        )


class TestLimitValidityTimerView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.campaign_1 = LimitValidityTimerCampaignFactory(
            start_date=datetime(2024, 3, 15, 13, 30, 30, tzinfo=pytz.UTC),
            end_date=datetime(2024, 3, 30, 17, 30, 30, tzinfo=pytz.UTC),
            campaign_name='campaign_1',
            content=dict(
                title="Title of campaign 1",
                body="Body of campaign 1",
                button="Button 1"
            ),
            minimum_available_limit=500000,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            is_active=True
        )
        self.campaign_2 = LimitValidityTimerCampaignFactory(
            start_date=datetime(2024, 3, 16, 13, 30, 30, tzinfo=pytz.UTC),
            end_date=datetime(2024, 3, 29, 17, 30, 30, tzinfo=pytz.UTC),
            campaign_name='campaign_2',
            content=dict(
                title="Title of campaign 2",
                body="Body of campaign 2",
                button="Button 2"
            ),
            minimum_available_limit=800000,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            is_active=True
        )

    def test_account_is_suspended(self):
        self.account.update_safely(status_id=430)

        res = self.client.get('/api/customer-module/v2/limit-timer')
        self.assertIsNone(res.json()['data'])

    def test_account_not_enough_available_limit(self):
        self.account.update_safely(status_id=420)
        self.account_limit.update_safely(available_limit=300000)

        res = self.client.get('/api/customer-module/v2/limit-timer')
        self.assertIsNone(res.json()['data'])

    @patch('juloserver.limit_validity_timer.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_account_has_no_validity_timer_campaign(self, mock_now, mock_redis_client):
        mock_now.return_value = datetime(2024, 3, 20, 12, 23, 30)
        mock_redis_client.return_value.exists.return_value = False

        self.account.update_safely(status_id=420)
        self.account_limit.update_safely(available_limit=1000000)

        res = self.client.get('/api/customer-module/v2/limit-timer')
        self.assertIsNone(res.json()['data'])

        mock_redis_client.return_value.exists.return_value = True
        mock_redis_client.return_value.sismember.return_value = True
        self.campaign_1.update_safely(transaction_method_id=None)
        self.campaign_2.update_safely(transaction_method_id=None)

        res = self.client.get('/api/customer-module/v2/limit-timer')
        self.assertIsNone(res.json()['data'])

    @patch('juloserver.limit_validity_timer.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_account_has_validity_timer_campaign(self, mock_now, mock_redis_client):
        mock_now.return_value = datetime(2024, 3, 20, 12, 23, 30)
        mock_redis_client.return_value.exists.return_value = True
        mock_redis_client.return_value.sismember.return_value = True

        self.account.update_safely(status_id=420)
        self.account_limit.update_safely(available_limit=1000000)

        res = self.client.get('/api/customer-module/v2/limit-timer')
        expected_data = {
            "end_time": "2024-03-29T17:30:30Z",
            "campaign_name": "campaign_2",
            "information": {
                "title": "Title of campaign 2",
                "body": "Body of campaign 2",
                "button": "Button 2",
                "transaction_method_id": TransactionMethodCode.OTHER.code
            },
            "pop_up_message": None
        }
        self.assertEqual(res.json()['data'], expected_data)

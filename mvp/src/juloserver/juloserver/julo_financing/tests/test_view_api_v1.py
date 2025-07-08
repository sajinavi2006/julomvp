from io import BytesIO
import tempfile
from unittest.mock import patch

from PIL import Image
from django.conf import settings
from mock import ANY
import pytz
from datetime import timedelta, datetime
from unittest import mock
from juloserver.julo.services2.redis_helper import MockRedisHelper
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile

from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework.status import HTTP_200_OK

from juloserver.account.tests.factories import (
    AccountFactory,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo_financing.constants import (
    JFinancingEntryPointType,
    JFinancingErrorMessage,
    RedisKey,
)
from juloserver.julo_financing.services.token_related import (
    JFinancingToken,
    get_j_financing_token_config_fs,
    TokenData,
    get_or_create_customer_token,
    get_entry_point,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    LoanFactory,
    ProductLookupFactory,
    CreditMatrixRepeatFactory,
    ProductLineFactory,
    StatusLookupFactory,
)
from juloserver.julo.constants import FeatureNameConst, ApplicationStatusCodes
from juloserver.julo_financing.tests.factories import (
    JFinancingCategoryFactory,
    JFinancingCheckoutFactory,
    JFinancingProductFactory,
    JFinancingVerificationFactory,
)
from juloserver.loan.constants import LoanTaxConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.account.constants import AccountConstant
from juloserver.julo_financing.constants import (
    JFinancingFeatureNameConst,
    JFinancingResponseMessage,
)
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.julo_financing.exceptions import ProductNotFound


class TestJFinancingTokenAPIView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.J_FINANCING_TOKEN_CONFIG,
            is_active=True,
            parameters={'token_expired_hours': 30 * 24},
        )
        self.token_obj = JFinancingToken()

    def test_token_expiry_time(self):
        token_config = get_j_financing_token_config_fs()
        token = self.token_obj.generate_token(self.customer.id, token_config['token_expired_hours'])
        token_data = self.token_obj.decrypt(token)
        expected_expiry_time = timezone.localtime(timezone.now()) + timedelta(
            hours=self.fs.parameters.get('token_expired_hours')
        )

        expiry_time = datetime.fromtimestamp(token_data.expiry_time)
        self.assertEquals(expiry_time.date(), expected_expiry_time.date())

    @mock.patch('juloserver.julo_financing.services.token_related.get_redis_client')
    def test_entry_point_api(self, _mock_redis_server):
        _mock_redis_server.return_value = MockRedisHelper()
        landing_page = JFinancingEntryPointType.LANDING_PAGE
        expected_expiry_time = timezone.localtime(timezone.now()) + timedelta(
            hours=self.fs.parameters.get('token_expired_hours')
        )
        response = self.client.get(
            '/api/julo-financing/v1/entry-point?type={}'.format(landing_page)
        )

        data = response.json()['data']['link']
        token = data.split('token=')[1]
        is_valid, token_data = self.token_obj.is_token_valid(token)

        assert is_valid == True
        assert token_data.customer_id == self.customer.pk
        assert (
            expected_expiry_time.date()
            == datetime.fromtimestamp(token_data.expiry_time, pytz.timezone('Asia/Jakarta')).date()
        )

        # token exist
        response = self.client.get(
            '/api/julo-financing/v1/entry-point?type={}'.format(landing_page)
        )
        data = response.json()['data']['link']
        existing_token = data.split('token=')[1]
        assert existing_token == token

        is_valid, token_data = self.token_obj.is_token_valid(token)

        assert is_valid == True
        assert token_data.customer_id == self.customer.pk
        assert (
            expected_expiry_time.date()
            == datetime.fromtimestamp(token_data.expiry_time, pytz.timezone('Asia/Jakarta')).date()
        )

        # not found
        response = self.client.get('/api/julo-financing/v1/entry-point?type={}'.format("test"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @mock.patch('juloserver.julo_financing.services.token_related.get_redis_client')
    def test_entry_point_api_with_product_detail(self, _mock_redis_server):
        _mock_redis_server.return_value = MockRedisHelper()
        type = JFinancingEntryPointType.PRODUCT_DETAIL
        product = JFinancingProductFactory()
        product_id = product.pk
        expected_expiry_time = timezone.localtime(timezone.now()) + timedelta(
            hours=self.fs.parameters.get('token_expired_hours')
        )
        response = self.client.get(
            '/api/julo-financing/v1/entry-point?type={}&product_id={}'.format(type, product_id)
        )

        data = response.json()['data']['link']
        token = data.split('token=')[1]
        is_valid, token_data = self.token_obj.is_token_valid(token)
        query_params = {"product_id": product_id}
        expected_entry_point = get_entry_point(self.customer.pk, type, query_params)

        assert is_valid == True
        assert data == expected_entry_point
        assert token_data.customer_id == self.customer.pk
        assert (
            expected_expiry_time.date()
            == datetime.fromtimestamp(token_data.expiry_time, pytz.timezone('Asia/Jakarta')).date()
        )

        # token exist
        response = self.client.get(
            '/api/julo-financing/v1/entry-point?type={}&product_id={}'.format(type, product_id)
        )
        data = response.json()['data']['link']
        existing_token = data.split('token=')[1]
        is_valid, token_data = self.token_obj.is_token_valid(token)

        query_params = {"product_id": product_id}
        expected_entry_point = get_entry_point(self.customer.pk, type, query_params)
        assert is_valid == True
        assert existing_token == token
        assert data == expected_entry_point
        assert token_data.customer_id == self.customer.pk
        assert (
            expected_expiry_time.date()
            == datetime.fromtimestamp(token_data.expiry_time, pytz.timezone('Asia/Jakarta')).date()
        )

        # bad request
        # 1. product_id not existing in query_params
        response = self.client.get('/api/julo-financing/v1/entry-point?type={}'.format(type))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # 2. product_id not existing in the database
        response = self.client.get(
            '/api/julo-financing/v1/entry-point?type={}?product_id=99999999'.format(type)
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class JFinancingAuthenticateTestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('juloserver.julo_financing.views.view_api_v1.get_j_financing_user_info')
    @patch('juloserver.julo_financing.views.view_api_v1.get_list_j_financing_product')
    @patch('juloserver.julo_financing.authentication.JFinancingToken.is_token_valid')
    def test_authenticate(
        self, mock_is_token_valid, mock_get_list_j_financing_product, mock_get_j_financing_user_info
    ):
        # invalid token
        mock_is_token_valid.return_value = (False, None)
        response = self.client.get(path='/api/julo-financing/v1/products/invalid-token')
        self.assertEqual(response.status_code, 403)

        # valid token, but no-existing customer
        mock_is_token_valid.return_value = (
            True,
            TokenData(customer_id=0, event_time=0, expiry_time=0),
        )
        response = self.client.get(path='/api/julo-financing/v1/products/valid-token')
        self.assertEqual(response.status_code, 403)

        # valid token, existing customer
        customer = CustomerFactory()
        mock_is_token_valid.return_value = (
            True,
            TokenData(customer_id=customer.id, event_time=0, expiry_time=0),
        )
        mock_get_list_j_financing_product.return_value = []
        mock_get_j_financing_user_info.return_value = {
            "full_name": "John Doe",
            "phone_number": "01234567890",
            "address": "1, 2, 3, 4, 5, 6",
            "address_detail": "Apt 4B",
            "available_limit": 5000,
            "province_name": "Jakarta",
        }
        response = self.client.get(path='/api/julo-financing/v1/products/valid-token')
        self.assertEqual(response.status_code, 200)


class JFinancingProductViewTestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.feature_setting = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE,
            is_active=True,
            parameters={
                'province_shipping_fee': {
                    'JAKARTA': 10000,
                },
            },
        )

    @patch('juloserver.julo_financing.views.view_api_v1.get_j_financing_user_info')
    @patch('juloserver.julo_financing.views.view_api_v1.get_list_j_financing_product')
    @patch('juloserver.julo_financing.authentication.JFinancingToken.is_token_valid')
    def test_get_product_list(self, mock_is_token_valid, mock_get_products, mock_get_user_info):
        customer = CustomerFactory(address_provinsi='Jakarta')
        mock_is_token_valid.return_value = (
            True,
            TokenData(customer_id=customer.id, event_time=0, expiry_time=0),
        )
        expected_sale_tags = [
            {
                "primary": True,
                "image_url": "abc.com",
                "tag_name": "hades",
            },
            {
                "primary": False,
                "image_url": "zxc",
                "tag_name": "ms. johnson",
            },
        ]
        mock_get_user_info.return_value = {
            'full_name': 'Test User',
            'phone_number': '1234567890',
            'address': 'Test Address',
            'address_detail': 'Apt 123',
            'available_limit': 1000,
            'province_name': 'Jakarta',
        }
        mock_get_products.return_value = [
            {
                'id': 1,
                'name': 'Product 1',
                'price': 100,
                'display_installment_price': 'Rp5.600.000',
                'thumbnail_url': 'http://example.com/thumb1.jpg',
                'sale_tags': expected_sale_tags,
            }
        ]

        response = self.client.get(path='/api/julo-financing/v1/products/valid-token')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['success'], True)
        self.assertIn('user_info', response.data['data'])
        self.assertIn('products', response.data['data'])

        # check fields
        self.assertEqual(response.data['data']['products'][0]['sale_tags'], expected_sale_tags)

        mock_get_user_info.assert_called_once_with(customer=customer)
        mock_get_products.assert_called_once_with(category_id=None)

        mock_get_products.reset_mock()
        response = self.client.get(path='/api/julo-financing/v1/products/valid-token?category_id=1')
        self.assertEqual(response.status_code, 400)
        mock_get_products.assert_not_called()

        category = JFinancingCategoryFactory()
        mock_get_products.reset_mock()
        response = self.client.get(
            path='/api/julo-financing/v1/products/valid-token?category_id={}'.format(category.id)
        )
        self.assertEqual(response.status_code, 200)
        mock_get_products.assert_called_once_with(category_id=category.id)

    @patch('juloserver.julo_financing.views.view_api_v1.get_j_financing_product_detail')
    @patch('juloserver.julo_financing.authentication.JFinancingToken.is_token_valid')
    def test_get_product_detail(self, mock_is_token_valid, mock_get_j_financing_product_detail):
        customer = CustomerFactory()
        mock_is_token_valid.return_value = (
            True,
            TokenData(customer_id=customer.id, event_time=0, expiry_time=0),
        )

        # invalid product (inactive or not-existing)
        mock_get_j_financing_product_detail.side_effect = ProductNotFound
        response = self.client.get(path='/api/julo-financing/v1/products/1/valid-token')
        self.assertEqual(response.status_code, 400)
        mock_get_j_financing_product_detail.assert_called_once_with(product_id=1)

        expected_data = {
            'id': 1,
            'name': 'Product 1',
            'price': 100,
            'display_installment_price': 'Rp5.600.000',
            'description': 'Description',
            'images': ['http://example.com/image1.jpg', 'http://example.com/image2.jpg'],
            'sale_tags': [
                {"image_url": "abc.com/xxx.jpg", "primary": False, "tag_name": "xxx"},
            ],
        }
        mock_get_j_financing_product_detail.reset_mock()
        mock_get_j_financing_product_detail.side_effect = None
        mock_get_j_financing_product_detail.return_value = expected_data
        response = self.client.get(path='/api/julo-financing/v1/products/1/valid-token')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['success'], True)
        self.assertDictEqual(response.data['data'], expected_data)
        mock_get_j_financing_product_detail.assert_called_once_with(product_id=1)


class JFinancingLoanCalculationViewTestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, address_provinsi="Jakarta")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=5000000)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
        )
        self.category = JFinancingCategoryFactory()
        self.j_financing_product = JFinancingProductFactory(
            j_financing_category=self.category, is_active=True
        )
        self.allowed_durations = {'is_active': True, 'durations': [6]}
        self.fs = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION,
            is_active=True,
            parameters={'allowed_durations': self.allowed_durations},
        )
        self.province_shipping_fee_fs = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE,
            is_active=True,
            parameters={
                'province_shipping_fee': {
                    'JAKARTA': 999999,
                },
            },
        )

    @patch('juloserver.loan.services.adjusted_loan_matrix.get_daily_max_fee')
    @patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.get_first_payment_date_by_application')
    @patch('juloserver.loan.services.adjusted_loan_matrix.timezone.localtime')
    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    @patch('juloserver.loan.views.views_api_v3.get_loan_duration')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.loan.views.views_api_v3.get_credit_matrix_repeat')
    @patch('juloserver.julo_financing.authentication.JFinancingToken.is_token_valid')
    def test_loan_duration(
        self,
        mock_is_token_valid,
        mock_credit_matrix_repeat,
        mock_get_credit_matrix_and_credit_matrix_product_line,
        mock_get_loan_duration,
        mock_is_product_locked,
        mock_time_zone_local_time,
        mock_get_first_date,
        mock_loan_related_time_zone,
        mock_loan_related_first_payment,
        mock_daily_max_fee,
    ):
        customer = self.customer
        mock_is_token_valid.return_value = (
            True,
            TokenData(customer_id=customer.id, event_time=0, expiry_time=0),
        )
        today_date = datetime(2023, 10, 1, 0, 0, 0)
        first_payment_date = datetime(2023, 10, 21, 0, 0, 0).date()

        mock_time_zone_local_time.return_value = today_date
        mock_get_first_date.return_value = first_payment_date
        mock_loan_related_first_payment.return_value = first_payment_date
        mock_loan_related_time_zone.return_value = today_date
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        monthly_interest_rate = 0.06
        provision_rate = 0.08
        TransactionMethod.objects.all().delete()
        self_method = TransactionMethodFactory(
            id=TransactionMethodCode.JFINANCING.code,
            method=TransactionMethodCode.JFINANCING,
        )
        credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self_method,
            version=1,
            interest=monthly_interest_rate,
            provision=provision_rate,
            max_tenure=6,
        )
        credit_matrix_repeat.save()
        mock_credit_matrix_repeat.return_value = credit_matrix_repeat

        mock_get_loan_duration.return_value = [3, 4, 6, 5, 7, 9]
        mock_is_product_locked.return_value = False
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            credit_matrix,
            credit_matrix_product_line,
        )

        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.1,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

        data = {
            "loan_amount_request": 3_000_000,
            'j_financing_product_id': self.j_financing_product.pk,
            "province_name": "Jakarta",
        }
        daily_max_fee_rate = 0.4
        mock_daily_max_fee.return_value = daily_max_fee_rate
        response = self.client.post("/api/julo-financing/v1/loan-duration/test/", data=data)
        assert response.status_code == HTTP_200_OK

        response_data = response.json()['data']
        loan_choices = response_data['loan_choice']
        for loan_choice in loan_choices:
            assert loan_choice['duration'] in self.allowed_durations['durations']

        # fs is off
        self.fs.parameters['allowed_durations']['is_active'] = False
        self.fs.save()
        response = self.client.post("/api/julo-financing/v1/loan-duration/test/", data=data)
        response_data = response.json()['data']
        loan_choices = response_data['loan_choice']
        assert len(loan_choices) > len(self.allowed_durations['durations'])

        # product not found
        data = {
            "loan_amount_request": 3_000_000,
            'j_financing_product_id': self.j_financing_product.pk + 999,
        }
        response = self.client.post("/api/julo-financing/v1/loan-duration/test/", data=data)
        assert response.status_code == 400


class TestTransactionHistoryListView(APITestCase):
    def setUp(self):
        from django.conf import settings

        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        settings.J_FINANCING_SECRET_KEY_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.J_FINANCING_TOKEN_CONFIG,
            is_active=True,
            parameters={'token_expired_hours': 30 * 24},
        )
        self.token_obj = JFinancingToken()
        self.token = self.token_obj.generate_token(self.customer.id)

    @mock.patch('juloserver.julo_financing.services.token_related.get_redis_client')
    def test_get_or_create_customer_token(self, _mock_redis_server):
        redis = MockRedisHelper()
        redis_key = RedisKey.J_FINANCING_CUSTOMER_TOKEN.format(self.customer.pk)
        _mock_redis_server.return_value = redis

        token, _ = get_or_create_customer_token(self.customer.pk)
        remaining_seconds = redis.client.ttl(redis_key)
        expected_expiry_time = timezone.localtime(timezone.now()) + timedelta(
            seconds=remaining_seconds
        )
        token_data = self.token_obj.decrypt(token)
        token_expired = datetime.fromtimestamp(
            token_data.expiry_time, pytz.timezone('Asia/Jakarta')
        ) - timedelta(minutes=1)

        assert expected_expiry_time.date() == token_expired.date()
        assert expected_expiry_time.hour == token_expired.hour
        assert expected_expiry_time.minute == token_expired.minute
        
    def test_invalid_token(self):
        # empty
        empty_token = ''
        response = self.client.get(
            '/api/julo-financing/v1/customer/checkouts/{}'.format(empty_token)
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

        # bad
        bad_token = 'abc'
        response = self.client.get('/api/julo-financing/v1/customer/checkouts/{}'.format(bad_token))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['errors'][0] == 'Authentication credentials were not provided.'

        # token with non-existing customer
        no_customer_token = self.token_obj.generate_token(customer_id=0)

        response = self.client.get(
            '/api/julo-financing/v1/customer/checkouts/{}'.format(no_customer_token)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data['errors'][0] == 'Authentication credentials were not provided.'

    @mock.patch(
        'juloserver.julo_financing.views.view_api_v1.get_customer_jfinancing_transaction_history'
    )
    def test_ok(self, mock_get_transaction_history):
        return_dict = {
            "checkouts": [
                {
                    "id": 1,
                    "display_price": "Rp2.369.000",
                    "display_loan_amount": "Rp3.718.000",
                    "product_name": "Samsung Galaxy A15",
                    "thumbnail_url": "link",
                    "status": "Selesai",
                    "transaction_date": "12 Jun 2024",
                },
            ],
        }

        mock_get_transaction_history.return_value = return_dict
        response = self.client.get(
            '/api/julo-financing/v1/customer/checkouts/{}'.format(self.token)
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['data'] == return_dict

        mock_get_transaction_history.assert_called_once_with(customer_id=self.customer.id)


class TestJFinancingSubmitView(APITestCase):
    def setUp(self) -> None:
        from django.conf import settings

        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, address_provinsi="Jakarta")
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        # Create PIN for submit
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()

        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        settings.J_FINANCING_SECRET_KEY_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.J_FINANCING_TOKEN_CONFIG,
            is_active=True,
            parameters={'token_expired_hours': 30 * 24},
        )
        self.token_obj = JFinancingToken()
        self.token = self.token_obj.generate_token(self.customer.id)

        self.transaction_method = TransactionMethodFactory.jfinancing()
        self.jfinancing_product1 = JFinancingProductFactory(
            name="X",
            price=80_000,
            quantity=5,
        )
        self.province_shipping_fee_fs = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE,
            is_active=True,
            parameters={
                'province_shipping_fee': {
                    'JAKARTA': 0,
                },
            },
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=1_000_000)

    def test_invalid_product(self):
        non_existing_product_id = -1
        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "YAIBA",
                "phone_number": "0812321332132",
                "address": "julo",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": non_existing_product_id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("J_financing_product_id", response.data['errors'][0])

    def test_invalid_loan_duration(self):
        invalid_loan_duration = 999
        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "CLAUDIA",
                "phone_number": "0812321332132",
                "address": "julo",
                "address_detail": "julo",
            },
            "loan_duration": invalid_loan_duration,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Loan_duration", response.data['errors'][0])

    def test_fullname_max_length(self):
        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "A" * 256,
                "phone_number": "0812321332132",
                "address": "julo",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("full_name", response.data['errors'][0])

    def test_fullname_min_length(self):
        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "A",
                "phone_number": "0812321332132",
                "address": "julo",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("full_name", response.data['errors'][0])

    def test_bad_phone_number(self):
        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "GOKU",
                "phone_number": "1234578",
                "address": "julo",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone_number", response.data['errors'][0])

    @mock.patch('juloserver.julo_financing.services.view_related.is_product_lock_by_method')
    def test_product_locked(self, mock_is_product_locked):
        mock_is_product_locked.return_value = True, ""

        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "KRATOS",
                "phone_number": "0812321332132",
                "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.JFINANCING_NOT_AVAILABLE, response.data['errors'][0])

    @mock.patch("juloserver.julo_financing.views.view_api_v1.JFinancingSubmitViewService")
    def test_ok(self, MockJFinancingSubmitViewService):
        service_instance = mock.MagicMock()
        MockJFinancingSubmitViewService.return_value = service_instance

        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "HADES",
                "phone_number": "0812321332132",
                "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }

        service_instance.submit.return_value = None
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        MockJFinancingSubmitViewService.assert_called_once_with(
            customer=self.customer,
            submit_data=ANY,
        )

        # make sure pin is not in data that's passed to service
        actual_call = MockJFinancingSubmitViewService.call_args
        self.assertNotIn("pin", actual_call[1]['submit_data'])

        self.assertEqual(response.status_code, 200)

    def test_product_out_of_stock(self):
        self.jfinancing_product1.quantity = 0
        self.jfinancing_product1.save()

        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "KRATOS",
                "phone_number": "0812321332132",
                "address": "julo",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.PRODUCT_NOT_AVAILABLE, response.data['errors'][0])

    def test_insufficent_loan_limit(self):
        self.account_limit.available_limit = 0
        self.account_limit.save()

        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "KRATOS",
                "phone_number": "0812321332132",
                "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            JFinancingErrorMessage.LIMIT_NOT_ENOUGH,
            response.data['errors'][0],
        )

    @patch('juloserver.julo_financing.services.view_related.transaction_method_limit_check')
    def test_transaction_limit_check(self, mock_transaction_limit_check):
        message = "war is piece"
        mock_transaction_limit_check.return_value = False, message

        data = {
            "pin": "123456",
            "checkout_info": {
                "full_name": "KRATOS",
                "phone_number": "0812321332132",
                "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
                "address_detail": "julo",
            },
            "loan_duration": 4,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }
        response = self.client.post(
            '/api/julo-financing/v1/submit/{}'.format(self.token), data=data, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("war is piece", response.data['errors'][0])


class TestJFinancingUploadSignatureView(APITestCase):
    def _generate_dummy_image(self, width, height, color=(255, 255, 255), format='PNG'):
        img = Image.new('RGB', (width, height), color)

        temp_file = BytesIO()
        img.save(temp_file, format=format)

        dummy_image = SimpleUploadedFile(
            name="dummy_image.{}".format(format.lower()),
            content=temp_file.getvalue(),
            content_type="image/{}".format(format.lower()),
        )

        return dummy_image

    def _generate_dummy_text_file(self, content, file_extension='txt'):
        with tempfile.NamedTemporaryFile(
            mode='w+', suffix=f'.{file_extension}', delete=False
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            temp_file.seek(0)

            dummy_text_file = SimpleUploadedFile(
                f"dummy_text.{file_extension}",
                temp_file.read().encode(),
                content_type=f"text/{file_extension}",
            )

        return dummy_text_file

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.productX = JFinancingProductFactory(
            quantity=1,
        )
        self.checkout = JFinancingCheckoutFactory(
            customer=self.customer,
            j_financing_product=self.productX,
        )
        self.loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            customer=self.customer,
        )
        self.verification = JFinancingVerificationFactory(
            loan=self.loan,
            j_financing_checkout=self.checkout,
            validation_status="initial",
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        settings.J_FINANCING_SECRET_KEY_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.J_FINANCING_TOKEN_CONFIG,
            is_active=True,
            parameters={'token_expired_hours': 30 * 24},
        )
        self.token_obj = JFinancingToken()
        self.token = self.token_obj.generate_token(self.customer.id)

    def test_case_checkout_not_found(self):
        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "abc.png",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/0/{}'.format(self.token),
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SYSTEM_ISSUE, response.data['errors'][0])

    def test_case_user_not_allowed(self):
        new_client = APIClient()
        new_user = AuthUserFactory()
        new_customer = CustomerFactory(user=new_user)
        new_client.force_login(new_user)
        new_client.credentials(HTTP_AUTHORIZATION='Token ' + new_user.auth_expiry_token.key)

        new_token = self.token_obj.generate_token(customer_id=new_customer.id)

        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "abc.jpg",
        }
        response = new_client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, new_token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 403)

    def test_case_product_outtastock(self):
        self.productX.quantity = 0
        self.productX.save()

        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "abc.jpeg",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, self.token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.STOCK_NOT_AVAILABLE, response.data['errors'][0])

    def test_case_invalid_status(self):
        self.verification.validation_status = "on_delivery"
        self.verification.save()

        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "abc.jpg",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, self.token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SYSTEM_ISSUE, response.data['errors'][0])

    @mock.patch("juloserver.julo_financing.views.view_api_v1.JFinancingUploadSignatureService")
    def test_case_ok(self, MockJFinancingSignatureViewService):
        service_instance = mock.MagicMock()
        MockJFinancingSignatureViewService.return_value = service_instance

        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "abc.jpg",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, self.token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 201)

        MockJFinancingSignatureViewService.assert_called_once_with(
            checkout_id=self.checkout.id,
            input_data=ANY,
            user=self.user,
        )

    @mock.patch("juloserver.julo_financing.views.view_api_v1.JFinancingUploadSignatureService")
    def test_case_invalid_name(self, MockJFinancingSignatureViewService):
        service_instance = mock.MagicMock()
        MockJFinancingSignatureViewService.return_value = service_instance

        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "abc",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, self.token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SIGNATURE_ISSUE, response.data['errors'][0])

        # invalid characters
        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "tiếng Việt",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, self.token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SIGNATURE_ISSUE, response.data['errors'][0])

        # end with dash
        data = {
            'upload': self._generate_dummy_image(300, 200),
            'data': "--abc.jpeg",
        }
        response = self.client.post(
            path='/api/julo-financing/v1/signature/upload/{}/{}'.format(
                self.checkout.id, self.token
            ),
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SIGNATURE_ISSUE, response.data['errors'][0])


class TestJFinancingTransactionDetailView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.productX = JFinancingProductFactory(
            quantity=1,
        )
        self.checkout = JFinancingCheckoutFactory(
            customer=self.customer,
            j_financing_product=self.productX,
        )
        self.loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            customer=self.customer,
        )
        self.verification = JFinancingVerificationFactory(
            loan=self.loan,
            j_financing_checkout=self.checkout,
            validation_status="on_review",
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        settings.J_FINANCING_SECRET_KEY_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.J_FINANCING_TOKEN_CONFIG,
            is_active=True,
            parameters={'token_expired_hours': 30 * 24},
        )
        self.token_obj = JFinancingToken()
        self.token = self.token_obj.generate_token(self.customer.id)

    def test_checkout_not_found(self):
        self.verification.validation_status = "initial"
        self.verification.save()

        response = self.client.get(
            path='/api/julo-financing/v1/customer/checkout/{}/{}'.format(
                self.checkout.id, self.token
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SYSTEM_ISSUE, response.data['errors'][0])

        # on review status
        self.verification.validation_status = "on_review"
        self.verification.save()

        response = self.client.get(
            path='/api/julo-financing/v1/customer/checkout/{}/{}'.format(0, self.token),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(JFinancingErrorMessage.SYSTEM_ISSUE, response.data['errors'][0])

    def test_case_user_not_allowed(self):
        new_client = APIClient()
        new_user = AuthUserFactory()
        new_customer = CustomerFactory(user=new_user)
        new_client.force_login(new_user)
        new_client.credentials(HTTP_AUTHORIZATION='Token ' + new_user.auth_expiry_token.key)

        new_token = self.token_obj.generate_token(customer_id=new_customer.id)

        response = new_client.get(
            path='/api/julo-financing/v1/customer/checkout/{}/{}'.format(
                self.checkout.id, new_token
            ),
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(JFinancingErrorMessage.JFINANCING_NOT_AVAILABLE, response.data['errors'][0])

    @mock.patch(
        "juloserver.julo_financing.views.view_api_v1.JFinancingTransactionDetailViewService"
    )
    def test_case_ok(self, mock_service):
        service_instance = mock.MagicMock()
        mock_service.return_value = service_instance

        mock_return_data = {"data": "mock_returned_data"}
        service_instance.get_transaction_detail.return_value = mock_return_data
        response = self.client.get(
            path='/api/julo-financing/v1/customer/checkout/{}/{}'.format(
                self.checkout.id, self.token
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], mock_return_data)

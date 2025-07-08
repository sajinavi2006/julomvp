from django.test import TestCase

from rest_framework.test import APIClient

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    PaymentMethodFactory,
    GlobalPaymentMethodFactory,
    PaymentMethodLookupFactory,
    FeatureSettingFactory
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.payment_methods import PaymentMethodCodes


class TestPaymentMethodRetrieveView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        mobile_phone_1 = '081234567890'
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            mobile_phone_1=mobile_phone_1
        )
        self.payment_method_name_bca = "Bank BCA"
        self.payment_method_name_bri ="Bank BRI"
        self.payment_method_name_permata = "PERMATA Bank"
        self.payment_method_name_ovo = "OVO"
        self.payment_method_name_alfamart = "ALFAMART"
        PaymentMethodFactory(
            id=1,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.BRI,
            payment_method_name=self.payment_method_name_bri,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.BRI + mobile_phone_1,
            sequence=1,
            bank_code="1",
        )
        PaymentMethodLookupFactory(
            name=self.payment_method_name_bri,
            code=PaymentMethodCodes.BRI
        )
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.BRI,
            payment_method_name=self.payment_method_name_bri)
        PaymentMethodFactory(
            id=2,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.PERMATA,
            payment_method_name=self.payment_method_name_permata,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.PERMATA + mobile_phone_1,
            sequence=3,
            bank_code="2",
        )
        PaymentMethodLookupFactory(
            name=self.payment_method_name_permata,
            code=PaymentMethodCodes.PERMATA,
        )
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.PERMATA,
            payment_method_name=self.payment_method_name_permata)
        self.bca_payment_method = PaymentMethodFactory(
            id=3,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.BCA,
            payment_method_name=self.payment_method_name_bca,
            is_shown=True,
            is_primary=True,
            virtual_account=PaymentMethodCodes.BCA + mobile_phone_1,
            sequence=7,
            bank_code="3",
        )
        PaymentMethodLookupFactory(
            name=self.payment_method_name_bca,
            code=PaymentMethodCodes.BCA,
        )
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.BCA,
            payment_method_name=self.payment_method_name_bca)
        PaymentMethodFactory(
            id=4,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.OVO,
            payment_method_name=self.payment_method_name_ovo,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.OVO + mobile_phone_1,
            sequence=4,
            bank_code="4",
        )
        PaymentMethodLookupFactory(
            name=self.payment_method_name_ovo,
            code=PaymentMethodCodes.OVO
        )
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.OVO,
            payment_method_name=self.payment_method_name_ovo)
        self.alfamart_payment_method = PaymentMethodFactory(
            id=5,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.ALFAMART,
            payment_method_name=self.payment_method_name_alfamart,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.ALFAMART + mobile_phone_1,
            sequence=5,
            bank_code="5",
        )
        PaymentMethodLookupFactory(
            name=self.payment_method_name_alfamart,
            code=PaymentMethodCodes.ALFAMART
        )
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.ALFAMART,
            payment_method_name=self.payment_method_name_alfamart
        )
        FeatureSettingFactory(
            feature_name='order_payment_methods_by_groups',
            is_active=True,
            parameters={
                "autodebet_group": [],
                "bank_va_group": ["bank bca", "bank bri", "bank mandiri", "permata bank", "bank maybank"],
                "e_wallet_group": ["gopay", "gopay tokenization", "ovo"],
                "new_repayment_channel_group": {"end_date": "",
                                                "new_repayment_channel": []
                                            },
                "retail_group": ["indomaret", "alfamart"]
            }
        )

    def test_payment_method_retrieve_view_should_success(self):
        response = self.client.get(
            '/api/account_payment/v3/payment_methods/{}'.format(self.account.id)
        )
        self.assertEqual(response.status_code, 200)
        expected_response = [
            {
                "id": 3,
                "bank_code": "3",
                "virtual_account": PaymentMethodCodes.BCA + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_shown": True,
                "is_primary": True,
                "sequence": 7,
                "bank_virtual_name": self.payment_method_name_bca,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 1,
                "bank_code": "1",
                "virtual_account": PaymentMethodCodes.BRI + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 1,
                "bank_virtual_name": self.payment_method_name_bri,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 2,
                "bank_code": "2",
                "virtual_account": PaymentMethodCodes.PERMATA + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 3,
                "bank_virtual_name": self.payment_method_name_permata,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 5,
                "bank_code": "5",
                "virtual_account": PaymentMethodCodes.ALFAMART + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 5,
                "bank_virtual_name": self.payment_method_name_alfamart,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 4,
                "bank_code": "4",
                "virtual_account": PaymentMethodCodes.OVO + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 4,
                "bank_virtual_name": self.payment_method_name_ovo,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
        ]
        response = response.json()
        self.assertEqual(expected_response, response['data']['payment_methods'])
        self.alfamart_payment_method.update_safely(is_primary=True)
        self.bca_payment_method.update_safely(is_primary=False)
        response = self.client.get(
            '/api/account_payment/v3/payment_methods/{}'.format(self.account.id)
        )
        self.assertEqual(response.status_code, 200)
        expected_response = [
            {
                "id": 5,
                "bank_code": "5",
                "virtual_account": PaymentMethodCodes.ALFAMART + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": True,
                "is_shown": True,
                "sequence": 5,
                "bank_virtual_name": self.payment_method_name_alfamart,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 1,
                "bank_code": "1",
                "virtual_account": PaymentMethodCodes.BRI + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 1,
                "bank_virtual_name": self.payment_method_name_bri,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 2,
                "bank_code": "2",
                "virtual_account": PaymentMethodCodes.PERMATA + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 3,
                "bank_virtual_name": self.payment_method_name_permata,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 3,
                "bank_code": "3",
                "virtual_account": PaymentMethodCodes.BCA + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_shown": True,
                "is_primary": False,
                "sequence": 7,
                "bank_virtual_name": self.payment_method_name_bca,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
            {
                "id": 4,
                "bank_code": "4",
                "virtual_account": PaymentMethodCodes.OVO + self.application.mobile_phone_1,
                "customer": self.customer.id,
                "is_primary": False,
                "is_shown": True,
                "sequence": 4,
                "bank_virtual_name": self.payment_method_name_ovo,
                "image_background_url": None,
                "image_logo_url": None,
                "is_enable": True,
                "is_show_new_badge":False,
                "is_latest_payment_method": None,
                "virtual_account_tokenized": None,
                "vendor": None,
            },
        ]
        response = response.json()
        self.assertEqual(expected_response, response['data']['payment_methods'])

    def test_payment_method_retrieve_view_should_failed_when_account_id_is_incorrect(self):
        response = self.client.get(
            '/api/account_payment/v3/payment_methods/2{}'.format(self.account.id)
        )
        self.assertEqual(response.status_code, 400)
        response = response.json()
        self.assertIn('Account tidak ditemukan', response['errors'])

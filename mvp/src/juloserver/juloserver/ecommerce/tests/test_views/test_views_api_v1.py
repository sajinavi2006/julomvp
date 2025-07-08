from importlib import import_module
from unittest.mock import patch

from django.contrib.auth.models import Group, User

from django.test import TestCase
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, \
    HTTP_500_INTERNAL_SERVER_ERROR, HTTP_404_NOT_FOUND
from rest_framework.test import APIClient, APITestCase

from juloserver.account.constants import TransactionType
from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.ecommerce.models import IpriceTransaction, JuloShopTransaction, \
    JuloShopStatusHistory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Partner
from juloserver.julo.partners import PartnerConstant

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CustomerFactory, CleanLoanFactory, FeatureSettingFactory,
)
from juloserver.ecommerce.tests.factories import (
    EcommerceConfigurationFactory,
    EcommerceBankConfigurationFactory,
    JuloShopTransactionFactory
)
from juloserver.partnership.constants import PartnershipTypeConstant
from juloserver.partnership.services.services import process_register_partner
from juloserver.partnership.tests.factories import PartnershipTypeFactory


PACKAGE_NAME = "juloserver.ecommerce.views.views_api_v1"


class TestEcommerceCategory(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.bank = BankFactory(
            bank_code='012',
            bank_name='BCA',
            xendit_bank_code='BCA',
            swift_bank_code='01'
        )
        self.ecommerce_configuration = EcommerceConfigurationFactory()
        self.ecommerce_bank_configuration = EcommerceBankConfigurationFactory(
            bank=self.bank,
            ecommerce_configuration=self.ecommerce_configuration
        )

    def test_get_ecommerce_category(self):
        res = self.client.get('/api/ecommerce/v1/category/')
        self.assertEqual(res.status_code, 200)


class TestIpriceCallbacksV1(APITestCase):
    RETROLOAD_PACKAGE_NAME = 'juloserver.retroloads.164024289081__ecommerce__add_new_partner_iprice'
    retroload = import_module(
        name='.164024289081__ecommerce__add_new_partner_iprice',
        package='juloserver.retroloads',
    )

    def setUp(self):
        # run retroload function to add iprice
        Group.objects.create(name='julo_partners')
        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.ECOMMERCE,
            parent_category_id=1,
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer, application_xid='123123123')

        with patch('{}.ValidationProcess'.format(self.RETROLOAD_PACKAGE_NAME)) as mock_process:
            mock_process_obj = mock_process.return_value
            self.retroload.add_new_partner_iprice(None, None)
            mock_process_obj.validate.assert_called_once()

        self.iprice_user = User.objects.get(username=PartnerConstant.IPRICE)
        self.iprice_partner = Partner.objects.get(user=self.iprice_user)
        token = self.iprice_partner.token
        self.client = APIClient()
        self.client.credentials(
            HTTP_USERNAME=PartnerConstant.IPRICE,
            HTTP_SECRET_KEY=token,
        )

        self.post_data = {
                "partnerUserId": str(self.application.application_xid),
                "paymentType": "JULO_LOAN_FINANCING",
                "externalId": "b113650m",
                "grandAmount": 1620000,
                "address": "tmn melati, tmn melati, , tmn melati",
                "province": "Kepulauan Bangka Belitung",
                "city": "Pangkal Pinang",
                "email": "salam.abdoul4543453@gmail.com",
                "firstName": "Abdoul",
                "lastName": "Salam",
                "mobile": "0801234567891",
                "postcode": "53100",
                "items": [
                {
                    "id": "AJ0-70000-00001",
                    "url": "https://dev-julo-id.iprice.mx/r/pc/?_id=13321637ac8359824108378cd011ef5a1bbd898e",
                    "imageUrl": "https://p.ipricegroup.com/13321637ac8359824108378cd011ef5a1bbd898e_0.jpg",
                    "name": "Vivo Y12 Ram 3 32 Gb New Y12 Garansi Resmi Merah",
                    "price": 1600000,
                    "quantity": 1,
                    "category": "ponsel-tablet",
                    "brandName": "Vivo",
                    "merchantName": "Tokopedia"
                }
            ],
            "successRedirectUrl": "https://dev-julo-id.iprice.mx/checkout/success/",
            "failRedirectUrl": "https://dev-julo-id.iprice.mx/checkout/fail/"
        }

    @patch(f'{PACKAGE_NAME}.check_account_limit')
    def test_iprice_checkout_callback(self, mock_check_account_limit):
        response = self.client.post('/api/ecommerce/v1/callbacks/iprice-checkout', data=self.post_data, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)

        transaction = IpriceTransaction.objects.filter(
            application=self.application,
            customer=self.customer,
        ).last()
        deep_link = "julo://e-commerce/checkout-redirect/iprice"
        expected_response = {
            "transaction_id": transaction.iprice_transaction_xid,
            "application_id": transaction.application.application_xid,
            "redirect_url": "{}?transaction_id={}".format(
                deep_link,
                transaction.iprice_transaction_xid,
            ),
        }
        self.assertEqual(response.data['data'], expected_response)

        mock_check_account_limit.assert_called_once_with(transaction)

    def test_iprice_checkout_callback_bad_authorization(self):
        self.client.credentials(
            HTTP_USERNAME=PartnerConstant.IPRICE,
            HTTP_SECRET_KEY="bad_key",
        )
        response = self.client.post(
            '/api/ecommerce/v1/callbacks/iprice-checkout',
            data=self.post_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_401_UNAUTHORIZED)



    def test_iprice_checkout_bad_request_data(self):
        self.post_data['partnerUserId'] = "asldfhi4kjfdsh"

        response = self.client.post('/api/ecommerce/v1/callbacks/iprice-checkout', data=self.post_data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        self.post_data['partnerUserId'] = "0192380912479"

        response = self.client.post('/api/ecommerce/v1/callbacks/iprice-checkout', data=self.post_data)
        self.assertEqual(response.status_code, HTTP_500_INTERNAL_SERVER_ERROR)

        self.post_data['partnerUserId'] = str(self.application.application_xid)
        self.post_data.pop('grandAmount', None)

        response = self.client.post('/api/ecommerce/v1/callbacks/iprice-checkout', data=self.post_data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)


    def test_iprice_other_partner_authorization(self):
        data = process_register_partner({
            'username': 'grabby',
            'email': 'testing@julofinance.com',
            'partnership_type': PartnershipTypeFactory().id,
            'callback_url': '',
            'callback_token': '',
        })

        self.client.credentials(
            HTTP_USERNAME=data['partner_name'],
            HTTP_SECRET_KEY=data['secret_key']
        )
        response = self.client.post('/api/ecommerce/v1/callbacks/iprice-checkout', data=self.post_data)
        self.assertEqual(response.status_code, HTTP_401_UNAUTHORIZED)


class TestJuloShopCallbacksV1(APITestCase):
    def add_new_partner_juloshop(self):
        partnership_type = PartnershipTypeFactory(
            partner_type_name=PartnershipTypeConstant.JULOSHOP
        )
        email = "finance-payment@juloshopgroup.com"
        partner_data = {
            "username": PartnerConstant.JULOSHOP,
            "email": email,
            "partnership_type": partnership_type.id,
            "callback_url": "",
            "callback_token": "",
        }

        # generate rows in ops.auth_user & ops.partner & ops.partnership_config
        process_register_partner(partner_data)

    def setUp(self):
        self.user = AuthUserFactory()
        Group.objects.create(name='julo_partners')
        self.customer = CustomerFactory(user=self.user)
        self.add_new_partner_juloshop()
        self.application = ApplicationFactory(customer=self.customer)
        self.juloshop_user = User.objects.get(username=PartnerConstant.JULOSHOP)
        self.juloshop_partner = Partner.objects.get(user=self.juloshop_user)
        token = self.juloshop_partner.token
        self.client = APIClient()
        self.client.credentials(
            HTTP_USERNAME=PartnerConstant.JULOSHOP,
            HTTP_SECRET_KEY=token,
        )
        self.post_data = {
            "applicationXID": self.application.application_xid,
            "sellerName": "jd_id",
            "items": [{
                "productID": "AJ0-70000-00001",
                "productName": "Vivo Y12 Ram 3 32 Gb New Y12 Garansi Resmi Merah",
                "price": 1600000,
                "quantity": 1,
                "image": "https://p.julo_group.com/13321637ac8359824108378cd011ef5a1bbd898e_0.jpg",
            }],
            "recipientDetail": {
                "name": "recipient 1",
                "phoneNumber": "0123456789"
            },
            "shippingDetail": {
                "province": "Chau Thanh",
                "city": "Tra Vinh",
                "area": "middle earth",
                "postalCode": "70000",
                "fullAddress": "Khom 2, quoc lo 54, thi tran chau thanh"
            },
            "totalProductAmount": 1600000,
            "shippingFee": 10000,
            "insuranceFee": 5000,
            "discount": 0,
            "finalAmount": 166000,
        }

    def test_authentication_failed(self):
        self.client.credentials(
            HTTP_USERNAME=PartnerConstant.JULOSHOP,
            HTTP_SECRET_KEY='wrong token'
        )
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        self.assertEqual(response.status_code, HTTP_401_UNAUTHORIZED)

    @patch(f'{PACKAGE_NAME}.check_juloshop_account_limit')
    def test_juloshop_checkout_callback(self, mock_check_juloshop_account_limit):
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULOSHOP_WHITELIST, parameters={'application_ids': []}
        )
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["errors"], ['JuloShop tidak ditemukan'])

        fs.update_safely(parameters={'application_ids': [self.application.id]})
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        self.assertEqual(response.status_code, HTTP_200_OK)

        transaction = JuloShopTransaction.objects.filter(
            application=self.application,
            customer=self.customer,
        ).last()
        deep_link = "julo://e-commerce/juloshop/checkout-redirect"
        expected_response = {
            "transaction_id": transaction.transaction_xid,
            "application_id": transaction.application.application_xid,
            "redirect_url": "{}?transaction_id={}".format(
                deep_link,
                transaction.transaction_xid,
            ),
        }
        self.assertEqual(response.data['data'], expected_response)

        mock_check_juloshop_account_limit.assert_called_once_with(transaction)

    def test_juloshop_checkout_bad_request_data(self):
        self.post_data['applicationXID'] = "asldfhi4kjfdsh"
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        self.post_data['applicationXID'] = 192380912479
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid application", response.data['non_field_errors'])

        self.post_data['applicationXID'] = self.application.application_xid
        self.post_data.pop('finalAmount', None)

        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('This field is required.', response.data['finalAmount'])

    @patch('juloserver.ecommerce.juloshop_service.calculate_loan_amount')
    @patch('juloserver.ecommerce.juloshop_service.is_account_limit_sufficient')
    def test_juloshop_checkout_callback_insufficient_credit_limit(
            self,
            mock_is_account_limit_sufficient,
            mock_calculate_loan_amount
    ):
        mock_calculate_loan_amount.return_value = 110000, None, None
        mock_is_account_limit_sufficient.return_value = False
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        transaction = JuloShopTransaction.objects.filter(
            application=self.application,
            customer=self.customer,
        ).last()
        transaction_history = JuloShopStatusHistory.objects.get(transaction=transaction)
        self.assertEqual(transaction_history.status_old, 'draft')
        self.assertEqual(transaction_history.status_new, 'failed')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

        mock_is_account_limit_sufficient.return_value = True
        response = self.client.post(
            '/api/ecommerce/v1/callback/juloshop/checkout', data=self.post_data, format='json'
        )
        transaction = JuloShopTransaction.objects.filter(
            application=self.application,
            customer=self.customer,
        ).last()
        deep_link = "julo://e-commerce/juloshop/checkout-redirect"
        expected_response = {
            "transaction_id": transaction.transaction_xid,
            "application_id": transaction.application.application_xid,
            "redirect_url": "{}?transaction_id={}".format(
                deep_link,
                transaction.transaction_xid,
            ),
        }
        self.assertEqual(response.data['data'], expected_response)

        mock_calculate_loan_amount.assert_called_with(
            application=self.application,
            loan_amount_requested=transaction.transaction_total_amount,
            transaction_type=TransactionType.ECOMMERCE
        )


class TestJuloShopTransactionDetails(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = CleanLoanFactory(
            customer=self.customer, application=self.application, loan_amount=100000
        )
        self.juloshop_transaction = JuloShopTransactionFactory(
            customer=self.customer, application=self.application, loan=self.loan,
            seller_name='bukalapak', transaction_xid='ba679f4b-4446-4952-a166-ae93f31f1d69',
            product_total_amount=100000,
            checkout_info={
                "items": [{
                    "image": "https://google.com",
                    "price": 1725000.0, "quantity": 1, "productID": "618697428",
                    "productName": "AQUA Kulkas 1 Pintu [153 L] AQR-D191 (LB) - Lily Blue"
                }],
                "discount": 400000, "finalAmount": 2000000, "shippingFee": 0, "insuranceFee": 0,
                "shippingDetail": {
                    "area": "Kelapa Dua", "city": "Kabupaten Tangerang",
                    "province": "Banten", "postalCode": "15810",
                    "fullAddress": "Fiordini 3"
                },
                "recipientDetail": {"name": "Alvin", "phoneNumber": "08110000003"},
                "totalProductAmount": 2125000
            },
        )
        self.ecommerce_configuration = EcommerceConfigurationFactory(
            ecommerce_name='Julo Shop',
            extra_config={
                'logos': {
                    'bukalapak': {
                        'url': 'abcd',
                        'name': 'Bukalapak'
                    }
                },
                'default_images': {
                    'invalid_product_image': 'abcdef.com'
                }
            }
        )

    def test_get_transaction_details_success(self):
        url = '/api/ecommerce/v1/juloshop/get_details?' \
              'transaction_xid=ba679f4b-4446-4952-a166-ae93f31f1d69'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data']['transaction_details']['items'], {
                "sellerLogo": "abcd",
                "image": "https://google.com",
                "defaultImage": "abcdef.com",
                "price": 2000000,
                "quantity": 1,
                "productID": "618697428",
                "productName": "AQUA Kulkas 1 Pintu [153 L] AQR-D191 (LB) - Lily Blue"
            }
        )
        self.assertEqual(
            response.json()['data']['transaction_details']['shipping_details'], {
                "area": "Kelapa Dua",
                "city": "Kabupaten Tangerang",
                "province": "Banten",
                "postalCode": "15810",
                "fullAddress": "Fiordini 3"
            }
        )

        self.juloshop_transaction.checkout_info['items'][0]['image'] = 'xyz.com'
        self.juloshop_transaction.save()

        response = self.client.get(url)
        error_image_response = {
            "sellerLogo": "abcd",
            "image": "xyz.com",
            "defaultImage": "abcdef.com",
            "price": 2000000,
            "quantity": 1,
            "productID": "618697428",
            "productName": "AQUA Kulkas 1 Pintu [153 L] AQR-D191 (LB) - Lily Blue"
        }
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()['data']['transaction_details']['items'], error_image_response
        )

    def test_get_transaction_details_incorrect_transaction_xid(self):
        url = '/api/ecommerce/v1/juloshop/get_details'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['transaction_xid'][0], 'This field is required.')

        url = '/api/ecommerce/v1/juloshop/get_details?transaction_xid=MakeTheWorldGoAway-Duffy'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['transaction_xid'][0],
                         '"MakeTheWorldGoAway-Duffy" is not a valid UUID.')

        url = '/api/ecommerce/v1/juloshop/get_details?transaction_xid=123'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['transaction_xid'][0], '"123" is not a valid UUID.')

        url = '/api/ecommerce/v1/juloshop/get_details?transaction_xid='
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['transaction_xid'][0], '"" is not a valid UUID.')

        url = '/api/ecommerce/v1/juloshop/get_details?transaction_xid=' \
              'ba679f4b-4446-4952-a166-ae93f31f1d70'
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.json()['data']['transaction_details'], {})

    def test_application_none(self):
        url = '/api/ecommerce/v1/juloshop/get_details?' \
              'transaction_xid=ba679f4b-4446-4952-a166-ae93f31f1d69'
        self.application.delete()

        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)


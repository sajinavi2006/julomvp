
import uuid

from django.conf import settings
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR
from rest_framework.test import APIClient, APITestCase

from juloserver.ecommerce.tests.factories import EcommerceConfigurationFactory, IpriceTransactionFactory
from juloserver.ecommerce.constants import CategoryType, EcommerceConstant
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import ApplicationFactory, AuthUserFactory, CustomerFactory, \
    FeatureSettingFactory


class TestEcommerceCategory(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.base_url = settings.ECOMMERCE_LOGO_STATIC_FILE_PATH

    def test_get_ecommerce_category(self):
        self.iprice = EcommerceConfigurationFactory(
            id=1,
            ecommerce_name=EcommerceConstant.IPRICE,
            selection_logo=f'{self.base_url}/iprice_logo',
            background_logo=f'{self.base_url}/iprice_background_logo',
            text_logo=f'{self.base_url}/iprice_text_logo',
            color_scheme='#00FF10',
            url='https://julo-id.iprice.mx/',
            is_active=True,
            category_type=CategoryType.MARKET,
            order_number=1,
        )
        self.shoppe = EcommerceConfigurationFactory(
            id=2,
            ecommerce_name=EcommerceConstant.SHOPEE,
            selection_logo=f'{self.base_url}/shoppe_selection_logo',
            background_logo=f'{self.base_url}/shoppe_background_logo',
            text_logo=f'{self.base_url}/shoppe_text_logo',
            color_scheme='#00FF11',
            url='https://shoppe.com',
            is_active=True,
            category_type=CategoryType.ECOMMERCE,
            order_number=1,
        )
        expected_marketplace = [
            {
                'id': self.iprice.id,
                'marketplace_id': self.iprice.ecommerce_name,
                'marketplace_name': self.iprice.ecommerce_name,
                'marketplace_logo': self.iprice.selection_logo,
                'marketplace_background': self.iprice.background_logo,
                'marketplace_colour': self.iprice.color_scheme,
                'marketplace_uri': "{}?partner_user_id={}".format(
                    self.iprice.url,
                    self.application.application_xid,
                ),
                'marketplace_account_icon': self.iprice.text_logo,
                'marketplace_order_tracking_url': '',
                'category_type': self.iprice.category_type,
                'order_number': self.iprice.order_number,
                'extra_config': None
            }
        ]

        expected_category = [
            {
                'id': self.shoppe.id,
                'ecommerce_id': self.shoppe.ecommerce_name,
                'ecommerce_name': self.shoppe.ecommerce_name,
                'ecommerce_logo': self.shoppe.selection_logo,
                'ecommerce_background': self.shoppe.background_logo,
                'ecommerce_colour': self.shoppe.color_scheme,
                'ecommerce_uri': self.shoppe.url,
                'ecommerce_account_icon': self.shoppe.text_logo,
                'category_type': self.shoppe.category_type,
                'ecommerce_web_view_uri': "{}?ecommerce_name=#{}".format(
                    settings.WEBVIEW_ECOMMERCE_URL,
                    self.shoppe.ecommerce_name,
                ),
                'order_number': self.shoppe.order_number,
                'extra_config': None
            }
        ]

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='7.10.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_category, response['category'])
        self.assertEqual(expected_marketplace, response['marketPlace'])

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='7.9.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_category, response['category'])
        self.assertEquals(response['marketPlace'], [])

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='5.0.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_category, response['category'])
        self.assertEquals(response['marketPlace'], [])

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='7.9.99')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_category, response['category'])
        self.assertEquals(response['marketPlace'], [])

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='8.10.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_category, response['category'])
        self.assertEqual(expected_marketplace, response['marketPlace'])

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='99.99.10')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_category, response['category'])
        self.assertEqual(expected_marketplace, response['marketPlace'])

    def test_juloshop_category(self):
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULOSHOP_WHITELIST, parameters={'application_ids': []}
        )
        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='99.99.10')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"], ['Ecommerce tidak ditemukan'])

        self.juloshop = EcommerceConfigurationFactory(
            id=3,
            ecommerce_name=EcommerceConstant.JULOSHOP,
            selection_logo=f'{self.base_url}/juloshop_logo',
            background_logo=f'{self.base_url}/juloshop_background_logo',
            text_logo=f'{self.base_url}/juloshop_text_logo',
            color_scheme='#00FF10',
            url='https://julo-id-testing.juloshop/',
            is_active=True,
            category_type=CategoryType.MARKET,
            order_number=1,
            extra_config={
                "logos": {
                    "jdid": {
                        "url": "https://statics.julo.co.id/juloserver/staging/static/images/"
                               "ecommerce/juloshop/jdid_text_logo.png",
                        "name": "JD.ID"
                    },
                    "bukalapak": {
                        "url": "https://statics.julo.co.id/juloserver/staging/static/images/"
                               "ecommerce/juloshop/bukalapak_text_logo_updated.png",
                        "name": "Bukalapak"
                    }
                },
                "default_images": {
                    "invalid_product_image": "https://statics.julo.co.id/juloserver/staging/static/"
                                             "images/ecommerce/juloshop/invalid_product_image.png"
                },
                "urls": {
                    "order_tracking_url": "https://staging.vospay.id/juloshop/BL/"
                                          "order-history?env=staging&application_xid="
                }
            }
        )
        fs.update_safely(parameters={'application_ids': [self.application.id]})
        expected_marketplace = [
            {
                'id': self.juloshop.id,
                'marketplace_id': self.juloshop.ecommerce_name,
                'marketplace_name': self.juloshop.ecommerce_name,
                'marketplace_logo': self.juloshop.selection_logo,
                'marketplace_background': self.juloshop.background_logo,
                'marketplace_colour': self.juloshop.color_scheme,
                'marketplace_uri': self.juloshop.url,
                'marketplace_account_icon': self.juloshop.text_logo,
                'marketplace_order_tracking_url': self.juloshop.extra_config['urls'][
                    'order_tracking_url'],
                'category_type': self.juloshop.category_type,
                'order_number': self.juloshop.order_number,
                'extra_config': self.juloshop.extra_config
            }
        ]
        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='99.99.10')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(expected_marketplace, response['marketPlace'])

        response = self.client.get('/api/ecommerce/v2/category')
        self.assertEqual(response.status_code, 400)

        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='7.10.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEqual(self.juloshop.extra_config['urls']['order_tracking_url'],
                         response['marketPlace'][0]['marketplace_order_tracking_url'])

        EcommerceConfigurationFactory(
            id=2,
            ecommerce_name=EcommerceConstant.SHOPEE,
            is_active=True,
            category_type=CategoryType.ECOMMERCE
        )
        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='7.9.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEquals(response['marketPlace'], [])

        self.juloshop.update_safely(extra_config={})
        response = self.client.get('/api/ecommerce/v2/category', HTTP_X_APP_VERSION='7.10.0')
        self.assertEqual(response.status_code, 200)
        response = response.json()['data']
        self.assertEquals(response['marketPlace'][0]['marketplace_order_tracking_url'], '')


class TestIpriceViews(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_get_transaction(self):
        transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
        )
        response = self.client.get(
            '/api/ecommerce/v2/get-iprice-transaction-info/{}'.format(transac.iprice_transaction_xid)
        )
        self.assertEqual(response.status_code, HTTP_200_OK)

    def test_get_transaction_wrong_uuid(self):
        # badly formed UUID string
        fake_transaction_id = "0jfkeofjf39"
        response = self.client.get(
            '/api/ecommerce/v2/get-iprice-transaction-info/{}'.format(fake_transaction_id)
        )

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

        wrong_transaction_id = str(uuid.uuid4())
        response = self.client.get(
            '/api/ecommerce/v2/get-iprice-transaction-info/{}'.format(wrong_transaction_id)
        )

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

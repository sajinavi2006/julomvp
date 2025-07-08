import mock
from django.conf import settings
from django.test.testcases import TestCase
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import SepulsaProduct
from juloserver.julo.tests.factories import FeatureSettingFactory, SepulsaProductFactory

from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory
from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.services.product_related import \
    determine_transaction_method_by_sepulsa_product

from juloserver.payment_point.services import sepulsa as sepulsa_services
from juloserver.payment_point.tasks.product_related import (
    update_product_sepulsa_subtask,
    auto_update_sepulsa_product
)

class TestProductRelatedServices(TestCase):
    def setUp(self):
        self.prepaid_method = TransactionMethod.objects.get(pk=3)
        self.postpaid_method = TransactionMethod.objects.get(pk=4)
        self.ewallet_method = TransactionMethod.objects.get(pk=5)
        self.pln_method = TransactionMethod.objects.get(pk=6)
        self.bpjs_kesehatan_method = TransactionMethod.objects.get(pk=7)

    def test_determine_transaction_method_by_sepulsa_product(self):
        product_pulsa = SepulsaProduct(type=SepulsaProductType.MOBILE,
                                       category=SepulsaProductCategory.PRE_PAID_AND_DATA[0])
        pulsa_method = determine_transaction_method_by_sepulsa_product(product_pulsa)
        self.assertEqual(self.prepaid_method, pulsa_method)

        product_pascabayar = SepulsaProduct(type=SepulsaProductType.MOBILE,
                                            category=SepulsaProductCategory.POSTPAID[0])
        pascabayar_method = determine_transaction_method_by_sepulsa_product(product_pascabayar)
        self.assertEqual(self.postpaid_method, pascabayar_method)

        product_ewallet = SepulsaProduct(type=SepulsaProductType.EWALLET,
                                         category='ovo')
        dompet_digital_method = determine_transaction_method_by_sepulsa_product(product_ewallet)
        self.assertEqual(self.ewallet_method, dompet_digital_method)

        product_pln = SepulsaProduct(type=SepulsaProductType.ELECTRICITY,
                                     category='prepaid')
        pln_method = determine_transaction_method_by_sepulsa_product(product_pln)
        self.assertEqual(self.pln_method, pln_method)

        product_bpjs = SepulsaProduct(type=SepulsaProductType.BPJS,
                                      category=SepulsaProductCategory.BPJS_KESEHATAN[0])
        bpjs_kes_method = determine_transaction_method_by_sepulsa_product(product_bpjs)
        self.assertEqual(self.bpjs_kesehatan_method, bpjs_kes_method)


class TestSepulsaClientServices(TestCase):
    def setUp(self):
        self.new_sepulsa_url_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.USE_NEW_SEPULSA_BASE_URL,
        )

    def test_get_sepulsa_base_url(self):
        self.assertEqual(
            sepulsa_services.get_sepulsa_base_url(),
            settings.NEW_SEPULSA_BASE_URL
        )

        self.new_sepulsa_url_setting.is_active = False
        self.new_sepulsa_url_setting.save()
        self.assertEqual(
            sepulsa_services.get_sepulsa_base_url(),
            settings.SEPULSA_BASE_URL)


class TestUpdateSepulsaProduct(TestCase):
    def setUp(self):
        self.first_product = SepulsaProductFactory(
            product_id='1',
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID,
            partner_price=10000,
            customer_price=16000,
            is_active=True,
            customer_price_regular=11000,
        )
        self.second_product = SepulsaProductFactory(
            product_id='2',
            type=SepulsaProductType.BPJS,
            category=SepulsaProductCategory.BPJS_KESEHATAN,
            partner_price=20000,
            customer_price=26000,
            is_active=True,
            customer_price_regular=21000,
        )
        self.third_product = SepulsaProductFactory(
            product_id='3',
            type=SepulsaProductType.MOBILE,
            category=SepulsaProductCategory.PRE_PAID_AND_DATA,
            partner_price=30000,
            customer_price=36000,
            is_active=True,
            customer_price_regular=31000,
        )
        self.fourth_product = SepulsaProductFactory(
            product_id='4',
            type=SepulsaProductType.MOBILE,
            category=SepulsaProductCategory.PRE_PAID_AND_DATA,
            partner_price=123,
            customer_price=123,
            is_active=True,
            customer_price_regular=31000,
            is_not_blocked=True
        )

    def test_update_update_product_sepulsa_subtask(self):
        new_price = 3500
        products = [
            {
                'product_id': '1',
                'type': 'electricity_postpaid',
                'label': 'PLN Postpaid BAG Jatim',
                'operator': 'pln_postpaid',
                'nominal': '2500',
                'price': new_price,
                'enabled': '1'
            },
            {
                'product_id': '2',
                'type': 'electricity_postpaid',
                'label': 'PLN Postpaid Jatelindo',
                'operator': 'pln_postpaid',
                'nominal': '3500',
                'price': new_price,
                'enabled': '1'
            },
            {'product_id': '3',
                'type': 'mobile_postpaid',
                'label': 'IM3 Postpaid test',
                'operator': 'pln',
                'nominal': '4500',
                'price': new_price,
                'enabled': '0'
            }
        ]
        data_product_ids = {
            p['product_id']: {'price': p['price'], 'enabled': p['enabled']} for p in products}

        update_product_sepulsa_subtask(data_product_ids)
        for product in SepulsaProduct.objects.exclude(product_id='4'):
            self.assertEqual(product.partner_price, new_price)
            self.assertEqual(product.customer_price_regular, new_price)
            self.assertEqual(product.customer_price, new_price + (new_price * 0.1))

    @mock.patch('juloserver.payment_point.tasks.product_related.SepulsaLoanService')
    @mock.patch('juloserver.payment_point.tasks.product_related.update_product_sepulsa_subtask')
    @mock.patch('juloserver.payment_point.tasks.product_related.SepulsaService')
    def test_auto_update_sepulsa_product(self, mock_sepulsa_service, mock_update_product, mock_sepulsa_loan_service):
        products = [
            {
                'product_id': '1',
                'type': 'electricity_postpaid',
                'label': 'PLN Postpaid BAG Jatim',
                'operator': 'pln_postpaid',
                'nominal': '2500',
                'price': '321',
                'enabled': '1'
            },
            {
                'product_id': '2',
                'type': 'electricity_postpaid',
                'label': 'PLN Postpaid Jatelindo',
                'operator': 'pln_postpaid',
                'nominal': '3500',
                'price': '231',
                'enabled': '1'
            }
        ]
        mock_sepulsa_loan_service.return_value.get_sepulsa_product.return_.value = products
        auto_update_sepulsa_product()
        mock_update_product.delay.assert_called_once()

        #the product doesn't exist on the Sepulsa server
        fourth_product = SepulsaProduct.objects.get(product_id='4')
        self.assertEqual(fourth_product.is_active, False)
        self.assertEqual(fourth_product.is_not_blocked, False)
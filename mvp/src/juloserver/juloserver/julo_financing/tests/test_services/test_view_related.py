from datetime import datetime
from io import BytesIO
from unittest.mock import ANY, call, patch
import pytz

from PIL import Image
from past.utils import old_div
from django.core.files.uploadedfile import SimpleUploadedFile

from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.apiv2.tests.test_apiv2_services import CustomerFactory
from juloserver.account.constants import AccountConstant
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditMatrixRepeatFactory,
    CustomerFactory,
    FeatureSettingFactory,
    ImageFactory,
    LenderFactory,
    LoanFactory,
    LoanHistoryFactory,
    PartnerFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.julo_financing.constants import (
    JFinancingFeatureNameConst,
    JFinancingProductListConst,
    JFinancingProductImageType,
    JFinancingStatus,
)
from juloserver.julo.utils import display_rupiah_no_space
from juloserver.julo_financing.models import JFinancingCheckout
from juloserver.julo_financing.exceptions import (
    CheckoutNotFound,
    InvalidVerificationStatus,
    ProductOutOfStock,
    JFinancingProductLocked,
    UserNotAllowed,
    ProductNotFound,
)
from juloserver.julo_financing.services.view_related import (
    JFinancingTransactionDetailViewService,
    JFinancingUploadSignatureService,
    get_account_available_limit,
    get_j_financing_user_info,
    get_min_quantity_to_show_product_in_list,
    get_mapping_thumbnail_url_for_list_j_financing_product,
    get_list_j_financing_product,
    get_j_financing_product_detail,
    get_j_financing_product_images,
    JFinancingSubmitViewService,
    get_customer_jfinancing_transaction_history,
)
from juloserver.julo_financing.tasks import upload_jfinancing_signature_image_task
from juloserver.julo_financing.tests.factories import (
    JFinancingCategoryFactory,
    JFinancingCheckoutFactory,
    JFinancingProductFactory,
    JFinancingCheckoutFactory,
    JFinancingVerificationFactory,
    JFinancingProductSaleTagFactory,
    JFinancingProductSaleTagDetailFactory,
)

from juloserver.julocore.python2.utils import py2round
from juloserver.loan.constants import LoanFeatureNameConst, LoanTaxConst
from juloserver.loan.exceptions import AccountLimitExceededException, LoanTransactionLimitExceeded
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.julo.models import FeatureSetting, Image as ImageModel, StatusLookup
from juloserver.payment_point.constants import TransactionMethodCode


class TestViewRelated(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(
            fullname="John Doe",
            phone="01234567890",
            address_street_num="1",
            address_kelurahan="2",
            address_kecamatan="3",
            address_kabupaten="4",
            address_provinsi="5",
            address_kodepos="6",
            address_detail="Apt 4B",
        )
        self.account = AccountFactory(customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE,
            is_active=True,
            parameters={
                "province_shipping_fee": {
                    "JAKARTA": 10000,
                }
            },
        )
        self.best_seller_tag = JFinancingProductSaleTagFactory.best_seller()
        self.free_insurance_tag = JFinancingProductSaleTagFactory.free_insurance()
        self.free_data_tag = JFinancingProductSaleTagFactory.free_data_package()

    def test_get_account_available_limit(self):
        # no account limit
        self.assertEqual(get_account_available_limit(customer=self.customer), 0)

        # single account limit
        AccountLimitFactory(account=self.account, available_limit=10000)
        self.assertEqual(get_account_available_limit(customer=self.customer), 10000)

        # multiple account limits
        AccountLimitFactory(account=self.account, available_limit=20000)
        self.assertEqual(get_account_available_limit(customer=self.customer), 20000)

    @patch('juloserver.julo_financing.services.view_related.get_phone_from_applications')
    @patch('juloserver.julo_financing.services.view_related.get_account_available_limit')
    def test_get_j_financing_user_info(self, mock_get_limit, mock_get_phone):
        mock_get_limit.return_value = 5000

        # address and address detail is empty when province name is not supported
        expected_info = {
            "full_name": "John Doe",
            "phone_number": "01234567890",
            "address": "",
            "address_detail": "",
            "available_limit": 5000,
            "province_name": "",
        }
        self.assertEqual(get_j_financing_user_info(customer=self.customer), expected_info)
        mock_get_phone.assert_not_called()

        # test customer table does not have phone number
        self.customer.phone = None
        self.customer.address_provinsi = "Jakarta"
        self.customer.save()
        mock_get_phone.return_value = "09876543210"
        expected_info = {
            "full_name": "John Doe",
            "phone_number": "09876543210",
            "address": "1, 2, 3, 4, Jakarta, 6",
            "address_detail": "Apt 4B",
            "available_limit": 5000,
            "province_name": "Jakarta",
        }
        self.assertEqual(get_j_financing_user_info(customer=self.customer), expected_info)
        mock_get_phone.assert_called()

    @patch('juloserver.julo_financing.services.view_related.FeatureSettingHelper')
    def test_get_min_quantity_to_show_product_in_list(self, mock_fs_helper):
        mock_fs_instance = mock_fs_helper.return_value
        mock_fs_instance.is_active = True
        mock_fs_instance.params = {'min_quantity_to_show_product_in_list': 5}

        # fs is active and has params to config min quantity
        self.assertEqual(get_min_quantity_to_show_product_in_list(), 5)
        mock_fs_helper.assert_called_once_with(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION
        )

        # fs is active but no params
        mock_fs_instance.params = {}
        self.assertEqual(
            get_min_quantity_to_show_product_in_list(),
            JFinancingProductListConst.MIN_PRODUCT_QUANTITY,
        )

        # fs is inactive
        mock_fs_instance.is_active = False
        self.assertEqual(
            get_min_quantity_to_show_product_in_list(),
            JFinancingProductListConst.MIN_PRODUCT_QUANTITY,
        )

    @patch('juloserver.julo.models.get_oss_presigned_url')
    def test_get_mapping_thumbnail_url_for_list_j_financing_product(
        self, mock_get_oss_presigned_url
    ):
        sample_thumbnail_url = 'https://example.com/thumbnail.jpg'
        mock_get_oss_presigned_url.return_value = sample_thumbnail_url
        for image_source_id in [1, 2, 3]:
            last_image = ImageFactory(
                image_source=image_source_id,
                image_type=JFinancingProductImageType.PRIMARY,
                service='oss',
            )

        # image source id 3 is not primary
        last_image.image_type = JFinancingProductImageType.DETAIL
        last_image.save()

        expected = {1: sample_thumbnail_url, 2: sample_thumbnail_url}

        # existing products
        result = get_mapping_thumbnail_url_for_list_j_financing_product(product_ids=[1, 2])
        self.assertEqual(result, expected)

        # only show primary images
        result = get_mapping_thumbnail_url_for_list_j_financing_product(product_ids=[1, 2, 3])
        self.assertEqual(result, expected)

        # duplicate product ids
        result = get_mapping_thumbnail_url_for_list_j_financing_product(product_ids=[1, 1, 2])
        self.assertEqual(result, expected)

        # non-existing product
        result = get_mapping_thumbnail_url_for_list_j_financing_product(product_ids=[4])
        self.assertEqual(result, {})

        # mixed non-existing and existing product
        result = get_mapping_thumbnail_url_for_list_j_financing_product(product_ids=[1, 4])
        self.assertEqual(result, {1: sample_thumbnail_url})

    @patch(
        'juloserver.julo_financing.services.view_related.get_min_quantity_to_show_product_in_list'
    )
    @patch(
        'juloserver.julo_financing.services.view_related.'
        'get_mapping_thumbnail_url_for_list_j_financing_product'
    )
    def test_get_list_j_financing_product(self, mock_get_thumbnail, mock_get_min_quantity):
        category1 = JFinancingCategoryFactory(name="Test Category 1")
        category2 = JFinancingCategoryFactory(name="Test Category 2")
        product1 = JFinancingProductFactory(
            name="Product 1",
            price=1000,
            display_installment_price=1_000_000,
            quantity=10,
            j_financing_category=category1,
        )
        product2 = JFinancingProductFactory(
            name="Product 2",
            price=2000,
            display_installment_price=200,
            quantity=20,
            j_financing_category=category2,
        )
        product3 = JFinancingProductFactory(
            name="Inactive Product",
            price=3000,
            display_installment_price=300,
            quantity=30,
            j_financing_category=category1,
            is_active=False,
        )

        # set up tags
        JFinancingProductSaleTagDetailFactory(
            primary=True,
            jfinancing_product=product2,
            jfinancing_product_sale_tag=self.best_seller_tag,
        )
        JFinancingProductSaleTagDetailFactory(
            primary=False,
            jfinancing_product=product2,
            jfinancing_product_sale_tag=self.free_insurance_tag,
        )
        JFinancingProductSaleTagDetailFactory(
            primary=False,
            jfinancing_product=product2,
            jfinancing_product_sale_tag=self.free_data_tag,
        )
        self.free_data_tag.is_active = False
        self.free_data_tag.save()

        mock_get_min_quantity.return_value = 5
        mock_get_thumbnail.return_value = {
            product1.id: 'url1',
            product2.id: 'url2',
            product3.id: 'url3',
        }

        # no category and min quantity is 5 => product 1 and 2
        result = get_list_j_financing_product(category_id=None)
        self.assertEqual(len(result), 2)

        self.assertEqual(result[0]['id'], product2.id)
        self.assertEqual(result[0]['name'], "Product 2")
        self.assertEqual(result[0]['price'], 2000)
        self.assertEqual(result[0]['display_installment_price'], 'Rp200')
        self.assertEqual(result[0]['thumbnail_url'], 'url2')

        self.assertEqual(
            result[0]['sale_tags'],
            [
                {
                    "primary": True,
                    "image_url": self.best_seller_tag.tag_image_url,
                    "tag_name": self.best_seller_tag.tag_name,
                },
                {
                    "primary": False,
                    "image_url": self.free_insurance_tag.tag_image_url,
                    "tag_name": self.free_insurance_tag.tag_name,
                },
            ],
        )

        self.assertEqual(result[1]['id'], product1.id)
        self.assertEqual(result[1]['name'], "Product 1")
        self.assertEqual(result[1]['price'], 1000)
        self.assertEqual(result[1]['sale_tags'], [])
        self.assertEqual(result[1]['display_installment_price'], 'Rp1.000.000')
        self.assertEqual(result[1]['thumbnail_url'], 'url1')
        self.assertEqual(result[1]['sale_tags'], [])

        # no category and min quantity is 20 => only product 2
        mock_get_min_quantity.return_value = 20
        result = get_list_j_financing_product(category_id=None)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]['id'], product2.id)

        # category 1 and min quantity is 5 => only product 1
        mock_get_min_quantity.return_value = 5
        result = get_list_j_financing_product(category_id=category1)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]['id'], product1.id)

        # non-existing category
        result = get_list_j_financing_product(category_id=9999)
        self.assertEqual(len(result), 0)

        # non-exist thumbnail
        mock_get_thumbnail.return_value = {product1.id: 'url1'}
        result = get_list_j_financing_product(category_id=None)

        self.assertEqual(result[0]['id'], product2.id)
        self.assertEqual(result[0]['name'], "Product 2")
        self.assertEqual(result[0]['price'], 2000)
        self.assertEqual(result[0]['display_installment_price'], 'Rp200')
        self.assertEqual(result[0]['thumbnail_url'], '')

    @patch('juloserver.julo.models.get_oss_presigned_url')
    def test_get_j_financing_product_images(self, mock_get_oss_presigned_url):
        sample_image_url = 'https://example.com/example.jpg'
        mock_get_oss_presigned_url.return_value = sample_image_url

        product_id = 1

        ImageFactory(
            image_source=product_id,
            image_type=JFinancingProductImageType.PRIMARY,
            service='oss',
        )
        ImageFactory(
            image_source=product_id,
            image_type=JFinancingProductImageType.DETAIL,
            service='oss',
        )

        # existing product
        result = get_j_financing_product_images(product_id=product_id)
        self.assertEqual(result, [sample_image_url, sample_image_url])

        # non-existing product
        result = get_j_financing_product_images(product_id=0)
        self.assertEqual(result, [])

    @patch(
        'juloserver.julo_financing.services.view_related.get_min_quantity_to_show_product_in_list'
    )
    @patch('juloserver.julo_financing.services.view_related.get_j_financing_product_images')
    def test_get_j_financing_product_detail(
        self, mock_get_j_financing_product_images, mock_get_min_quantity
    ):
        mock_get_j_financing_product_images.return_value = []

        active_product = JFinancingProductFactory(
            name="Active Product",
            price=1000,
            display_installment_price=1_000_000,
            description="This is an active product",
            quantity=5,
            is_active=True,
        )
        # set up tags
        JFinancingProductSaleTagDetailFactory(
            primary=True,
            jfinancing_product=active_product,
            jfinancing_product_sale_tag=self.best_seller_tag,
        )
        JFinancingProductSaleTagDetailFactory(
            primary=False,
            jfinancing_product=active_product,
            jfinancing_product_sale_tag=self.free_insurance_tag,
        )
        JFinancingProductSaleTagDetailFactory(
            primary=False,
            jfinancing_product=active_product,
            jfinancing_product_sale_tag=self.free_data_tag,
        )
        self.free_data_tag.is_active = False
        self.free_data_tag.save()

        # images
        ImageFactory(
            image_source=active_product.id,
            image_type=JFinancingProductImageType.PRIMARY,
            service='oss',
        )
        ImageFactory(
            image_source=active_product.id,
            image_type=JFinancingProductImageType.DETAIL,
            service='oss',
        )

        # active product & quantity is >= min quantity
        mock_get_min_quantity.return_value = 5
        result = get_j_financing_product_detail(product_id=active_product.id)
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], active_product.id)
        self.assertEqual(result['name'], "Active Product")
        self.assertEqual(result['price'], 1000)
        self.assertEqual(result['display_installment_price'], 'Rp1.000.000')
        self.assertEqual(result['description'], "This is an active product")
        self.assertEqual(result['images'], [])

        self.assertEqual(len(result['sale_tags']), 2)
        self.assertEqual(
            result['sale_tags'],
            [
                {
                    "primary": True,
                    "image_url": self.best_seller_tag.tag_image_url,
                    "tag_name": self.best_seller_tag.tag_name,
                },
                {
                    "primary": False,
                    "image_url": self.free_insurance_tag.tag_image_url,
                    "tag_name": self.free_insurance_tag.tag_name,
                },
            ],
        )

        # active product & quantity is < min quantity
        mock_get_min_quantity.return_value = 6
        with self.assertRaises(ProductOutOfStock):
            result = get_j_financing_product_detail(product_id=active_product.id)

        # inactive product
        inactive_product = JFinancingProductFactory(
            name="Inactive Product",
            price=2000,
            display_installment_price=200,
            description="This is an inactive product",
            is_active=False,
        )
        with self.assertRaises(ProductNotFound):
            result = get_j_financing_product_detail(product_id=inactive_product.id)

        with self.assertRaises(ProductNotFound):
            result = get_j_financing_product_detail(product_id=0)


class TestGetCustomerJFinancingTransactionHistory(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.jfinancing_product1 = JFinancingProductFactory(
            name="X",
        )
        self.jfinancing_product2 = JFinancingProductFactory(
            name="Y",
        )
        self.jfinancing_product3 = JFinancingProductFactory(
            name="Z",
        )

        # transaction 1
        self.date1 = "12 Jun 2024"
        self.loan_amount1 = 110_000
        self.loan1 = LoanFactory(
            customer=self.customer,
            status=StatusLookupFactory(
                status_code=209,
            ),
            loan_amount=self.loan_amount1,
        )
        self.checkout1_price = 100_000
        self.checkout1 = JFinancingCheckoutFactory(
            customer=self.customer,
            j_financing_product=self.jfinancing_product1,
            price=self.checkout1_price,
        )
        self.checkout1.cdate = datetime.strptime(self.date1, '%d %b %Y')
        self.checkout1.save()

        self.verification1 = JFinancingVerificationFactory(
            validation_status=JFinancingStatus.ON_REVIEW,
            loan=self.loan1,
            j_financing_checkout=self.checkout1,
        )
        ImageFactory(
            image_source=self.jfinancing_product1.id,
            image_type=JFinancingProductImageType.PRIMARY,
            thumbnail_url="img1",
        )

        # transaction 2
        self.date2 = "01 Jul 2024"
        self.loan_amount2 = 120_000
        self.loan2 = LoanFactory(
            customer=self.customer,
            status=StatusLookupFactory(
                status_code=220,
            ),
            loan_amount=self.loan_amount2,
        )
        self.checkout2_price = 90_000
        self.checkout2 = JFinancingCheckoutFactory(
            customer=self.customer,
            j_financing_product=self.jfinancing_product2,
            price=self.checkout1_price,
            cdate=datetime.strptime(self.date2, '%d %b %Y'),
        )
        self.checkout2.cdate = datetime.strptime(self.date2, '%d %b %Y')
        self.checkout2.save()

        self.verification2 = JFinancingVerificationFactory(
            validation_status=JFinancingStatus.ON_DELIVERY,
            loan=self.loan2,
            j_financing_checkout=self.checkout2,
        )
        ImageFactory(
            image_source=self.jfinancing_product2.id,
            image_type=JFinancingProductImageType.PRIMARY,
            thumbnail_url="img2",
        )

        # transaction 3
        self.date3 = "05 Jul 2024"
        self.loan_amount3 = 80_000
        self.loan3 = LoanFactory(
            customer=self.customer,
            status=StatusLookupFactory(
                status_code=212,
            ),
            loan_amount=self.loan_amount2,
        )
        self.checkout3 = JFinancingCheckoutFactory(
            customer=self.customer,
            j_financing_product=self.jfinancing_product3,
            price=self.checkout1_price,
        )
        self.verification3 = JFinancingVerificationFactory(
            validation_status=JFinancingStatus.INITIAL,
            loan=self.loan3,
            j_financing_checkout=self.checkout3,
        )

    @patch('juloserver.julo.models.get_oss_presigned_url')
    def test_ok_get_customer_jfinancing_transaction_history(self, mock_get_oss_presigned_url):
        sample_thumbnail_url = 'https://example.com/thumbnail.jpg'
        mock_get_oss_presigned_url.return_value = sample_thumbnail_url

        data = get_customer_jfinancing_transaction_history(
            customer_id=self.customer.id,
        )

        expected_data = {
            "checkouts": [
                {
                    "id": self.checkout2.id,
                    "display_price": display_rupiah_no_space(self.checkout2.price),
                    "display_loan_amount": display_rupiah_no_space(self.loan2.loan_amount),
                    "product_name": self.jfinancing_product2.name,
                    "thumbnail_url": sample_thumbnail_url,
                    "status": "Pesanan dikirim",
                    "transaction_date": self.date2,
                },
                {
                    "id": self.checkout1.id,
                    "display_price": display_rupiah_no_space(self.checkout1.price),
                    "display_loan_amount": display_rupiah_no_space(self.loan1.loan_amount),
                    "product_name": self.jfinancing_product1.name,
                    "thumbnail_url": sample_thumbnail_url,
                    "status": "Menunggu konfirmasi",
                    "transaction_date": self.date1,
                },
            ]
        }

        self.assertEqual(
            data,
            expected_data,
        )

        mock_get_oss_presigned_url.assert_has_calls(
            [
                call(ANY, "img1", expires_in_seconds=ANY),
                call(ANY, "img2", expires_in_seconds=ANY),
            ]
        )


class TestJFinancingSubmitViewService(TestCase):
    def setUp(self) -> None:
        StatusLookupFactory(status_code=LoanStatusCodes.DRAFT)

        self.transaction_method = TransactionMethodFactory.jfinancing()
        self.jfinancing_product1 = JFinancingProductFactory(
            name="X",
            price=80_000,
        )
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=1_000_000)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.cm_provision_fee = 0.1
        self.product = ProductLookupFactory(origination_fee_pct=self.cm_provision_fee)
        self.credit_matrix = CreditMatrixFactory(
            product=self.product,
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.product_line,
        )
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.transaction_method,
            version=1,
            interest=0.5,
            provision=self.cm_provision_fee,
            max_tenure=6,
        )
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="Fiona!")
        self.lender = LenderFactory(user=self.user_partner)
        self.customer.address_provinsi = "Jakarta"
        self.customer.save()
        self.feature_setting = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE,
            is_active=True,
            parameters={
                "province_shipping_fee": {
                    "JAKARTA": 10000,
                    "JAKARTA BARAT": 0,
                }
            },
        )

        self.tax_percent = 0.1
        self.tax_fs = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": self.tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

    @patch('juloserver.loan.services.loan_related.is_julo_one_product_locked_and_reason')
    def test_submit_product_locked(self, mock_julo_one_product_locked):
        mock_julo_one_product_locked.return_value = True, ""

        submit_data = {
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

        with self.assertRaises(JFinancingProductLocked):
            service = JFinancingSubmitViewService(
                customer=self.customer,
                submit_data=submit_data,
            )
            service.submit()

        checkout_exists = JFinancingCheckout.objects.filter(
            j_financing_product_id=self.jfinancing_product1.id,
        ).exists()
        self.assertEqual(checkout_exists, False)

    @patch('juloserver.julo_financing.services.view_related.julo_one_lender_auto_matchmaking')
    @patch('juloserver.julo_financing.services.view_related.calculate_loan_amount')
    @patch('juloserver.julo_financing.services.view_related.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.is_julo_one_product_locked_and_reason')
    @patch('juloserver.loan.services.loan_related.validate_max_fee_rule_by_loan_requested')
    def test_submit_ok_credit_matrix(
        self,
        mock_validate_max_fee,
        mock_julo_one_product_locked,
        mock_get_cm_repeat,
        mock_calculate_loan_amount,
        mock_lender_matchmaking,
    ):
        adjusted_loan_amount = 120_000
        loan_duration = 4

        mock_validate_max_fee.return_value = (False, 0, 0, 0, 0, self.cm_provision_fee, 0)
        mock_lender_matchmaking.return_value = self.lender
        mock_julo_one_product_locked.return_value = False, ""
        mock_get_cm_repeat.return_value = None
        mock_calculate_loan_amount.return_value = (
            adjusted_loan_amount,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )

        checkout_info = {
            "full_name": "A",
            "phone_number": "0812321332132",
            "address": "julo",
            "address_detail": "julo",
        }
        submit_data = {
            "checkout_info": checkout_info,
            "loan_duration": loan_duration,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "JAKARTA BARAT",
        }

        service = JFinancingSubmitViewService(
            customer=self.customer,
            submit_data=submit_data,
        )
        response_data = service.submit()
        checkout_id = response_data['checkout_id']
        response_loan_amount = response_data['loan_amount']
        response_product_name = response_data['product_name']
        response_total_price = response_data['total_price']

        # assert records
        checkout = JFinancingCheckout.objects.get(pk=checkout_id)
        self.assertEqual(checkout.price, self.jfinancing_product1.price)
        self.assertEqual(checkout.price, response_total_price)
        self.assertEqual(checkout.customer_id, self.customer.id)
        self.assertEqual(checkout.j_financing_product_id, self.jfinancing_product1.id)
        self.assertEqual(checkout.additional_info, checkout_info)

        self.assertEqual(checkout.j_financing_product.name, response_product_name)
        self.assertEqual(self.jfinancing_product1.name, response_product_name)

        verification = checkout.verification
        self.assertIsNotNone(verification)
        self.assertEqual(verification.validation_status, JFinancingStatus.INITIAL)

        loan = verification.loan
        expected_tax = int(
            py2round(self.cm_provision_fee * adjusted_loan_amount * self.tax_percent)
        )
        self.assertIsNotNone(loan)
        self.assertEqual(loan.loan_amount, adjusted_loan_amount + expected_tax)
        self.assertEqual(loan.loan_amount, response_loan_amount)
        self.assertEqual(loan.status, LoanStatusCodes.DRAFT)
        self.assertEqual(loan.credit_matrix, self.credit_matrix)
        self.assertEqual(loan.loan_duration, loan_duration)
        self.assertEqual(loan.transaction_method_id, self.transaction_method.id)
        self.assertEqual(loan.lender_id, self.lender.id)
        self.assertEqual(loan.partner, self.lender.user.partner)

        # payments
        payments = loan.payment_set.all()
        self.assertEqual(len(payments), loan_duration)

    @patch('juloserver.julo_financing.services.view_related.julo_one_lender_auto_matchmaking')
    @patch('juloserver.julo_financing.services.view_related.calculate_loan_amount')
    @patch('juloserver.julo_financing.services.view_related.get_credit_matrix_repeat')
    @patch('juloserver.loan.services.loan_related.is_julo_one_product_locked_and_reason')
    @patch('juloserver.loan.services.loan_related.validate_max_fee_rule_by_loan_requested')
    def test_submit_ok_credit_matrix_repeat(
        self,
        mock_validate_max_fee,
        mock_julo_one_product_locked,
        mock_get_cm_repeat,
        mock_calculate_loan_amount,
        mock_lender_matchmaking,
    ):
        adjusted_loan_amount = 120_000
        loan_duration = 4

        mock_validate_max_fee.return_value = (False, 0, 0, 0, 0, self.cm_provision_fee, 0)

        mock_lender_matchmaking.return_value = self.lender
        mock_julo_one_product_locked.return_value = False, ""
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat
        mock_calculate_loan_amount.return_value = (
            adjusted_loan_amount,
            self.credit_matrix,
            self.credit_matrix_product_line,
        )

        checkout_info = {
            "full_name": "A",
            "phone_number": "0812321332132",
            "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
            "address_detail": "julo",
        }
        submit_data = {
            "checkout_info": checkout_info,
            "loan_duration": loan_duration,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }

        service = JFinancingSubmitViewService(
            customer=self.customer,
            submit_data=submit_data,
        )
        response_data = service.submit()
        checkout_id = response_data['checkout_id']
        response_loan_amount = response_data['loan_amount']
        response_product_name = response_data['product_name']
        response_total_price = response_data['total_price']

        # assert records
        checkout = JFinancingCheckout.objects.get(pk=checkout_id)
        self.assertEqual(checkout.price, self.jfinancing_product1.price)
        self.assertEqual(checkout.total_price, response_total_price)
        self.assertEqual(checkout.customer_id, self.customer.id)
        self.assertEqual(checkout.j_financing_product_id, self.jfinancing_product1.id)
        self.assertEqual(checkout.additional_info, checkout_info)
        self.assertEqual(
            checkout.shipping_fee,
            self.feature_setting.parameters['province_shipping_fee']['JAKARTA'],
        )

        self.assertEqual(checkout.j_financing_product.name, response_product_name)
        self.assertEqual(self.jfinancing_product1.name, response_product_name)

        verification = checkout.verification
        self.assertIsNotNone(verification)
        self.assertEqual(verification.validation_status, JFinancingStatus.INITIAL)

        loan = verification.loan
        self.assertIsNotNone(loan)

        adjusted_loan_amount = int(
            py2round(
                py2round(old_div(checkout.total_price, (1 - self.credit_matrix_repeat.provision)))
            )
        )
        expected_tax = int(
            py2round(self.cm_provision_fee * adjusted_loan_amount * self.tax_percent)
        )
        self.assertEqual(loan.loan_amount, adjusted_loan_amount + expected_tax)

        self.assertEqual(loan.status, LoanStatusCodes.DRAFT)
        self.assertEqual(loan.credit_matrix, self.credit_matrix)
        self.assertEqual(loan.loan_amount, response_loan_amount)
        self.assertEqual(loan.loan_duration, loan_duration)
        self.assertEqual(loan.transaction_method_id, self.transaction_method.id)
        self.assertEqual(loan.lender_id, self.lender.id)
        self.assertEqual(loan.partner, self.lender.user.partner)

        # payments
        payments = loan.payment_set.all()
        self.assertEqual(len(payments), loan_duration)

    def test_check_not_enough_limit(self):
        loan_duration = 4
        checkout_info = {
            "full_name": "A",
            "phone_number": "0812321332132",
            "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
            "address_detail": "julo",
        }
        submit_data = {
            "checkout_info": checkout_info,
            "loan_duration": loan_duration,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }

        service = JFinancingSubmitViewService(
            customer=self.customer,
            submit_data=submit_data,
        )

        # set zero available limit
        self.account_limit.available_limit = 0
        self.account_limit.save()

        with self.assertRaises(AccountLimitExceededException):
            service.check_eligibility()

    def test_check_too_many_transaction(self):
        parameters = {
            TransactionMethodCode.JFINANCING.name: {
                '24 hr': 1,
                '1 hr': 1,
                '5 min': 1,
                'is_active': True,
            },
            "errors": {"24 hr": "abc", "other": "dgv"},
        }
        FeatureSetting.objects.create(
            is_active=True,
            feature_name=LoanFeatureNameConst.TRANSACTION_METHOD_LIMIT,
            parameters=parameters,
        )
        tarik_dana_loan = LoanFactory(
            account=self.account,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.INACTIVE),
            transaction_method_id=TransactionMethodCode.SELF.code,
        )
        LoanHistoryFactory(
            loan=tarik_dana_loan,
            status_old=0,
            status_new=210,
        )
        loan_duration = 4
        checkout_info = {
            "full_name": "A",
            "phone_number": "0812321332132",
            "address": "L. Selat Karimata 11, Duren Sawit, Duren Sawit, Kota Jakarta Timur, DKI Jakarta, 13440",
            "address_detail": "julo",
        }
        submit_data = {
            "checkout_info": checkout_info,
            "loan_duration": loan_duration,
            "j_financing_product_id": self.jfinancing_product1.id,
            "province_name": "Jakarta",
        }

        # no error
        service = JFinancingSubmitViewService(
            customer=self.customer,
            submit_data=submit_data,
        )
        service.check_eligibility()

        # with x210 jfinancing loan
        jfinancing_loan = LoanFactory(
            account=self.account,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.INACTIVE),
            transaction_method_id=TransactionMethodCode.JFINANCING.code,
        )
        LoanHistoryFactory(
            loan=jfinancing_loan,
            status_old=209,
            status_new=210,
        )

        with self.assertRaises(LoanTransactionLimitExceeded) as e:
            service.check_eligibility()


class TestJFinancingUploadSignatureService(TestCase):
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

    def setUp(self) -> None:
        self.customer = CustomerFactory()
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

    def test_checkout_not_found(self):
        with self.assertRaises(CheckoutNotFound):
            JFinancingUploadSignatureService(
                checkout_id=-1,
                input_data={'any': '123'},
                user=self.customer.user,
            )

    def test_out_of_stock(self):
        self.productX.quantity = 0
        self.productX.save()

        with self.assertRaises(ProductOutOfStock):
            service = JFinancingUploadSignatureService(
                checkout_id=self.checkout.id,
                input_data={'any': 'any'},
                user=self.customer.user,
            )
            service.upload_signature()

    def test_invalid_verification_status(self):
        self.verification.validation_status = "on_delivery"
        self.verification.save()

        with self.assertRaises(InvalidVerificationStatus):
            service = JFinancingUploadSignatureService(
                checkout_id=self.checkout.id,
                input_data={'any': 'any'},
                user=self.customer.user,
            )
            service.upload_signature()

    @patch('juloserver.julo_financing.services.crm_services.execute_after_transaction_safely')
    @patch('juloserver.julo_financing.services.view_related.execute_after_transaction_safely')
    @patch(
        'juloserver.julo_financing.services.view_related.upload_jfinancing_signature_image_task.delay'
    )
    @patch('juloserver.julo_financing.services.core_services.upload_file_to_oss')
    def test_case_ok(
        self, mock_upload_to_oss, mock_upload_task, mock_execute, mock_execute_crm_service
    ):
        self.image = self._generate_dummy_image(300, 200)
        file_name = 'journey-to-the-west.png'
        input_data = {
            'upload': self.image,
            'data': file_name,
        }
        service = JFinancingUploadSignatureService(
            checkout_id=self.checkout.id,
            input_data=input_data,
            user=self.customer.user,
        )
        service.upload_signature()

        mock_execute.assert_called_once()
        mock_execute_crm_service.assert_called_once()

        # get first positional argument
        lambda_func = mock_execute.call_args[0][0]

        # Ensure it's a callable (lambda)
        self.assertTrue(callable(lambda_func))

        # call it (not actually being called in test)
        lambda_func()
        mock_upload_task.assert_called_once()
        keyword_args = mock_upload_task.call_args[1]

        called_customer_id = keyword_args['customer_id']
        called_image_id = keyword_args['image_id']
        self.assertEqual(called_customer_id, self.customer.id)

        upload_jfinancing_signature_image_task(
            image_id=called_image_id,
            customer_id=called_customer_id,
        )

        # assert image, checkout, verification
        result_image = ImageModel.objects.get_or_none(pk=keyword_args['image_id'])
        self.assertIsNotNone(result_image)

        self.assertEqual(result_image.image_type, 'signature')
        self.assertEqual(result_image.service, 'oss')
        self.assertEqual(
            result_image.url,
            'cust_{}/loan_{}/signature_{}.png'.format(
                self.customer.id, self.loan.id, called_image_id
            ),
        )
        self.assertEqual(
            result_image.thumbnail_url,
            'cust_{}/loan_{}/signature_{}_thumbnail.png'.format(
                self.customer.id, self.loan.id, called_image_id
            ),
        )

        # checkout
        expected_quantity = self.productX.quantity - 1
        self.productX.refresh_from_db()
        self.assertEqual(self.productX.quantity, expected_quantity)
        self.checkout.refresh_from_db()
        self.assertEqual(self.checkout.signature_image_id, result_image.id)

        # verification
        self.verification.refresh_from_db()
        self.assertEqual(self.verification.validation_status, "on_review")


class TestJFinancingTransactionDetailViewService(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
        )
        self.productX = JFinancingProductFactory(
            quantity=1,
        )
        self.courier_name = "Elon Musk"
        self.courier_tracking_id = "XYZ123"
        self.checkout_address = "dragonstone"
        self.checkout_phone_number = "08123456678"
        self.checkout_full_name = "Daenerys of the House Targaryen, the First of Her Name"
        self.checkout = JFinancingCheckoutFactory(
            customer=self.customer,
            j_financing_product=self.productX,
            courier_name=self.courier_name,
            courier_tracking_id=self.courier_tracking_id,
            additional_info={
                "address": self.checkout_address,
                "phone_number": self.checkout_phone_number,
                "full_name": self.checkout_full_name,
            },
        )
        self.loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            customer=self.customer,
        )
        self.verification = JFinancingVerificationFactory(
            loan=self.loan,
            j_financing_checkout=self.checkout,
            validation_status="on_delivery",
        )
        self.courier_icon_link = "tesla.png"
        self.fs = FeatureSettingFactory(
            feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PRODUCT_CONFIGURATION,
            is_active=True,
            parameters={
                "couriers_info": {
                    self.courier_name: {
                        "image_link": self.courier_icon_link,
                        "web_link": "tesla.com",
                    }
                }
            },
        )
        ImageFactory(
            image_source=self.productX.id,
            image_type=JFinancingProductImageType.PRIMARY,
            thumbnail_url="img1",
        )

    def test_case_initial_status(self):
        """
        Checkout with initial status won't appear
        """
        self.verification.validation_status = "initial"
        self.verification.save()

        with self.assertRaises(CheckoutNotFound):
            service = JFinancingTransactionDetailViewService(
                checkout_id=self.checkout.id,
                user=self.user,
            )
            service.get_transaction_detail()

    def test_case_different_user(self):
        user2 = AuthUserFactory()
        with self.assertRaises(UserNotAllowed):
            service = JFinancingTransactionDetailViewService(
                checkout_id=self.checkout.id,
                user=user2,
            )
            service.get_transaction_detail()

    def test_logistics_info(self):
        # active
        # status onreview
        self.verification.validation_status = "on_review"
        self.verification.save()

        service = JFinancingTransactionDetailViewService(
            checkout_id=self.checkout.id,
            user=self.user,
        )
        logistics_info = service.logistics_info
        expected = {}
        self.assertEqual(logistics_info, expected)

        # status on delivery
        self.verification.validation_status = "on_delivery"
        self.verification.save()

        service = JFinancingTransactionDetailViewService(
            checkout_id=self.checkout.id,
            user=self.user,
        )
        logistics_info = service.logistics_info
        expected = {
            "courier": {
                "icon_link": self.courier_icon_link,
                "name": self.courier_name,
            },
            "seri_number": self.courier_tracking_id,
        }
        self.assertEqual(logistics_info, expected)

        # inactive, doesn't affect icon link
        self.fs.is_active = False
        self.fs.save()

        service = JFinancingTransactionDetailViewService(
            checkout_id=self.checkout.id,
            user=self.user,
        )
        logistics_info = service.logistics_info

        expected = {
            "courier": {
                "icon_link": self.courier_icon_link,
                "name": self.courier_name,
            },
            "seri_number": self.courier_tracking_id,
        }
        self.assertEqual(logistics_info, expected)

    @patch('juloserver.julo.models.get_oss_presigned_url')
    def test_case_ok_on_delivery(self, mock_get_oss_presigned_url):
        native_dt = datetime(2024, 6, 12, 11, 15, 0)  # 2024/06/12 11:15
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        aware_dt = jakarta_tz.localize(native_dt)

        self.checkout.cdate = aware_dt
        self.checkout.shipping_fee = 10000
        self.checkout.save()

        sample_thumbnail_url = 'https://example.com/thumbnail.jpg'
        mock_get_oss_presigned_url.return_value = sample_thumbnail_url

        # on delivery case
        service = JFinancingTransactionDetailViewService(
            checkout_id=self.checkout.id,
            user=self.user,
        )

        shipping_fee = self.checkout.shipping_fee
        expected_response = {
            "logistics_info": {
                "courier": {
                    "icon_link": self.courier_icon_link,
                    "name": self.courier_name,
                },
                "seri_number": self.courier_tracking_id,
            },
            "product_detail": {
                "display_price": display_rupiah_no_space(self.checkout.price),
                "name": self.productX.name,
                "display_loan_amount": display_rupiah_no_space(self.loan.loan_amount),
                "thumbnail_url": sample_thumbnail_url,
                "status": self.checkout.verification.get_validation_status_display(),
            },
            "checkout_info": {
                "full_name": self.checkout_full_name,
                "phone_number": self.checkout_phone_number,
                "address": self.checkout_address,
            },
            "transaction_detail": {
                "transaction_date": "12 Jun 2024, 11:15 WIB",
                "display_total_price": display_rupiah_no_space(self.checkout.total_price),
                "display_shipping_fee": display_rupiah_no_space(shipping_fee),
                "display_price": display_rupiah_no_space(self.checkout.price),
            },
            "loan_detail": {
                "display_total_price": display_rupiah_no_space(self.checkout.total_price),
                "display_loan_amount": display_rupiah_no_space(self.loan.loan_amount),
                "duration": "{} bulan".format(self.loan.loan_duration),
                "monthly_installment_amount": display_rupiah_no_space(self.loan.installment_amount),
            },
        }
        response = service.get_transaction_detail()
        self.assertEqual(expected_response, response)

    def test_case_non_delivery_status(self):
        """
        Logistics_info is empty for non on_delivery status
        """
        self.verification.validation_status = "on_review"
        self.verification.save()

        service = JFinancingTransactionDetailViewService(
            checkout_id=self.checkout.id,
            user=self.user,
        )

        response = service.get_transaction_detail()
        self.assertEqual(response['logistics_info'], {})

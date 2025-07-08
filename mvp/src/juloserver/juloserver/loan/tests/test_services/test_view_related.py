from datetime import datetime
import uuid

from django.conf import settings
from mock import MagicMock, Mock, PropertyMock, patch
from rest_framework.test import APITestCase
from django.test.testcases import TestCase
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from juloserver.account.constants import AccountConstant
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.customer_module.tests.factories import (
    BankAccountDestinationFactory,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.tests.factories import DisbursementFactory, NameBankValidationFactory
from juloserver.ecommerce.tests.factories import JuloShopTransactionFactory
from juloserver.education.tests.factories import LoanStudentRegisterFactory, StudentRegisterFactory
from juloserver.healthcare.factories import HealthcarePlatformFactory, HealthcareUserFactory
from juloserver.healthcare.models import HealthcareUser
from juloserver.julo.models import SepulsaProduct
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo_financing.constants import (
    JFINACNING_FE_PRODUCT_CATEGORY,
    JFINANCING_VENDOR_NAME,
)
from juloserver.julo_financing.tests.factories import (
    JFinancingCheckoutFactory,
    JFinancingProductFactory,
    JFinancingVerificationFactory,
)
from juloserver.loan.models import AdditionalLoanInformation
from juloserver.loan.services.feature_settings import (
    AnaTransactionModelSetting,
    AvailableLimitInfoSetting,
    LockedProductPageSetting,
)
from juloserver.loan.services.loan_creation import LoanCreditMatrices
from juloserver.payment_point.constants import SepulsaProductType
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import display_rupiah_no_space
from juloserver.loan.constants import (
    DEFAULT_OTHER_PLATFORM_MONTHLY_INTEREST_RATE,
    DEFAULT_LIST_SAVING_INFORMATION_DURATION,
    CampaignConst,
    LoanFeatureNameConst,
    TransactionResultConst,
)
from juloserver.loan.exceptions import TransactionResultException
from juloserver.loan.services.views_related import (
    AvailableLimitInfoAPIService,
    LoanTenureRecommendationService,
    LockedProductPageService,
    TransactionResultAPIService,
    UserCampaignEligibilityAPIV2Service,
    append_qris_method,
    compute_range_max_amount,
    filter_loan_choice,
    get_loan_details,
    get_voice_bypass_feature,
    get_privy_bypass_feature,
    get_other_platform_monthly_interest_rate,
    calculate_saving_information,
    get_list_object_saving_information_duration,
    check_if_tenor_based_pricing,
    apply_pricing_logic,
    show_select_tenure,
)
from juloserver.loan.services.agreement_related import (
    get_loan_agreement_template_julo_one,
    get_skrtp_template_julo_one,
    get_loan_agreement_type,
    get_master_agreement,
)
from juloserver.loan.tests.factories import (
    LoanTransactionDetailFactory,
    TransactionMethodFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CustomerFactory,
    LoanFactory,
    FeatureSettingFactory,
    ApplicationJ1Factory,
    DocumentFactory,
    MobileFeatureSettingFactory,
    PartnerFactory,
    PaymentMethodFactory,
    ProductLineFactory,
    ProductLookupFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
    StatusLookupFactory,
    CreditMatrixRepeatFactory,
    LoanDelayDisbursementFeeFactory,
    WorkflowFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LoanAgreementTemplateFactory,
)
from juloserver.julo.constants import FeatureNameConst, MobileFeatureNameConst, WorkflowConst
from juloserver.payment_point.constants import SepulsaProductCategory, TransactionMethodCode
from juloserver.payment_point.models import (
    TransactionMethod,
    AYCEWalletTransaction,
)
from juloserver.payment_point.tests.factories import (
    TrainStationFactory,
    TrainTransactionFactory,
    AYCProductFactory,
    XfersProduct,
    XfersEWalletTransactionFactory,
)
from juloserver.qris.constants import QrisLinkageStatus, QrisTransactionStatus
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory, QrisPartnerTransactionFactory


class TestThreshold(APITestCase):
    def setUp(self):
        self.loan = LoanFactory(sphp_sent_ts=timezone.now())
        parameters_digital_signature = {
            'digital_signature_loan_amount_threshold': 500000
        }
        parameters_voice_record = {
            'voice_recording_loan_amount_threshold': 500000
        }
        self.feature_voice = FeatureSettingFactory(
            feature_name=FeatureNameConst.VOICE_RECORDING_THRESHOLD,
            parameters=parameters_voice_record)
        self.feature_signature = FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGITAL_SIGNATURE_THRESHOLD,
            parameters=parameters_digital_signature)

    def test_voice_record_threshold(self):
        self.loan.loan_amount = 490000
        self.loan.save()
        return_value = get_voice_bypass_feature(self.loan)
        self.assertFalse(return_value)

        self.loan.loan_amount = 600000
        self.loan.save()
        return_value = get_voice_bypass_feature(self.loan)
        self.assertTrue(return_value)

    def test_digital_signature_threshold(self):
        self.loan.loan_amount = 490000
        self.loan.save()
        return_value = get_privy_bypass_feature(self.loan)
        self.assertTrue(return_value)

        self.loan.loan_amount = 600000
        self.loan.save()
        return_value = get_privy_bypass_feature(self.loan)
        self.assertFalse(return_value)


class TestLoanAgreementTemplate(TestCase):
    def setUp(self) -> None:
        self.loan = LoanFactory(
            lender=LenderCurrentFactory(),
            sphp_sent_ts=timezone.now(),
        )
        self.application = ApplicationJ1Factory()
        self.account = AccountFactory()
        self.master_agreement = DocumentFactory(
            document_type="master_agreement",
        )

    def test_get_loan_agreement_template_julo_one(self):
        AccountLimitFactory(account=self.account)
        text_agreement, _ = get_loan_agreement_template_julo_one(None)
        self.assertIsNone(text_agreement)

        text_agreement, _ = get_loan_agreement_template_julo_one(self.loan.id)
        self.assertIsNone(text_agreement)

        old_application_id2 = self.loan.application_id2
        self.loan.account = self.account
        self.loan.application_id2 = None
        self.loan.save()
        text_agreement, _ = get_loan_agreement_template_julo_one(self.loan.id)
        self.assertIsNone(text_agreement)

        self.loan.application_id2 = old_application_id2
        self.loan.save()
        self.application.account = self.account
        self.application.save()
        text_agreement, _ = get_loan_agreement_template_julo_one(self.loan.id)
        self.assertIsNotNone(text_agreement)

        self.master_agreement.document_source = self.application.id
        self.master_agreement.save()
        text_agreement, _ = get_loan_agreement_template_julo_one(self.loan.id)
        self.assertIsNotNone(text_agreement)

    def test_get_skrtp_template_julo_one(self):
        self.assertIsNone(get_skrtp_template_julo_one(None, None, None, None))

        self.assertIsNone(
            get_skrtp_template_julo_one(
                self.loan, self.account, self.application, self.master_agreement
            )
        )

        AccountLimitFactory(account=self.account)
        PaymentMethodFactory(virtual_account=self.loan.julo_bank_account_number)
        LoanAgreementTemplateFactory(lender=self.loan.lender, agreement_type='skrtp')
        self.assertIsNotNone(
            get_skrtp_template_julo_one(
                self.loan, self.account, self.application, self.master_agreement
            )
        )

    def test_get_loan_agreement_type(self):
        loan_agreement = get_loan_agreement_type(self.loan.loan_xid)
        self.assertEqual('sphp', loan_agreement['type'])

        self.loan.account = self.account
        self.loan.save()
        self.application.account = self.account
        self.application.save()
        self.master_agreement.document_source = self.application.id
        self.master_agreement.save()
        loan_agreement = get_loan_agreement_type(self.loan.loan_xid)
        self.assertEqual('skrtp', loan_agreement['type'])

    def test_get_master_agreement(self):
        self.assertIsNone(get_master_agreement(self.application.id))


class TestSavingCalculationWithOtherPlatform(TestCase):
    def test_get_other_platform_monthly_interest_rate(self):
        # don't have fs yet, use default rate
        other_platform_monthly_interest_rate = get_other_platform_monthly_interest_rate()
        self.assertEqual(
            other_platform_monthly_interest_rate, DEFAULT_OTHER_PLATFORM_MONTHLY_INTEREST_RATE
        )

        # have fs, but inactive, still use default rate
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SAVING_INFORMATION_CONFIGURATION,
            parameters={
                'other_platform_monthly_interest_rate': 0.56
            },
            is_active=False,
        )
        other_platform_monthly_interest_rate = get_other_platform_monthly_interest_rate()
        self.assertEqual(
            other_platform_monthly_interest_rate, DEFAULT_OTHER_PLATFORM_MONTHLY_INTEREST_RATE
        )

        # have fs, active, use fs rate
        fs.is_active = True
        fs.save()
        other_platform_monthly_interest_rate = get_other_platform_monthly_interest_rate()
        self.assertEqual(
            other_platform_monthly_interest_rate, 0.56
        )

    def test_calculate_saving_information(self):
        monthly_interest_rate = 0.05
        other_platform_monthly_interest_rate = 0.1

        # duration > 1: round_rupiah monthly interest
        saving_information = calculate_saving_information(
            133_000, 1_000_000, 12, monthly_interest_rate, other_platform_monthly_interest_rate
        )
        self.assertEqual(saving_information['monthly_interest_rate'], monthly_interest_rate)
        self.assertEqual(saving_information['total_amount_need_to_paid'], 1_596_000)
        self.assertEqual(saving_information['regular_monthly_installment'], 133_000)
        self.assertEqual(saving_information['other_platform_monthly_interest_rate'],
                         other_platform_monthly_interest_rate)
        self.assertEqual(saving_information['other_platform_total_amount_need_to_paid'],
                         2_196_000)
        self.assertEqual(saving_information['other_platform_regular_monthly_installment'],
                         183_000)
        self.assertEqual(saving_information['saving_amount_per_monthly_installment'], 50_000)
        self.assertEqual(saving_information['saving_amount_per_transaction'], 600_000)

        # duration = 1: don't round_rupiah monthly interest
        saving_information = calculate_saving_information(
            315_129, 300123, 1, monthly_interest_rate, other_platform_monthly_interest_rate
        )
        self.assertEqual(saving_information['monthly_interest_rate'], monthly_interest_rate)
        self.assertEqual(saving_information['total_amount_need_to_paid'], 315_129)
        self.assertEqual(saving_information['regular_monthly_installment'], 315_129)
        self.assertEqual(saving_information['other_platform_monthly_interest_rate'],
                         other_platform_monthly_interest_rate)
        self.assertEqual(saving_information['other_platform_total_amount_need_to_paid'],
                         330_135)
        self.assertEqual(saving_information['other_platform_regular_monthly_installment'],
                         330_135)
        self.assertEqual(saving_information['saving_amount_per_monthly_installment'], 15_006)
        self.assertEqual(saving_information['saving_amount_per_transaction'], 15_006)


class TestSavingInformation(TestCase):
    def test_get_list_object_saving_information_duration(self):
        default_list_object_saving_information_duration = [{'duration': duration} for duration in
                                                           DEFAULT_LIST_SAVING_INFORMATION_DURATION]
        # don't have fs yet, use default list
        list_object_saving_information_duration = get_list_object_saving_information_duration()
        self.assertEqual(
            list_object_saving_information_duration, default_list_object_saving_information_duration
        )

        # have fs, but inactive, still use default list
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SAVING_INFORMATION_CONFIGURATION,
            parameters={
                'list_saving_information_duration': [9, 8, 10]
            },
            is_active=False,
        )
        list_object_saving_information_duration = get_list_object_saving_information_duration()
        self.assertEqual(
            list_object_saving_information_duration, default_list_object_saving_information_duration
        )

        # have fs, active, use fs paramaters value
        fs.is_active = True
        fs.save()
        list_object_saving_information_duration = get_list_object_saving_information_duration()
        self.assertEqual(
            list_object_saving_information_duration,
            [{'duration': 9}, {'duration': 8}, {'duration': 10}]
        )


class TestTransactionResultViewService(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)

        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product_lookup = ProductLookupFactory(product_line=product_line)

        self.loan_amount = 900_000
        self.disbursed_amount = 1_000_000

        self.account = AccountFactory(customer=self.customer)
        self.bank_account_number = '1606'
        self.name_in_bank = "Guy Fawkes"
        self.bank_name = "VForVendetta"
        self.bank = BankFactory(
            bank_name=self.bank_name,
            bank_name_frontend=self.bank_name,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            name_in_bank=self.name_in_bank,
            method='XFERS',
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            customer=self.customer,
            name_bank_validation=self.name_bank_validation,
            account_number=self.bank_account_number,
        )

        self.loan = LoanFactory(
            customer=self.customer,
            product=product_lookup,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            loan_amount=self.loan_amount,
            loan_disbursement_amount=self.disbursed_amount,
            bank_account_destination=self.bank_account_destination,
        )

    @patch.object(TransactionResultAPIService, "delay_disbursement", new_callable=PropertyMock)
    @patch.object(TransactionResultAPIService, "product_detail", new_callable=PropertyMock)
    @patch.object(TransactionResultAPIService, "content", new_callable=PropertyMock)
    @patch.object(TransactionResultAPIService, "fe_messages", new_callable=PropertyMock)
    def test_construct_response_data(
        self, mock_fe_messages, mock_content, mock_product_detail, mock_dd
    ):
        fake_value = 1
        fake_dd = {
            'is_eligible': False,
            'tnc': '',
            'threshold_time': 0,
            'cashback': 0,
            'status': '',
            'agreement_timestamp': '',
        }

        # mock these properties and test them in seperate tests
        mock_fe_messages.return_value = fake_value
        mock_content.return_value = fake_value
        mock_product_detail.return_value = fake_value

        mock_dd.return_value = fake_dd

        # set up loan, case success
        self.loan.transaction_method_id = 1
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)
        data = service.construct_response_data()

        sub_path = 'transaction_status/'
        expected_data = {
            "status_image": settings.STATIC_ALICLOUD_BUCKET_URL + sub_path + 'success.png',
            "product_detail": fake_value,
            "content": fake_value,
            "fe_messages": fake_value,
            "shown_amount": display_rupiah_no_space(self.loan_amount),
            "disbursement_date": timezone.localtime(self.loan.fund_transfer_ts),
            "status": TransactionResultConst.Status.SUCCESS,
            "delay_disbursement": fake_dd,
        }

        self.assertEqual(data, expected_data)

        # case shown amount is disbursement amount

    def test_property_displayed_amount(self):
        # self & other method
        self.loan.transaction_method_id = 1
        self.loan.save()
        self.loan.refresh_from_db()
        service = TransactionResultAPIService(loan=self.loan)

        self.assertEqual(
            service.displayed_loan_amount,
            display_rupiah_no_space(self.loan.loan_amount),
        )

        # other methods
        self.loan.transaction_method_id = 3
        self.loan.save()
        self.loan.refresh_from_db()
        service = TransactionResultAPIService(loan=self.loan)

        self.assertEqual(
            service.displayed_loan_amount,
            display_rupiah_no_space(self.loan.loan_disbursement_amount),
        )

    @patch("juloserver.loan.services.views_related.get_loan_details")
    def test_property_status(self, mock_loan_details):
        loan_mock = Mock()
        # 220
        loan_mock.loan_status_id = LoanStatusCodes.CURRENT
        service = TransactionResultAPIService(loan=loan_mock)

        self.assertEqual(service.status, TransactionResultConst.Status.SUCCESS)

        # 212
        loan_mock.loan_status_id = LoanStatusCodes.FUND_DISBURSAL_ONGOING
        service.loan = loan_mock
        self.assertEqual(service.status, TransactionResultConst.Status.IN_PROGRESS)

        # 215
        loan_mock.loan_status_id = LoanStatusCodes.TRANSACTION_FAILED
        service.loan = loan_mock
        self.assertEqual(service.status, TransactionResultConst.Status.FAILED)

    def test_property_fe_messages(self):
        fs = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.TRANSACTION_RESULT_FE_MESSAGES,
            is_active=False,
            parameters={
                TransactionMethodCode.SELF.code: {
                    "IN_PROGRESS": {"title": "inpro1", "payment_message": "", "info_message": ""},
                    "FAILED": {
                        "title": "failed",
                        "payment_message": "paymentfailed",
                        "info_message": "",
                    },
                    "SUCCESS": {
                        "title": "success",
                        "payment_message": "paymentsuccess",
                        "info_message": "",
                    },
                },
                TransactionMethodCode.LISTRIK_PLN.code: {
                    "IN_PROGRESS": {
                        "title": "inprogress2_title",
                        "payment_message": "",
                        "info_message": "inprogress2_info",
                    },
                    "FAILED": {
                        "title": "Pencairan Dana Gagal",
                        "payment_message": "Dana akan dikembalikan ke limit tersedia. Coba ulangi lagi transaksinya, yuk!",
                        "info_message": "",
                    },
                    "SUCCESS": {
                        "title": "Pencairan Dana Berhasil",
                        "payment_message": "Terima kasih! Bayar tagihan listrik kamu selalu di JULO, biar terbebas dari kegelapan :bulb:",
                        "info_message": "",
                    },
                },
            },
        )
        service = TransactionResultAPIService(loan=self.loan)
        with self.assertRaises(TransactionResultException) as e:
            service.fe_messages
            self.assertEqual(e.message, "Missing transaction result FS for FE messages")

        fs.is_active = True
        fs.save()

        self.loan.transaction_method_id = TransactionMethodCode.SELF.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)
        expected_data = {
            "title": "success",
            "payment_message": "paymentsuccess",
            "info_message": "",
        }
        self.assertEqual(expected_data, service.fe_messages)

        # electricity, postpaid
        self.loan.transaction_method_id = TransactionMethodCode.LISTRIK_PLN.code
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        )
        self.loan.save()
        self.loan.refresh_from_db()
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                type=SepulsaProductType.ELECTRICITY,
                category=SepulsaProductCategory.ELECTRICITY_POSTPAID,
            ),
            loan=self.loan,
            customer=self.loan.customer,
        )
        service = TransactionResultAPIService(loan=self.loan)

        self.assertEqual(
            service.fe_messages,
            {"title": "inprogress2_title", "payment_message": "", "info_message": ""},
        )

        # electricity, prepaid => token message
        sepulsa_transaction.product.category = SepulsaProductCategory.ELECTRICITY_PREPAID
        sepulsa_transaction.product.save()

        service = TransactionResultAPIService(loan=self.loan)

        self.assertEqual(
            service.fe_messages,
            {
                "title": "inprogress2_title",
                "payment_message": "",
                "info_message": "inprogress2_info",
            },
        )

    def test_property_fe_messages_juloshop(self):
        quantity = 2
        price = 1_000_000.2
        product_name = "Aliens (1979) Bluray Disc"

        TransactionMethodFactory.ecommerce()
        JuloShopTransactionFactory(
            customer=self.customer,
            loan=self.loan,
            transaction_total_amount=price * quantity,
            checkout_info={
                "items": [
                    {
                        "image": "http:random_link.com",
                        "price": price,
                        "quantity": quantity,
                        "productID": "618697428",
                        "productName": product_name,
                    }
                ],
                "discount": 0,
                "finalAmount": self.disbursed_amount,
                "shippingFee": 0,
                "insuranceFee": 0,
                "shippingDetail": {
                    "area": "Kelapa Dua",
                    "city": "Kabupaten Tangerang",
                    "province": "Banten",
                    "postalCode": "15810",
                    "fullAddress": "Fiordini 3",
                },
                "recipientDetail": {"name": "Alvin", "phoneNumber": "08110000003"},
                "totalProductAmount": price * quantity,
            },
        )

        self.loan.transaction_method_id = TransactionMethodCode.E_COMMERCE.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)
        messages = service.fe_messages
        self.assertIsNotNone(messages)

        # default is sucesss (loan 220)
        self.assertEqual(messages['title'], "Transaksi JULO Shop Berhasil")

        payment_msg = "Terima kasih! Kalau butuh yang lainnya, belanjanya di JULO Shop aja!"
        self.assertEqual(messages['payment_message'], payment_msg)
        self.assertEqual(messages['info_message'], "")

    def test_property_product_detail(self):
        category_product_name = "say_my_name"
        foreground_icon_url = "heisenberg.org"
        # MOBILE
        self.loan.transaction_method_id = TransactionMethodCode.PULSA_N_PAKET_DATA.code
        method = TransactionMethod.objects.get(pk=TransactionMethodCode.PULSA_N_PAKET_DATA.code)
        method.fe_display_name = category_product_name
        method.foreground_icon_url = foreground_icon_url
        method.save()

        self.loan.save()
        self.loan.refresh_from_db()

        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                type=SepulsaProductType.MOBILE, category=SepulsaProductCategory.PULSA
            ),
            loan=self.loan,
            customer=self.loan.customer,
        )
        service = TransactionResultAPIService(loan=self.loan)

        expected_data = {
            "category_product_name": category_product_name,
            "product_name": "Pulsa",
            "product_image": foreground_icon_url,
            "transaction_type_code": TransactionMethodCode.PULSA_N_PAKET_DATA.code,
            "deeplink": TransactionResultConst.DEEPLINK_MAPPING[
                TransactionMethodCode.PULSA_N_PAKET_DATA.code
            ],
        }
        self.assertEqual(service.product_detail, expected_data)

        # mobile: paket data
        sepulsa_transaction.product.category = SepulsaProductCategory.PAKET_DATA
        sepulsa_transaction.product.save()

        service = TransactionResultAPIService(loan=self.loan)
        expected_data['product_name'] = "Paket Data"
        self.assertEqual(service.product_detail, expected_data)

    def test_property_product_detail_juloshop(self):
        """
        Test case JULOSHOP loan for `product-detail`
        """
        category_product_name = "dexter"
        foreground_icon_url = "dexter.png"

        TransactionMethodFactory.ecommerce()

        self.loan.transaction_method_id = TransactionMethodCode.E_COMMERCE.code
        self.loan.save()

        method = TransactionMethod.objects.get(pk=TransactionMethodCode.E_COMMERCE.code)
        method.fe_display_name = category_product_name
        method.foreground_icon_url = foreground_icon_url
        method.save()

        # case juloshop
        price = 1_000
        quantity = 3
        item_name = 'one piece'
        JuloShopTransactionFactory(
            customer=self.customer,
            loan=self.loan,
            transaction_total_amount=price * quantity,
            checkout_info={
                "items": [
                    {
                        "image": "http:random_link.com",
                        "price": price,
                        "quantity": quantity,
                        "productID": "618697428",
                        "productName": item_name,
                    }
                ],
                "discount": 0,
                "finalAmount": self.disbursed_amount,
                "shippingFee": 0,
                "insuranceFee": 0,
                "shippingDetail": {
                    "area": "Kelapa Dua",
                    "city": "Kabupaten Tangerang",
                    "province": "Banten",
                    "postalCode": "15810",
                    "fullAddress": "Fiordini 3",
                },
                "recipientDetail": {"name": "Alvin", "phoneNumber": "08110000003"},
                "totalProductAmount": price * quantity,
            },
        )

        service = TransactionResultAPIService(loan=self.loan)
        expected_data = {
            "category_product_name": category_product_name,
            "product_name": "JULO Shop",
            "product_image": foreground_icon_url,
            "transaction_type_code": TransactionMethodCode.E_COMMERCE.code,
            "deeplink": TransactionResultConst.DEEPLINK_MAPPING[
                TransactionMethodCode.E_COMMERCE.code
            ],
        }
        self.assertEqual(service.product_detail, expected_data)

    def test_property_content_self_other_method(self):
        self.loan.transaction_method_id = TransactionMethodCode.SELF.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        logo = self.bank.bank_logo if self.bank.bank_logo else ""
        expected_content = [
            {
                "title": "Bank tujuan",
                "value": self.bank_name,
                "type": "image_text",
                "image": logo,
            },
            {
                "title": "Pemilik rekening",
                "value": self.name_in_bank,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nomor rekening",
                "value": self.bank_account_number,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Dana cair",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

        # other
        self.loan.transaction_method_id = TransactionMethodCode.OTHER.code
        self.loan.save()
        self.loan.refresh_from_db()
        service = TransactionResultAPIService(loan=self.loan)

        self.assertEqual(service.content, expected_content)

    @patch.object(SepulsaProduct, "ewallet_logo", new_callable=PropertyMock)
    def test_property_content_ewallet_method(self, mock_logo):
        kabam = "kabam!"
        mock_logo.return_value = kabam
        product_name = "ABC"
        phone_number = "123"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.EWALLET,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            phone_number=phone_number,
        )

        self.loan.transaction_method_id = TransactionMethodCode.DOMPET_DIGITAL.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": product_name,
                "type": "image_text",
                "image": kabam,
            },
            {"title": "Nomor HP", "value": phone_number, "type": "text_normal", "image": ""},
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    @patch('juloserver.payment_point.services.ewallet_related.get_ewallet_logo')
    def test_property_content_ayoconnect_ewallet_method(self, mock_logo):
        kabam = "kabam!"
        mock_logo.return_value = kabam
        product_name = "ABC"
        phone_number = "08123321123"
        sepulsa_product = SepulsaProductFactory(
            product_name=product_name,
            type=SepulsaProductType.EWALLET,
        )
        ayc_product = AYCProductFactory(
            sepulsa_product=sepulsa_product,
            category=SepulsaProductType.EWALLET,
            type=SepulsaProductType.EWALLET,
            product_name=product_name,
            partner_price=10_000,
            customer_price=10_000,
            customer_price_regular=10_000,
        )
        AYCEWalletTransaction.objects.create(
            loan_id=self.loan.pk,
            ayc_product_id=ayc_product.pk,
            customer_id=self.loan.customer_id,
            phone_number=phone_number,
        )

        self.loan.transaction_method_id = TransactionMethodCode.DOMPET_DIGITAL.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": product_name,
                "type": "image_text",
                "image": kabam,
            },
            {"title": "Nomor HP", "value": phone_number, "type": "text_normal", "image": ""},
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    @patch('juloserver.payment_point.services.ewallet_related.get_ewallet_logo')
    def test_property_content_xfers_ewallet_method(self, mock_logo):
        kabam = "kabam!"
        mock_logo.return_value = kabam
        product_name = "ABC"
        phone_number = "08123321123"
        sepulsa_product = SepulsaProductFactory(
            product_name=product_name,
            type=SepulsaProductType.EWALLET,
        )
        xfers_product = XfersProduct.objects.create(
            sepulsa_product=sepulsa_product,
            category=SepulsaProductType.EWALLET,
            type=SepulsaProductType.EWALLET,
            product_name=product_name,
            partner_price=10_000,
            customer_price=10_000,
            customer_price_regular=10_000,
        )
        XfersEWalletTransactionFactory(
            loan_id=self.loan.pk,
            xfers_product_id=xfers_product.pk,
            customer_id=self.loan.customer_id,
            phone_number=phone_number,
        )

        self.loan.transaction_method_id = TransactionMethodCode.DOMPET_DIGITAL.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": product_name,
                "type": "image_text",
                "image": kabam,
            },
            {"title": "Nomor HP", "value": phone_number, "type": "text_normal", "image": ""},
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_eletricity_method_postpaid(self):
        kabam = "kabam!"
        product_name = "ABC"
        account_name = "ZXY"
        phone_number = "123"
        customer_number = "ABC123"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.ELECTRICITY,
                category=SepulsaProductCategory.ELECTRICITY_POSTPAID,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            phone_number=phone_number,
            customer_number=customer_number,
            account_name=account_name,
        )

        self.loan.transaction_method_id = TransactionMethodCode.LISTRIK_PLN.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": "Tagihan Listrik PLN",
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.meter / ID pelanggan",
                "value": customer_number,
                "type": "text_normal",
                "image": "",
            },
            {"title": "Nama", "value": account_name, "type": "text_normal", "image": ""},
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_eletricity_method_prepaid(self):
        kabam = "kabam!"
        product_name = "ABC"
        account_name = "ZXY"
        phone_number = "123"
        customer_number = "ABC123"
        token = "ihatecoding"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.ELECTRICITY,
                category=SepulsaProductCategory.ELECTRICITY_PREPAID,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            phone_number=phone_number,
            customer_number=customer_number,
            account_name=account_name,
            transaction_token=token,
        )

        self.loan.transaction_method_id = TransactionMethodCode.LISTRIK_PLN.code
        self.loan.loan_status_id = 220
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": "Token Listrik PLN",
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.meter / ID pelanggan",
                "value": customer_number,
                "type": "text_normal",
                "image": "",
            },
            {"title": "Nama", "value": account_name, "type": "text_normal", "image": ""},
            {
                "title": "Nominal token",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {"title": "Token", "value": token, "type": "text_copy", "image": ""},
        ]
        self.assertEqual(service.content, expected_content)

        # case in progress
        self.loan.loan_status_id = 212
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": "Token Listrik PLN",
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.meter / ID pelanggan",
                "value": customer_number,
                "type": "text_normal",
                "image": "",
            },
            {"title": "Nama", "value": account_name, "type": "text_normal", "image": ""},
            {
                "title": "Nominal token",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {"title": "Token", "value": "-", "type": "text_normal", "image": ""},
        ]
        self.assertEqual(service.content, expected_content)

    def test_property_content_mobile_method(self):
        product_name = "ABC"
        phone_number = "123"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.MOBILE,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            phone_number=phone_number,
        )

        self.loan.transaction_method_id = TransactionMethodCode.PULSA_N_PAKET_DATA.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": product_name,
                "type": "image_text",
                "image": "",
            },
            {"title": "Nomor HP", "value": phone_number, "type": "text_normal", "image": ""},
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_pasca_bayar(self):
        product_name = "ABC"
        phone_number = "123"
        account_name = "XYA"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.MOBILE,
                category=SepulsaProductCategory.POSTPAID[0],
            ),
            loan=self.loan,
            customer=self.loan.customer,
            phone_number=phone_number,
            account_name=account_name,
        )

        self.loan.transaction_method_id = TransactionMethodCode.PASCA_BAYAR.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": product_name,
                "type": "image_text",
                "image": "",
            },
            {"title": "Nomor HP", "value": phone_number, "type": "text_normal", "image": ""},
            {"title": "Nama", "value": account_name, "type": "text_normal", "image": ""},
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_pdam_method(self):
        # create method
        TransactionMethodFactory.water()

        product_name = "ABC"
        phone_number = "123"
        account_name = "XYA"
        customer_number = "911"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.PDAM,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            customer_number=customer_number,
            phone_number=phone_number,
            account_name=account_name,
        )

        self.loan.transaction_method_id = TransactionMethodCode.PDAM.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Nomor pelanggan",
                "value": customer_number,
                "type": "text_normal",
                "image": "",
            },
            {"title": "Nama", "value": account_name, "type": "text_normal", "image": ""},
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_bpjs_method(self):
        product_name = "ABC"
        phone_number = "123"
        account_name = "XYA"
        customer_number = "911"
        # create sepulsa
        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.BPJS,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            customer_number=customer_number,
            phone_number=phone_number,
            account_name=account_name,
        )

        self.loan.transaction_method_id = TransactionMethodCode.BPJS_KESEHATAN.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {"title": "Nama peserta", "value": account_name, "type": "text_normal", "image": ""},
            {
                "title": "No. kartu peserta",
                "value": customer_number,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    @patch("juloserver.loan.services.views_related.is_ecommerce_bank_account")
    def test_property_content_ecommerce_method(self, mock_is_ecommerce_bank):
        TransactionMethodFactory.ecommerce()
        mock_is_ecommerce_bank.return_value = True

        product_kind = "shopee"
        self.bank_account_destination.description = product_kind
        self.bank_account_destination.save()
        self.loan.transaction_method_id = TransactionMethodCode.E_COMMERCE.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Jenis",
                "value": product_kind,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nomor HP",
                "value": self.bank_account_destination.account_number,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    @patch("juloserver.loan.services.views_related.is_ecommerce_bank_account")
    def test_property_content_ecommerce_juloshop(self, mock_is_ecommerce_bank):
        mock_is_ecommerce_bank.return_value = False

        # set up data
        quantity = 2
        price = 1_000_000.2
        product_name = "Aliens (1979) Bluray Disc"

        TransactionMethodFactory.ecommerce()
        JuloShopTransactionFactory(
            customer=self.customer,
            loan=self.loan,
            transaction_total_amount=price * quantity,
            checkout_info={
                "items": [
                    {
                        "image": "http:random_link.com",
                        "price": price,
                        "quantity": quantity,
                        "productID": "618697428",
                        "productName": product_name,
                    }
                ],
                "discount": 0,
                "finalAmount": self.disbursed_amount,
                "shippingFee": 0,
                "insuranceFee": 0,
                "shippingDetail": {
                    "area": "Kelapa Dua",
                    "city": "Kabupaten Tangerang",
                    "province": "Banten",
                    "postalCode": "15810",
                    "fullAddress": "Fiordini 3",
                },
                "recipientDetail": {"name": "Alvin", "phoneNumber": "08110000003"},
                "totalProductAmount": price * quantity,
            },
        )

        self.loan.transaction_method_id = TransactionMethodCode.E_COMMERCE.code
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Nama produk",
                "value": product_name,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah produk",
                "value": str(quantity),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Harga produk",
                "value": display_rupiah_no_space(int(price)),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.loan.loan_disbursement_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]
        self.assertEqual(service.content, expected_content)

    def test_property_content_train_ticket_method(self):
        TransactionMethodFactory.train_ticket()

        product_name = "ABC"
        phone_number = "123"
        account_name = "XYA"
        customer_number = "911"
        depart_station_name = "ME"
        depart_code = "A"
        destination_station_name = "YOU"
        destination_code = "B"

        self.loan.transaction_method_id = TransactionMethodCode.TRAIN_TICKET.code
        self.loan.save()
        self.loan.refresh_from_db()

        sepulsa_transaction = SepulsaTransactionFactory(
            product=SepulsaProductFactory(
                product_name=product_name,
                type=SepulsaProductType.TRAIN_TICKET,
            ),
            loan=self.loan,
            customer=self.loan.customer,
            customer_number=customer_number,
            phone_number=phone_number,
            account_name=account_name,
        )
        TrainStationFactory(
            id=1,
            code=depart_code,
            name=depart_station_name,
        )
        TrainStationFactory(
            id=2,
            code=destination_code,
            name=destination_station_name,
        )
        TrainTransactionFactory(
            sepulsa_transaction=sepulsa_transaction,
            depart_station_id=1,
            destination_station_id=2,
        )

        self.loan.transaction_method_id = TransactionMethodCode.TRAIN_TICKET.code

        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Nama pemesan",
                "value": account_name,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Rute",
                "value": "{} ({}) - {} ({})".format(
                    depart_station_name,
                    depart_code,
                    destination_station_name,
                    destination_code,
                ),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nominal",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_healthcare_method(self):
        TransactionMethodFactory.healthcare()

        num = "1234567890"
        fullname = "samval"
        disbursement = DisbursementFactory(
            reference_id=num,
        )
        self.loan.transaction_method_id = TransactionMethodCode.HEALTHCARE.code
        self.loan.loan_status_id = 220
        self.loan.disbursement_id = disbursement.id
        self.loan.save()
        self.loan.refresh_from_db()

        healthcare_platform = HealthcarePlatformFactory()
        healthcare_user = HealthcareUserFactory(
            account=self.account,
            healthcare_platform=healthcare_platform,
            fullname=fullname,
        )

        AdditionalLoanInformation.objects.create(
            content_type=ContentType.objects.get_for_model(HealthcareUser),
            object_id=healthcare_user.pk,
            loan=self.loan,
        )
        service = TransactionResultAPIService(loan=self.loan)

        logo = self.bank.bank_logo if self.bank.bank_logo else ""
        expected_content = [
            {
                "title": "Rumah sakit",
                "value": healthcare_platform.name,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.rek./VA",
                "value": self.bank_account_number,
                "type": "image_text",
                "image": logo,
            },
            {"title": "Nama", "value": fullname, "type": "text_normal", "image": ""},
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {"title": "No. referensi bank", "value": num, "type": "text_copy", "image": ""},
        ]

        self.assertEqual(service.content, expected_content)

        # case in progress
        self.loan.loan_status_id = 212
        self.loan.save()
        self.loan.refresh_from_db()
        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Rumah sakit",
                "value": healthcare_platform.name,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.rek./VA",
                "value": self.bank_account_number,
                "type": "image_text",
                "image": logo,
            },
            {"title": "Nama", "value": fullname, "type": "text_normal", "image": ""},
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {"title": "No. referensi bank", "value": "-", "type": "text_normal", "image": ""},
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_content_education_method(self):
        TransactionMethodFactory.education()

        num = "1234567890"
        disbursement = DisbursementFactory(
            reference_id=num,
        )
        self.loan.transaction_method_id = TransactionMethodCode.EDUCATION.code
        self.loan.loan_status_id = 220
        self.loan.disbursement_id = disbursement.id
        self.loan.save()
        self.loan.refresh_from_db()

        student_register = StudentRegisterFactory(
            bank_account_destination=BankAccountDestinationFactory(
                account_number=num,
            )
        )
        LoanStudentRegisterFactory(
            loan=self.loan,
            student_register=student_register,
        )
        # not creating document won't trigger error
        service = TransactionResultAPIService(loan=self.loan)

        logo = self.bank.bank_logo if self.bank.bank_logo else ""
        expected_content = [
            {
                "title": "Sekolah",
                "value": student_register.school.name,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.rek./VA",
                "value": num,
                "type": "image_text",
                "image": logo,
            },
            {
                "title": "Nama",
                "value": student_register.student_fullname,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {"title": "No. referensi bank", "value": num, "type": "text_copy", "image": ""},
        ]

        self.assertEqual(service.content, expected_content)

        # case in progress
        self.loan.loan_status_id = 212
        self.loan.save()
        self.loan.refresh_from_db()
        service = TransactionResultAPIService(loan=self.loan)

        expected_content = [
            {
                "title": "Sekolah",
                "value": student_register.school.name,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "No.rek./VA",
                "value": student_register.bank_account_destination.account_number,
                "type": "image_text",
                "image": logo,
            },
            {
                "title": "Nama",
                "value": student_register.student_fullname,
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Nominal tagihan",
                "value": display_rupiah_no_space(self.disbursed_amount),
                "type": "text_normal",
                "image": "",
            },
            {
                "title": "Jumlah pinjaman",
                "value": display_rupiah_no_space(self.loan_amount),
                "type": "text_normal",
                "image": "",
            },
            {"title": "No. referensi bank", "value": "-", "type": "text_normal", "image": ""},
        ]

        self.assertEqual(service.content, expected_content)

    def test_property_shown_date(self):
        self.loan.loan_status_id = 220
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)
        self.assertEqual(service.shown_date, timezone.localtime(self.loan.fund_transfer_ts))

        # in progress
        self.loan.loan_status_id = 212
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)
        self.assertEqual(service.shown_date, timezone.localtime(self.loan.cdate))

        # failed
        self.loan.loan_status_id = 215
        self.loan.save()
        self.loan.refresh_from_db()

        service = TransactionResultAPIService(loan=self.loan)
        self.assertEqual(service.shown_date, timezone.localtime(self.loan.cdate))

    def test_property_delay_disbursement(self):

        sphp_dt = '2024-10-09 10:00:00'
        agreement_timestamp = timezone.localtime(datetime.strptime(sphp_dt, '%Y-%m-%d %H:%M:%S'))

        FeatureSettingFactory(
            feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            parameters={
                "content": {"tnc": "here's tnc"},
                "condition": {
                    "cut_off": "23:59",
                    "cashback": 25000,
                    "start_time": "01:00",
                    "daily_limit": 1,
                    "monthly_limit": 4,
                    "min_loan_amount": 1000,
                    "threshold_duration": 600,
                    "list_transaction_method_code": [1],
                },
                "whitelist_last_digit": 3,
            },
        )

        service = TransactionResultAPIService(loan=self.loan)
        expected_not_get_delay_disbursement = {
            "is_eligible": False,
            "tnc": "",
            "cashback": 0,
            "status": "",
            "threshold_time": 0,
            "agreement_timestamp": "",
        }
        self.assertEqual(service.delay_disbursement, expected_not_get_delay_disbursement)

        dd = LoanDelayDisbursementFeeFactory(
            loan=self.loan,
            threshold_time=600,
            cashback=25000,
            agreement_timestamp=agreement_timestamp,
            status="ACTIVE",
        )
        service = TransactionResultAPIService(loan=self.loan)
        expected_delay_disbursement = {
            "is_eligible": True,
            "tnc": "here's tnc",
            "threshold_time": dd.threshold_time,
            "cashback": dd.cashback,
            "status": dd.status,
            "agreement_timestamp": dd.agreement_timestamp,
        }
        self.assertEqual(service.delay_disbursement, expected_delay_disbursement)


class TestGetLoanDetails(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)

        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product_lookup = ProductLookupFactory(product_line=product_line)

        self.loan_amount = 900_000
        self.disbursed_amount = 1_000_000

        self.account = AccountFactory(customer=self.customer)
        self.bank_account_number = '1606'
        self.name_in_bank = "Guy Fawkes"
        self.bank_name = "VForVendetta"
        self.bank = BankFactory(
            bank_name=self.bank_name,
            bank_name_frontend=self.bank_name,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            name_in_bank=self.name_in_bank,
            method='XFERS',
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            customer=self.customer,
            name_bank_validation=self.name_bank_validation,
            account_number=self.bank_account_number,
        )

        self.loan = LoanFactory(
            customer=self.customer,
            product=product_lookup,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=self.loan_amount,
            loan_disbursement_amount=self.disbursed_amount,
            bank_account_destination=self.bank_account_destination,
        )

        self.product_quantity = 10
        self.product = JFinancingProductFactory(quantity=self.product_quantity)
        self.checkout = JFinancingCheckoutFactory(
            customer=self.customer, additional_info={}, j_financing_product=self.product
        )
        self.verification = JFinancingVerificationFactory(
            j_financing_checkout=self.checkout, loan=self.loan
        )
        self.jfinancing_method = TransactionMethodFactory.jfinancing()
        self.qris_1_method = TransactionMethodFactory.qris_1()

    def test_ok_jfinancing(self):
        price = 999_999
        self.loan.transaction_method_id = self.jfinancing_method.id
        self.checkout.price = price

        self.checkout.save()
        self.loan.save()

        data = get_loan_details(loan=self.loan)

        self.assertEqual(data['qris']['product_category'], JFINACNING_FE_PRODUCT_CATEGORY)
        self.assertEqual(data['qris']['merchant_name'], JFINANCING_VENDOR_NAME)
        self.assertEqual(data['qris']['price'], price)

    def test_ok_qris_1_product(self):
        merchant_name = "allison reynolds"
        partner_user = AuthUserFactory()
        partner = PartnerFactory(
            user=partner_user,
            name=PartnerNameConstant.AMAR,
        )

        linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.customer.id,
            partner_id=partner.id,
            partner_callback_payload={"any": "any"},
        )
        transaction = QrisPartnerTransactionFactory(
            loan_id=self.loan.id,
            status=QrisTransactionStatus.SUCCESS,
            qris_partner_linkage=linkage,
            merchant_name=merchant_name,
            from_partner_transaction_xid=uuid.uuid4().hex,
            partner_transaction_request={"any": "any"},
            partner_callback_payload={"any": "any"},
        )

        self.loan.transaction_method_id = self.qris_1_method.id

        self.loan.save()

        detail = {
            "admin_fee": 2500,
            "provision_fee_rate": 0.02,
            "dd_premium": 15000,
            "insurance_premium": 20000,
            "digisign_fee": 5000,
            "total_registration_fee": 40000,
            "tax_fee": 3000,
            "monthly_interest_rate": 1.5,
            "tax_on_fields": 5,
        }

        LoanTransactionDetailFactory(
            loan_id=self.loan.id,
            detail=detail
        )

        data = get_loan_details(loan=self.loan)
        transaction_detail = transaction.partner_transaction_request.get('transactionDetail', {})
        callback_payload = transaction.partner_callback_payload.get('data', {})
        self.assertEqual(data['qris']['product_category'], "QRIS")
        self.assertEqual(data['qris']['merchant_name'], transaction.merchant_name)
        self.assertEqual(data['qris']['price'], transaction.total_amount)
        self.assertEqual(data['qris']['type'], "Pembayaran QRIS")
        self.assertEqual(data['qris']['product_name'], transaction_detail.get('productName', '-'))
        self.assertEqual(data['qris']['merchant_city'], transaction_detail.get('merchantCity', '-'))
        self.assertEqual(data['qris']['customer_pan'], callback_payload.get('customerPan', '-'))
        self.assertEqual(data['qris']['merchant_pan'], callback_payload.get('merchantPan', '-'))
        self.assertEqual(data['qris']['admin_fee'], detail.get('admin_fee', 0))
        self.assertEqual(data['qris']['tax_fee'], detail.get('tax_fee', 0))
        self.assertEqual(data['qris']['monthly_interest_rate'], detail.get('monthly_interest_rate', 0))


class TestLoanTenureRecommendationService(TestCase):
    def setUp(self):
        self.min_tenure = 4
        self.max_tenure = 10
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.LOAN_TENURE_RECOMMENDATION,
            is_active=False,
            parameters={
                'experiment_config': {
                    'is_active': False,
                    'experiment_customer_id_last_digits': [],
                },
                'general_config': {
                    'min_tenure': self.min_tenure,
                    'max_tenure': self.max_tenure,
                    'campaign_tag': "Paling Murah!",
                    'transaction_methods': [
                        TransactionMethodCode.SELF.code,
                    ],
                },
            },
        )
        self.user = AuthUserFactory()
        # self.client.force_login(self.user)
        # self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.method = TransactionMethodCode.SELF.code

    def test_fs_unactive(self):
        self.fs.is_active = False
        self.fs.save()

        service = LoanTenureRecommendationService(
            available_tenures=[1, 2, 3],
            customer_id=self.customer.id,
            transaction_method_id=self.method,
        )

        self.assertIsNone(
            service.get_recommended_tenure(),
        )

    def test_fs_active_with_experiment_active(self):
        self.fs.is_active = True
        self.fs.parameters['experiment_config']['is_active'] = True
        self.fs.parameters['experiment_config']['experiment_customer_id_last_digits'] = []
        self.fs.save()

        customer_id = 12345
        tenures = [4, 5, 6]
        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )

        self.assertIsNone(service.get_recommended_tenure())

        # update last digits on FS
        self.fs.parameters['experiment_config']['experiment_customer_id_last_digits'] = [1, 5]
        self.fs.save()

        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )

        self.assertEqual(
            service.get_recommended_tenure(),
            6,
        )

        tenures = [8, 9, 10, 11]

        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )

        self.assertEqual(
            service.get_recommended_tenure(),
            self.max_tenure,
        )

        # last digits exists but not valid
        self.fs.parameters['experiment_config']['experiment_customer_id_last_digits'] = [
            1,
            -9,
            13,
            "abc",
        ]
        self.fs.save()

        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )

        self.assertIsNone(
            service.get_recommended_tenure(),
        )

    def test_fs_active_with_experiment_inactive(self):
        customer_id = 12345

        # case empty transaction methods
        self.fs.is_active = True
        self.fs.parameters['experiment_config']['is_active'] = False
        self.fs.parameters['experiment_config']['experiment_customer_id_last_digits'] = [1]
        self.fs.parameters['general_config']['transaction_methods'] = []
        self.fs.save()

        tenures = [8, 9, 10, 11]
        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )
        self.assertIsNone(service.get_recommended_tenure())

        # case max tenure > max tenure in FS
        self.fs.parameters['general_config']['transaction_methods'] = [self.method]
        self.fs.save()

        tenures = [8, 9, 10, 11]
        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )
        self.assertEqual(
            service.get_recommended_tenure(),
            self.max_tenure,
        )

        # case min tenure in FS <= max tenure <= max tenure in FS
        tenures = [7, 8, 9]
        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )

        self.assertEqual(
            service.get_recommended_tenure(),
            9,
        )

        # case min tenure in FS <= max tenure <= max tenure in FS
        tenures = [1, 2, 3]
        service = LoanTenureRecommendationService(
            available_tenures=tenures,
            customer_id=customer_id,
            transaction_method_id=self.method,
        )

        self.assertIsNone(service.get_recommended_tenure())


class TestTenureBasedPricingCalculation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.ecommerce_method = TransactionMethodFactory(
            method=TransactionMethodCode.E_COMMERCE,
            id=8,
        )
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a',
            product_line_id=1,
            transaction_method=self.ecommerce_method,
            version=1,
            interest=0.07
        )
        self.credit_matrix_repeat_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CREDIT_MATRIX_REPEAT_SETTING,
            description="Enable Credit Matrix Repeat",
        )
        parameters = {
            'thresholds': {
                'data': {
                    6: 0.01,
                    9: 0.02,
                    12: 0.05,
                },
                'is_active': True,
            },
            'minimum_pricing': {
                'data': 0.04,
                'is_active': True,
            },
            'cmr_segment': {
                'data': ['activeus_a'],
                'is_active': True,
            },
            'transaction_methods': {
                'data': [1, 2, 8],
                'is_active': True,
            }
        }
        self.new_tenor_feature_settings = FeatureSettingFactory(
            is_active=True,
            feature_name=LoanFeatureNameConst.NEW_TENOR_BASED_PRICING,
            parameters=parameters
        )
        self.threshold_fs = self.new_tenor_feature_settings.parameters['thresholds']

    def test_check_if_tenor_based_pricing(self):
        monthly_interest_rate, tenor_based_pricing, min_pricing, _, _ = check_if_tenor_based_pricing(
            self.customer,
            self.new_tenor_feature_settings,
            7,
            self.credit_matrix_repeat,
            8,
            check_duration=True
        )
        self.assertAlmostEqual(monthly_interest_rate, 0.06, places=7)
        self.assertAlmostEqual(tenor_based_pricing.new_pricing, 0.06, places=7)
        self.assertAlmostEqual(min_pricing, 0.04, places=7)

    def test_apply_pricing_logic(self):
        min_pricing_fs = self.new_tenor_feature_settings.parameters['minimum_pricing']
        min_pricing = min_pricing_fs['data']
        new_pct, drop_pct = apply_pricing_logic(
            7,
            self.threshold_fs,
            self.credit_matrix_repeat,
            min_pricing
        )
        self.assertAlmostEqual(new_pct, 0.06, places=7)
        self.assertAlmostEqual(drop_pct, 0.01, places=7)




class TestAppendingQrisMethod(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.qris_1_method = TransactionMethodFactory.qris_1()

        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.APPENDING_QRIS_TRANSACTION_METHOD_HOME_PAGE,
            is_active=True,
        )

    @patch("juloserver.loan.services.views_related.is_qris_1_blocked")
    def test_append_qris_method(self, mock_is_qris_1_blocked):
        mock_is_qris_1_blocked.return_value = False

        length_items = 3
        transaction_methods = TransactionMethod.objects.all().order_by('order_number')[
            :length_items
        ]

        result_transaction_methods = append_qris_method(self.account, list(transaction_methods))

        self.assertEqual(
            result_transaction_methods[-1],
            self.qris_1_method,
        )

        # test already exists in list
        self.qris_1_method.order_number = 1
        self.qris_1_method.save()

        transaction_methods = TransactionMethod.objects.all().order_by('order_number')[
            :length_items
        ]

        result_transaction_methods = append_qris_method(self.account, list(transaction_methods))

        self.assertIn(
            self.qris_1_method,
            result_transaction_methods,
        )

        self.assertEqual(
            result_transaction_methods[0],
            self.qris_1_method,
        )

        self.assertNotEqual(
            result_transaction_methods[-1],
            self.qris_1_method,
        )


class TestShowSelectTenure(TestCase):
    def setUp(self):
        self.loan_choice = {
            2: {'mock2': 'b'},
            3: {'mock3': 'c'},
            4: {'mock4': 'd'},
            5: {'mock5': 'e'},
            6: {'mock6': 'f'},
            7: {'mock7': 'g'},
            8: {'mock8': 'h'},
            9: {'mock9': 'i'},
            10: {'mock10': 'j'},
        }

    def test_show_select_tenure_with_null_tenures(self):
        show_tenure = []
        loan_choice_result = show_select_tenure(show_tenure, self.loan_choice, customer_id=1)
        self.assertEqual(
            loan_choice_result,
            self.loan_choice
        )

    def test_show_select_tenure_with_show_tenure_as_subset(self):
        show_tenure = [3, 4, 8, 9]
        loan_choice_result = show_select_tenure(show_tenure, self.loan_choice, customer_id=1)
        self.assertEqual(
            loan_choice_result,
            {
                3: {'mock3': 'c'},
                4: {'mock4': 'd'},
                8: {'mock8': 'h'},
                9: {'mock9': 'i'},
            }
        )

    def test_show_select_tenure_with_show_tenure_as_superset(self):
        show_tenure = [1, 2, 3, 4, 8, 9, 10, 11]
        loan_choice_result = show_select_tenure(show_tenure, self.loan_choice, customer_id=1)
        self.assertEqual(
            loan_choice_result,
            {
                2: {'mock2': 'b'},
                3: {'mock3': 'c'},
                4: {'mock4': 'd'},
                8: {'mock8': 'h'},
                9: {'mock9': 'i'},
                10: {'mock10': 'j'},
            }
        )

    def test_show_select_tenure_with_loan_choices_null(self):
        show_tenure = [1, 2, 3, 4, 5]
        loan_choice_result = show_select_tenure(show_tenure, {}, customer_id=1)
        self.assertEqual(
            loan_choice_result,
            {}
        )


class TestAvailableLimitInfoAPIService(TestCase):
    def setUp(self):
        params = {
            "displayed_sections": [
                AvailableLimitInfoSetting.SECTION_AVAILABLE_CASHLOAN_LIMIT,
                AvailableLimitInfoSetting.SECTION_NORMAL_AVAILABLE_LIMIT,
            ],
            "sections": {
                AvailableLimitInfoSetting.SECTION_AVAILABLE_CASHLOAN_LIMIT: {
                    "title": "Jumlah Pinjaman Tarik Dana",
                    "icon": AvailableLimitInfoSetting.MONEY_BAG_ICON,
                    "items": [
                        {
                            "icon": AvailableLimitInfoSetting.EXCLAMATION_ICON,
                            "text": (
                                "Ini adalah jumlah maksimum untuk tarik dana "
                                "karena riwayat pembayaranmu di JULO dan/atau aplikasi lain kurang baik"
                            ),
                        },
                        {
                            "icon": AvailableLimitInfoSetting.SPARKLES_ICON,
                            "text": (
                                "Untuk dapat gunakan limitmu sepenuhnya di tarik dana, "
                                "pastikan kamu selalu bayar tagihan di JULO "
                                "dan/atau aplikasi lain tepat waktu, ya!"
                            ),
                        },
                    ],
                },
                AvailableLimitInfoSetting.SECTION_NORMAL_AVAILABLE_LIMIT: {
                    "title": "Jumlah Pinjaman Total Di JULO",
                    "icon": AvailableLimitInfoSetting.WEB_PERKS_ICON,
                    "items": [
                        {
                            "icon": "",
                            "text": (
                                "Tapi, jika untuk beli pulsa dan token, "
                                "bayar tagihan listrik, air, dan produk non tunai lainnya, "
                                "kamu bisa transaksi sepenuhnya!"
                            ),
                        },
                    ],
                },
            },
        }

        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AVAILABLE_LIMIT_INFO,
            is_active=True,
            parameters=params,
        )
        self.mercury_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.ANA_TRANSACTION_MODEL,
            is_active=True,
            parameters={
                "cooldown_time_in_seconds": AnaTransactionModelSetting.DEFAULT_COOLDOWN_TIME,
                "request_to_ana_timeout_in_seconds": AnaTransactionModelSetting.DEFAULT_REQUEST_TIMEOUT,
                "whitelist_settings": {
                    "is_whitelist_active": False,
                    "whitelist_by_customer_id": [],
                    "whitelist_by_last_digit": [],
                },
            },
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.method = TransactionMethodCode.SELF.code
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=20_000_000,
            available_limit=5_000_000,
        )

        self.credit_matrix = CreditMatrixFactory(
            product=ProductLookupFactory(
                product_line=self.product_line,
            )
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=7,
            min_duration=2,
        )

    @patch("juloserver.loan.services.loan_creation.get_loan_matrices")
    @patch("juloserver.loan.services.views_related.get_range_loan_amount")
    def test_response_data_case_false_cashloan_available_limit(
        self, mock_get_range_loan_amount, mock_get_loan_matrices
    ):
        mock_get_loan_matrices.return_value = LoanCreditMatrices(
            credit_matrix=self.credit_matrix,
            credit_matrix_product_line=self.credit_matrix_product_line,
            credit_matrix_repeat=None,
        )
        mock_get_range_loan_amount_result = dict(
            min_amount_threshold=50_000,
            min_amount=300_000,
            max_amount=500_000,
            default_amount=100_000,
        )
        mock_get_range_loan_amount.return_value = mock_get_range_loan_amount_result

        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=False,
            account_id=self.account.id,
            input=None,
        )
        # mercury fs is inactive => available_cash_loan_limit amount should be ZERO
        self.mercury_fs.is_active = False
        self.mercury_fs.save()
        expected_available_cashloan_limit_data = {
            "name": "available_cash_loan_limit",
            "title": "Jumlah Pinjaman Tarik Dana",
            "icon": "https://statics.julo.co.id/loan/available_limit_info_page/red_money_bag.png",
            "item": [
                {
                    "item_icon": "https://statics.julo.co.id/loan/available_limit_info_page/icon_exclamation_circle.png",
                    "item_text": "Ini adalah jumlah maksimum untuk tarik dana karena riwayat pembayaranmu di JULO dan/atau aplikasi lain kurang baik",
                },
                {
                    "item_icon": "https://statics.julo.co.id/loan/available_limit_info_page/icon_sparkles.png",
                    "item_text": "Untuk dapat gunakan limitmu sepenuhnya di tarik dana, pastikan kamu selalu bayar tagihan di JULO dan/atau aplikasi lain tepat waktu, ya!",
                },
            ],
            "amount": 0,  # due to mercury inactive
        }
        expected_normal_available_limit_data = {
            "name": "normal_available_limit",
            "title": "Jumlah Pinjaman Total Di JULO",
            "icon": "https://statics.julo.co.id/loan/available_limit_info_page/web_perks.png",
            "item": [
                {
                    "item_icon": "",
                    "item_text": "Tapi, jika untuk beli pulsa dan token, bayar tagihan listrik, air, dan produk non tunai lainnya, kamu bisa transaksi sepenuhnya!",
                }
            ],
            "amount": self.account_limit.available_limit,
        }
        expected_response_list = [
            expected_available_cashloan_limit_data,
            expected_normal_available_limit_data,
        ]

        response = service.construct_response_data()
        self.assertEqual(response, expected_response_list)

        # case Mercury FS is active
        self.mercury_fs.is_active = True
        self.mercury_fs.save()

        # reinit service
        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=False, account_id=self.account.id, input=None
        )

        response = service.construct_response_data()
        self.assertEqual(response, expected_response_list)

        # case main FS is inactive, result is empty
        self.fs.is_active = False
        self.fs.save()

        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=True,
            account_id=self.account.id,
            input={
                "transaction_type_code": TransactionMethodCode.SELF.code,
            },
        )

        response = service.construct_response_data()
        self.assertEqual(response, [])

    @patch("juloserver.loan.services.loan_creation.get_loan_matrices")
    @patch("juloserver.loan.services.views_related.get_range_loan_amount")
    def test_response_data_case_true_cashloan_available_limit(
        self, mock_get_range_loan_amount, mock_get_loan_matrices
    ):
        mock_get_loan_matrices.return_value = LoanCreditMatrices(
            credit_matrix=self.credit_matrix,
            credit_matrix_product_line=self.credit_matrix_product_line,
            credit_matrix_repeat=None,
        )
        mock_get_range_loan_amount_result = dict(
            min_amount_threshold=50_000,
            min_amount=300_000,
            max_amount=500_000,
            default_amount=100_000,
        )
        mock_get_range_loan_amount.return_value = mock_get_range_loan_amount_result

        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=True,
            account_id=self.account.id,
            input={
                "transaction_type_code": TransactionMethodCode.SELF.code,
            },
        )
        # mercury fs is inactive => available_cash_loan_limit amount should be ZERO
        self.mercury_fs.is_active = False
        self.mercury_fs.save()
        expected_available_cashloan_limit_data = {
            "name": "available_cash_loan_limit",
            "title": "Jumlah Pinjaman Tarik Dana",
            "icon": "https://statics.julo.co.id/loan/available_limit_info_page/red_money_bag.png",
            "item": [
                {
                    "item_icon": "https://statics.julo.co.id/loan/available_limit_info_page/icon_exclamation_circle.png",
                    "item_text": "Ini adalah jumlah maksimum untuk tarik dana karena riwayat pembayaranmu di JULO dan/atau aplikasi lain kurang baik",
                },
                {
                    "item_icon": "https://statics.julo.co.id/loan/available_limit_info_page/icon_sparkles.png",
                    "item_text": "Untuk dapat gunakan limitmu sepenuhnya di tarik dana, pastikan kamu selalu bayar tagihan di JULO dan/atau aplikasi lain tepat waktu, ya!",
                },
            ],
            "amount": 0,  # due to mercury inactive
        }
        expected_normal_available_limit_data = {
            "name": "normal_available_limit",
            "title": "Jumlah Pinjaman Total Di JULO",
            "icon": "https://statics.julo.co.id/loan/available_limit_info_page/web_perks.png",
            "item": [
                {
                    "item_icon": "",
                    "item_text": "Tapi, jika untuk beli pulsa dan token, bayar tagihan listrik, air, dan produk non tunai lainnya, kamu bisa transaksi sepenuhnya!",
                }
            ],
            "amount": self.account_limit.available_limit,
        }
        expected_response_list = [
            expected_available_cashloan_limit_data,
            expected_normal_available_limit_data,
        ]

        response = service.construct_response_data()
        self.assertEqual(response, expected_response_list)

        # Mercury FS is active
        self.mercury_fs.is_active = True
        self.mercury_fs.save()

        # reinit
        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=True,
            account_id=self.account.id,
            input={
                "transaction_type_code": TransactionMethodCode.SELF.code,
            },
        )
        response = service.construct_response_data()
        expected_available_cashloan_limit_data['amount'] = mock_get_range_loan_amount_result[
            'max_amount'
        ]
        self.assertEqual(response, expected_response_list)

        # case main FS is inactive, result is empty
        self.fs.is_active = False
        self.fs.save()

        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=True,
            account_id=self.account.id,
            input={
                "transaction_type_code": TransactionMethodCode.SELF.code,
            },
        )

        response = service.construct_response_data()
        self.assertEqual(response, [])


class TestLockedProductPageService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.LOCK_PRODUCT_PAGE,
            is_active=True,
            parameters={
                "locked_settings": {
                    LockedProductPageSetting.MERCURY_LOCKED_SETTING: {
                        "header_image_url": LockedProductPageSetting.DEFAULT_HEADER_IMAGE_URL,
                        "locked_message": LockedProductPageSetting.MERCURY_LOCKED_MESSAGE,
                    }
                },
                "default_header_image_url": LockedProductPageSetting.DEFAULT_HEADER_IMAGE_URL,
                "default_locked_message": LockedProductPageSetting.DEFAULT_LOCKED_MESSAGE,
            },
        )

    def test_construct_response_data_mercury(self):
        service = LockedProductPageService(
            customer=self.customer,
            input_data={
                "page": CampaignConst.PRODUCT_LOCK_PAGE_FOR_MERCURY,
            },
        )

        response_data = service.construct_response_data()
        expected_response_data = {
            "locked_header_image": LockedProductPageSetting.DEFAULT_HEADER_IMAGE_URL,
            "locked_message": LockedProductPageSetting.MERCURY_LOCKED_MESSAGE,
            "is_show_repayment": True,
        }
        self.assertEqual(
            response_data,
            expected_response_data,
        )

    def test_construct_response_data_general_page(self):
        """
        Case page general, or no page name
        """
        page = "non-existing"
        service = LockedProductPageService(
            customer=self.customer,
            input_data={
                "page": page,
            },
        )

        response_data = service.construct_response_data()
        expected_response_data = {
            "locked_header_image": LockedProductPageSetting.DEFAULT_HEADER_IMAGE_URL,
            "locked_message": LockedProductPageSetting.DEFAULT_LOCKED_MESSAGE,
            "is_show_repayment": True,
        }
        self.assertEqual(
            response_data,
            expected_response_data,
        )

        # fs setting is off, response should be the same
        self.fs.is_active = False
        self.fs.save()

        response_data = service.construct_response_data()
        expected_response_data = {
            "locked_header_image": LockedProductPageSetting.DEFAULT_HEADER_IMAGE_URL,
            "locked_message": LockedProductPageSetting.DEFAULT_LOCKED_MESSAGE,
            "is_show_repayment": True,
        }
        self.assertEqual(
            response_data,
            expected_response_data,
        )


class TestUserCampaignEligibilityAPIV2Service(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

        self.input_data = {
            "transaction_type_code": TransactionMethodCode.SELF.code,
        }
        self.mercury_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.ANA_TRANSACTION_MODEL,
            is_active=True,
            parameters={
                "cooldown_time_in_seconds": AnaTransactionModelSetting.DEFAULT_COOLDOWN_TIME,
                "request_to_ana_timeout_in_seconds": AnaTransactionModelSetting.DEFAULT_REQUEST_TIMEOUT,
                "whitelist_settings": {
                    "is_whitelist_active": False,
                    "whitelist_by_customer_id": [],
                    "whitelist_by_last_digit": [],
                },
                "is_hitting_ana": False,
            },
        )
        self.customer = CustomerFactory()

        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=20_000_000,
            available_limit=5_000_000,
        )

        self.credit_matrix = CreditMatrixFactory(
            product=ProductLookupFactory(
                product_line=self.product_line,
            )
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=7,
            min_duration=2,
        )

        self.fake_redis = MockRedisHelper()

    def test_customer_with_no_account(self):
        # 100 status customer with no account yet
        self.no_account_customer = CustomerFactory(account=None)
        validated_data = self.input_data

        service = UserCampaignEligibilityAPIV2Service(
            customer=self.no_account_customer,
            validated_data=validated_data,
        )

        response_data = service.construct_response_data()

        self.assertEqual(
            response_data,
            {
                'campaign_name': '',
                'alert_image': '',
                'alert_description': '',
                'max_default_amount': 0,
                'show_alert': False,
                'show_pop_up': False,
                'toggle_title': '',
                'toggle_description': '',
                'toggle_link_text': '',
                'toggle_click_link': '',
            },
        )

    @patch('juloserver.loan.services.views_related.MercuryCustomerService')
    def test_construct_response_data_for_mercury_case_blocked(self, mock_mercury_service):
        # set up

        mock_mercury_service_object = MagicMock()
        mock_mercury_service.return_value = mock_mercury_service_object
        mock_mercury_service_object.get_mercury_status_and_loan_tenure.return_value = True, None

        mock_mercury_service_object.is_mercury_customer_blocked.return_value = True

        validated_data = self.input_data

        service = UserCampaignEligibilityAPIV2Service(
            customer=self.customer,
            validated_data=validated_data,
        )

        response = service.construct_response_data()

        expected_response = {
            'campaign_name': CampaignConst.PRODUCT_LOCK_PAGE_FOR_MERCURY,
            'alert_image': '',
            'alert_description': '',
            'max_default_amount': 0,
            'show_alert': False,
            'show_pop_up': False,
            'toggle_title': '',
            'toggle_description': '',
            'toggle_link_text': '',
            'toggle_click_link': '',
        }

        self.assertEqual(response, expected_response)

    @patch('juloserver.loan.services.views_related.MercuryCustomerService')
    def test_construct_response_data_for_mercury_case_not_blocked(self, mock_mercury_service):
        # set up
        mock_mercury_service_object = MagicMock()
        mock_mercury_service.return_value = mock_mercury_service_object
        mock_mercury_service_object.get_mercury_status_and_loan_tenure.return_value = True, None

        mock_mercury_service_object.is_mercury_customer_blocked.return_value = False

        validated_data = self.input_data

        service = UserCampaignEligibilityAPIV2Service(
            customer=self.customer,
            validated_data=validated_data,
        )

        response = service.construct_response_data()

        # no campaign will show
        expected_response = {
            'campaign_name': '',
            'alert_image': '',
            'alert_description': '',
            'max_default_amount': 0,
            'show_alert': False,
            'show_pop_up': False,
            'toggle_title': '',
            'toggle_description': '',
            'toggle_link_text': '',
            'toggle_click_link': '',
        }

        self.assertEqual(response, expected_response)


class TestFilterLoanChoice(TestCase):
    def test_filter_loan_choice(self):

        # case 1
        loan_choice = {
            5: {'duration': 5, 'other_data': 'test,'},
            6: {'duration': 6, 'other_data': 'test,'},
            7: {'duration': 7, 'other_data': 'test,'},
            8: {'duration': 8, 'other_data': 'test,'},
            9: {'duration': 9, 'other_data': 'test,'},
        }

        displayed_tenures = [4, 5]
        result_choice = filter_loan_choice(
            original_loan_choice=loan_choice,
            displayed_tenures=displayed_tenures,
            customer_id=1,
        )

        self.assertEqual(
            sorted(list(result_choice.keys())),
            [5],
        )

        # case 2, no over-lap
        loan_choice = {
            1: {'duration': 1, 'other_data': 'test,'},
            2: {'duration': 2, 'other_data': 'test,'},
        }

        displayed_tenures = [3, 4]
        result_choice = filter_loan_choice(
            original_loan_choice=loan_choice,
            displayed_tenures=displayed_tenures,
            customer_id=1,
        )

        self.assertEqual(
            sorted(list(result_choice.keys())),
            [1, 2],
        )

        # case 3, no over-lap
        loan_choice = {
            5: {'duration': 5, 'other_data': 'test,'},
            6: {'duration': 6, 'other_data': 'test,'},
        }

        displayed_tenures = [3, 4]
        result_choice = filter_loan_choice(
            original_loan_choice=loan_choice,
            displayed_tenures=displayed_tenures,
            customer_id=1,
        )

        self.assertEqual(
            sorted(list(result_choice.keys())),
            [5, 6],
        )

        # case 4, some overlap
        loan_choice = {
            5: {'duration': 5, 'other_data': 'test,'},
            6: {'duration': 6, 'other_data': 'test,'},
        }

        displayed_tenures = [6, 7]
        result_choice = filter_loan_choice(
            original_loan_choice=loan_choice,
            displayed_tenures=displayed_tenures,
            customer_id=1,
        )

        self.assertEqual(
            sorted(list(result_choice.keys())),
            [6],
        )

        # case 5
        loan_choice = {
            3: {'duration': 3, 'other_data': 'test,'},
            4: {'duration': 4, 'other_data': 'test,'},
            5: {'duration': 5, 'other_data': 'test,'},
        }

        displayed_tenures = [2, 3, 4]
        result_choice = filter_loan_choice(
            original_loan_choice=loan_choice,
            displayed_tenures=displayed_tenures,
            customer_id=1,
        )

        self.assertEqual(
            sorted(list(result_choice.keys())),
            [3, 4],
        )

        # case 6
        loan_choice = {
            3: {'duration': 3, 'other_data': 'test,'},
            4: {'duration': 4, 'other_data': 'test,'},
            5: {'duration': 5, 'other_data': 'test,'},
            6: {'duration': 6, 'other_data': 'test,'},
            7: {'duration': 7, 'other_data': 'test,'},
            8: {'duration': 8, 'other_data': 'test,'},
        }

        displayed_tenures = [1, 2, 3, 4, 5]
        result_choice = filter_loan_choice(
            original_loan_choice=loan_choice,
            displayed_tenures=displayed_tenures,
            customer_id=1,
        )

        self.assertEqual(
            sorted(list(result_choice.keys())),
            [3, 4, 5],
        )


class TestComputeRangeMaxAmount(TestCase):
    def setUp(self):

        self.customer = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()

    @patch("juloserver.loan.services.views_related.LoanAmountFormulaService")
    def test_compute_range_max_amount_tarik(
        self,
        mock_formula_service,
    ):

        mock_service_object = MagicMock()
        mock_formula_service.return_value = mock_service_object

        available_limit = 1_000_000

        highest_allowed_loan_amount = compute_range_max_amount(
            transaction_type=TransactionMethodCode.SELF.name,
            available_limit=available_limit,
            app=self.application,
            provision_rate=0.08,
        )

        self.assertEqual(
            highest_allowed_loan_amount,
            1_000_000,
        )

    @patch("juloserver.loan.services.views_related.LoanAmountFormulaService")
    def test_compute_range_max_amount_kirim(
        self,
        mock_formula_service,
    ):
        mock_service_object = MagicMock()
        mock_formula_service.return_value = mock_service_object

        mock_service_object.compute_requested_amount_from_final_amount.return_value = 3_000_000

        available_limit = 3_290_340

        highest_allowed_loan_amount = compute_range_max_amount(
            transaction_type=TransactionMethodCode.OTHER.name,
            available_limit=available_limit,
            app=self.application,
            provision_rate=0.08,
        )

        self.assertEqual(
            highest_allowed_loan_amount,
            3_000_000,
        )

        mock_service_object.compute_requested_amount_from_final_amount.assert_called_once_with(
            final_amount=available_limit,
        )

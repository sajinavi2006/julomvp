from mock import patch
from django.conf import settings
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import FDCInquiry, FeatureSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, PaymentStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanPurposeFactory,
    PartnerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    BankFactory,
    LoanFactory,
    PaymentMethodFactory,
    PaymentMethodLookupFactory,
    GlobalPaymentMethodFactory,
)
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.partnership.constants import PartnershipTokenType
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting
from juloserver.julo.payment_methods import PaymentMethodCodes


class TestLeadgenMaxPlatformCheck(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.endpoint = "/api/leadgen/max-platform-check"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "bypass": {
                    "is_active": False,
                },
                "daily_checker_config": {
                    "last_access_days": 7,
                    "nearest_due_date_from_days": 5,
                    "retry_per_days": 1,
                    "rps_throttling": 1,
                },
                "fdc_data_outdated_threshold_days": 7,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 2,
                },
                "ineligible_alert_after_fdc_checking": {
                    "clickable_text": "di sini",
                    "content": "Kamu terdeteksi memiliki pinjaman aktif di {} aplikasi lain. Lunasi salah satu pinjaman dulu, ya. Kamu juga bisa baca info lebih lanjut di sini.",
                    "is_active": False,
                    "link": "https://www.julo.co.id/faq",
                    "title": "Kamu Belum Bisa Transaksi",
                },
                "ineligible_message_for_old_application": "Menurut aturan terbaru OJK, kamu tidak dapat memiliki pinjaman aktif di lebih dari 3 aplikasi berbeda. Lunasi salah satu pinjamanmu dulu untuk transaksi di JULO, ya!<br><br>Jika pinjamanmu sudah lunas. Kamu juga bisa tunggu 1x24 jam untuk coba lagi atau hubungi CS JULO.",
                "number_of_allowed_platforms": 3,
                "popup": {
                    "eligible": {
                        "additional_information": {
                            "clickable_text": "di sini",
                            "content": "Untuk informasi lebih lanjut, kamu bisa klik di sini",
                            "is_active": False,
                            "link": "https://www.julo.co.id/faq",
                        },
                        "banner": {
                            "is_active": False,
                            "url": "https://julofiles-uat.oss-ap-southeast-5.aliyuncs.com/static_test/loan/3_platform_validation/eligible.png",
                        },
                        "content": "Menurut aturan terbaru OJK, tiap pengguna hanya dapat memiliki pinjaman aktif di maks. 3 aplikasi yang berbeda.<br><br>Jadikan JULO sebagai aplikasi pinjaman pilihanmu, ya!",
                        "is_active": False,
                        "title": "Perhatikan Aturan Terbaru OJK, Ya!",
                    },
                    "ineligible": {
                        "additional_information": {
                            "clickable_text": "di sini",
                            "content": "for further information,you can click di sini",
                            "is_active": False,
                            "link": "https://www.julo.co.id/faq",
                        },
                        "banner": {
                            "is_active": False,
                            "url": "https://julofiles-uat.oss-ap-southeast-5.aliyuncs.com/static_test/loan/3_platform_validation/ineligible.png",
                        },
                        "content": "Sesuai aturan OJK, kamu hanya bisa punya pinjaman di maks.3 aplikasi. Lunasi hingga tersisa 2 pinjaman aktif untuk transaksi di JULO, ya!<br><br>Jika pinjamanmu sudah lunas, harap tunggu 1x24 jam untuk coba lagi atau hubungi CS JULO",
                        "is_active": False,
                        "title": "Kamu Belum Bisa Transaksi",
                    },
                },
                "whitelist": {"is_active": False, "list_application_id": []},
            },
            is_active=True,
            category="loan",
            description="Check number of other active platforms using FDC",
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.pk, score="C")
        self.account_property = AccountPropertyFactory(account=self.account, pgood=0.75)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_active_platform_check(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=token)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @patch("juloserver.loan.services.loan_related.get_info_active_loan_from_platforms")
    def test_fail_active_platform_check(self, mock_max_platform):
        FDCInquiry.objects.create(application_id=self.application.id, inquiry_status="success")
        mock_max_platform.return_value = ("", 5, "")
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=token)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestLeadgenBankAccountDestination(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.endpoint = "/api/leadgen/loan/bank-account-destination"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number="1234541352",
            name_in_bank="BCA",
            method="XFERS",
            validation_status="SUCCESS",
            mobile_phone="086747341324",
            attempt=0,
        )
        self.bank = BankFactory(
            bank_code="012",
            bank_name="BCA",
            xendit_bank_code="BCA",
            swift_bank_code="01",
            bank_name_frontend="BCA",
            xfers_bank_code="BCA",
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category="self", display_label="Pribadi", parent_category_id=1
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            id=12345,
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number="1234541352",
            is_deleted=False,
        )

        # Create JWT token
        jwt = JWTManager(
            user=self.customer.user,
            partner_name=self.partner_name,
            application_xid=self.application.application_xid,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = "Bearer {}".format(access.token)

    def test_success_get_leadgen_bank_account_destination(self):
        expected_response = {
            "accountDestinationId": 12345,
            "accountName": "BCA",
            "accountNumber": "1234541352",
            "name": "BCA",
            "logo": settings.BANK_LOGO_STATIC_FILE_PATH + "BCA.png",
            "accountCategory": "Pribadi",
        }

        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(expected_response, response.json().get("data"))

    def test_invalid_token_get_leadgen_bank_account_destination(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token + "asdasd")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_token_get_leadgen_bank_account_destination(self):
        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestLeadgenActiveAccountPayment(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.endpoint = "/api/leadgen/account/account-payment/active"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.account_property = AccountPropertyFactory(account=self.account, pgood=0.75)
        self.account_payment = AccountPaymentFactory(account=self.account)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DPD_WARNING_COLOR_TRESHOLD,
            is_active=True,
            parameters={"dpd_warning_color_treshold": -3},
        )
        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_active_account_payment(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)
        response_data = response.json()['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data["dueAmount"], self.account_payment.due_amount)
        self.assertEqual(response_data["dpd"], self.account_payment.dpd)

    def test_success_no_active_account_payment(self):
        self.account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
        self.account_payment.save()
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data, {"data": {}})


class TestLeadgenAccountPaymentDetail(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.account_payment_id = 12388
        self.endpoint = "/api/leadgen/account/account-payment/"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.account_payment = AccountPaymentFactory(
            id=self.account_payment_id,
            account=self.account,
        )

        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_account_payment_detail(self):
        response = self.client.get(
            self.endpoint + str(self.account_payment_id), HTTP_AUTHORIZATION=self.token
        )
        response_data = response.json()['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data["id"], self.account_payment_id)

    def test_success_no_account_payment_detail(self):
        response = self.client.get(self.endpoint + "123", HTTP_AUTHORIZATION=self.token)
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data, {"data": {}})


class TestLeadgenLoanTransactionResult(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.loan_xid = 8854321
        self.endpoint = "/api/leadgen/loan/"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.bank = BankFactory(
            bank_name_frontend="Mandiri",
            bank_logo="/static/images/bank_logo/MANDIRI.png",
        )
        self.name_bank_validation = NameBankValidationFactory(validated_name="PROD ONLY")
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            account_number="23475724796969",
            name_bank_validation=self.name_bank_validation,
        )
        self.transaction_method = TransactionMethodFactory(id=11111)
        self.loan_amount = 1000000
        self.loan = LoanFactory(
            loan_xid=self.loan_xid,
            customer=self.customer,
            loan_amount=self.loan_amount,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            bank_account_destination=self.bank_account_destination,
            transaction_method=self.transaction_method,
        )

        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_transaction_result(self):
        response = self.client.get(
            self.endpoint + str(self.loan_xid) + "/result", HTTP_AUTHORIZATION=self.token
        )
        response_data = response.json()['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data['amount'], self.loan_amount)

    def test_success_no_transaction_result(self):
        response = self.client.get(self.endpoint + "8854321/result", HTTP_AUTHORIZATION=self.token)
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestLeadgenGetPrimaryPaymentMethod(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.endpoint = "/api/leadgen/payment-method/primary"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.payment_method_name = "MANDIRI"
        self.payment_method = PaymentMethodFactory(
            id=123,
            payment_method_name=self.payment_method_name,
            bank_code="13",
            virtual_account="23475724796969",
            customer=self.customer,
            is_primary=True,
        )
        self.payment_method_lookup = PaymentMethodLookupFactory(
            name=self.payment_method_name,
            image_logo_url="/static/images/bank_logo/MANDIRI.png",
        )

        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_primary_payment_method(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)
        response_data = response.json()['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data["name"], self.payment_method_name)

    def test_success_no_primary_payment_method(self):
        self.payment_method.is_primary = False
        self.payment_method.save()
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data, {"data": {}})


class TestLeadgenLoanDetail(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.loan_xid = 8854321
        self.endpoint = "/api/leadgen/loan/"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.bank = BankFactory(
            bank_name_frontend="Mandiri",
            bank_logo="/static/images/bank_logo/MANDIRI.png",
        )
        self.name_bank_validation = NameBankValidationFactory(validated_name="PROD ONLY")
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            account_number="23475724796969",
            name_bank_validation=self.name_bank_validation,
        )
        self.transaction_method = TransactionMethodFactory(id=1111)
        self.loan_amount = 1000000
        self.loan = LoanFactory(
            loan_xid=self.loan_xid,
            customer=self.customer,
            loan_amount=self.loan_amount,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            bank_account_destination=self.bank_account_destination,
            transaction_method=self.transaction_method,
        )

        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_loan_data_exist(self):
        response = self.client.get(
            self.endpoint + str(self.loan_xid), HTTP_AUTHORIZATION=self.token
        )
        response_data = response.json()['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data['amount'], self.loan_amount)

    def test_success_with_loan_data_not_exist(self):
        response = self.client.get(self.endpoint + "123", HTTP_AUTHORIZATION=self.token)
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response_data['message'], "Loan tidak ditemukan")


class TestLeadgenLoanList(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.loan_xid = 8854321
        self.endpoint = "/api/leadgen/loans/"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )
        self.bank = BankFactory(
            bank_name_frontend="Mandiri",
            bank_logo="/static/images/bank_logo/MANDIRI.png",
        )
        self.name_bank_validation = NameBankValidationFactory(validated_name="PROD ONLY")
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            account_number="23475724796969",
            name_bank_validation=self.name_bank_validation,
        )
        self.transaction_method = TransactionMethodFactory(id=1111)
        self.loan_amount = 1000000
        self.loan = LoanFactory(
            loan_xid=self.loan_xid,
            customer=self.customer,
            loan_amount=self.loan_amount,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            bank_account_destination=self.bank_account_destination,
            transaction_method=self.transaction_method,
        )

        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_active_loan_list(self):
        response = self.client.get(self.endpoint + "active", HTTP_AUTHORIZATION=self.token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_success_with_paid_off_loan_list(self):
        response = self.client.get(self.endpoint + "paid-off", HTTP_AUTHORIZATION=self.token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestLeadgenLoanPurposes(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.endpoint = "/api/leadgen/loan/purposes/"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        self.transaction_method = TransactionMethodFactory(id=1111)
        self.loan_purposes = LoanPurposeFactory()

        self.token = self._create_token(self.customer, self.partner_name, self.application)

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=customer.user,
            partner_name=partner_name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_with_loan_purposes_data(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestLeadgenProductListView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.endpoint = "/api/leadgen/products"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

    def _create_token(self, customer, partner_name, application, token_type=None):
        if not token_type:
            token_type = PartnershipTokenType.ACCESS_TOKEN

        # Create JWT token
        jwt = JWTManager(
            user=self.customer.user,
            partner_name=self.partner_name,
            application_xid=self.application.application_xid,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=token_type)
        return "Bearer {}".format(access.token)

    def test_success_get_product_list(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_success_locked_other_products(self):
        token = self._create_token(self.customer, self.partner_name, self.application)
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=token)
        data = response.json()["data"]
        for product in data:
            if product["name"] not in {"tarik-dana", "semua-produk"}:
                self.assertEqual(product["isLocked"], True)


class TestLeadgenPaymentMethodList(TestCase):
    def setUp(self):
        self.maxDiff = None

        self.client = APIClient()
        self.endpoint = "/api/leadgen/payment-methods"
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.mobile_phone_1 = "081234567890"

        self.partnership_leadgen_api_config_fs = FeatureSettingFactory(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )

        self.order_payment_methods_by_groups_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
            is_active=True,
            parameters={
                "autodebet_group": [],
                "bank_va_group": [
                    "bank bca",
                    "bank bri",
                    "bank mandiri",
                    "permata bank",
                    "bank maybank",
                ],
                "e_wallet_group": ["gopay", "gopay tokenization", "ovo"],
                "new_repayment_channel_group": {"end_date": "", "new_repayment_channel": []},
                "retail_group": ["indomaret", "alfamart"],
            },
        )

        self.payment_method_faq_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.PAYMENT_METHOD_FAQ_URL,
            is_active=True,
            parameters={
                "ovo": "https://cms-staging.julo.co.id/cara-bayar?provider=ovo&metode=ovo&in_app=true",
                "gopay": "https://cms-staging.julo.co.id/cara-bayar?provider=gopay&metode=gopay&in_app=true",
                "alfamart": "https://cms-staging.julo.co.id/cara-bayar?provider=alfamart&metode=kasiralfamart&in_app=true",
                "bank bca": "https://cms-staging.julo.co.id/cara-bayar?provider=bankbca&metode=atmbca&in_app=true",
                "bank bni": "https://cms-staging.julo.co.id/cara-bayar?provider=bankbni&metode=atmbni&in_app=true",
                "bank bri": "https://cms-staging.julo.co.id/cara-bayar?provider=bankbri&metode=atmbri&in_app=true",
                "indomaret": "https://cms-staging.julo.co.id/cara-bayar?provider=indomaret&metode=kasirindomaret&in_app=true",
                "bank mandiri": "https://cms-staging.julo.co.id/cara-bayar?provider=bankmandiri&metode=atmmandiri&in_app=true",
                "bank maybank": "https://cms-staging.julo.co.id/cara-bayar?provider=maybank&metode=atmmaybankmenutransfer&in_app=true",
                "permata bank": "https://cms-staging.julo.co.id/cara-bayar?provider=bankpermata&metode=atmpermata&in_app=true",
                "bank cimb niaga": "https://cms-staging.julo.co.id/cara-bayar?in_app=true&provider=bankcimb",
                "gopay tokenization": "https://cms-staging.julo.co.id/cara-bayar?provider=gopay&metode=gopay&in_app=true",
            },
        )

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        self.payment_method_name_bca = "Bank BCA"
        self.payment_method_name_bri = "Bank BRI"
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
            virtual_account=PaymentMethodCodes.BRI + self.mobile_phone_1,
            sequence=1,
            bank_code="1",
        )
        PaymentMethodLookupFactory(name=self.payment_method_name_bri, code=PaymentMethodCodes.BRI)
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.BRI,
            payment_method_name=self.payment_method_name_bri,
        )
        PaymentMethodFactory(
            id=2,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.PERMATA,
            payment_method_name=self.payment_method_name_permata,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.PERMATA + self.mobile_phone_1,
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
            payment_method_name=self.payment_method_name_permata,
        )
        self.bca_payment_method = PaymentMethodFactory(
            id=3,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.BCA,
            payment_method_name=self.payment_method_name_bca,
            is_shown=True,
            is_primary=True,
            virtual_account=PaymentMethodCodes.BCA + self.mobile_phone_1,
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
            payment_method_name=self.payment_method_name_bca,
        )
        PaymentMethodFactory(
            id=4,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.OVO,
            payment_method_name=self.payment_method_name_ovo,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.OVO + self.mobile_phone_1,
            sequence=4,
            bank_code="4",
        )
        PaymentMethodLookupFactory(name=self.payment_method_name_ovo, code=PaymentMethodCodes.OVO)
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.OVO,
            payment_method_name=self.payment_method_name_ovo,
        )
        self.alfamart_payment_method = PaymentMethodFactory(
            id=5,
            customer=self.customer,
            payment_method_code=PaymentMethodCodes.ALFAMART,
            payment_method_name=self.payment_method_name_alfamart,
            is_shown=True,
            is_primary=False,
            virtual_account=PaymentMethodCodes.ALFAMART + self.mobile_phone_1,
            sequence=5,
            bank_code="5",
        )
        PaymentMethodLookupFactory(
            name=self.payment_method_name_alfamart, code=PaymentMethodCodes.ALFAMART
        )
        GlobalPaymentMethodFactory(
            is_active=True,
            payment_method_code=PaymentMethodCodes.ALFAMART,
            payment_method_name=self.payment_method_name_alfamart,
        )

        # Create JWT token
        jwt = JWTManager(
            user=self.customer.user,
            partner_name=self.partner_name,
            application_xid=self.application.application_xid,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = "Bearer {}".format(access.token)

    def test_success_get_payment_method_list(self):
        expected_response = {
            "bankVAs": [
                {
                    "id": 3,
                    "name": self.payment_method_name_bca,
                    "bankCode": "3",
                    "virtualAccount": PaymentMethodCodes.BCA + self.mobile_phone_1,
                    "logo": None,
                },
                {
                    "id": 1,
                    "name": self.payment_method_name_bri,
                    "bankCode": "1",
                    "virtualAccount": PaymentMethodCodes.BRI + self.mobile_phone_1,
                    "logo": None,
                },
                {
                    "id": 2,
                    "name": self.payment_method_name_permata,
                    "bankCode": "2",
                    "virtualAccount": PaymentMethodCodes.PERMATA + self.mobile_phone_1,
                    "logo": None,
                },
            ],
            "retails": [
                {
                    "id": 5,
                    "name": self.payment_method_name_alfamart,
                    "bankCode": "5",
                    "virtualAccount": PaymentMethodCodes.ALFAMART + self.mobile_phone_1,
                    "logo": None,
                }
            ],
            "eWallets": [
                {
                    "id": 4,
                    "name": self.payment_method_name_ovo,
                    "bankCode": "4",
                    "virtualAccount": PaymentMethodCodes.OVO + self.mobile_phone_1,
                    "logo": None,
                }
            ],
        }

        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(expected_response, response.json().get("data"))

    def test_invalid_token_get_payment_method_list(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token + "asdasd")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_token_get_payment_method_list(self):
        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestLeadgenLoanAgreementContentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        FeatureSetting.objects.create(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            is_active=True,
            parameters={"allowed_partner": [self.partner_name]},
            category="partner",
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, email="prod.only@julofinance.com")
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            partner=self.partner,
        )

        self.name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number="1234541352",
            name_in_bank="BCA",
            method="XFERS",
            validation_status="SUCCESS",
            mobile_phone="086747341324",
            attempt=0,
        )
        self.bank = BankFactory(
            bank_code="012",
            bank_name="BCA",
            xendit_bank_code="BCA",
            swift_bank_code="01",
            bank_name_frontend="BCA",
            xfers_bank_code="BCA",
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category="self", display_label="Pribadi", parent_category_id=1
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            id=12345,
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number="1234541352",
            is_deleted=False,
        )

        self.loan_xid = 8854321
        self.loan_amount = 1000000
        self.transaction_method = TransactionMethodFactory(id=123)

        self.loan = LoanFactory(
            loan_xid=self.loan_xid,
            customer=self.customer,
            loan_amount=self.loan_amount,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            bank_account_destination=self.bank_account_destination,
            transaction_method=self.transaction_method,
        )

        self.endpoint = "/api/leadgen/loan/{}/agreement".format(self.loan_xid)

        # Create JWT token
        jwt = JWTManager(
            user=self.customer.user,
            partner_name=self.partner_name,
            application_xid=self.application.application_xid,
            product_id=self.application.product_line_code,
        )
        access = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)
        self.token = "Bearer {}".format(access.token)

    def test_success_get_leadgen_loan_agreement_content(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_invalid_token_get_leadgen_loan_agreement_content(self):
        response = self.client.get(self.endpoint, HTTP_AUTHORIZATION=self.token + "asdasd")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_token_get_leadgen_loan_agreement_content(self):
        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

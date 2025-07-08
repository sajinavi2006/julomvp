from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from juloserver.portal.object.loan_app.constants import ImageUploadType

from unittest.mock import patch

import mock
from django.test.testcases import TestCase
from rest_framework.test import APIClient, APITestCase
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_400_BAD_REQUEST,
    HTTP_405_METHOD_NOT_ALLOWED,
)
from django.utils import timezone
from django.conf import settings
from datetime import datetime, timedelta
import json
import tempfile
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from factory import Iterator

from juloserver.account.constants import AccountConstant
from juloserver.graduation.tests.factories import CustomerSuspendFactory, \
    CustomerSuspendHistoryFactory
from juloserver.julo.models import StatusLookup, SepulsaProduct
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
    ApplicationStatusCodes,
)
from juloserver.julo.tests.factories import (
    ProductLineFactory,
    LoanPurposeFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    CreditScoreFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    StatusLookupFactory,
    ProductLookupFactory,
    ProductLineLoanPurposeFactory,
    WorkflowFactory,
    AffordabilityHistoryFactory,
    BankFactory,
    LoanFactory,
    FeatureSettingFactory,
    SepulsaProductFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    DocumentFactory,
    ImageFactory,
    SepulsaTransactionFactory,
    FDCActiveLoanCheckingFactory
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
    AccountPropertyFactory,
)
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julovers.tests.factories import JuloverFactory
from juloserver.loan.constants import OneClickRepeatConst, LoanFeatureNameConst
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.otp.constants import SessionTokenAction
from juloserver.otp.tests.factories import OtpTransactionFlowFactory
from juloserver.pin.models import CustomerPin
from juloserver.julo.constants import FeatureNameConst
from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory
from juloserver.pin.tests.factories import TemporarySessionFactory
from juloserver.promo.constants import PromoCodeBenefitConst, PromoCodeTypeConst
from juloserver.promo.tests.factories import PromoCodeFactory
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
    FintechFactory,
)
from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.loan.constants import DBRConst
from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.loan.models import (
    LoanAdditionalFeeType,
)
from juloserver.loan.constants import LoanTaxConst
from juloserver.julo.services2.redis_helper import MockRedisHelper
from freezegun import freeze_time
from juloserver.loan.utils import is_max_creditors_done_in_1_day
from juloserver.payment_point.tests.factories import (
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)


class TestLoanPurpose(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.loan_purpose = LoanPurposeFactory()
        self.product_line_loan_purpose = ProductLineLoanPurposeFactory(
            product_line=self.product_line
        )

    def test_get_loan_purpose(self):
        res = self.client.get('/api/loan/v1/loan-purpose/')
        assert res.status_code == 200


class TestLoanCalculationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.customer = CustomerFactory(user=self.user, nik='1234567890123456')
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line
        )
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        StatusLookupFactory(status_code=210)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id, score=u'A-', credit_matrix_id=self.credit_matrix.id
        )

        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )

        self.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow, name='julo1', payment_frequency='1'
        )

        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.account_credit_limit = AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=10000000,
            available_limit=10000000,
            latest_affordability_history=self.affordability_history,
            latest_credit_score=self.credit_score,
        )
        self.application.account = self.account
        self.application.save()
        self.application.refresh_from_db()
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
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
        )
        self.sepulsa_product = SepulsaProductFactory(
            product_id='1',
            product_name='Token 20000',
            product_nominal=25000,
            product_label='Token 20000',
            product_desc='Token 20000',
            type=SepulsaProductType.BPJS,
            category=SepulsaProductCategory.BPJS_KESEHATAN[0],
            partner_price=20000,
            customer_price=26000,
            is_active=True,
            customer_price_regular=21000,
            is_not_blocked=True,
            admin_fee=1000,
            service_fee=2000,
            collection_fee=1000,
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={'daily_max_fee': 0.4},
        )

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_range_loan_amount(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.get('/api/loan/v1/range-loan-amount/{}'.format(self.account.id))
        assert res.status_code == 200
        res = self.client.get('/api/loan/v1/range-loan-amount/{}'.format(0))
        response_data = res.json()
        self.assertEqual(response_data['success'], False)

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_loan_duration(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        data = {
            "loan_amount_request": 3000000,
            "account_id": self.account.id,
            "self_bank_account": True,
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan-duration', data=data, format='json')
        assert res.status_code == 200
        data["self_bank_account"] = False
        res = self.client.post('/api/loan/v1/loan-duration/', data=data, format='json')
        assert res.status_code == 200
        data['account_id'] = 12312312
        res = self.client.post('/api/loan/v1/loan-duration/', data=data, format='json')
        response_data = res.json()
        self.assertEqual(response_data['success'], False)
        data['account_id'] = self.account.id
        res = self.client.get('/api/loan/v1/loan-duration/', data=data, format='json')
        assert res.status_code != 200

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_submit_loan_request(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        self.application.customer.user.set_password('123456')
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": True,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        assert res.status_code == 200

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_submit_loan_request_with_tax_active(
        self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        tax_feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        self.application.customer.user.set_password('123456')
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": True,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
        }
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        data = res.json()['data']
        assert res.status_code == 200
        assert data['tax'] != 0

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_submit_loan_request_with_tax_inactive(
        self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        tax_feature_setting = FeatureSettingFactory(
            is_active=False,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        self.application.customer.user.set_password('123456')
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": True,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
        }
        self.credit_matrix_product_line.product = product_line
        self.credit_matrix_product_line.save()
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        data = res.json()['data']
        assert res.status_code == 200
        assert data['tax'] == 0

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_create_payment_point_loan(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        self.application.customer.user.set_password('123456')
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": False,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
            "is_payment_point": True,
            "bpjs_number": "1",
            "bpjs_times": 1,
            "payment_point_product_id": self.sepulsa_product.id,
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(SepulsaProduct.objects.all()), 1)

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_create_payment_point_loan_phone_validation(
        self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        self.application.customer.user.set_password('123456')
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": False,
            "mobile_number": "081234",
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
            "is_payment_point": True,
            "bpjs_number": "1",
            "bpjs_times": 1,
            "payment_point_product_id": self.sepulsa_product.id,
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        assert res.status_code == 400
        assert res.json()['errors'][0] == ErrorMessageConst.PHONE_INVALID

        # valid mobile number
        data['mobile_number'] = "081216986633"
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        assert res.status_code == 200

        data['mobile_number'] = "628970091935"
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        assert res.status_code == 200

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_response_error_message(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        self.application.customer.user.set_password('123456')
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        AccountPropertyFactory(account=self.account)
        self.loan = LoanFactory(customer=self.customer, account=self.account, application=None)

        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": False,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
            "is_payment_point": True,
            "bpjs_number": "1",
            "bpjs_times": 1,
            "payment_point_product_id": self.sepulsa_product.id,
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        assert res.json()['errors'][0] == ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT

        res = self.client.post('/api/loan/v2/loan', data=data, format='json')
        assert res.json()['errors'][0] == ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_submit_loan_request_with_dbr(
        self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "ratio_percentage": DBRConst.DEFAULT_INCOME_PERCENTAGE,
                "popup_banner": DBRConst.DEFAULT_POPUP_BANNER,
                "product_line_ids": DBRConst.DEFAULT_PRODUCT_LINE_IDS,
            },
        )
        monthly_income = 10_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+1),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+2),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=1_000_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.save()
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        self.application.customer.user.set_password('123456')
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": True,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
            "transaction_type_code": 1,
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        assert res.status_code == 200

    @mock.patch(
        'juloserver.loan.views.views_api_v1.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_submit_loan_request_with_dbr_exception(
        self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "ratio_percentage": DBRConst.DEFAULT_INCOME_PERCENTAGE,
                "popup_banner": DBRConst.DEFAULT_POPUP_BANNER,
                "product_line_ids": DBRConst.DEFAULT_PRODUCT_LINE_IDS,
            },
        )
        monthly_income = 1_000_000
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+1),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+2),
            due_amount=1_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=+3),
            due_amount=1_000_000,
        )
        self.application.monthly_income = monthly_income
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.application_status_id = 420
        self.application.save()
        CustomerPin.objects.create(
            last_failure_time=timezone.localtime(timezone.now()),
            user=self.application.customer.user,
        )
        self.application.customer.user.set_password('123456')
        self.application.customer.user.save()
        self.application.customer.user.refresh_from_db()
        data = {
            "loan_amount_request": 3000000,
            "loan_duration": 2,
            "account_id": self.account.id,
            "bank_account_number": "1231242",
            "username": self.application.customer.nik,
            "pin": '123456',
            "self_bank_account": True,
            "bank_account_destination_id": self.bank_account_destination.id,
            "loan_purpose": "Modal usaha",
            "transaction_type_code": 1,
        }
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (
            self.credit_matrix,
            self.credit_matrix_product_line,
        )
        res = self.client.post('/api/loan/v1/loan', data=data, format='json')
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST, res.content)


class TestLoanDetailsAndTemplate(TestCase):
    def generate_dummy_image(self, width, height, color=(255, 255, 255), format='PNG'):
        img = Image.new('RGB', (width, height), color)

        temp_file = BytesIO()
        img.save(temp_file, format=format)

        dummy_image = SimpleUploadedFile(
            "dummy_image.{}".format(format.lower()),
            temp_file.getvalue(),
            content_type="image/{}".format(format.lower()),
        )

        return dummy_image

    def generate_dummy_text_file(self, content, file_extension='txt'):
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
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line, email='test_email@gmail.com'
        )
        self.application.dob = datetime(1994, 6, 10)
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.account_limit = AccountLimitFactory(
            latest_credit_score=self.credit_score,
            account=self.account,
        )
        self.loan = LoanFactory(customer=self.customer, account=self.account, application=None)
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        parameters_digital_signature = {'digital_signature_loan_amount_threshold': 500000}
        parameters_voice_record = {'voice_recording_loan_amount_threshold': 500000}
        self.feature_voice = FeatureSettingFactory(
            feature_name=FeatureNameConst.VOICE_RECORDING_THRESHOLD,
            parameters=parameters_voice_record,
        )
        self.feature_signature = FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGITAL_SIGNATURE_THRESHOLD,
            parameters=parameters_digital_signature,
        )
        self.loan.loan_xid = 1000023456
        self.application.account = self.account
        self.application.save()
        self.loan.loan_amount = 1000000
        self.loan.save()

    def test_loan_details(self):
        res = self.client.get('/api/loan/v1/agreement/loan/1000023456/')
        self.assertIs(res.status_code, 200)

    def test_loan_details_fintech_name(self):
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.DISBURSED,
            loan=self.loan,
        )

        self.name_bank_validation = NameBankValidationFactory(method="Xfers")
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.save()

        res = self.client.get('/api/loan/v1/agreement/loan/1000023456/')
        body = res.json()
        self.assertIsNot(body['data']["loan"]["fintech_name"], None)

    def test_loan_content(self):
        res = self.client.get('/api/loan/v1/agreement/content/1000023456/')
        self.assertIs(res.status_code, 200)

    def test_loan_content_for_julovers(self):
        product_line = ProductLineFactory()
        product_line.product_line_code = 200
        product_line.save()
        self.application.product_line = product_line
        self.application.save()
        julover = JuloverFactory(
            application_id=self.application.id, email='abcxyz@gmail.com', real_nik='123456789'
        )
        with self.assertTemplateUsed('../../julovers/templates/julovers/julovers_sphp.html'):
            response = self.client.get('/api/loan/v1/agreement/content/1000023456/')
        self.assertEqual(response.status_code, 200)

    def test_upload_signature(self):
        dummy_png = self.generate_dummy_image(300, 200)
        data = {"data": "NotEmpty", 'upload': dummy_png}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertIs(res.status_code, 201)

    def test_upload_signature_for_grab(self):
        self.account.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow,
            name='GRAB',
            payment_frequency='1'
        )
        self.account.save()

        self.loan.loan_status = StatusLookupFactory(status_code=210)

        FDCActiveLoanCheckingFactory(
            number_of_other_platforms=4, customer=self.customer
        )

        dummy_png = self.generate_dummy_image(300, 200)
        data = {"data": "NotEmpty", 'upload': dummy_png}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertIs(res.status_code, 201)

    def test_upload_signature_for_grab_no_fdc_active_loan_checking(self):
        self.account.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow,
            name='GRAB',
            payment_frequency='1'
        )
        self.account.save()

        self.loan.loan_status = StatusLookupFactory(status_code=210)

        dummy_png = self.generate_dummy_image(300, 200)
        data = {"data": "NotEmpty", 'upload': dummy_png}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertIs(res.status_code, 201)

    @patch("juloserver.loan.views.views_api_v1.update_loan_status_and_loan_history")
    def test_upload_signature_for_grab_out_date_fdc_active_loan_checking(
        self,
        mock_update_loan_status_and_loan_history
    ):
        self.account.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow,
            name='GRAB',
            payment_frequency='1'
        )
        self.account.save()

        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.cdate = '2024-01-01'
        self.loan.update_safely(
            cdate='2024-01-01'
        )

        FDCActiveLoanCheckingFactory(
            number_of_other_platforms=4, customer=self.customer
        )

        dummy_png = self.generate_dummy_image(300, 200)
        data = {"data": "NotEmpty", 'upload': dummy_png}
        resp = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertIs(resp.status_code, HTTP_400_BAD_REQUEST)
        mock_update_loan_status_and_loan_history.assert_called_with(
            loan_id=self.loan.id,
            new_status_code=216,
            change_reason="No 3 max creditors check"
        )

    @patch("juloserver.loan.views.views_api_v1.update_loan_status_and_loan_history")
    @patch("juloserver.loan.views.views_api_v1.is_max_creditors_done_in_1_day")
    def test_upload_signature_for_grab_3_max_creds_done_more_than_1_day(
        self,
        mock_is_max_creditors_done_in_1_day,
        mock_update_loan_status_and_loan_history
    ):
        mock_is_max_creditors_done_in_1_day.return_value = False

        self.account.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow,
            name='GRAB',
            payment_frequency='1'
        )
        self.account.save()

        self.loan.loan_status = StatusLookupFactory(status_code=210)

        FDCActiveLoanCheckingFactory(
            number_of_other_platforms=4, customer=self.customer
        )

        dummy_png = self.generate_dummy_image(300, 200)
        data = {"data": "NotEmpty", 'upload': dummy_png}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertIs(res.status_code, HTTP_400_BAD_REQUEST)
        mock_update_loan_status_and_loan_history.assert_called_with(
            loan_id=self.loan.id,
            new_status_code=216,
            change_reason="No 3 max creditors check"
        )

    def test_upload_signature_jpeg(self):
        dummy_jpg = self.generate_dummy_image(300, 200, format="jpeg")
        data = {"data": "NotEmpty", 'upload': dummy_jpg}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertIs(res.status_code, 201)

    def test_failed_upload_signature_not_image(self):
        dummy_file = self.generate_dummy_text_file("test", file_extension="sh")
        data = {"data": "NotEmpty", 'upload': dummy_file}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)

    def test_failed_upload_signature_invalid_image(self):
        fake_image = self.generate_dummy_text_file("yowman", "png")
        data = {"data": "NotEmpty", 'upload': fake_image}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)

        invalid_format_image = self.generate_dummy_image(300, 200, format="PDF")
        data = {"data": "NotEmpty", 'upload': invalid_format_image}
        res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
        self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)

    def test_failed_upload_signature_invalid_path(self):
        test_cases = [
            '..',
            '../',
            '../../../',
            '/../../',
            '<script>hello world</script>',
            'hello!',
            '$yowman',
            '!yo',
            '--',
            '*/halsdhfldkf',
            'lajsdf\*',
            'infosec/try/to/write/on/other/malicious.php',
            'infosec/try/to/write/on/other/05052025.jpg',
        ]

        for path in test_cases:
            dummy_png = self.generate_dummy_image(300, 200)

            data = {"data": "{}/NotEmpty".format(path), 'upload': dummy_png}
            res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
            self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)

        for path in test_cases:
            dummy_png = self.generate_dummy_image(300, 200)
            data = {"data": "NotEmpty/{}".format(path), 'upload': dummy_png}
            res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
            self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)

        for path in test_cases:
            dummy_png = self.generate_dummy_image(300, 200)
            data = {"data": path, 'upload': dummy_png}
            res = self.client.post('/api/loan/v1/agreement/signature/upload/1000023456/', data=data)
            self.assertEqual(res.status_code, HTTP_400_BAD_REQUEST)

    def test_voice_record(self):
        data = {
            "data": "NotEmpty",
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
        }

        res = self.client.post('/api/loan/v1/agreement/voice/upload/1000023456/', data=data)
        self.assertIs(res.status_code, 201)

    def test_get_voice_record_fraudster(self):
        customer = CustomerFactory()
        self.loan.customer_id = customer.pk
        self.loan.save()
        res = self.client.get('/api/loan/v1/agreement/voice/script/{}/'.format(self.loan.loan_xid))
        self.assertEqual(res.status_code, 403)

    @mock.patch('juloserver.loan.views.views_api_v1.get_voice_record_script')
    def test_get_voice_record_success(self, mock_get_voice_record_script):
        mock_get_voice_record_script.return_value = "success"
        res = self.client.get('/api/loan/v1/agreement/voice/script/{}/'.format(self.loan.loan_xid))
        self.assertEqual(res.status_code, 200)

    @mock.patch('juloserver.loan.views.views_api_v1.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v1.accept_julo_sphp')
    def test_accept_or_cancel_api(self, mock_accept, mock_cancel):
        data = {"status": "finish"}
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v1/agreement/loan/status/1000023456/', data=data, format='json'
        )
        self.assertIs(res.status_code, 200)
        mock_accept.assert_called_once()

        data = {"status": "cancel"}
        res = self.client.post(
            '/api/loan/v1/agreement/loan/status/1000023456/', data=data, format='json'
        )
        self.assertIs(res.status_code, 200)
        mock_cancel.assert_called_once()


class TestLoanSimulationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_range_loan_amount_simulation(self):
        response = self.client.get('/api/loan/v1/simulation/range-loan-amount')
        self.assertIs(response.status_code, 200)

    def test_loan_duratioin_simulation(self):
        data = dict(loan_amount=8000000, self_bank_account=True, is_payment_point=False)
        response = self.client.get('/api/loan/v1/simulation/loan-duration', data=data)
        self.assertIs(response.status_code, 200)


class TestChangeLoanStatusOtp(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line
        )
        self.application.dob = datetime(1994, 6, 10)
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.loan = LoanFactory(customer=self.customer, account=self.account, application=None)
        parameters_digital_signature = {'digital_signature_loan_amount_threshold': 500000}
        parameters_voice_record = {'voice_recording_loan_amount_threshold': 500000}
        self.feature_voice = FeatureSettingFactory(
            feature_name=FeatureNameConst.VOICE_RECORDING_THRESHOLD,
            parameters=parameters_voice_record,
        )
        self.feature_signature = FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGITAL_SIGNATURE_THRESHOLD,
            parameters=parameters_digital_signature,
        )
        self.loan.loan_xid = 1000023456
        self.application.account = self.account
        self.application.save()
        self.loan.loan_amount = 1000000
        self.loan.save()
        self.otf = OtpTransactionFlowFactory(customer=self.customer)
        self.mfs = MobileFeatureSettingFactory(feature_name='otp_setting')
        self.otp_request = OtpRequestFactory(action_type=SessionTokenAction.TRANSACTION_TARIK_DANA)
        self.session = TemporarySessionFactory(
            user=self.customer.user, otp_request=self.otp_request
        )
        self.image_factory = ImageFactory(
            image_type=ImageUploadType.SIGNATURE,
            image_source=self.loan.id,
            thumbnail_url_api='https://test',
            image_status=0,
        )

    @mock.patch('juloserver.loan.views.views_api_v2.is_eligible_for_sign_document')
    @mock.patch('juloserver.loan.views.views_api_v2.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_change_loan_status_otp_active(self, mock_accept, mock_cancel, mock_is_eligible_for_sign_document):
        self.mfs.is_active = True
        self.mfs.save()
        mock_is_eligible_for_sign_document.return_value = False
        data = {
            "status": "finish",
            "session_token": self.session.access_key,
            "action_type": SessionTokenAction.TRANSACTION_TARIK_DANA,
        }
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v2/agreement/loan/status/1000023456', data=data, format='json'
        )
        self.assertEqual(res.status_code, 200)
        mock_accept.assert_called_once()

    @mock.patch('juloserver.loan.views.views_api_v2.is_eligible_for_sign_document')
    @mock.patch('juloserver.loan.views.views_api_v2.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_change_loan_status_otp_inactive(self, mock_accept, mock_cancel, mock_is_eligible_for_sign_document):
        self.mfs.is_active = False
        self.mfs.save()

        data = {
            "status": "finish",
            "session_token": self.session.access_key,
            "action_type": SessionTokenAction.TRANSACTION_TARIK_DANA,
        }
        mock_is_eligible_for_sign_document.return_value = False
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v2/agreement/loan/status/1000023456', data=data, format='json'
        )
        self.assertEqual(res.status_code, 200)
        mock_accept.assert_called_once()

    @mock.patch('juloserver.loan.views.views_api_v2.is_eligible_for_sign_document')
    @mock.patch('juloserver.loan.views.views_api_v2.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_change_loan_status_otp_blank_active(self, mock_accept, mock_cancel, mock_is_eligible_for_sign_document):
        self.otf.loan_xid = 1000023456
        self.otf.action_type = SessionTokenAction.TRANSACTION_TARIK_DANA
        self.otf.is_allow_blank_token_transaction = True
        self.otf.save()
        self.mfs.is_active = True
        self.mfs.save()
        mock_is_eligible_for_sign_document.return_value = False

        data = {
            "status": "finish",
            "session_token": '',
            "action_type": SessionTokenAction.TRANSACTION_TARIK_DANA,
        }
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v2/agreement/loan/status/1000023456', data=data, format='json'
        )
        self.assertEqual(res.status_code, 200)
        mock_accept.assert_called_once()

    @mock.patch('juloserver.loan.views.views_api_v2.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_change_loan_status_otp_blank_inactive(self, mock_accept, mock_cancel):
        self.otf.loan_xid = 1000023456
        self.otf.action_type = SessionTokenAction.TRANSACTION_TARIK_DANA
        self.otf.is_allow_blank_token_transaction = False
        self.otf.save()
        self.mfs.is_active = True
        self.mfs.save()

        data = {
            "status": "finish",
            "session_token": '',
            "action_type": SessionTokenAction.TRANSACTION_TARIK_DANA,
        }
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v2/agreement/loan/status/1000023456', data=data, format='json'
        )
        self.assertEqual(res.status_code, 400)

    @mock.patch('juloserver.loan.views.views_api_v2.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_change_loan_status_otp_loan_invalid(self, mock_accept, mock_cancel):
        self.otf.loan_xid = 10000234
        self.otf.action_type = SessionTokenAction.TRANSACTION_TARIK_DANA
        self.otf.is_allow_blank_token_transaction = True
        self.otf.save()
        self.mfs.is_active = True
        self.mfs.save()

        data = {
            "status": "finish",
            "session_token": '',
            "action_type": SessionTokenAction.TRANSACTION_TARIK_DANA,
        }
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v2/agreement/loan/status/1000023456', data=data, format='json'
        )
        self.assertEqual(res.status_code, 400)

    @mock.patch('juloserver.loan.views.views_api_v2.cancel_loan')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_change_loan_status_otp_token_invalid(self, mock_accept, mock_cancel):
        self.otf.loan_xid = 1000023456
        self.otf.action_type = SessionTokenAction.TRANSACTION_TARIK_DANA
        self.otf.is_allow_blank_token_transaction = True
        self.otf.save()
        self.mfs.is_active = True
        self.mfs.save()

        data = {
            "status": "finish",
            "session_token": 'asdadq12131231',
            "action_type": SessionTokenAction.TRANSACTION_TARIK_DANA,
        }
        self.loan.loan_status = StatusLookup.objects.get(status_code=210)
        self.loan.save()
        mock_cancel.return_value = 216
        mock_accept.return_value = 211
        res = self.client.post(
            '/api/loan/v2/agreement/loan/status/1000023456', data=data, format='json'
        )
        self.assertEqual(res.status_code, 403)


class TestChangeLoanStatusV2(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        self.promo_code = PromoCodeFactory(
            promo_code="say-my-name...",
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=1000000,
        )
        self.image_factory = ImageFactory(
            image_type=ImageUploadType.SIGNATURE,
            image_source=self.loan.id,
            thumbnail_url_api='https://test',
            image_status=0,
        )

    @mock.patch('juloserver.loan.views.views_api_v2.PromoCodeService')
    @mock.patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    @mock.patch('juloserver.loan.views.views_api_v2.is_eligible_for_sign_document')
    def test_case_good_promo_code(self, mock_is_eligible_for_sign_document, mock_accept, mock_promo_service):
        mock_accept.return_value = 220
        mock_is_eligible_for_sign_document.return_value = False
        mock_promo_service.proccess_applied_with_loan.return_value = None
        self.loan.loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        data = {
            'status': 'finish',
            'promo_code': self.promo_code.promo_code,
        }
        response = self.client.post(
            path=f'/api/loan/v2/agreement/loan/status/{self.loan.loan_xid}',
            data=data,
            format='json',
        )

        self.assertEqual(response.status_code, HTTP_200_OK)


class TestJuloCardTransactionInfo(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(
            account=self.account,
            disbursement_id=888,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            transaction_method_id=10,
            loan_amount=100000,
            loan_duration=3,
            sphp_accepted_ts=timezone.localtime(timezone.now()),
            loan_xid=1231,
            customer=self.customer,
        )
        self.url_julo_card_transaction_info = '/api/loan/v1/julo-card/transaction-info/'

    def test_julo_card_transaction_info_should_success(self):
        response = self.client.get((self.url_julo_card_transaction_info + str(self.loan.loan_xid)))
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        sphp_accepted_ts_local = timezone.localtime(self.loan.sphp_accepted_ts)
        expected_result = {
            'date': sphp_accepted_ts_local.strftime('%Y-%m-%d'),
            'time': sphp_accepted_ts_local.strftime('%H:%M:%S'),
            'nominal': self.loan.loan_amount,
            'tenor': self.loan.loan_duration,
        }
        self.assertEqual(response['data'], expected_result)

    def test_julo_card_transaction_info_should_failed_when_pass_wrong_loan_xid(self):
        response = self.client.get((self.url_julo_card_transaction_info + '31231232'))
        self.assertEqual(response.status_code, 404, response.content)


class TestOneClickRepeatTransaction(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.application_status_id = 190
        self.application.save()

        self.bank_account_destination = BankAccountDestinationFactory(customer=self.customer)
        self.application.name_bank_validation = self.bank_account_destination.name_bank_validation
        self.application.save()
        self.loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name='one_click_repeat',
            parameters={'transaction_method_ids': [1, 5]},
            is_active=True,
        )
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        self.url = '/api/loan/v1/one-click-repeat/'
        self.url_v2 = '/api/loan/v2/one-click-repeat/'

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_get_one_loan_type_no_cache_success(self, mock_get_client):
        self.loans2 = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        len_response = len(response.json()['data'])
        self.assertEquals(len_response, 1)
        for index in range(len_response):
            loan_returned = response.json()['data'][index]
            self.assertEquals(
                loan_returned['title'],
                'Rp {:,}'.format(self.loans[index].loan_amount).replace(",", "."),
            )
            self.assertEquals(
                loan_returned['body'],
                '{} - {}'.format(
                    self.loans[index].bank_account_destination.bank.bank_name_frontend,
                    self.loans[index].bank_account_destination.account_number,
                ),
            )
            self.assertEquals(
                loan_returned['icon'], self.loans[index].transaction_method.foreground_icon_url
            )

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_get_one_loan_type_with_cache_success(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis
        expected_results = []
        for loan in self.loans:
            loan_info = dict()
            loan_info['title'] = 'Rp {:,}'.format(loan.loan_amount).replace(",", ".")
            loan_info['body'] = '{} - {}'.format(
                loan.bank_account_destination.bank.bank_name_frontend,
                loan.bank_account_destination.account_number,
            )
            loan_info['icon'] = loan.transaction_method.foreground_icon_url
            loan_info['product_data'] = {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "bank_account_destination_id": loan.bank_account_destination_id,
                "bank_account_number": loan.bank_account_destination.account_number,
                "loan_duration": loan.loan_duration,
                "loan_purpose": loan.loan_purpose,
                "loan_amount": loan.loan_amount,
            }

            expected_results.append(loan_info)
        fake_redis.set(
            OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT.format(self.customer.id),
            json.dumps(expected_results),
        )

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEquals(response.json()['data'], expected_results)

    def test_application_invalid(self):
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)

        self.application.delete()
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_404_NOT_FOUND)

    def test_invalid_request(self):
        response = self.client.post(self.url)
        self.assertEquals(response.status_code, HTTP_405_METHOD_NOT_ALLOWED)

    def test_feature_setting_off(self):
        self.feature_setting.update_safely(is_active=False)
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertIsNone(response.json()['data'])
        self.assertEqual(int(response._headers['x-cache-expiry'][1]), 1)

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_julo_starter_product_line(self, mock_get_client):
        self.application.update_safely(
            ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER)
        )

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        for index in range(len(response.json()['data'])):
            loan_returned = response.json()['data'][index]
            self.assertEquals(
                loan_returned['title'],
                'Rp {:,}'.format(self.loans[index].loan_amount).replace(",", "."),
            )
            self.assertEquals(
                loan_returned['body'],
                '{} - {}'.format(
                    self.loans[index].bank_account_destination.bank.bank_name_frontend,
                    self.loans[index].bank_account_destination.account_number,
                ),
            )
            self.assertEquals(
                loan_returned['icon'], self.loans[index].transaction_method.foreground_icon_url
            )

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_no_loan_user(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        for loan in self.loans:
            loan.delete()

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEquals(response.json()['data'], [])

        self.assertEquals(
            fake_redis.get(OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT.format(self.customer.id)),
            '[]',
        )

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_loan_missing_info(self, mock_get_client):
        client = APIClient()
        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth)
        client.credentials(HTTP_AUTHORIZATION='Token ' + user_auth.auth_expiry_token.key)
        account = AccountFactory(
            customer=customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 190
        application.save()

        BankAccountDestinationFactory(customer=customer)
        LoanFactory.create_batch(
            4,
            customer=customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=None,
        )

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEquals(response.json()['data'], [])

    @patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_check_redis_timeout(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertIsNotNone(
            fake_redis.get(OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT.format(self.customer.id))
        )

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_hide_one_click_repeat_with_inactive_account(self, mock_get_client):
        self.account.status_id = AccountConstant.STATUS_CODE.active_in_grace
        self.account.save()
        self.loans2 = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        data = response.json()['data']
        assert data == None

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_hide_one_click_repeat_with_balance_consolidation(self, mock_get_client):
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        self.name_bank_validation = NameBankValidationFactory(method="Xfers")
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.save()
        self.loans2 = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        data = response.json()['data']
        assert data == None

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_hide_one_click_repeat_with_balance_consolidation_and_inactive(self, mock_get_client):
        self.account.status_id = AccountConstant.STATUS_CODE.active_in_grace
        self.account.save()
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        self.name_bank_validation = NameBankValidationFactory(method="Xfers")
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.save()
        self.loans2 = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        data = response.json()['data']
        assert data == None

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_hide_one_click_repeat_with_customer_suspend(self, mock_get_client):
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        self.loans2 = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )
        CustomerSuspendFactory(customer_id=self.customer.id, is_suspend=True)
        CustomerSuspendHistoryFactory(
            customer_id=self.customer.id, change_reason='bad_and_good_repeat_rules'
        )
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        data = response.json()['data']
        self.assertIsNone(data)

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_show_one_click_repeat_with_customer_unsuspend(self, mock_get_client):
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        self.loans2 = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination,
        )
        CustomerSuspendFactory(customer_id=self.customer.id, is_suspend=False)

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        data = response.json()['data']
        self.assertEqual(len(data), 1)

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_get_latest_transactions_no_cache_success_v2(self, mock_get_client):
        # Dompet digital loans
        dompet_digital_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=20000,
            loan_status=StatusLookupFactory(status_code=210),
        )
        xfers_product = XfersProductFactory(type=SepulsaProductType.EWALLET)
        xferx_transactions = XfersEWalletTransactionFactory.create_batch(
            4,
            customer=self.customer,
            phone_number="081234000001",
            xfers_product=xfers_product,
            loan=Iterator(dompet_digital_loans),
        )

        for dompet_digital_loan in dompet_digital_loans:
            dompet_digital_loan.update_safely(loan_status_id=220)

        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        response = self.client.get(self.url_v2)
        self.assertEquals(response.status_code, HTTP_200_OK)
        len_response = len(response.json()['data'])
        self.assertEquals(len_response, 2)

        # Sepulsa loan
        loan_returned = response.json()['data'][0]
        self.assertEquals(loan_returned['loan_id'], dompet_digital_loans[-1].id)
        self.assertEquals(loan_returned['title'], xfers_product.product_name)
        self.assertEquals(loan_returned['body'], xferx_transactions[-1].phone_number)
        self.assertEquals(
            loan_returned['icon'], dompet_digital_loans[-1].transaction_method.foreground_icon_url
        )

        # Tarik dana loan
        loan_returned = response.json()['data'][1]
        self.assertEquals(loan_returned['loan_id'], self.loans[-1].id)
        self.assertEquals(
            loan_returned['title'],
            'Rp {:,}'.format(self.loans[-1].loan_amount).replace(",", "."),
        )
        self.assertEquals(
            loan_returned['body'],
            '{} - {}'.format(
                self.loans[-1].bank_account_destination.bank.bank_name_frontend,
                self.loans[-1].bank_account_destination.account_number,
            ),
        )
        self.assertEquals(
            loan_returned['icon'], self.loans[-1].transaction_method.foreground_icon_url
        )

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_get_latest_transactions_cache_success_v2(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        dompet_digital_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=20000,
            loan_status=StatusLookupFactory(status_code=210),
        )
        sepulsa_product = SepulsaProductFactory(type=SepulsaProductType.EWALLET)
        sepulsa_transactions = SepulsaTransactionFactory.create_batch(
            4,
            customer=self.customer,
            phone_number="081234000001",
            transaction_status="success",
            product=sepulsa_product,
            loan=Iterator(dompet_digital_loans),
        )
        for dompet_digital_loan in dompet_digital_loans:
            dompet_digital_loan.update_safely(loan_status_id=220)

        expected_results = []
        for sepulsa_transaction in sepulsa_transactions:
            loan_info = dict()
            loan = sepulsa_transaction.loan
            loan_info['loan_id'] = loan.id
            loan_info['title'] = sepulsa_transaction.product.product_name
            loan_info['body'] = sepulsa_transaction.phone_number
            loan_info['icon'] = loan.transaction_method.foreground_icon_url
            loan_info['product_data'] = {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "phone_number": sepulsa_transaction.phone_number,
                "loan_duration": loan.loan_duration,
                "loan_amount": loan.loan_amount,
                "sepulsa_product_id": sepulsa_product.id,
                "sepulsa_product_category": sepulsa_product.category,
            }
            expected_results.append(loan_info)

        for loan in self.loans:
            loan_info = dict()
            loan_info['loan_id'] = loan.id
            loan_info['title'] = 'Rp {:,}'.format(loan.loan_amount).replace(",", ".")
            loan_info['body'] = '{} - {}'.format(
                loan.bank_account_destination.bank.bank_name_frontend,
                loan.bank_account_destination.account_number,
            )
            loan_info['icon'] = loan.transaction_method.foreground_icon_url
            loan_info['product_data'] = {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "bank_account_destination_id": loan.bank_account_destination_id,
                "bank_account_number": loan.bank_account_destination.account_number,
                "loan_duration": loan.loan_duration,
                "loan_purpose": loan.loan_purpose,
                "loan_amount": loan.loan_amount,
            }
            expected_results.append(loan_info)

        fake_redis.set(
            OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V2.format(self.customer.id),
            json.dumps(expected_results),
        )

        response = self.client.get(self.url_v2)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEquals(response.json()['data'], expected_results)


class TestLoanRequestValidation(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.client.force_login(self.user_auth)
        self.client.force_authenticate(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(
            account=self.account,
            disbursement_id=888,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            transaction_method_id=10,
            loan_amount=100000,
            loan_duration=3,
            sphp_accepted_ts=timezone.localtime(timezone.now()),
            loan_xid=1231,
            customer=self.customer,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.account_limit = AccountLimitFactory(
            latest_credit_score=self.credit_score,
            account=self.account,
        )
        self.url = '/api/loan/v1/loan-request-validation/'

    def test_loan_request_validation_failed(self):
        another_user = AuthUserFactory()
        self.account.customer.user_id = another_user.id
        self.account.customer.save()

        response = self.client.get(
            self.url + "?loan_amount_request=1&account_id=" + str(self.account.id), format='json'
        )
        self.assertEqual(response.status_code, 403, response.content)

    @patch('juloserver.loan.views.views_api_v1.get_or_none_balance_consolidation')
    def test_loan_request_validation_success(self, mock_get_or_none_balance_consolidation):
        self.account.status = StatusLookupFactory(status_code=420)
        self.account.save()
        mock_get_or_none_balance_consolidation.return_value = False
        response = self.client.get(
            self.url + "?loan_amount_request=1&account_id=" + str(self.account.id), format='json'
        )
        self.assertEqual(response.status_code, 200, response.content)


class TestSavingInformationDuration(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_success_saving_information_duration(self):
        response = self.client.get('/api/loan/v1/saving-information/duration/')
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNotNone(response.data['data'])


class TestZeroInterestPopupBanner(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.client.force_login(self.user_auth)
        self.client.force_authenticate(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)

        self.feature_settings = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                'content': {
                    "title": 'Tarik Dana dengan Bunga 0%, Yuk!',
                    "banner_link": "https://statics.julo.co.id/zero_interest/banner_zero_interest.png",
                    "description": "Tarik dana max Rp3.000.000 "
                    "1-3 bulan, bunga 0%! Jangan lewatkan kesempatan ini!",
                    "webview_link": "https://www.julo.co.id",
                }
            },
        )

    def test_zero_interest_popup_banner(self):
        response = self.client.get('/api/loan/v1/zero-interest-popup-banner-content/')
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNotNone(response.data['data'])

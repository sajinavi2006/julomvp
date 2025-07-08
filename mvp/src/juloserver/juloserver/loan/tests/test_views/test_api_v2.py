import responses
from mock import MagicMock, patch
from datetime import datetime
from rest_framework import status
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR
from rest_framework.test import APIClient
from django.test.testcases import TestCase

from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
)
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.ecommerce.tests.factories import IpriceTransactionFactory

from juloserver.ecommerce.constants import IpriceTransactionStatus
from juloserver.ecommerce.models import IpriceStatusHistory
from juloserver.ecommerce.tests.factories import IpriceTransactionFactory
from juloserver.education.tests.factories import (
    SchoolFactory,
    StudentRegisterFactory,
    LoanStudentRegisterFactory,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from juloserver.loan.constants import CampaignConst
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.otp.tests.factories import OtpTransactionFlowFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
)
from juloserver.promo.constants import PromoCodeTimeConst
from juloserver.payment_point.models import TransactionMethod
from juloserver.promo.models import PromoCodeUsage
from juloserver.promo.tests.factories import (
    PromoCodeBenefitConst,
    PromoCodeBenefitFactory,
    PromoCodeCriteriaConst,
    PromoCodeCriteriaFactory,
    PromoCodeLoanFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    BankFactory,
    DocumentFactory,
    WorkflowFactory,
    ProductLineFactory,
    ProductLookupFactory,
    FeatureSettingFactory,
    ImageFactory,
    CreditScoreFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory, JuloverFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.healthcare.factories import HealthcareUserFactory
from django.contrib.contenttypes.models import ContentType
from juloserver.healthcare.models import HealthcareUser
from juloserver.loan.models import AdditionalLoanInformation


class TestRangeLoanAmount(TestCase):
    def setUp(self):
        super().setUp()
        self.available_limit = 1000000
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limt = AccountLimitFactory(
            account=self.account, available_limit=self.available_limit
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

    @patch('juloserver.loan.views.views_api_v2.logger')
    @patch('juloserver.loan.views.views_api_v2.get_credit_matrix_and_credit_matrix_product_line')
    def test_no_product_in_credit_matrix(
        self, mock_get_credit_matrix_and_credit_matrix_product_line, mock_logger
    ):
        """
        https://juloprojects.atlassian.net/browse/RUS1-101
        https://sentry.io/organizations/juloeng/issues/2434400563
        """
        credit_matrix = CreditMatrixFactory(product=None)
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = (credit_matrix, None)
        data = {'transaction_type_code': TransactionMethodCode.SELF.code}
        url = '/api/loan/v2/range-loan-amount/{}'.format(self.account.id)
        response = self.client.get(url, data)

        self.assertEqual(400, response.status_code, response.content)
        self.assertEqual('Product tidak ditemukan.', response.json()['errors'][0])

        # Check expected method calls
        mock_logger.info.assert_called_once_with(
            {
                'message': 'Unauthorized loan request.',
                'account_id': str(self.account.id),
                'self_bank_account': False,
                'transaction_method_id': str(TransactionMethodCode.SELF.code),
                'credit_matrix': credit_matrix,
            }
        )


class TestChangeLoanStatusView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        OtpTransactionFlowFactory(
            customer=self.customer,
            loan_xid=12345,
            action_type='transaction_pulsa_dan_data',
            is_allow_blank_token_transaction=True,
        )
        WorkflowStatusPathFactory(status_previous=210, status_next=211, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=210, status_next=216, workflow=self.workflow)
        self.promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={'percent': 1, 'max_cashback': 10000},
        )
        self.criterion_limit = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                'limit_per_promo_code': 1,
                'times': PromoCodeTimeConst.ALL_TIME,
            },
        )
        self.promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO', promo_code_benefit=self.promo_code_benefit
        )
        self.promo_code.criteria = [
            self.criterion_limit.id,
        ]
        self.promo_code.save()

        self.loan = LoanFactory(
            customer=self.customer,
            loan_xid=12345,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            account=self.account,
            application=self.application,
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.image_factory = ImageFactory(
            image_type=ImageUploadType.SIGNATURE,
            image_source=self.loan.id,
            thumbnail_url_api='https://test',
            image_status=0,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name='swift_limit_drainer',
            parameters={'jail_days': 0},
            is_active=False,
        )

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    @patch('juloserver.loan.views.views_api_v2.update_iprice_transaction_loan')
    def test_iprice_logic_is_called(
        self,
        mock_update_iprice_transaction_loan,
        mock_accept_julo_sphp,
    ):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        loan = self.loan

        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {
            'iprice_transaction_id': '12345',
            'status': 'finish',
            'action_type': 'transaction_pulsa_dan_data',
        }
        response = self.client.post(url, data)

        self.assertEqual(200, response.status_code, response.json())
        mock_accept_julo_sphp.assert_called_once()
        mock_update_iprice_transaction_loan.assert_called_once_with('12345', loan)

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    @patch('juloserver.loan.views.views_api_v2.update_iprice_transaction_loan')
    def test_iprice_logic_is_not_called(
        self, mock_update_iprice_transaction_loan, mock_accept_julo_sphp
    ):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        loan = self.loan
        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {'status': 'finish', 'action_type': 'transaction_pulsa_dan_data'}
        response = self.client.post(url, data)

        self.assertEqual(200, response.status_code, response.json())
        mock_update_iprice_transaction_loan.assert_not_called()

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_integration_update_iprice_transaction_loan(self, mock_accept_julo_sphp):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        account = AccountFactory(customer=self.customer)
        iprice_transaction = IpriceTransactionFactory(
            application=ApplicationFactory(customer=self.customer, account=account),
            customer=self.customer,
            current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=99999,
        )
        loan = LoanFactory(
            customer=self.customer,
            account=account,
            loan_amount=120000,
            loan_disbursement_amount=99999,
            loan_xid=12346,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )

        self.image_factory.image_source = loan.id
        self.image_factory.save()
        self.image_factory.refresh_from_db()

        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {
            'iprice_transaction_id': iprice_transaction.id,
            'status': 'finish',
            'action_type': 'transaction_pulsa_dan_data',
        }
        response = self.client.post(url, data)

        iprice_transaction.refresh_from_db()
        self.assertEqual(200, response.status_code, response.json())
        self.assertEqual(loan, iprice_transaction.loan)

    @responses.activate
    def test_integration_iprice_cancel_loan(self):
        account = AccountFactory(customer=self.customer)
        AccountLimitFactory(account=account, used_limit=0, available_limit=1000000)
        iprice_transaction = IpriceTransactionFactory(
            application=ApplicationFactory(customer=self.customer, account=account),
            customer=self.customer,
            current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=99999,
        )
        loan = LoanFactory(
            customer=self.customer,
            account=account,
            loan_amount=100000,
            loan_disbursement_amount=99999,
            loan_xid=12346,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )
        self.image_factory.image_source = loan.id
        self.image_factory.save()
        self.image_factory.refresh_from_db()
        # iprice mock response
        iprice_response_json = {
            'orderId': 'b113650m',
            'applicationId': str(iprice_transaction.iprice_transaction_xid),
            'confirmationStatus': 'success',
        }
        responses.add(
            responses.POST,
            'http://iprice.url/v1/invoice-callback/julo?pid=iprice-pid',
            json=iprice_response_json,
            status=200,
        )

        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {
            'iprice_transaction_id': iprice_transaction.id,
            'status': 'cancel',
            'action_type': 'transaction_pulsa_dan_data',
        }
        response = self.client.post(url, data)

        self.assertEqual(200, response.status_code, response.json())

        iprice_transaction.refresh_from_db()
        iprice_status_history = IpriceStatusHistory.objects.get(
            iprice_transaction=iprice_transaction
        )
        self.assertEqual(loan, iprice_transaction.loan)
        self.assertEqual(self.user, iprice_status_history.changed_by)
        self.assertEqual(IpriceTransactionStatus.LOAN_REJECTED, iprice_transaction.current_status)

    @responses.activate
    def test_integration_iprice_accept_sphp(self):
        account = AccountFactory(customer=self.customer)
        AccountLimitFactory(account=account, used_limit=0, available_limit=1000000)
        iprice_transaction = IpriceTransactionFactory(
            iprice_order_id='b113650m',
            application=ApplicationFactory(customer=self.customer, account=account),
            customer=self.customer,
            current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=99999,
        )
        loan = LoanFactory(
            customer=self.customer,
            account=account,
            loan_amount=100000,
            loan_disbursement_amount=99999,
            loan_xid=12346,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            transaction_method=TransactionMethod.objects.get(id=1),
        )
        self.image_factory.image_source = loan.id
        self.image_factory.save()
        self.image_factory.refresh_from_db()
        # iprice mock response
        iprice_response_json = {
            'orderId': 'b113650m',
            'applicationId': str(iprice_transaction.iprice_transaction_xid),
            'confirmationStatus': 'success',
        }
        responses.add(
            responses.POST,
            'http://iprice.url/v1/invoice-callback/julo?pid=iprice-pid',
            json=iprice_response_json,
            status=200,
        )

        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {
            'iprice_transaction_id': iprice_transaction.id,
            'status': 'finish',
            'action_type': 'transaction_pulsa_dan_data',
        }
        response = self.client.post(url, data)

        self.assertEqual(200, response.status_code, response.json())

        iprice_transaction.refresh_from_db()
        iprice_status_history = IpriceStatusHistory.objects.get(
            iprice_transaction=iprice_transaction
        )
        self.assertEqual(loan, iprice_transaction.loan)
        self.assertEqual(self.user, iprice_status_history.changed_by)
        self.assertEqual(IpriceTransactionStatus.PROCESSING, iprice_transaction.current_status)

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_promo_code_usage_count(self, mock_accept_julo_sphp):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        loan = self.loan
        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        payload = {'status': 'finish', 'promo_code': 'TESTPROMO'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(HTTP_200_OK, resp.status_code)

        self.promo_code.refresh_from_db()
        self.assertEqual(1, self.promo_code.promo_code_usage_count)
        self.assertEqual(1, self.promo_code.promo_code_daily_usage_count)
        promo_code_usage = PromoCodeUsage.objects.filter(
            promo_code=self.promo_code, loan_id=self.loan.id
        ).last()
        self.assertFalse(promo_code_usage.is_cancelled)

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_promo_code_reach_limit_per_promo_code(self, mock_accept_julo_sphp):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        loan1 = self.loan
        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan1.loan_xid)
        payload = {'status': 'finish', 'promo_code': 'TESTPROMO'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(HTTP_200_OK, resp.status_code)

        # loan2 will fail, because limit_per_promo_code = 1, it already applied to loan1
        loan2 = LoanFactory(
            customer=self.customer,
            loan_xid=23456,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )
        ImageFactory(
            image_type=ImageUploadType.SIGNATURE,
            image_source=loan2.id,
            thumbnail_url_api='https://test',
            image_status=0,
        )
        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan2.loan_xid)
        payload = {'status': 'finish', 'promo_code': 'TESTPROMO'}

        resp = self.client.post(url, payload, format='json')
        self.assertEqual(HTTP_400_BAD_REQUEST, resp.status_code)

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    def test_promo_code_do_not_apply_in_loan_balance_consolidation(self, mock_accept_julo_sphp):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        loan = self.loan
        balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        consolidation_verification.account_limit_histories = {
            "upgrade": {"max_limit": 385918, "set_limit": 385919, "available_limit": 385920}
        }
        consolidation_verification.loan = loan
        loan.save()
        consolidation_verification.save()

        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        payload = {'status': 'finish', 'promo_code': 'TESTPROMO'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(HTTP_200_OK, resp.status_code)

        promo_code_usage = PromoCodeUsage.objects.filter(loan_id=loan.id).first()
        self.assertIsNone(promo_code_usage)

    @patch('juloserver.loan.views.views_api_v2.accept_julo_sphp')
    @patch('juloserver.loan.views.views_api_v2.update_iprice_transaction_loan')
    def test_manual_signature(
        self,
        mock_update_iprice_transaction_loan,
        mock_accept_julo_sphp,
    ):
        mock_accept_julo_sphp.return_value = LoanStatusCodes.LENDER_APPROVAL
        loan = self.loan
        # test failed
        self.image_factory.image_source = 123232
        self.image_factory.save()
        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {
            'iprice_transaction_id': '12345',
            'status': 'finish',
            'action_type': 'transaction_pulsa_dan_data',
        }
        response = self.client.post(url, data)
        self.assertEqual(403, response.status_code, response.json())
        # test success
        self.image_factory.image_source = loan.id
        self.image_factory.save()
        self.image_factory.refresh_from_db()
        response = self.client.post(url, data)
        self.assertEqual(200, response.status_code, response.json())

    @responses.activate
    def test_manual_signature_cancel_loan(self):
        account = AccountFactory(customer=self.customer)
        AccountLimitFactory(account=account, used_limit=0, available_limit=1000000)
        iprice_transaction = IpriceTransactionFactory(
            application=ApplicationFactory(customer=self.customer, account=account),
            customer=self.customer,
            current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=99999,
        )
        loan = LoanFactory(
            customer=self.customer,
            account=account,
            loan_amount=100000,
            loan_disbursement_amount=99999,
            loan_xid=12346,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )
        self.image_factory.image_source = loan.id
        self.image_factory.save()
        self.image_factory.refresh_from_db()
        # iprice mock response
        iprice_response_json = {
            'orderId': 'b113650m',
            'applicationId': str(iprice_transaction.iprice_transaction_xid),
            'confirmationStatus': 'success',
        }
        responses.add(
            responses.POST,
            'http://iprice.url/v1/invoice-callback/julo?pid=iprice-pid',
            json=iprice_response_json,
            status=200,
        )

        url = '/api/loan/v2/agreement/loan/status/{}'.format(loan.loan_xid)
        data = {
            'iprice_transaction_id': iprice_transaction.id,
            'status': 'cancel',
            'action_type': 'transaction_pulsa_dan_data',
        }
        response = self.client.post(url, data)
        self.assertEqual(200, response.status_code, response.json())


class TestLoanDuration(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_iprice_case_invalid_amount(self):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        data = {
            "loan_amount_request": amount + 1,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
        }
        response = self.client.post('/api/loan/v2/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_iprice_case_invalid_id(self):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": 2394873294,
        }
        response = self.client.post('/api/loan/v2/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_iprice_case_wrong_transaction_type(self):
        amount = 3000000
        iprice_transac = IpriceTransactionFactory(
            customer=self.customer,
            application=self.application,
            iprice_total_amount=amount,
        )
        data = {
            "loan_amount_request": amount,
            "account_id": self.account.id,
            "self_bank_account": False,
            "iprice_transaction_id": iprice_transac.id,
            "transaction_type_code": 7,
        }
        response = self.client.post('/api/loan/v2/loan-duration/', data=data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)


class TestTransactionDetail(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)

    def test_get_transaction_detail_for_education(self):
        disbursement = DisbursementFactory(reference_id='contract_0b797cb8f5984e0e89eb802a009fa5f4')
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=220),
            disbursement_id=disbursement.id,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.EDUCATION.code, method=TransactionMethodCode.EDUCATION
            ),
        )
        DocumentFactory(document_type='education_invoice', document_source=loan.id)
        school = SchoolFactory()
        student_register = StudentRegisterFactory(
            account=self.account,
            school=school,
            bank_account_destination=BankAccountDestinationFactory(bank=BankFactory()),
            student_fullname='This is full name',
            note='123456789',
        )
        LoanStudentRegisterFactory(loan=loan, student_register=student_register)

        response = self.client.get('/api/loan/v2/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        student_tuition_info = response.data['data']['loan']['student_tuition']
        self.assertEqual(student_tuition_info['bank']['reference_number'], '079785984089')
        self.assertEqual(student_tuition_info['school']['name'], school.name)
        self.assertEqual(student_tuition_info['name'], student_register.student_fullname)
        self.assertEqual(student_tuition_info['note'], student_register.note)
        self.assertIsNotNone(student_tuition_info['invoice_pdf_link'])
        self.assertIn('category_product_name', response.data['data']['loan'])

        # test bank_reference_number is null when loan status < 220
        loan.loan_status = StatusLookupFactory(status_code=212)
        loan.save()
        response = self.client.get('/api/loan/v2/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['data']['loan']['student_tuition']['bank']['reference_number'], None
        )
        loan = response.json()['data']['loan']
        assert loan['crossed_installment_amount'] != None
        assert loan['crossed_loan_disbursement_amount'] != None
        assert loan['crossed_interest_rate_monthly'] != None

    def test_get_transaction_detail_for_healthcare(self):
        disbursement = DisbursementFactory(reference_id='contract_0b123cb4f5678ee9eb100a109fa5f4')
        healthcare_user = HealthcareUserFactory(account=self.account)
        bank_account_destination = healthcare_user.bank_account_destination
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=220),
            disbursement_id=disbursement.id,
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.HEALTHCARE.code, method=TransactionMethodCode.HEALTHCARE
            ),
            bank_account_destination=bank_account_destination,
        )
        AdditionalLoanInformation.objects.create(
            content_type=ContentType.objects.get_for_model(HealthcareUser),
            object_id=healthcare_user.pk,
            loan=loan,
        )
        DocumentFactory(document_type='healthcare_invoice', document_source=loan.id)

        response = self.client.get('/api/loan/v2/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        healthcare_user_info = response.data['data']['loan']['healthcare_user']
        self.assertEqual(
            healthcare_user_info['healthcare_platform_name'],
            healthcare_user.healthcare_platform.name,
        )
        self.assertEqual(healthcare_user_info['healthcare_user_fullname'], healthcare_user.fullname)
        self.assertEqual(healthcare_user_info['bank_reference_number'], '012345678910')
        self.assertIsNotNone(healthcare_user_info['invoice_pdf_link'])
        self.assertEqual(
            response.data['data']['loan']['bank']['account_name'],
            bank_account_destination.get_name_from_bank_validation,
        )
        self.assertEqual(
            response.data['data']['loan']['bank']['account_number'],
            bank_account_destination.account_number,
        )

        # test bank_reference_number is null when loan status < 220
        loan.loan_status = StatusLookupFactory(status_code=212)
        loan.save()
        response = self.client.get('/api/loan/v2/agreement/loan/{}/'.format(loan.loan_xid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        healthcare_user_info = response.data['data']['loan']['healthcare_user']
        self.assertIsNone(healthcare_user_info['bank_reference_number'])
        self.assertIsNone(healthcare_user_info['invoice_pdf_link'])


class TestLoanDetailsAndTemplateJulover(TestCase):
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

    def test_loan_content_for_julovers(self):
        product_line = ProductLineFactory()
        product_line.product_line_code = 200
        product_line.save()
        self.application.product_line = product_line
        self.application.save()
        JuloverFactory(
            application_id=self.application.id, email='abcxyz@gmail.com', real_nik='123456789'
        )
        with self.assertTemplateUsed('../../julovers/templates/julovers/julovers_sphp.html'):
            response = self.client.get('/api/loan/v2/agreement/content/1000023456/')
        print(response.json())
        self.assertEqual(response.status_code, 200)


class TestUserCampaignEligibilityView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.product_line,
        )
        self.account = AccountFactory(customer=self.customer)
        self.jc_feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CARE_CONFIGURATION,
            parameters={
                'alert_image': 'https://statics.julo.co.id/julo_care/julo_care_icon.png',
                'alert_description': '',
                'show_alert': True,
            },
            is_active=True,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            latest_credit_score=CreditScoreFactory(application_id=self.application.id),
            available_limit=2000000,
        )
        self.base_url = '/api/loan/v2/user-campaign-eligibility'

    @patch('juloserver.loan.views.views_api_v2.UserCampaignEligibilityAPIV2Service')
    def test_run_service_ok(self, mock_service):
        """
        Only need to mock, we have seperate test for the service class
        """
        mock_service_instance = MagicMock()
        mock_service.return_value = mock_service_instance

        test_response = {'test': 'test'}
        mock_service_instance.construct_response_data.return_value = test_response

        input_device_brand = "abc"
        input_device_model = "zxc"
        os_version = 37

        response = self.client.post(
            self.base_url,
            data={
                'transaction_type_code': TransactionMethodCode.SELF.code,
                'device_brand': input_device_brand,
                'device_model': input_device_model,
                'os_version': os_version,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], test_response)

    @patch('juloserver.loan.services.julo_care_related.get_eligibility_status')
    @patch('juloserver.loan.services.views_related.is_customer_can_do_zero_interest')
    @patch(
        'juloserver.loan.services.views_related.UserCampaignEligibilityAPIV2Service.'
        'is_customer_with_lock_product_campaign'
    )
    def test_get_julo_care_response(
        self,
        mock_is_customer_with_locked_product_campaign,
        mock_can_do_zero_interest,
        mock_julo_care_eligible,
    ):
        mock_is_customer_with_locked_product_campaign.return_value = False, {}
        mock_can_do_zero_interest.return_value = (False, {})
        mock_julo_care_eligible.return_value = (True, {})

        device_brand = 'xiaomi'
        device_model = 'Redmi Note 8'
        os_version = 30
        url = '/api/loan/v2/user-campaign-eligibility'

        response = self.client.post(
            url,
            data={
                'transaction_type_code': TransactionMethodCode.SELF.code,
                'device_brand': device_brand,
                'device_model': device_model,
                'os_version': os_version,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['campaign_name'], CampaignConst.JULO_CARE)
        mock_julo_care_eligible.assert_called_with(
            customer=self.customer,
            list_loan_tenure=[],
            loan_amount=self.account_limit.available_limit,
            device_brand=device_brand,
            device_model=device_model,
            os_version=os_version,
        )

        mock_julo_care_eligible.reset_mock()

        response = self.client.post(url, data={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['campaign_name'], "")
        mock_julo_care_eligible.assert_not_called()

        response = self.client.post(
            url,
            data={
                'transaction_type_code': TransactionMethodCode.OTHER.code,
                'device_brand': device_brand,
                'device_model': device_model,
                'os_version': os_version,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['campaign_name'], '')
        mock_julo_care_eligible.assert_not_called()

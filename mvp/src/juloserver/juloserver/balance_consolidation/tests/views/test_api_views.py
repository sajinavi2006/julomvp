import io
import json
from datetime import timedelta, datetime
from unittest import mock

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from factory import Iterator
from rest_framework.test import APIClient, APITestCase
from rest_framework.reverse import reverse

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountPropertyFactory,
    AccountLimitFactory,
)
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    TOKEN_EXPIRATION_DAYS,
    BalanceConsolidationFeatureName,
)
from juloserver.balance_consolidation.models import (
    BalanceConsolidation,
    BalanceConsolidationVerification,
)
from juloserver.balance_consolidation.services import BalanceConsolidationToken
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
    FintechFactory,
)
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.julo.constants import (
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CustomerFactory,
    LoanFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    FeatureSettingFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CurrentCreditMatrixFactory,
)
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.moengage.services.data_constructors import (
    construct_data_for_balance_consolidation_submit_form_id,
)


class TestBalanceConsolidation(APITestCase):
    @staticmethod
    def create_document():
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        canv = canvas.Canvas(buffer, pagesize=A4)
        canv.drawString(100, 400, "test")
        canv.save()
        pdf = buffer.getvalue()
        return pdf

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, email='kj.nam444@julofinance.com', fullname='Nguyen Van E')
        # Create PIN for submit
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()
        self.fintech = FintechFactory(is_active=True)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=10000)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        # Mock up data for get loan duration API
        transaction_type = "balance_consolidation"
        credit_matrix = CreditMatrixFactory(
            transaction_type=transaction_type, credit_matrix_type='julo1', parameter=''
        )
        CurrentCreditMatrixFactory(credit_matrix=credit_matrix, transaction_type=transaction_type)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=6000000, set_limit=6000000
        )
        self.bank = BankFactory(bank_name="test", is_active=True)

        from django.conf import settings

        settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY = (
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        )
        fernet = Fernet(settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY)
        event_time = timezone.localtime(timezone.now())
        expiry_time = event_time + timedelta(days=TOKEN_EXPIRATION_DAYS)
        info_dict = {
            'customer_id': self.customer.id,
            'event_time': event_time.timestamp(),
            'expiry_time': expiry_time.timestamp(),
        }
        encrypted_str = fernet.encrypt(json.dumps(info_dict).encode()).decode()
        self.url = reverse(
            'balance_consolidation:submit',
            kwargs={'token': encrypted_str},
        )
        self.get_loan_duration_url = reverse(
            'balance_consolidation:loan_duration', kwargs={'token': encrypted_str}
        )

    @mock.patch('juloserver.balance_consolidation.services.upload_document')
    @mock.patch('juloserver.balance_consolidation.services.get_local_file')
    def test_submit_balance_consolidation(self, mock_get_local_file, mock_upload_document):
        mock_get_local_file.return_value = '/tmp/abc.pdf', 'abc.pdf'
        request_data = {
            'fintech_id': 500,
            'loan_agreement_number': 'abcd123',
            'loan_principal_amount': 1000000,
            'loan_outstanding_amount': 1000000,
            'disbursement_date': '2022-10-01',
            'due_date': '2030-10-01',
            'bank_id': self.bank.pk,
            'bank_account_number': '123456789',
            'name_in_bank': 'Nguyen Van E',
            'loan_duration': 3,
            'pin': '159357',
        }
        # Test pin failed
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['errors'], ['PIN yang kamu ketik tidak sesuai'])

        # second call failed
        request_data['pin'] = '111111'
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()['errors'],
            [
                'Kamu telah 2 kali salah memasukkan informasi. 3 kali kesalahan membuat akunmu terblokir sementara waktu.'
            ],
        )

        # Test pin success
        request_data['pin'] = '123456'
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, 404)

        request_data['fintech_id'] = self.fintech.id
        document = self.create_document()
        document_file = SimpleUploadedFile(
            'document_loan_agreement.png', document, content_type='application/png'
        )
        request_data['loan_agreement_document'] = document_file
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'], ['Only accept file type: .pdf'])

        document_file.name = 'document_loan_agreement.pdf'
        document_file.content_type = 'application/pdf'
        request_data['loan_agreement_document'] = document_file
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 200)

        balance_consolidation = BalanceConsolidation.objects.get(customer=self.customer)
        self.assertEqual(
            response.data['data']['balance_consolidation_id'], balance_consolidation.id
        )
        self.assertEqual(balance_consolidation.email, 'kj.nam444@julofinance.com')
        self.assertEqual(balance_consolidation.fullname, 'Nguyen Van E')
        self.assertEqual(balance_consolidation.loan_duration, 3)
        verification = BalanceConsolidationVerification.objects.get(
            balance_consolidation=balance_consolidation
        )
        self.assertEqual(verification.validation_status, BalanceConsolidationStatus.DRAFT)
        # Draft is not considered an active submission, customer can create another submission
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, 200)

        # Bank not found
        request_data['bank_id'] = self.bank.pk + 1
        res = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(res.status_code, 400)

        request_data['bank_id'] = self.bank.pk + 1
        res = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(res.status_code, 400)

    @mock.patch('juloserver.balance_consolidation.services.upload_document')
    @mock.patch('juloserver.balance_consolidation.services.get_local_file')
    def test_submit_balance_consolidation_loan_amount(
        self, mock_get_local_file, mock_upload_document
    ):
        mock_get_local_file.return_value = '/tmp/abc.pdf', 'abc.pdf'

        document = self.create_document()
        document_file = SimpleUploadedFile(
            'document_loan_agreement.pdf', document, content_type='application/pdf'
        )
        request_data = {
            'fintech_id': self.fintech.id,
            'loan_agreement_number': 'abcd123',
            'loan_principal_amount': 1000000,
            'loan_outstanding_amount': 299999,
            'disbursement_date': '2022-10-01',
            'due_date': '2030-10-01',
            'bank_id': self.bank.pk,
            'bank_account_number': '123456789',
            'name_in_bank': 'Nguyen Van E',
            'loan_agreement_document': document_file,
            'loan_duration': 3,
            'pin': '123456',
        }
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 400)

        # loan_outstanding_amount > 20.000.000
        request_data['loan_outstanding_amount'] = 20000001
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 400)

        # loan_principal_amount > 20.000.000
        request_data['loan_outstanding_amount'] = 2000000
        request_data['loan_principal_amount'] = 20000001
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 400)

        # Success case
        request_data['loan_outstanding_amount'] = 2000000
        request_data['loan_principal_amount'] = 2000000
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 200)

    def test_get_fintechs(self):
        response = self.client.get('/api/balance-consolidation/v1/get-fintechs/')
        fintechs = response.data['data']
        self.assertEqual(response.status_code, 200)
        expected_response = [{'id': self.fintech.pk, 'name': 'Kredivo'}]
        self.assertEqual(expected_response, fintechs)

        response = self.client.get('/api/balance-consolidation/v1/get-fintechs')
        fintechs = response.data['data']
        self.assertEqual(response.status_code, 200)
        expected_response = [{'id': self.fintech.pk, 'name': 'Kredivo'}]
        self.assertEqual(expected_response, fintechs)

        response = self.client.get('/api/balance-consolidation/v1/get-fintechs/352634527')
        self.assertEqual(response.status_code, 404)

    @mock.patch('juloserver.balance_consolidation.services.get_local_file')
    def test_get_temporary_loan_agreement(self, mock_get_local_file):
        # Submit balance consolidation first
        mock_get_local_file.return_value = '/tmp/abc.pdf', 'abc.pdf'
        request_data = {
            'fintech_id': 3,
            'loan_agreement_number': 'abcd123',
            'loan_principal_amount': 1000000,
            'loan_outstanding_amount': 1000000,
            'disbursement_date': '2024-10-01',
            'due_date': '2030-10-01',
            'bank_id': self.bank.pk,
            'bank_account_number': '123456789',
            'name_in_bank': 'Nguyen Van E',
            'loan_duration': 3,
            'pin': '123456',
        }
        request_data['fintech_id'] = self.fintech.id
        document = self.create_document()
        document_file = SimpleUploadedFile(
            'document_loan_agreement.pdf', document, content_type='application/pdf'
        )
        request_data['loan_agreement_document'] = document_file
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 200)

        # Create token
        from django.conf import settings

        settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY = (
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        )
        fernet = Fernet(settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY)
        event_time = timezone.localtime(timezone.now())
        expiry_time = event_time + timedelta(days=TOKEN_EXPIRATION_DAYS)
        info_dict = {
            'customer_id': self.customer.id,
            'event_time': event_time.timestamp(),
            'expiry_time': expiry_time.timestamp(),
        }
        encrypted_str = fernet.encrypt(json.dumps(info_dict).encode()).decode()

        # Call Loan Agreement API after submit balance consolidation successfully
        balance_consolidation_id = response.data['data']['balance_consolidation_id']
        res = self.client.get(
            f'/api/balance-consolidation/v1/agreement/content/{balance_consolidation_id}/{encrypted_str}/',
        )
        self.assertIs(res.status_code, 200)

    @mock.patch('juloserver.balance_consolidation.services.get_local_file')
    def test_upload_signature_image(self, mock_get_local_file):
        # Submit balance consolidation first
        mock_get_local_file.return_value = '/tmp/abc.pdf', 'abc.pdf'
        request_data = {
            'fintech_id': 3,
            'loan_agreement_number': 'abcd123',
            'loan_principal_amount': 1000000,
            'loan_outstanding_amount': 1000000,
            'disbursement_date': '2024-10-01',
            'due_date': '2030-10-01',
            'bank_id': self.bank.pk,
            'bank_account_number': '123456789',
            'name_in_bank': 'Nguyen Van E',
            'loan_duration': 3,
            'pin': '123456',
        }
        request_data['fintech_id'] = self.fintech.id
        document = self.create_document()
        document_file = SimpleUploadedFile(
            'document_loan_agreement.pdf', document, content_type='application/pdf'
        )
        request_data['loan_agreement_document'] = document_file
        response = self.client.post(
            self.url,
            data=request_data,
            file={'loan_agreement_document': document_file},
        )
        self.assertEqual(response.status_code, 200)
        # After input the PIN, balance consolidation status is DRAFT
        balance_consolidation = BalanceConsolidation.objects.get(customer=self.customer)
        verification = BalanceConsolidationVerification.objects.get(
            balance_consolidation=balance_consolidation
        )
        self.assertEqual(verification.validation_status, BalanceConsolidationStatus.DRAFT)
        # Create token
        from django.conf import settings

        settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY = (
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        )
        fernet = Fernet(settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY)
        event_time = timezone.localtime(timezone.now())
        expiry_time = event_time + timedelta(days=TOKEN_EXPIRATION_DAYS)
        info_dict = {
            'customer_id': self.customer.id,
            'event_time': event_time.timestamp(),
            'expiry_time': expiry_time.timestamp(),
        }
        encrypted_str = fernet.encrypt(json.dumps(info_dict).encode()).decode()
        # Upload image after submit balance consolidation successfully
        balance_consolidation_id = response.data['data']['balance_consolidation_id']
        data = {
            "data": "NotEmpty",
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
        }
        res = self.client.post(
            f'/api/balance-consolidation/v1/signature/upload/{balance_consolidation_id}/{encrypted_str}/',
            data=data,
        )
        self.assertIs(res.status_code, 201)
        # After upload signature image, balance consolidation status is ON_REVIEW
        verification = BalanceConsolidationVerification.objects.get(
            balance_consolidation=balance_consolidation
        )
        self.assertEqual(verification.validation_status, BalanceConsolidationStatus.ON_REVIEW)
        # Test back to digisign after submitting balcon
        res = self.client.post(
            f'/api/balance-consolidation/v1/signature/upload/{balance_consolidation_id}/{encrypted_str}/',
            data=data,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()['errors'], ['Balance Consolidation not found'])


    @mock.patch('juloserver.loan.services.loan_related.get_loan_duration')
    def test_get_loan_duration(self, mock_get_loan_duration):
        mock_get_loan_duration.return_value = [3, 4, 5, 6]

        request_data = {}
        response = self.client.get(self.get_loan_duration_url, data=request_data)
        self.assertEqual(response.status_code, 400)

        request_data['loan_amount'] = 2000000
        response = self.client.get(self.get_loan_duration_url, data=request_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['loan_duration'], [3, 4, 5, 6])


class TestBalanceConsolidationInfoAPIView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        self.consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )

        self.bank = BankFactory(bank_name='BCA')
        self.bank_account_category = BankAccountCategoryFactory(
            category='installment', display_label='label'
        )
        self.bank_acount_destination = BankAccountDestinationFactory(
            bank=self.bank,
            customer=self.customer,
            bank_account_category=self.bank_account_category,
            name_bank_validation=self.consolidation_verification.name_bank_validation,
        )

        self.url = reverse('balance_consolidation:info_card')

    def test_get_success(self):
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data)
        data = resp.data.get('data')
        self.assertIsNotNone(data)
        self.assertIsNotNone(data['balance_consolidation'])
        self.assertIsNotNone(resp.get('x-cache-expiry'))

    def test_get_fail_because_loan_exist(self):
        self.consolidation_verification.loan = LoanFactory()
        self.consolidation_verification.save()

        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.data.get('data')
        self.assertIsNotNone(data)
        self.assertIsNone(data['balance_consolidation'])


class TestBalanceConsolidationTokenMoengage(APITestCase):
    def setUp(self):
        from django.conf import settings

        self.customers = CustomerFactory.create_batch(100)
        self.accounts = AccountFactory.create_batch(100, customer=Iterator(self.customers))
        self.applications = ApplicationFactory.create_batch(
            100, customer=Iterator(self.customers), account=Iterator(self.accounts)
        )
        self.event_type = 'balance_consolidation_submit_form_batch__2023__4__13__15'
        settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY = (
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        )
        self.fs = FeatureSettingFactory(
            feature_name=BalanceConsolidationFeatureName.BALANCE_CONS_TOKEN_CONFIG,
            is_active=True,
            parameters={'token_expiry_days': 30},
        )

    def test_generate_token_for_customers(self):
        tokens = []
        for application in self.applications:
            user_attributes, _ = construct_data_for_balance_consolidation_submit_form_id(
                application.id, self.event_type
            )
            tokens.append(user_attributes['attributes']['balance_cons_encrypted_key'])

        unique_tokens = set(tokens)
        self.assertEquals(len(tokens), len(unique_tokens))

    def test_token_expiry_time(self):
        token_obj = BalanceConsolidationToken()
        event_time, expiry_time, _ = token_obj.generate_token_balance_cons_submit(
            self.customers[0].id
        )
        expected_expiry_time = timezone.localtime(timezone.now()) + timedelta(
            days=self.fs.parameters.get('token_expiry_days')
        )
        self.assertEquals(expiry_time.date(), expected_expiry_time.date())


class TestBalanceConsolidationCustomerInfoView(APITestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        from django.conf import settings

        settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY = (
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        )
        self.fernet = Fernet(settings.BALANCE_CONS_SUBMIT_FORM_SECRET_KEY)
        self.event_time = timezone.localtime(timezone.now())
        self.expiry_time = self.event_time + timedelta(days=TOKEN_EXPIRATION_DAYS)
        info_dict = {
            'customer_id': self.customer.id,
            'event_time': self.event_time.timestamp(),
            'expiry_time': self.expiry_time.timestamp(),
        }
        self.encrypted_str = self.fernet.encrypt(json.dumps(info_dict).encode()).decode()

    def test_get_customer_success_from_balance_cons_token(self):
        response = self.client.get(
            f'/api/balance-consolidation/v1/customer-info/{self.encrypted_str}/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['customer_id'], self.customer.id)
        expiry_time_str = self.expiry_time.strftime('%d/%m/%Y %H:%M:%S %Z')
        self.assertEqual(response.data['data']['expiry_time'], expiry_time_str)

    def test_invalid_token(self):
        event_time = datetime(2023, 11, 29, 4, 15, 0)
        expiry_time = event_time + timedelta(days=TOKEN_EXPIRATION_DAYS)
        info_dict = {
            'customer_id': self.customer.id,
            'event_time': event_time.timestamp(),
            'expiry_time': expiry_time.timestamp(),
        }
        encrypted_str = self.fernet.encrypt(json.dumps(info_dict).encode()).decode()
        response = self.client.get(f'/api/balance-consolidation/v1/customer-info/{encrypted_str}/')
        self.assertEqual(response.status_code, 404)

    def test_value_error(self):
        encrypted_str = 'abcde123'
        response = self.client.get(f'/api/balance-consolidation/v1/customer-info/{encrypted_str}/')
        self.assertEqual(response.status_code, 404)

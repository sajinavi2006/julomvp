from datetime import timedelta
from mock import patch

from babel.dates import format_date

from django.conf import settings
from django.test import override_settings
from django.test.testcases import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import MagicMock

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory
)
from juloserver.employee_financing.constants import ErrorMessageConstEF
from juloserver.employee_financing.models import EmFinancingWFAccessToken
from juloserver.employee_financing.tests.factories import CompanyFactory
from juloserver.employee_financing.utils import create_or_update_token, encode_jwt_token
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    PartnerFactory,
    ApplicationFactory,
    CustomerFactory,
    AuthUserFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    MasterAgreementTemplateFactory
)


class TestEmployeeFinancingAuth(TestCase):

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def setUp(self) -> None:
        self.client = APIClient()
        self.partner = PartnerFactory()
        self.company = CompanyFactory(
            partner=self.partner,
            name='pt abc',
            email='ptabc@email.com',
            phone_number='089899998888',
            address='abc',
            company_profitable='Yes',
            centralised_deduction='Yes'
        )
        email = 'company21@email.com'
        form_type = 'application'
        expired_at = timezone.localtime(timezone.now()) + timedelta(days=30)

        self.access_token = create_or_update_token(
            email=email,
            company=self.company,
            form_type=form_type,
            expired_at=expired_at
        )
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.access_token.token)
        self.endpoint = '/api/employee-financing/pilot/auth'

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_auth_access_token_success(self) -> None:
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)

        # User clicked token
        access_token = EmFinancingWFAccessToken.objects.filter(token=self.access_token.token).last()
        self.assertEqual(access_token.is_clicked, True)

    @patch('juloserver.employee_financing.security.decode_jwt_token')
    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_auth_access_token_expired(self, token_is_not_expired: MagicMock) -> None:
        token_is_not_expired.return_value = False
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['token'], ErrorMessageConstEF.INVALID_TOKEN)

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_auth_access_token_invalid(self) -> None:
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ddsdsadasdsadasdcb12121')
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['token'], ErrorMessageConstEF.INVALID_TOKEN)


class TestSubmitWFApplicationEmployeeFinancing(TestCase):
    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def setUp(self) -> None:
        self.client = APIClient()
        self.partner = PartnerFactory()
        self.company = CompanyFactory(
            partner=self.partner,
            name='pt abc',
            email='ptabc@email.com',
            phone_number='089899998888',
            address='abc',
            company_profitable='Yes',
            centralised_deduction='Yes'
        )
        self.email = 'emailtest@email.com'
        form_type = 'application'
        expired_at = timezone.localtime(timezone.now()) + timedelta(days=30)

        self.access_token = create_or_update_token(
            email=self.email,
            company=self.company,
            form_type=form_type,
            expired_at=expired_at
        )
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.access_token.token)
        self.upload = open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb')
        self.endpoint = '/api/employee-financing/pilot/submit-application'
        self.payload = {
            'email': self.email,
            'nik': '7106031509960222',
            'phone_number': '0877815407962',
            'place_of_birth': 'Jakarta',
            'gender': 'male',
            'marriage_status': 'married',
            'mother_name': 'Test User',
            'mother_phone_number': '0877815407961',
            'couple_name': 'Test User',
            'couple_phone_number': '0877815407961',
            'expense_per_month': 0,
            'expenses_monthly_house_rent': 0,
            'debt_installments_per_month': 0,
            'ktp_image': self.upload,
            'selfie': self.upload,
        }

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_submit_form_application_success(self) -> None:
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.json()['data']['message'], 'Success submit form')
        self.access_token.refresh_from_db()
        self.assertEqual(self.access_token.is_used, True)

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_submit_form_application_failure(self) -> None:
        # required field
        self.payload['email'] = ''
        self.payload['nik'] = ''
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['email'], 'Email tidak boleh kosong')
        self.assertEqual(response.json()['errors']['nik'], 'NIK tidak boleh kosong')

        # invalid email format
        self.payload['email'] = 'asdsadasdsa'
        self.payload['nik'] = '7106031509960222'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['email'],
                         'Email data tidak valid')

        # invalid nik format
        self.payload['email'] = self.email
        self.payload['nik'] = '710603150996022sssss2'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['nik'],
                         'NIK tidak memenuhi pattern yang dibutuhkan')

        # Invalid phone number
        self.payload['nik'] = '7106031509960222'
        self.payload['phone_number'] = '909090909090909'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['phone_number'],
                         'Nomor telepon tidak valid')

        # Invalid loan amount request
        self.payload['nik'] = '7106031509960222'
        self.payload['phone_number'] = '0877815407962'
        self.payload['request_loan_amount'] = 20_000_001
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Nilai pinjaman harus lebih besar dari sama dengan 300.000 ' \
            'dan tidak boleh lebih besar dari 20.000.000'
        self.assertEqual(response.json()['errors']['request_loan_amount'], msg)

        # Invalid tenor
        self.payload['nik'] = '7106031509960222'
        self.payload['phone_number'] = '0877815407962'
        self.payload['request_loan_amount'] = 20_000_000
        self.payload['tenor'] = 10
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Tenor yang dipilih harus lebih besar dari 0 dan tidak boleh lebih besar dari 9'
        self.assertEqual(response.json()['errors']['tenor'], msg)

        # Invalid email
        self.payload['tenor'] = 7
        self.payload['email'] = 'test@email.com'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Email salah, mohon menggunakan email yang sama dengan email penerima link'
        self.assertEqual(response.json()['errors']['email'], msg)

        # Invalid emergency contact
        self.payload['email'] = self.email
        self.payload['marriage_status'] = 'not_married'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Status Pernikahan tidak valid untuk mengisi kolom ini'
        self.assertEqual(response.json()['errors']['couple_name'], msg)

        self.payload['marriage_status'] = 'married'
        self.payload['couple_name'] = 'Test User'
        self.payload['couple_phone_number'] = '90090909090909090'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Nomor telepon pasangan tidak valid'
        self.assertEqual(response.json()['errors']['couple_phone_number'], msg)

        # Photo no submit
        self.payload['couple_phone_number'] = '0877815407961'
        self.payload['ktp_image'] = ''
        self.payload['selfie'] = ''
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Mohon upload foto ktp terlebih dahulu'
        self.assertEqual(response.json()['errors']['ktp_image'], msg)

        self.payload['ktp_image'] = self.upload
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Mohon upload foto selfie terlebih dahulu'
        self.assertEqual(response.json()['errors']['selfie'], msg)

        # form already submit, token invalid
        self.payload['selfie'] = self.upload
        self.access_token.is_used = True
        self.access_token.save()
        self.access_token.refresh_from_db()
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['success'], False)
        msg = 'Token tidak valid atau token kadaluwarsa'
        self.assertEqual(response.json()['errors']['token'], msg)


class TestSubmitWFDisbursementEmployeeFinancingView(TestCase):
    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def setUp(self) -> None:
        self.client = APIClient()
        self.partner = PartnerFactory()
        self.company = CompanyFactory(
            partner=self.partner,
            name='pt abc',
            email='ptabc@email.com',
            phone_number='089899998888',
            address='abc',
            company_profitable='Yes',
            centralised_deduction='Yes'
        )
        self.email = 'emailtest@email.com'
        form_type = 'disbursement'
        expired_at = timezone.localtime(timezone.now()) + timedelta(days=30)

        self.access_token = create_or_update_token(
            email=self.email,
            company=self.company,
            form_type=form_type,
            expired_at=expired_at
        )
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.access_token.token)
        self.endpoint = '/api/employee-financing/pilot/submit-disbursement'
        self.payload = {
            'nik': '3525013006580042',
            'request_loan_amount': 1000000,
            'tenor': 3
        }

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_submit_form_disbursement_success(self) -> None:
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.json()['data']['message'], 'Success submit form')
        self.access_token.refresh_from_db()
        self.assertEqual(self.access_token.is_used, True)

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_failed_required_field(self) -> None:
        # required field
        self.payload['nik'] = ''
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['nik'], 'NIK tidak boleh kosong')

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_failed_invalid_nik(self) -> None:
        # invalid nik format
        self.payload['nik'] = '710603150996022sssss2'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors']['nik'],
                         'NIK tidak memenuhi pattern yang dibutuhkan')

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_failed_invalid_loan_amount_request(self) -> None:
        # Invalid loan amount request
        self.payload['request_loan_amount'] = 10
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Nilai pinjaman harus lebih besar dari sama dengan 300.000 ' \
            'dan tidak boleh lebih besar dari 20.000.000'
        self.assertEqual(response.json()['errors']['request_loan_amount'], msg)
    
    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_failed_invalid_tenor(self) -> None:
        # Invalid tenor
        self.payload['tenor'] = 10
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        msg = 'Tenor yang dipilih harus lebih besar dari 0 dan tidak boleh lebih besar dari 9'
        self.assertEqual(response.json()['errors']['tenor'], msg)

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_failed_form_already_submitted(self) -> None:
        # form already submit, token invalid
        self.access_token.is_used = True
        self.access_token.save()
        self.access_token.refresh_from_db()
        response = self.client.post(self.endpoint, data=self.payload)        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['success'], False)
        msg = 'Token tidak valid atau token kadaluwarsa'
        self.assertEqual(response.json()['errors']['token'], msg)


class TestValidateDOBEmployeeFinancingView(TestCase):
    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def setUp(self) -> None:
        self.client = APIClient()
        self.master_agreement =  MasterAgreementTemplateFactory(
            product_name='EF', is_active=True,
            parameters='<p>Test</p>'
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory()
        self.company = CompanyFactory(
            partner=self.partner,
            name='pt abc',
            email='ptabc@email.com',
            phone_number='089899998888',
            address='abc',
            company_profitable='Yes',
            centralised_deduction='Yes'
        )
        self.email = 'emailtest@email.com'
        form_type = 'master_agreement'

        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer,  status=active_status_code)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.EMPLOYEE_FINANCING)
        self.application = ApplicationFactory(
            company=self.company,
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999087,
            partner=self.partner,
            product_line=self.product_line
        )
        self.account_limit = AccountLimitFactory(account=self.account)

        target_expired_date = timezone.localtime(timezone.now()) + timedelta(days=30)
        expired_at = target_expired_date.replace(hour=23, minute=59, second=59)
        self.payload = {
            'application_xid': self.application.application_xid,
            'email': self.application.email,
            'dob': format_date(self.application.dob, 'ddMMyy', locale='id_ID'),
            'company': self.application.company.id,
            'exp': expired_at,
            'form_type': form_type
        }
        self.token = encode_jwt_token(self.payload)
        EmFinancingWFAccessToken.objects.create(
            token=self.token,
            email=self.application.email,
            company=self.company,
            expired_at=expired_at,
            form_type=form_type,
            limit_token_creation=0
        )
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.token)
        self.endpoint = '/api/employee-financing/pilot/validate'

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_validate_dob_success(self) -> None:
        dob = self.application.dob.strftime('%d%m%y')
        response = self.client.post(self.endpoint, data={'dob': dob})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    @override_settings(WEB_FORM_ALGORITHM_JWT_TYPE='secret-key')
    def test_validate_dob_failed(self) -> None:
        dob = self.application.dob.strftime('%d%m%y')

        # invalid dob
        response = self.client.post(self.endpoint, data={'dob': '909090'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

        # ma agreement template not found
        self.master_agreement.is_active = False
        self.master_agreement.save(update_fields=['is_active'])
        response = self.client.post(self.endpoint, data={'dob': dob})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

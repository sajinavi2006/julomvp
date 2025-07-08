import json
import time
from unittest.mock import MagicMock

from freezegun import freeze_time
import pytz
import requests
from http import HTTPStatus

import mock
import pytest
from django.db.models import signals
from django.utils import timezone
from datetime import date, timedelta, datetime
from factory import LazyAttribute
from mock.mock import patch
from rest_framework.test import APIClient, APITestCase
from juloserver.core.utils import JuloFakerProvider
from juloserver.grab.constants import (
    GRAB_REFERRAL_CASHBACK,
    GrabBankValidationStatus,
    GrabErrorMessage,
    GrabErrorCodes,
    GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE,
        GrabExperimentConst
)
from juloserver.grab.models import (
    GrabCustomerData,
    GrabReferralCode,
    GrabLoanOffer,
    GrabLoanData,
    GrabPaymentPlans,
)
from juloserver.grab.services.services import (
    update_grab_referral_code, GrabApplicationService,
    process_reset_pin_request, reset_pin_ext_date
)

from juloserver.grab.tests.factories import (
    GrabLoanDataFactory,
    GrabCustomerDataFactory,
    GrabLoanInquiryFactory,
    GrabPromoCodeFactory,
    GrabLoanOfferFactory
)
from juloserver.julo.constants import WorkflowConst, FeatureNameConst, MobileFeatureNameConst
from juloserver.julo.models import (
    Application,
    OtpRequest,
    StatusLookup,
    Payment,
    ApplicationFieldChange,
    Image,
    Customer,
    MobileFeatureSetting,
    SmsHistory
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory, AuthUserFactory, CustomerFactory, PartnerFactory,
    ProductLineFactory, StatusLookupFactory, WorkflowFactory, MobileFeatureSettingFactory,
    LoanFactory, FeatureSettingFactory, PaybackTransactionFactory, LoanHistoryFactory,
    ApplicationHistoryFactory, ProvinceLookupFactory, CityLookupFactory, DistrictLookupFactory,
    SubDistrictLookupFactory, BankFactory, ImageFactory, DocumentFactory, ProductLookupFactory,
    NameBankValidationFactory)
from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from faker import Faker
from juloserver.grab.constants import GrabWriteOffStatus

from juloserver.julo.utils import format_nexmo_voice_phone_number
from juloserver.otp.constants import FeatureSettingName
from juloserver.pin.services import CustomerPinService
from juloserver.grab.tests.factories import GrabCustomerReferralWhitelistHistoryFactory, \
    GrabReferralWhitelistProgramFactory, GrabReferralCodeFactory
from juloserver.followthemoney.factories import LenderBucketFactory
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from requests.models import Response
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import (
    NameBankValidation,
    NameBankValidationHistory
)
from juloserver.disbursement.tests.factories import (
    NameBankValidationFactory,
    BankNameValidationLogFactory
)
from juloserver.referral.signals import invalidate_cache_referee_count
from juloserver.grab.services.bank_rejection_flow import GrabChangeBankAccountService
from juloserver.grab.utils import (
    GrabUtils,
    MockValidationProcessService,
    get_grab_customer_data_anonymous_user
)
from juloserver.grab.exceptions import GrabLogicException
from rest_framework.status import HTTP_400_BAD_REQUEST
from juloserver.grab.tasks import grab_send_reset_pin_sms
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.grab.tasks import grab_send_reset_pin_sms
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.core.authentication import JWTAuthentication

fake = Faker()
fake.add_provider(JuloFakerProvider)


class TestPostGrabSubmitApplicationView(APITestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(name=PartnerConstant.GRAB_PARTNER)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application = ApplicationFactory(customer=self.customer, name_in_bank='name in bank')
        self.grab_loan_data = GrabLoanDataFactory(grab_loan_inquiry__grab_customer_data__customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)

    @patch('juloserver.grab.services.services.process_application_status_change')
    def test_submit_application_form_created(self, mock_process_application_status_change):
        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=status_lookup)
        data = {
            'fullname': "test",
            'email': 'newemail@gmail.com'
        }
        response = self.client.post('/api/partner/grab/application/submit', data=data, format='json')

        # Check expected response
        self.assertEqual(200, response.status_code, response.content)
        self.assertTrue(response.json()['data']['is_grab_application_saved'])
        self.assertIsNotNone('application_id', response.json()['data']['application_id'])
        self.assertIn('is_submitted', response.json()['data'])
        self.assertIn('missing_fields', response.json()['data'])
        self.assertIn('pre_loan_data', response.json()['data'])

        # Check expected data in DB
        self.customer.refresh_from_db()
        self.user.refresh_from_db()
        application = Application.objects.get_or_none(pk=response.json()['data']['application_id'])
        self.assertIsNotNone(application)
        self.assertEqual(self.product_line, application.product_line)
        self.assertEqual(data['email'], self.user.email)
        self.assertEqual(data['email'], self.customer.email)
        self.assertEqual(data['email'], application.email)

        # Check dependencies mock
        mock_process_application_status_change.assert_called_once_with(
            application.id,
            ApplicationStatusCodes.FORM_PARTIAL, change_reason='customer_triggered')

    @patch('juloserver.grab.services.services.trigger_application_creation_grab_api.delay')
    @patch('juloserver.grab.services.services.process_application_status_change')
    def test_uppercase_email(self, *args):
        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=status_lookup)

        expected_email = 'newemail@gmail.com'
        data = {
            'fullname': "test",
            'email': ' NewEMAIL@gmAIL.COm '
        }
        response = self.client.post('/api/partner/grab/application/submit', data=data, format='json')

        # Check expected response
        self.assertEqual(200, response.status_code, response.content)  # Check expected data in DB

        # Check expected data in DB
        self.customer.refresh_from_db()
        self.user.refresh_from_db()
        application = Application.objects.get_or_none(pk=response.json()['data']['application_id'])
        self.assertIsNotNone(application)
        self.assertEqual(expected_email, self.user.email)
        self.assertEqual(expected_email, self.customer.email)
        self.assertEqual(expected_email, application.email)

    def test_failed_submit_application_long_form_duplicate_customer_email(self):
        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=status_lookup)

        # create existing customer
        existing_user = AuthUserFactory()
        CustomerFactory(user=existing_user, email="joker@gmail.com")

        data = {
            'fullname': "test",
            'email': 'joker@gmail.com'
        }
        response = self.client.post('/api/partner/grab/application/submit', data=data, format='json')

        # Check expected response
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'Alamat email sudah terpakai')
        self.assertFalse(response.json()['success'])


    def test_failed_submit_application_long_form_duplicate_application_email(self):
        status_lookup = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.update_safely(application_status=status_lookup)

        # create existing customer and application
        draft_email="batman@gmail.com"
        existing_user = AuthUserFactory()
        existing_customer = CustomerFactory(user=existing_user, email=draft_email)
        ApplicationFactory(customer=existing_customer, name_in_bank='name in bank', email=draft_email)

        data = {
            'fullname': "test",
            'email': draft_email
        }
        response = self.client.post('/api/partner/grab/application/submit', data=data, format='json')

        # Check expected response
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'Alamat email sudah terpakai')
        self.assertFalse(response.json()['success'])


class TestGrabChangePinView(APITestCase):
    def setUp(self) -> None:
        self.grab_change_pin_url = '/api/partner/grab/change-pin'
        self.fake_pin = fake.numerify(text="#%#%#%")
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.user.refresh_from_db()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def set_pin(self):
        self.user.set_password(self.fake_pin)
        self.user.save()
        self.user.refresh_from_db()
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)

    def test_error_user_doesnt_have_pin(self):
        data = {
            'current_pin': self.fake_pin,
            'new_pin': "190762"
        }
        response = self.client.post(self.grab_change_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "User ini tidak mempunyai PIN")

    def test_error_without_current_pin(self):
        self.set_pin()
        data = {
            'new_pin': "777790"
        }
        response = self.client.post(self.grab_change_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "PIN harus diisi")

    def test_error_without_new_pin(self):
        self.set_pin()
        data = {
            'current_pin': self.fake_pin
        }
        response = self.client.post(self.grab_change_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "PIN baru harus diisi")

    def test_error_invalid_current_pin(self):
        self.set_pin()
        data = {
            'current_pin': "9999999",
            "new_pin": "999999"
        }
        response = self.client.post(self.grab_change_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "PIN tidak sesuai silahkan coba lagi")

    def test_error_same_new_pin(self):
        self.set_pin()
        data = {
            'current_pin': self.fake_pin,
            'new_pin': self.fake_pin
        }
        response = self.client.post(self.grab_change_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Pastikan PIN Baru Kamu tidak sama dengan PIN lama")

    def test_success_change_pin(self):
        self.set_pin()
        data = {
            'current_pin': self.fake_pin,
            'new_pin': "090891"
        }
        response = self.client.post(self.grab_change_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("data").get("updated_status"), True)


class TestGrabVerifyPinView(APITestCase):
    def setUp(self) -> None:
        self.verify_pin_url = '/api/partner/grab/verify-pin'
        self.fake_pin = fake.numerify(text="#%#%#%")
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        self.user.refresh_from_db()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def set_pin(self):
        self.user.set_password(self.fake_pin)
        self.user.save()
        self.user.refresh_from_db()
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)

    def test_error_user_doesnt_have_pin(self):
        data = {
            'pin': self.fake_pin,
        }
        response = self.client.post(self.verify_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "User ini tidak mempunyai PIN")

    def test_error_without_pin(self):
        self.set_pin()
        data = {
            'not_pin': "777790"
        }
        response = self.client.post(self.verify_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "PIN harus diisi")

    def test_error_verify_pin(self):
        self.set_pin()
        data = {
            "pin": "999999"
        }
        # first call
        response = self.client.post(self.verify_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "PIN yang kamu ketik tidak sesuai")

        # second call
        response = self.client.post(self.verify_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Kamu telah 2 kali salah memasukkan informasi. 3 kali kesalahan membuat akunmu terblokir sementara waktu.")

        # third call getting locked
        response = self.client.post(self.verify_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.FORBIDDEN, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Akun kamu diblokir sementara selama 1 Jam karena salah memasukkan informasi. Silakan coba masuk kembali nanti.")

    def test_success_verify_pin(self):
        self.set_pin()
        data = {
            'pin': self.fake_pin,
        }
        response = self.client.post(self.verify_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("data").get("verified_status"), True)


class TestGrabForgotPinView(APITestCase):
    def setUp(self) -> None:
        self.grab_forgot_pin_url = '/api/partner/grab/forgot_pin'
        self.fake_pin = fake.numerify(text="#%#%#%")
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.set_password(self.fake_pin)
        self.user.save()
        self.user.refresh_from_db()
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)
        self.customer = CustomerFactory(user=self.user, phone='6289998881111')
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.reset_pin_key = 'test key'
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.LUPA_PIN,
            is_active=True,
            parameters={
                "request_count": 4,
                "request_time": {"days": 0, "hours": 24, "minutes": 0},
                "pin_users_link_exp_time": {"days": 0, "hours": 24, "minutes": 0},
            },
        )

    def test_error_email_required(self):
        data = {
            "email": self.user.email
        }
        response = self.client.post(self.grab_forgot_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Email Harus Diisi")

    def test_email_invalid(self):
        self.user.email = fake.random_email()
        self.user.save()
        data = {
            "email": "bambang@gmail.com"
        }
        response = self.client.post(self.grab_forgot_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("data"), "A PIN reset email will be sent if the email is registered")

    def test_success_forgot_pin(self):
        self.user.email = fake.random_email()
        self.user.save()
        data = {
            "email": self.user.email
        }
        response = self.client.post(self.grab_forgot_pin_url, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("data"), "A PIN reset email will be sent if the email is registered")

    @mock.patch(
        'juloserver.grab.services.services.grab_send_reset_pin_sms.delay')
    @patch('django.utils.timezone.now')
    @patch('juloserver.grab.services.services.generate_email_key')
    def test_process_reset_pin_request(
            self,
            mock_mail_pin_request,
            mock_localtime,
            mock_grab_send_reset_pin_sms
    ):

        JAKARTA_TZ = pytz.timezone("Asia/Jakarta")
        current_time = datetime.now(JAKARTA_TZ)
        mock_localtime.return_value = current_time
        mock_mail_pin_request.return_value = self.reset_pin_key
        exp_time = current_time + timedelta(hours=24)
        self.customer.reset_password_key = self.reset_pin_key
        self.customer.save()
        self.customer.refresh_from_db()
        process_reset_pin_request(self.customer)
        self.assertEquals(self.customer.reset_password_exp_date, exp_time)
        mock_grab_send_reset_pin_sms.assert_called()

        self.customer.reset_password_exp_date = reset_pin_ext_date()
        self.customer.save()
        self.customer.refresh_from_db()
        process_reset_pin_request(self.customer)
        self.assertEquals(self.customer.reset_password_exp_date, exp_time)
        mock_grab_send_reset_pin_sms.assert_called()

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    def test_grab_send_reset_pin_sms(
            self,
            mock_send_sms
    ):

        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'nexmo',
                 'status': '0',
                 'message-id': '123'
                 }
            ]}
        )
        grab_send_reset_pin_sms(self.customer, self.customer.phone, self.reset_pin_key)
        self.assertTrue(SmsHistory.objects.filter(message_id='123',
                                                  customer=self.customer,
                                                  template_code='grab_reset_pin_by_sms'
                                                  ).exists())


class TestGrabChangePhoneNumberView(APITestCase):
    def setUp(self) -> None:
        self.grab_change_phone_number_url = '/api/partner/grab/change_phone/change_phone_number'
        self.fake_pin = fake.numerify(text="#%#%#%")
        self.user = AuthUserFactory()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.set_password(self.fake_pin)
        self.user.save()
        self.user.refresh_from_db()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.grab_customer_data = GrabCustomerData.objects.create(
            customer=self.customer,
            phone_number=format_nexmo_voice_phone_number(self.random_plus_62_phone_number())
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory(feature_name='mobile_phone_1_otp')
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.product_line,
            workflow=self.workflow
        )

    def random_plus_62_phone_number(self):
        return f'+62{fake.numerify(text="#%#%#%#%#%")}'

    def random_62_phone_number(self):
        return f'62{fake.numerify(text="#%#%#%#%#%")}'

    def test_error_old_phone_number_with_invalid_country_code(self):
        data = {
            "old_phone_number": '+7085225443889',
            "new_phone_number": self.random_plus_62_phone_number()
        }
        response = self.client.post(self.grab_change_phone_number_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Mohon isi nomor HP lama dengan format 628xxxxxxxx")

    def test_error_new_phone_number_with_invalid_country_code(self):
        data = {
            "old_phone_number": self.random_plus_62_phone_number(),
            "new_phone_number": '+7085225443880'
        }
        response = self.client.post(self.grab_change_phone_number_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Mohon isi nomor HP baru dengan format 628xxxxxxxx")

    @pytest.mark.skip(reason="Flaky")
    def test_error_new_phone_number_already_registered(self):
        data = {
            "old_phone_number": self.grab_customer_data.phone_number,
            "new_phone_number": self.random_62_phone_number()
        }
        GrabCustomerData.objects.create(
            customer=self.customer,
            phone_number=data.get("new_phone_number"),
            grab_validation_status=True
        )
        response = self.client.post(self.grab_change_phone_number_url, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json().get("errors")[0], "Customer Already registered with new_phone_number")

    def test_success_update_with_plus_62_country_code(self):
        data = {
            "old_phone_number": self.grab_customer_data.phone_number,
            "new_phone_number": self.random_plus_62_phone_number()
        }
        old_phone_number_otp_req = OtpRequest.objects.create(
            customer=self.customer,
            phone_number=data.get("old_phone_number"),
            is_used=True,
            cdate=timezone.localtime(timezone.now()) + timedelta(minutes=10)
        )
        new_phone_number_otp_req = OtpRequest.objects.create(
            customer=self.customer,
            phone_number=format_nexmo_voice_phone_number(data.get("new_phone_number")),
            is_used=True,
            cdate=timezone.localtime(timezone.now()) + timedelta(minutes=10)
        )
        response = self.client.post(self.grab_change_phone_number_url, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(True, response.json()['data']['update_customer'])


class TestGrabAccountSummary(APITestCase):
    def setUp(self) -> None:
        self.grab_account_summary_url = '/api/partner/grab/account_summary'
        self.client = APIClient()
        self.deduction_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            parameters={
                "schedule": ["01:00", "04:00", "07:00", "09:00", "10:00", "12:00",
                             "14:00", "16:00", "18:00", "22:00"],
                "complete_rollover": False
            },
            is_active=False
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            partner=self.partner,
            account=self.account,
            workflow=self.workflow,
            application_xid=LazyAttribute(lambda o: fake.random_int(
                10000000, 20000000))
        )
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account
        )
        self.customer_2 = CustomerFactory()
        self.account_2 = AccountFactory(
            customer=self.customer_2,
            account_lookup=self.account_lookup
        )
        self.application_2 = ApplicationFactory(
            customer=self.customer_2,
            partner=self.partner,
            account=self.account_2,
            workflow=self.workflow
        )
        self.loan_2 = LoanFactory(
            customer=self.customer_2,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account_2
        )
        self.loan_3 = LoanFactory(
            customer=self.customer_2,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account_2
        )
        self.loan_4 = LoanFactory(
            customer=self.customer_2,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account_2
        )
        self.loan_5 = LoanFactory(
            customer=self.customer_2,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account_2
        )
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.grab_loan_data_2 = GrabLoanDataFactory(loan=self.loan_2)
        self.grab_loan_data_3 = GrabLoanDataFactory(loan=self.loan_3)
        self.grab_loan_data_4 = GrabLoanDataFactory(loan=self.loan_4)
        self.grab_loan_data_5 = GrabLoanDataFactory(loan=self.loan_5)
        self.write_off_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_WRITE_OFF, is_active=True)
        self.write_off_feature_setting.parameters = {
            "early_write_off": True,
            "manual_write_off": True,
            "180_dpd_write_off": True
        }
        self.write_off_feature_setting.save()

    def test_account_summary_loan_xid(self) -> None:
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)

        data = {"loan_xid": 0}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 400)
        response_content = json.loads(response.content)
        self.assertTrue('Grab Application not found for loan xid' in response_content['errors'][0])

    def test_account_summary_offset_limit(self) -> None:
        data = {"offset": 0, 'limit': 5}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 5)

    def test_account_summary_application_xid(self) -> None:
        data = {"application_xid": self.application.application_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)

        data = {"application_xid": 0}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 400)
        response_content = json.loads(response.content)
        self.assertTrue('Grab Application not found for application xid' in response_content['errors'][0])

    def test_feature_setting_active(self) -> None:
        self.deduction_feature_setting.is_active = True
        self.deduction_feature_setting.parameters['complete_rollover'] = True
        self.deduction_feature_setting.save()
        data = {"offset": 0, 'limit': 5}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 5)

    def test_account_summary_early_write_off_failed(self) -> None:
        self.loan.loan_xid = 1000097141
        self.loan.save()
        self.write_off_feature_setting.is_active = True
        self.write_off_feature_setting.parameters['early_write_off'] = True
        self.write_off_feature_setting.save()
        self.grab_loan_data.is_early_write_off = False
        self.grab_loan_data.save()
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertNotEqual(
            response_content['data']['rows'][0]['loan_status_id'], GrabWriteOffStatus.EARLY_WRITE_OFF)

    def test_account_summary_early_write_off_success(self) -> None:
        self.loan.loan_xid = 1000097141
        self.loan.save()
        self.grab_loan_data.is_early_write_off = True
        self.grab_loan_data.save()
        self.write_off_feature_setting.is_active = True
        self.write_off_feature_setting.parameters['early_write_off'] = True
        self.write_off_feature_setting.save()
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['loan_status_id'], GrabWriteOffStatus.EARLY_WRITE_OFF)

    def test_account_summary_early_write_off_feature_off(self) -> None:
        self.loan.loan_xid = 1000097141
        self.loan.save()
        self.grab_loan_data.is_early_write_off = True
        self.grab_loan_data.save()
        self.write_off_feature_setting.is_active = False
        self.write_off_feature_setting.parameters['early_write_off'] = True
        self.write_off_feature_setting.save()
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertNotEqual(
            response_content['data']['rows'][0]['loan_status_id'], GrabWriteOffStatus.EARLY_WRITE_OFF)

    def test_account_summary_180dpd_write_off_feature_on(self) -> None:
        self.loan.loan_xid = 1000097141
        self.loan.loan_status = StatusLookupFactory(
            status_code=StatusLookup.LOAN_180DPD_CODE)
        self.loan.save()
        payments = self.loan.payment_set.all().order_by('id')
        for idx, payment in enumerate(payments):
            payment.due_date = date.today() - timedelta(days=181) + timedelta(days=idx)
            payment.due_amount = self.loan.installment_amount
            payment.save()

        self.grab_loan_data.is_early_write_off = False
        self.grab_loan_data.save()
        self.loan_history = LoanHistoryFactory(
            loan=self.loan, status_old=236, status_new=237)
        self.write_off_feature_setting.is_active = True
        self.write_off_feature_setting.parameters["180_dpd_write_off"] = True
        self.write_off_feature_setting.save()
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['loan_status_id'], GrabWriteOffStatus.WRITE_OFF_180_DPD)

        payments = self.loan.payment_set.all().order_by('id')
        for idx, payment in enumerate(payments):
            payment.due_date = date.today() - timedelta(days=180) + timedelta(days=idx)
            payment.due_amount = self.loan.installment_amount
            payment.save()

        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['loan_status_id'], '180dpd')

    def test_account_summary_180dpd_write_off_feature_off(self) -> None:
        self.loan.loan_xid = 1000097141
        self.loan.loan_status = StatusLookupFactory(
            status_code=StatusLookup.LOAN_180DPD_CODE)
        self.loan.save()
        self.grab_loan_data.is_early_write_off = False
        self.grab_loan_data.save()
        self.loan_history = LoanHistoryFactory(
            loan=self.loan, status_old=236, status_new=237)
        self.write_off_feature_setting.is_active = True
        self.write_off_feature_setting.parameters["180_dpd_write_off"] = False
        self.write_off_feature_setting.save()
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertNotEqual(
            response_content['data']['rows'][0]['loan_status_id'], GrabWriteOffStatus.WRITE_OFF_180_DPD)
        self.assertEqual(response_content['data']['rows'][0]['loan_status_id'], '180dpd')

    def test_restructure_program_loan_xid(self):
        self.deduction_feature_setting.is_active = True
        self.deduction_feature_setting.parameters['complete_rollover'] = True
        self.deduction_feature_setting.save()
        self.loan.loan_xid = 1000097145
        self.loan.save()
        self.grab_loan_data.is_repayment_capped = False
        self.grab_loan_data.save()
        data = {"loan_xid": self.loan.loan_xid}
        payments = self.loan.payment_set.all().order_by('id')
        for idx, payment in enumerate(payments):
            payment.due_date = date.today() - timedelta(days=3) + timedelta(days=idx)
            payment.due_amount = self.loan.installment_amount
            if idx < 3:
                payment.payment_status = StatusLookupFactory(
                    status_code=StatusLookup.PAYMENT_5DPD_CODE)
            payment.save()
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['total_due_amount'], (self.loan.installment_amount*4))

        self.grab_loan_data.is_repayment_capped = True
        self.grab_loan_data.save()
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['total_due_amount'], self.loan.installment_amount)

    def test_restructure_program_loan_xid_partial_payments(self) -> None:
        self.deduction_feature_setting.is_active = True
        self.deduction_feature_setting.parameters['complete_rollover'] = True
        self.deduction_feature_setting.save()
        self.loan.loan_xid = 1000097145
        self.loan.save()
        self.grab_loan_data.is_repayment_capped = True
        self.grab_loan_data.save()
        data = {"loan_xid": self.loan.loan_xid}
        payments = self.loan.payment_set.all().order_by('id')
        for idx, payment in enumerate(payments):
            payment.due_date = date.today() - timedelta(days=3) + timedelta(days=idx)
            payment.due_amount = self.loan.installment_amount
            if idx < 3:
                payment.payment_status = StatusLookupFactory(
                    status_code=StatusLookup.PAYMENT_5DPD_CODE)
            payment.save()
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['total_due_amount'], self.loan.installment_amount)

        payback_transaction_1 = PaybackTransactionFactory(
            customer=self.customer,
            loan=self.loan,
            transaction_date=datetime.today(),
            payment=payments[0],
            account=self.account,
            amount=20000,
            is_processed=True,
            payback_service='grab'
        )
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['total_due_amount'], self.loan.installment_amount - 20000)

        payback_transaction_2 = PaybackTransactionFactory(
            customer=self.customer,
            loan=self.loan,
            transaction_date=datetime.today(),
            payment=payments[0],
            account=self.account,
            amount=15000,
            is_processed=True,
            payback_service='grab'
        )
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['total_due_amount'], self.loan.installment_amount - 35000)

        payback_transaction_3 = PaybackTransactionFactory(
            customer=self.customer,
            loan=self.loan,
            transaction_date=datetime.today(),
            payment=payments[0],
            account=self.account,
            amount=15000,
            is_processed=True,
            payback_service='grab'
        )
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, 200)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(
            response_content['data']['rows'][0]['total_due_amount'], 0)

    def test_success_account_summary_loan_invalidated(self) -> None:
        self.loan.loan_xid = 1000097142
        loan_status = StatusLookupFactory(status_code=LoanStatusCodes.LOAN_INVALIDATED)
        self.loan.update_safely(loan_status=loan_status)
        self.loan.save()
        data = {"loan_xid": self.loan.loan_xid}
        response = self.client.get(self.grab_account_summary_url, data=data)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['count'], 1)
        self.assertEqual(response_content['data']['rows'][0]['loan_status_id'],"Invalid")


class TestGrabAccountPageView(APITestCase):
    def setUp(self) -> None:
        self.grab_account_page_url = '/api/partner/grab/account-page'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.paid_off_loan_status = StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        self.cancelled_loan_status = StatusLookupFactory(status_code=StatusLookup.CANCELLED_BY_CUSTOMER)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            account=self.account
        )
        self.bank = BankFactory(bank_name="test", is_active=True)
        self.application = ApplicationFactory(
            workflow=self.workflow,
            bank_name=self.bank.bank_name,
            bank_account_number='121212223'
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         'Invalid token header. No credentials provided.')
        self.assertEqual(response_content['data'], None)

    def test_success_account_page_with_referral_disabled(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        self.application.customer = self.customer
        self.application.save()
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], True)
        self.assertEqual(response_content['data']['nik'], self.customer.nik)
        self.assertEqual(response_content['data']['email'], self.customer.email)
        self.assertEqual(response_content['data']['phone'], self.customer.phone)
        self.assertEqual(response_content['data']['referral_enabled'], False)

    def test_success_account_page_with_referral_disabled_v2(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        self.application.customer = self.customer
        self.application.save()
        self.loan.update_safely(loan_status=self.paid_off_loan_status)
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], True)
        self.assertEqual(response_content['data']['nik'], self.customer.nik)
        self.assertEqual(response_content['data']['email'], self.customer.email)
        self.assertEqual(response_content['data']['phone'], self.customer.phone)
        self.assertEqual(response_content['data']['referral_enabled'], False)

    def test_success_account_page_with_referral_disabled_v3(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        self.application.customer = self.customer
        self.application.save()
        self.loan.update_safely(loan_status=self.cancelled_loan_status)
        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], True)
        self.assertEqual(response_content['data']['nik'], self.customer.nik)
        self.assertEqual(response_content['data']['email'], self.customer.email)
        self.assertEqual(response_content['data']['phone'], self.customer.phone)
        self.assertEqual(response_content['data']['referral_enabled'], False)

    def test_success_account_page_with_referral_enabled(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        self.application.customer = self.customer
        self.application.save()
        self.loan.update_safely(loan_status=self.paid_off_loan_status)
        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], True)
        self.assertEqual(response_content['data']['nik'], self.customer.nik)
        self.assertEqual(response_content['data']['email'], self.customer.email)
        self.assertEqual(response_content['data']['phone'], self.customer.phone)
        self.assertEqual(response_content['data']['referral_enabled'], True)

    def test_failed_with_no_grab_customer_data(self):
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         GrabUtils.create_error_message(
                             GrabErrorCodes.GAP_ERROR_CODE.format('1'),
                             GrabErrorMessage.PROFILE_PAGE_GENERAL_ERROR_MESSAGE))
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_application(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         GrabUtils.create_error_message(
                             GrabErrorCodes.GAP_ERROR_CODE.format('2'),
                             GrabErrorMessage.PROFILE_PAGE_GENERAL_ERROR_MESSAGE))
        self.assertEqual(response_content['data'], None)

    def test_success_with_bank_details(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        self.application.customer = self.customer
        self.application.save()
        response = self.client.get(self.grab_account_page_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['data']['nik'], self.customer.nik)
        self.assertEqual(response_content['data']['email'], self.customer.email)
        self.assertEqual(response_content['data']['phone'], self.customer.phone)
        self.assertEqual(response_content['data']['bank_logo'],
                         None)
        self.assertEqual(response_content['data']['bank_account_number'],
                         self.application.bank_account_number)


class TestGrabReferralInfoView(APITestCase):
    def setUp(self) -> None:
        signals.post_save.disconnect(invalidate_cache_referee_count, sender=Application)
        self.grab_generate_referral_code_url = '/api/partner/grab/referral-info'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.customer.update_safely(self_referral_code='PROD87RN')
        self.paid_off_loan_status = StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            account=self.account
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_REFERRAL_PROGRAM,
            parameters={
                "max incentivised referral/whitelist": "10",
                "referrer_incentive": 50000,
                "referred_incentive": 20000
            }
        )

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         'Invalid token header. No credentials provided.')
        self.assertEqual(response_content['data'], None)

    def test_failed_generate_referral_code(self):
        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         'customer not eligible to generate referral code')
        self.assertEqual(response_content['data'], None)

    def test_success_generate_referral_code(self):
        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        self.loan.update_safely(loan_status=self.paid_off_loan_status)
        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(response_content['data']['total_cashback'], 0)

    def test_success_get_referral_cashback(self):
        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        self.loan.update_safely(loan_status=self.paid_off_loan_status)
        approved_status_lookup = StatusLookupFactory(status_code=190)
        customer_referred = CustomerFactory()
        account_referred = AccountFactory()
        application_referred = ApplicationFactory(
            referral_code="PROD87RN",
            account=account_referred,
            customer=customer_referred,
            application_status=StatusLookupFactory(status_code=190)
        )
        ApplicationHistoryFactory(
            application_id=application_referred.id,
            status_new=105,
            cdate=timezone.localtime(timezone.now())
        )
        GrabReferralCodeFactory(
            referred_customer=self.customer,
            application=application_referred,
            referral_code="PROD87RN",
            cdate=timezone.localtime(timezone.now())
        )
        LoanFactory(
            account=account_referred,
            loan_status=StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        )
        application_referred.application_status = approved_status_lookup
        application_referred.save()
        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(
            response_content['data']['total_cashback'],
            self.feature_setting.parameters.get("referrer_incentive")
        )
        self.assertIsNotNone(response_content['data']['campaign_start_time'])
        self.assertIsNotNone(response_content['data']['max_limit_current_whitelist'])

    def test_success_get_referral_cashback_old_whitelist(self):
        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        grab_customer_whitelist = GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        grab_customer_whitelist.start_time = timezone.localtime(timezone.now() -
                                                                timedelta(minutes=90))
        grab_customer_whitelist.save()
        self.loan.update_safely(loan_status=self.paid_off_loan_status)

        StatusLookupFactory(status_code=190)
        customer_referred = CustomerFactory()
        account_referred = AccountFactory()
        application_referred = ApplicationFactory(
            referral_code="PROD87RN",
            account=account_referred,
            customer=customer_referred
        )
        application_referred.application_status = StatusLookupFactory(status_code=190)
        application_referred.save()
        ah = ApplicationHistoryFactory(
            application_id=application_referred.id,
            status_new=105
        )
        ah.cdate = timezone.localtime(timezone.now() - timedelta(days=20))
        ah.save()
        grab_referral_code = GrabReferralCodeFactory(
            referred_customer=self.customer,
            application=application_referred,
            referral_code="PROD87RN",
        )
        grab_referral_code.cdate = timezone.localtime(timezone.now() - timedelta(days=20))
        grab_referral_code.save()
        LoanFactory(
            account=account_referred,
            loan_status=StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        )
        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(response_content['data']['total_cashback'], 0)
        self.assertIsNotNone(response_content['data']['campaign_start_time'])
        self.assertIsNotNone(response_content['data']['max_limit_current_whitelist'])

    def test_success_get_referral_cashback_max_feature_setting(self):
        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        grab_customer_whitelist = GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        self.feature_setting.parameters = {
            "max incentivised referral/whitelist": "2",
            "referrer_incentive": 50000,
            "referred_incentive": 20000
        }
        self.feature_setting.save()
        grab_customer_whitelist.start_time = timezone.localtime(timezone.now() -
                                                                timedelta(minutes=90))
        grab_customer_whitelist.save()
        self.loan.update_safely(loan_status=self.paid_off_loan_status)

        # Application 1
        customer_referred = CustomerFactory()
        account_referred = AccountFactory()
        application_referred = ApplicationFactory(
            referral_code="PROD87RN",
            account=account_referred,
            customer=customer_referred
        )
        application_referred.application_status = StatusLookupFactory(status_code=190)
        application_referred.save()
        ah = ApplicationHistoryFactory(
            application_id=application_referred.id,
            status_new=105
        )
        ah.cdate = timezone.localtime(timezone.now())
        ah.save()
        GrabReferralCodeFactory(
            referred_customer=self.customer,
            application=application_referred,
            referral_code="PROD87RN"
        )
        LoanFactory(
            account=account_referred,
            loan_status=StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        )

        # Application 2
        customer_referred_2 = CustomerFactory()
        account_referred_2 = AccountFactory()
        application_referred_2 = ApplicationFactory(
            referral_code="PROD87RN",
            account=account_referred_2,
            customer=customer_referred_2
        )
        application_referred_2.application_status = StatusLookupFactory(status_code=190)
        application_referred_2.save()
        ah = ApplicationHistoryFactory(
            application_id=application_referred_2.id,
            status_new=105
        )
        ah.cdate = timezone.localtime(timezone.now())
        ah.save()
        GrabReferralCodeFactory(
            referred_customer=self.customer,
            application=application_referred_2,
            referral_code="PROD87RN"
        )
        LoanFactory(
            account=account_referred_2,
            loan_status=StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        )

        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(
            response_content['data']['total_cashback'],
            self.feature_setting.parameters.get("referrer_incentive") * 2
        )
        self.assertIsNotNone(response_content['data']['campaign_start_time'])
        self.assertIsNotNone(response_content['data']['max_limit_current_whitelist'])

        # Application 3
        customer_referred_3 = CustomerFactory()
        account_referred_3 = AccountFactory()
        application_referred_3 = ApplicationFactory(
            referral_code="PROD87RN",
            account=account_referred_3,
            customer=customer_referred_3
        )
        application_referred_3.application_status = StatusLookupFactory(status_code=190)
        application_referred_3.save()
        ah = ApplicationHistoryFactory(
            application_id=application_referred_3.id,
            status_new=105
        )
        ah.cdate = timezone.localtime(timezone.now())
        ah.save()
        GrabReferralCodeFactory(
            referred_customer=self.customer,
            application=application_referred_3,
            referral_code="PROD87RN"
        )
        LoanFactory(
            account=account_referred_3,
            loan_status=StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        )

        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(response_content['data']['total_cashback'],
                         self.feature_setting.parameters.get("referrer_incentive") * 2)
        self.assertIsNotNone(response_content['data']['campaign_start_time'])
        self.assertIsNotNone(response_content['data']['max_limit_current_whitelist'])

        self.feature_setting.parameters = {
            "max incentivised referral/whitelist": "10",
            "referrer_incentive": 50000,
            "referred_incentive": 20000
        }
        self.feature_setting.save()

        response = self.client.get(self.grab_generate_referral_code_url)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(response_content['data']['total_cashback'],
                         self.feature_setting.parameters.get("referrer_incentive") * 3)
        self.assertIsNotNone(response_content['data']['campaign_start_time'])
        self.assertIsNotNone(response_content['data']['max_limit_current_whitelist'])

    def test_grab_referral_code_update(self):
        referral_code = 'SOMEOTHERREFERRAL'
        customer = CustomerFactory(
            self_referral_code='SOMEREFFERALCODE'
        )
        application = ApplicationFactory()
        GrabReferralCodeFactory(
            application=application,
            referred_customer=customer,
            referral_code=referral_code
        )
        update_grab_referral_code(application, referral_code)
        self.assertTrue(
            GrabReferralCode.objects.filter(
                application=application,
                referred_customer=customer,
                referral_code=referral_code).exists())

    def test_grab_referral_code_create(self):
        referral_code = 'SOMEREFFERALCODE'
        customer = CustomerFactory(
            self_referral_code='SOMEREFFERALCODE'
        )
        application = ApplicationFactory()
        update_grab_referral_code(application, referral_code)
        self.assertTrue(
            GrabReferralCode.objects.filter(
                application=application,
                referred_customer=customer,
                referral_code=referral_code).exists())


class TestGrabReferralValidateView(APITestCase):
    def setUp(self) -> None:
        self.grab_validate_referral_code_url = '/api/partner/grab/application/validate_referral_code'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.paid_off_loan_status = StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            account=self.account
        )
        self.grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        self.grab_customer_whitelist = GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=self.grab_whitelist_program,
            customer=self.customer
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.get(self.grab_validate_referral_code_url, data={'referral_code': 'BAMBANG'})
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         'Invalid token header. No credentials provided.')
        self.assertEqual(response_content['data'], None)

    def test_failed_generate_referral_code(self):
        response = self.client.get(self.grab_validate_referral_code_url, data={'referral_code': 'BAMBANG'})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], True)
        self.assertEqual(response_content['data']['validation_status'], False)
        self.assertEqual(
            response_content['data']['error_message'],
            'Kode referral tidak terdaftar. Silakan '
            'masukkan kode referral lainnya.'
        )

    def test_success_validate_referral_code(self):
        self.loan.update_safely(loan_status=self.paid_off_loan_status)
        self.customer.self_referral_code = "BAMBANG"
        self.customer.save()

        grab_whitelist_program = GrabReferralWhitelistProgramFactory()
        GrabCustomerReferralWhitelistHistoryFactory(
            grab_referral_whitelist_program=grab_whitelist_program,
            customer=self.customer
        )
        response = self.client.get(self.grab_validate_referral_code_url, data={'referral_code': 'BAMBANG'})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(response_content['data']['validation_status'], True)

    def test_success_get_referral_cashback(self):
        self.loan.update_safely(loan_status=self.paid_off_loan_status)
        self.customer.self_referral_code = "BAMBANG"
        self.customer.save()

        approved_status_lookup = StatusLookupFactory(status_code=190)
        application_referred = ApplicationFactory(referral_code="BAMBANG")
        application_referred.application_status = approved_status_lookup
        application_referred.save()
        response = self.client.get(self.grab_validate_referral_code_url,
                                   data={'referral_code': 'BAMBANG'})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.customer.refresh_from_db()
        self.assertEqual(response_content['data']['referral_code'],
                         self.customer.self_referral_code)
        self.assertEqual(response_content['data']['validation_status'], True)


class TestGrabNewDisbursementFlow(APITestCase):
    def setUp(self) -> None:
        self.grab_validate_referral_code_url = '/api/followthemoney/v1/create_bucket/'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow, name=GRAB_ACCOUNT_LOOKUP_NAME)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            account=self.account
        )

    @patch('juloserver.followthemoney.services.get_redis_client')
    @mock.patch('juloserver.followthemoney.views.j1_views.grab_disbursement_trigger_task')
    @mock.patch('juloserver.followthemoney.views.j1_views.generate_summary_lender_loan_agreement')
    def test_api_view(self, mocked_lender, mocked_disbursement, _mock_get_redis_client):
        _mock_get_redis_client.return_value = MockRedisHelper()
        data = {
            "application_ids": {
                "approved": [self.loan.id],
                "rejected": []
            }
        }
        mocked_lender.delay.return_value = None
        mocked_disbursement.delay.return_value = None

        response = self.client.post(self.grab_validate_referral_code_url, data=data, format='json')
        mocked_lender.delay.assert_called()
        mocked_disbursement.delay.assert_called()
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.followthemoney.services.get_redis_client')
    @mock.patch('juloserver.followthemoney.views.j1_views.update_loan_status_and_loan_history')
    def test_api_rejected(self, mocked_loan_status_update, _mock_get_redis_client):
        _mock_get_redis_client.return_value = MockRedisHelper()
        data = {
            "application_ids": {
                "approved": [],
                "rejected": [self.loan.id]
            }
        }
        self.lender_bucket = LenderBucketFactory(partner=self.partner, is_active=False)
        mocked_loan_status_update.return_value = None
        response = self.client.post(self.grab_validate_referral_code_url, data=data, format='json')
        mocked_loan_status_update.assert_called()
        self.assertEqual(response.status_code, 200)


class TestApplicationLongFormUpdated(APITestCase):
    def setUp(self) -> None:
        self.grab_application_form = '/api/partner/grab/application/form'
        self.grab_province = '/api/partner/grab/address/provinces'
        self.grab_city = '/api/partner/grab/address/cities'
        self.grab_district = '/api/partner/grab/address/districts'
        self.grab_subdistricts = '/api/partner/grab/address/subdistricts'
        self.grab_address_info = '/api/partner/grab/address/info'
        self.grab_verify_bank = '/api/partner/grab/application/verify-grab-bank-account'
        self.grab_submit_api = '/api/partner/grab/application/v2/submit'
        self.grab_populate = '/api/partner/grab/application/form/load'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        self.status_form_created = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=self.status_form_created,
            product_line=self.product_line,
            workflow=self.workflow
        )
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        province = ProvinceLookupFactory(province='Jawa Barat')
        city = CityLookupFactory(city='Bogor', province=province)
        district = DistrictLookupFactory(district='Parung Panjang', city=city)
        SubDistrictLookupFactory(sub_district='Kabasiran', zipcode='12345', district=district)

    def test_application_form_page_1(self):
        query_param = {
            'page': 1
        }
        response = self.client.get(self.grab_application_form, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(json.loads(response.content)['data'])

    def test_application_form_page_2(self):
        query_param = {
            'page': 2
        }
        response = self.client.get(self.grab_application_form, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(json.loads(response.content)['data'])

    def test_application_form_page_3(self):
        query_param = {
            'page': 3
        }
        response = self.client.get(self.grab_application_form, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(json.loads(response.content)['data'])

    def test_application_form_page_invalid(self):
        query_param = {
            'page': 4
        }
        response = self.client.get(self.grab_application_form, data=query_param)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(json.loads(response.content)['success'])

    def test_application_address_province_success(self):
        response = self.client.get(self.grab_province)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(json.loads(response.content)['data']), 0)

    def test_application_address_city_success(self):
        query_param = {
            'province': 'Jawa Barat'
        }
        response = self.client.get(self.grab_city, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(json.loads(response.content)['data']), 0)

    def test_application_address_city_failed(self):
        query_param = {
            'province': 'Jawa Timur123'
        }
        response = self.client.get(self.grab_city, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)['data']), 0)

    def test_application_address_district_success(self):
        query_param = {
            'province': 'Jawa Barat',
            'city': 'Bogor'
        }
        response = self.client.get(self.grab_district, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(json.loads(response.content)['data']), 0)

    def test_application_address_district_failed(self):
        query_param = {
            'province': 'Jawa Barat12',
            'city': 'Bogor'
        }
        response = self.client.get(self.grab_district, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)['data']), 0)

    def test_application_address_subdistrict_success(self):
        query_param = {
            'province': 'Jawa Barat',
            'city': 'Bogor',
            'district': 'Parung Panjang'
        }
        response = self.client.get(self.grab_subdistricts, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(json.loads(response.content)['data']), 0)

    def test_application_address_subdistrict_failed(self):
        query_param = {
            'province': 'Jawa Barat123',
            'city': 'Bogor',
            'district': 'Parung Panjang'
        }
        response = self.client.get(self.grab_subdistricts, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(json.loads(response.content)['data']), 0)

    def test_address_info_success(self):
        query_param = {
            'subdistrict': 'Kabasiran',
            'zipcode': '12345'
        }
        response = self.client.get(self.grab_address_info, data=query_param)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['data']['province'], 'Jawa Barat')
        self.assertEqual(json.loads(response.content)['data']['city'], 'Bogor')
        self.assertEqual(json.loads(response.content)['data']['district'], 'Parung Panjang')
        self.assertEqual(json.loads(response.content)['data']['subDistrict'], 'Kabasiran')
        self.assertEqual(json.loads(response.content)['data']['zipcode'], '12345')

    @mock.patch('juloserver.grab.services.services.update_loan_status_for_grab_invalid_bank_account')
    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_success_bank_verification(self, mocked_client, mocked_cancel_loan):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        mocked_cancel_loan.return_value = None
        response = Response()
        response.status_code = 200
        response.url = self.grab_verify_bank
        response._content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {
                "msg_id": "30a4c02637674cde8477d1f832a7386f",
                "code": False,
                "reason": None
                }
        })
        data = {
            'bank_name': 'bank_name',
            'bank_account_number': '12345678910'
        }
        mocked_client.return_value = response
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        mocked_client.assert_called()
        self.assertIsNotNone(response)
        mocked_cancel_loan.assert_called()
        self.assertTrue(json.loads(response.content)['data']['bank_name_validation'])

    @mock.patch('juloserver.grab.services.services.update_loan_status_for_grab_invalid_bank_account')
    @mock.patch('juloserver.grab.clients.clients.GrabClient.get_pre_disbursal_check')
    def test_failed_bank_verification_predisbursal_error(self, mocked_client, mocked_cancel_loan):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        mocked_cancel_loan.return_value = None

        response = Response()
        response.status_code = 400
        response.url = self.grab_verify_bank
        response._content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": False, "error": {"error_code": 4001, "dev_message": ""},
            "data": {
                "msg_id": "30a4c02637674cde8477d1f832a7386f",
                "code": True,
                "reason": None
                }
        })
        data = {
            'bank_name': 'bank_name',
            'bank_account_number': '12345678910'
        }
        mocked_client.return_value = response
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        mocked_client.assert_called()
        self.assertIsNotNone(response)
        mocked_cancel_loan.assert_not_called()
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_submit_updation_api_failure_no_data(self):
        status_190 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.application_status = status_190
        self.application.save()
        data = {
            'step': '1'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertGreater(len(response_data['errors'].keys()), 0)

    def test_submit_updation_api_success(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sampleemail@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['data']['is_allowed_application'])

    def test_submit_updation_api_failure_1(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)

    def test_submit_updation_api_fullname_regex_failure_1(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky.adrian',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_submit_updation_api_fullname_regex_failure_2(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky-adrian',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_submit_updation_api_fullname_regex_failure_3(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky âdrian',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_submit_updation_api_fullname_regex_failure_4(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky édrian',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_submit_updation_api_failure_status(self):
        status_190 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.application_status = status_190
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sampleemail@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 403)
        response_data = json.loads(response.content)
        self.assertIsNone(response_data.get('data'))

    def test_submit_updation_api_failure_step_mismatch(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '2',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertGreater(len(response_data['errors'].keys()), 0)

    def test_submit_updation_api_failure_email_validation_fail1(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sample_email",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertGreater(len(response_data['errors'].keys()), 0)

    def test_submit_updation_api_failure_email_validation_fail2(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sample_email@julof",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertGreater(len(response_data['errors'].keys()), 0)

    def test_submit_updation_api_success_step_2(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '2',
            'close_kin_mobile_phone': '0886713723',
            'kin_name': 'testtt',
            'kin_relationship': 'Orang tua',
            'close_kin_name': 'testt',
            'kin_mobile_phone': '0812376132',
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['data']['is_allowed_application'])

    def test_submit_updation_api_success_step_3(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            'step': '3',
            'monthly_income': '150000042',
            'bank_name': 'BANK MANDIRI (PERSERO), Tbk',
            'referral_code': None,
            'bank_account_number': '1212121212',
            'loan_purpose': 'Kebutuhan sehari-hari',
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['data']['is_allowed_application'])

    def test_populate_application_field_api_test(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.monthly_income = None
        self.application.kin_name = None
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sampleemail@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        image_1 = ImageFactory(image_source=self.application.id, image_type='ktp_self')
        image_2 = ImageFactory(image_source=self.application.id, image_type='selfie')
        self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '1'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 2)

        data['email'] = None
        self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '1'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 2)

        data = {
            'step': '2',
            'close_kin_mobile_phone': '0886713723',
            'kin_name': 'testtt',
            'kin_relationship': 'Orang tua',
            'close_kin_name': 'testt',
            'kin_mobile_phone': '0812376132',
        }
        self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '2'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 3)

        data = {
            'step': '3',
            'monthly_income': '150000042',
            'bank_name': 'BANK MANDIRI (PERSERO), Tbk',
            'referral_code': None,
            'bank_account_number': '1212121212',
            'loan_purpose': 'Kebutuhan sehari-hari',
        }
        response = self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '3'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 4)

    def test_populate_application_field_api_test_email_success_1(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.monthly_income = None
        self.application.kin_name = None
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        image_1 = ImageFactory(image_source=self.application.id, image_type='ktp_self')
        image_2 = ImageFactory(image_source=self.application.id, image_type='selfie')
        self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '1'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 2)

    def test_populate_application_field_api_test_email_failure(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.monthly_income = None
        self.application.kin_name = None
        self.application.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': ".sample_email@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        image_1 = ImageFactory(image_source=self.application.id, image_type='ktp_self')
        image_2 = ImageFactory(image_source=self.application.id, image_type='selfie')
        self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '1'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 1)

    def test_populate_application_field_phone_api_test(self):
        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.monthly_income = None
        self.application.kin_name = None
        self.application.save()
        self.application.customer.phone = '628032143254'
        self.application.customer.save()
        data = {
            'step': '1',
            'address': 'address street number',
            'address_province': 'DKI Jakarta',
            'address_regency': 'Jakarta Barat',
            'address_district': 'Kebon Jeruk',
            'address_subdistrict': 'Kebon Jeruk',
            'address_zipcode': '11531',
            'fullname': 'lucky',
            'email': "sampleemail@example.com",
            'primary_phone_number': '62812874533030',
            'secondary_phone_number': '62813459884524',
            'dob': '1996-02-22',
            'gender': 'Pria',
            'last_education': 'SLTA',
            'marital_status': 'Lajang',
            'total_dependent': '3'
        }
        image_1 = ImageFactory(image_source=self.application.id, image_type='ktp_self')
        image_2 = ImageFactory(image_source=self.application.id, image_type='selfie')
        self.client.patch(self.grab_submit_api, data=data, format='json')
        response = self.client.get(self.grab_populate, data={'step': '1'})
        self.assertEqual(int(json.loads(response.content)['data']['current_step']), 2)
        self.assertEqual(json.loads(response.content)['data']['primary_phone_number'], '08032143254')

    def test_failed_submit_application_long_form_duplicate_customer_email(self):
        # create existing customer
        dup_email = "joker@gmail.com"
        existing_user = AuthUserFactory()
        CustomerFactory(user=existing_user, email=dup_email)

        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            "fullname":"PROD ONLY",
            "dob":"1995-04-06",
            "gender":"Pria",
            "marital_status":"Menikah",
            "close_kin_name":"bambang",
            "close_kin_mobile_phone":"085225443009",
            "kin_relationship":"Saudara kandung",
            "kin_name":"Lidia",
            "kin_mobile_phone":"087663884990",
            "last_education":"S1",
            "bank_name":"BANK BCA SYARIAH",
            "bank_account_number":"121212121212",
            "loan_purpose":"Kebutuhan sehari-hari",
            "email":dup_email,
            "monthly_income":20000000,
            "nik":"3216070308940002",
            "address_zipcode":"17520",
            "address_province":"Jawa Barat",
            "address_regency":"Kab. Bekasi",
            "address_district":"Cibitung",
            "address_subdistrict":"Wanasari",
            "total_dependent":1,
            "primary_phone_number":"081914321881",
            "address":"bekasi",
            "secondary_phone_number":"",
            "referral_code":""
        }
        response = self.client.post(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        response_data = json.loads(response.content)
        self.assertIsNone(response_data['data'])
        self.assertEqual(response_data['errors'][0], 'Alamat email sudah terpakai')
        self.assertFalse(response_data['success'])

    def test_failed_submit_application_long_form_duplicate_application_email(self):
        # create existing customer
        dup_email = "joker@gmail.com"
        existing_user = AuthUserFactory()
        existing_customer = CustomerFactory(user=existing_user, email=dup_email)
        ApplicationFactory(customer=existing_customer, name_in_bank='name in bank', email=dup_email)

        status_100 = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.application_status = status_100
        self.application.save()
        data = {
            "fullname":"PROD ONLY",
            "dob":"1995-04-06",
            "gender":"Pria",
            "marital_status":"Menikah",
            "close_kin_name":"bambang",
            "close_kin_mobile_phone":"085225443009",
            "kin_relationship":"Saudara kandung",
            "kin_name":"Lidia",
            "kin_mobile_phone":"087663884990",
            "last_education":"S1",
            "bank_name":"BANK BCA SYARIAH",
            "bank_account_number":"121212121212",
            "loan_purpose":"Kebutuhan sehari-hari",
            "email":dup_email,
            "monthly_income":20000000,
            "nik":"3216070308940002",
            "address_zipcode":"17520",
            "address_province":"Jawa Barat",
            "address_regency":"Kab. Bekasi",
            "address_district":"Cibitung",
            "address_subdistrict":"Wanasari",
            "total_dependent":1,
            "primary_phone_number":"081914321881",
            "address":"bekasi",
            "secondary_phone_number":"",
            "referral_code":""
        }
        response = self.client.post(self.grab_submit_api, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        response_data = json.loads(response.content)
        self.assertIsNone(response_data['data'])
        self.assertEqual(response_data['errors'][0], 'Alamat email sudah terpakai')
        self.assertFalse(response_data['success'])

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    @mock.patch('juloserver.grab.services.services.update_loan_status_for_grab_invalid_bank_account')
    def test_failed_bank_verification_invalid_bank_account_number(self, mocked_cancel_loan, mocked_client):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        data = {
            'bank_name': 'bank_name',
            'bank_account_number': '1234 5678 910 abc'
        }
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        self.assertIsNotNone(response)
        self.assertEqual(response.data.get('errors')[0],
                         GrabUtils.create_error_message(
                             GrabErrorCodes.GAX_ERROR_CODE.format('6'),
                             GrabErrorMessage.BANK_VALIDATION_INCORRECT_ACCOUNT_NUMBER
                         ))
        mocked_cancel_loan.assert_not_called()
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        response = Response()
        response.status_code = 200
        response.url = self.grab_verify_bank
        response._content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {
                "msg_id": "30a4c02637674cde8477d1f832a7386f",
                "code": False,
                "reason": None
            }
        })
        mocked_client.return_value = response
        data = {
            'bank_name': 'bank_name',
            'bank_account_number': '4443'
        }
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        self.assertIsNotNone(response)
        mocked_client.assert_called()
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @mock.patch('juloserver.grab.services.services.update_loan_status_for_grab_invalid_bank_account')
    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_success_bank_verification_auto_remove_whitespace(self, mocked_client, mocked_cancel_loan):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        mocked_cancel_loan.return_value = None
        response = Response()
        response.status_code = 200
        response.url = self.grab_verify_bank
        response._content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {
                "msg_id": "30a4c02637674cde8477d1f832a7386f",
                "code": False,
                "reason": None
                }
        })
        data = {
            'bank_name': 'bank_name',
            'bank_account_number': '1234 5678 910 '
        }
        mocked_client.return_value = response
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        mocked_client.assert_called()
        self.assertIsNotNone(response)
        mocked_cancel_loan.assert_called()
        self.assertTrue(json.loads(response.content)['data']['bank_name_validation'])

    def test_fail_bank_account_verify_for_no_grab_customer_data(self):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        response = Response()
        response.status_code = HTTPStatus.BAD_REQUEST
        response.url = self.grab_verify_bank
        self.grab_customer_data.grab_validation_status = False
        self.grab_customer_data.save(update_fields=['grab_validation_status'])
        data = {
            'bank_name': self.bank.bank_name,
            'bank_account_number': '12345678910'
        }
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        response_data = json.loads(response.content)
        self.assertIsNone(response_data['data'])
        self.assertEqual(response_data['errors'][0], GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)
        self.assertFalse(response_data['success'])

    def test_fail_bank_account_verify_for_incorrect_bank(self):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        response = Response()
        response.status_code = HTTPStatus.BAD_REQUEST
        response.url = self.grab_verify_bank
        data = {
            'bank_name': 'fsdfsdf',
            'bank_account_number': '12345678910'
        }
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        response_data = json.loads(response.content)
        self.assertIsNone(response_data['data'])
        self.assertEqual(response_data['errors'][0], GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)
        self.assertFalse(response_data['success'])

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_fail_bank_account_verify_with_data_not_in_response(self, mocked_client):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        response = Response()
        response.status_code = HTTPStatus.BAD_REQUEST
        response.url = self.grab_verify_bank
        response._content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": False, "error": {"error_code": 4001, "dev_message": ""},

        })
        data = {
            'bank_name': self.bank.bank_name,
            'bank_account_number': '12345678910'
        }
        mocked_client.return_value = response
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        response_data = json.loads(response.content)
        mocked_client.assert_called()
        self.assertEqual(response_data['errors'][0], GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)
        self.assertFalse(response_data['success'])

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_fail_bank_account_verify_with_code_in_response(self, mocked_client):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        response = Response()
        response.status_code = HTTPStatus.BAD_REQUEST
        response.url = self.grab_verify_bank
        response._content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": False, "error": {"error_code": 4001, "dev_message": ""},
            "data": {
                "msg_id": "30a4c02637674cde8477d1f832a7386f",
                "code": True,
                "reason": None
            }
        })
        data = {
            'bank_name': self.bank.bank_name,
            'bank_account_number': '12345678910'
        }
        mocked_client.return_value = response
        response = self.client.post(self.grab_verify_bank, data=data, format='json')
        response_data = json.loads(response.content)
        mocked_client.assert_called()
        self.assertEqual(response_data['errors'][0], GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)
        self.assertFalse(response_data['success'])


class TestLinkAPIView(APITestCase):
    def setUp(self) -> None:
        self.grab_link_url = '/api/partner/grab/link'
        self.user = AuthUserFactory()
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.mobile_phone = '628112345687'
        self.nik = '1601260506021284'
        self.customer = CustomerFactory(phone=self.mobile_phone, nik=self.nik, user=self.user)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(account_lookup=self.account_lookup)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.ctl_product_line = ProductLineFactory(product_line_code=ProductLineCodes.CTL1)
        self.application_status_code = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            workflow=self.workflow
        )
        GrabCustomerDataFactory(customer=self.customer)

    def test_link_api_failed_blank(self):
        data = {"phone_number": ""}
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_link_api_failed_null(self):
        data = {"phone_number": None}
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_link_api_failed_regex_test_1(self):
        data = {"phone_number": "628"}
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_link_api_failed_regex_test_2(self):
        data = {"phone_number": "62"}
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_link_api_failed_regex_test_3(self):
        data = {"phone_number": "628012345687"}
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    @mock.patch('juloserver.grab.services.services.GrabAuthService.request_otp')
    @mock.patch('juloserver.grab.services.services.GrabClient.check_account_on_grab_side')
    def test_link_api_failed_regex_test_4(self, mocked_link, mocked_otp):
        data = {"phone_number": "628112345687"}
        return_value = {
            "msg_id": "59d59468e0894f6ea7fa9b64683b81e1",
            "success": True,
            "version": "1.0", "data": ""
        }
        mocked_link.return_value = return_value
        mocked_otp.return_value = {
            "request_id": 123
        }
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 200)

    def test_link_api_failed_do_to_invalid_customer_phone(self):
        data = {"phone_number": self.mobile_phone}
        self.application.mobile_phone_1 = self.mobile_phone
        self.application.save()
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)
        phone = '628112347787'
        data = {"phone_number": phone}
        self.application.mobile_phone_1 = phone
        self.application.product_line = self.ctl_product_line
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        self.application.save()
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    @mock.patch('juloserver.grab.services.services.GrabAuthService.request_otp')
    @mock.patch('juloserver.grab.services.services.GrabClient.check_account_on_grab_side')
    def test_link_api_success_with_valid_customer_phone(self, mocked_link, mocked_otp):
        data = {"phone_number": "628112345687"}
        return_value = {
            "msg_id": "59d59468e0894f6ea7fa9b64683b81e1",
            "success": True,
            "version": "1.0", "data": ""
        }
        mocked_link.return_value = return_value
        mocked_otp.return_value = {
            "request_id": 123
        }
        self.application.product_line = self.ctl_product_line
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        )
        self.application.save()
        response = self.client.post(self.grab_link_url, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        response_json = response.json()
        self.assertTrue('jwt_token' in response_json["data"])
        self.assertFalse('grab_customer_data_id' in response_json["data"])


class TestGrabLoanOfferView(APITestCase):
    def random_plus_62_phone_number(self):
        return f'+62{fake.numerify(text="#%#%#%#%#%")}'

    def setUp(self) -> None:
        self.grab_loan_offer_url = '/api/partner/grab/loan_offer/'
        self.fake_pin = fake.numerify(text="#%#%#%")


class TestGrabChangeBankAccountView(APITestCase):
    def setUp(self) -> None:
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.initialize_url = '/api/partner/grab/change-bank-account/'
        self.status_url = '/api/partner/grab/change-bank-account/status'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.phone_number = "628456812565"
        self.customer = CustomerFactory(
            user=self.user,
            phone=self.phone_number
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
            phone_number=self.phone_number
        )
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.bank_name = "test_bank_name"
        self.bank_code = "BCA"
        self.bank = BankFactory(
            bank_code=self.bank_code,
            bank_name=self.bank_name,
            is_active=True,
            swift_bank_code="ABSWIFTCD",
            xfers_bank_code=self.bank_code
        )

        self.bank_account_number = '1212122231'
        self.application = ApplicationFactory(
            workflow=self.workflow,
            bank_name=self.bank.bank_name,
            bank_account_number=self.bank_account_number,
            customer=self.customer,
            account=self.account,
            name_in_bank=self.customer.fullname
        )
        self.bank_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )

        self.old_name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=123,
            name_in_bank=self.customer.fullname,
            method="xfers",
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=123
        )
        self.application.name_bank_validation = self.old_name_bank_validation
        self.application.bank_account_number = self.old_name_bank_validation.account_number

        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.validation_id = 1234
        self.method = 'Xfers'
        self.name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=self.bank_account_number,
            name_in_bank=self.customer.fullname,
            method=self.method,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=self.validation_id
        )

        self.bank_name_validation_log = BankNameValidationLogFactory(
            validation_id=self.validation_id,
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name=self.customer.fullname,
            account_number=self.bank_account_number,
            method=self.method,
            application=self.application,
            reason="",
        )

    @patch('juloserver.disbursement.services.get_service')
    def test_change_bank_account_success(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        data = {
            "bank_account_number": self.bank_account_number,
            "bank_name": self.bank_name,
            "application_id": self.application.id
        }

        response = self.client.post(
            self.initialize_url, data=data, format='json')

        # check name bank validation
        name_bank_validation_id = response.json()['data']['name_bank_validation_id']
        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=name_bank_validation_id
        )
        self.assertEqual(name_bank_validation_obj.validation_id, '1234')
        self.assertTrue(name_bank_validation_obj is not None)
        self.assertEqual(name_bank_validation_obj.validation_status,
                         NameBankValidationStatus.SUCCESS)
        self.assertEqual(name_bank_validation_obj.name_in_bank, self.customer.fullname)

        # check the history
        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        # check the response
        self.assertEqual(response.json()['data']['validation_status'],
                         GrabBankValidationStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @patch('juloserver.disbursement.services.get_service')
    def test_sucess_change_bank_account_with_status_190(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        data = {
            "bank_account_number": self.bank_account_number,
            "bank_name": self.bank_name,
            "application_id": self.application.id
        }

        response = self.client.post(
            self.initialize_url, data=data, format='json')

        # check name bank validation
        name_bank_validation_id = response.json()['data']['name_bank_validation_id']
        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=name_bank_validation_id
        )
        self.assertEqual(name_bank_validation_obj.validation_id, '1234')
        self.assertTrue(name_bank_validation_obj is not None)
        self.assertEqual(name_bank_validation_obj.validation_status,
                         NameBankValidationStatus.SUCCESS)
        self.assertEqual(name_bank_validation_obj.name_in_bank, self.customer.fullname)

        # check the history
        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        # check the response
        self.assertEqual(response.json()['data']['validation_status'],
                         GrabBankValidationStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @patch('juloserver.disbursement.services.get_service')
    def test_failed_change_bank_account_with_applicaton_status_190_has_active_loan(
        self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        loan_status = StatusLookupFactory(status_code=StatusLookup.LENDER_APPROVAL)
        product_line = ProductLineFactory()
        LoanFactory(
            customer=self.customer,
            product=ProductLookupFactory(product_line=product_line, late_fee_pct=0.05),
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=loan_status,
            account=self.account,
            application=self.application
        )

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        data = {
            "bank_account_number": self.bank_account_number,
            "bank_name": self.bank_name,
            "application_id": self.application.id
        }

        response = self.client.post(
            self.initialize_url, data=data, format='json')

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.disbursement.services.get_service')
    def test_change_bank_account_invalid_app(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.ACTIVATION_CALL_FAILED
        )
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )

        mock_get_service.return_value = mock_service

        for application_id in [self.application.id, 1]:
            data = {
                "bank_account_number": self.bank_account_number,
                "bank_name": self.bank_name,
                "application_id": application_id
            }

            response = self.client.post(
                self.initialize_url, data=data, format='json')

            self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_change_bank_account_invalid_request_payload(self):
        data_tests = [
            {
                "bank_account_number": None,
                "bank_name": self.bank_name,
                "application_id": self.application.id
            },
            {
                "bank_account_number": "",
                "bank_name": self.bank_name,
                "application_id": self.application.id
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": None,
                "application_id": self.application.id
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": "",
                "application_id": self.application.id
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": self.bank_name,
                "application_id": ""
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": self.bank_name,
                "application_id": None
            },
        ]
        for data in data_tests:
            response = self.client.post(
                self.initialize_url, data=data, format='json')
            self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch("juloserver.grab.views.trigger_create_or_update_ayoconnect_beneficiary.delay")
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_success(self, mock_get_service,
                                                    mock_create_update_beneficiary):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        self.assertEqual(self.application.name_bank_validation, self.old_name_bank_validation)
        self.assertNotEqual(self.application.bank_account_number, self.bank_account_number)
        old_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()
        self.assertEqual(old_count_of_application_field_change, 0)

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        # verify the application data related to bank is updated
        data = response.json()
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(data["data"]["validation_status"], NameBankValidationStatus.SUCCESS)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_bank_validation, self.name_bank_validation)
        self.assertEqual(self.application.bank_account_number, self.bank_account_number)

        # verify the ApplicationFieldChange is created
        new_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()

        self.assertEqual(new_count_of_application_field_change, 3)

        mock_create_update_beneficiary.assert_not_called()

    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_invalid_app_status(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.NOT_YET_CREATED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_app_not_owned_by_the_owner(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        unknow_app = ApplicationFactory()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(unknow_app.id))

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_app_not_grab(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        workflow = WorkflowFactory(name="test workflow")
        self.application.workflow = workflow
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.get_name_bank_validation_status')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_failed_get_name_bank_validation_status(
        self, mock_get_service, mock_get_name_bank_validation_status):
        mock_get_name_bank_validation_status.side_effect = GrabLogicException(
            GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                "test error"))

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertTrue("test error" in response.json()["errors"][0])
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.create_new_bank_destination')
    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.update_bank_application')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_in_progress(
        self, mock_get_service, mock_update_bank_application, mock_create_new_bank_destination):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        self.name_bank_validation.validation_status = NameBankValidationStatus.INITIATED
        self.name_bank_validation.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertEqual(response.json()['data']['validation_status'],
                         GrabBankValidationStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        mock_update_bank_application.assert_not_called()
        mock_create_new_bank_destination.assert_not_called()

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.update_bank_application')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_failed_update_bank_application(
        self, mock_get_service, mock_update_bank_application):
        mock_update_bank_application.side_effect = GrabLogicException(
            GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                "test error"))

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertTrue("test error" in response.json()["errors"][0])
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.create_new_bank_destination')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_failed_create_new_bank_destination(
        self, mock_get_service, mock_create_new_bank_destination):
        mock_create_new_bank_destination.side_effect = GrabLogicException(
            GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                "test error"))

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertTrue("test error" in response.json()["errors"][0])
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch("juloserver.grab.views.trigger_create_or_update_ayoconnect_beneficiary.delay")
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_success_190(self, mock_get_service,
                                                        mock_create_update_beneficiary):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        self.assertEqual(self.application.name_bank_validation, self.old_name_bank_validation)
        self.assertNotEqual(self.application.bank_account_number, self.bank_account_number)
        old_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()

        self.assertEqual(old_count_of_application_field_change, 0)

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        # verify the application data related to bank is updated
        data = response.json()

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(data["data"]["validation_status"], NameBankValidationStatus.SUCCESS)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_bank_validation, self.name_bank_validation)
        self.assertEqual(self.application.bank_account_number, self.bank_account_number)

        # verify the ApplicationFieldChange is created
        new_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()

        self.assertEqual(new_count_of_application_field_change, 3)

        mock_create_update_beneficiary.assert_called()


class TestAgreementLetterView(APITestCase):
    def random_plus_62_phone_number(self):
        return f'+62{fake.numerify(text="#%#%#%#%#%")}'

    def setUp(self):
        self.grab_agreement_letter = '/api/partner/grab/loan/agreement_letter'
        self.user = AuthUserFactory()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.grab_loan_offer_url = '/api/partner/grab/loan_offer/'
        self.fake_pin = fake.numerify(text="#%#%#%")
        self.user.set_password(self.fake_pin)
        self.user.save()
        self.user.refresh_from_db()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=self.user.auth_expiry_token.key)
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.phone_number = format_nexmo_voice_phone_number(self.random_plus_62_phone_number())
        self.grab_customer_data = GrabCustomerData.objects.create(
            customer=self.customer,
            phone_number=self.phone_number,
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED,
            token=self.user.auth_expiry_token.key
        )

    @mock.patch('juloserver.grab.services.services.GrabLoanService.save_grab_loan_offer_to_redis')
    @mock.patch('juloserver.grab.services.services.GrabClient.get_loan_offer')
    def test_sucsess_get_loan_offer(self, mock_get_loan_offer, mock_save_grab_loan_offer_to_redis):
        mock_get_loan_offer.return_value = {
            "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
            "success": True, "version": "1",
            "data": [
                {
                    "program_id": "DAX_ID_CL02",
                    "max_loan_amount": "1000000",
                    "min_loan_amount": "500000",
                    "weekly_installment_amount":"1000000",
                    "loan_duration": 180,
                    "min_tenure": 60,
                    "tenure_interval": 30,
                    "frequency_type": "DAILY",
                    "fee_type": "FLAT",
                    "fee_value": "40000",
                    "interest_type": "SIMPLE_INTEREST",
                    "interest_value": "3",
                    "penalty_type": "FLAT",
                    "penalty_value": "2000000"
                },
                {
                    "program_id": "DAX_ID_CL03",
                    "max_loan_amount": "1500000",
                    "min_loan_amount": "500000",
                    "weekly_installment_amount":"1000000",
                    "loan_duration": 180,
                    "min_tenure": 60,
                    "tenure_interval": 30,
                    "frequency_type": "DAILY",
                    "fee_type": "FLAT",
                    "fee_value": "40000",
                    "interest_type": "SIMPLE_INTEREST",
                    "interest_value": "3",
                    "penalty_type": "FLAT",
                    "penalty_value": "2000000"
                }
            ]
        }

        with mock.patch("juloserver.grab.services.services.get_redis_client") as \
            mock_get_redis_client:
            mock_get_redis_client.return_value = mock.Mock()

            resp = self.client.get(
                self.grab_loan_offer_url + "?phone_number={}".format(self.phone_number))
            self.assertEqual(resp.status_code, HTTPStatus.OK)
            grab_loan_offers = GrabLoanOffer.objects.filter(
                grab_customer_data=self.grab_customer_data
            )
            self.assertEqual(len(grab_loan_offers), 1)
            mock_save_grab_loan_offer_to_redis.assert_called()
            self.assertEqual(grab_loan_offers[0].program_id, "DAX_ID_CL03")

    @mock.patch('juloserver.grab.services.services.GrabLoanService.save_grab_loan_offer_to_redis')
    @mock.patch('juloserver.grab.services.services.GrabClient.get_loan_offer')
    def test_sucess_get_loan_offer_updated(self, mock_get_loan_offer,
                                           mock_save_grab_loan_offer_to_redis):
        grab_loan_offer_data = {
            "program_id": "DAX_ID_CL02",
            "max_loan_amount": "1000000",
            "min_loan_amount": "500000",
            "loan_duration": 180,
            "min_tenure": 60,
            "tenure_interval": 30,
            "frequency_type": "DAILY",
            "fee_type": "FLAT",
            "fee_value": "40000",
            "interest_type": "SIMPLE_INTEREST",
            "interest_value": "3",
            "penalty_type": "FLAT",
            "penalty_value": "2000000"
        }

        grab_loan_offer_data.update({
            "grab_customer_data": self.grab_customer_data,
            "tenure": grab_loan_offer_data["loan_duration"]
        })
        del grab_loan_offer_data["loan_duration"]
        GrabLoanOffer.objects.create(**grab_loan_offer_data)

        grab_loan_offer_data.update({
            "loan_duration": grab_loan_offer_data["tenure"]
        })
        self.assertEqual(GrabLoanOffer.objects.get(
            grab_customer_data=self.grab_customer_data
        ).max_loan_amount, 1000000)


        grab_loan_offer_data.update({
            "max_loan_amount": "2000000",
            "weekly_installment_amount":"1000000",
        })

        for field in ["grab_customer_data", "tenure"]:
            del grab_loan_offer_data[field]

        mock_get_loan_offer.return_value = {
            "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
            "success": True, "version": "1",
            "data": [grab_loan_offer_data]
        }

        with mock.patch("juloserver.grab.services.services.get_redis_client") as \
            mock_get_redis_client:
            mock_get_redis_client.return_value = mock.Mock()

            resp = self.client.get(
                self.grab_loan_offer_url + "?phone_number={}".format(self.phone_number))

            self.assertEqual(resp.status_code, HTTPStatus.OK)
            self.assertEqual(GrabLoanOffer.objects.get(
                grab_customer_data=self.grab_customer_data
            ).max_loan_amount, 2000000)
            mock_save_grab_loan_offer_to_redis.assert_called()


class TestGrabChangeBankAccountView(APITestCase):
    def setUp(self) -> None:
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.initialize_url = '/api/partner/grab/change-bank-account/'
        self.status_url = '/api/partner/grab/change-bank-account/status'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.phone_number = "628456812565"
        self.customer = CustomerFactory(
            user=self.user,
            phone=self.phone_number
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
            phone_number=self.phone_number
        )
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )

        self.bank_name = "test_bank_name"
        self.bank_code = "BCA"
        self.bank = BankFactory(
            bank_code=self.bank_code,
            bank_name=self.bank_name,
            is_active=True,
            swift_bank_code="ABSWIFTCD",
            xfers_bank_code=self.bank_code
        )

        self.bank_account_number = '1212122231'
        self.application = ApplicationFactory(
            workflow=self.workflow,
            bank_name=self.bank.bank_name,
            bank_account_number=self.bank_account_number,
            customer=self.customer,
            account=self.account,
            name_in_bank=self.customer.fullname
        )
        self.bank_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )

        self.old_name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=123,
            name_in_bank=self.customer.fullname,
            method="xfers",
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=123
        )
        self.application.name_bank_validation = self.old_name_bank_validation
        self.application.bank_account_number = self.old_name_bank_validation.account_number

        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.validation_id = 1234
        self.method = 'Xfers'
        self.name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=self.bank_account_number,
            name_in_bank=self.customer.fullname,
            method=self.method,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=self.validation_id
        )

        self.bank_name_validation_log = BankNameValidationLogFactory(
            validation_id=self.validation_id,
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name=self.customer.fullname,
            account_number=self.bank_account_number,
            method=self.method,
            application=self.application,
            reason="",
        )

    @patch('juloserver.disbursement.services.get_service')
    def test_change_bank_account_success(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        data = {
            "bank_account_number": self.bank_account_number,
            "bank_name": self.bank_name,
            "application_id": self.application.id
        }

        response = self.client.post(
            self.initialize_url, data=data, format='json')

        # check name bank validation
        name_bank_validation_id = response.json()['data']['name_bank_validation_id']
        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=name_bank_validation_id
        )
        self.assertEqual(name_bank_validation_obj.validation_id, '1234')
        self.assertTrue(name_bank_validation_obj is not None)
        self.assertEqual(name_bank_validation_obj.validation_status,
                         NameBankValidationStatus.SUCCESS)
        self.assertEqual(name_bank_validation_obj.name_in_bank, self.customer.fullname)

        # check the history
        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        # check the response
        self.assertEqual(response.json()['data']['validation_status'],
                         GrabBankValidationStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @patch('juloserver.disbursement.services.get_service')
    def test_sucess_change_bank_account_with_status_190(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        data = {
            "bank_account_number": self.bank_account_number,
            "bank_name": self.bank_name,
            "application_id": self.application.id
        }

        response = self.client.post(
            self.initialize_url, data=data, format='json')

        # check name bank validation
        name_bank_validation_id = response.json()['data']['name_bank_validation_id']
        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=name_bank_validation_id
        )
        self.assertEqual(name_bank_validation_obj.validation_id, '1234')
        self.assertTrue(name_bank_validation_obj is not None)
        self.assertEqual(name_bank_validation_obj.validation_status,
                         NameBankValidationStatus.SUCCESS)
        self.assertEqual(name_bank_validation_obj.name_in_bank, self.customer.fullname)

        # check the history
        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        # check the response
        self.assertEqual(response.json()['data']['validation_status'],
                         GrabBankValidationStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @patch('juloserver.disbursement.services.get_service')
    def test_failed_change_bank_account_with_applicaton_status_190_has_active_loan(
        self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        loan_status = StatusLookupFactory(status_code=StatusLookup.LENDER_APPROVAL)
        product_line = ProductLineFactory()
        LoanFactory(
            customer=self.customer,
            product=ProductLookupFactory(product_line=product_line, late_fee_pct=0.05),
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() - timedelta(days=3),
            loan_status=loan_status,
            account=self.account,
            application=self.application
        )

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        data = {
            "bank_account_number": self.bank_account_number,
            "bank_name": self.bank_name,
            "application_id": self.application.id
        }

        response = self.client.post(
            self.initialize_url, data=data, format='json')

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.disbursement.services.get_service')
    def test_change_bank_account_invalid_app(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.ACTIVATION_CALL_FAILED
        )
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )

        mock_get_service.return_value = mock_service

        for application_id in [self.application.id, 1]:
            data = {
                "bank_account_number": self.bank_account_number,
                "bank_name": self.bank_name,
                "application_id": application_id
            }

            response = self.client.post(
                self.initialize_url, data=data, format='json')

            self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_change_bank_account_invalid_request_payload(self):
        data_tests = [
            {
                "bank_account_number": None,
                "bank_name": self.bank_name,
                "application_id": self.application.id
            },
            {
                "bank_account_number": "",
                "bank_name": self.bank_name,
                "application_id": self.application.id
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": None,
                "application_id": self.application.id
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": "",
                "application_id": self.application.id
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": self.bank_name,
                "application_id": ""
            },
            {
                "bank_account_number": self.bank_account_number,
                "bank_name": self.bank_name,
                "application_id": None
            },
        ]
        for data in data_tests:
            response = self.client.post(
                self.initialize_url, data=data, format='json')
            self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch("juloserver.grab.views.trigger_create_or_update_ayoconnect_beneficiary.delay")
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_success(self, mock_get_service,
                                                    mock_create_update_beneficiary):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        self.assertEqual(self.application.name_bank_validation, self.old_name_bank_validation)
        self.assertNotEqual(self.application.bank_account_number, self.bank_account_number)
        old_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()
        self.assertEqual(old_count_of_application_field_change, 0)

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        # verify the application data related to bank is updated
        data = response.json()
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(data["data"]["validation_status"], NameBankValidationStatus.SUCCESS)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_bank_validation, self.name_bank_validation)
        self.assertEqual(self.application.bank_account_number, self.bank_account_number)

        # verify the ApplicationFieldChange is created
        new_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()

        self.assertEqual(new_count_of_application_field_change, 3)

        mock_create_update_beneficiary.assert_not_called()

    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_invalid_app_status(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.NOT_YET_CREATED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_app_not_owned_by_the_owner(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        unknow_app = ApplicationFactory()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(unknow_app.id))

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_app_not_grab(self, mock_get_service):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        workflow = WorkflowFactory(name="test workflow")
        self.application.workflow = workflow
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.get_name_bank_validation_status')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_failed_get_name_bank_validation_status(
        self, mock_get_service, mock_get_name_bank_validation_status):
        mock_get_name_bank_validation_status.side_effect = GrabLogicException(
            GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                "test error"))

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertTrue("test error" in response.json()["errors"][0])
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.create_new_bank_destination')
    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.update_bank_application')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_in_progress(
        self, mock_get_service, mock_update_bank_application, mock_create_new_bank_destination):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        self.name_bank_validation.validation_status = NameBankValidationStatus.INITIATED
        self.name_bank_validation.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertEqual(response.json()['data']['validation_status'],
                         GrabBankValidationStatus.IN_PROGRESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        mock_update_bank_application.assert_not_called()
        mock_create_new_bank_destination.assert_not_called()

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.update_bank_application')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_failed_update_bank_application(
        self, mock_get_service, mock_update_bank_application):
        mock_update_bank_application.side_effect = GrabLogicException(
            GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                "test error"))

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertTrue("test error" in response.json()["errors"][0])
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.create_new_bank_destination')
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_failed_create_new_bank_destination(
        self, mock_get_service, mock_create_new_bank_destination):
        mock_create_new_bank_destination.side_effect = GrabLogicException(
            GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                "test error"))

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        self.assertTrue("test error" in response.json()["errors"][0])
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch("juloserver.grab.views.trigger_create_or_update_ayoconnect_beneficiary.delay")
    @patch('juloserver.disbursement.services.get_service')
    def test_get_status_change_bank_account_success_190(self, mock_get_service,
                                                        mock_create_update_beneficiary):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        self.assertEqual(self.application.name_bank_validation, self.old_name_bank_validation)
        self.assertNotEqual(self.application.bank_account_number, self.bank_account_number)
        old_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()

        self.assertEqual(old_count_of_application_field_change, 0)

        response = self.client.get(self.status_url \
            + "?name_bank_validation_id={}&".format(self.name_bank_validation.id)\
            + "application_id={}".format(self.application.id))

        # verify the application data related to bank is updated
        data = response.json()

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(data["data"]["validation_status"], NameBankValidationStatus.SUCCESS)
        self.application.refresh_from_db()
        self.assertEqual(self.application.name_bank_validation, self.name_bank_validation)
        self.assertEqual(self.application.bank_account_number, self.bank_account_number)

        # verify the ApplicationFieldChange is created
        new_count_of_application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        ).count()

        self.assertEqual(new_count_of_application_field_change, 3)

        mock_create_update_beneficiary.assert_called()


class TestGrabUserBankAccountDetailsView(APITestCase):
    def setUp(self) -> None:
        self.get_user_bank_account = '/api/partner/grab/get-user-bank-account'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.bank = BankFactory(bank_name="test", is_active=True)
        self.application = ApplicationFactory(
            workflow=self.workflow,
            bank_name=self.bank.bank_name,
            bank_account_number='121212223'
        )
        self.data = {
            'bank_name': 'bank_name',
            'bank_account_number': '12345678910'
        }

        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.get(self.get_user_bank_account)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         'Invalid token header. No credentials provided.')
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_grab_customer_data(self):
        response = self.client.get(self.get_user_bank_account)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         GrabUtils.create_error_message(
                         GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                         GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE))
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_application(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        response = self.client.get(self.get_user_bank_account)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         GrabUtils.create_error_message(
                         GrabErrorCodes.GAX_ERROR_CODE.format('3'),
                         GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE))
        self.assertEqual(response_content['data'], None)

    def test_failed_with_invalid_application_status(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        self.application.customer = self.customer
        self.application.save()
        response = self.client.get(self.get_user_bank_account)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         GrabUtils.create_error_message(
                             GrabErrorCodes.GAX_ERROR_CODE.format('10'),
                             GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE))
        self.assertEqual(response_content['data'], None)

        response = self.client.get(self.get_user_bank_account)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         GrabUtils.create_error_message(
                             GrabErrorCodes.GAX_ERROR_CODE.format('10'),
                             GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE))
        self.assertEqual(response_content['data'], None)

    def test_success_with_user_bank_details(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        self.bank = BankFactory(bank_name="test", is_active=True)
        self.application.customer = self.customer
        self.application.bank_name = self.bank.bank_name
        self.application.bank_account_number = '121212223'
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.save()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='bank account not under own name'
        )
        response = self.client.get(self.get_user_bank_account)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertGreaterEqual(len(response_content['data']['banks']), 1)
        self.data = {
            'bank_name': self.bank.bank_name,
            'bank_account_number': '1111111111'
        }

        self.assertEqual(response_content['data']['bank_name'], self.application.bank_name)
        self.assertEqual(response_content['data']['bank_account_number'],
                         self.application.bank_account_number)


class TestReapplyApplication135(APITestCase):
    '''this test will test reapply, load form and submit endpoint for app 135'''

    def save_image_app(self):
        target_type_images = ('ktp_self', 'selfie', 'crop_selfie')
        for image in target_type_images:
            ImageFactory(image_type=image, image_source=self.application.id)

    def setUp(self) -> None:
        self.grab_populate_url = '/api/partner/grab/application/form/load'
        self.grab_reapply_url = '/api/partner/grab/reapply/'
        self.grab_submit_form_url = '/api/partner/grab/application/v2/submit'

        self.mobile_phone = '6281245789865'
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.hashed_phone_number = '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd9564a2'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user, phone=self.mobile_phone)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token,
            hashed_phone_number=self.hashed_phone_number
        )
        self.status_form_created = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application_status_code = StatusLookupFactory(code=190)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank',
            email='testingemail@gmail.com'
        )
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup
        )
        self.txn_id = 'abc123'
        self.document = DocumentFactory(loan_xid=self.loan.loan_xid, document_type='sphp_julo')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.save_image_app()

    def create_app_135(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
            grab_loan_inquiry=self.grab_loan_inquiry
        )

        # creating valid app with status 135 and change reason because of bank rejection
        GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.bank_name = '666_bank'
        self.application.bank_account_number = '666'
        self.application.kin_relationship = 'Orang tua'
        self.application.close_kin_mobile_phone = '081260036278'
        self.application.close_kin_name = 'yowman'
        self.application.last_education = 'SLTA'
        self.application.marital_status = 'Lajang'
        self.application.save()

        bank_rejection_reason = GrabApplicationService.get_bank_rejection_reason()
        self.application_history_135 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=135,
            status_old=124,
            change_reason='KTP blurry, {}'.format(bank_rejection_reason.mapping_status)
        )


    def test_load_form_for_app_135(self):
        response = self.client.get(self.grab_populate_url, {'step': 1})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['current_step'], 1)

        # if previous app is 135 and the reason is related to bank
        # the form load should return 4 for current_step value
        self.create_app_135()
        response = self.client.get(self.grab_populate_url, {'step': 1})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['current_step'], 4)

    def mock_process_application_status_change(self, application_id, new_status_code, change_reason,
                                          note=None):
        Application.objects.filter(id=application_id).\
            update(application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FORM_CREATED)
            )

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.grab.services.services.partnership_tokenize_pii_data')
    @mock.patch('juloserver.grab.services.services.process_application_status_change')
    def test_reapply_flow_for_app_135(self, mock_process_application_status_change, mocked_pii):
        mock_process_application_status_change.side_effect = self.mock_process_application_status_change

        self.create_app_135()
        mocked_pii.return_value = None

        # reapply
        response = self.client.post(self.grab_reapply_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['application']['application_status'],
                         ApplicationStatusCodes.FORM_CREATED)

        # load
        response = self.client.get(self.grab_populate_url, {'step': 4})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['current_step'], 4)

        # submit
        response = self.client.post(self.grab_submit_form_url, data=response.json()['data'],
                                    format='json')
        response_json = response.json()
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertNotEqual(response_json['data']['application_id'], self.application.id)

        # make sure the new app have image
        images_new_app = Image.objects.filter(image_source=response_json['data']['application_id'])
        for image in images_new_app:
            self.assertTrue(image.image_type in ['ktp_self', 'selfie', 'crop_selfie'])
        self.assertEqual(images_new_app.count(), 3)


class TestRegistration(APITestCase):
    def setUp(self) -> None:
        self.grab_register_url = '/api/partner/grab/register'
        self.mobile_phone = '6281245789863'
        self.mobile_phone_j1 = '6281245789866'
        self.nik = '1277020212980101'
        self.nik_j1 = '1277020212980102'
        self.email_j1 = 'test_login@gmail.com'
        self.token = (
            '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d'
            '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc'
            '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d'
            '8971764c12b9fb912c7d1c3b1db1f933'
        )
        self.token_j1 = (
            '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d'
            '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc'
            '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d'
            '8971764c12b9fb912c7d1c3b32423443'
        )
        self.hashed_phone_number = (
            '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd9564a3'
        )
        self.data = {"nik": self.nik, "pin": "159357", "phone_number": self.mobile_phone}
        self.mobile_feature_setting = MobileFeatureSettingFactory(feature_name='mobile_phone_1_otp')
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=0, status_next=100, workflow=self.workflow, is_active=True
        )
        self.partner = PartnerFactory(name='grab')
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token,
            hashed_phone_number=self.hashed_phone_number
        )
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)

        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=self.token)

        # J1 existing customer
        self.customer_j1 = CustomerFactory(nik=self.nik_j1, email=self.email_j1)
        self.customer_j1.save()
        customer_pin = CustomerPinFactory(user=self.customer_j1.user)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application_j1 = ApplicationFactory(
            customer=self.customer_j1,
            mobile_phone_1=self.mobile_phone_j1,
            email=self.email_j1,
            ktp=self.nik_j1,
            workflow=self.workflow_j1,
        )
        self.application_j1.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        )
        self.application_j1.save(update_fields=['application_status'])
        self.grab_customer_data_j1 = GrabCustomerDataFactory(
            phone_number=self.mobile_phone_j1,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token_j1,
        )

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='')
        response = self.client.post(self.grab_register_url,  data=self.data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0],
                         'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    @mock.patch('juloserver.grab.services.services.process_application_status_change')
    @mock.patch('juloserver.grab.services.services.partnership_tokenize_pii_data')
    def test_registeration(self, mock_process_application_status_change, mocked_pii):
        response = self.client.post(self.grab_register_url, data=self.data,
                                    format='json')
        self.assertEqual(response.status_code, 200)
        customer = Customer.objects.filter(nik=self.nik).last()
        self.assertEqual(None, customer.email)

    def test_j1_reapply_nik_disabled_reapply_flag(self):
        data = {
            "nik": self.nik_j1,
            "pin": "159357",
            "phone_number": self.mobile_phone_j1,
            "j1_bypass": False,
        }
        self.client.credentials(HTTP_AUTHORIZATION=self.token_j1)
        response = self.client.post(self.grab_register_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_j1_reapply_nik_with_flag(self):
        data = {
            "nik": self.nik_j1,
            "pin": "159357",
            "phone_number": self.mobile_phone_j1,
            "j1_bypass": True,
        }
        self.client.credentials(HTTP_AUTHORIZATION=self.token_j1)
        response = self.client.post(self.grab_register_url, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        j1_application = Application.objects.filter(
            customer_id=self.customer_j1.id,
            workflow__name=WorkflowConst.GRAB,
            application_status_id=100,
        ).last()
        self.assertIsNotNone(j1_application)
        # clean up
        Application.objects.filter(
            customer_id=self.customer_j1.id,
            workflow__name=WorkflowConst.GRAB,
            application_status_id=100,
        ).delete()

    def test_j1_reapply_email_with_flag(self):
        data = {
            "nik": self.email_j1,
            "pin": "159357",
            "phone_number": self.mobile_phone_j1,
            "j1_bypass": True,
        }
        self.client.credentials(HTTP_AUTHORIZATION=self.token_j1)
        self.assertTrue(Customer.objects.filter(email__iexact=self.email_j1).first())
        response = self.client.post(self.grab_register_url, data=data, format='json')
        self.assertEqual(response.status_code, 200)
        j1_application = Application.objects.filter(
            customer_id=self.customer_j1.id,
            workflow__name=WorkflowConst.GRAB,
            application_status_id=100,
        ).last()
        self.assertIsNotNone(j1_application)
        # clean up
        Application.objects.filter(
            customer_id=self.customer_j1.id,
            workflow__name=WorkflowConst.GRAB,
            application_status_id=100,
        ).delete()

    def test_j1_reapply_email_without_flag(self):
        data = {
            "nik": self.email_j1,
            "pin": "159357",
            "phone_number": self.mobile_phone_j1,
            "j1_bypass": False,
        }
        self.client.credentials(HTTP_AUTHORIZATION=self.token_j1)
        response = self.client.post(self.grab_register_url, data=data, format='json')
        self.assertEqual(response.status_code, 400)
        j1_application = Application.objects.filter(
            customer_id=self.customer_j1.id,
            workflow__name=WorkflowConst.GRAB,
            application_status_id=100,
        ).last()
        self.assertIsNone(j1_application)
        # clean up
        Application.objects.filter(
            customer_id=self.customer_j1.id,
            workflow__name=WorkflowConst.GRAB,
            application_status_id=100,
        ).delete()


class TestGrabOTPRequestConfirmView(APITestCase):
    def setUp(self) -> None:
        self.grab_link_url = '/api/partner/grab/link'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer, grab_validation_status=True, otp_status='VERIFIED'
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=GRAB_ACCOUNT_LOOKUP_NAME
        )
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.client = APIClient()
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=FeatureSettingName.COMPULSORY,
            is_active=True,
            parameters={
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time_sms": 1,
                    "otp_resend_time_miscall": 30,
                },
                "wait_time_seconds": 1440,
            },
        )

    @mock.patch('juloserver.grab.clients.clients.requests.get')
    def test_link_success(self, mocked_linked_response):
        mocked_response = mock.MagicMock(spec=requests.Response)
        mocked_response.status_code = 200
        response_body = {
            "msg_id": "834a730e92c24ed9a4f7205b972c2020",
            "success": True,
            "version": "1.0",
            "data": "",
        }
        mocked_response.content = json.dumps(response_body)
        mocked_linked_response.return_value = mocked_response
        request_body = {'phone_number': '6281247745668'}
        self.assertFalse(GrabCustomerData.objects.filter(phone_number='6281247745668').exists())
        response = self.client.post(self.grab_link_url, data=request_body, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            GrabCustomerData.objects.filter(
                phone_number='6281247745668', grab_validation_status=True
            ).exists()
        )

    @mock.patch('juloserver.grab.clients.clients.requests.get')
    def test_link_failure(self, mocked_linked_response):
        mocked_response = mock.MagicMock(spec=requests.Response)
        mocked_response.status_code = 200
        response_body = {
            "msg_id": "834a730e92c24ed9a4f7205b972c2020",
            "success": False,
            "version": "1.0",
            "data": "",
        }
        mocked_response.content = json.dumps(response_body)
        mocked_linked_response.return_value = mocked_response
        request_body = {'phone_number': '6281247745669'}
        self.assertFalse(GrabCustomerData.objects.filter(phone_number='6281247745669').exists())
        response = self.client.post(self.grab_link_url, data=request_body, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            GrabCustomerData.objects.filter(
                phone_number='6281247745669', grab_validation_status=False
            ).exists()
        )

    @mock.patch('juloserver.grab.clients.clients.requests.get')
    def test_otp_request_limit(self, mocked_linked_response):
        mocked_response = mock.MagicMock(spec=requests.Response)
        mocked_response.status_code = 200
        response_body = {
            "msg_id": "834a730e92c24ed9a4f7205b972c2020",
            "success": True,
            "version": "1.0",
            "data": "",
        }
        mocked_response.content = json.dumps(response_body)
        mocked_linked_response.return_value = mocked_response
        request_body = {'phone_number': '6281247745670'}
        self.assertFalse(GrabCustomerData.objects.filter(phone_number='6281247745670').exists())
        for i in list(range(4)):
            response = self.client.post(self.grab_link_url, data=request_body, format='json')
            time.sleep(2)
            if i == 3:
                self.assertEqual(response.status_code, 400)
                self.assertEqual(OtpRequest.objects.filter(phone_number='6281247745670').count(), i)
            else:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    OtpRequest.objects.filter(phone_number='6281247745670').count(), i + 1
                )

    @mock.patch('juloserver.grab.clients.clients.requests.get')
    def test_otp_request_limit_insufficient(self, mocked_linked_response):
        mocked_response = mock.MagicMock(spec=requests.Response)
        mocked_response.status_code = 200
        response_body = {
            "msg_id": "834a730e92c24ed9a4f7205b972c2020",
            "success": True,
            "version": "1.0",
            "data": "",
        }
        mocked_response.content = json.dumps(response_body)
        mocked_linked_response.return_value = mocked_response
        request_body = {'phone_number': '6281247745671'}
        self.assertFalse(GrabCustomerData.objects.filter(phone_number='6281247745671').exists())
        for i in list(range(2)):
            response = self.client.post(self.grab_link_url, data=request_body, format='json')
            if i == 1:
                self.assertEqual(response.status_code, 400)
                self.assertEqual(OtpRequest.objects.filter(phone_number='6281247745671').count(), i)
            else:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    OtpRequest.objects.filter(phone_number='6281247745671').count(), i + 1
                )


class TestSubmitLoan(APITestCase):
    def save_image_app(self):
        target_type_images = ('ktp_self', 'selfie', 'crop_selfie')
        for image in target_type_images:
            ImageFactory(image_type=image, image_source=self.application.id)

    def setUp(self):
        self.url = "/api/partner/grab/loan"
        self.mobile_phone = '6281245789865'
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.hashed_phone_number = '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd9564a2'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=190,
            status_next=180,
            workflow=self.workflow,
            is_active=True
        )
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(
            user=self.user,
            phone=self.mobile_phone,
            nik=12345678969)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token,
            hashed_phone_number=self.hashed_phone_number
        )
        self.status_form_created = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank',
            email='testingemail@gmail.com',
            application_status=StatusLookupFactory(status_code=190),
            workflow=self.workflow
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup
        )
        self.txn_id = 'abc123'
        self.document = DocumentFactory(loan_xid=self.loan.loan_xid, document_type='sphp_julo')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.save_image_app()

        self.grab_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [],
                },
                "daily_checker_config": {
                    "rps_throttling": 3,
                    "nearest_due_date_from_days": 5,
                    "batch_size": 1000,
                    "last_access_days": 7,
                    "retry_per_days": 1
                }
            },
            is_active=True,
        )

    @patch("juloserver.grab.views.GrabLoanService.apply")
    def test_loan_apply_have_active_loan(self, mock_loan_apply):
        mock_loan_apply.return_value = {
            'loan': self.loan,
            'disbursement_amount': 0,
            'installment_amount': 0,
            'monthly_interest': 0
        }
        data = {
            "program_id": "GRAB10000000",
            "loan_amount": 1000000,
            "tenure": 60
        }
        resp = self.client.post(self.url, data=data)
        self.assertEqual(resp.status_code, HTTPStatus.OK)

    @patch("juloserver.grab.views.GrabLoanApplyView.seojk_max_creditors_validation")
    @patch("juloserver.grab.views.GrabLoanService.apply")
    def test_loan_apply_have_no_active_loan(
        self,
        mock_loan_apply,
        mock_seojk_max_creditors_validation
    ):
        mock_seojk_max_creditors_validation.return_value = True, self.application
        mock_loan_apply.return_value = {
            'loan': self.loan,
            'disbursement_amount': 0,
            'installment_amount': 0,
            'monthly_interest': 0
        }
        self.loan.delete()
        data = {
            "program_id": "GRAB10000000",
            "loan_amount": 1000000,
            "tenure": 60
        }
        resp = self.client.post(self.url, data=data)
        self.assertEqual(resp.status_code, HTTPStatus.OK)
        mock_seojk_max_creditors_validation.assert_called()

    @patch("juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task")
    @patch("juloserver.grab.views.GrabLoanService.apply")
    def test_seojk_max_creditors_validation_no_fdc_data(
        self,
        mock_loan_apply,
        mock_fdc_inquiry_other_active_loans_from_platforms_task
    ):
        mock_fdc_inquiry_other_active_loans_from_platforms_task.return_value = False
        mock_loan_apply.return_value = {
            'loan': self.loan,
            'disbursement_amount': 0,
            'installment_amount': 0,
            'monthly_interest': 0
        }
        self.loan.delete()
        data = {
            "program_id": "GRAB10000000",
            "loan_amount": 1000000,
            "tenure": 60
        }
        resp = self.client.post(self.url, data=data)
        self.assertEqual(resp.status_code, HTTPStatus.OK)
        self.assertEqual(mock_fdc_inquiry_other_active_loans_from_platforms_task.call_count, 3)


    @patch("juloserver.grab.views.views.process_application_status_change")
    @patch("juloserver.grab.views.GrabLoanApplyView.seojk_max_creditors_validation")
    @patch("juloserver.grab.views.GrabLoanService.apply")
    def test_loan_apply_have_not_eligible(
        self,
        mock_loan_apply,
        mock_seojk_max_creditors_validation,
        mock_process_application_status_change
    ):
        mock_seojk_max_creditors_validation.return_value = False, self.application
        mock_loan_apply.return_value = {
            'loan': self.loan,
            'disbursement_amount': 0,
            'installment_amount': 0,
            'monthly_interest': 0
        }
        self.loan.delete()
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()

        data = {
            "program_id": "GRAB10000000",
            "loan_amount": 1000000,
            "tenure": 60
        }
        resp = self.client.post(self.url, data=data)
        self.assertEqual(resp.status_code, HTTPStatus.BAD_REQUEST)
        mock_seojk_max_creditors_validation.assert_called()
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE.format(3)
        )


class TestGrabValidatePromoCodeView(APITestCase):
    def random_plus_62_phone_number(self):
        return f'+62{fake.numerify(text="#%#%#%#%#%")}'

    def setUp(self) -> None:
        self.validate_promo_code = '/api/partner/grab/validate-promo-code'
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.phone_number = format_nexmo_voice_phone_number(self.random_plus_62_phone_number())
        self.grab_customer_data = GrabCustomerData.objects.create(
            customer=self.customer,
            phone_number=self.phone_number,
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED,
            token=self.user.auth_expiry_token.key
        )
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.bank = BankFactory(bank_name="test", is_active=True)
        self.application = ApplicationFactory(
            workflow=self.workflow
        )
        self.data = {
            'promo_code': '111111',
            'phone_number': self.phone_number
        }
        self.grab_promo_code = GrabPromoCodeFactory(
            promo_code=111111,
            title="test",
            active_date='2024-01-04',
            expire_date=timezone.localtime(timezone.now()).date()
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client_token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=self.client_token)
        self.mobile_feature_setting = MobileFeatureSetting.objects.get_or_create(
            feature_name='mobile_phone_1_otp'
        )

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        self.data = {
            'promo_code': '111111',
            'phone_number': '24234234'
        }
        response = self.client.post(self.validate_promo_code,  data=self.data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    def test_failed_with_invalid_promo_code(self):
        data = {
            'promo_code': '',
            'phone_number': self.phone_number
        }
        response = self.client.post(self.validate_promo_code, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        data = {
            'promo_code': '1',
            'phone_number': self.phone_number
        }
        response = self.client.post(self.validate_promo_code, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

        data = {
            'promo_code': '1#@$@#$',
            'phone_number': self.phone_number
        }
        response = self.client.post(self.validate_promo_code, data=data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_failed_with_no_matching_segment(self):
        self.grab_promo_code1 = GrabPromoCodeFactory(
            promo_code=222222,
            title="test",
            active_date='2024-01-04',
            expire_date='2024-02-04'
        )
        response = self.client.post(self.validate_promo_code, data=self.data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['is_valid_promo_code'], False)

    @freeze_time("2023-01-02 15:00:00")
    def test_success_with_segment_rule_1(self):
        promo_code = 3333
        GrabPromoCodeFactory(
            promo_code=promo_code,
            title="test segment 1",
            active_date='2023-01-01',
            expire_date='2024-02-04',
            rule=[1],
        )
        payload = {'promo_code': promo_code, 'phone_number': self.phone_number}
        response = self.client.post(self.validate_promo_code, data=payload, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['is_valid_promo_code'], True)

    @freeze_time("2023-01-02 15:00:00")
    def test_success_with_segment_rule_2(self):
        promo_code = 4444
        GrabPromoCodeFactory(
            promo_code=promo_code,
            title="test segment 2",
            active_date='2023-01-01',
            expire_date='2024-02-04',
            rule=[2],
        )
        LoanFactory(customer=self.customer, account=self.account)
        payload = {'promo_code': promo_code, 'phone_number': self.phone_number}
        response = self.client.post(self.validate_promo_code, data=payload, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['is_valid_promo_code'], True)

    @freeze_time("2023-01-02 15:00:00")
    def test_success_with_segment_rule_3(self):
        user = AuthUserFactory()
        partner = PartnerFactory(user=user, name='grab')
        customer = CustomerFactory(user=user)
        phone_number = format_nexmo_voice_phone_number(self.random_plus_62_phone_number())
        grab_customer_data = GrabCustomerData.objects.create(
            customer=customer,
            phone_number=phone_number,
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED,
            token=user.auth_expiry_token.key,
        )
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        self.client.force_login(user)
        self.client_token = user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=self.client_token)
        promo_code = 5555
        GrabPromoCodeFactory(
            promo_code=promo_code,
            title="test segment 3",
            active_date='2023-01-01',
            expire_date='2024-02-04',
            rule=[3],
        )
        loan = LoanFactory(customer=customer, account=account)
        paid_off_status = StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF)
        loan.update_safely(loan_status=paid_off_status)
        payload = {'promo_code': promo_code, 'phone_number': phone_number}
        response = self.client.post(self.validate_promo_code, data=payload, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['is_valid_promo_code'], True)

    @freeze_time("2023-01-02 15:00:00")
    def test_failed_with_segment_rule_3_with_no_loan(self):
        user = AuthUserFactory()
        partner = PartnerFactory(user=user, name='grab')
        customer = CustomerFactory(user=user)
        phone_number = format_nexmo_voice_phone_number(self.random_plus_62_phone_number())
        grab_customer_data = GrabCustomerData.objects.create(
            customer=customer,
            phone_number=phone_number,
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED,
            token=user.auth_expiry_token.key,
        )
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        self.client.force_login(user)
        self.client_token = user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=self.client_token)
        promo_code = 6666
        GrabPromoCodeFactory(
            promo_code=promo_code,
            title="test segment 3 with no loan",
            active_date='2023-01-01',
            expire_date='2024-02-04',
            rule=[3],
        )
        payload = {'promo_code': promo_code, 'phone_number': phone_number}
        response = self.client.post(self.validate_promo_code, data=payload, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.json()['data']['is_valid_promo_code'], False)


class TestGrabUserExperimentDetailsView(APITestCase):
    def setUp(self) -> None:
        self.get_user_experiment_group = '/api/partner/grab/user-experiment-group'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)

        self.client = APIClient()
        self.client.force_login(self.user)
        self.client_token = 'Token ' + self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=self.client_token)

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.get(self.get_user_experiment_group)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_phone_number(self):
        response = self.client.get(self.get_user_experiment_group)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_grab_customer_data(self):
        phone_number = LazyAttribute(lambda o: fake.phone_number())
        response = self.client.get(
            self.get_user_experiment_group + "?phone_number={}".format(phone_number))
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    @patch('juloserver.grab.services.services.GrabUserExperimentService.get_user_experiment_group')
    def test_success_with_user_experiment_group_data(self, mock_get_user_experiment_group):
        mock_get_user_experiment_group.return_value = "control"
        phone_number = "085225443991"
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=phone_number,
            token=self.client_token,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
        )
        response = self.client.get(
            self.get_user_experiment_group + "?phone_number={}".format(phone_number))
        self.assertEqual(response.status_code, HTTPStatus.OK)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], True)
        self.assertGreaterEqual(response_content['data'], 'control')


class TestGrabPaymentPlansView(APITestCase):
    def setUp(self) -> None:
        self.get_payment_plan = '/api/partner/grab/payment_plans'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)

        self.client = APIClient()
        self.client.force_login(self.user)
        self.client_token = 'Token ' + self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=self.client_token)
        self.mock_request_body = {"phone_number": "6281982736152",
                                  "program_id": "ID-DAX-CL-6-MONTHS-MOCK",
                                  "max_loan_amount": "6600000",
                                  "min_loan_amount": "300000", "interest_rate": "4",
                                  "loan_amount": 6575000, "offer_threshold": "385000",
                                  "tenure": 120,
                                  "tenure_interval": 30, "min_tenure": 30, "upfront_fee": "25000"}

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.post(self.get_payment_plan, data=self.mock_request_body,
                                    format='json')
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_grab_customer_data(self):
        response = self.client.post(self.get_payment_plan, format='json')
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_success_without_user_type(self, mock_get_user_experiment_group):
        grab_cust_data = GrabCustomerDataFactory(
            phone_number=self.mock_request_body.get('phone_number'),
            token=self.client_token,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        grab_loan_offer = GrabLoanOfferFactory(
            grab_customer_data=grab_cust_data,
            program_id=self.mock_request_body.get('program_id'),
            interest_value=self.mock_request_body.get('interest_rate'),
            fee_value=self.mock_request_body.get('upfront_fee'),
            min_tenure=self.mock_request_body.get('min_tenure'),
            tenure=self.mock_request_body.get('tenure'),
            tenure_interval=self.mock_request_body.get('tenure_interval'),
            weekly_installment_amount=500000,
            min_loan_amount=self.mock_request_body.get('min_loan_amount'),
            max_loan_amount=self.mock_request_body.get('max_loan_amount'),
        )
        with mock.patch("juloserver.grab.services.services.get_redis_client") as \
            mock_get_redis_client:
            mock_get_redis_client.return_value = mock.Mock()
            response = self.client.post(
                self.get_payment_plan,
                data=self.mock_request_body,
                format='json'
            )
            self.assertEqual(response.status_code, HTTPStatus.OK)
            response_content = json.loads(response.content)
            self.assertEqual(response_content['success'], True)
            self.assertGreaterEqual(len(response_content['data']), 4)

            grab_payment_plans = GrabPaymentPlans.objects.last()
            self.assertEqual(grab_payment_plans.grab_customer_data_id, grab_cust_data.id)
            self.assertEqual(grab_payment_plans.program_id, grab_loan_offer.program_id)
            self.assertIsNotNone(grab_payment_plans.payment_plans)

            # re hit the api for testing multiple hit payment plan
            response = self.client.post(
                self.get_payment_plan, data=self.mock_request_body, format='json'
            )
            self.assertEqual(response.status_code, HTTPStatus.OK)
            response_content = json.loads(response.content)
            self.assertEqual(response_content['success'], True)
            self.assertGreaterEqual(len(response_content['data']), 4)

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_success_with_user_type_variation(self, mock_get_user_experiment_group):
        grab_cust_data = GrabCustomerDataFactory(
            phone_number=self.mock_request_body.get('phone_number'),
            token=self.client_token,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        self.mock_request_body['user_type'] = GrabExperimentConst.VARIATION_TYPE
        grab_loan_offer = GrabLoanOfferFactory(
            grab_customer_data=grab_cust_data,
            program_id=self.mock_request_body.get('program_id'),
            interest_value=self.mock_request_body.get('interest_rate'),
            fee_value=self.mock_request_body.get('upfront_fee'),
            min_tenure=self.mock_request_body.get('min_tenure'),
            tenure=self.mock_request_body.get('tenure'),
            tenure_interval=self.mock_request_body.get('tenure_interval'),
            weekly_installment_amount=500000,
            min_loan_amount=self.mock_request_body.get('min_loan_amount'),
            max_loan_amount=self.mock_request_body.get('max_loan_amount'),
        )
        with mock.patch(
            "juloserver.grab.services.services.get_redis_client"
        ) as mock_get_redis_client:
            mock_get_redis_client.return_value = mock.Mock()
            response = self.client.post(
                self.get_payment_plan,
                data=self.mock_request_body,
                format='json'
            )
            self.assertEqual(response.status_code, HTTPStatus.OK)
            response_content = json.loads(response.content)
            self.assertEqual(response_content['success'], True)
            self.assertGreaterEqual(len(response_content['data']), 16)

            list_of_loan_amount_from_response = []
            list_of_daily_repayment_from_response = []
            list_of_weekly_instalment_from_response = []
            list_of_loan_disbursement_amount_from_response = []
            for data in response_content['data']:
                if data.get('loan_amount') not in list_of_loan_amount_from_response:
                    list_of_loan_amount_from_response.append(data.get('loan_amount'))
                if data.get('daily_repayment') not in list_of_daily_repayment_from_response:
                    list_of_daily_repayment_from_response.append(data.get('daily_repayment'))
                if (
                    data.get('weekly_instalment_amount')
                    not in list_of_weekly_instalment_from_response
                ):
                    list_of_weekly_instalment_from_response.append(
                        data.get('weekly_instalment_amount')
                    )
                if (
                    data.get('loan_disbursement_amount')
                    not in list_of_loan_disbursement_amount_from_response
                ):
                    list_of_loan_disbursement_amount_from_response.append(
                        data.get('loan_disbursement_amount')
                    )

            self.assertEqual(
                [300000, 1600000, 2850000, 4100000, 5350000, 6600000],
                list_of_loan_amount_from_response,
            )
            self.assertEqual(
                [
                    10400.0,
                    5400.0,
                    3734.0,
                    2900.0,
                    55467.0,
                    28800.0,
                    19912.0,
                    15467.0,
                    51300.0,
                    35467.0,
                    27550.0,
                    51023.0,
                    39634.0,
                    66578.0,
                    51717.0,
                    63800.0,
                ],
                list_of_daily_repayment_from_response,
            )
            self.assertEqual(
                [
                    72800.0,
                    37800.0,
                    26138.0,
                    20300.0,
                    388269.0,
                    201600.0,
                    139384.0,
                    108269.0,
                    359100.0,
                    248269.0,
                    192850.0,
                    357161.0,
                    277438.0,
                    466046.0,
                    362019.0,
                    446600.0,
                ],
                list_of_weekly_instalment_from_response,
            )
            self.assertEqual(
                [275000.0, 1575000.0, 2825000.0, 4075000.0, 5325000.0, 6575000.0],
                list_of_loan_disbursement_amount_from_response,
            )
            grab_payment_plans = GrabPaymentPlans.objects.last()
            self.assertEqual(grab_payment_plans.grab_customer_data_id, grab_cust_data.id)
            self.assertEqual(grab_payment_plans.program_id, grab_loan_offer.program_id)
            self.assertIsNotNone(grab_payment_plans.payment_plans)


class TestGrabChoosePaymentPlanView(APITestCase):
    def setUp(self) -> None:
        self.get_payment_plan = '/api/partner/grab/payment_plans'
        self.choose_payment_plan = '/api/partner/grab/choose_payment_plan'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)

        self.client = APIClient()
        self.client.force_login(self.user)
        self.client_token = 'Token ' + self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=self.client_token)
        self.mock_choose_payment_plan_payload = {
            "phone_number": "6281260036277",
            "program_id": "ID-DAX-CL",
            "max_loan_amount": 2000000,
            "min_loan_amount": 500000,
            "frequency_type": "DAILY",
            "loan_disbursement_amount": 1925000,
            "penalty_type": "FLAT",
            "penalty_value": 0,
            "amount_plan": 1925000,
            "tenure_plan": 90,
            "interest_type_plan": "SIMPLE_INTEREST",
            "interest_value_plan": 4,
            "instalment_amount_plan": 24889,
            "fee_type_plan": "FLAT",
            "fee_value_plan": 75000,
            "total_repayment_amount_plan": 2240000,
            "weekly_installment_amount": 700000,
            "smaller_loan_option_flag": False,
            "promo_code": "",
        }

        self.mock_payment_plan_payload = {
            "phone_number": "6281260036277",
            "program_id": "ID-DAX-CL",
            "max_loan_amount": "2000000",
            "min_loan_amount": "500000",
            "interest_rate": "4",
            "loan_amount": 1925000,
            "offer_threshold": "700000",
            "tenure": 180,
            "tenure_interval": 30,
            "min_tenure": 30,
            "upfront_fee": 75000,
        }
        self.mock_payment_plan_response = [
            {
                'tenure': 180,
                'daily_repayment': 13777,
                'repayment_amount': 2479860,
                'loan_disbursement_amount': 1925000,
                'weekly_instalment_amount': 77777.77777777778,
                'loan_amount': 2000000,
                'smaller_loan_option_flag': False,
                'upfront_fee': 20000,
            },
            {
                'tenure': 150,
                'daily_repayment': 16000,
                'repayment_amount': 2400000,
                'loan_disbursement_amount': 1925000,
                'weekly_instalment_amount': 93333.33333333334,
                'loan_amount': 2000000,
                'smaller_loan_option_flag': False,
                'upfront_fee': 20000,
            },
            {
                'tenure': 120,
                'daily_repayment': 19333,
                'repayment_amount': 2319960,
                'loan_disbursement_amount': 1925000,
                'weekly_instalment_amount': 116666.66666666667,
                'loan_amount': 2000000,
                'smaller_loan_option_flag': False,
                'upfront_fee': 20000,
            },
            {
                'tenure': 90,
                'daily_repayment': 24888,
                'repayment_amount': 2239920,
                'loan_disbursement_amount': 1925000,
                'weekly_instalment_amount': 155555.55555555556,
                'loan_amount': 2000000,
                'smaller_loan_option_flag': False,
                'upfront_fee': 20000,
            },
            {
                'tenure': 60,
                'daily_repayment': 36000,
                'repayment_amount': 2160000,
                'loan_disbursement_amount': 1925000,
                'weekly_instalment_amount': 233333.33333333334,
                'loan_amount': 2000000,
                'smaller_loan_option_flag': False,
                'upfront_fee': 20000,
            },
            {
                'tenure': 30,
                'daily_repayment': 69333,
                'repayment_amount': 2079990,
                'loan_disbursement_amount': 1925000,
                'weekly_instalment_amount': 466666.6666666667,
                'loan_amount': 2000000,
                'smaller_loan_option_flag': False,
                'upfront_fee': 20000,
            },
        ]
        self.mock_grab_loan_offer = {
            'program_id': 'ID-DAX-CL',
            'max_loan_amount': '2000000',
            'min_loan_amount': '500000',
            'weekly_installment_amount': '700000',
            'tenure': 180,
            'min_tenure': 30,
            'tenure_interval': 30,
            'daily_repayment': 13777,
            'upfront_fee_type': 'FLAT',
            'upfront_fee': '75000',
            'interest_rate_type': 'SIMPLE_INTEREST',
            'interest_rate': '4',
            'penalty_type': 'FLAT',
            'penalty_value': '0',
            'loan_disbursement_amount': 1925000,
            'frequency_type': 'DAILY',
        }

    def test_failed_with_wrong_auth(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ')
        response = self.client.post(
            self.choose_payment_plan, data=self.mock_choose_payment_plan_payload, format='json'
        )
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    def test_failed_with_no_grab_customer_data(self):
        response = self.client.post(self.choose_payment_plan, format='json')
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        response_content = json.loads(response.content)
        self.assertEqual(response_content['success'], False)
        self.assertEqual(response_content['errors'][0], 'Unauthorized request')
        self.assertEqual(response_content['data'], None)

    @mock.patch(
        "juloserver.grab.services.services.process_update_grab_experiment_by_grab_customer_data"
    )
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_success_without_user_type(
        self, mock_get_user_experiment_group, mock_update_grab_experiment: MagicMock
    ):
        grab_cust_data = GrabCustomerDataFactory(
            phone_number=self.mock_choose_payment_plan_payload.get('phone_number'),
            token=self.client_token,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
        )
        GrabLoanOfferFactory(
            grab_customer_data=grab_cust_data,
            program_id=self.mock_grab_loan_offer.get('program_id'),
            interest_value=self.mock_grab_loan_offer.get('interest_rate'),
            fee_value=self.mock_grab_loan_offer.get('upfront_fee'),
            min_tenure=self.mock_grab_loan_offer.get('min_tenure'),
            tenure=self.mock_grab_loan_offer.get('tenure'),
            tenure_interval=self.mock_grab_loan_offer.get('tenure_interval'),
            weekly_installment_amount=self.mock_grab_loan_offer.get('weekly_installment_amount'),
            min_loan_amount=self.mock_grab_loan_offer.get('min_loan_amount'),
            max_loan_amount=self.mock_grab_loan_offer.get('max_loan_amount'),
        )
        with mock.patch(
            "juloserver.grab.services.services.get_redis_client"
        ) as mock_get_redis_client:
            mock_get_redis_client.return_value = mock.Mock()

            # call get payment plan
            response_payment_plan = self.client.post(
                self.get_payment_plan, data=self.mock_payment_plan_payload, format='json'
            )

            # call choose payment plan
            response = self.client.post(
                self.choose_payment_plan, data=self.mock_choose_payment_plan_payload, format='json'
            )
            self.assertEqual(response.status_code, HTTPStatus.OK)
            response_content = json.loads(response.content)
            self.assertEqual(response_content['success'], True)

            grab_loan_data_obj = GrabLoanData.objects.last()
            grab_loan_offer_obj = GrabLoanOffer.objects.last()
            grab_payment_plans_obj = GrabPaymentPlans.objects.filter(
                grab_customer_data_id=grab_cust_data.id,
                program_id=self.mock_choose_payment_plan_payload.get('program_id'),
            ).last()
            payment_plan = {}
            list_of_payment_plan = json.loads(grab_payment_plans_obj.payment_plans)
            for payment_plan in list_of_payment_plan:
                if self.mock_choose_payment_plan_payload.get(
                    'total_repayment_amount_plan'
                ) == payment_plan.get(
                    'repayment_amount'
                ) and self.mock_choose_payment_plan_payload.get(
                    'tenure_plan'
                ) == payment_plan.get(
                    'tenure'
                ):
                    payment_plan = payment_plan
                    break
            self.assertEqual(
                grab_loan_data_obj.program_id,
                self.mock_choose_payment_plan_payload.get('program_id'),
            )
            self.assertEqual(grab_loan_data_obj.selected_amount, payment_plan.get('loan_amount'))
            self.assertEqual(grab_loan_data_obj.selected_tenure, payment_plan.get('tenure'))
            self.assertEqual(
                grab_loan_data_obj.selected_interest, grab_loan_offer_obj.interest_value
            )
            self.assertEqual(
                grab_loan_data_obj.selected_instalment_amount, payment_plan.get('daily_repayment')
            )

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_success_with_user_type_variation(self, mock_get_user_experiment_group):
        grab_cust_data = GrabCustomerDataFactory(
            phone_number=self.mock_choose_payment_plan_payload.get('phone_number'),
            token=self.client_token,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
        )
        self.mock_choose_payment_plan_payload['user_type'] = GrabExperimentConst.VARIATION_TYPE
        grab_loan_offer = GrabLoanOfferFactory(
            grab_customer_data=grab_cust_data,
            program_id=self.mock_grab_loan_offer.get('program_id'),
            interest_value=self.mock_grab_loan_offer.get('interest_rate'),
            fee_value=self.mock_grab_loan_offer.get('upfront_fee'),
            min_tenure=self.mock_grab_loan_offer.get('min_tenure'),
            tenure=self.mock_grab_loan_offer.get('tenure'),
            tenure_interval=self.mock_grab_loan_offer.get('tenure_interval'),
            weekly_installment_amount=500000,
            min_loan_amount=self.mock_grab_loan_offer.get('min_loan_amount'),
            max_loan_amount=self.mock_grab_loan_offer.get('max_loan_amount'),
        )
        with mock.patch(
            "juloserver.grab.services.services.get_redis_client"
        ) as mock_get_redis_client:
            mock_get_redis_client.return_value = mock.Mock()

            # call get payment plan
            self.client.post(
                self.get_payment_plan, data=self.mock_payment_plan_payload, format='json'
            )

            # call choose payment plan
            response = self.client.post(
                self.choose_payment_plan, data=self.mock_choose_payment_plan_payload, format='json'
            )
            self.assertEqual(response.status_code, HTTPStatus.OK)
            response_content = json.loads(response.content)
            self.assertEqual(response_content['success'], True)
            self.assertEqual(response_content['data'].get('is_payment_plan_set'), True)

            grab_loan_data = GrabLoanData.objects.last()
            self.assertEqual(
                grab_loan_data.program_id, self.mock_choose_payment_plan_payload.get('program_id')
            )
            self.assertEqual(
                grab_loan_data.selected_amount,
                self.mock_choose_payment_plan_payload.get('max_loan_amount'),
            )
            self.assertEqual(
                grab_loan_data.selected_tenure,
                self.mock_choose_payment_plan_payload.get('tenure_plan'),
            )
            self.assertEqual(
                grab_loan_data.selected_interest,
                self.mock_choose_payment_plan_payload.get('interest_value_plan'),
            )
            self.assertEqual(
                grab_loan_data.selected_instalment_amount,
                self.mock_choose_payment_plan_payload.get('instalment_amount_plan'),
            )


class TestGrabLoginView(APITestCase):
    def setUp(self) -> None:
        self.grab_login = '/api/partner/grab/login'
        self.fake_pin = fake.numerify(text="#%#%#%")
        self.nik = '1601260506021284'
        self.email = fake.random_email()

    def set_pin(self, user, pin):
        user.set_password(pin)
        user.save()
        user.refresh_from_db()
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(user)

    def test_success_validate_user_registered_using_nik(self):
        CustomerFactory(nik=self.nik)
        data = {'nik': self.nik}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("success"), True)

    def test_success_validate_user_registered_using_email(self):
        CustomerFactory(email=self.email)
        data = {'nik': self.email}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("success"), True)

    def test_success_validate_user_not_registered_using_nik(self):
        data = {'nik': self.nik}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(
            response.json().get("errors")[0],
            {
                'title': 'NIK / Email anda tidak terdaftar',
                'subtitle': 'your NIK / Email not registered',
            },
        )

    def test_success_validate_user_not_registered_using_email(self):
        data = {'nik': self.email}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(
            response.json().get("errors")[0],
            {
                'title': 'NIK / Email anda tidak terdaftar',
                'subtitle': 'your NIK / Email not registered',
            },
        )

    def test_success_login_with_empty_pin_not_getting_token(self):
        CustomerFactory(email=self.email)
        data = {'nik': self.email, 'pin': ''}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertEqual(response.json().get("data"), None)

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_success_login_getting_token(self, mock_redis_client):
        mock_redis_client.return_value.get_list.return_value = []
        user = AuthUserFactory()
        user.is_superuser = True
        user.is_staff = True
        user.save()
        user.refresh_from_db()
        customer = CustomerFactory(user=user, email=self.email)
        ApplicationFactory(customer=customer)
        GrabCustomerDataFactory(customer=customer)

        self.set_pin(user, self.fake_pin)

        data = {'nik': self.email, 'pin': self.fake_pin}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code, response.content)
        self.assertIsNotNone(response.json().get("data").get('token'))
        self.assertIsNotNone(response.json().get("data").get("jwt_token"))

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_success_login_getting_token_no_application(self, mock_redis_client):
        mock_redis_client.return_value.get_list.return_value = []
        user = AuthUserFactory()
        user.is_superuser = True
        user.is_staff = True
        user.save()
        user.refresh_from_db()
        customer = CustomerFactory(user=user, email=self.email)
        GrabCustomerDataFactory(customer=customer)

        self.set_pin(user, self.fake_pin)

        data = {'nik': self.email, 'pin': self.fake_pin}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code)
        jwt_token = response.json()['data']['jwt_token']
        jwt_auth = JWTAuthentication()
        decoded = jwt_auth.decode_token(jwt_token, verify_signature=False)
        self.assertEqual(decoded['application_id'], None)

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_success_login_getting_token_no_grab_customer_data(self, mock_redis_client):
        mock_redis_client.return_value.get_list.return_value = []
        user = AuthUserFactory()
        user.is_superuser = True
        user.is_staff = True
        user.save()
        user.refresh_from_db()
        customer = CustomerFactory(user=user, email=self.email)
        grab_anon_user = get_grab_customer_data_anonymous_user()

        self.set_pin(user, self.fake_pin)

        data = {'nik': self.email, 'pin': self.fake_pin}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.OK, response.status_code)
        jwt_token = response.json()['data']['jwt_token']
        jwt_auth = JWTAuthentication()
        decoded = jwt_auth.decode_token(jwt_token, verify_signature=False)
        self.assertEqual(decoded['application_id'], None)
        self.assertEqual(decoded['user_identifier_id'], grab_anon_user.id)

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_invalid_pin(self, mock_redis_client):
        mock_redis_client.return_value.get_list.return_value = []
        user = AuthUserFactory()
        user.is_superuser = True
        user.is_staff = True
        user.save()
        user.refresh_from_db()
        CustomerFactory(user=user, email=self.email)

        self.set_pin(user, self.fake_pin)

        data = {'nik': self.email, 'pin': 123456}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(
            response.json().get("errors")[0],
            {'title': 'NIK, Email, atau PIN Anda salah', 'subtitle': ''},
        )

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_invalid_string_pin(self, mock_redis_client):
        mock_redis_client.return_value.get_list.return_value = []
        user = AuthUserFactory()
        user.is_superuser = True
        user.is_staff = True
        user.save()
        user.refresh_from_db()
        CustomerFactory(user=user, email=self.email)

        self.set_pin(user, self.fake_pin)

        data = {'nik': self.email, 'pin': 'number'}
        response = self.client.post(self.grab_login, data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(
            response.json().get("errors")[0],
            {'title': 'This value does not match the required pattern.', 'subtitle': ''},
        )

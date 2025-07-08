import json
from mock import patch
from io import StringIO
from datetime import timedelta

from django.test.testcases import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    ImageFactory,
    ApplicationFactory,
    OtpRequestFactory,
    MobileFeatureSettingFactory,
    FeatureSettingFactory,
    GroupFactory,
    WorkflowFactory,
    AffordabilityHistoryFactory,
    ProductLookupFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    PaymentFactory,
    CreditScoreFactory,
    LoanFactory,
    AccountingCutOffDateFactory,
)
from juloserver.julo.models import Loan

from juloserver.julovers.tests.factories import (
    WorkflowStatusPathFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AddressFactory,
    AccountLimitFactory,
    AccountLookupFactory,
)
from juloserver.account.constants import AccountConstant

from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.credit_card.tests.factiories import (
    CreditCardFactory,
    CreditCardApplicationFactory,
    CreditCardStatusFactory,
    CreditCardTransactionFactory,
    JuloCardBannerFactory,
)
from juloserver.credit_card.constants import (
    BSSTransactionConstant,
    PushNotificationContentsConst,
)

from juloserver.cfs.tests.factories import AgentFactory

from juloserver.credit_card.constants import (
    CreditCardStatusConstant,
    ErrorMessage,
    OTPConstant,
    FeatureNameConst,
    BSSResponseConstant,
)
from juloserver.credit_card.utils import AESCipher
from juloserver.credit_card.models import (
    CreditCard,
    CreditCardTransaction,
)

from juloserver.julo.statuses import (
    CreditCardCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.constants import WorkflowConst

from juloserver.pin.services import CustomerPinService
from juloserver.pin.constants import VerifyPinMsg

from juloserver.portal.object.dashboard.constants import JuloUserRoles

from juloserver.loan.tests.factories import (
    TransactionMethodFactory,
    TransactionCategoryFactory,
)
from juloserver.loan.services.loan_related import get_loan_duration

from juloserver.payment_point.constants import TransactionMethodCode
import pytest


def create_mock_credit_card_application(
    credit_card_application_status_code: int
) -> CreditCardApplicationFactory:
    user = AuthUserFactory()
    customer = CustomerFactory(user=user)
    account = AccountFactory(customer=customer,
                             account_lookup=AccountLookupFactory(moengage_mapping_number="1"))
    ApplicationFactory(
        customer=customer, account=account,
    )
    address = AddressFactory(
        latitude=0.1,
        longitude=0.2,
        provinsi='Jawa Barat',
        kabupaten='Bandung',
        kecamatan='Cibeunying kaler',
        kelurahan='Cigadung',
        kodepos=12345,
        detail='jl cigadung'
    )
    image = ImageFactory(image_source=1, image_type='selfie')
    credit_card_application = CreditCardApplicationFactory(
        virtual_card_name='Jhon',
        virtual_account_number='1231231231',
        status=StatusLookupFactory(status_code=credit_card_application_status_code),
        shipping_number='20314872344',
        address=address,
        account=account,
        image=image
    )
    return credit_card_application


class TestCardInformationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=510)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        self.credit_card = CreditCardFactory(
            card_number='1532',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_card_infromation = '/api/credit-card/v1/card/information'

    def test_get_information_success(self):
        response = self.client.get(self.url_card_infromation)
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(
            response['data']['virtual_account_number'],
            self.credit_card_application.virtual_account_number
        )

    def test_get_information_not_found(self):
        account = AccountFactory()
        self.credit_card_application.account = account
        self.credit_card_application.save()
        self.credit_card_application.refresh_from_db()
        response = self.client.get(self.url_card_infromation)
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.CREDIT_CARD_NOT_FOUND,
            response['errors'],
        )


class TestCardStatusView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED_WRONG_PIN)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        # example active card status response from bss
        self.mock_response_bss = {
            'responseCode': '00',
            'responseDescription': 'SUCCEED',
            'cardStatus': 'ACTIVE',
            'blockStatus': '',
            'accountNumber': '1021785136',
            'accountHolderName': 'PT, FINANCE',
            'incorrectPinCounter': '00',
            'dateCardLinked': '2022-08-15 00:00',
            'dateLastUsed': '2022-09-05 00:00',
            'dateBlocked': '',
            'dateClosed': ''
        }
        self.url_card_status = '/api/credit-card/v1/card/status'

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_get_status_success(self, mock_inquiry_card_status, mock_redis_client):
        mock_redis_client.return_value.get.return_value = '1'
        mock_inquiry_card_status.return_value = self.mock_response_bss
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(response['data']['status'], CreditCardCodes.CARD_ACTIVATED)
        self.assertIsNone(response['data']['incorrect_pin_warning_message'])

    def test_get_status_not_found(self):
        account = AccountFactory()
        self.credit_card_application.account = account
        self.credit_card_application.save()
        self.credit_card_application.refresh_from_db()
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.CREDIT_CARD_NOT_FOUND,
            response['errors'],
        )

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_inquiry_status_error_bss_server(self, mock_inquiry_card_status,
                                             mock_redis_client):
        mock_redis_client.return_value.get.return_value = '0'
        mock_inquiry_card_status.return_value = {
            'responseCode': '24',
            'description': 'Transaksi tidak dapat diproses'
        }
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(response['data']['status'], self.credit_card_application.status_id)

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_card_status_should_584_when_response_from_bss_wrong_pin_three_time(
            self, mock_inquiry_card_status, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = '0'
        self.credit_card_application.status_id = CreditCardCodes.CARD_UNBLOCKED
        self.credit_card_application.save()
        self.credit_card_application.refresh_from_db()
        self.mock_response_bss['dateBlocked'] = '2022-09-05 11:41'
        self.mock_response_bss['incorrectPinCounter'] = '03'
        self.mock_response_bss['blockStatus'] = 'Excessive PIN Tries, Decline'
        mock_inquiry_card_status.return_value = self.mock_response_bss
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_BLOCKED_WRONG_PIN)
        self.assertEqual(response['data']['status'], CreditCardCodes.CARD_BLOCKED_WRONG_PIN)

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_card_status_should_581_when_response_from_bss_blocked_card(
            self, mock_inquiry_card_status, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = '0'
        self.mock_response_bss['dateBlocked'] = '2022-09-05 11:41'
        self.mock_response_bss['blockStatus'] = 'KARTU DIBLOKIR VIA CDC_CORP'
        mock_inquiry_card_status.return_value = self.mock_response_bss
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_BLOCKED)
        self.assertEqual(response['data']['status'], CreditCardCodes.CARD_BLOCKED)

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_card_status_should_582_when_initial_card_satus_582_and_response_from_bss_block_card(
            self, mock_inquiry_card_status, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = '0'
        self.credit_card_application.status_id = CreditCardCodes.CARD_UNBLOCKED
        self.credit_card_application.save()
        self.credit_card_application.refresh_from_db()
        self.mock_response_bss['dateBlocked'] = '2022-09-05 11:41'
        self.mock_response_bss['blockStatus'] = 'KARTU DIBLOKIR VIA CDC_CORP'
        mock_inquiry_card_status.return_value = self.mock_response_bss
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(response['data']['status'], CreditCardCodes.CARD_UNBLOCKED)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_UNBLOCKED)

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_card_status_should_580_when_initial_card_satus_582_and_response_from_bss_active_card(
            self, mock_inquiry_card_status, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = '0'
        self.credit_card_application.status_id = CreditCardCodes.CARD_UNBLOCKED
        self.credit_card_application.save()
        self.credit_card_application.refresh_from_db()
        mock_inquiry_card_status.return_value = self.mock_response_bss
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200)
        response = json.loads(response.content)
        self.assertEqual(response['data']['status'], CreditCardCodes.CARD_ACTIVATED)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_ACTIVATED)

    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    def test_get_active_status_and_wrong_pin_two_times(self, mock_inquiry_card_status,
                                                       mock_redis_client, mock_get_julo_pn_client):
        self.mock_response_bss['incorrectPinCounter'] = '02'
        mock_redis_client.return_value.get.return_value = None
        mock_inquiry_card_status.return_value = self.mock_response_bss
        response = self.client.get(self.url_card_status)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(response['data']['status'], CreditCardCodes.CARD_ACTIVATED)
        self.assertEqual(
            response['data']['incorrect_pin_warning_message'],
            'Kamu sudah salah pin 2x, mohon berhati hati bila salah sekali akan terblokir otomatis'
        )
        self.assertTrue(mock_get_julo_pn_client.return_value.credit_card_notification.called)
        # test if incorrect pin warning pn already sent
        mock_redis_client.return_value.get.return_value = '1'
        self.client.get(self.url_card_status)
        self.assertTrue(mock_get_julo_pn_client.return_value.credit_card_notification.not_called)


class TestCardConfirmation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.pin = '123111'
        self.user.set_password(self.pin)
        self.user.save()
        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_ON_SHIPPING)
        StatusLookupFactory(status_code=CreditCardCodes.CARD_RECEIVED_BY_USER)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        self.url_card_confirmation = '/api/credit-card/v1/card/confirmation'

    def test_card_confirmation_success(self):
        response = self.client.post(self.url_card_confirmation, data={"pin": self.pin})
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertTrue(response['success'])
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_RECEIVED_BY_USER)

    def test_card_confirmation_failed_wrong_pin(self):
        response = self.client.post(self.url_card_confirmation, data={"pin": self.pin[:5] + '2'})
        self.assertEqual(response.status_code, 401, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_ON_SHIPPING)

    def test_card_confirmation_failed_wrong_card_status(self):
        self.credit_card_application.status = StatusLookupFactory(
            status_code=CreditCardCodes.CARD_APPLICATION_SUBMITTED
        )
        self.credit_card_application.save()
        self.credit_card_application.refresh_from_db()
        response = self.client.post(self.url_card_confirmation, data={"pin": self.pin})
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_APPLICATION_SUBMITTED)


class TestCardValidation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_RECEIVED_BY_USER)
        self.nik = '3203020101010006'
        self.customer = CustomerFactory(user=self.user, nik=self.nik)
        self.account = AccountFactory(customer=self.customer)
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_card_validation = '/api/credit-card/v1/card/validation'

    def test_card_validation_success(self):
        data = {
            'username': self.nik,
            'card_number': self.credit_card.card_number,
            'expire_date': self.credit_card.expired_date,
        }
        response = self.client.post(self.url_card_validation, data=data, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    def test_card_validation_failed_card_number_not_found(self):
        data = {
            'username': self.nik,
            'card_number': self.credit_card.card_number[:len(self.credit_card.card_number)-1] + '1',
            'expire_date': self.credit_card.expired_date,
        }
        response = self.client.post(self.url_card_validation, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)


@override_settings(BSS_CREDIT_CARD_HASHCODE='mockhash')
class TestSendOTP(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_RECEIVED_BY_USER)
        MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180
                },
                'wait_time_seconds': 400
            }
        )
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_send_otp = '/api/credit-card/v1/card/otp/send'

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.request_otp_value')
    @patch('juloserver.julo.tasks.send_sms_otp_token')
    def test_send_otp_success(self, mock_send_sms_otp_token, mock_request_otp_value):
        aes_cipher = AESCipher(self.credit_card.card_number)
        encrypted_otp = aes_cipher.encrypt('123456')
        mock_request_otp_value.return_value = {
            'responseCode': '00',
            'otpValue': encrypted_otp
        }
        data = {
            'transaction_type': OTPConstant.TRANSACTION_TYPE.new_pin
        }
        response = self.client.post(self.url_send_otp, data=data, format='json')
        self.assertEqual(response.status_code, 201, response.content)

    def test_send_otp_failed_invalid_transaction_type(self):
        data = {
            'transaction_type': 'failed'
        }
        response = self.client.post(self.url_send_otp, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)

    def test_send_otp_failed_not_eligible_status_card(self):
        status_blocked = StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED)
        self.credit_card_application.update_safely(status=status_blocked)
        self.credit_card_application.refresh_from_db()
        data = {
            'transaction_type': 'failed'
        }
        response = self.client.post(self.url_send_otp, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestCardActivation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_VALIDATED)
        StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.otp_request = OtpRequestFactory(otp_token='123456',
                                             action_type=OTPConstant.ACTION_TYPE.new_pin,
                                             customer=self.customer)
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        CreditCardStatusFactory(
            description=CreditCardStatusConstant.ACTIVE
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_card_activation = '/api/credit-card/v1/card/activation'

    @pytest.mark.skip(reason="Flaky")
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.set_new_pin')
    def test_card_activation_success(self, mock_set_new_pin):
        mock_set_new_pin.return_value = {'responseCode': '00'}
        data = {
            'otp': self.otp_request.otp_token,
            'pin': '159357',
        }
        response = self.client.post(self.url_card_activation, data=data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.credit_card_application.refresh_from_db()
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id, CreditCardCodes.CARD_ACTIVATED)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.ACTIVE)

    def test_card_activation_failed_pin_weak(self):
        data = {
            'otp': self.otp_request.otp_token,
            'pin': '123456',
        }
        response = self.client.post(self.url_card_activation, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_VALIDATED)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.ASSIGNED)

    def test_card_activation_failed_already_activated(self):
        data = {
            'otp': self.otp_request.otp_token,
            'pin': '123456',
        }
        self.credit_card_application.status_id = CreditCardCodes.CARD_ACTIVATED
        response = self.client.post(self.url_card_activation, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)


class TestLoginCardControlSystem(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.username = 'username_test'
        self.password = 'password_test'
        self.user = AuthUserFactory(username=self.username)
        self.client.force_authenticate(self.user)
        self.user.set_password(self.password)
        self.user.save()
        self.group_factory = GroupFactory(name=JuloUserRoles.CCS_AGENT)
        self.user.groups.add(self.group_factory)
        self.url_login_ccs = '/api/credit-card/v1/card-control-system/login'

    def test_login_card_control_system_success(self):
        data = {
            'username': self.username,
            'password': self.password
        }
        response = self.client.post(self.url_login_ccs, data=data, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    def test_login_card_control_system_failed_wrong_password(self):
        data = {
            'username': self.username,
            'password': self.password + '123123'
        }
        response = self.client.post(self.url_login_ccs, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)

    def test_login_card_control_system_failed_wrong_username(self):
        data = {
            'username': self.username + '123123',
            'password': self.password
        }
        response = self.client.post(self.url_login_ccs, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)

    def test_login_card_control_system_failed_wrong_username_and_password(self):
        data = {
            'username': self.username + '123123',
            'password': self.password + '123123'
        }
        response = self.client.post(self.url_login_ccs, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)

    def test_login_card_control_system_failed_ccs_agent_group_required(self):
        data = {
            'username': self.username,
            'password': self.password
        }
        self.user.groups.remove(self.group_factory)
        response = self.client.post(self.url_login_ccs, data=data, format='json')
        self.assertEqual(response.status_code, 403, response.content)
        response = json.loads(response.content)
        self.assertIn('User not allowed', response['errors'])


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestBlockCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        self.status_blocked = StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.CREDIT_CARD_BLOCK_REASON,
            parameters=['Berhenti menggunakan JULO card', 'Kartu hilang']
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        CreditCardStatusFactory(
            description=CreditCardStatusConstant.BLOCKED
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_block_card = '/api/credit-card/v1/card/block'
        self.url_block_reason = '/api/credit-card/v1/card/block/reason'

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.block_card')
    def test_block_card_success(self, mock_block_card):
        mock_block_card.return_value = {'responseCode': '00'}
        response = self.client.post(self.url_block_card,
                                    data={'block_reason': 'Berhenti menggunakan JULO card'})
        self.assertEqual(response.status_code, 200, response.content)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id, CreditCardCodes.CARD_BLOCKED,
                         response.content)

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.block_card')
    def test_block_card_failed(self, mock_block_card):
        self.credit_card_application.update_safely(
            status=self.status_blocked
        )
        mock_block_card.return_value = {'responseCode': '00'}
        response = self.client.post(self.url_block_card,
                                    data={'block_reason': 'Berhenti menggunakan JULO card'})
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertIn(ErrorMessage.FAILED_PROCESS, response['errors'])

    def test_get_block_reasons_success(self):
        response = self.client.get(self.url_block_reason)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertIsNotNone(response['data'])

    def test_get_block_reasons_not_found(self):
        self.feature_setting.update_safely(
            feature_name=FeatureNameConst.CREDIT_CARD_BLOCK_REASON + '_wrong'
        )
        response = self.client.get(self.url_block_reason)
        self.assertEqual(response.status_code, 404, response.content)
        response = json.loads(response.content)
        self.assertIsNone(response['data'])


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestUnblockCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_UNBLOCKED)
        StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image,
        )
        self.otp_request = OtpRequestFactory(otp_token='123456',
                                             action_type=OTPConstant.ACTION_TYPE.new_pin,
                                             customer=self.customer)
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        CreditCardStatusFactory(
            description=CreditCardStatusConstant.ACTIVE
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_unblock_card = '/api/credit-card/v1/card/unblock'

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.unblock_card')
    def test_unblock_card_success(self, mock_unblock_card):
        mock_unblock_card.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        data = {'pin': '123456'}
        response = self.client.post(self.url_unblock_card, data=data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.credit_card_application.refresh_from_db()
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id, CreditCardCodes.CARD_ACTIVATED)

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.unblock_card')
    def test_unblock_card_failed_transaction_from_bss(self, mock_unblock_card):
        mock_unblock_card.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code']
        }
        data = {'pin': '123456'}
        response = self.client.post(self.url_unblock_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.FAILED_PIN_RELATED,
            response['errors'],
        )

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.unblock_card')
    def test_unblock_card_credit_card_application_not_found(self, mock_unblock_card):
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        self.credit_card_application.account = account
        self.credit_card_application.save()
        mock_unblock_card.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        data = {'pin': '123456'}
        response = self.client.post(self.url_unblock_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.CREDIT_CARD_NOT_FOUND,
            response['errors'],
        )


class TestResetPinCreditCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.otp_request = OtpRequestFactory(otp_token='123456',
                                             action_type=OTPConstant.ACTION_TYPE.new_pin,
                                             customer=self.customer)
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ACTIVE
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_reset_pin_credit_card = '/api/credit-card/v1/card/pin/reset'
        self.correct_data = {'pin': '159357', 'otp': self.otp_request.otp_token}

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.reset_pin')
    def test_reset_pin_credit_card_success(self, mock_reset_pin, mock_redis_client):
        mock_reset_pin.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        response = self.client.post(self.url_reset_pin_credit_card, data=self.correct_data,
                                    format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.otp_request.refresh_from_db()
        self.assertTrue(self.otp_request.is_used)

    def test_reset_pin_credit_card_failed_weak_pin(self):
        data = {'pin': '123456', 'otp': self.otp_request.otp_token}
        response = self.client.post(self.url_reset_pin_credit_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.otp_request.refresh_from_db()
        self.assertFalse(self.otp_request.is_used)
        response = json.loads(response.content)
        self.assertIn(
            VerifyPinMsg.PIN_IS_TOO_WEAK,
            response['errors'],
        )

    def test_reset_pin_credit_card_failed_incorrect_otp(self):
        data = {'pin': '159357', 'otp': '123457'}
        response = self.client.post(self.url_reset_pin_credit_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.otp_request.refresh_from_db()
        self.assertFalse(self.otp_request.is_used)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.INCORRECT_OTP,
            response['errors'],
        )

    def test_reset_pin_card_credit_card_application_not_found(self):
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        self.credit_card_application.account = account
        self.credit_card_application.save()
        response = self.client.post(self.url_reset_pin_credit_card, data=self.correct_data,
                                    format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.otp_request.refresh_from_db()
        self.assertFalse(self.otp_request.is_used)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.CREDIT_CARD_NOT_FOUND,
            response['errors'],
        )

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.reset_pin')
    def test_reset_pin_card_failed_transaction_from_bss(self, mock_reset_pin):
        mock_reset_pin.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code']
        }
        response = self.client.post(self.url_reset_pin_credit_card, data=self.correct_data,
                                    format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.otp_request.refresh_from_db()
        self.assertFalse(self.otp_request.is_used)
        response = json.loads(response.content)
        self.assertIn(
            ErrorMessage.FAILED_PROCESS,
            response['errors'],
        )


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestCCSChangeCardStatus(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.ccs_agent = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.CCS_AGENT)
        self.ccs_agent.groups.add(self.group_factory)
        AgentFactory(user=self.ccs_agent)
        token = self.ccs_agent.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.user = AuthUserFactory()
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.CREDIT_CARD,
        )
        WorkflowStatusPathFactory(
            status_previous=581, status_next=583, type='happy', is_active=True,
            workflow=self.workflow,
        )
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ASSIGNED
        )
        CreditCardStatusFactory(
            description=CreditCardStatusConstant.CLOSED
        )
        CreditCardStatusFactory(
            description=CreditCardStatusConstant.ACTIVE
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_change_status = '/api/credit-card/v1/card-control-system/'\
                                 'credit-card-application/change-status'
        self.data = {
            "credit_card_application_id": self.credit_card_application.id,
            "next_status": CreditCardCodes.CARD_CLOSED,
            "change_reason": "Card Closed"
        }

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.close_card')
    def test_close_card_success(self, mock_close_card):
        mock_close_card.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        response = self.client.post(self.url_change_status, data=self.data, format='json')
        self.credit_card_application.refresh_from_db()
        self.credit_card.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_CLOSED)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.CLOSED)

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.close_card')
    def test_close_card_failed_current_status_is_not_blocked(self, mock_close_card):
        status_lookup_card_active = StatusLookupFactory(
            status_code=CreditCardCodes.CARD_ACTIVATED
        )
        self.credit_card_application.status = status_lookup_card_active
        self.credit_card_application.save()
        mock_close_card.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }

        response = self.client.post(self.url_change_status, data=self.data, format='json')
        self.credit_card_application.refresh_from_db()
        self.credit_card.refresh_from_db()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertNotEqual(self.credit_card_application.status_id,
                            CreditCardCodes.CARD_CLOSED)
        self.assertNotEqual(self.credit_card.credit_card_status.description,
                            CreditCardStatusConstant.CLOSED)

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.close_card')
    def test_close_card_failed_bss_error(self, mock_close_card):
        mock_close_card.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code']
        }
        response = self.client.post(self.url_change_status, data=self.data, format='json')
        self.credit_card_application.refresh_from_db()
        self.credit_card.refresh_from_db()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertNotEqual(self.credit_card_application.status_id,
                            CreditCardCodes.CARD_CLOSED)
        self.assertNotEqual(self.credit_card.credit_card_status.description,
                            CreditCardStatusConstant.CLOSED)


class TestReversalTransactionCreditCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score=u'A-',
            credit_matrix_id=self.credit_matrix.id
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=10000000,
            available_limit=10000000,
            latest_affordability_history=self.affordability_history,
            latest_credit_score=self.credit_score,
        )
        self.loan = LoanFactory(
            account=self.account,
            disbursement_id=888,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            transaction_method_id=10,
        )
        self.account_payment = AccountPaymentFactory(
            account=self.loan.account,
            due_amount=self.loan.loan_amount
        )
        PaymentFactory(
            loan=self.loan,
            account_payment=self.account_payment,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE),
            due_amount=self.loan.loan_amount,
        )
        today_datetime = timezone.localtime(timezone.now())
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED),
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.ASSIGNED
            ),
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.credit_card_transaction = CreditCardTransactionFactory(
            loan=self.loan,
            amount=1000000,
            fee=5000,
            transaction_date=today_datetime,
            reference_number='001',
            bank_reference='bank',
            terminal_type='terminal_type',
            terminal_id='t01',
            terminal_location='bandung',
            merchant_id='a001',
            acquire_bank_code='1234',
            destination_bank_code='bca',
            destination_account_number='12314',
            destination_account_name='ani',
            biller_code='341',
            biller_name='abc',
            customer_id='014312',
            hash_code='er23423rdasasfse',
            transaction_status="success",
            transaction_type=BSSTransactionConstant.EDC,
            credit_card_application=self.credit_card_application,
        )
        self.accounting_cutoff_date = AccountingCutOffDateFactory()
        self.url_reversal_transaction_credit_card = '/api/credit-card/v1/reversalCdcTransaction'
        self.payloads = {
            'transactionType': self.credit_card_transaction.transaction_type,
            'cardNumber': self.credit_card.card_number,
            'amount': self.credit_card_transaction.amount,
            'fee': self.credit_card_transaction.fee,
            'referenceNumber': self.credit_card_transaction.reference_number,
            'terminalType': self.credit_card_transaction.terminal_type,
            'terminalId': self.credit_card_transaction.terminal_id,
            'hashCode': self.credit_card_transaction.hash_code,
        }
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=220, status_next=215, workflow=self.workflow)

    def test_reversal_transaction_success(self):
        response = self.client.post(self.url_reversal_transaction_credit_card, data=self.payloads)
        self.loan.refresh_from_db()
        self.account_payment.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.TRANSACTION_FAILED)
        self.assertEqual(self.account_payment.status_id, PaymentStatusCodes.PAID_ON_TIME)

    def test_reversal_transaction_failed_transaction_not_found(self):
        self.payloads['referenceNumber'] = '1234'
        response = self.client.post(self.url_reversal_transaction_credit_card, data=self.payloads)
        self.assertEqual(response.status_code, 400)
        response = json.loads(response.content)
        self.assertEqual(response['responseCode'],
                         BSSResponseConstant.TRANSACTION_NOT_FOUND['code'])

    def test_reversal_transaction_failed_credit_card_not_found(self):
        self.payloads['cardNumber'] = '12312312'
        response = self.client.post(self.url_reversal_transaction_credit_card, data=self.payloads)
        self.assertEqual(response.status_code, 400)
        response = json.loads(response.content)
        self.assertEqual(response['responseCode'],
                         BSSResponseConstant.CARD_NOT_REGISTERED['code'])

    def test_reversal_transaction_failed_transaction_type_invalid(self):
        self.payloads['transactionType'] = 'transactionTypeInvalid'
        response = self.client.post(self.url_reversal_transaction_credit_card, data=self.payloads)
        self.assertEqual(response.status_code, 400)
        response = json.loads(response.content)
        self.assertEqual(response['responseCode'],
                         BSSResponseConstant.TRANSACTION_FAILED['code'])


class TestCCSCardApplicationList(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.ccs_agent = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.CCS_AGENT)
        self.ccs_agent.groups.add(self.group_factory)
        AgentFactory(user=self.ccs_agent)
        token = self.ccs_agent.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        status_codes = {CreditCardCodes.CARD_BLOCKED, CreditCardCodes.CARD_ACTIVATED,
                        CreditCardCodes.CARD_CLOSED, CreditCardCodes.CARD_UNBLOCKED}
        card_number_pattern = '581807150000645'
        virtual_account_number = '121230438830829'
        mobile_number_pattern = '085123456789'
        for idx, status_code in enumerate(status_codes):
            user = AuthUserFactory()
            customer = CustomerFactory(user=user)
            account = AccountFactory(customer=customer)
            ApplicationFactory(
                id=idx, customer=customer, application_xid=idx, account=account,
                email='email_{}@gmail.com'.format(idx),
                mobile_phone_1=mobile_number_pattern + str(idx)
            )
            address = AddressFactory(
                latitude=0.1,
                longitude=0.2,
                provinsi='Jawa Barat',
                kabupaten='Bandung',
                kecamatan='Cibeunying kaler',
                kelurahan='Cigadung',
                kodepos=12345,
                detail='jl cigadung'
            )
            image = ImageFactory(image_source=idx, image_type='selfie')
            credit_card_application = CreditCardApplicationFactory(
                id=idx,
                virtual_card_name='Jhon' + str(idx),
                virtual_account_number=virtual_account_number + str(idx),
                status=StatusLookupFactory(status_code=status_code),
                shipping_number=str(idx),
                address=address,
                account=account,
                image=image
            )
            credit_card_status = CreditCardStatusFactory(
                description=CreditCardStatusConstant.ASSIGNED
            )
            CreditCardFactory(
                card_number=card_number_pattern + str(idx),
                credit_card_status=credit_card_status,
                expired_date='12/21',
                credit_card_application=credit_card_application
            )
        self.url_card_application_list = '/api/credit-card/v1/card-control-system/' \
                                         'credit-card-application-list'

    def test_success_get_card_application_list_with_status_581(self):
        params = {
            'type': CreditCardCodes.CARD_BLOCKED,
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(response['data']['items'][0]['status'], CreditCardCodes.CARD_BLOCKED)
        self.assertEqual(len(response['data']['items']), 1)

    def test_success_get_card_application_list_with_status_580(self):
        params = {
            'type': CreditCardCodes.CARD_ACTIVATED,
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(response['data']['items'][0]['status'], CreditCardCodes.CARD_ACTIVATED)
        self.assertEqual(len(response['data']['items']), 1)

    def test_success_get_card_application_list_with_all_status_500s(self):
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 4)

    def test_get_card_application_list_not_found(self):
        params = {
            'type': CreditCardCodes.CARD_APPLICATION_SUBMITTED,
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 0)

    def test_get_card_application_list_status_card_not_valid(self):
        params = {
            'type': LoanStatusCodes.CURRENT,
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertIn(
            'Customer data is not listed',
            response['errors'],
        )

    def test_card_app_list_should_show_1_items_when_filter_by_correct_credit_card_application_id(
            self
    ):
        credit_card_application_id = 1
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'credit_card_application_id': credit_card_application_id,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 1)
        self.assertEqual(response['data']['items'][0]['credit_card_application_id'],
                         credit_card_application_id)

    def test_card_app_list_should_show_0_items_when_filter_by_incorrect_credit_card_application_id(
            self
    ):
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'credit_card_application_id': 200011111,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 0)

    def test_card_app_list_should_show_1_items_when_filter_correct_by_application_id(self):
        application_id = 1
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'application_id': application_id,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 1)
        self.assertEqual(response['data']['items'][0]['application_id'], application_id)

    def test_card_app_list_should_show_0_items_when_filter_by_incorrect_application_id(self):
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'application_id': 200011111,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 0)

    def test_card_app_list_should_show_1_items_when_filter_by_correct_email(self):
        email = "email_1@gmail.com"
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'email': email,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 1)
        self.assertEqual(response['data']['items'][0]['email'], email)

    def test_card_app_list_should_show_0_items_when_filter_by_incorrect_email(self):
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'email': "example_wrong_email@gmail.com",
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 0)

    def test_card_app_list_should_show_1_items_when_filter_by_correct_mobile_phone_number(self):
        mobile_phone_number = "0851234567891"
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'mobile_phone_number': mobile_phone_number,
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 1)
        self.assertEqual(response['data']['items'][0]['mobile_phone_number'], mobile_phone_number)

    def test_card_app_list_should_show_0_items_when_filter_by_incorrect_mobile_phone_number(self):
        params = {
            'last_id': 0,
            'order': 'desc',
            'limit': 10,
            'mobile_phone_number': "000000000",
        }
        response = self.client.get(self.url_card_application_list, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertEqual(len(response['data']['items']), 0)


class TestNotifyJuloCardStatusChange(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED_WRONG_PIN)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ACTIVE
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_notify_julo_card_status_change = '/api/credit-card/v1/notifyCardStatus'
        self.headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        self.data = {
            "cardNumber": self.credit_card.card_number,
            "referenceNumber": "01",
            "previousCardStatus": "success",
            "currentCardStatus": "pin tries",
            "description": "",
            "hashCode": "12uygfsa73ihj8"
        }

    def test_notify_julo_card_status_change_success(self):
        response = self.client.post(self.url_notify_julo_card_status_change,
                                    data=self.data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.credit_card_application.refresh_from_db()
        self.assertEqual(self.credit_card_application.status_id,
                         CreditCardCodes.CARD_BLOCKED_WRONG_PIN)

    def test_notify_julo_card_status_change_failed_blank_card_number(self):
        self.data["cardNumber"] = ""
        response = self.client.post(self.url_notify_julo_card_status_change,
                                    data=self.data, headers=self.headers)
        self.assertEqual(response.status_code, 400, response.content)
        self.credit_card_application.refresh_from_db()
        self.assertNotEqual(self.credit_card_application.status_id,
                            CreditCardCodes.CARD_BLOCKED_WRONG_PIN)
        response = json.loads(response.content)
        self.assertIn(
            BSSResponseConstant.TRANSACTION_FAILED['description'],
            response['responseDescription'],
        )

    def test_notify_julo_card_status_change_failed_card_number_doesnt_exists(self):
        self.data["cardNumber"] = self.data["cardNumber"][-2] + "12"
        response = self.client.post(self.url_notify_julo_card_status_change,
                                    data=self.data, headers=self.headers)
        self.assertEqual(response.status_code, 400, response.content)
        self.credit_card_application.refresh_from_db()
        self.assertNotEqual(self.credit_card_application.status_id,
                            CreditCardCodes.CARD_BLOCKED_WRONG_PIN)
        response = json.loads(response.content)
        self.assertIn(
            BSSResponseConstant.CARD_NOT_REGISTERED['description'],
            response['responseDescription'],
        )


class TestCCSCheckCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.ccs_agent = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.CCS_AGENT)
        self.ccs_agent.groups.add(self.group_factory)
        AgentFactory(user=self.ccs_agent)
        token = self.ccs_agent.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.UNASSIGNED
        )
        self.card_number = '1234567890123456'
        self.credit_card = CreditCardFactory(
            card_number=self.card_number,
            credit_card_status=credit_card_status,
            expired_date='12/21',
        )
        self.url_check_card = '/api/credit-card/v1/card-control-system/check-card'

    def test_check_card_should_success_when_card_number_is_correct(self):
        params = {
            'card_number': self.card_number,
        }
        response = self.client.get(self.url_check_card, data=params)
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertTrue(response['success'])

    def test_check_card_should_failed_when_card_number_is_incorrect(self):
        params = {
            'card_number': '0000000000',
        }
        response = self.client.get(self.url_check_card, data=params)
        self.assertEqual(response.status_code, 404, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.assertIn(
            ErrorMessage.CARD_NUMBER_INVALID,
            response['errors'],
        )

    def test_check_card_should_failed_when_card_number_already_assign(self):
        credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_ACTIVATED
        )
        self.credit_card.update_safely(credit_card_application=credit_card_application)
        params = {
            'card_number': self.card_number,
        }
        response = self.client.get(self.url_check_card, data=params)
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.assertIn(
            ErrorMessage.CARD_NUMBER_NOT_AVAILABLE,
            response['errors'],
        )


class TestCCSAssignCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.ccs_agent = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.CCS_AGENT)
        self.ccs_agent.groups.add(self.group_factory)
        AgentFactory(user=self.ccs_agent)
        token = self.ccs_agent.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.credit_card = CreditCardFactory(
            card_number='1234567890123456',
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.UNASSIGNED
            ),
            expired_date='12/21',
        )
        self.credit_card_1 = CreditCardFactory(
            card_number='1234567890123457',
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.UNASSIGNED
            ),
            expired_date='12/21',
        )
        self.credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_APPLICATION_SUBMITTED
        )
        self.url_check_card = '/api/credit-card/v1/card-control-system/assign-card'
        CreditCardStatusFactory(description=CreditCardStatusConstant.ASSIGNED)

    def test_assign_card_should_success_when_payloads_is_correct(self):
        payloads = {
            'card_number': self.credit_card.card_number,
            'credit_card_application_id': self.credit_card_application.id,
        }
        response = self.client.post(self.url_check_card, data=payloads, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        response = json.loads(response.content)
        self.assertTrue(response['success'])
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card.credit_card_application_id,
                         self.credit_card_application.id)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.ASSIGNED)

    def test_assign_card_should_failed_when_card_number_is_incorrect(self):
        payloads = {
            'card_number': "0000000000000",
            'credit_card_application_id': self.credit_card_application.id,
        }
        response = self.client.post(self.url_check_card, data=payloads, format='json')
        self.assertEqual(response.status_code, 404, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.assertIn(
            ErrorMessage.CARD_NUMBER_INVALID,
            response['errors'],
        )
        self.credit_card.refresh_from_db()
        self.assertIsNone(self.credit_card.credit_card_application_id)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.UNASSIGNED)

    def test_assign_card_should_failed_when_card_app_id_is_incorrect(self):
        payloads = {
            'card_number': self.credit_card.card_number,
            'credit_card_application_id': 1111111111,
        }
        response = self.client.post(self.url_check_card, data=payloads, format='json')
        self.assertEqual(response.status_code, 404, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.assertIn(
            ErrorMessage.CARD_APPLICATION_ID_INVALID,
            response['errors'],
        )
        self.credit_card.refresh_from_db()
        self.assertIsNone(self.credit_card.credit_card_application_id)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.UNASSIGNED)

    def test_assign_card_should_failed_when_card_already_assign(self):
        credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_ACTIVATED
        )
        self.credit_card.update_safely(credit_card_application=credit_card_application)
        payloads = {
            'card_number': self.credit_card.card_number,
            'credit_card_application_id': self.credit_card_application.id,
        }
        response = self.client.post(self.url_check_card, data=payloads, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.assertIn(
            ErrorMessage.CARD_NUMBER_NOT_AVAILABLE,
            response['errors'],
        )
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card.credit_card_application_id, credit_card_application.id)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.UNASSIGNED)

    def test_assign_card_should_failed_when_card_application_has_assigned_credit_card(self):
        self.credit_card.update_safely(
            credit_card_application=self.credit_card_application,
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.ASSIGNED
            ),
        )
        self.credit_card.refresh_from_db()
        payloads = {
            'card_number': self.credit_card_1.card_number,
            'credit_card_application_id': self.credit_card_application.id,
        }
        response = self.client.post(self.url_check_card, data=payloads, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = json.loads(response.content)
        self.assertFalse(response['success'])
        self.assertIn(
            ErrorMessage.CARD_APPLICATION_HAS_CARD_NUMBER,
            response['errors'],
        )
        self.credit_card.refresh_from_db()
        self.assertEqual(self.credit_card.credit_card_application_id,
                         self.credit_card_application.id)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.ASSIGNED)

    def test_assign_card_should_success_when_card_application_has_closed_credit_card(self):
        self.credit_card.update_safely(
            credit_card_application=self.credit_card_application,
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.CLOSED
            ),
        )
        self.credit_card.refresh_from_db()
        payloads = {
            'card_number': self.credit_card_1.card_number,
            'credit_card_application_id': self.credit_card_application.id,
        }
        response = self.client.post(self.url_check_card, data=payloads, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.credit_card_1.refresh_from_db()
        self.assertEqual(self.credit_card_1.credit_card_application_id,
                         self.credit_card_application.id)
        self.assertEqual(self.credit_card.credit_card_status.description,
                         CreditCardStatusConstant.CLOSED)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestUploadJuloCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.ccs_agent = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.CCS_AGENT)
        self.ccs_agent.groups.add(self.group_factory)
        AgentFactory(user=self.ccs_agent)
        token = self.ccs_agent.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.url_check_card = '/api/credit-card/v1/card/upload/no'
        self.csv_file = StringIO(
            "Nomor Kartu,Expired Date (MMYY),\n"
            "5301234567,1222,\n"
            "5301234568,1022\n"
            "5301234569,1122"
        )
        self.card_status_unassigned = CreditCardStatusFactory(
            description=CreditCardStatusConstant.UNASSIGNED
        )

    def test_upload_julo_card_should_created_3_row(self):
        data = {
            'credit_card_csv': self.csv_file
        }
        response = self.client.post(self.url_check_card, data=data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CreditCard.objects.all().count(), 3)

    def test_upload_julo_card_should_created_2_row_when_got_1_duplicate_card_number(self):
        existing_credit_card = CreditCardFactory(
            card_number="5301234567",
            credit_card_status=self.card_status_unassigned,
            expired_date="1222",
        )
        data = {
            'credit_card_csv': self.csv_file
        }
        response = self.client.post(self.url_check_card, data=data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CreditCard.objects.exclude(pk=existing_credit_card.id).count(), 2)

    def test_upload_julo_card_should_created_0_row_when_csv_file_is_missing(self):
        data = {
            'credit_card_csv': None
        }
        response = self.client.post(self.url_check_card, data=data)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(CreditCard.objects.all().count(), 0)


class TestTransactionJuloCard(TestCase):
    def setUp(self):
        self.client = APIClient()
        customer = CustomerFactory()
        self.account = AccountFactory(
            customer=customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        application = ApplicationFactory(
            customer=customer, application_xid=123, account=self.account
        )
        affordability_history = AffordabilityHistoryFactory(application=application)
        product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=application.product_line,
            max_duration=8,
            min_duration=1,
        )
        credit_score = CreditScoreFactory(
            application_id=application.id,
            score=u'A-',
            credit_matrix_id=self.credit_matrix.id
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=10000000,
            available_limit=10000000,
            latest_affordability_history=affordability_history,
            latest_credit_score=credit_score,
        )
        TransactionMethodFactory(
            id=TransactionMethodCode.CREDIT_CARD.code,
            method=TransactionMethodCode.CREDIT_CARD.name,
            transaction_category=TransactionCategoryFactory(fe_display_name="Belanja"),
        )
        address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED),
            shipping_number='01122',
            address=address,
            account=self.account,
            image=image
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.ASSIGNED
            ),
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_julo_card_transaction = "/api/credit-card/v1/cdcTransaction"
        self.payloads = {
            'transactionType': "DEBIT.EDC",
            'cardNumber': self.credit_card.card_number,
            'amount': '300000',
            'fee': '0',
            'dateTime': '202207131700',
            'referenceNumber': 'Testtrx01',
            'bankReference': 'TERMINALEDC000000138266',
            'terminalType': '6012',
            'terminalId': 'TERMINALEDC000000138266',
            'terminalLocation': 'PT.RINTIS SEJAHTERA JAKARTA',
            'merchantId': '001',
            'acquireBankCode': 'RINTISBANK',
            'destinationBankCode': '523',
            'hashCode': 'a866a23aab4e03a188187dce58e972b6'
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CARD_ON_OFF,
            is_active=True,
            description='for turn off/on julo card transaction',
            category='julo card'
        )

    @patch(
        'juloserver.credit_card.services.transaction_related.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    @patch('juloserver.credit_card.views.views_api_v1.upload_sphp_loan_credit_card_to_oss')
    def test_julo_card_transaction_should_success_when_tenor_options_more_than_1(
            self, mock_upload_sphp_loan_credit_card_to_oss, mock_get_julo_pn_client,
            mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        response = self.client.post(self.url_julo_card_transaction, data=self.payloads)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(mock_get_julo_pn_client.return_value.credit_card_notification.called)
        arguments = \
            mock_get_julo_pn_client.return_value.credit_card_notification.call_args_list[0][0]
        pn_contents = arguments[1:]
        # check PN content change tenor
        self.assertEqual(tuple(PushNotificationContentsConst.CHANGE_TENOR.values()),
                         pn_contents)
        loan = Loan.objects.filter(loan_disbursement_amount=int(self.payloads['amount'])).last()
        # check if the loan duration is the longest tenor options
        tenor_options = get_loan_duration(
            int(self.payloads['amount']),
            self.credit_matrix_product_line.max_duration,
            self.credit_matrix_product_line.min_duration,
            self.account_limit.set_limit,
            customer=self.account.customer,
        )
        credit_card_transaction = loan.creditcardtransaction_set.last()
        self.assertEqual(loan.loan_duration, max(tenor_options))
        self.assertEqual(credit_card_transaction.tenor_options, tenor_options)

    @patch(
        'juloserver.credit_card.services.transaction_related.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    @patch('juloserver.credit_card.views.views_api_v1.upload_sphp_loan_credit_card_to_oss')
    def test_julo_card_transaction_should_success_when_tenor_options_only_1(
            self, mock_upload_sphp_loan_credit_card_to_oss, mock_get_julo_pn_client,
            mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        self.payloads['amount'] = '50000'
        self.credit_matrix_product_line.update_safely(max_duration=1, min_duration=1)
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        response = self.client.post(self.url_julo_card_transaction, data=self.payloads)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(mock_get_julo_pn_client.return_value.credit_card_notification.called)
        arguments = \
            mock_get_julo_pn_client.return_value.credit_card_notification.call_args_list[0][0]
        pn_contents = arguments[1:]
        # check PN template code completed transaction
        self.assertEqual(PushNotificationContentsConst.TRANSACTION_COMPLETED.get('template_code'),
                         pn_contents[2])
        # check if the loan duration is the longest tenor options
        loan = Loan.objects.last()
        credit_card_transaction = loan.creditcardtransaction_set.last()
        self.assertEqual(loan.loan_duration, 1)
        self.assertEqual(credit_card_transaction.tenor_options, [1])

    @patch(
        'juloserver.credit_card.services.transaction_related.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_julo_card_transaction_should_failed_when_account_status_is_not_eligible(
            self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        self.account.update_safely(
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        )
        response = self.client.post(self.url_julo_card_transaction, data=self.payloads)
        self.assertEqual(response.status_code, 400, response.content)

    @patch(
        'juloserver.credit_card.services.transaction_related.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_julo_card_transaction_should_failed_when_account_limit_not_enough(
            self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        self.account_limit.update_safely(available_limit=0)
        response = self.client.post(self.url_julo_card_transaction, data=self.payloads)
        self.assertEqual(response.status_code, 400, response.content)

    def test_julo_card_transaction_should_failed_when_julo_card_is_blocked(self):
        self.credit_card_application.update_safely(
            status=StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED)
        )
        response = self.client.post(self.url_julo_card_transaction, data=self.payloads)
        self.assertEqual(response.status_code, 400, response.content)

    @patch(
        'juloserver.credit_card.services.transaction_related.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_julo_card_transaction_should_failed_when_julo_card_transaction_turned_off(
            self, mock_get_credit_matrix_and_credit_matrix_product_line
    ):
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        self.feature_setting.update_safely(
            is_active=False
        )
        response = self.client.post(self.url_julo_card_transaction, data=self.payloads)
        self.assertEqual(response.status_code, 400, response.content)


class TestChangePinJuloCard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.status_lookup = StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED)
        self.customer = CustomerFactory(user=self.user,
                                        nik='3203020101320001')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=self.status_lookup,
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.otp_request = OtpRequestFactory(otp_token='123456',
                                             action_type=OTPConstant.ACTION_TYPE.new_pin,
                                             customer=self.customer)
        self.credit_card_status = CreditCardStatusFactory(
            description=CreditCardStatusConstant.ACTIVE
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=self.credit_card_status,
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        self.url_change_pin_credit_card = '/api/credit-card/v1/card/pin/change'

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.change_pin')
    def test_change_pin_credit_card_success(self, mock_change_pin):
        mock_change_pin.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        data = {'old_pin': '159357', 'new_pin': '159358'}
        response = self.client.post(self.url_change_pin_credit_card, data=data, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.change_pin')
    def test_change_pin_failed_weak_pin(self, mock_change_pin):
        mock_change_pin.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        data = {'old_pin': '159357', 'new_pin': '123456'}
        response = self.client.post(self.url_change_pin_credit_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()
        self.assertIn(VerifyPinMsg.PIN_IS_TOO_WEAK, response['errors'])

    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.change_pin')
    def test_change_pin_failed_dob_pin(self, mock_change_pin):
        mock_change_pin.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code']
        }
        data = {'old_pin': '159357', 'new_pin': '010132'}
        response = self.client.post(self.url_change_pin_credit_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()
        self.assertIn(VerifyPinMsg.PIN_IS_DOB, response['errors'])

    @patch('juloserver.credit_card.services.card_related.get_redis_client')
    @patch('juloserver.credit_card.tasks.notification_tasks.get_julo_pn_client')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.inquiry_card_status')
    @patch('juloserver.credit_card.clients.bss.BSSCreditCardClient.change_pin')
    def test_change_pin_failed_user_input_wrong_pin(
            self, mock_change_pin, mock_inquiry_card_status, mock_get_julo_pn_client,
            mock_redis_client
    ):
        mock_change_pin.return_value = {
            'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code']
        }
        mock_inquiry_card_status.return_value = {
            'responseCode': '00',
            'responseDescription': 'SUCCEED',
            'cardStatus': 'ACTIVE',
            'blockStatus': '',
            'accountNumber': '1021785136',
            'accountHolderName': 'PT, FINANCE',
            'incorrectPinCounter': '02',
            'dateCardLinked': '2022-08-15 00:00',
            'dateLastUsed': '2022-09-05 00:00',
            'dateBlocked': '',
            'dateClosed': ''
        }
        mock_redis_client.return_value.get.return_value = None
        data = {'old_pin': '159357', 'new_pin': '159311'}
        response = self.client.post(self.url_change_pin_credit_card, data=data, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()
        self.assertIn(ErrorMessage.FAILED_PIN_RELATED, response['errors'])
        self.assertTrue(mock_get_julo_pn_client.return_value.credit_card_notification.called)
        # test if incorrect pin warning pn already sent
        mock_redis_client.return_value.get.return_value = '1'
        self.client.post(self.url_change_pin_credit_card, data=data, format='json')
        self.assertTrue(mock_get_julo_pn_client.return_value.credit_card_notification.not_called)


class TestJuloCardBanner(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user,
                                        nik='3203020101320001')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        JuloCardBannerFactory(
            id=1,
            name='banner test a',
            click_action='home page',
            banner_type='DEEP_LINK',
            image=ImageFactory(image_source=1, image_type='julo_card_banner_image'),
            is_active=True,
            display_order=1
        )
        JuloCardBannerFactory(
            id=2,
            name='banner test b',
            click_action='home page',
            banner_type='DEEP_LINK',
            image=ImageFactory(image_source=2, image_type='julo_card_banner_image'),
            is_active=True,
            display_order=2
        )

    def test_get_julo_card_banner_success(self):
        response = self.client.get('/api/credit-card/v1/banner')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(len(response['data']), 2)
        self.assertEqual(response['data'][0]['display_order'], 1)
        self.assertEqual(response['data'][1]['display_order'], 2)


class TestTransactionHistory(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, application_xid=123, account=self.account
        )
        self.affordability_history = AffordabilityHistoryFactory(application=self.application)
        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score=u'A-',
            credit_matrix_id=self.credit_matrix.id
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=10000000,
            available_limit=10000000,
            latest_affordability_history=self.affordability_history,
            latest_credit_score=self.credit_score,
        )
        self.address = AddressFactory(
            latitude=0.1,
            longitude=0.2,
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Cibeunying kaler',
            kelurahan='Cigadung',
            kodepos=12345,
            detail='jl cigadung'
        )
        self.image = ImageFactory(image_source=3332, image_type='selfie')
        self.credit_card_application = CreditCardApplicationFactory(
            virtual_card_name='Jhon',
            virtual_account_number='112233',
            status=StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED),
            shipping_number='01122',
            address=self.address,
            account=self.account,
            image=self.image
        )
        self.credit_card = CreditCardFactory(
            card_number='5818071500006459',
            credit_card_status=CreditCardStatusFactory(
                description=CreditCardStatusConstant.ASSIGNED
            ),
            expired_date='12/21',
            credit_card_application=self.credit_card_application
        )
        today_datetime = timezone.localtime(timezone.now())
        for i in range(1, 61):
            loan = LoanFactory(
                account=self.account,
                loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
                transaction_method_id=10,
                loan_xid=i,
            )
            CreditCardTransactionFactory(
                id=i,
                loan=loan,
                amount=1000000,
                fee=5000,
                transaction_date=(today_datetime - timedelta(hours=i)),
                reference_number=str(i),
                bank_reference='bank',
                terminal_type='terminal_type',
                terminal_id='t01',
                terminal_location='bandung',
                merchant_id='a001',
                acquire_bank_code='1234',
                destination_bank_code='bca',
                destination_account_number='12314',
                destination_account_name='ani',
                biller_code='341',
                biller_name='abc',
                customer_id='014312',
                hash_code='er23423rdasasfse',
                transaction_status="success",
                transaction_type=BSSTransactionConstant.EDC,
                credit_card_application=self.credit_card_application,
            )
        self.url_transaction_history = '/api/credit-card/v1/card/transaction-history'

    def test_transaction_history_should_success(self):
        response = self.client.get(self.url_transaction_history)
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(len(response['data']['transaction_history_data']), 50)
        self.assertEqual(
            response['data']['transaction_history_data'][0]['credit_card_transaction_id'], 60
        )
        self.assertEqual(
            response['data']['transaction_history_data'][-1]['credit_card_transaction_id'], 11
        )
        data = {
            'credit_card_transaction_id': response['data']['last_credit_card_transaction_id']
        }
        response = self.client.get(self.url_transaction_history, data=data)
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(len(response['data']['transaction_history_data']), 10)
        self.assertEqual(
            response['data']['transaction_history_data'][0]['credit_card_transaction_id'], 10
        )
        self.assertEqual(
            response['data']['transaction_history_data'][-1]['credit_card_transaction_id'], 1
        )
        data = {'limit': 20}
        response = self.client.get(self.url_transaction_history, data=data)
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(len(response['data']['transaction_history_data']), 20)
        self.assertEqual(
            response['data']['transaction_history_data'][0]['credit_card_transaction_id'], 60
        )
        self.assertEqual(
            response['data']['transaction_history_data'][-1]['credit_card_transaction_id'], 41
        )

    def test_transaction_history_should_fail_when_customer_has_no_julo_card(self):
        self.credit_card_application.update_safely(
            account=AccountFactory()
        )
        self.credit_card_application.refresh_from_db()
        response = self.client.get(self.url_transaction_history)
        self.assertEqual(response.status_code, 400, response.content)

    def test_transaction_history_should_fail_return_empty_when_customer_has_no_transaction(self):
        CreditCardTransaction.objects.all().delete()
        response = self.client.get(self.url_transaction_history)
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(response['data'], None)

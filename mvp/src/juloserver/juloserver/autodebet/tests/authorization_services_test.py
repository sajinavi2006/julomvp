from django.test.testcases import TestCase

from mock import patch
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory,
    AutodebetMandiriAccountFactory
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
    DeviceFactory,
)

from juloserver.autodebet.constants import (
    FeatureNameConst,
    CallbackAuthorizationErrorResponseConst,
)
from juloserver.julo.constants import FeatureNameConst as JuloConst
from juloserver.autodebet.services.authorization_services import (
    process_account_registration,
    validate_callback_process_account_authorization,
    callback_process_account_authorization,
    process_account_revocation,
    process_reset_autodebet_account,
    get_revocation_status,
    validate_existing_autodebet_account,
    get_gopay_wallet_token,
    update_gopay_wallet_token,
    check_gopay_wallet_token_valid,
    gopay_registration_autodebet,
    gopay_autodebet_revocation,
)
from juloserver.julo.models import PaymentMethod

from juloserver.payback.tests.factories import GopayAccountLinkStatusFactory
from juloserver.payback.models import GopayAccountLinkStatus


class TestAutodebetAuthorizationServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.current_ts = timezone.localtime(timezone.now())
        cls.feature_setting = FeatureSettingFactory(feature_name=FeatureNameConst.AUTODEBET_BCA)
        cls.whitelist_setting = FeatureSettingFactory()
        cls.user = AuthUserFactory()
        cls.customer = CustomerFactory(user=cls.user, fullname='customer name 1')
        cls.account = AccountFactory(customer=cls.customer)
        cls.application = ApplicationFactory(customer=cls.customer, account=cls.account)
        cls.gopay_account_link_status = GopayAccountLinkStatusFactory(
            account=cls.account,
            token='eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ==',
        )
        cls.feature_setting_gopay = FeatureSettingFactory(
            feature_name=JuloConst.GOPAY_ACTIVATION_LINKING)
        cls.device = DeviceFactory(customer=cls.customer)

    def setUp(self):
        self.autodebet_account = AutodebetAccountFactory(account=self.account)
        self.application.application_xid = "1234567899"
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()
        self.callback_data = {
            "request_id": "uniquerequestid",
            "customer_id_merchant": self.application.application_xid,
            "customer_name": self.application.fullname,
            "db_account_no": "1234567890",
            "status": "01",
            "reason": "success",
        }

    @patch('juloserver.autodebet.clients.AutodebetBCAClient.send_request')
    def test_process_account_registration(self, mock_client_send_request):
        self.autodebet_account.registration_ts = self.current_ts
        self.autodebet_account.save()
        data, error_message, is_forbidden = process_account_registration(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Account sedang dalam proses registrasi")
        self.assertTrue(is_forbidden)

        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.save()
        data, error_message, is_forbidden = process_account_registration(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Account autodebet sedang aktif")
        self.assertTrue(is_forbidden)

        mock_client_send_request.return_value = ({}, "Failed Mock Response")
        self.autodebet_account.delete()
        data, error_message, is_forbidden = process_account_registration(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Failed Mock Response")
        self.assertFalse(is_forbidden)

        mock_client_send_request.return_value = (
            {"request_id": "uniquerequestid", "random_string": "randomstring"},
            None
        )
        data, error_message, is_forbidden = process_account_registration(self.account)
        self.assertTrue("webview_url" in data.keys())
        self.assertIsNone(error_message)
        self.assertFalse(is_forbidden)

    def test_validate_callback_process_account_authorization(self):
        success, response = validate_callback_process_account_authorization(self.callback_data)
        self.assertFalse(success)
        self.assertEqual(response, CallbackAuthorizationErrorResponseConst.ERR444)

        self.autodebet_account.request_id = self.callback_data["request_id"]
        self.autodebet_account.save()
        success, response = validate_callback_process_account_authorization(self.callback_data)
        self.assertTrue(success)
        self.assertIsNone(response)

        self.callback_data["customer_id_merchant"] = "1029384756"
        success, response = validate_callback_process_account_authorization(self.callback_data)
        self.assertFalse(success)
        self.assertEqual(response, CallbackAuthorizationErrorResponseConst.ERR111)

    @patch('slackclient.SlackClient.api_call')
    def test_callback_process_account_authorization(self, mock_slack_api_call):
        mock_slack_api_call.return_value = {}
        self.autodebet_account.request_id = self.callback_data["request_id"]
        self.autodebet_account.save()
        prev_autodebet_account = self.autodebet_account
        callback_process_account_authorization(self.callback_data)
        self.autodebet_account.refresh_from_db()
        self.assertIsNotNone(self.autodebet_account.activation_ts)
        self.assertTrue(self.autodebet_account.is_use_autodebet)
        self.assertFalse(self.autodebet_account.is_deleted_autodebet)
        self.assertEqual(self.autodebet_account.db_account_no, self.callback_data["db_account_no"])
        payment_method = PaymentMethod.objects.filter(customer=self.customer, payment_method_name="Autodebet BCA")
        self.assertIsNotNone(payment_method)

        self.callback_data["status"] = "02"
        self.callback_data["reason"] = "Failed activation process"
        callback_process_account_authorization(self.callback_data)
        self.autodebet_account.refresh_from_db()
        self.assertIsNotNone(self.autodebet_account.failed_ts)
        self.assertFalse(self.autodebet_account.is_use_autodebet)
        self.assertFalse(self.autodebet_account.is_deleted_autodebet)
        self.assertEqual(self.autodebet_account.failed_reason, "Failed activation process")

        self.callback_data["status"] = "03"
        callback_process_account_authorization(self.callback_data)
        self.autodebet_account.refresh_from_db()
        self.assertIsNotNone(self.autodebet_account.deleted_success_ts)
        self.assertFalse(self.autodebet_account.is_use_autodebet)
        self.assertTrue(self.autodebet_account.is_deleted_autodebet)

        self.callback_data["status"] = "04"
        self.callback_data["reason"] = "Failed revocation process"
        callback_process_account_authorization(self.callback_data)
        self.autodebet_account.refresh_from_db()
        self.assertIsNotNone(self.autodebet_account.deleted_failed_ts)
        self.assertFalse(self.autodebet_account.is_use_autodebet)
        self.assertFalse(self.autodebet_account.is_deleted_autodebet)
        self.assertEqual(self.autodebet_account.deleted_failed_reason, "Failed revocation process")

        self.autodebet_account = prev_autodebet_account
        self.callback_data["request_id"] = "1029384756"
        callback_process_account_authorization(self.callback_data)
        self.autodebet_account.refresh_from_db()
        self.assertFalse(self.autodebet_account.is_use_autodebet)

    @patch('juloserver.autodebet.clients.AutodebetBCAClient.send_request')
    def test_process_account_revocation(self, mock_client_send_request):
        self.autodebet_account.registration_ts = self.current_ts
        self.autodebet_account.save()
        data, error_message = process_account_revocation(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Account autodebet belum pernah di aktivasi")

        self.autodebet_account.activation_ts = self.current_ts
        self.autodebet_account.save()
        data, error_message = process_account_revocation(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Account autodebet tidak aktif")

        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.save()
        data, error_message = process_account_revocation(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Account autodebet tidak aktif")

        self.autodebet_account.db_account_no = self.callback_data["db_account_no"]
        self.autodebet_account.save()
        mock_client_send_request.return_value = ({}, "Failed Mock Response")
        data, error_message = process_account_revocation(self.account)
        self.assertEqual(data, {})
        self.assertEqual(error_message, "Failed Mock Response")

        mock_client_send_request.return_value = (self.callback_data, None)
        data, error_message = process_account_revocation(self.account)
        self.assertEqual(data, self.callback_data)
        self.assertIsNone(error_message)

    def test_process_reset_autodebet_account(self):
        self.assertIsNone(process_reset_autodebet_account(self.account))

    def test_get_revocation_status(self):
        self.autodebet_account.deleted_request_ts = self.current_ts
        self.autodebet_account.is_deleted_autodebet = False
        self.autodebet_account.save()
        self.assertTrue(get_revocation_status(self.account))

        self.autodebet_account.deleted_request_ts = None
        self.autodebet_account.save()
        self.assertFalse(get_revocation_status(self.account))

        self.autodebet_account.delete()
        self.assertFalse(get_revocation_status(self.account))

    def test_validate_existing_autodebet_account(self):
        _, error, _ = validate_existing_autodebet_account(self.account, 'BNIasd123123')
        self.assertEqual(error, 'Vendor tidak tersedia')

    @patch('juloserver.autodebet.services.authorization_services.get_gopay_client')
    def test_get_gopay_wallet_token_should_success(self, mock_get_gopay_client):
        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "GOPAY_WALLET",
                        "active": True,
                        "balance": {
                            "value": "1000000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ=="
                    },
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {
                            "value": "350000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
                    }
                ]
            }
        }
        token = get_gopay_wallet_token(self.account)
        self.assertEqual(token, 'eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ==')

    @patch('juloserver.autodebet.services.authorization_services.get_gopay_client')
    def test_get_gopay_wallet_token_should_failed_when_gopay_wallet_token_not_found(
            self, mock_get_gopay_client
    ):
        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {
                            "value": "350000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
                    }
                ]
            }
        }
        token = get_gopay_wallet_token(self.gopay_account_link_status.pay_account_id)
        self.assertIsNone(token)

    def test_update_gopay_wallet_token_should_success(self):
        new_token = 'new_token'
        update_gopay_wallet_token(self.account, new_token)
        gopay_account_link_status = GopayAccountLinkStatus.objects.get(account=self.account)
        self.assertEqual(gopay_account_link_status.token, new_token)

    def test_update_gopay_wallet_token_should_failed_when_gopay_account_link_status_not_found(self):
        new_token = 'new_token'
        self.gopay_account_link_status.update_safely(account=AccountFactory())
        update_gopay_wallet_token(self.account, new_token)
        self.assertNotEqual(self.gopay_account_link_status.token, new_token)

    @patch('juloserver.autodebet.services.authorization_services.get_gopay_client')
    def test_check_gopay_wallet_token_valid_should_success(self, mock_get_gopay_client):
        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "GOPAY_WALLET",
                        "active": True,
                        "balance": {
                            "value": "1000000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ=="
                    },
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {
                            "value": "350000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
                    }
                ]
            }
        }
        is_valid, token = check_gopay_wallet_token_valid(self.account)
        self.assertTrue(is_valid)
        self.gopay_account_link_status.refresh_from_db()
        self.assertEqual(self.gopay_account_link_status.token, token)

    @patch('juloserver.autodebet.services.authorization_services.get_gopay_client')
    def test_check_gopay_wallet_token_valid_should_failed(self, mock_get_gopay_client):
        mock_get_gopay_client().get_pay_account.return_value = {
            "status_code": "200",
            "payment_type": "gopay",
            "account_id": "00000269-7836-49e5-bc65-e592afafec14",
            "account_status": "ENABLED",
            "metadata": {
                "payment_options": [
                    {
                        "name": "GOPAY_WALLET",
                        "active": True,
                        "balance": {
                            "value": "1000000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIkdPUEFZX1dBTExFVCIsICJpZCI6ICIifQ=="
                    },
                    {
                        "name": "PAY_LATER",
                        "active": True,
                        "balance": {
                            "value": "350000.00",
                            "currency": "IDR"
                        },
                        "metadata": {},
                        "token": "eyJ0eXBlIjogIlBBWV9MQVRFUiIsICJpZCI6ICIifQ=="
                    }
                ]
            }
        }
        self.gopay_account_link_status.update_safely(token='different_token')
        is_valid, token = check_gopay_wallet_token_valid(self.account)
        self.assertFalse(is_valid)
        self.assertNotEqual(self.gopay_account_link_status.token, token)

    def test_get_check_gopay_wallet_token_valid_should_failed_when_gopay_link_not_found(self):
        GopayAccountLinkStatus.objects.all().delete()
        self.assertIsNone(check_gopay_wallet_token_valid(self.account))

    def test_registration_gopay_autodebet(self):
        self.gopay_account_link_status.status = 'ENABLED'
        self.gopay_account_link_status.save()
        message, status = gopay_registration_autodebet(self.account)
        self.assertEqual(message, 'Aktivasi GoPay Autodebet Berhasil!')

        self.feature_setting_gopay.is_active = False
        self.feature_setting_gopay.save()

        message, status = gopay_registration_autodebet(self.account)
        self.assertEqual(message, 'Fitur autodebet sedang tidak aktif')

    def test_revocation_gopay_autodebet(self):
        self.autodebet_account.delete()
        self.gopay_account_link_status.status = 'ENABLED'
        self.gopay_account_link_status.save()
        gopay_registration_autodebet(self.account)
        message, status = gopay_autodebet_revocation(self.account)
        self.assertEqual(message, 'Nonaktifkan Autodebet GoPay berhasil')

        gopay_registration_autodebet(self.account)
        self.autodebet_account = AutodebetAccount.objects.filter(account=self.account).last()
        self.autodebet_account.is_use_autodebet = False
        self.autodebet_account.save()
        message, status = gopay_autodebet_revocation(self.account)
        self.assertEqual(message, 'Account autodebet tidak aktif')

        self.autodebet_account.delete()
        message, status = gopay_autodebet_revocation(self.account)
        self.assertEqual(message, 'Account autodebet tidak ditemukan')

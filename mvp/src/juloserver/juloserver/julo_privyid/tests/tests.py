from __future__ import absolute_import
from builtins import object
import mock
from django.test.testcases import override_settings
from django.test import TestCase
from datetime import datetime, timedelta
from .factories import PrivyCustomerFactory, PrivyDocumentFactory, MockRedis
from ..clients.privyid import JuloPrivyIDClient
from django.conf import settings
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    DeviceFactory,
    AwsFaceRecogLogFactory,
    MobileFeatureSettingFactory,
    DocumentFactory,
    DigitalSignatureFaceResultFactory,
    ProductLineFactory,
    ImageFactory,
    FeatureSettingFactory
)

from ..services import (
    get_privy_customer_data,
    create_privy_user,
    check_status_privy_user,
    re_upload_privy_user_photo,
    get_privy_document_data,
    upload_document_to_privy,
    check_privy_document_status,
    get_otp_token,
    request_otp_to_privy,
    confirm_otp_to_privy,
    proccess_signing_document,
    check_privy_registeration_verified,
    upload_document_and_verify_privy,
)
from ..tasks import (
    update_existing_privy_customer,
    send_reminder_sign_sphp,
    create_new_privy_user,
    upload_document_privy
)
from ..constants import CustomerStatusPrivy, DocumentStatusPrivy
from ...julo.models import Workflow, Application, Image
from ...julo.statuses import ApplicationStatusCodes
from ...julo.exceptions import JuloException
from rest_framework.test import APIClient
from ..services.privy_services import get_image_for_reupload
from ..constants import PrivyReUploadCodes, PRIVY_IMAGE_TYPE
from juloserver.julo.tests.factories import WorkflowFactory, AuthUserFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo_privyid.services.usecases import (
    sign_document_privy_service,
    confirm_otp_privy_service,
    request_otp_privy_service,
    upload_document_privy_service,
    check_document_status_for_upload,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo_privyid.exceptions import (
    JuloPrivyLogicException,
    PrivyApiResponseException,
)
from juloserver.julo_privyid.services.common import (
    get_failover_feature,
    get_privy_feature,
    upload_privy_sphp_document,
)
from juloserver.julo_privyid.services.privy_services import (
    store_otp_token_privy,
    get_otp_token_privy,
    check_customer_status,
)
from juloserver.julo_privyid.services.privy_integrate import (
    store_privy_document_data_julo_one,
    is_privy_custumer_valid,
    update_digital_signature_face_recognition,
)
from ..models import PrivyDocument


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestsServicePrivyID(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = CustomerFactory()
        cls.application = ApplicationFactory(customer=cls.customer)
        cls.loan = LoanFactory(application=cls.application)
        cls.privy_customer = PrivyCustomerFactory(customer=cls.customer)
        cls.privy_document = PrivyDocumentFactory(privy_customer=cls.privy_customer, application_id=cls.application)

        cls.otp_token = "0316a5332d05e5eb86a93ce13608252753e7f2b808c7e5739d8cb340a62acd9d"
        cls.otp_code = "73734"

        cls.redis = MockRedis()

    # test registration proccess to privy

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_create_privy_user(self, mocked_client):
        mocked_client.return_value = {
            "code": 201,
            "data": {
                "email": "mail@example.com",
                "phone": "+62834988803591",
                "userToken": "0316a5332d05e5eb86a93ce13608252753e7f2b808c7e5739d8cb340a62acd9d",
                "status": "waiting"},
            "message": "Waiting for Verification"
        }

        new_customer = CustomerFactory()
        new_application = ApplicationFactory(customer=new_customer)

        privy_customer = create_privy_user(new_application)

        self.assertIsNotNone(privy_customer)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_create_privy_user_already_registered(self, mocked_client):
        mocked_client.return_value = {
            "code": 422,
            "errors": [{
                "field": "phone",
                "messages": [
                    "Phone +62898321303511 already registered"
                ]
            }],
            "message": "Validation(s) Error"
        }

        new_customer = CustomerFactory()
        new_application = ApplicationFactory(customer=new_customer)
        cashloan_workflow = Workflow.objects.get(name='CashLoanWorkflow')
        new_application.workflow = cashloan_workflow
        new_application.change_status(ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL)
        new_application.save()

        privy_customer = create_privy_user(new_application)

        self.assertIsNone(privy_customer)

    # test registration status privy

    @mock.patch('juloserver.julo_privyid.services.privy_integrate.process_application_status_change')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_failover_feature')
    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_julo_one_create_privy_user_for_failover(
            self, mocked_client, mock_failover, mock_process_application_status_change):
        mocked_client.return_value = {
            "code": 400,
            "errors": [{
                'field': 'test_field',
                'messages': []
            }],
            "message": "Waiting for Verification"
        }
        mock_failover.return_value = True
        new_customer = CustomerFactory()
        new_application = ApplicationFactory(customer=new_customer)
        new_application.application_status_id = 150
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        new_application.workflow = julo_one_workflow
        new_application.save()

        privy_customer = create_privy_user(new_application)
        new_application.refresh_from_db()
        self.assertIsNone(privy_customer)
        mock_process_application_status_change.assert_called_with(
            new_application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'privy_registration_failed. test_field Error: _failoveron',
            'Failover to Julo'
        )

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_check_status_privy_user_verified(self, mocked_client):
        token = self.privy_customer.privy_customer_token
        mocked_client.return_value = {
            "code": 201,
            "data": {
                "privyId": "JO6663",
                "email": "mail@example8s.com",
                "phone": "+62856437006663",
                "processedAt": "2019-04-19 20:02:06 +0700",
                "userToken": token,
                "status": "verified",
                "identity": {
                    "nama": "Jon Snow",
                    "nik": "1234567890123969",
                    "tanggalLahir": "1993-02-02",
                    "tempatLahir": "Salakan"
                }
            },
            "message": "Data Verified"
        }

        privy_customer, response = check_status_privy_user(token, self.application)

        self.assertIsNotNone(privy_customer)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_check_status_privy_user_rejected(self, mocked_client):
        token = self.privy_customer.privy_customer_token
        mocked_client.return_value = {
            "code": 201,
            "data": {
                "privyId": "JO6663",
                "email": "mail@example8s.com",
                "phone": "+62856437006663",
                "processedAt": "2019-04-19 20:02:06 +0700",
                "userToken": token,
                "status": "rejected",
                "reject": {
                    "code": "PRVM001",
                    "reason": "Email telah terdaftar dengan NIK yang berbeda",
                    "handlers": []
                }
            },
            "message": "Data Rejected"
        }

        privy_customer, response = check_status_privy_user(token, self.application)

        self.assertIsNotNone(privy_customer)
        self.assertIsNotNone(privy_customer.reject_reason)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_check_status_privy_user_wrongtoken(self, mocked_client):
        token = self.privy_customer.privy_customer_token
        mocked_client.return_value = {
            "code": 404,
            "errors": [],
            "message": "Unable to find userToken wR0nGuS3rT0kEn"
        }

        privy_customer, response = check_status_privy_user(token, self.application)

        self.assertIsNone(privy_customer)

    # test re upload photos to privy

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_re_upload_privy_user_photo_success(self, mocked_client):
        token = self.privy_customer.privy_customer_token
        category = 'selfie'
        mocked_client.return_value = {
            "code": 201,
            "data": None,
            "message": "Successfully upload Selfie"
        }

        uploaded = re_upload_privy_user_photo(category, token, self.application.id)

        self.assertEqual(uploaded, True)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_re_upload_privy_user_photo_failed(self, mocked_client):
        token = self.privy_customer.privy_customer_token
        category = 'selfie'
        mocked_client.return_value = {
            "code": 442,
            "errors": [],
            "message": "Validation(s) Error"
        }

        uploaded = re_upload_privy_user_photo(category, token, self.application.id)

        self.assertEqual(uploaded, False)

    def test_re_upload_privy_user_photo_uncatagories(self):
        token = self.privy_customer.privy_customer_token
        category = 'groupfie'

        uploaded = re_upload_privy_user_photo(category, token, self.application.id)

        self.assertEqual(uploaded, False)

    # check privy customer data

    def test_get_privy_customer_data_nonexist(self):
        customer = CustomerFactory()

        privy_customer_data = get_privy_customer_data(customer)

        self.assertIsNone(privy_customer_data)

    def test_get_privy_customer_data_exist(self):
        customer = self.customer

        privy_customer = get_privy_customer_data(customer)

        self.assertIsNotNone(privy_customer)

    # check privy document data

    def test_get_privy_document_data_nonexist(self):
        new_customer = CustomerFactory()
        new_application = ApplicationFactory(customer=new_customer)

        privy_document = get_privy_document_data(new_application)

        self.assertIsNone(privy_document)

    def test_get_privy_document_data_exist(self):
        application = self.application

        privy_document = get_privy_document_data(application)

        self.assertIsNotNone(privy_document)

    # test upload document to privy

    @mock.patch("juloserver.julo_privyid.tasks.upload_document_to_privy")
    @mock.patch('juloserver.loan.services.views_related.get_sphp_template_privy')
    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_upload_document_to_privy_success(self, mock_client, mock_sphp, mocked_upload_document):
        mocked_upload_document.return_value = self.privy_document
        mock_client.return_value = {
            "code": 201,
            "data": {
                "docToken": "61c29277d95c3d06aa80617f60a8f2fa11e3a3a7a63ce431070493a931ecb7a8",
                "urlDocument": "https://signsandbox.privy.id/61c29277d95c3d06aa80617f60a8f2fa11e3a3a7a63ce431070493a931 ecb7a8",
                "recipients": [
                    {
                        "privyId": "KE8226",
                        "type": "Reviewer",
                        "enterpriseToken": None
                    },
                    {
                        "privyId": "TES002",
                        "type": "Signer",
                        "enterpriseToken": None
                    }
                ]
            },
            "message": "Document successfully upload and shared"
        }
        mock_sphp.return_value = "<html><body> mock sphp </body></html>"

        return_value = upload_document_privy(self.application.id)
        self.assertTrue(return_value)

    @mock.patch("juloserver.julo_privyid.tasks.upload_document_to_privy")
    @mock.patch('juloserver.loan.services.views_related.get_sphp_template_privy')
    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_upload_document_to_privy_failed(self, mock_client, mock_sphp, mocked_upload_document):
        mocked_upload_document.return_value = self.privy_document
        mock_client.return_value = {
            "code": 422,
            "errors": [
                {
                    "field": "owner.enterpriseToken",
                    "messages": [
                        "cannot be blank"
                    ]
                }
            ],
            "messages": "Validation(s) Error"
        }
        mock_sphp.return_value = "<html><body> mock sphp </body></html>"

        return_value = upload_document_privy(self.application.id)
        self.assertTrue(return_value)


    # test privy document status
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.upload_sphp_privy_doc')
    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_check_privy_document_status_success(self, mock_client, mock_upload):
        application = self.application
        privy_document = self.privy_document
        mock_upload.return_value = True
        mock_client.return_value = {
            "code": 200,
            "data": {
                "docToken": privy_document.privy_document_token,
                "recipients": [
                    {
                        "privyId": "AB1234",
                        "type": "Reviewer",
                        "signatoryStatus": "Completed"
                    },
                    {
                        "privyId": "DE3456",
                        "type": "Signer",
                        "signatoryStatus": "Completed"
                    }
                ],
                "documentStatus": "Completed",
                "urlDocument": "https://signsandbox.privy.id/doc/bb5e12c77438f60da1f2ab6e566c5aeb6d03561bec3e5d588f7e24 0e4c164120",
                "download": {
                    "url": "http://api-sandbox.privy.id/document/6S7p0MVgdBf9a360ab-6d47-41d8-881d-b4492bad49f8",
                    "expiredAt": "2019-04-25T09:33:58+00:00"
                }
            },
            "message": "Successfully get a status document"
        }

        privy_document = check_privy_document_status(privy_document, application)

        self.assertIsNotNone(privy_document)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_check_privy_document_status_failed(self, mock_client):
        application = self.application
        privy_document = self.privy_document
        mock_client.return_value = {
            "code": 404,
            "errors": [],
            "message": "Unable to find docToken 123445555"
        }

        privy_document = check_privy_document_status(privy_document, application)

        self.assertIsNone(privy_document)

    # signing document to privy

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_proccess_signing_document_success(self, mock_client):
        application = self.application
        privy_document = self.privy_document
        otp_token = self.otp_token
        mock_client.return_value = {
            "code": 201,
            "data": {},
            "message": "Document successfully upload"
        }

        signed = proccess_signing_document(privy_document.privy_document_token, otp_token, application.id)

        self.assertEqual(signed, True)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_proccess_signing_document_failed(self, mock_client):
        application = self.application
        privy_document = self.privy_document
        otp_token = self.otp_token
        mock_client.return_value = {
            "code": 442,
            "errors": [],
            "message": "Validation(s) Error"
        }

        signed = proccess_signing_document(privy_document.privy_document_token, otp_token, application.id)

        self.assertEqual(signed, False)

    # test otp privy

    @mock.patch('juloserver.julo.services2.redis_helper.RedisHelper')
    def test_get_otp_token_succes_from_redis(self, mock_redis):
        application = self.application
        privy_customer = self.privy_customer
        mock_redis.return_value = MockRedis()

        otp_token = get_otp_token(privy_customer.privy_id, application.id)

        self.assertIsNotNone(otp_token)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    @mock.patch('juloserver.julo.services2.redis_helper.RedisHelper')
    def test_get_otp_token_succes_from_api(self, mock_redis, mock_client):
        application = self.application
        privy_id = "error"
        mock_client.return_value = {
            "code": 201,
            "data": {
                "token": "61c29277d95c3d06aa80617f60a8f2fa11e3a3a7a63ce431070493a931ecb7a8",
                "active": False,
                "expired_at": "2019-04-05T18:20:32.000+07:00",
                "created_at": "2019-04-04T18:20:32.000+07:00"
            },
            "message": "User token successfully create"
        }
        mock_redis.return_value = MockRedis()

        otp_token = get_otp_token(privy_id, application.id)

        self.assertIsNotNone(otp_token)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    @mock.patch('juloserver.julo.services2.redis_helper.RedisHelper')
    def test_get_otp_token_failed(self, mock_redis, mock_client):
        application = self.application
        privy_id = "error"
        mock_client.return_value = {
            "code": 442,
            "errors": [],
            "message": "Validation(s) Error"
        }
        mock_redis.return_value = MockRedis()

        otp_token = get_otp_token(privy_id, application.id)

        self.assertIsNone(otp_token)

    # request otp token

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_request_otp_to_privy_success(self, mock_client):
        application = self.application
        otp_token = self.otp_token
        mock_client.return_value = {
            "code": 201,
            "data": {},
            "message": "OTP sent to +62823332xxxx"
        }

        requested = request_otp_to_privy(otp_token, application.id)

        self.assertEqual(requested, True)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_request_otp_to_privy_failed(self, mock_client):
        application = self.application
        otp_token = self.otp_token
        mock_client.return_value = {
            "code": 442,
            "errors": [],
            "message": "Unauthorized. Invalid or expired token"
        }

        requested = request_otp_to_privy(otp_token, application.id)

        self.assertEqual(requested, False)

    # confirm otp token

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_confirm_otp_to_privy_success(self, mock_client):
        application = self.application
        otp_token = self.otp_token
        otp_code = self.otp_code
        mock_client.return_value = {
            "code": 201,
            "data": {},
            "message": "OTP Verification success "
        }

        requested = confirm_otp_to_privy(otp_code, otp_token, application.id)

        self.assertEqual(requested, True)

    @mock.patch('juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request')
    def test_confirm_otp_to_privy_failed(self, mock_client):
        application = self.application
        otp_token = self.otp_token
        otp_code = self.otp_code
        mock_client.return_value = {
            "code": 442,
            "errors": [],
            "message": "Unauthorized. Invalid or expired token"
        }

        requested = confirm_otp_to_privy(otp_code, otp_token, application.id)

        self.assertEqual(requested, False)


    @mock.patch('juloserver.julo_privyid.services.privy_integrate.upload_document_and_verify_privy')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.check_status_privy_user')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_privy_customer_data')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.'
                'process_application_status_change')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_failover_feature')
    def test_check_privy_registeration_verified(self, mocked_failover, mocked_app_change,
                                                mocked_privy_customer, mocked_check_status, mocked_upload):
        customer_data = PrivyCustomerFactory()
        customer_data.privy_customer_status = CustomerStatusPrivy.WAITING
        customer_data.save()
        updated_customer_data = customer_data
        updated_customer_data.privy_customer_status = CustomerStatusPrivy.VERIFIED
        updated_customer_data.save()
        application = self.application
        mocked_failover.return_value = False
        mocked_privy_customer.return_value = customer_data
        response = {'code': 201}
        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (updated_customer_data, response)]
        mocked_upload.return_value = None
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_not_called()
        mocked_app_change.reset_mock()

        rejected_customer_data = customer_data
        rejected_customer_data.privy_customer_status = CustomerStatusPrivy.REJECTED
        rejected_customer_data.reject_reason = 'Selfie Not Found'
        rejected_customer_data.save()

        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (rejected_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()
        mocked_app_change.reset_mock()

        mocked_failover.return_value = True
        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (rejected_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()
        mocked_app_change.reset_mock()

        rejected_customer_data = customer_data
        mocked_failover.return_value = True
        rejected_customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        rejected_customer_data.reject_reason = 'SELFIE. PRVS-Helo'
        rejected_customer_data.save()
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()

        mocked_app_change.reset_mock()
        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (rejected_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()

        with mock.patch('django.utils.timezone.localtime') as mocked_time:
            mocked_failover.return_value = False
            datetime_now = datetime(2020, 9, 10, 10, 30)
            mocked_time.side_effect = [datetime_now,
                                       datetime_now,
                                       datetime_now + timedelta(minutes=JuloPrivyIDClient.TIMEOUT_DURATION+1)]
            with self.assertRaises(JuloException):
                check_privy_registeration_verified(application.customer)

            mocked_failover.return_value = True
            mocked_time.side_effect = [datetime_now,
                                       datetime_now,
                                       datetime_now + timedelta(minutes=JuloPrivyIDClient.TIMEOUT_DURATION+1)]
            return_value = check_privy_registeration_verified(application.customer)
            mocked_app_change.assert_called_with(application.id,
                                                 ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                                                 'Registrasi akun tanda tangan digital gagal, dialihkan ke tanda tangan JULO',
                                                 'Failover to Julo'
                                                 )
            self.assertIsNone(return_value)


    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_failover_feature')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.time.sleep')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.'
                'process_application_status_change')
    @mock.patch('juloserver.julo_privyid.tasks.upload_document_privy.delay')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.check_privy_document_status')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_privy_document_data')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_privy_customer_data')
    def test_upload_document_and_verify_privy(self, mocked_customer_data, mocked_document_data,
                                              mocked_document_status, mocked_upload, mocked_status_change,
                                              mocked_sleep, mocked_failover):
        application = self.application
        customer_data = PrivyCustomerFactory()
        customer_data.privy_customer_status = CustomerStatusPrivy.VERIFIED
        customer_data.save()
        document_data = PrivyDocumentFactory()
        document_data.privy_document_status = DocumentStatusPrivy.IN_PROGRESS
        document_data.save()
        completed_document_data = PrivyDocumentFactory()
        completed_document_data.privy_document_status = DocumentStatusPrivy.COMPLETED
        completed_document_data.save()
        mocked_customer_data.return_value = customer_data
        mocked_document_data.side_effect = [None, document_data, completed_document_data,
                                            completed_document_data]
        mocked_document_status.return_value = document_data
        mocked_upload.return_value = None
        mocked_sleep.return_value = None
        upload_document_and_verify_privy(application.customer)
        mocked_upload.assert_called_once()
        mocked_status_change.assert_called_once()

        mocked_customer_data.return_value = None
        with self.assertRaises(JuloException):
            upload_document_and_verify_privy(application.customer)

        customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        customer_data.save()
        mocked_customer_data.return_value = customer_data
        return_value = upload_document_and_verify_privy(application.customer)
        self.assertIsNone(return_value)

        customer_data.privy_customer_status = CustomerStatusPrivy.WAITING
        customer_data.save()
        mocked_customer_data.return_value = customer_data
        with self.assertRaises(JuloException):
            upload_document_and_verify_privy(application.customer)

        customer_data.privy_customer_status = CustomerStatusPrivy.VERIFIED
        customer_data.save()
        mocked_document_data.side_effect = [None, None, document_data, document_data]
        upload_document_and_verify_privy(application.customer)
        mocked_status_change.assert_called_with(application.id,
                                                ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                                                'Privy Document uploaded successfully')

        customer_data.privy_customer_status = CustomerStatusPrivy.VERIFIED
        customer_data.save()
        mocked_document_data.side_effect = [None, None, None, document_data, document_data]
        upload_document_and_verify_privy(application.customer)
        mocked_status_change.assert_called_with(application.id,
                                                ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                                                'Privy Document uploaded successfully')

        mocked_document_data.side_effect = [None, None, None, None]
        mocked_failover.return_value = False
        upload_document_and_verify_privy(application.customer)
        mocked_status_change.assert_called_with(application.id,
                                                ApplicationStatusCodes.DIGISIGN_FAILED,
                                                'Gagal unggah dokumen SPHP untuk tanda tangan digital')

        mocked_document_data.side_effect = [None, None, None, None]
        mocked_failover.return_value = True
        upload_document_and_verify_privy(application.customer)
        mocked_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            'Gagal unggah dokumen SPHP untuk tanda tangan digital, '
            'dialihkan ke tanda tangan JULO',
            'Failover to Julo'
        )

        mocked_document_data.side_effect = [document_data, None]
        with self.assertRaises(JuloException):
            upload_document_and_verify_privy(application.customer)

        mocked_document_data.side_effect = [document_data, document_data]
        mocked_document_status.return_value = None
        with self.assertRaises(JuloException):
            upload_document_and_verify_privy(application.customer)

    @mock.patch('juloserver.julo_privyid.tasks.task_check_privy_registeration_verified.apply_async')
    @mock.patch('juloserver.julo_privyid.tasks.process_application_status_change')
    @mock.patch('juloserver.julo_privyid.tasks.get_failover_feature')
    @mock.patch('juloserver.julo_privyid.tasks.Image.objects')
    @mock.patch('juloserver.julo_privyid.tasks.upload_document_and_verify_privy')
    @mock.patch('juloserver.julo_privyid.tasks.check_privy_registeration_verified')
    @mock.patch('juloserver.julo_privyid.tasks.re_upload_privy_user_photo')
    @mock.patch('juloserver.julo_privyid.tasks.get_privy_customer_data')
    def test_update_existing_privy_customer(self, mocked_customer_data, mocked_reupload, mocked_verify_reg,
                                            mocked_document, mocked_queryset, mocked_failover,
                                            mocked_status_change, mocked_task):
        class ImageMock(object):
            image_type = 'selfie_ops'
        application = self.application
        image_mock_1 = ImageMock()
        image_mock_2 = ImageMock()
        image_mock_2.image_type = 'ktp_self_ops'
        mocked_queryset.filter.return_value.last.side_effect = [image_mock_1, image_mock_2]
        mocked_task.return_value = None

        mocked_reupload.return_value = True
        privy_customer_data = PrivyCustomerFactory()
        privy_customer_data.privy_customer_status = 'invalid'
        privy_customer_data.save()
        mocked_customer_data.return_value = privy_customer_data
        update_existing_privy_customer(application.id)
        mocked_reupload.assert_called()
        mocked_task.assert_called()

        mocked_customer_data.return_value = None
        return_value = update_existing_privy_customer(application.id)
        self.assertFalse(return_value)

        mocked_task.reset_mock()
        mocked_customer_data.return_value = privy_customer_data
        privy_customer_data.privy_customer_status = CustomerStatusPrivy.WAITING
        update_existing_privy_customer(application.id)
        mocked_task.assert_called_once()

        self.assertFalse(return_value)

        image_mock_1 = ImageMock()
        image_mock_2 = ImageMock()
        image_mock_2.image_type = 'ktp_self_ops'
        mocked_queryset.filter.return_value.last.side_effect = [image_mock_1, image_mock_2]
        mocked_customer_data.return_value = privy_customer_data
        privy_customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        mocked_reupload.return_value = False
        mocked_failover.return_value = False
        return_value = update_existing_privy_customer(application.id)
        mocked_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.DIGISIGN_FAILED,
            'Dokumen pendukung (KTP / Selfie / Other) tidak tepat'
        )
        self.assertIsNone(return_value)

        image_mock_1 = ImageMock()
        image_mock_2 = ImageMock()
        image_mock_2.image_type = 'ktp_self_ops'
        mocked_queryset.filter.return_value.last.side_effect = [image_mock_1, image_mock_2]
        mocked_customer_data.return_value = privy_customer_data
        privy_customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        mocked_failover.return_value = True
        mocked_reupload.return_value = False
        return_value = update_existing_privy_customer(application.id)
        mocked_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            'Dialihkan ke tanda tangan JULO'
        )
        self.assertIsNone(return_value)

    @mock.patch('juloserver.julo_privyid.tasks.task_check_privy_registeration_verified.apply_async')
    @mock.patch('juloserver.julo_privyid.tasks.process_application_status_change')
    @mock.patch('juloserver.julo_privyid.tasks.upload_document_and_verify_privy')
    @mock.patch('juloserver.julo_privyid.tasks.check_privy_registeration_verified')
    @mock.patch('juloserver.julo_privyid.tasks.create_privy_user')
    @mock.patch('juloserver.julo_privyid.tasks.get_privy_customer_data')
    @mock.patch('juloserver.julo_privyid.tasks.get_failover_feature')
    def test_create_new_privy_user(self, mocked_failover, mocked_get_customer,
                                   mocked_create_user, mocked_upload, mocked_verify,
                                   mocked_process, mocked_task):
        self.aws_face_log = AwsFaceRecogLogFactory(application_id=self.application.id,
                                                   is_indexed=True,
                                                   is_quality_check_passed=True)
        mocked_failover.return_value = False
        mocked_task.return_value = None
        mocked_get_customer.return_value = None
        mocked_create_user.return_value = self.privy_customer
        mocked_upload.return_value = True
        mocked_verify.return_value = True
        create_new_privy_user(self.application.id)
        mocked_create_user.assert_called_once()
        mocked_task.assert_called_once()

        mocked_failover.return_value = False
        self.privy_customer.privy_customer_status = CustomerStatusPrivy.INVALID
        self.privy_customer.save()
        mocked_get_customer.return_value = self.privy_customer
        mocked_process.return_value = False
        create_new_privy_user(self.application.id)
        mocked_process.assert_called_with(self.application.id,
                                          ApplicationStatusCodes.DIGISIGN_FAILED,
                                          'Dokumen pendukung (KTP / Selfie / Other) belum diganti')

        mocked_failover.return_value = True
        create_new_privy_user(self.application.id)
        mocked_process.assert_called_with(self.application.id,
                                          ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                                          'Dialihkan ke tanda tangan JULO')

        mocked_task.reset_mock()
        self.privy_customer.privy_customer_status = CustomerStatusPrivy.VERIFIED
        self.privy_customer.save()
        mocked_get_customer.return_value = self.privy_customer
        create_new_privy_user(self.application.id)
        mocked_task.called_once()

    @mock.patch('juloserver.julo_privyid.tasks.task_check_privy_registeration_verified.apply_async')
    @mock.patch('juloserver.julo_privyid.tasks.process_application_status_change')
    @mock.patch('juloserver.julo_privyid.tasks.upload_document_and_verify_privy')
    @mock.patch('juloserver.julo_privyid.tasks.check_privy_registeration_verified')
    @mock.patch('juloserver.julo_privyid.tasks.create_privy_user')
    @mock.patch('juloserver.julo_privyid.tasks.get_privy_customer_data')
    @mock.patch('juloserver.julo_privyid.tasks.get_failover_feature')
    def test_julo_one_create_new_privy_user(self, mocked_failover, mocked_get_customer,
                                   mocked_create_user, mocked_verify, mocked_upload,
                                   mocked_process, mocked_task):
        self.aws_face_log = AwsFaceRecogLogFactory(application_id=self.application.id,
                                                   is_indexed=True,
                                                   is_quality_check_passed=True)
        mocked_failover.return_value = False
        mocked_get_customer.return_value = None
        mocked_create_user.return_value = self.privy_customer
        mocked_upload.return_value = True
        mocked_verify.return_value = True
        mocked_task.return_value = None
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        create_new_privy_user(self.application.id)
        mocked_create_user.assert_called_once()
        mocked_task.assert_called_once()
        mocked_upload.assert_not_called()

        mocked_failover.return_value = False
        self.privy_customer.privy_customer_status = CustomerStatusPrivy.INVALID
        self.privy_customer.save()
        mocked_get_customer.return_value = self.privy_customer
        mocked_process.return_value = False
        create_new_privy_user(self.application.id)
        mocked_process.assert_called_with(self.application.id,
                                          ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
                                          'Dokumen pendukung (KTP / Selfie / Other) belum diganti')

        mocked_failover.return_value = True
        create_new_privy_user(self.application.id)
        mocked_process.assert_called_with(self.application.id,
                                          ApplicationStatusCodes.LOC_APPROVED,
                                          'Dialihkan ke tanda tangan JULO')

        mocked_upload.reset_mock()
        mocked_task.reset_mock()
        self.privy_customer.privy_customer_status = CustomerStatusPrivy.VERIFIED
        self.privy_customer.save()
        mocked_get_customer.return_value = self.privy_customer
        create_new_privy_user(self.application.id)
        mocked_upload.assert_not_called()
        mocked_task.called_once()

    @mock.patch('juloserver.julo_privyid.tasks.task_check_privy_registeration_verified.apply_async')
    @mock.patch('juloserver.julo_privyid.tasks.process_application_status_change')
    @mock.patch('juloserver.julo_privyid.tasks.get_failover_feature')
    @mock.patch('juloserver.julo_privyid.tasks.Image.objects')
    @mock.patch('juloserver.julo_privyid.tasks.upload_document_and_verify_privy')
    @mock.patch('juloserver.julo_privyid.tasks.check_privy_registeration_verified')
    @mock.patch('juloserver.julo_privyid.tasks.re_upload_privy_user_photo')
    @mock.patch('juloserver.julo_privyid.tasks.get_privy_customer_data')
    def test_julo_lone_update_existing_privy_customer(self, mocked_customer_data, mocked_reupload,
                                            mocked_verify_reg,
                                            mocked_document, mocked_queryset, mocked_failover,
                                            mocked_status_change, mocked_task):
        class ImageMock(object):
            image_type = 'selfie_ops'

        application = self.application
        image_mock_1 = ImageMock()
        image_mock_2 = ImageMock()
        image_mock_2.image_type = 'ktp_self_ops'
        mocked_queryset.filter.return_value.last.side_effect = [image_mock_1, image_mock_2]

        mocked_reupload.return_value = True
        privy_customer_data = PrivyCustomerFactory()
        privy_customer_data.privy_customer_status = 'invalid'
        privy_customer_data.save()
        mocked_task.return_value = None
        mocked_customer_data.return_value = privy_customer_data
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        update_existing_privy_customer(application.id)
        mocked_reupload.assert_called()
        mocked_task.assert_called()
        mocked_document.assert_not_called()

        mocked_customer_data.return_value = None
        return_value = update_existing_privy_customer(application.id)
        self.assertFalse(return_value)

        mocked_task.reset_mock()
        mocked_document.reset_mock()
        mocked_customer_data.return_value = privy_customer_data
        privy_customer_data.privy_customer_status = CustomerStatusPrivy.WAITING
        update_existing_privy_customer(application.id)
        mocked_document.assert_not_called()
        mocked_task.assert_called_once()
        self.assertFalse(return_value)

        image_mock_1 = ImageMock()
        image_mock_2 = ImageMock()
        image_mock_2.image_type = 'ktp_self_ops'
        mocked_queryset.filter.return_value.last.side_effect = [image_mock_1, image_mock_2]
        mocked_customer_data.return_value = privy_customer_data
        privy_customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        mocked_reupload.return_value = False
        mocked_failover.return_value = False
        return_value = update_existing_privy_customer(application.id)
        mocked_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.DIGISIGN_FAILED,
            'Dokumen pendukung (KTP / Selfie / Other) tidak tepat'
        )
        self.assertIsNone(return_value)

        image_mock_1 = ImageMock()
        image_mock_2 = ImageMock()
        image_mock_2.image_type = 'ktp_self_ops'
        mocked_queryset.filter.return_value.last.side_effect = [image_mock_1, image_mock_2]
        mocked_customer_data.return_value = privy_customer_data
        privy_customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        mocked_failover.return_value = True
        mocked_reupload.return_value = False
        return_value = update_existing_privy_customer(application.id)
        mocked_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'Dialihkan ke tanda tangan JULO'
        )
        self.assertIsNone(return_value)

    @mock.patch('juloserver.julo_privyid.services.privy_integrate.check_status_privy_user')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_privy_customer_data')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.'
                'process_application_status_change')
    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_failover_feature')
    def test_julo_one_check_privy_registeration_verified(self, mocked_failover, mocked_app_change,
                                                mocked_privy_customer, mocked_check_status):
        customer_data = PrivyCustomerFactory()
        customer_data.privy_customer_status = CustomerStatusPrivy.WAITING
        customer_data.save()
        updated_customer_data = customer_data
        updated_customer_data.privy_customer_status = CustomerStatusPrivy.VERIFIED
        updated_customer_data.save()
        application = self.application
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        application.workflow = julo_one_workflow
        application.save()

        mocked_failover.return_value = False
        mocked_privy_customer.return_value = customer_data
        response = {'code': 200}
        mocked_check_status.side_effect = [(customer_data, response) , (customer_data, response),
                                           (updated_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()
        mocked_app_change.reset_mock()

        rejected_customer_data = customer_data
        rejected_customer_data.privy_customer_status = CustomerStatusPrivy.REJECTED
        rejected_customer_data.reject_reason = 'Selfie Not Found'
        rejected_customer_data.save()

        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (rejected_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()
        mocked_app_change.reset_mock()

        mocked_failover.return_value = True
        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (rejected_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()
        mocked_app_change.reset_mock()

        rejected_customer_data = customer_data
        mocked_failover.return_value = True
        rejected_customer_data.privy_customer_status = CustomerStatusPrivy.INVALID
        rejected_customer_data.reject_reason = 'SELFIE. PRVS-Helo'
        rejected_customer_data.save()
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()

        mocked_app_change.reset_mock()
        mocked_check_status.side_effect = [(customer_data, response), (customer_data, response),
                                           (rejected_customer_data, response)]
        check_privy_registeration_verified(application.customer)
        mocked_app_change.assert_called_once()

        with mock.patch('django.utils.timezone.localtime') as mocked_time:
            mocked_failover.return_value = False
            datetime_now = datetime(2020, 9, 10, 10, 30)
            mocked_time.side_effect = [datetime_now,
                                       datetime_now,
                                       datetime_now + timedelta(minutes=JuloPrivyIDClient.TIMEOUT_DURATION+1)]
            with self.assertRaises(JuloException):
                check_privy_registeration_verified(application.customer)

            mocked_failover.return_value = True
            mocked_time.side_effect = [datetime_now,
                                       datetime_now,
                                       datetime_now + timedelta(minutes=JuloPrivyIDClient.TIMEOUT_DURATION+1)]
            return_value = check_privy_registeration_verified(application.customer)
            mocked_app_change.assert_called_with(application.id,
                                                 ApplicationStatusCodes.LOC_APPROVED,
                                                 'Registrasi akun tanda tangan digital gagal, dialihkan ke tanda tangan JULO',
                                                 'Failover to Julo'
                                                 )
            self.assertIsNone(return_value)


class TestSphpTaskReminder(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(
            can_notify=True
        )
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.device = DeviceFactory(customer=self.customer)
        application = Application.objects.get(id=self.loan.application.id)
        application.device = self.device
        application.save()

    @mock.patch('juloserver.julo_privyid.services.privy_integrate.get_privy_document_data')
    @mock.patch('juloserver.julo_privyid.tasks.get_julo_pn_client')
    def test_send_reminder_sign_sphp_task(self, mocked_client, mocked_document):
        magic_mocked_client = mock.MagicMock()
        magic_mocked_client.sphp_sign_ready_reminder.return_value = None
        magic_document = mock.MagicMock()
        magic_document.privy_document_status = "In Progress"
        mocked_document.return_value = magic_document
        mocked_client.return_value = magic_mocked_client
        send_reminder_sign_sphp(self.application.id)
        mocked_client.assert_called_once()


class TestUseCasesPrivy(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account
        )
        self.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_xid=1000200300,
            loan_status=self.loan_status,
        )
        self.privy_customer = PrivyCustomerFactory(
            customer=self.customer, privy_id="ABC123"
        )
        self.privy_document = PrivyDocumentFactory(
            privy_customer=self.privy_customer, application_id=None, loan_id=self.loan
        )
        self.response_data = {
            "code": 200,
            "data": {"signed": True, "privyId": "ABC123"},
            "message": "Document already signed.",
        }
        self.request_param = {
            "url": "localhost:8000/v1/merchant/document/multiple-signing",
            "data": {
                "documents": [{"docToken": "TokenDoc"}],
                "signature": {"visibility": True},
            },
            "headers": {
                "Token": "CustomerToken",
                "Content-Type": "application/json",
                "Merchant-Key": "aaqbrczxdcqnaid4almv",
            },
        }
        self.request_path = "/document/multiple-signing"
        self.response_status_code = 200

        self.doc_status_response = {
            "code": 200,
            "data": {
                "title": "ABC123_doc.pdf",
                "docToken": "doctoken",
                "download": {
                    "url": "www.google.com",
                    "expiredAt": "2020-10-23T13:44:17+00:00",
                },
                "recipients": [
                    {
                        "type": "Signer",
                        "privyId": "DEV-JU1612",
                        "signedAt": "2020-10-23T20:29:21.000+07:00",
                        "signatoryStatus": "Completed",
                    },
                    {
                        "type": "Signer",
                        "privyId": "DEVPR4164",
                        "signedAt": "2020-10-23T20:34:25.000+07:00",
                        "signatoryStatus": "Completed",
                    },
                ],
                "urlDocument": "localhost/doc/token",
                "documentStatus": "Completed",
            },
            "message": "Successfully get a status document",
        }

    @mock.patch(
        "juloserver.julo_privyid.services.usecases.store_privy_document_data_julo_one"
    )
    @mock.patch("juloserver.julo_privyid.services.usecases.accept_julo_sphp")
    @mock.patch(
        "juloserver.julo_privyid.services.usecases.upload_privy_sphp_document.delay"
    )
    @mock.patch("juloserver.julo_privyid.services.usecases.store_privy_api_data.delay")
    @mock.patch("juloserver.julo_privyid.services.usecases.get_otp_token_privy")
    @mock.patch(
        "juloserver.julo_privyid.clients.privy.JuloPrivyClient.get_document_status"
    )
    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.sign_document")
    def test_sign_document_privy_service(
        self,
        mocked_client,
        mocked_client_doc,
        mocked_otp_token,
        mocked_store_data,
        mocked_upload,
        mocked_accept,
        mocked_store_document,
    ):
        data = self.response_data
        api_data = dict()
        api_data["response_code"] = self.response_data
        api_data["request_param"] = self.request_param
        api_data["request_path"] = self.request_path
        api_data["response_status_code"] = self.response_status_code
        mocked_client.return_value = (data, api_data)
        mocked_store_data.return_value = None
        mocked_otp_token.return_value = "mocked_token"
        api_data1 = api_data
        api_data1["response_code"] = self.doc_status_response
        mocked_client_doc.return_value = (self.doc_status_response["data"], api_data)
        mocked_upload.return_value = None
        mocked_accept.return_value = None

        return_value = sign_document_privy_service(self.user, self.loan.loan_xid)
        mocked_otp_token.assert_called_with(
            self.privy_customer.privy_id, self.loan.loan_xid
        )
        mocked_store_data.assert_called_with(self.loan.loan_xid, api_data)
        mocked_client_doc.assert_called_with(self.privy_document.privy_document_token)
        mocked_upload.assert_called_with(
            "www.google.com",
            self.loan.id,
            self.loan.loan_xid,
            self.application.fullname,
        )
        mocked_accept.assert_called_with(self.loan, "Privy")
        mocked_store_document.assert_called_with(
            self.loan,
            self.privy_document.privy_customer,
            self.doc_status_response["data"],
        )

        self.assertIsNone(return_value)

        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_APPROVAL
        )
        self.loan.save()
        with self.assertRaises(JuloPrivyLogicException):
            return_value = sign_document_privy_service(self.user, self.loan.loan_xid)

    @mock.patch("juloserver.julo_privyid.services.usecases.get_privy_customer_data")
    @mock.patch("juloserver.julo_privyid.services.usecases.get_otp_token_privy")
    @mock.patch(
        "juloserver.julo_privyid.clients.privy.JuloPrivyClient.confirm_otp_token"
    )
    def test_confirmed_otp_privy(self, mocked_client, mocked_token, mocked_customer):
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE
        )
        self.loan.save()
        mocked_token.return_value = "mocked_token"
        otp_code = "123"
        data, api_data = {}, {}
        data["None"] = 0
        api_data["response_status_code"] = 200
        mocked_client.return_value = (data, api_data)
        return_value = confirm_otp_privy_service(
            self.user, self.loan.loan_xid, otp_code
        )
        mocked_client.assert_called_with(otp_code, "mocked_token")
        self.assertIsNone(return_value)

        api_data["response_status_code"] = 404
        mocked_client.return_value = (data, api_data)
        with self.assertRaises(PrivyApiResponseException):
            return_value = confirm_otp_privy_service(
                self.user, self.loan.loan_xid, otp_code
            )
            mocked_client.assert_called_with(otp_code, "mocked_token")

        mocked_customer.return_value = None
        with self.assertRaises(JuloPrivyLogicException):
            return_value = confirm_otp_privy_service(
                self.user, self.loan.loan_xid, otp_code
            )

        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_APPROVAL
        )
        self.loan.save()
        with self.assertRaises(JuloPrivyLogicException):
            return_value = sign_document_privy_service(self.user, self.loan.loan_xid)

    @mock.patch("juloserver.julo_privyid.services.usecases.request_otp_to_privy")
    @mock.patch("juloserver.julo_privyid.services.usecases.get_otp_token_privy")
    def test_request_otp_privy(self, mocked_token, mocked_request):
        self.application.mobile_phone_1 = "123456789"
        self.application.save()
        mocked_token.return_value = "mocked_token"
        mocked_request.return_value = None

        return_value = request_otp_privy_service(self.user, self.loan.loan_xid)
        mocked_token.assert_called_with(
            self.privy_customer.privy_id, self.loan.loan_xid
        )
        mocked_request.assert_called_with(
            "mocked_token", self.loan, self.privy_customer
        )
        self.assertEqual(return_value, self.application.mobile_phone_1)

    @mock.patch.object(PrivyDocument.objects, "get_or_none")
    @mock.patch(
        "juloserver.julo_privyid.services.usecases.store_privy_document_data_julo_one"
    )
    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.upload_document")
    def test_upload_document_privy_service(
        self, mocked_client, mocked_store, mocked_qs
    ):
        response_data = {
            "code": 201,
            "data": {
                "docToken": "Token",
                "recipients": [
                    {
                        "type": "Signer",
                        "privyId": "DEV-JU1612",
                        "enterpriseToken": "41bc84b42c8543daf448d893c255be1dbdcc722e",
                    },
                    {"type": "Signer", "privyId": "DEVPR0130", "enterpriseToken": None},
                ],
                "urlDocument": "localhost/doc/:token",
            },
            "message": "Document successfully upload and shared",
        }
        request_param = {
            "url": "localhost/v3/merchant/document/upload",
            "data": {
                "owner": {"privyId": "DEV-JU1612", "enterpriseToken": "Token"},
                "docType": "Serial",
                "recipients": [
                    {
                        "privyId": "DEV-JU1612",
                        "enterpriseToken": "Token",
                        "type": "Signer",
                    },
                    {"privyId": "DEVPR0130", "enterpriseToken": "", "type": "Signer"},
                ],
                "templateId": "juloPOA001",
                "documentTitle": "DEVPR0130_2000002045.pdf",
            },
            "files": {"document": "DEVPR0130_2000002045.pdf"},
            "headers": {"Merchant-Key": "Key"},
        }
        input_data = {"max_count": 3, "retry_count": 1}

        self.privy_customer.privy_customer_status = CustomerStatusPrivy.VERIFIED
        self.privy_customer.save()
        api_data = dict()
        api_data["response_code"] = response_data
        api_data["request_params"] = request_param
        api_data["request_path"] = self.request_path
        api_data["response_status_code"] = self.response_status_code
        data = self.response_data["data"]
        mocked_client.return_value = (data, api_data)
        mocked_store.return_value = self.privy_document
        mocked_qs.return_value = None

        upload_document_privy_service(self.user, self.loan.loan_xid, input_data)
        mocked_client.assert_called_with(self.privy_customer.privy_id, self.loan.id)
        mocked_store.assert_called_with(self.loan, self.privy_customer, data)

    @mock.patch(
        "juloserver.julo_privyid.services.usecases.upload_privy_sphp_document.delay"
    )
    @mock.patch("juloserver.julo_privyid.services.usecases.accept_julo_sphp")
    @mock.patch(
        "juloserver.julo_privyid.clients.privy.JuloPrivyClient.get_document_status"
    )
    @mock.patch("juloserver.julo_privyid.services.usecases.get_privy_feature")
    @mock.patch("juloserver.julo_privyid.services.usecases.get_failover_feature")
    def test_check_document_status_for_upload(
        self,
        mocked_failover,
        mocked_privy,
        mocked_doc_status,
        mocked_accept,
        mocked_upload,
    ):
        data = self.doc_status_response["data"]
        data["documentStatus"] = "In Progress"
        api_data = self.doc_status_response
        api_data["data"]["documentStatus"] = "In Progress"
        data["docToken"] = self.privy_document.privy_document_token
        mocked_privy.return_value = True
        mocked_failover.return_value = False
        mocked_doc_status.return_value = (data, api_data)

        return_value = check_document_status_for_upload(self.user, self.loan.loan_xid)
        mocked_privy.assert_called()
        mocked_failover.assert_called()
        mocked_doc_status.assert_called_with(self.privy_document.privy_document_token)
        self.assertEqual(return_value, ("In Progress", True, False))

        data["documentStatus"] = "Completed"
        api_data = self.doc_status_response
        api_data["data"]["documentStatus"] = "Completed"
        data["docToken"] = self.privy_document.privy_document_token
        mocked_privy.return_value = True
        mocked_failover.return_value = False
        mocked_doc_status.return_value = (data, api_data)
        mocked_upload.return_value = None
        mocked_accept.return_value = None
        return_value = check_document_status_for_upload(self.user, self.loan.loan_xid)
        mocked_privy.assert_called()
        mocked_failover.assert_called()
        mocked_upload.assert_called()
        mocked_accept.assert_called()
        mocked_doc_status.assert_called_with(self.privy_document.privy_document_token)
        mocked_privy.assert_called()
        mocked_failover.assert_called()
        self.assertEqual(return_value, ("Completed", True, False))

    def test_common_functions(self):
        mobile_feature_1 = MobileFeatureSettingFactory(
            feature_name="digital_signature_failover", is_active=True
        )
        mobile_feature_2 = MobileFeatureSettingFactory(
            feature_name="privy_mode", is_active=True
        )

        return_value = get_privy_feature()
        self.assertTrue(return_value)

        return_value = get_failover_feature()
        self.assertTrue(return_value)

        mobile_feature_1.is_active = False
        mobile_feature_2.is_active = False
        mobile_feature_1.save()
        mobile_feature_2.save()

        return_value = get_privy_feature()
        self.assertFalse(return_value)

        return_value = get_failover_feature()
        self.assertFalse(return_value)


class TestPrivyServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account
        )
        self.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_xid=1000200300,
            loan_status=self.loan_status,
        )
        self.privy_customer = PrivyCustomerFactory(
            customer=self.customer, privy_id="ABC123"
        )
        self.privy_document = PrivyDocumentFactory(
            privy_customer=self.privy_customer, application_id=None, loan_id=self.loan
        )

    @mock.patch("juloserver.julo_privyid.services.privy_services.get_redis_client")
    def test_store_otp_token_privy(self, mocked_redis):
        mocked_redis_mock = mock.MagicMock()
        mocked_redis_mock.set.return_value = None
        mocked_redis.return_value = mocked_redis_mock
        response = {
            "code": 201,
            "data": {
                "token": "Token",
                "created_at": "2020-11-30T09:53:49.000+07:00",
                "expired_at": "2020-12-02T09:53:49.000+07:00",
            },
            "message": "User token successfully created",
        }
        data = response["data"]
        store_otp_token_privy(self.privy_customer.privy_id, data)
        mocked_redis.assert_called()
        mocked_redis_mock.set.assert_called()

    @mock.patch("juloserver.julo_privyid.services.privy_services.store_otp_token_privy")
    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.create_token")
    @mock.patch("juloserver.julo_privyid.services.privy_services.get_redis_client")
    def test_get_otp_token_privy(self, mocked_redis, mocked_token, mocked_store):
        mocked_redis_mock = mock.MagicMock()
        mocked_redis_mock.get.return_value = "token"
        mocked_redis.return_value = mocked_redis_mock
        response = {
            "code": 201,
            "data": {
                "token": "Token",
                "created_at": "2020-11-30T09:53:49.000+07:00",
                "expired_at": "2020-12-02T09:53:49.000+07:00",
            },
            "message": "User token successfully created",
        }
        data = response["data"]
        api_data = dict()
        api_data["response_status_code"] = 201
        api_data["response_code"] = response

        token = get_otp_token_privy(self.privy_customer.privy_id, self.loan.loan_xid)
        self.assertEqual(token, "token")
        mocked_redis_mock.get.assert_called()

        mocked_redis_mock.get.return_value = None
        mocked_token.return_value = (data, api_data)
        mocked_store.return_value = None
        token = get_otp_token_privy(self.privy_customer.privy_id, self.loan.loan_xid)
        self.assertEqual(token, "Token")
        mocked_redis_mock.get.assert_called()
        mocked_store.assert_called()
        mocked_token.assert_called()

    @mock.patch(
        "juloserver.julo_privyid.services.privy_services.update_digital_signature_face_recognition"
    )
    @mock.patch("juloserver.julo_privyid.services.privy_services.store_privy_api_data")
    @mock.patch(
        "juloserver.julo_privyid.services.privy_services.store_privy_customer_data"
    )
    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.register_status")
    @mock.patch("juloserver.julo_privyid.services.privy_services.get_privy_feature")
    @mock.patch("juloserver.julo_privyid.services.privy_services.get_failover_feature")
    def test_check_customer_status(
        self,
        mocked_failover,
        mocked_privy,
        mocked_status,
        mocked_store,
        mocked_api_store,
        mocked_recog,
    ):
        mocked_failover.return_value = False
        mocked_privy.return_value = True
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr603@julofinance.com",
                "phone": "+628147536408",
                "status": "waiting",
                "userToken": "Token",
            },
            "message": "Waiting for Verification",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        api_data["response_status_code"] = 201
        data = api_data["response_json"]["data"]
        mocked_status.return_value = (data, api_data)
        mocked_api_store.return_value = None
        mocked_recog.return_value = None
        mocked_store.return_value = self.privy_customer
        return_value = check_customer_status(self.customer, self.application)
        mocked_api_store.assert_called()
        mocked_status.assert_called()
        mocked_privy.assert_called_once()
        mocked_failover.assert_called_once()
        self.assertDictEqual(
            return_value,
            {
                'privy_status': 'verified',
                'failed_image_types': [],
                'failed_images': [],
                'failed': False,
                'uploaded_failed_images': [],
                'is_privy_mode': True,
                'is_failover_active': False
            }
        )

    def test_store_privy_document_data_julo_one(self):
        data = {
            "title": "DEVPR2779_3000008063.pdf",
            "docToken": self.privy_document.privy_document_token,
            "recipients": [
                {
                    "type": "Signer",
                    "privyId": "DEV-JU1612",
                    "signedAt": None,
                    "signatoryStatus": "In Progress",
                },
                {
                    "type": "Signer",
                    "privyId": "DEVPR2779",
                    "signedAt": None,
                    "signatoryStatus": "In Progress",
                },
            ],
            "urlDocument": "UrlDoc",
            "documentStatus": "In Progress",
        }
        return_value = store_privy_document_data_julo_one(
            self.loan, self.privy_customer, data
        )
        self.privy_document.refresh_from_db()
        self.assertEqual(return_value, self.privy_document)

    # @mock.patch('juloserver.julo_privyid.clients.privy.JuloPrivyClient.document_upload')
    # def test_upload_document_to_privy_julo_one(self, mocked_status):
    #     mocked_status =
    #     upload_document_to_privy_julo_one(self.privy_customer, self.loan)

    def test_is_privy_custumer_valid(self):
        return_value = is_privy_custumer_valid(self.application)
        self.assertEqual(return_value, self.privy_customer)

    @mock.patch("juloserver.julo_privyid.services.common.upload_document")
    @mock.patch("juloserver.julo_privyid.services.common.requests.get")
    def test_upload_privy_sphp_document(self, mocked_request, mocked_upload):
        mocked = mock.MagicMock()
        mocked.content = "abcd"
        mocked_request.return_value = mocked
        self.document = DocumentFactory(
            document_type="sphp_julo", loan_xid=self.loan.loan_xid
        )
        mocked_upload.return_value = None

        upload_privy_sphp_document(
            "www.google.com", self.loan.id, self.loan.loan_xid, "MrXyz"
        )
        mocked_request.assert_called()
        mocked_upload.assert_called()

    def test_update_digital_signature_face_recognition(self):
        self.aws_face_log = AwsFaceRecogLogFactory(
            customer_id=self.customer.id,
            application_id=self.application.id,
            is_indexed=True,
            is_quality_check_passed=True,
        )
        self.digital = DigitalSignatureFaceResultFactory()
        self.aws_face_log.digital_signature_face_result = self.digital
        self.aws_face_log.save()
        return_value = update_digital_signature_face_recognition(
            self.application, self.privy_customer
        )
        self.assertTrue(return_value)


class TestReuploadPrivy(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer, product_line=self.product_line)
        self.feature_settings = FeatureSettingFactory(
            feature_name='privy_reupload_settings', is_active=True,
            parameters=dict(
                KTP_CODES=['PRVK002', 'PRVK003', 'PRVK004', 'PRVK013', 'PRVD001',
                     'PRVD002', 'PRVD005', 'PRVK019', 'PRVK016'],
                E_KTP_CODES=['PRVP010'],
                SELFIE_CODES=['PRVS001', 'PRVS003', 'PRVS004', 'PRVS006', 'PRVD001', 'PRVD011',
                              'PRVD002', 'PRVD005', 'PRVD013', 'PRVD007',
                              'PRVD009'],
                SELFIE_WITH_KTP_CODES=['PRVS002', 'PRVP006', 'PRVP014'],
                DRIVER_LICENSE_CODES=['PRVK011', 'PRVK012', 'PRVP004', 'PRVP005', 'PRVK017',
                                      'PRVP012', 'PRVP015', 'PRVD013', 'PRVK006', 'PRVK016'],
                KK_CODES=['PRVK009', 'PRVK015', 'PRVK018', 'PRVN004', 'PRVP001', 'PRVD007', 'PRVD011',
                          'PRVP002', 'PRVP003', 'PRVK008',
                          'PRVK019', 'PRVK017', 'PRVD009'],
                REJECTED_CODES=['PRVK001', 'PRVK014', 'PRVM002', 'PRVM001', 'PRVM003',
                                'PRVN002', 'PRVD004', 'PRVP009']
            ))
        self.privy_customer = PrivyCustomerFactory(customer=self.customer)

    @mock.patch('juloserver.julo_privyid.views.get_privy_feature')
    def test_reupload_image(self, mocked_privy):
        mocked_privy.return_value = True
        data = {"data": "NotEmpty", 'upload': open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', mode='rb')}
        res = self.client.post('/api/julo_privy/v1/upload-image-reupload/sim_privy/', data=data)
        self.assertIs(res.status_code, 201)

        data = {"data": "NotEmpty", 'upload': open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', mode='rb')}
        res = self.client.post('/api/julo_privy/v1/upload-image-reupload/ktp_privy/', data=data)
        self.assertIs(res.status_code, 201)

        data = {"data": "NotEmpty", 'upload': open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', mode='rb')}
        res = self.client.post('/api/julo_privy/v1/upload-image-reupload/ektp_privy/', data=data)
        self.assertIs(res.status_code, 201)

        data = {"data": "NotEmpty", 'upload': open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', mode='rb')}
        res = self.client.post('/api/julo_privy/v1/upload-image-reupload/selfie_privy/', data=data)
        self.assertIs(res.status_code, 201)

        data = {"data": "NotEmpty", 'upload': open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', mode='rb')}
        res = self.client.post('/api/julo_privy/v1/upload-image-reupload/selfie_dengan_ktp_privy/', data=data)
        self.assertIs(res.status_code, 201)

        data = {"data": "NotEmpty", 'upload': open(
            settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', mode='rb')}
        res = self.client.post('/api/julo_privy/v1/upload-image-reupload/kk_privy/', data=data)
        self.assertIs(res.status_code, 201)

    def test_get_image_reupload(self):
        image_type = PRIVY_IMAGE_TYPE[PrivyReUploadCodes.IMAGE_MAPPING[PrivyReUploadCodes.KK]]
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type=image_type,
                                  image_status=0)
        image = get_image_for_reupload(self.application.id, PrivyReUploadCodes.KK)
        self.assertIsNotNone(image)
        self.assertEqual(type(image), Image)

        image_type = PRIVY_IMAGE_TYPE[PrivyReUploadCodes.IMAGE_MAPPING[PrivyReUploadCodes.SELFIE]]
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type=image_type,
                                  image_status=0)
        image = get_image_for_reupload(self.application.id, PrivyReUploadCodes.SELFIE)
        self.assertIsNotNone(image)
        self.assertEqual(type(image), Image)

        image_type = PRIVY_IMAGE_TYPE[PrivyReUploadCodes.IMAGE_MAPPING[PrivyReUploadCodes.E_KTP]]
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type=image_type,
                                  image_status=0)
        image = get_image_for_reupload(self.application.id, PrivyReUploadCodes.E_KTP)
        self.assertIsNotNone(image)
        self.assertEqual(type(image), Image)

        image_type = PRIVY_IMAGE_TYPE[PrivyReUploadCodes.IMAGE_MAPPING[PrivyReUploadCodes.KTP]]
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type=image_type,
                                  image_status=0)
        image = get_image_for_reupload(self.application.id, PrivyReUploadCodes.KTP)
        self.assertIsNotNone(image)
        self.assertEqual(type(image), Image)

        image_type = PRIVY_IMAGE_TYPE[PrivyReUploadCodes.IMAGE_MAPPING[PrivyReUploadCodes.SELFIE_WITH_KTP]]
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type=image_type,
                                  image_status=0)
        image = get_image_for_reupload(self.application.id, PrivyReUploadCodes.SELFIE_WITH_KTP)
        self.assertIsNotNone(image)
        self.assertEqual(type(image), Image)

        image_type = PRIVY_IMAGE_TYPE[PrivyReUploadCodes.IMAGE_MAPPING[PrivyReUploadCodes.DRIVING_LICENSE]]
        self.image = ImageFactory(image_source=self.application.id,
                                  image_type=image_type,
                                  image_status=0)
        image = get_image_for_reupload(self.application.id, PrivyReUploadCodes.DRIVING_LICENSE)
        self.assertIsNotNone(image)
        self.assertEqual(type(image), Image)

    # @mock.patch('juloserver.julo_privyid.services.privy_services.store_privy_customer_data')
    # @mock.patch('juloserver.julo_privyid.services.privy_services.store_privy_api_data')
    # @mock.patch('juloserver.julo_privyid.services.privy_services.get_julo_privy_client')
    # @mock.patch('juloserver.julo_privyid.services.privy_services.get_privy_customer_data')
    # @mock.patch('juloserver.julo_privyid.services.privy_services.get_privy_feature')
    # @mock.patch('juloserver.julo_privyid.services.privy_services.get_failover_feature')
    # def test_check_customer_status(self, mocked_failover, mocked_privy, mocked_customer_data,
    #                                mocked_client, mocked_store_data, mocked_store_cust):
    #     mocked_failover.return_value = False
    #     mocked_privy.return_value = True
    #     mocked_customer_data.return_value = self.privy_customer
    #     client = mock.MagicMock()
    #     client.register_status.return_value = None, None
    #     mocked_client.return_value = client
    #     mocked_store_data.return_value = None
    #     mocked_store_cust.return_value = self.privy_customer
    #     return_resp = check_customer_status(self.customer, self.application)
    #
    #     self.assertIsNotNone(return_resp)
    #     mocked_failover.assert_called()
    #     mocked_privy.assert_called()
    #     mocked_customer_data.assert_called_with(self.customer)

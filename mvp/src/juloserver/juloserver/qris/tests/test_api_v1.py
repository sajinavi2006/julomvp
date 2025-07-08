from mock import MagicMock, patch, ANY
from faker import Faker

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from juloserver.julo.constants import FeatureNameConst
from juloserver.account.constants import AccountConstant
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.followthemoney.constants import LenderName
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CustomerFactory,
    FeatureSettingFactory,
    PartnerFactory,
    ApplicationFactory,
    ProductLineFactory,
    StatusLookupFactory,
)
from juloserver.loan.constants import LoanErrorCodes, LoanFeatureNameConst, LoanLogIdentifierType
from juloserver.loan.exceptions import AccountUnavailable, TransactionAmountTooLow
from juloserver.loan.models import LoanErrorLog
from juloserver.qris.constants import AmarCallbackConst, QrisLinkageStatus, QrisProductName
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.qris.serializers import BaseQrisRequestSerializer
from django.db import DatabaseError
from django.core.files.uploadedfile import SimpleUploadedFile
from juloserver.qris.services.user_related import (
    QrisAgreementService,
    QrisUploadSignatureService,
    QrisListTransactionService,
)
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.qris.exceptions import (
    AlreadySignedWithLender,
    NoQrisLenderAvailable,
    QrisLinkageNotFound,
)


class TestPermissionQrisView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.partner_xid = "Amar123321"
        self.partner = PartnerFactory(
            user=self.user, name=PartnerNameConstant.AMAR, partner_xid=self.partner_xid
        )

    def test_permission_qris_api(self):
        # without headers => will got 403
        res = self.client.post('/api/qris/v1/transaction-limit-check')
        assert res.status_code == 403

        # wrong partner_xid
        headers = {'HTTP_PARTNERXID': 'invalid_xid'}
        res = self.client.post('/api/qris/v1/transaction-limit-check', **headers)
        assert res.status_code == 403

        # user is not partner
        self.partner.user_id = None
        self.partner.save()
        res = self.client.post('/api/qris/v1/transaction-limit-check')
        assert res.status_code == 403

    def test_qris_base_serializer(self):
        qris_linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.pk, partner_id=self.partner.pk
        )
        fake = Faker()
        # Generate a fake UUID
        fake_uuid = fake.uuid4()
        data = {"partnerUserId": fake_uuid}
        serializer_class = BaseQrisRequestSerializer(data=data)
        assert serializer_class.is_valid() == False

        data = {"partnerUserId": qris_linkage.to_partner_user_xid}
        serializer_class = BaseQrisRequestSerializer(data=data)
        assert serializer_class.is_valid() == True


class QrisUserAgreementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory(username='testuser', password='12345')
        self.customer = CustomerFactory(user=self.user)
        self.client.force_authenticate(user=self.user)
        self.url = '/api/qris/v1/user/agreement'

        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )

        self.multi_lender_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_MULTIPLE_LENDER,
            is_active=True,
            parameters={
                "out_of_balance_threshold": 0,
                "lender_names_ordered_by_priority": [
                    self.lender.lender_name,
                ],
            },
        )

    @patch.object(QrisAgreementService, 'validate_agreement_type')
    @patch.object(QrisAgreementService, 'get_document_content')
    def test_get_agreement_success(self, mock_get_content, mock_validate):
        expected_content = "Test content"
        mock_validate.return_value = (True, None)
        mock_get_content.return_value = expected_content

        response = self.client.get(
            self.url,
            {
                'partner_name': PartnerNameConstant.AMAR,
                'document_type': 'master_agreement',
                'lender_name': self.lender.lender_name,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'], expected_content)

    def test_get_agreement_invalid(self):
        # invalid product_name (bad partner name)
        response = self.client.get(
            self.url,
            {
                'partner_name': "bad_partner_name",
                'document_type': 'master_agreement',
                'lender_name': self.lender.lender_name,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errors'][0], "Product not supported")

        # invalid document_type
        response = self.client.get(
            self.url,
            {
                'partner_name': PartnerNameConstant.AMAR,
                'document_type': 'bad_doc_type',
                'lender_name': self.lender.lender_name,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errors'][0], "Document type not supported")

        # invalid lender name
        response = self.client.get(
            self.url,
            {
                'partner_name': PartnerNameConstant.AMAR,
                'document_type': 'master_agreement',
                'lender_name': "fake_lender",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errors'][0], "Lender not valid")


class QrisUserSignatureTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )

        self.user.set_password('123456')
        self.user.save()
        CustomerPinFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        amar_user = AuthUserFactory(username='amar', password='12345')
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=amar_user)

        url_params = (
            f"?partner_name={PartnerNameConstant.AMAR}&lender_name={self.lender.lender_name}"
        )
        self.url = '/api/qris/v1/user/signature' + url_params

        # Create a simple image file for testing
        self.image = SimpleUploadedFile(
            name='test_image.jpg',
            content=b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b',
            content_type='image/jpeg',
        )

        # feature setting
        self.multi_lender_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_MULTIPLE_LENDER,
            is_active=True,
            parameters={
                "out_of_balance_threshold": 0,
                "lender_names_ordered_by_priority": [
                    self.lender.lender_name,
                ],
            },
        )

    def get_valid_payload(self):
        return {'upload': self.image, 'data': 'test_image.jpg', 'pin': '123456'}

    @patch.object(QrisUploadSignatureService, 'process_linkage_and_upload_signature')
    def test_upload_signature_success(self, mock_upload):
        mock_upload.return_value = None
        response = self.client.post(self.url, data=self.get_valid_payload(), format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_upload.assert_called_once()

    @patch.object(QrisUploadSignatureService, 'process_linkage_and_upload_signature')
    def test_upload_signature_duplicate(self, mock_upload):
        mock_upload.side_effect = DatabaseError("Duplicate request")

        response = self.client.post(self.url, data=self.get_valid_payload(), format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['errors'][0], "Duplicate request")

    def test_upload_signature_missing_data(self):
        response = self.client.post(self.url, data={}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_signature_invalid_file_extension(self):
        invalid_payload = self.get_valid_payload()
        invalid_payload['data'] = 'test_image.txt'

        response = self.client.post(self.url, data=invalid_payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def tearDown(self):
        self.image.close()

    @patch.object(QrisUploadSignatureService, 'process_linkage_and_upload_signature')
    def test_already_signed_with_lender(self, mock_upload):
        mock_upload.side_effect = AlreadySignedWithLender
        response = self.client.post(self.url, data=self.get_valid_payload(), format='multipart')

        mock_upload.assert_called_once()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.data['errors'][0], "Already signed with this lender")


class QrisTransactionListViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        amar_user = AuthUserFactory(username='amar', password='12345')
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=amar_user)
        self.url = '/api/qris/v1/transactions?partner_name=' + PartnerNameConstant.AMAR

    @patch.object(QrisListTransactionService, 'get_successful_transaction')
    def test_get_transactions_success(self, mock_get_successful_transaction):
        mock_transactions = {
            '11-2024': [
                {
                    'merchant_name': 'Merchant A',
                    'transaction_date': '03-11-2024',
                    'amount': 'Rp 10.000',
                },
                {
                    'merchant_name': 'Merchant B',
                    'transaction_date': '02-11-2024',
                    'amount': 'Rp 20.000',
                },
            ]
        }

        mock_get_successful_transaction.return_value = mock_transactions
        self.url = self.url + '&limit=10'
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], mock_transactions)

    def test_get_transactions_partner_not_found(self):
        response = self.client.get('/api/qris/v1/transactions?partner_name=invalid_name')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Partner not found')

    @patch.object(QrisListTransactionService, 'get_successful_transaction')
    def test_get_transactions_qris_linkage_not_found(self, mock_get_successful_transaction):
        mock_get_successful_transaction.side_effect = QrisLinkageNotFound()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Qris User Linkage not found')

    @patch.object(QrisListTransactionService, 'get_successful_transaction')
    def test_get_transactions_with_limit(self, mock_get_successful_transaction):
        mock_transactions = [
            {
                '11-2024': [
                    {
                        'merchant_name': 'Merchant A',
                        'transaction_date': '03-11-2024',
                        'amount': 'Rp 10.000',
                    },
                    {
                        'merchant_name': 'Merchant B',
                        'transaction_date': '02-11-2024',
                        'amount': 'Rp 20.000',
                    },
                ]
            }
        ]

        mock_get_successful_transaction.return_value = mock_transactions
        self.url = self.url + '&limit=1'
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], mock_transactions)
        mock_get_successful_transaction.assert_called_once_with(limit=1)


class TestQrisUserState(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.partner_user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)

        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(
            user=self.partner_user,
            name=PartnerNameConstant.AMAR,
        )
        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )

    def test_invalid_partner_name(self):
        fake_partner = "hehee"
        res = self.client.get('/api/qris/v1/user/state?partner_name={}'.format(fake_partner))

        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid Partner", res.data['errors'][0])

    def test_get_qris_cofig(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.QRIS_LANDING_PAGE_CONFIG,
            parameters={
                "faq_link": "https://www.julo.co.id/faq/faq-julo-ponsel-plus",
                "banner_image_link": "banner.png"
            }
        )
        res = self.client.get('/api/qris/v1/config')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {
            'success': True,
            'data': {
                'faq_link': 'https://www.julo.co.id/faq/faq-julo-ponsel-plus',
                'banner_image_link': 'banner.png'
            }, 'errors': []
        })

    @patch('juloserver.qris.views.view_api_v1.get_qris_user_state_service')
    def test_200_amar(self, mock_get_qris_user_state):
        mock_service = MagicMock()
        mock_get_qris_user_state.return_value = mock_service

        mock_data = {
            "email": "abc@gmail.com",
            "phone": "08123456789",
            "to_partner_xid": "3d474ab5879749538a2cfcb0cc8a6a01",
            "is_linkage_active": False,
            "nik": "123245",
            "signature_id": str(123),
            "faq_link": "abc.com",
            "available_limit": 100_000,
            "to_sign_lender": "",
            "registration_progress_bar": {
                "is_active": True,
                "percentage": "40",
                "messages": {
                    "title": "Langkah 1: Aktifkan QRIS",
                    "body": "Sebentar lagi QRIS kamu aktif. Tunggu info dari kami, ya!",
                    "footer": "Tenang, datamu dijamin aman",
                },
            },
        }
        mock_service.get_response.return_value = mock_data

        res = self.client.get(
            '/api/qris/v1/user/state?partner_name={}'.format(PartnerNameConstant.AMAR)
        )

        self.assertEqual(res.status_code, 200)

        self.assertEqual(res.data['data'], mock_data)

        mock_get_qris_user_state.assert_called_once_with(
            customer_id=self.customer.id,
            partner_name=self.partner.name,
        )

    @patch('juloserver.qris.views.view_api_v1.get_qris_user_state_service')
    def test_200_before_sign_signature(self, mock_get_qris_user_state):
        """
        Before signing signature, most data is empty

        """
        mock_service = MagicMock()
        mock_get_qris_user_state.return_value = mock_service

        mock_data = {
            "email": "",
            "phone": "",
            "to_partner_xid": "",
            "is_linkage_active": False,
            "nik": "",
            "signature_id": "",
            "faq_link": "abc.com",
            "to_sign_lender": self.lender.lender_name,
        }
        mock_service.get_response.return_value = mock_data

        res = self.client.get(
            '/api/qris/v1/user/state?partner_name={}'.format(PartnerNameConstant.AMAR)
        )

        self.assertEqual(res.status_code, 200)

        self.assertEqual(res.data['data'], mock_data)

        mock_get_qris_user_state.assert_called_once_with(
            customer_id=self.customer.id,
            partner_name=self.partner.name,
        )

    @patch('juloserver.qris.views.view_api_v1.get_qris_user_state_service')
    def test_200_no_qris_lender_available(self, mock_get_qris_user_state):
        mock_get_qris_user_state.side_effect = NoQrisLenderAvailable

        res = self.client.get(
            '/api/qris/v1/user/state?partner_name={}'.format(PartnerNameConstant.AMAR)
        )

        self.assertEqual(res.status_code, 400)

        self.assertEqual(res.data['errors'][0], LoanErrorCodes.NO_LENDER_AVAILABLE.message)
        self.assertEqual(res.data['errorCode'], LoanErrorCodes.NO_LENDER_AVAILABLE.code)

        mock_get_qris_user_state.assert_called_once_with(
            customer_id=self.customer.id,
            partner_name=self.partner.name,
        )

class TestAmarRegisterLoginCallbackView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.partner_user = AuthUserFactory()
        # self.client.force_login(self.partner_user)
        # self.client.force_authenticate(user=self.partner_user)
        self.customer = CustomerFactory(user=self.partner_user)
        self.partner = PartnerFactory(user=self.partner_user, name=PartnerNameConstant.AMAR)
        self.token = self.partner_user.auth_expiry_token
        self.token.is_active = True
        self.token.save()

        self.client.credentials(
            HTTP_AUTHORIZATION="Token " + self.token.key,
            HTTP_PARTNERXID=self.partner.partner_xid,
        )

    @patch("juloserver.qris.views.view_api_v1.get_julo_sentry_client")
    def test_callback_invalid_status(self, mock_get_sentry_client):
        mock_get_sentry_client.return_value = MagicMock()
        url = "/api/qris/v1/amar/callback/initial-account-status"
        fake_status = "yeah yeah"

        data = {
            "partnerCustomerId": "2a196a04bf5f45a18187136a6d1706ff",
            "status": fake_status,
            "accountNumber": "1503566938",
            "type": "new",
        }
        response = self.client.post(url, data=data, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid status", str(response.data['errors'][0]))

    @patch("juloserver.qris.views.view_api_v1.get_julo_sentry_client")
    def test_callback_invalid_type(self, mock_get_sentry_client):
        mock_get_sentry_client.return_value = MagicMock()
        url = "/api/qris/v1/amar/callback/initial-account-status"
        fake_type = "yeah yeah"

        data = {
            "partnerCustomerId": "2a196a04bf5f45a18187136a6d1706ff",
            "status": "accepted",
            "accountNumber": "1503566938",
            "type": fake_type,
        }
        response = self.client.post(url, data=data, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid type", str(response.data['errors'][0]))

    def test_callback_invalid_partnerCustomerId(self):
        url = "/api/qris/v1/amar/callback/initial-account-status"
        fake_uuid = "lasdkfj0234"

        data = {
            "partnerCustomerId": fake_uuid,
            "status": "accepted",
            "accountNumber": "1503566938",
            "type": "new",
        }
        response = self.client.post(url, data=data, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn("Partnercustomerid", str(response.data['errors'][0]))

    @patch("juloserver.qris.services.view_related.process_callback_register_from_amar_task")
    def test_callback_ok(self, mock_process_callback):
        to_partner_user_xid = "2a196a04bf5f45a18187136a6d1706ff"
        status = "accepted"
        account_num = "1503566938"
        type = "existing"

        url = "/api/qris/v1/amar/callback/initial-account-status"
        data = {
            "partnerCustomerId": to_partner_user_xid,
            "status": status,
            "accountNumber": account_num,
            "type": type,
            "source_type": "partner_apps",
            "client_id": "ebf-amarbank",
            "reject_reason": "",
        }
        response = self.client.post(url, data=data, format='json')

        self.assertEqual(response.status_code, 200)

        mock_process_callback.delay.assert_called_once_with(
            to_partner_user_xid=to_partner_user_xid,
            amar_status=status,
            payload=data,
        )

    @patch("juloserver.qris.services.view_related.process_callback_register_from_amar_task")
    def test_callback_ok_rejected_status(self, mock_process_callback):
        to_partner_user_xid = "2a196a04bf5f45a18187136a6d1706ff"
        status = "rejected"
        type = "new"

        url = "/api/qris/v1/amar/callback/initial-account-status"
        data = {
            "partnerCustomerId": to_partner_user_xid,
            "status": status,
            "accountNumber": "",
            "type": type,
            "source_type": "partner_apps",
            "client_id": "ebf-amarbank",
            "reject_reason": "selfieHoldingIdCard,editedSelfie,selfieCapturedByOther,zeroLiveness",
        }
        response = self.client.post(url, data=data, format='json')

        self.assertEqual(response.status_code, 200)

        mock_process_callback.delay.assert_called_once_with(
            to_partner_user_xid=to_partner_user_xid,
            amar_status=status,
            payload=data,
        )

    @patch('juloserver.qris.views.view_api_v1.AmarRegisterLoginCallbackService')
    def test_extra_fields_still_ok(self, mock_register_service):
        # if new fields are added, no need for develpment

        to_partner_user_xid = "2a196a04bf5f45a18187136a6d1706ff"
        status = "accepted"
        account_num = "123049"
        type = "existing"

        url = "/api/qris/v1/amar/callback/initial-account-status"
        initial_data = {
            "partnerCustomerId": to_partner_user_xid,
            "status": status,
            "accountNumber": account_num,
            "type": type,
            "new_field": {
                "abc": True,
            },
            "client_id": "123-123-123",
            "reject_reason": "123",
            "source_type": "partner_apps",
        }
        response = self.client.post(url, data=initial_data, format='json')

        self.assertEqual(response.status_code, 200)

        mock_register_service.assert_called_once_with(
            data=initial_data,
        )


class TestTransactionLimitCheckView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.partner_user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.partner_user)
        self.partner = PartnerFactory(user=self.partner_user, name=PartnerNameConstant.AMAR)
        self.token = self.partner_user.auth_expiry_token
        self.token.is_active = True
        self.token.save()

        self.client.credentials(
            HTTP_AUTHORIZATION="Token " + self.token.key,
            HTTP_PARTNERXID=self.partner.partner_xid,
        )

        self.qris_customer = CustomerFactory()
        self.linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.qris_customer.id,
            partner_id=self.partner.id,
            partner_callback_payload={"any": "any"},
        )

        self.qris_error_log_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_ERROR_LOG,
            is_active=True,
        )

    @patch("juloserver.qris.views.view_api_v1.QrisLimitEligibilityService")
    def test_200_ok(self, mock_limit_eligibility_service):
        mock_obj = MagicMock()

        mock_limit_eligibility_service.return_value = mock_obj
        transaction_detail = {
            "feeAmount": 1000.1,
            "tipAmount": 1000.2,
            "transactionAmount": 1000.5,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            # "acquirerId": "abcd",
            "acquirerName": "abcd",
            "terminalId": "",
        }

        totalAmount = 50_000.0
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        mock_obj.perform_check.return_value = None

        url = "/api/qris/v1/transaction-limit-check"
        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 200)

        mock_limit_eligibility_service.assert_called_once_with(
            data=ANY,
            partner=self.partner,
        )

    def test_400_bad_input(self):

        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "acquirerId": "abcd",
            "acquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = 50_000

        # bad partnerUserId
        input_data = {
            "partnerUserId": "123",
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        url = "/api/qris/v1/transaction-limit-check"
        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(LoanErrorCodes.GENERAL_ERROR.code, response.data['errorCode'])
        self.assertIn("partnerUserId", response.data['errors'][0])

        # bad productId & productName
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": -1,
            "productName": "QRIS",
            "transactionDetail": transaction_detail,
        }

        url = "/api/qris/v1/transaction-limit-check"
        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(LoanErrorCodes.GENERAL_ERROR.code, response.data['errorCode'])
        self.assertIn("productId", response.data['errors'][0])

        # bad totalAmount
        totalAmount = 0
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": 1,
            "productName": "QRIS",
            "transactionDetail": transaction_detail,
        }

        url = "/api/qris/v1/transaction-limit-check"
        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(LoanErrorCodes.GENERAL_ERROR.code, response.data['errorCode'])
        self.assertIn("totalAmount", response.data['errors'][0])

    @patch("juloserver.qris.views.view_api_v1.QrisLimitEligibilityService")
    def test_400_loan_error_code(self, mock_limit_eligibility_service):
        mock_obj = MagicMock()

        mock_limit_eligibility_service.return_value = mock_obj
        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "acquirerId": "abcd",
            "acquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = 50_000
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }
        url = "/api/qris/v1/transaction-limit-check"

        # TEST NO ACCOUNT
        mock_obj.perform_check.side_effect = AccountUnavailable
        # linkage is None => log to_partner_user_xid in LoanErrorLog
        mock_obj.linkage = None

        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.ACCOUNT_UNAVAILABLE.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.ACCOUNT_UNAVAILABLE.message)

        mock_limit_eligibility_service.assert_called_once_with(
            data=ANY,
            partner=self.partner,
        )

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=str(self.linkage.to_partner_user_xid),
            identifier_type=LoanLogIdentifierType.TO_AMAR_USER_XID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.ACCOUNT_UNAVAILABLE.code)
        self.assertEqual(qris_error_log.error_detail, LoanErrorCodes.ACCOUNT_UNAVAILABLE.name)
        self.assertEqual(qris_error_log.http_status_code, 400)
        self.assertEqual(qris_error_log.identifier, str(self.linkage.to_partner_user_xid))

        # TEST AMOUNT TOO LOW
        mock_obj.perform_check.side_effect = TransactionAmountTooLow
        mock_obj.linkage = self.linkage

        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.code)
        self.assertEqual(
            response.data['errors'][0], LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.message
        )

        # check logs
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.code)
        self.assertEqual(
            qris_error_log.error_detail, LoanErrorCodes.TRANSACTION_AMOUNT_TOO_LOW.name
        )
        self.assertEqual(qris_error_log.http_status_code, 400)
        self.assertEqual(qris_error_log.identifier, str(self.linkage.customer_id))

        # TEST GENERAL ERROR
        error_message = "general error"
        mock_obj.perform_check.side_effect = Exception(error_message)
        # linkage is not None => log `customer_id` in LoanErrorLog
        mock_obj.linkage = self.linkage

        response = self.client.post(url, data=input_data, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.GENERAL_ERROR.code)
        self.assertEqual(response.data['errors'][0], LoanErrorCodes.GENERAL_ERROR.message)

        # check logs general error
        qris_error_log = LoanErrorLog.objects.filter(
            identifier=self.linkage.customer_id,
            identifier_type=LoanLogIdentifierType.CUSTOMER_ID,
            error_code=LoanErrorCodes.GENERAL_ERROR.code,
        ).last()
        self.assertIsNotNone(qris_error_log)

        self.assertEqual(qris_error_log.api_url, url)
        self.assertEqual(qris_error_log.error_code, LoanErrorCodes.GENERAL_ERROR.code)
        self.assertEqual(qris_error_log.error_detail, error_message)
        self.assertEqual(qris_error_log.http_status_code, 400)
        self.assertEqual(qris_error_log.identifier, str(self.linkage.customer_id))


class TestAmarLoanCallbackView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.partner_user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.partner_user)
        self.partner = PartnerFactory(user=self.partner_user, name=PartnerNameConstant.AMAR)
        self.token = self.partner_user.auth_expiry_token
        self.token.is_active = True
        self.token.save()

        self.client.credentials(
            HTTP_AUTHORIZATION="Token " + self.token.key,
            HTTP_PARTNERXID=self.partner.partner_xid,
        )

        self.customer = CustomerFactory()
        self.linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            partner_callback_payload={"any": "any"},
        )
        self.serviceId = AmarCallbackConst.LoanDisbursement.SERVICE_ID

    @patch(
        "juloserver.qris.services.view_related.process_callback_transaction_status_from_amar_task"
    )
    def test_200(self, mock_process_callback):
        payload = {
            "serviceId": self.serviceId,
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "00",  # success
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": "anytext",
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 200)

        mock_process_callback.delay.assert_called_once_with(
            payload=ANY,
        )
        _, kwargs = mock_process_callback.delay.call_args

        assert kwargs['payload']['serviceId'] == self.serviceId
        assert kwargs['payload']['partnerCustomerID'] == self.linkage.to_partner_user_xid.hex

    @patch(
        "juloserver.qris.services.view_related.process_callback_transaction_status_from_amar_task"
    )
    def test_200_case_fail_loan(self, mock_process_callback):
        payload = {
            "serviceId": self.serviceId,
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "01",  # failed
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "",
                "transactionID": "anytext",
                "customerPan": "",
                "amount": 10000,
            },
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 200)

        mock_process_callback.delay.assert_called_once_with(
            payload=ANY,
        )
        _, kwargs = mock_process_callback.delay.call_args

        assert kwargs['payload']['serviceId'] == self.serviceId
        assert kwargs['payload']['partnerCustomerID'] == self.linkage.to_partner_user_xid.hex

    def test_400(self):
        # serviceId
        payload = {
            "serviceId": "fakeservice",
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "00",  # success
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": "anytext",
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.GENERAL_ERROR.code)

        self.assertIn("serviceId", response.data['errors'][0])

        # partnerCustomerId
        payload = {
            "serviceId": self.serviceId,
            "amarbankAccount": "1513001959",
            "partnerCustomerID": "fake id",
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "00",  # success
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": "anytext",
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.GENERAL_ERROR.code)

        self.assertIn("partnerCustomerID", response.data['errors'][0])

        # status
        payload = {
            "serviceId": self.serviceId,
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "9999",  # fake status
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": "anytext",
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(response.data['errorCode'], LoanErrorCodes.GENERAL_ERROR.code)

        self.assertIn("status", response.data['errors'][0])

    @patch(
        "juloserver.qris.services.view_related.process_callback_transaction_status_from_amar_task"
    )
    def test_ok_amar_pending_status(self, mock_process_callback):
        payload = {
            "serviceId": self.serviceId,
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "02",  # pending status
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": "anytext",
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 200)

        mock_process_callback.delay.assert_called_once_with(
            payload=ANY,
        )
        _, kwargs = mock_process_callback.delay.call_args

        assert kwargs['payload']['serviceId'] == self.serviceId
        assert kwargs['payload']['partnerCustomerID'] == self.linkage.to_partner_user_xid.hex

    @patch('juloserver.qris.views.view_api_v1.AmarTransactionStatusCallbackService')
    def test_extra_fields_still_ok(self, mock_service):
        # if new fields are added, no need for develpment

        payload = {
            "serviceId": self.serviceId,
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "00",  # pending status
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": "anytext",
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
            "new_field": {"hello": True, "world": "abc", "sam": 123},
        }

        url = "/api/qris/v1/amar/loan/callback"
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, 200)

        mock_service.assert_called_once_with(
            validated_data=payload,
        )


class QrisTenureRangeView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)

        self.customer = CustomerFactory(user=self.user)
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_TENURE_FROM_LOAN_AMOUNT,
            is_active=True,
            parameters={},
        )
        self.credit_matrix = CreditMatrixFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=2,
        )

    @patch("juloserver.qris.views.view_api_v1.QrisTenureRangeService")
    def test_200(self, mock_service):
        mock_service_object = MagicMock()
        mock_service.return_value = mock_service_object

        response_data = {"any": "any"}
        mock_service_object.get_response.return_value = response_data

        url = "/api/qris/v1/tenure-range"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        mock_service.assert_called_once_with(
            customer=self.customer,
        )

        self.assertEqual(response.data['data'], response_data)

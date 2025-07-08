import io
import operator
from mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.cfs.tests.factories import (
    CashbackBalanceFactory,
    CfsActionFactory,
    CfsTierFactory,
    ImageFactory,
)
from juloserver.cfs.constants import (
    ImageUploadType,
    CfsActionId,
    FeatureNameConst as CFSFeatureNameConst
)
from juloserver.cfs.authentication import EasyIncomeWebToken
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    MobileFeatureSettingFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.cfs.models import CfsAssignmentVerification
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.otp.constants import OTPType
from juloserver.julo.models import OtpRequest
from juloserver.pin.tests.factories import CustomerPinFactory

PACKAGE_NAME = 'juloserver.cfs.views.api_views'


class TestCfs(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.cashback_balance = CashbackBalanceFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                },
            }
        )
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        CfsTierFactory(id=1, name='Starter', point=100, icon='123.pnj')
        CfsTierFactory(id=2, name='Advanced', point=300, icon='123.pnj')
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj')
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj')
        FeatureSettingFactory(
            feature_name='otp_switch',
            parameters={
                'message': 'Harap masukkan kode OTP yang telah kami kirim lewat SMS atau Email ke '
                'nomor atau email Anda yang terdaftar.',
            },
            is_active=False,
        )

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_do_mission_verify_phone_2(self, mock_send_cfs_ga_event):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application.save()
        PdCreditModelResultFactory(id=122, application_id=self.application.id, pgood=0.8)
        self.token = self.user.auth_expiry_token.key
        self.otp_action_setting = FeatureSettingFactory(
            feature_name='otp_action_type',
            parameters={
                'login': 'short_lived',
                'verify_phone_number_2': 'short_lived'
            }
        )
        self.action = CfsActionFactory(
            id=8,
            is_active=True,
            action_code='verify_phone_number_2',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        data = {
            "otp_service_type": "sms",
            "action_type": "verify_phone_number_2",
            "phone_number": "08123456789",
        }
        self.mfs = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 2,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                    'otp_max_validate': 3
                },
                'wait_time_seconds': 400
            },
            is_active=True,
        )
        result = self.client.post('/api/otp/v2/request', data=data)
        self.assertEqual(result.json()['data']['is_feature_active'], True)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        otp_request = OtpRequest.objects.filter(
            customer=self.customer,
            otp_service_type__in=[OTPType.SMS]
        ).latest('id')
        result = self.client.post(
            '/api/otp/v1/validate',
            data={
                'otp_token': otp_request.otp_token,
                'action_type': 'verify_phone_number_2'
            }
        )
        session_token = result.json()['data']['session_token']
        self.assertEqual(result.status_code, 200)

        data = {'session_token': session_token, 'pin': '112233'}

        # wrong pin
        response = self.client.post(
            '/api/cfs/v2/do_mission/verify_phone_number_2/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        self.assertEqual(response.json()['errors'],
                         ['Email, NIK, Nomor Telepon, PIN, atau Kata Sandi kamu salah'])
        assert response.status_code == 401

        # correct pin
        data['pin'] = '123456'
        response = self.client.post(
            '/api/cfs/v2/do_mission/verify_phone_number_2/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200


class TestWebCFS(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.upload_image_url = '/api/cfs/v2/web/images/'
        self.upload_document_url = '/api/cfs/v2/web/do_mission/upload_document/'
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        CfsTierFactory(id=1, name='Starter', point=100, icon='123.pnj')
        CfsTierFactory(id=2, name='Advanced', point=300, icon='123.pnj')
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj')
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj')
        self.cfs_upload_img_fs = FeatureSettingFactory(
            feature_name=CFSFeatureNameConst.CFS_UPLOAD_IMAGE_SIZE,
            is_active=True,
            parameters={},
        )
        self.user_token = EasyIncomeWebToken.generate_token_from_user(self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.user_token)

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        image = io.BytesIO()
        Image.new('RGB', size).save(image, image_format)
        image.seek(0)
        return image

    @staticmethod
    def create_document():
        buffer = io.BytesIO()
        canv = canvas.Canvas(buffer, pagesize=A4)
        canv.drawString(100, 400, "test")
        canv.save()
        pdf = buffer.getvalue()
        return pdf

    def test_web_cfs_upload_image_failed(self):
        request_data = {}
        response = self.client.post(self.upload_image_url, request_data)
        self.assertEqual(response.status_code, 400)

        request_data['image_type'] = ImageUploadType.PAYSTUB
        response = self.client.post(self.upload_image_url, request_data)
        self.assertEqual(response.status_code, 400)

        # Invalid file upload
        document = self.create_document()
        document_file = SimpleUploadedFile('test.pdf', document)
        request_data['upload'] = document_file
        response = self.client.post(self.upload_image_url, request_data)
        self.assertEqual(response.status_code, 400)

        # Maximum image size
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        request_data['upload'] = image_file

        self.cfs_upload_img_fs.parameters['max_size'] = 100
        self.cfs_upload_img_fs.save()
        response = self.client.post(self.upload_image_url, request_data)
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.cfs.views.api_v2_views.upload_image')
    def test_web_cfs_upload_image_success(self, mock_upload_image):
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        request_data = {
            "image_type": ImageUploadType.PAYSTUB,
            "upload": image_file
        }
        self.cfs_upload_img_fs.parameters['max_size'] = 10000
        self.cfs_upload_img_fs.save()
        response = self.client.post(self.upload_image_url, request_data)
        self.assertEqual(response.status_code, 201)
        mock_upload_image.apply_async.assert_called_once()

    def test_web_cfs_upload_document(self):
        self.images = ImageFactory.create_batch(
            3, image_source=self.application.id, image_type=ImageUploadType.BANK_STATEMENT
        )
        image_ids = list(map(operator.attrgetter("id"), self.images))
        data = {
            'image_ids': image_ids,
            'monthly_income': 2000000,
            'upload_type': ImageUploadType.BANK_STATEMENT
        }
        response = self.client.post(
            self.upload_document_url, data=data, format='json'
        )
        assert response.status_code == 404
        assert response.json()['errors'] == ['Action not found']

        self.action = CfsActionFactory(
            id=CfsActionId.UPLOAD_BANK_STATEMENT,
            is_active=True,
            action_code='upload_bank_statement',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/111.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=2000,
            repeat_occurrence_cashback_amount=500
        )
        response = self.client.post(
            self.upload_document_url, data=data, format='json'
        )
        assert response.status_code == 200

        cfs_assignment_verification = CfsAssignmentVerification.objects.get(
            account_id=self.account.id
        )
        self.assertEqual(cfs_assignment_verification.extra_data['image_ids'], image_ids)
        self.assertEqual(cfs_assignment_verification.monthly_income, 2000000)

    def test_web_cfs_upload_document_credit_card(self):
        self.images = ImageFactory.create_batch(
            3, image_source=self.application.id, image_type=ImageUploadType.CREDIT_CARD
        )
        image_ids = list(map(operator.attrgetter("id"), self.images))
        data = {
            'image_ids': image_ids,
            'monthly_income': 2000000,
            'upload_type': ImageUploadType.CREDIT_CARD
        }
        response = self.client.post(
            self.upload_document_url, data=data, format='json'
        )
        assert response.status_code == 404
        assert response.json()['errors'] == ['Action not found']

        self.action = CfsActionFactory(
            id=CfsActionId.UPLOAD_CREDIT_CARD,
            is_active=True,
            action_code='credit_card',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/111.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=2000,
            repeat_occurrence_cashback_amount=500
        )
        response = self.client.post(
            self.upload_document_url, data=data, format='json'
        )
        assert response.status_code == 200

        cfs_assignment_verification = CfsAssignmentVerification.objects.get(
            account_id=self.account.id
        )
        self.assertEqual(cfs_assignment_verification.extra_data['image_ids'], image_ids)
        self.assertEqual(cfs_assignment_verification.monthly_income, 2000000)

from __future__ import print_function

from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.exceptions import JuloException
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AppVersionFactory,
    AuthUserFactory,
    CustomerFactory,
    DigisignConfigurationFactory,
    DocumentFactory,
    MobileFeatureSettingFactory,
    PartnerFactory,
    ProductLineFactory,
    SignatureMethodHistoryFactory,
)


class TestDigisignRegisterViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignRegisterViewAPIv2_success(self, mock_get_julo_digisign_client):
        data = {'application_id': self.application.id}
        mock_get_julo_digisign_client.return_value.register.return_value = True
        response = self.client.post('/api/v2/digisign/register', data=data)
        assert response.status_code == 200


class TestDigisignSendDocumentViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignSendDocumentViewAPIv2_success(self, mock_get_julo_digisign_client):
        data = {'document_id': '', 'application_id': self.application.id, 'filename': ''}
        mock_get_julo_digisign_client.return_value.send_document.return_value = True
        response = self.client.post('/api/v2/digisign/send-document', data=data)
        assert response.status_code == 200


class TestDigisignActivateViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.is_digisign_web_browser')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignActivateViewAPIv2_success(
        self, mock_get_julo_digisign_client, mock_is_digisign_web_browser
    ):
        mock_get_julo_digisign_client.return_value.activation.return_value = ['success']
        response = self.client.get('/api/v2/digisign/activate')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.is_digisign_web_browser')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignActivateViewAPIv2_failed(
        self, mock_get_julo_digisign_client, mock_is_digisign_web_browser
    ):
        data = {}
        mock_get_julo_digisign_client.return_value.activation.side_effect = JuloException()
        response = self.client.get('/api/v2/digisign/activate', data=data)
        assert response.status_code == 400


class TestDigisignSignDocumentViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.document = DocumentFactory()
        self.application = ApplicationFactory(id=123123123)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.is_digisign_web_browser')
    @patch('juloserver.apiv2.views.signature_method_history_task')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignSignDocumentViewAPIv2_success(
        self,
        mock_get_julo_digisign_client,
        mock_signature_method_history_task,
        mock_is_digisign_web_browser,
    ):
        self.document.document_source = 123123123
        self.document.document_type = 'sphp_digisign'
        self.document.save()

        mock_get_julo_digisign_client.return_value.sign_document.return_value = ['success']
        response = self.client.get('/api/v2/digisign/sign-document/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.is_digisign_web_browser')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignSignDocumentViewAPIv2_failed(
        self, mock_get_julo_digisign_client, mock_is_digisign_web_browser
    ):
        self.document.document_source = 123123123
        self.document.document_type = 'sphp_digisign'
        self.document.save()
        mock_get_julo_digisign_client.return_value.sign_document.side_effect = JuloException()
        response = self.client.get('/api/v2/digisign/sign-document/123123123/')
        assert response.status_code == 400


class TestDigisignUserStatusViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.mobile_feature_setting1 = MobileFeatureSettingFactory()
        self.digisign_configuration = DigisignConfigurationFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.product_line = ProductLineFactory()
        self.app_version = AppVersionFactory()
        self.signature_method_history = SignatureMethodHistoryFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestDigisignUserStatusViewAPIv2_mobile_feature_setting_not_found(self):
        self.mobile_feature_setting.feature_name = 'test'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'test'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()
        response = self.client.get('/api/v2/digisign/user-status')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignUserStatusViewAPIv2_success_case_1(self, mock_get_julo_digisign_client):
        mock_user_status_response = {'JSONFile': {'result': '00', 'info': 'belum aktif'}}
        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()

        self.digisign_configuration.product_selection = 'MTL'
        self.digisign_configuration.is_active = True
        self.digisign_configuration.save()

        self.app_version.app_version = '3.12.0'
        self.app_version.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        mock_get_julo_digisign_client.return_value.user_status.return_value = (
            mock_user_status_response
        )
        response = self.client.get('/api/v2/digisign/user-status')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignUserStatusViewAPIv2_is_digisign_affected(
        self, mock_get_julo_digisign_client
    ):
        mock_user_status_response = {'JSONFile': {'result': '00', 'info': 'belum aktif'}}
        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()

        self.digisign_configuration.product_selection = 'test'
        self.digisign_configuration.is_active = True
        self.digisign_configuration.save()

        self.app_version.app_version = '3.10.0'
        self.app_version.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.app_version = '3.10.0'
        self.application.save()

        mock_get_julo_digisign_client.return_value.user_status.return_value = (
            mock_user_status_response
        )
        response = self.client.get('/api/v2/digisign/user-status')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignUserStatusViewAPIv2_digisign_user_status_failed_case_1(
        self, mock_get_julo_digisign_client
    ):
        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()

        self.digisign_configuration.product_selection = 'test'
        self.digisign_configuration.is_active = True
        self.digisign_configuration.save()

        self.app_version.app_version = '3.12.0'
        self.app_version.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        mock_get_julo_digisign_client.return_value.user_status.side_effect = JuloException()
        response = self.client.get('/api/v2/digisign/user-status')
        assert response.status_code == 400

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignUserStatusViewAPIv2_success_case_2(self, mock_get_julo_digisign_client):
        mock_user_status_response = {'JSONFile': {'result': '00', 'info': 'aktif'}}
        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()

        self.digisign_configuration.product_selection = 'MTL'
        self.digisign_configuration.is_active = True
        self.digisign_configuration.save()

        self.app_version.app_version = '3.12.0'
        self.app_version.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        mock_get_julo_digisign_client.return_value.user_status.return_value = (
            mock_user_status_response
        )
        response = self.client.get('/api/v2/digisign/user-status')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignUserStatusViewAPIv2_success_case_3(
        self, mock_get_julo_digisign_client, mock_process_application_status_change
    ):
        mock_user_status_response = {'JSONFile': {'result': '01', 'notif': 'test'}}
        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        self.digisign_configuration.product_selection = 'MTL'
        self.digisign_configuration.is_active = True
        self.digisign_configuration.save()

        self.app_version.app_version = '3.12.0'
        self.app_version.save()

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        self.signature_method_history.application = self.application
        self.signature_method_history.signature_method = 'Digisign'
        self.signature_method_history.is_used = False
        self.signature_method_history.save()

        mock_get_julo_digisign_client.return_value.user_status.return_value = (
            mock_user_status_response
        )
        response = self.client.get('/api/v2/digisign/user-status')
        assert response.status_code == 200


class TestDigisignUserActivationViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestDigisignUserActivationViewAPIv2_success(self):
        data = {'is_actived': True}
        response = self.client.put('/api/v2/digisign/user-activation', data=data)
        assert response.status_code == 200


class TestDigisignFailedActionViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @patch('juloserver.apiv2.views.signature_method_history_task')
    def test_TestDigisignFailedActionViewAPIv2_success(self, mock_signature_method_history_task):
        response = self.client.post('/api/v2/digisign/failed-action/')
        assert response.status_code == 200


class TestDigisignDocumentStatusViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, id=123123123)
        self.partner = PartnerFactory()
        self.product_line = ProductLineFactory()
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.mobile_feature_setting1 = MobileFeatureSettingFactory()
        self.document = DocumentFactory()
        self.signature_method_history = SignatureMethodHistoryFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestDigisignDocumentStatusViewAPIv2_application_not_found(self):
        response = self.client.get('/api/v2/digisign/document-status/1231231/')
        assert response.status_code == 400
        print((response.json())['error_message'] == 'application_id is required')

    def test_TestDigisignDocumentStatusViewAPIv2_partner_pede(self):
        self.partner.name = 'pede'
        self.partner.save()

        self.application.partner = self.partner
        self.application.save()

        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    def test_TestDigisignDocumentStatusViewAPIv2_feature_setting_not_found(self):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.save()

        self.mobile_feature_setting.feature_name = 'test'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'test'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()

        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.upload_sphp_from_digisign_task')
    def test_TestDigisignDocumentStatusViewAPIv2_feature_mobile_not_found(self, mock_task):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'test'
        self.mobile_feature_setting1.is_active = True
        self.mobile_feature_setting1.save()

        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.upload_sphp_from_digisign_task')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_is_digisign_version_true(
        self, mock_get_julo_digisign_client, mock_task
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_is_digisign_version_false(
        self, mock_get_julo_digisign_client
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.10.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_document_not_found(
        self, mock_get_julo_digisign_client
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.10.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        self.document.document_source = 123
        self.document.document_type = 'test'
        self.document.save()

        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_digisign_document_status_failed(
        self, mock_get_julo_digisign_client
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        self.document.document_source = 123123123
        self.document.document_type = 'sphp_digisign'
        self.document.save()

        mock_get_julo_digisign_client.return_value.document_status.side_effect = JuloException()
        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 400
        print((response.json())['error_message'] == 'Call api digisign user status failed')

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_success_case_1(
        self, mock_get_julo_digisign_client
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        self.document.document_source = 123123123
        self.document.document_type = 'sphp_digisign'
        self.document.save()

        mock_document_status_response = {'JSONFile': {'result': '00', 'status': 'waiting'}}

        self.signature_method_history.application = self.application
        self.signature_method_history.signature_method = 'Digisign'
        self.signature_method_history.is_used = False
        self.signature_method_history.save()

        mock_get_julo_digisign_client.return_value.document_status.return_value = (
            mock_document_status_response
        )
        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_success_case_2(
        self, mock_get_julo_digisign_client
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        self.document.document_source = 123123123
        self.document.document_type = 'sphp_digisign'
        self.document.save()

        mock_document_status_response = {'JSONFile': {'result': '00', 'status': 'complete'}}

        self.signature_method_history.application = self.application
        self.signature_method_history.signature_method = 'Digisign'
        self.signature_method_history.is_used = False
        self.signature_method_history.save()

        mock_get_julo_digisign_client.return_value.document_status.return_value = (
            mock_document_status_response
        )
        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.upload_sphp_from_digisign_task')
    @patch('juloserver.apiv2.views.get_julo_digisign_client')
    def test_TestDigisignDocumentStatusViewAPIv2_success_case_3(
        self, mock_get_julo_digisign_client, mock_task
    ):
        self.partner.name = 'test'
        self.partner.save()

        self.application.partner = self.partner
        self.application.product_line = self.product_line
        self.application.app_version = '3.12.0'
        self.application.save()

        self.mobile_feature_setting.feature_name = 'digisign_mode'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.save()

        self.mobile_feature_setting1.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting1.is_active = False
        self.mobile_feature_setting1.save()

        self.document.document_source = 123123123
        self.document.document_type = 'sphp_digisign'
        self.document.save()

        mock_document_status_response = {'JSONFile': {'result': '', 'status': ''}}

        self.signature_method_history.application = self.application
        self.signature_method_history.signature_method = 'Digisign'
        self.signature_method_history.is_used = False
        self.signature_method_history.save()

        mock_get_julo_digisign_client.return_value.document_status.return_value = (
            mock_document_status_response
        )
        response = self.client.get('/api/v2/digisign/document-status/123123123/')
        assert response.status_code == 200

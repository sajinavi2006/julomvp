from builtins import str
import mock
from rest_framework.test import APITestCase
from rest_framework.reverse import reverse
from rest_framework import status
from requests.models import Response
from juloserver.julo.tests.factories import PartnerFactory, AuthUserFactory, DocumentFactory, \
    MobileFeatureSettingFactory
from ..factories import LenderCurrentFactory, LenderBucketFactory


class TestLenderDocumentSign(APITestCase):

    def create_user(self):
        user = AuthUserFactory(username='test')
        self.client.force_authenticate(user)
        partner = PartnerFactory(user=user)
        return user, partner

    def test_unsign_applications_view(self):
        data = dict(application_xid=123456789)
        url = reverse('unsign')
        user, partner = self.create_user()
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_FTM_signed_document_view(self):
        data = dict(bucket_id=1, signature_method='test')
        url = reverse('signed_doc')
        user, partner = self.create_user()
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        lender_bucket = LenderBucketFactory(partner=partner)
        data['bucket_id'] = lender_bucket.id
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)

    def test_FTM_list_document_view(self):
        data = dict()
        url = reverse('list_document')
        user, partner = self.create_user()
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lender_bucket = LenderBucketFactory(partner=partner)
        data['last_bucket_id'] = lender_bucket.id
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def get_response_obj(self):
        the_response = Response()
        the_response.status_code = 200
        return the_response

    @mock.patch('requests.post')
    def test_FTM_sign_document_view(self, mocked_task):
        data = dict()
        document_factory = DocumentFactory(document_type="summary_lender_sphp")
        url = '/api/followthemoney/v1/digisign/sign-document/' + str(document_factory.document_source)
        user, partner = self.create_user()
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        LenderCurrentFactory(user=user)
        the_response = self.get_response_obj()
        the_response._content = u'{}'
        mocked_task.return_value = the_response
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, 200)

    @mock.patch('requests.post')
    def test_FTM_digisign_document_status_view(self, mocked_task):
        data = dict(bucket_id=1)
        url = '/api/followthemoney/v1/digisign/document-status/'
        user, partner = self.create_user()
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        MobileFeatureSettingFactory()
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        LenderCurrentFactory(user=user)
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data['bucket_id'] = 12345
        DocumentFactory(document_type="summary_lender_sphp")
        the_response = self.get_response_obj()
        the_response._content = u'{"JSONFile": {"result": "00", "status": "waiting"}}'
        mocked_task.return_value = the_response
        response = self.client.get(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

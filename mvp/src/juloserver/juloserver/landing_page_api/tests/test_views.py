from django.core.urlresolvers import reverse
from rest_framework.test import APIClient
from django.test import TestCase
from django.utils.translation import ugettext as _

from juloserver.landing_page_api.constants import FAQItemType
from juloserver.landing_page_api.models import LandingPageCareer
from juloserver.landing_page_api.tests.factories import FAQItemFactory, LandingPageCareerFactory, \
    LandingPageSectionFactory

from django.core.files.uploadedfile import SimpleUploadedFile

from unittest.mock import patch
from copy import deepcopy

class TestFAQItemViewSet(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.faq_item = FAQItemFactory(title='faq title')

    def test_get(self):
        response = self.client.get('/api/landing_page/faq/{}/'.format(self.faq_item.id))

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(self.faq_item.id, response.json()['data']['id'])

    def test_get_404(self):
        response = self.client.get('/api/landing_page/faq/{}/'.format('not-found'))

        self.assertEqual(404, response.status_code, response.content)
        self.assertEqual(_('Not found.'), response.json()['message'])

    def test_list_sections(self):
        section_faqs = FAQItemFactory.create_batch(size=5, type=FAQItemType.SECTION)
        FAQItemFactory.create_batch(size=2, type=FAQItemType.QUESTION)
        response = self.client.get('/api/landing_page/faq/', {'type': FAQItemType.SECTION})

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(len(section_faqs), response.json()['data']['count'])


    def test_list_question_by_parent(self):
        section_faqs = FAQItemFactory.create_batch(size=3, type=FAQItemType.SECTION)
        other_faqs = FAQItemFactory.create_batch(size=4, type=FAQItemType.QUESTION)

        expected_faqs = FAQItemFactory.create_batch(size=5, type=FAQItemType.QUESTION, parent=section_faqs[0])
        data = {
            'type': FAQItemType.QUESTION,
            'parent': section_faqs[0].id
        }
        response = self.client.get('/api/landing_page/faq/', data)

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(len(expected_faqs), response.json()['data']['count'])

    def test_list_search(self):
        FAQItemFactory.create_batch(size=3, type=FAQItemType.QUESTION)
        expected_faq = FAQItemFactory(title='search query random stuff')
        data = {
            'search': 'search query',
        }
        response = self.client.get('/api/landing_page/faq/', data)

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(1, response.json()['data']['count'])
        self.assertEqual(expected_faq.id, response.json()['data']['results'][0]['id'])


class TestLandingPageCareerViewSet(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_get_list(self):
        LandingPageCareerFactory.create_batch(size=10, is_active=True)
        LandingPageCareerFactory.create_batch(size=2, is_active=False)

        response = self.client.get('/api/landing_page/career/')

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(10, response.json()['data']['count'])
        self.assertNotContains(response, 'rich_text')
        for field in LandingPageCareer.extra_data_fields:
            self.assertContains(response, f'"{field}"')

    def test_get_list_with_filter(self):
        LandingPageCareerFactory.create_batch(size=10, category='test-category', is_active=True)
        LandingPageCareerFactory.create_batch(size=2, is_active=True)

        data = {
            'category': 'test-category',
        }
        response = self.client.get('/api/landing_page/career/', data)
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(10, response.json()['data']['count'])

    def test_get_list_with_search(self):
        LandingPageCareerFactory.create_batch(size=10, category='test-category', is_active=True)
        LandingPageCareerFactory.create_batch(size=2, is_active=True)

        data = {
            'search': 'test-category',
        }
        response = self.client.get('/api/landing_page/career/', data)
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(10, response.json()['data']['count'])

    def test_get_detail(self):
        career = LandingPageCareerFactory(**{
            'title': 'test-title',
            'category': 'test-category',
            'skills': ['test-skill1', 'test-skill2'],
            'is_active': True,
            'published_date': '2021-10-10 10:11:12',
            'rich_text': 'test-rich-text',
            'extra_data': {
                'type': 'test-type',
                'vacancy': 'test-vacancy',
                'experience': 'test-experience',
                'salary': 'test-salary',
                'location': 'test-location',
            }
        })

        response = self.client.get(f'/api/landing_page/career/{career.id}/')
        expected_keys = [
            'id', 'title', 'category', 'skills', 'published_date', 'is_active', 'rich_text', 'type',
            'vacancy', 'salary', 'experience', 'location', 'cdate', 'udate',
        ]

        self.assertEqual(200, response.status_code, response.content)
        for expected_key in expected_keys:
            self.assertIn(expected_key, response.json()['data'])


class TestLandingPageSectionViewSet(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_get_detail(self):
        section = LandingPageSectionFactory()
        response = self.client.get(f'/api/landing_page/section/{section.id}/')
        expected_keys = [
            'id', 'name', 'rich_text', 'cdate', 'udate',
        ]

        self.assertEqual(200, response.status_code, response.content)
        for expected_key in expected_keys:
            self.assertIn(expected_key, response.json()['data'])

    def test_get_list(self):
        LandingPageSectionFactory.create_batch(10)
        response = self.client.get('/api/landing_page/section/')
        expected_keys = [
            'id', 'name', 'rich_text', 'cdate', 'udate',
        ]

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(10, response.json()['data']['count'])
        for expected_key in expected_keys:
            self.assertIn(expected_key, response.json()['data']['results'][0])

    def test_get_list_filter_in(self):
        LandingPageSectionFactory.create_batch(10)
        LandingPageSectionFactory(name='name-1')
        LandingPageSectionFactory(name='name-2')

        data = {
            'name__in': 'name-1,name-2'
        }
        response = self.client.get('/api/landing_page/section/', data)

        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(2, response.json()['data']['count'])
        self.assertContains(response, 'name-1')
        self.assertContains(response, 'name-2')


class TestDeleteAccountRequestViewSet(TestCase):

    png_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x08\xd7c`\x00\x00\x00\x02\x00\x01\x05\x00\x00\x00\x00IEND\xaeB`\x82'

    data_happy_path = {
        "full_name": "Nama Lengkap",
        "nik": "3173020311990001",
        "phone_number": "+62877784855",
        "email_address": "marcellus@c3llus.dev",
        "reason": "lainnya",
        "details": "kwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkw",
        "image_ktp": SimpleUploadedFile(content=png_content, name="test.png", content_type="image/png"),
        "image_selfie": SimpleUploadedFile(content=png_content, name="test.png", content_type="image/png"),
    }

    def setUp(self):
        self.client = APIClient()

    @patch('juloserver.landing_page_api.views.upload_file_as_bytes_to_oss')
    @patch('juloserver.landing_page_api.views.handle_web_account_deletion_request.apply_async')
    def test_create_request_success(
        self,
        mock_upload_file_as_bytes_to_oss,
        mock_handle_web_account_deletion_request,
    ):
        mock_upload_file_as_bytes_to_oss.return_value = None
        mock_handle_web_account_deletion_request.return_value = None

        with patch('juloserver.landing_page_api.views.DeleteAccountRequestSerializer.is_valid', return_value=True):
            response = self.client.post("/api/landing_page/delete_account_request/", data=self.data_happy_path, format='multipart')
            self.assertEqual(200, response.status_code, response.content)

    def test_create_request_bad_request(self):
        data_bad_request = deepcopy(self.data_happy_path)
        data_bad_request['phone_number'] = '1234567890123456'

        response = self.client.post("/api/landing_page/delete_account_request/", data=data_bad_request, format='multipart')
        self.assertEqual(400, response.status_code, response.content)

    @patch('juloserver.landing_page_api.views.upload_file_as_bytes_to_oss')
    def test_create_request_internal_server_error(
        self,
        mock_upload_file_as_bytes_to_oss,
    ):
        mock_upload_file_as_bytes_to_oss.side_effect = Exception('test exception')

        response = self.client.post("/api/landing_page/delete_account_request/", data=self.data_happy_path, format='multipart')
        self.assertEqual(500, response.status_code, response.content)

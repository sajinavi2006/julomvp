
from copy import deepcopy
from django.test import TestCase
from juloserver.landing_page_api.constants import FAQItemType
from juloserver.landing_page_api.serializers import FAQItemSerializer, DeleteAccountRequestSerializer 
from juloserver.landing_page_api.tests.factories import FAQItemFactory

from django.core.files.uploadedfile import SimpleUploadedFile

class TestFAQItemSerializer(TestCase):
    def test_serialized(self):
        data = {
            'title': 'this is title',
            'slug': 'this-is-title',
            'rich_text': 'rich text',
            'visible': True,
            'type': FAQItemType.QUESTION,
            'order_priority': 1,
        }
        faq = FAQItemFactory(**data)

        serializer = FAQItemSerializer(faq)

        expected_data = deepcopy(data)
        expected_data.update({'id': faq.id, 'parent': None})
        self.assertEqual(expected_data, serializer.data)

    def test_serialized_with_parent(self):
        parent_faq = FAQItemFactory(title='parent title', type=FAQItemType.SECTION)
        data = {
            'title': 'this is title',
            'slug': 'this-is-title',
            'rich_text': 'rich text',
            'visible': True,
            'type': FAQItemType.QUESTION,
            'order_priority': 1,
            'parent': parent_faq
        }
        faq = FAQItemFactory(**data)

        serializer = FAQItemSerializer(faq)

        expected_data = deepcopy(data)
        expected_data.update({
            'id': faq.id,
            'parent': {
                'id': parent_faq.id,
                'title': parent_faq.title,
                'type': parent_faq.type
            }
        })
        self.assertEqual(expected_data, serializer.data)

class TestDeleteAccountRequestSerializer(TestCase):
    data_happy_path = {
        "full_name": "Nama Lengkap",
        "nik": "3173020311990001",
        "phone_number": "+62877784855",
        "email_address": "marcellus@c3llus.dev",
        "reason": "lainnya",
        "details": "kwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkwkw",
        "image_ktp": SimpleUploadedFile("ktp.png", b"file_content"),
        "image_selfie": SimpleUploadedFile("selfie.png",b"selfie_file_data"),
    }

    def test_happy_path(self):  
        serializer = DeleteAccountRequestSerializer(data=self.data_happy_path)
        self.assertTrue(serializer.is_valid())

    def test_invalid_nik(self):
        data_invalid_nik = deepcopy(self.data_happy_path)
        data_invalid_nik['nik'] = '123456789012345'

        serializer = DeleteAccountRequestSerializer(data=data_invalid_nik)
        self.assertFalse(serializer.is_valid())

    def test_invalid_phone_number(self):
        data_invalid_phone_number = deepcopy(self.data_happy_path)
        data_invalid_phone_number['phone_number'] = '1234567890123456'

        serializer = DeleteAccountRequestSerializer(data=data_invalid_phone_number)
        self.assertFalse(serializer.is_valid())

    def test_invalid_email_address(self):
        data_invalid_email_address = deepcopy(self.data_happy_path)
        data_invalid_email_address['email_address'] = 'john'

        serializer = DeleteAccountRequestSerializer(data=data_invalid_email_address)
        self.assertFalse(serializer.is_valid())
    
    def test_invalid_reason(self):
        data_invalid_reason = deepcopy(self.data_happy_path)
        data_invalid_reason['reason'] = 'lain'

        serializer = DeleteAccountRequestSerializer(data=data_invalid_reason)
        self.assertFalse(serializer.is_valid())
    
    def test_invalid_details(self):
        data_invalid_details = deepcopy(self.data_happy_path)
        data_invalid_details['details'] = 'fourteenchars'

        serializer = DeleteAccountRequestSerializer(data=data_invalid_details)
        self.assertFalse(serializer.is_valid())
    
    def test_invalid_attachment_type(self):
        data_invalid_attachment_type = deepcopy(self.data_happy_path)
        data_invalid_attachment_type['image_ktp'] = SimpleUploadedFile("selfie.txt",b'selfie_file_data')

        serializer = DeleteAccountRequestSerializer(data=data_invalid_attachment_type)
        self.assertFalse(serializer.is_valid())

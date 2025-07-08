import mock
import ulid
import base64
import io

from datetime import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase

from juloserver.partnership.liveness_partnership.constants import LivenessType
from juloserver.partnership.liveness_partnership.utils import generate_api_key
from juloserver.partnership.liveness_partnership.tests.factories import LivenessConfigurationFactory
from juloserver.partnership.liveness_partnership.services import (
    process_smile_liveness,
    process_passive_liveness,
)

from PIL import Image


@override_settings(
    PARTNERSHIP_LIVENESS_ENCRYPTION_KEY='AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE='
)
class TestServicePartnershipLiveness(TestCase):
    def setUp(self) -> None:
        client_id = ulid.new()
        self.liveness_configuration = LivenessConfigurationFactory(
            client_id=client_id.uuid,
            partner_id=1,
            detection_types={
                LivenessType.PASSIVE: True,
                LivenessType.SMILE: True,
            },
            platform='web',
            is_active=True,
        )
        self.liveness_configuration.cdate = datetime(2022, 11, 29, 4, 15, 0)
        # generate API Key
        cdate_timestamp = int(self.liveness_configuration.cdate.timestamp())
        data = "{}:{}".format(cdate_timestamp, self.liveness_configuration.client_id)
        api_key = generate_api_key(data)
        self.liveness_configuration.api_key = api_key
        self.liveness_configuration.whitelisted_domain = ['example.com']
        self.liveness_configuration.save()

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        Image.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.delete_customer_innovatrics'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.evaluate_smile'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.submit_neutral_image'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.submit_smile_image'
    )
    @mock.patch('juloserver.partnership.liveness_partnership.services.upload_liveness_image')
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.create_customer_liveness'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.create_customer_innovatrics'
    )
    def test_success_partnersip_smile_liveness(
        self,
        mock_create_customer,
        mock_create_customer_liveness,
        mock_upload_liveness_image,
        mock_submit_smile_image,
        mock_submit_neutral_image,
        mock_evaluate_smile,
        mock_delete_customer,
    ):
        image_1 = self.create_image()
        smile_file = SimpleUploadedFile('smile.jpeg', image_1.getvalue())
        image_2 = self.create_image()
        neutral_file = SimpleUploadedFile('smile.jpeg', image_2.getvalue())

        mock_create_customer.return_value = {
            'id': 'eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
            'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f'},
        }, 0

        mock_create_customer_liveness.return_value = {}, 0

        base64_image = base64.b64encode(image_1.read()).decode('utf-8')
        mock_upload_liveness_image.return_value = {
            'liveness_image': '1',
            'image_name': 'smile.jpeg',
            'image_url': 'https://www.test.co.id/ic-smile.jpeg',
            'base64_image': base64_image,
        }, True

        mock_submit_smile_image.return_value = {}, 0
        mock_submit_neutral_image.return_value = {}, 0
        mock_evaluate_smile.return_value = {'score': 1.0}, 0
        mock_delete_customer.return_value = {}, 0

        liveness_result, is_success = process_smile_liveness(
            self.liveness_configuration,
            neutral_file,
            smile_file,
        )
        self.assertEqual(liveness_result.status, 'success')
        self.assertEqual(is_success, True)
        self.assertEqual(mock_upload_liveness_image.call_count, 2)

    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.delete_customer_innovatrics'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.evaluate_passive'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.submit_passive_image'
    )
    @mock.patch('juloserver.partnership.liveness_partnership.services.upload_liveness_image')
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.create_customer_liveness'
    )
    @mock.patch(
        'juloserver.partnership.liveness_partnership.services.PartnershipDotDigitalIdentityClient.create_customer_innovatrics'
    )
    def test_success_partnersip_passive_liveness(
        self,
        mock_create_customer,
        mock_create_customer_liveness,
        mock_upload_liveness_image,
        mock_submit_passive_image,
        mock_evaluate_passive,
        mock_delete_customer,
    ):
        image_1 = self.create_image()
        neutral_file = SimpleUploadedFile('smile.jpeg', image_1.getvalue())

        mock_create_customer.return_value = {
            'id': 'eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
            'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f'},
        }, 0

        mock_create_customer_liveness.return_value = {}, 0

        base64_image = base64.b64encode(image_1.read()).decode('utf-8')
        mock_upload_liveness_image.return_value = {
            'liveness_image': '1',
            'image_name': 'smile.jpeg',
            'image_url': 'https://www.test.co.id/ic-smile.jpeg',
            'base64_image': base64_image,
        }, True

        mock_submit_passive_image.return_value = {}, 0
        mock_evaluate_passive.return_value = {'score': 0.5}, 0
        mock_delete_customer.return_value = {}, 0

        liveness_result, is_success = process_passive_liveness(
            self.liveness_configuration,
            neutral_file,
        )
        self.assertEqual(liveness_result.status, 'success')
        self.assertEqual(is_success, True)
        self.assertEqual(mock_upload_liveness_image.call_count, 1)

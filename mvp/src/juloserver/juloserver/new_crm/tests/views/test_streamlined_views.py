import io
from collections import OrderedDict
from symbol import parameters
from unittest import mock

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import StreamingHttpResponse
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
)
from rest_framework.test import APITestCase, APIClient

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationJ1Factory,
    FeatureSettingFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.standardized_api_response.utils import HTTP_425_TOO_EARLY
from juloserver.streamlined_communication.constant import CommsUserSegmentConstants
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationSegmentFactory,
    CommsUserSegmentChunkFactory,
)


class TestStreamlinedCommsImportUsersUploadFileView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.PRODUCT_MANAGER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.application1 = ApplicationJ1Factory()
        self.application2 = ApplicationJ1Factory()
        self.application3 = ApplicationJ1Factory()
        self.application4 = ApplicationJ1Factory()
        self.application5 = ApplicationJ1Factory()
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory()
        self.feature_setting_integrity_ttl = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL,
            parameters={"TTL": "1800"},
        )
        self.feature_setting_chunk_size = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_SIZE,
            parameters={"chunk_size": "2"},
        )

    @mock.patch('juloserver.new_crm.tasks.split_file_into_chunks_async.delay')
    def test_streamlined_comms_import_users_upload_file_view(
        self, mock_split_file_into_chunks_async
    ):
        url = '/new_crm/v1/streamlined/upload_user_data'
        csv_data = f"""account_id
                    {self.application1.account_id}
                    {self.application2.account_id}
                    {self.application3.account_id}
                    {self.application4.account_id}
                    {self.application5.account_id}
                    """
        data = bytes(csv_data, 'utf-8')
        csv_file = io.BytesIO(data)
        file = InMemoryUploadedFile(
            file=csv_file,
            field_name='',
            name='test_file.csv',
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        ordered_data = OrderedDict(
            [
                ('file_data_type', 'account_id'),
                ('customer_segment_name', 'test_seg_account'),
                ('csv_file', (file)),
            ]
        )
        request_data = {
            "csv_file": file,
            "file_data_type": 'account_id',
            "customer_segment_name": "test_seg_account",
        }
        mock_split_file_into_chunks_async.return_value = self.user_segment_obj
        expected_response = {
            'success': True,
            'data': {'user_segment_id': self.user_segment_obj.id},
            'errors': [],
        }
        response = self.client.post(url, data=request_data)
        mock_split_file_into_chunks_async.assert_called()
        self.assertEqual(response.json(), expected_response)

    @mock.patch('juloserver.new_crm.tasks.split_file_into_chunks_async.delay')
    def test_validate_csv_file_type_mismatch(self, mock_split_file_into_chunks_async):
        url = '/new_crm/v1/streamlined/upload_user_data'
        csv_data = f"""application_id
                    {self.application1.account_id}
                    {self.application2.account_id}
                    {self.application3.account_id}
                    {self.application4.account_id}
                    {self.application5.account_id}
                    """
        data = bytes(csv_data, 'utf-8')
        csv_file = io.BytesIO(data)
        file = InMemoryUploadedFile(
            file=csv_file,
            field_name='',
            name='test_file.csv',
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        OrderedDict(
            [
                ('file_data_type', 'account_id'),
                ('customer_segment_name', 'test_seg_account'),
                ('csv_file', (file)),
            ]
        )
        request_data = {
            "csv_file": file,
            "file_data_type": 'account_id',
            "customer_segment_name": "test_seg_account",
        }
        response = self.client.post(url, data=request_data)
        self.assertEqual(response.json()['errors'][0], "File type mismatch")
        mock_split_file_into_chunks_async.assert_not_called()


class TestStreamlinedCommsSegmentProcessStatus(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.PRODUCT_MANAGER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory()
        self.comms_segment_chunk1 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.comms_segment_chunk2 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.comms_segment_chunk3 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.comms_segment_chunk4 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )

    @mock.patch('juloserver.new_crm.views.streamlined_views.get_redis_client')
    def test_streamlined_comms_segment_process_status_425_all_unfinished_status(
        self, mocked_client
    ):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.return_value = [
            b'0235727112998040',
            b'0235727',
            b'0235727',
            b'0235727',
        ]
        mocked_client.return_value = mocked_redis_client
        response = self.client.get(
            '/new_crm/v1/streamlined/track_process_status/{}'.format(self.user_segment_obj.id)
        )
        self.assertEqual(response.status_code, HTTP_425_TOO_EARLY)
        self.assertEqual(
            response.json()['errors'][0]['message'], "Some chunks are still in progress"
        )

    @mock.patch('juloserver.new_crm.views.streamlined_views.get_redis_client')
    def test_streamlined_comms_segment_process_status_425_for_2_finished_status(
        self, mocked_client
    ):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.return_value = [b'0235727112998040', b'0235727']
        mocked_client.return_value = mocked_redis_client
        self.comms_segment_chunk4.process_status = CommsUserSegmentConstants.ChunkStatus.FINISH
        self.comms_segment_chunk4.save()
        self.comms_segment_chunk3.process_status = CommsUserSegmentConstants.ChunkStatus.FINISH
        self.comms_segment_chunk3.save()

        response = self.client.get(
            '/new_crm/v1/streamlined/track_process_status/{}'.format(self.user_segment_obj.id)
        )
        self.assertEqual(response.status_code, HTTP_425_TOO_EARLY)
        self.assertEqual(
            response.json()['errors'][0]['message'], "Some chunks are still in progress"
        )

    @mock.patch('juloserver.new_crm.views.streamlined_views.get_redis_client')
    def test_streamlined_comms_segment_process_status_200_for_all_finished_status(
        self, mocked_client
    ):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.return_value = []
        mocked_client.return_value = mocked_redis_client
        self.comms_segment_chunk4.process_status = CommsUserSegmentConstants.ChunkStatus.FINISH
        self.comms_segment_chunk3.process_status = CommsUserSegmentConstants.ChunkStatus.FINISH
        self.comms_segment_chunk2.process_status = CommsUserSegmentConstants.ChunkStatus.FINISH
        self.comms_segment_chunk1.process_status = CommsUserSegmentConstants.ChunkStatus.FINISH
        self.comms_segment_chunk1.save()
        self.comms_segment_chunk2.save()
        self.comms_segment_chunk3.save()
        self.comms_segment_chunk4.save()
        response = self.client.get(
            '/new_crm/v1/streamlined/track_process_status/{}'.format(self.user_segment_obj.id)
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.json()['data']['message'], "All chunks are finished")


class TestStreamlinedCommsSegmentAction(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.PRODUCT_MANAGER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory()
        self.application1 = ApplicationJ1Factory()
        self.application2 = ApplicationJ1Factory()

        self.comms_segment_chunk1 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.comms_segment_chunk2 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )

    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    def test_streamlined_comms_segment_action(self, mock_get_downloadable_response):
        self.application1.mobile_phone_1 = '0866340695459'
        self.application2.mobile_phone_1 = '0866340695459'
        self.application1.save()
        self.application2.save()
        chunk_csv_data1 = f"""account_id
        {self.application1.account_id}\n"""
        chunk_csv_data2 = f"""account_id
        {self.application2.account_id}"""
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )
        mock_get_downloadable_response.return_value = [response1, response2]

        request_data = {"action": "download"}
        response = self.client.get(
            '/new_crm/v1/streamlined/segment_data_action/{}'.format(self.user_segment_obj.id),
            data=request_data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')

        response_content = response.content.decode('utf-8')

        expected_csv_data = f"""account_id
        {self.application1.account_id}
        {self.application2.account_id}"""
        normalized_response_content = response_content.replace('\r\n', '\n').strip()
        normalized_expected_content = expected_csv_data.replace('\r\n', '\n').strip()
        self.assertEqual(normalized_response_content, normalized_expected_content)


class TestStreamlinedCommsSegmentErrorDetails(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.PRODUCT_MANAGER)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory()

    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.validate_csv_file'
    )
    def test_streamlined_comms_segment_error_details(self, mock_validate_csv_file):
        mock_validate_csv_file.return_value = (
            'The file contains data, that is not found in the DB',
            [['23456880'], ['819273863']],
            5,
        )
        self.user_segment_obj.status = CommsUserSegmentConstants.SegmentStatus.FAILED
        self.user_segment_obj.error_list = [
            'The file contains data, that is not found in the DB',
            '23456880',
            '819273863',
        ]
        self.user_segment_obj.save()
        response = self.client.get(
            '/new_crm/v1/streamlined/segment_error_details/{}'.format(self.user_segment_obj.id)
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.json()['data']['error_list'], self.user_segment_obj.error_list)

    def test_streamlined_comms_segment_error_details_for_no_error_list(self):
        self.user_segment_obj.status = CommsUserSegmentConstants.SegmentStatus.FAILED
        self.user_segment_obj.save()
        response = self.client.get(
            '/new_crm/v1/streamlined/segment_error_details/{}'.format(self.user_segment_obj.id)
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], "Error list is empty")

    def test_streamlined_comms_segment_error_details_if_segment_status_is_not_failed(self):
        response = self.client.get(
            '/new_crm/v1/streamlined/segment_error_details/{}'.format(self.user_segment_obj.id)
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0], "UserSegment status is not Failed")

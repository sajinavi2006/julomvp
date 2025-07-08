import io
import math
import os
from collections import OrderedDict
from unittest import mock

import pandas as pd
from django.test import TestCase

from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.status import HTTP_400_BAD_REQUEST

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    FeatureSettingFactory,
    AuthUserFactory,
)
from juloserver.new_crm.tasks import split_file_into_chunks_async, validate_and_upload_chunked_file
from juloserver.streamlined_communication.constant import CommsUserSegmentConstants
from juloserver.streamlined_communication.models import (
    StreamlinedCommunicationSegment,
    CommsUserSegmentChunk,
)
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationSegmentFactory,
)


class TestSplitFileIntoChunksAsync(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.application1 = ApplicationJ1Factory()
        self.application2 = ApplicationJ1Factory()
        self.application3 = ApplicationJ1Factory()
        self.application4 = ApplicationJ1Factory()
        self.application5 = ApplicationJ1Factory()
        self.feature_setting_integrity_ttl = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL,
            parameters={"TTL": "1800"},
        )

    @mock.patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    @mock.patch('juloserver.new_crm.tasks.validate_and_upload_chunked_file.delay')
    def test_split_file_into_chunks_async(
        self, mock_validate_and_upload_chunked_file, mock_upload_import_user_file_data_to_oss
    ):
        csv_data = f"""account_id
                    {self.application1.account_id}
                    {self.application2.account_id}
                    {self.application3.account_id}
                    {self.application4.account_id}
                    {self.application5.account_id}
                    """
        data = bytes(csv_data, 'utf-8')
        csv_file = io.BytesIO(data)
        file, _ = (
            InMemoryUploadedFile(
                file=csv_file,
                field_name='',
                name='test_file.csv',
                content_type='text/csv',
                size=len(data),
                content_type_extra=None,
                charset=None,
            ),
            None,
        )
        ordered_data = OrderedDict(
            [
                ('file_data_type', 'account_id'),
                ('customer_segment_name', ['test_seg_account', None]),
                ('csv_file', (file)),
            ]
        )
        rows_per_chunk = 2
        output_file_prefix = os.path.splitext(file.name)[0]
        df = pd.read_csv(csv_file).drop_duplicates()
        num_chunks = math.ceil(len(df) / int(rows_per_chunk))
        segment_obj = StreamlinedCommunicationSegment.objects.create(
            segment_name="test_seg_account",
            csv_file_type="account_id",
            chunk_count=num_chunks,
            csv_file_name=file.name,
            status=CommsUserSegmentConstants.SegmentStatus.PROCESSING,
        )
        segment_obj = split_file_into_chunks_async(
            output_file_prefix, segment_obj, df, 'account_id', num_chunks, rows_per_chunk=2
        )
        self.assertIsInstance(segment_obj, StreamlinedCommunicationSegment)
        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_validate_and_upload_chunked_file.assert_called()
        self.assertEqual(mock_validate_and_upload_chunked_file.call_count, 3)
        segment_obj = StreamlinedCommunicationSegment.objects.filter(
            segment_name='test_seg_account'
        ).last()
        self.assertIsNotNone(segment_obj)


class TestValidateAndUploadChunkedFile(TestCase):
    def setUp(self):
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory()
        self.application1 = ApplicationJ1Factory()
        self.application2 = ApplicationJ1Factory()
        self.application3 = ApplicationJ1Factory()
        self.application4 = ApplicationJ1Factory()
        self.application5 = ApplicationJ1Factory()

    @mock.patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_validate_and_upload_chunked_file(self, mock_upload_import_user_file_data_to_oss):
        csv_data = f"""account_id
                    {self.application1.account_id}
                    {self.application2.account_id}
                    {self.application3.account_id}
                    {self.application4.account_id}
                    {self.application5.account_id}
                    """
        data = bytes(csv_data, 'utf-8')
        csv_file = io.BytesIO(data)
        file, _ = (
            InMemoryUploadedFile(
                file=csv_file,
                field_name='',
                name='test_file.csv',
                content_type='text/csv',
                size=len(data),
                content_type_extra=None,
                charset=None,
            ),
            None,
        )
        ordered_data = OrderedDict(
            [
                ('file_data_type', self.user_segment_obj.csv_file_type),
                ('customer_segment_name', [self.user_segment_obj.segment_name, None]),
                ('csv_file', (file)),
            ]
        )
        output_file_prefix = 'test_seg_account' + '_' + file.name
        mock_upload_import_user_file_data_to_oss.return_value = None

        rows_per_chunk = 2
        df = pd.read_csv(file)
        num_chunks = (len(df) // rows_per_chunk) + 1
        for i in range(num_chunks):
            start_row = i * rows_per_chunk
            end_row = start_row + rows_per_chunk
            chunk_df = df.iloc[start_row:end_row]

            chunk_buffer = io.StringIO()
            chunk_df.to_csv(chunk_buffer, index=False)
            chunk_buffer.seek(0)

            chunk_file_name = f"{output_file_prefix}_chunk_{i + 1}.csv"

            comms_chunk = CommsUserSegmentChunk(
                chunk_csv_file_name=chunk_file_name,
                chunk_number=i + 1,
                streamlined_communication_segment=self.user_segment_obj,
            )
            comms_chunk.save()
            validate_and_upload_chunked_file(
                chunked_file=chunk_buffer,
                file_data_type=self.user_segment_obj.csv_file_type,
                chunk_file_name=chunk_file_name,
                segment=self.user_segment_obj,
            )
        comms_user_segment_chunk = CommsUserSegmentChunk.objects.filter(
            streamlined_communication_segment=self.user_segment_obj
        )
        # As given rows_per_chunk is 2, we expect the data to be split into 3 chunks.
        self.assertEqual(comms_user_segment_chunk.count(), 3)

    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.validate_csv_file'
    )
    @mock.patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_validate_and_upload_chunked_file_with_missing_values(
        self, mock_upload_import_user_file_data_to_oss, mock_validate_csv_file
    ):
        mock_validate_csv_file.return_value = (
            'The file contains data, that is not found in the DB',
            [
                self.application1.account_id,
                self.application2.account_id,
            ],
            5,
        )
        csv_data = f"""account_id
                       {self.application1.account_id}
                       {self.application2.account_id}
                       {self.application3.account_id}
                       {self.application4.account_id}
                       {self.application5.account_id}
                       """
        data = bytes(csv_data, 'utf-8')
        csv_file = io.BytesIO(data)
        file, _ = (
            InMemoryUploadedFile(
                file=csv_file,
                field_name='',
                name='test_file.csv',
                content_type='text/csv',
                size=len(data),
                content_type_extra=None,
                charset=None,
            ),
            None,
        )
        ordered_data = OrderedDict(
            [
                ('file_data_type', self.user_segment_obj.csv_file_type),
                ('customer_segment_name', [self.user_segment_obj.segment_name, None]),
                ('csv_file', (file)),
            ]
        )
        output_file_prefix = 'test_seg_account' + '_' + file.name
        mock_upload_import_user_file_data_to_oss.return_value = None

        rows_per_chunk = 2
        df = pd.read_csv(file)
        num_chunks = (len(df) // rows_per_chunk) + 1
        for i in range(num_chunks):
            start_row = i * rows_per_chunk
            end_row = start_row + rows_per_chunk
            chunk_df = df.iloc[start_row:end_row]

            chunk_buffer = io.StringIO()
            chunk_df.to_csv(chunk_buffer, index=False)
            chunk_buffer.seek(0)

            chunk_file_name = f"{output_file_prefix}_chunk_{i + 1}.csv"

            comms_chunk = CommsUserSegmentChunk(
                chunk_csv_file_name=chunk_file_name,
                chunk_number=i + 1,
            )
            comms_chunk.save()
            response = validate_and_upload_chunked_file(
                chunked_file=chunk_buffer,
                file_data_type=self.user_segment_obj.csv_file_type,
                chunk_file_name=chunk_file_name,
                segment=self.user_segment_obj,
            )

            self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

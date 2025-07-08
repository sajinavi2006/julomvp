import io
import math
import os

from unittest.mock import patch

import pandas as pd
from django.core.files.uploadedfile import InMemoryUploadedFile


from django.test import TestCase
from oauthlib.uri_validate import segment, segment_nz

from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
)
from juloserver.new_crm.services import streamlined_services
from collections import OrderedDict

from juloserver.streamlined_communication.models import (
    StreamlinedCommunicationSegment,
    CommsUserSegmentChunk,
)


class TestStreamlinedCommsImportUsersUploadFileServices(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.application1 = ApplicationJ1Factory()
        self.application2 = ApplicationJ1Factory()
        self.application3 = ApplicationJ1Factory()
        self.application4 = ApplicationJ1Factory()
        self.application5 = ApplicationJ1Factory()
        self.application6 = ApplicationJ1Factory()
        self.application7 = ApplicationJ1Factory()

    def test_validate_csv_file(self):
        csv_data = f"""account_id
                    {self.application.account_id}
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
        OrderedDict(
            [
                ('file_data_type', 'account_id'),
                ('customer_segment_name', ('test_seg_account', None)),
                ('csv_file', (file)),
            ]
        )
        rows_per_chunk = 10
        output_file_prefix = 'test_seg_account' + '_' + file.name
        df = pd.read_csv(csv_file)
        num_chunks = math.ceil(len(df) / int(rows_per_chunk))
        segment_obj = StreamlinedCommunicationSegment.objects.create(
            segment_name="test_seg_account",
            csv_file_type="account_id",
        )
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
            import_user_client = streamlined_services.StreamlinedImportUserClient(
                validated_data=chunk_buffer,
                file_data_type='account_id',
                segment_name='test_seg_account',
                chunk_file_name=chunk_file_name,
            )
            error, missing_values, row_count = import_user_client.validate_csv_file()
            self.assertEqual(error, None)
            self.assertEqual(missing_values, None)

    def test_validate_csv_file_data_not_found(self):
        csv_data = """account_id
                    8
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
                ('customer_segment_name', ('test_seg_account', None)),
                ('csv_file', (file)),
            ]
        )
        rows_per_chunk = 10
        output_file_prefix = 'test_seg_account' + '_' + file.name
        df = pd.read_csv(csv_file)
        num_chunks = math.ceil(len(df) / int(rows_per_chunk))
        StreamlinedCommunicationSegment.objects.create(
            segment_name="test_seg_account",
            csv_file_type="account_id",
        )
        for i in range(num_chunks):
            start_row = i * rows_per_chunk
            end_row = start_row + rows_per_chunk
            chunk_df = df.iloc[start_row:end_row]

            chunk_buffer = io.StringIO()
            chunk_df.to_csv(chunk_buffer, index=False)
            chunk_buffer.seek(0)

            chunk_file_name = f"{output_file_prefix}_chunk_{i + 1}.csv"

            CommsUserSegmentChunk(
                chunk_csv_file_name=chunk_file_name,
                chunk_number=i + 1,
            )
            import_user_client = streamlined_services.StreamlinedImportUserClient(
                validated_data=chunk_buffer,
                file_data_type='account_id',
                segment_name='test_seg_account',
                chunk_file_name=chunk_file_name,
            )
            error, missing_values, row_count = import_user_client.validate_csv_file()
            self.assertNotEqual(error, None)
            self.assertNotEqual(missing_values, None)

    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_record_segment_and_upload_file(self, mock_upload_import_user_file_data_to_oss):
        csv_data = f"""account_id
                    {self.application.account_id}
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
                ('customer_segment_name', ('test_seg_account', None)),
                ('csv_file', (file)),
            ]
        )
        rows_per_chunk = 10
        output_file_prefix = os.path.splitext(file.name)[0]
        df = pd.read_csv(csv_file)
        num_chunks = math.ceil(len(df) / int(rows_per_chunk))
        StreamlinedCommunicationSegment.objects.create(
            segment_name="test_seg_account", csv_file_type="account_id", csv_file_name=file.name
        )
        for i in range(num_chunks):
            start_row = i * rows_per_chunk
            end_row = start_row + rows_per_chunk
            chunk_df = df.iloc[start_row:end_row]

            chunk_buffer = io.StringIO()
            chunk_df.to_csv(chunk_buffer, index=False)
            chunk_buffer.seek(0)

            chunk_file_name = f"{output_file_prefix}_chunk_{i + 1}.csv"

            CommsUserSegmentChunk(
                chunk_csv_file_name=chunk_file_name,
                chunk_number=i + 1,
            )
            import_user_client = streamlined_services.StreamlinedImportUserClient(
                validated_data=chunk_buffer,
                file_data_type='account_id',
                segment_name='test_seg_account',
                chunk_file_name=chunk_file_name,
            )
            error, missing_values, row_count = import_user_client.validate_csv_file()
            mock_upload_import_user_file_data_to_oss.return_value = None
            data = import_user_client.record_segment_and_upload_file(
                1, "account_id", chunk_file_name
            )
            self.assertNotEqual(data, None)

    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_record_segment_and_upload_file_for_segment_count_update(
        self, mock_upload_import_user_file_data_to_oss
    ):
        csv_data = f"""account_id
                       {self.application.account_id}
                       {self.application1.account_id}
                       {self.application2.account_id}
                       {self.application3.account_id}
                       {self.application4.account_id}
                       {self.application5.account_id}
                       {self.application6.account_id}
                       {self.application7.account_id}
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
                ('customer_segment_name', 'test_seg_account'),
                ('csv_file', (file)),
            ]
        )
        rows_per_chunk = 2
        output_file_prefix = os.path.splitext(file.name)[0]
        df = pd.read_csv(csv_file)
        num_chunks = math.ceil(len(df) / int(rows_per_chunk))
        segment_obj = StreamlinedCommunicationSegment.objects.create(
            segment_name="test_seg_account",
            csv_file_type="account_id",
            chunk_count=num_chunks,
            csv_file_name=file.name,
        )
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
                streamlined_communication_segment=segment_obj,
            )
            comms_chunk.save()
            import_user_client = streamlined_services.StreamlinedImportUserClient(
                validated_data=chunk_buffer,
                file_data_type='account_id',
                segment_name='test_seg_account',
                chunk_file_name=chunk_file_name,
            )
            error, missing_values, row_count = import_user_client.validate_csv_file()
            mock_upload_import_user_file_data_to_oss.return_value = None
            data = import_user_client.record_segment_and_upload_file(
                row_count, "account_id", chunk_file_name
            )
            self.assertNotEqual(data, None)

        segment_obj.refresh_from_db()
        self.assertEqual(
            CommsUserSegmentChunk.objects.filter(
                streamlined_communication_segment=segment_obj
            ).count(),
            4,
        )
        self.assertEqual(segment_obj.segment_count, len(df))

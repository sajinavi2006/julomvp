import logging
import csv
import base64
import pandas as pd

from io import StringIO
from django.conf import settings
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Coalesce
from django.http.response import StreamingHttpResponse

from juloserver.julo.models import Application, Customer
from juloserver.account.models import Account
from juloserver.streamlined_communication.constant import CommsUserSegmentConstants
from juloserver.streamlined_communication.models import (
    StreamlinedCommunicationSegment,
    CommsUserSegmentChunk,
)
from juloserver.julo.utils import (
    upload_file_as_bytes_to_oss,
    get_file_from_oss,
    delete_public_file_from_oss,
    format_mobile_phone,
    add_plus_62_mobile_phone,
)

from juloserver.new_crm.constant import UserSegmentError

logger = logging.getLogger(__name__)


class StreamlinedImportUserClient:
    def __init__(
        self,
        validated_data=None,
        segment_obj=None,
        file_data_type=None,
        segment_name=None,
        chunk_file_name=None,
    ):
        self.validated_data = validated_data
        self.segment_obj = segment_obj
        self.file_data_type = file_data_type
        self.segment_name = segment_name
        self.chunk_file_name = chunk_file_name
        self.oss_bucket_name = 'streamlined-user-segments-' + settings.ENVIRONMENT.lower()

    def validate_csv_file(self):
        CommsUserSegmentChunk.objects.filter(chunk_csv_file_name=self.chunk_file_name).update(
            process_status=CommsUserSegmentConstants.ChunkStatus.ON_GOING
        )
        df_data = pd.read_csv(self.validated_data).drop_duplicates()
        file_data_type = self.file_data_type
        row_count = df_data.shape[0] if df_data.shape[0] else 0
        uploaded_ids = df_data[file_data_type].tolist()[0:]
        found_values = []
        missing_values = []
        if file_data_type not in df_data.columns[0]:
            error = UserSegmentError.DATA_NOT_FOUND.format(file_data_type)
            return error, None, row_count
        elif not uploaded_ids:
            error = UserSegmentError.INVALID_DATA
            return error, None, row_count
        if file_data_type == 'phone_number':
            for _, number in enumerate(uploaded_ids):
                formatted_number = format_mobile_phone(str(number))
                formatted_number = add_plus_62_mobile_phone(formatted_number)
                if len(str(formatted_number)) not in range(10, 15):
                    missing_values.append(str(number))
                elif not formatted_number.isdigit():
                    missing_values.append(str(number))
                else:
                    found_values.append(formatted_number)
            if missing_values:
                error = UserSegmentError.INVALID_DATA
                return error, missing_values, row_count
            return None, None, row_count
        if file_data_type == 'application_id':
            found_values = Application.objects.filter(id__in=uploaded_ids).values_list(
                'id', flat=True
            )
        elif file_data_type == 'customer_id':
            found_values = Customer.objects.filter(id__in=uploaded_ids).values_list('id', flat=True)
        else:
            found_values = Account.objects.filter(id__in=uploaded_ids).values_list('id', flat=True)
        missing_values = set(uploaded_ids).difference(set(found_values))
        missing_values = list(missing_values)
        if missing_values:
            error = UserSegmentError.INVALID_DATA
            return error, missing_values, row_count
        return None, None, row_count


    def upload_import_user_file_data_to_oss(self, encoded_base64, remote_file_name):
        decoded_bytes = base64.b64decode(encoded_base64)
        remote_filepath = '{}'.format(str(remote_file_name))
        upload_file_as_bytes_to_oss(self.oss_bucket_name, decoded_bytes, remote_filepath)
        return remote_filepath

    def record_segment_and_upload_file(self, row_count, csv_file_type, chunk_file_name):
        self.validated_data.seek(0)
        file_content = self.validated_data.read()
        file_bytes = file_content.encode('utf-8')
        encoded_base64 = base64.b64encode(file_bytes)
        segment_name = self.segment_name
        remote_file_name = segment_name + '_' + chunk_file_name
        remote_url = self.upload_import_user_file_data_to_oss(encoded_base64, remote_file_name)
        segment_obj = None
        with transaction.atomic():
            segment_obj = (
                StreamlinedCommunicationSegment.objects.filter(segment_name=segment_name)
                .select_for_update()
                .last()
            )
            if segment_obj:
                segment_obj.segment_count = (segment_obj.segment_count or 0) + row_count
                segment_obj.save()

        logger.info(
            {
                "action": "record_segment_and_upload_file",
                "segment": segment_obj.segment_name,
                "segment count": segment_obj.segment_count,
                "row_count": row_count,
                "remote_file_name": remote_file_name,
            }
        )

        if CommsUserSegmentChunk.objects.filter(chunk_csv_file_name=chunk_file_name).last():
            CommsUserSegmentChunk.objects.filter(chunk_csv_file_name=chunk_file_name).update(
                chunk_csv_file_url=remote_url,
                process_status=CommsUserSegmentConstants.ChunkStatus.FINISH,
                chunk_data_count=row_count,
            )
        return segment_obj

    def get_downloadable_response(self):
        response_list = []
        user_segment_chunks_obj = CommsUserSegmentChunk.objects.filter(
            streamlined_communication_segment=self.segment_obj
        )
        for user_segment_chunks in user_segment_chunks_obj:
            file = get_file_from_oss(self.oss_bucket_name, user_segment_chunks.chunk_csv_file_url)
            response = StreamingHttpResponse(streaming_content=file, content_type='text/csv')
            response['Content-Disposition'] = (
                'filename="' + user_segment_chunks.chunk_csv_file_name + '"'
            )
            response_list.append(response)
        return response_list
    
    def delete_file_and_record(self):
        user_segment_chunks_obj = CommsUserSegmentChunk.objects.filter(
            streamlined_communication_segment=self.segment_obj
        )
        for user_segment_chunks in user_segment_chunks_obj:
            if user_segment_chunks.chunk_csv_file_url:
                delete_public_file_from_oss(
                    self.oss_bucket_name, user_segment_chunks.chunk_csv_file_url
                )
            user_segment_chunks.delete()

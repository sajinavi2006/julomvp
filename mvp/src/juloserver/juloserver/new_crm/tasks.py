import io
import logging
import math
import os
from collections import OrderedDict, Counter
from datetime import timedelta

import pandas as pd
from celery import task
from django.db import transaction
from django.db.models import Sum
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.services import process_image_upload
from juloserver.julo.models import Image, FeatureSetting
from juloserver.new_crm.services.streamlined_services import StreamlinedImportUserClient
from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.streamlined_communication.constant import CommsUserSegmentConstants
from juloserver.streamlined_communication.models import (
    CommsUserSegmentChunk,
    StreamlinedCommunicationSegment,
)

logger = logging.getLogger(__name__)


@task
def upload_image(image_id, thumbnail=True, deleted_if_last_image=False):
    image = Image.objects.get_or_none(pk=image_id)
    if not image:
        logger.error({
            "image": image_id,
            "status": "not_found"
        })
    process_image_upload(image, thumbnail, deleted_if_last_image)


@task(queue='comms_user_segment_upload_queue')
def split_file_into_chunks_async(
    output_file_prefix, segment_obj, dataframe, file_data_type, num_chunks, rows_per_chunk
):
    """
    Processes a CSV file in chunks and validates each chunk using the `validate_file` method.

    Args:
        output_file_prefix (str): Prefix for naming output chunk files.
        segment_obj (StreamlinedCommunicationSegment): The user segment associated with the chunks.
        dataframe (pd.DataFrame): The DataFrame containing the CSV data to be processed.
        file_data_type (str): The type of data being processed.
        num_chunks (int): Total number of chunks to create from the DataFrame.
        rows_per_chunk (int): Number of rows in each chunk. Defaults to 25000.

    Returns:
        StreamlinedCommunicationSegment: The user segment object after processing the chunks.

    """
    for i in range(num_chunks):
        start_row = i * int(rows_per_chunk)
        end_row = start_row + int(rows_per_chunk)
        chunk_df = dataframe.iloc[start_row:end_row]

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
        validate_and_upload_chunked_file.delay(
            chunked_file=chunk_buffer,
            file_data_type=file_data_type,
            chunk_file_name=chunk_file_name,
            segment=segment_obj,
        )
    integrity_check_ttl_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL, is_active=True
    )
    if not integrity_check_ttl_setting:
        return general_error_response(
            "feature setting 'user_segment_chunk_integrity_check_ttl' is turn off."
        )
    check_integrity.apply_async(
        (segment_obj,), countdown=int(integrity_check_ttl_setting.parameters['TTL'])
    )
    return segment_obj


@task(queue='comms_user_segment_upload_queue')
def validate_and_upload_chunked_file(chunked_file, file_data_type, chunk_file_name, segment):
    """
    Validates and uploads chunks of the CSV file to Oss.

    Args:
        file_header: The header of the CSV file.
        chunked_file: A file-like object containing the chunked CSV data.
        file_data_type: The type of data being processed (e.g., phone_number, application_id).
        chunk_file_name: The name of the chunk file.
        segment_name: The name of the customer segment.

    Returns:
        None
    """
    import_users_client = StreamlinedImportUserClient(
        validated_data=chunked_file,
        file_data_type=file_data_type,
        segment_name=segment.segment_name,
        chunk_file_name=chunk_file_name,
    )
    errors, missing_values, row_count = import_users_client.validate_csv_file()
    if errors or missing_values:
        missing_values.append(errors)
        with transaction.atomic():
            segment_obj = (
                StreamlinedCommunicationSegment.objects.filter(id=segment.id)
                .select_for_update()
                .last()
            )
            if segment_obj:
                current_error_list = segment_obj.error_list or []
                new_error_list = current_error_list + missing_values
                segment_obj.error_list = new_error_list
                segment_obj.status = CommsUserSegmentConstants.SegmentStatus.FAILED
                segment_obj.save()
                CommsUserSegmentChunk.objects.filter(chunk_csv_file_name=chunk_file_name).update(
                    process_status=CommsUserSegmentConstants.ChunkStatus.FAILED,
                )
        logger.error(
            {
                "action": "validate_and_upload_chunked_file error",
                "error": errors,
                "missing_values": missing_values,
                "user segment": segment_obj.id,
            }
        )
        return general_error_response(errors, data=missing_values)
    import_users_client.record_segment_and_upload_file(row_count, file_data_type, chunk_file_name)


@task(queue='comms_user_segment_upload_queue')
def check_integrity(segment):
    process_status_list = CommsUserSegmentChunk.objects.filter(
        streamlined_communication_segment=segment
    ).values_list('process_status', flat=True)

    total_chunk_count = CommsUserSegmentChunk.objects.filter(
        streamlined_communication_segment=segment
    ).count()
    chunk_count_matches = segment.chunk_count == total_chunk_count
    all_statuses_finished = all(
        status == CommsUserSegmentConstants.ChunkStatus.FINISH for status in process_status_list
    )
    if all_statuses_finished:
        segment_count = (
            CommsUserSegmentChunk.objects.filter(
                streamlined_communication_segment=segment
            ).aggregate(total=Sum('chunk_data_count'))['total']
            or 0
        )
        StreamlinedCommunicationSegment.objects.filter(id=segment.id).update(
            segment_count=segment_count, status=CommsUserSegmentConstants.SegmentStatus.SUCCESS
        )
    if not chunk_count_matches or not all_statuses_finished:
        segment_obj = StreamlinedCommunicationSegment.objects.get(id=segment.id)
        if segment_obj and segment_obj.error_list:
            import_users_client = StreamlinedImportUserClient(segment_obj=segment)
            StreamlinedCommunicationSegment.objects.filter(id=segment.id).update(
                status=CommsUserSegmentConstants.SegmentStatus.FAILED,
            )
            import_users_client.delete_file_and_record()
            CommsUserSegmentChunk.objects.filter(streamlined_communication_segment=segment).delete()
            logger.info(
                {
                    "method": "check_integrity",
                    "message": "Deleted the uploaded chunks and related obj from DB.",
                    "User segment": segment_obj.id,
                }
            )

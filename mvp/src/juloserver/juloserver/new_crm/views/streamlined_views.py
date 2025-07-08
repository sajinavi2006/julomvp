import csv
import io
import logging
import math
import os
from collections import OrderedDict

import pandas as pd
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.services2 import get_redis_client
from juloserver.new_crm.tasks import split_file_into_chunks_async
from juloserver.new_crm.utils import crm_permission
from juloserver.new_crm.serializers import (
    StreamlinedCommsImportUsersUploadFileSerializer,
    StreamlinedCommunicationSegmentSerializer)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    too_early_error_response,
)
from juloserver.new_crm.services.streamlined_services import StreamlinedImportUserClient
from rest_framework.authentication import SessionAuthentication
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.new_crm.pagination import StreamlinedCommunicationSegmentPagination
from juloserver.streamlined_communication.constant import CommsUserSegmentConstants
from juloserver.streamlined_communication.models import (
    StreamlinedCommunicationSegment,
    CommsUserSegmentChunk,
)

logger = logging.getLogger(__name__)


class StreamlinedCommsImportUsersUploadFile(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.PRODUCT_MANAGER])]
    serializer_class = StreamlinedCommsImportUsersUploadFileSerializer
    pagination_class = StreamlinedCommunicationSegmentPagination

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        file, error = serializer.validate_csv_file(request.data.get('csv_file', None))
        if error:
            return general_error_response(error)

        customer_segment_name, error = serializer.validate_customer_segment_name(
            request.data.get('customer_segment_name', None)
        )
        if error:
            return general_error_response(error)

        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        df = pd.read_csv(file)
        file_header = df.columns.tolist()[0]
        file_data_type = data.get('file_data_type')
        if file_header != file_data_type:
            return general_error_response("File type mismatch")

        chunk_size_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_SIZE, is_active=True
        )
        if not chunk_size_setting:
            return general_error_response("feature setting 'user_segment_chunk_size' is turn off.")
        rows_per_chunk = chunk_size_setting.parameters['chunk_size']

        (
            output_file_prefix,
            segment_obj,
            dataframe,
            file_data_type,
            num_chunks,
        ) = self.create_user_segment_record(data, rows_per_chunk, request.user)
        # Split the file into smaller chunks asynchronously
        result = split_file_into_chunks_async.delay(
            output_file_prefix, segment_obj, dataframe, file_data_type, num_chunks, rows_per_chunk
        )
        return success_response({"user_segment_id": result.id})

    def create_user_segment_record(self, data, rows_per_chunk, user):

        if not isinstance(data, OrderedDict) or 'csv_file' not in data:
            raise ValueError("Data must be an OrderedDict containing 'csv_file' key")
        csv_file = data['csv_file']
        segment_name = data.get('customer_segment_name')[0]
        file_data_type = data.get('file_data_type')
        if not hasattr(csv_file[0], 'read'):
            raise ValueError("The 'csv_file' key must contain a file-like object")
        output_file_prefix = os.path.splitext(csv_file[0].name)[0]
        csv_file[0].seek(0)
        df = pd.read_csv(csv_file[0])
        num_chunks = math.ceil(len(df) / int(rows_per_chunk))
        segment_obj = StreamlinedCommunicationSegment.objects.create(
            segment_name=segment_name,
            csv_file_type=file_data_type,
            chunk_count=num_chunks,
            uploaded_by=user,
            csv_file_name=csv_file[0].name,
            status=CommsUserSegmentConstants.SegmentStatus.PROCESSING,
        )
        return output_file_prefix, segment_obj, df, file_data_type, num_chunks

    def get(self, request):
        queryset = StreamlinedCommunicationSegment.objects.all().order_by('-id')
        search_q = request.GET.get('search_q')
        if search_q:
            queryset = queryset.filter(
                Q(segment_name__icontains=search_q) |
                Q(uploaded_by__username__icontains=search_q)).order_by('-id')
        paginator = self.pagination_class()
        result_page = paginator.paginate_queryset(queryset, request)
        serializer = StreamlinedCommunicationSegmentSerializer(result_page, many=True)
        data={"data":serializer.data, "total_count":queryset.count()}
        return paginator.get_paginated_response(data)


class StreamlinedCommsSegmentAction(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.PRODUCT_MANAGER])]        
    
    def get(self, request, segment_id):
        segment_obj = get_object_or_404(StreamlinedCommunicationSegment, pk=segment_id)
        action = request.GET.get('action')
        if not action or action not in ['delete', 'download']:
            return general_error_response('action : This field is required, can be set to download/delete')
        import_users_client = StreamlinedImportUserClient(segment_obj=segment_obj)
        if action == 'delete':
            import_users_client.delete_file_and_record()
            logger.info({
                'action': 'streamlined_segment_delete',
                'user_id': request.user.id,
                'segment_id': segment_id,
                'segment_name': segment_obj.segment_name,
                'segment_csv_file_name': segment_obj.csv_file_name})
            response = success_response("Deleted Successfully")
        elif action == 'download':
            logger.info({
                'action': 'streamlined_segment_download',
                'user_id': request.user.id,
                'segment_id': segment_id,
                'segment_name': segment_obj.segment_name,
                'segment_csv_file_name': segment_obj.csv_file_name})
            response_list = import_users_client.get_downloadable_response()
            output = io.StringIO()
            csv_writer = csv.writer(output)
            header_written = False
            buffer = []
            for response in response_list:
                for chunk in response.streaming_content:
                    decoded_chunk = chunk.decode('utf-8')
                    buffer.append(decoded_chunk)
            complete_data = ''.join(buffer)
            csv_reader = csv.reader(io.StringIO(complete_data))
            for row in csv_reader:
                if not header_written:
                    header = row
                    csv_writer.writerow(header)
                    header_written = True
                else:
                    if row:
                        if (
                            row[0]
                            not in [
                                'account_id',
                                'application_id',
                                'customer_id',
                                'phone_number',
                            ]
                            and row[0] is not None
                        ):
                            csv_writer.writerow(row)

            output.seek(0)
            response = HttpResponse(output, content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename={segment_obj.csv_file_name}'
        return response


class StreamlinedCommsSegmentProcessStatus(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.PRODUCT_MANAGER])]

    def get(self, request, segment_id):
        segment_obj = get_object_or_404(StreamlinedCommunicationSegment, pk=segment_id)
        comms_user_segment_chunk_statuses = CommsUserSegmentChunk.objects.filter(
            streamlined_communication_segment=segment_obj
        ).values_list('process_status', flat=True)
        redis_client = get_redis_client()
        error_list = redis_client.get_list(segment_id)
        decoded_error_list = [value.decode('utf-8') for value in error_list]

        if comms_user_segment_chunk_statuses and all(
            status == CommsUserSegmentConstants.ChunkStatus.FINISH
            for status in comms_user_segment_chunk_statuses
        ):
            if segment_obj.status != CommsUserSegmentConstants.SegmentStatus.SUCCESS:
                segment_obj.status = CommsUserSegmentConstants.SegmentStatus.SUCCESS
                segment_obj.save()
            return success_response({'message': 'All chunks are finished'})
        elif any(
            status == CommsUserSegmentConstants.ChunkStatus.FAILED
            for status in comms_user_segment_chunk_statuses
        ):
            if segment_obj.status != CommsUserSegmentConstants.SegmentStatus.FAILED:
                segment_obj.status = CommsUserSegmentConstants.SegmentStatus.FAILED
                segment_obj.save()
            return general_error_response(
                {'message': 'Some chunks are Failed'}, data=decoded_error_list
            )
        else:
            return too_early_error_response(
                {'message': 'Some chunks are still in progress'}, data=decoded_error_list
            )


class StreamlinedCommsSegmentErrorDetails(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.PRODUCT_MANAGER])]

    def get(self, request, segment_id):
        segment_obj = get_object_or_404(StreamlinedCommunicationSegment, pk=segment_id)
        if segment_obj.status == CommsUserSegmentConstants.SegmentStatus.FAILED:
            if segment_obj.error_list:
                return success_response(data={'error_list': segment_obj.error_list})
            else:
                return general_error_response(message="Error list is empty")
        return general_error_response(message="UserSegment status is not Failed")

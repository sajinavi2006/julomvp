from __future__ import unicode_literals

import logging

from rest_framework import serializers
from rest_framework.exceptions import APIException
from juloserver.liveness_detection.constants import IMAGE_UPLOAD_MAX_SIZE
from juloserver.face_recognition.constants import FaceMatchingCheckConst

logger = logging.getLogger(__name__)


class CheckImageQualitySerializer(serializers.Serializer):
    image = serializers.ImageField(required=True)


class ImageMetadataSerializer(serializers.Serializer):
    file_name = serializers.CharField(max_length=500, required=True)
    directory = serializers.CharField(
        max_length=500, required=False, allow_null=True, allow_blank=True
    )
    file_size = serializers.IntegerField(required=False, allow_null=True)
    file_modification_time = serializers.DateTimeField(required=False)
    file_access_time = serializers.DateTimeField(required=False, allow_null=True)
    file_creation_time = serializers.DateTimeField(required=False, allow_null=True)
    file_permission = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    file_type = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    file_type_extension = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    file_mime = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    exif_byte_order = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    gps_lat_ref = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    gps_date = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    gps_timestamp = serializers.DateTimeField(required=False, allow_null=True)
    gps_altitude = serializers.IntegerField(required=False, allow_null=True)
    gps_long_ref = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    modify_date = serializers.DateTimeField(required=False, allow_null=True)
    creation_date = serializers.DateTimeField(required=False, allow_null=True)
    camera_model_name = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )
    orientation = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    flash_status = serializers.IntegerField(required=False, allow_null=True)
    exif_version = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    camera_focal_length = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    white_balance = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    exif_image_width = serializers.IntegerField(required=False, allow_null=True)
    exif_image_height = serializers.IntegerField(required=False, allow_null=True)
    sub_sec_time = serializers.IntegerField(required=False, allow_null=True)
    original_timestamp = serializers.DateTimeField(required=False, allow_null=True)
    sub_sec_time_original = serializers.IntegerField(required=False, allow_null=True)
    sub_sec_time_digitized = serializers.IntegerField(required=False, allow_null=True)
    make = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    jfif_version = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    resolution_unit = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    x_res = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    y_res = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    image_width = serializers.IntegerField(required=False, allow_null=True)
    image_height = serializers.IntegerField(required=False, allow_null=True)
    encoding = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    bits_per_sample = serializers.IntegerField(required=False, allow_null=True)
    color_components = serializers.IntegerField(required=False, allow_null=True)
    ycbcrsub_sampling = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    image_size = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    megapixels = serializers.FloatField(required=False, allow_null=True)
    create_date = serializers.DateTimeField(required=False, allow_null=True)
    datetime_original = serializers.DateTimeField(required=False, allow_null=True)
    gps_lat = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )
    gps_long = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )
    gps_position = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    bit_depth = serializers.IntegerField(required=False, allow_null=True)
    interlace = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    color_type = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )
    compression = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )
    filter = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )


class CheckImageQualitySerializerV1(CheckImageQualitySerializer, ImageMetadataSerializer):
    pass


class ImageSizeValidationError(APIException):
    status_code = 413
    default_detail = 'Request entity too large.'


class CheckImageQualitySerializerV2(CheckImageQualitySerializerV1):
    image = serializers.ImageField(required=False)

    def validate_image(self, value):
        filesize = value.size

        if filesize > IMAGE_UPLOAD_MAX_SIZE:
            raise ImageSizeValidationError("The maximum file size that can be uploaded is 5MB")
        else:
            return value


class FaceMatchingRequestSerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    process = serializers.ChoiceField(
        choices=[(enum.value, enum.name) for enum in FaceMatchingCheckConst.Process]
    )
    remarks = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    new_status = serializers.ChoiceField(
        choices=[(enum.value, enum.name) for enum in FaceMatchingCheckConst.Status]
    )
    is_agent_verified = serializers.NullBooleanField(required=False)

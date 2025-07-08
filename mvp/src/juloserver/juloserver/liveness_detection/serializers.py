from django.core.exceptions import ValidationError
from rest_framework import serializers

from juloserver.liveness_detection.constants import (
    IMAGE_UPLOAD_MAX_SIZE,
    ActiveLivenessPosition,
    ApplicationReasonFailed,
    SmileLivenessPicture,
    ServiceCheckType,
    ClientType,
    ActiveLivenessMethod,
)


def validate_file_size(value):
    filesize = value.size

    if filesize > IMAGE_UPLOAD_MAX_SIZE:
        raise ValidationError("The maximum file size that can be uploaded is 5MB")
    else:
        return value


class SegmentSerializer(serializers.Serializer):
    image = serializers.ImageField(required=False, validators=[validate_file_size])
    dot_position = serializers.ChoiceField(
        choices=(
            (ActiveLivenessPosition.TOP_LEFT, ActiveLivenessPosition.TOP_LEFT),
            (ActiveLivenessPosition.TOP_RIGHT, ActiveLivenessPosition.TOP_RIGHT),
            (ActiveLivenessPosition.BOTTOM_LEFT, ActiveLivenessPosition.BOTTOM_LEFT),
            (ActiveLivenessPosition.BOTTOM_RIGHT, ActiveLivenessPosition.BOTTOM_RIGHT),
        )
    )


class ActiveLivenessCheckSerializer(serializers.Serializer):
    segments = SegmentSerializer(many=True)
    application_failed = serializers.ChoiceField(
        required=False,
        choices=(
            (ApplicationReasonFailed.NO_MORE_SEGMENTS, ApplicationReasonFailed.NO_MORE_SEGMENTS),
            (ApplicationReasonFailed.EYES_NOT_DETECTED, ApplicationReasonFailed.EYES_NOT_DETECTED),
            (
                ApplicationReasonFailed.FACE_TRACKING_FAILED,
                ApplicationReasonFailed.FACE_TRACKING_FAILED,
            ),
            (ApplicationReasonFailed.INIT_FAILED, ApplicationReasonFailed.INIT_FAILED),
        ),
    )


class PassiveLivenessCheckSerializer(serializers.Serializer):
    image = serializers.ImageField(validators=[validate_file_size])


class PreCheckSerializer(serializers.Serializer):
    skip_customer = serializers.BooleanField()
    application_id = serializers.CharField(required=False)


class PreCheckSerializerV2(serializers.Serializer):
    skip_customer = serializers.BooleanField(required=False)
    service_check_type = serializers.ChoiceField(
        choices=(
            (ServiceCheckType.DDIS, ServiceCheckType.DDIS),
            (ServiceCheckType.DCS, ServiceCheckType.DCS),
        )
    )
    client_type = serializers.ChoiceField(
        choices=(
            (ClientType.ANDROID, ClientType.ANDROID),
            (ClientType.WEB, ClientType.WEB),
            (ClientType.IOS, ClientType.IOS),
        )
    )
    check_active = serializers.BooleanField(required=False)
    check_passive = serializers.BooleanField(required=False)


class SmileImageSerializer(serializers.Serializer):
    image = serializers.ImageField(required=False, validators=[validate_file_size])
    type = serializers.ChoiceField(
        choices=(
            (SmileLivenessPicture.NEUTRAL.value, SmileLivenessPicture.NEUTRAL.value),
            (SmileLivenessPicture.SMILE.value, SmileLivenessPicture.SMILE.value),
        )
    )


class SmileCheckSerializer(serializers.Serializer):
    images = SmileImageSerializer(many=True)


class PreSmileSerializer(serializers.Serializer):
    start_active = serializers.BooleanField(required=True)
    start_passive = serializers.BooleanField(required=True)


class PreCheckSerializerV3(PreCheckSerializerV2):
    active_method = serializers.ChoiceField(
        choices=(
            (ActiveLivenessMethod.EYE_GAZE.value, ActiveLivenessMethod.EYE_GAZE.value),
            (ActiveLivenessMethod.SMILE.value, ActiveLivenessMethod.SMILE.value),
            (ActiveLivenessMethod.MAGNIFEYE.value, ActiveLivenessMethod.MAGNIFEYE.value),
        )
    )


class LivenessRecordSerializer(serializers.Serializer):
    record = serializers.FileField(required=False, validators=[validate_file_size])
    application_failed = serializers.ChoiceField(
        required=False,
        choices=(
            (ApplicationReasonFailed.NO_MORE_SEGMENTS, ApplicationReasonFailed.NO_MORE_SEGMENTS),
            (ApplicationReasonFailed.EYES_NOT_DETECTED, ApplicationReasonFailed.EYES_NOT_DETECTED),
            (
                ApplicationReasonFailed.FACE_TRACKING_FAILED,
                ApplicationReasonFailed.FACE_TRACKING_FAILED,
            ),
            (ApplicationReasonFailed.INIT_FAILED, ApplicationReasonFailed.INIT_FAILED),
        ),
    )
    active_method = serializers.ChoiceField(
        choices=(
            (ActiveLivenessMethod.EYE_GAZE.value, ActiveLivenessMethod.EYE_GAZE.value),
            (ActiveLivenessMethod.SMILE.value, ActiveLivenessMethod.SMILE.value),
            (ActiveLivenessMethod.MAGNIFEYE.value, ActiveLivenessMethod.MAGNIFEYE.value),
        ),
        required=False,
    )
    start_active = serializers.BooleanField(required=False)
    start_passive = serializers.BooleanField(required=False)
    selfie_image = serializers.ImageField(required=False)

from rest_framework import serializers
from django.core.validators import MinValueValidator, MaxValueValidator
from juloserver.nps.constants import NpsSurveyErrorMessages


class NPSSurveySerilizers(serializers.Serializer):
    comments = serializers.CharField(
        required=False,
        error_messages={
            "invalid": NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG,
        },
    )
    rating = serializers.IntegerField(
        error_messages={
            "required": NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG,
            "invalid": NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG,
        },
        validators=[
            MinValueValidator(0, message='Harus lebih besar atau sama dengan 0'),
            MaxValueValidator(10, message='Harus lebih kecil atau sama dengan 10'),
        ],
    )
    android_id = serializers.CharField(
        error_messages={
            "required": NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG,
            "invalid": NpsSurveyErrorMessages.GENERAL_SERIALIZER_ERROR_MSG,
        }
    )


class NPSSurveyUpdateSerilizers(serializers.Serializer):
    is_access_survey = serializers.BooleanField()

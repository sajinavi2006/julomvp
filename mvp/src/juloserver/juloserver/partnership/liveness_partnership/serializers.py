from PIL import Image
from io import BytesIO
import logging

from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework import serializers

from juloserver.partnership.liveness_partnership.constants import (
    LivenessHTTPGeneralErrorMessage,
    LivenessType,
    IMAGE_MIME_TYPES,
    LIVENESS_UPLOAD_IMAGE_MAX_SIZE,
)
from juloserver.partnership.utils import (
    custom_error_messages_for_required,
)

logger = logging.getLogger(__name__)


def validate_liveness_image_size(value):
    max_size = LIVENESS_UPLOAD_IMAGE_MAX_SIZE
    if value.size > max_size:
        raise serializers.ValidationError(LivenessHTTPGeneralErrorMessage.NOT_ALLOWED_IMAGE_SIZE)
    return value


def convert_and_replace_image(uploaded_file):
    # convert all image to jpeg to standardize image liveness
    image = Image.open(uploaded_file)
    image_io = BytesIO()
    image = image.convert('RGB')
    image.save(image_io, format='JPEG')

    # Create a new InMemoryUploadedFile with the JPEG data
    file_name = uploaded_file.name
    converted_image = InMemoryUploadedFile(
        file=image_io,
        field_name=None,
        name=file_name.rsplit('.', 1)[0] + '.jpeg',
        content_type='image/jpeg',
        size=image_io.tell(),
        charset=None,
    )

    return converted_image


class LivenessImageUploadSerializer(serializers.Serializer):
    smile = serializers.FileField(required=False, validators=[validate_liveness_image_size])
    neutral = serializers.FileField(
        required=True,
        validators=[validate_liveness_image_size],
        error_messages=custom_error_messages_for_required('neutral'),
    )

    def validate_neutral(self, value):
        # cheking mimetypes and convert image to jpeg
        try:
            if value.content_type not in IMAGE_MIME_TYPES:
                raise serializers.ValidationError(LivenessHTTPGeneralErrorMessage.INVALID_FILE)
            converted_file = convert_and_replace_image(value)
            return converted_file
        except Exception as error:
            logger.warning(
                {
                    'action': 'FailedLivenessImageUploadSerializer',
                    'message': "failed_convert_and_replace_image",
                    'error': str(error),
                }
            )
            raise serializers.ValidationError(LivenessHTTPGeneralErrorMessage.INVALID_FILE)

    def validate(self, data):
        liveness_method = self.context.get('liveness_method')
        smile = data.get('smile')
        # validate smile, smile photo mandatory for smile liveness
        if liveness_method == LivenessType.SMILE:
            if not smile:
                raise serializers.ValidationError({"smile": "smile harus diisi"})
            try:
                if smile.content_type not in IMAGE_MIME_TYPES:
                    raise serializers.ValidationError(
                        {"smile": LivenessHTTPGeneralErrorMessage.INVALID_FILE}
                    )

                converted_smile_file = convert_and_replace_image(smile)
                data['smile'] = converted_smile_file
            except Exception as error:
                logger.warning(
                    {
                        'action': 'FailedLivenessImageUploadSerializer',
                        'message': "failed_convert_and_replace_image",
                        'error': str(error),
                    }
                )
                raise serializers.ValidationError(
                    {"smile": LivenessHTTPGeneralErrorMessage.INVALID_FILE}
                )

        return super().validate(data)

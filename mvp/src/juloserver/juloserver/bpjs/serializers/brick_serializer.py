from rest_framework import serializers

from juloserver.julo_starter.utils import custom_message_error_serializer


class GenerateWebViewSerializer(serializers.Serializer):

    application_id = serializers.IntegerField(
        required=True, error_messages=custom_message_error_serializer("data")
    )

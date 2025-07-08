from rest_framework import serializers

from juloserver.julo_starter.utils import custom_message_error_serializer
from juloserver.julo.models import Onboarding


class AppProductPickerSerializer(serializers.Serializer):
    """
    Serializer for Product Picker on the JuloStarter
    """

    onboarding_id = serializers.IntegerField(
        required=True, error_messages=custom_message_error_serializer("Onboarding")
    )
    customer_id = serializers.IntegerField(required=False)
    device_id = serializers.IntegerField(required=False)
    is_rooted_device = serializers.NullBooleanField(required=False)
    is_suspicious_ip = serializers.NullBooleanField(required=False)

    # Geolocation params
    # latitude and longitude as optional
    latitude = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages=custom_message_error_serializer("latitude"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages=custom_message_error_serializer("longitude"),
    )

    def validate_latitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value

    def validate_longitude(self, value):

        if not value:
            return 0

        if value:
            try:
                return float(value)
            except ValueError:
                raise serializers.ValidationError('Invalid request')

        return value

    def validate_onboarding_id(self, value):

        is_exist = Onboarding.objects.filter(id=value).exists()
        if not is_exist:
            raise serializers.ValidationError("Onboarding is not exist")

        return value

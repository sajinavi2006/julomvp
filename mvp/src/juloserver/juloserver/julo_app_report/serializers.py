from __future__ import absolute_import, unicode_literals

from rest_framework import serializers

from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.julo.models import Application


class JuloAppReportSerializer(serializers.Serializer):

    android_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("AndroidID")
    )

    device_name = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("Device Name")
    )

    endpoint = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
    request = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
    response = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
    application_id = serializers.IntegerField(
        required=False,
        default=None,
        allow_null=True
    )

    def validate_application_id(self, value):
        """
        Check application id existing
        """

        if value or value == 0:
            is_exist = Application.objects.filter(id=value).exists()
            if not is_exist:
                raise serializers.ValidationError("Application not found")

        return value

"""
Email Related serializers
"""
import time

from rest_framework import serializers


class EmailCallbackDTO(serializers.Serializer):
    """
    Serializer for callback event
    """

    email_request_id = serializers.CharField(required=True)
    status = serializers.CharField(required=True)
    event_at = serializers.IntegerField(
        required=False,
        allow_null=False,
        default=lambda: int(time.time()),
    )  # Unix timestamp in seconds
    remarks = serializers.CharField(required=False, allow_null=True)

    def error_string(self):
        return '; '.join([f"{field}: {', '.join(self.errors[field])}" for field in self.errors])

from rest_framework import serializers
from django.utils import timezone
import datetime

class FraudReportSubmitSerializer(serializers.Serializer):
    give_otp_or_pin = serializers.BooleanField()
    accident_date = serializers.DateField()
    monetary_loss = serializers.BooleanField()
    fraud_type = serializers.CharField()
    fraud_chronology = serializers.CharField()

    def validate_accident_date(self, value):
        today = timezone.localtime(timezone.now()).date()
        if value > today:
            raise serializers.ValidationError("Accident date should not be a future date")
        return value

from rest_framework import serializers
from juloserver.historical.models import BioSensorHistory


class BioSensorSerializer(serializers.ModelSerializer):
    accelerometer_data = serializers.ListField(required=False)
    gyroscope_data = serializers.ListField(required=False)
    gravity_data = serializers.ListField(required=False)
    rotation_data = serializers.ListField(required=False)
    orientation = serializers.CharField(required=False, allow_blank=True)
    al_activity = serializers.CharField(required=False, allow_blank=True)
    al_fragment = serializers.CharField(required=False, allow_blank=True)
    created_at = serializers.DateTimeField(required=True)
    error = serializers.ListField(required=False)
    android_id = serializers.CharField(required=False, allow_blank=True)
    gcm_reg_id = serializers.CharField(required=False, allow_blank=True)

    class Meta(object):
        model = BioSensorHistory
        exclude = ['id']


class ListBioSensorSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    histories = BioSensorSerializer(many=True)

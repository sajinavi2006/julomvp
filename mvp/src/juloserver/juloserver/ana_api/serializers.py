from builtins import object

from rest_framework import serializers

from juloserver.julo.models import DeviceScrapedData, Skiptrace


class StatusChangeSerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    new_status_code = serializers.IntegerField()
    change_reason = serializers.CharField()
    note = serializers.CharField(required=False)


class DeviceScrapedDataSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = DeviceScrapedData
        fields = '__all__'


class SkipTraceSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Skiptrace
        fields = ('application', 'contact_name', 'contact_source', 'phone_number', 'effectiveness')


class EtlPushNotificationUpdateStatusSerializer(serializers.Serializer):
    etl_job_id = serializers.IntegerField()


class PredictBankScrapCallbackSerializer(serializers.Serializer):
    status = serializers.ChoiceField(["success", "failed"])
    application_id = serializers.IntegerField()
    error_msg = serializers.CharField(allow_blank=True, required=False)


class DSDCompletionSerializer(serializers.Serializer):
    success = serializers.BooleanField(required=True)
    application = serializers.IntegerField(required=True)

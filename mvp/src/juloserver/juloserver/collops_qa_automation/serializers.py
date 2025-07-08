from rest_framework import serializers


class QAAirudderRecordingReportSerializer(serializers.Serializer):
    TaskID = serializers.CharField(required=True)
    Sign = serializers.CharField(required=True)
    QADetail = serializers.ListField(required=True)

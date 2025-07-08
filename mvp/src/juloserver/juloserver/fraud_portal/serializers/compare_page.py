from rest_framework import serializers


class ApplicationScoresResponse(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    application_full_name = serializers.CharField(required=True)
    shopee_score = serializers.BooleanField(required=False)
    application_similarity_score = serializers.FloatField(required=False)
    mycroft_score = serializers.FloatField(required=False)
    credit_score = serializers.CharField(required=False)
    active_liveness_score = serializers.FloatField(required=False)
    passive_liveness_score = serializers.FloatField(required=False)
    heimdall_score = serializers.FloatField(required=False)
    orion_score = serializers.FloatField(required=False)

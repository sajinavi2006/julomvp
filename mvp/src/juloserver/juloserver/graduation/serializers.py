from rest_framework import serializers

from juloserver.graduation.models import CustomerGraduation, CustomerGraduationFailure


class CustomerGraduationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    new_set_limit = serializers.FloatField()
    new_max_limit = serializers.FloatField()
    graduation_flow = serializers.CharField()

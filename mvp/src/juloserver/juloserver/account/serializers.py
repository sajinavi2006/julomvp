import logging
from builtins import object

from rest_framework import serializers

from juloserver.account.models import AdditionalCustomerInfo

logger = logging.getLogger(__name__)


class ImageAccountPaymentSerializer(serializers.Serializer):
    image_type = serializers.CharField(required=True)
    image_source = serializers.IntegerField(required=True)
    account_payment_id = serializers.IntegerField(required=True)
    upload = serializers.ImageField(required=True)
    filename = serializers.CharField()


class AdditionalCustomerInfoSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = AdditionalCustomerInfo
        exclude = ("cdate", "udate")


class TagihanRevampExperimentSerializer(serializers.Serializer):
    experiment_id = serializers.IntegerField(required=True)

    def validate(self, data):
        if data["experiment_id"] not in {1, 2}:
            raise serializers.ValidationError("experiment id tidak valid")
        experiment_group_mapping = {1: "control", 2: "experiment"}
        data["group"] = experiment_group_mapping[data["experiment_id"]]
        return data

from rest_framework import serializers
from juloserver.apirevampv3.serializers import CashBackToGopaySerializer
from juloserver.apiv2.serializers import CashbackSepulsaSerializer
from juloserver.apiv2.utils import custom_error_messages_for_required


class CashBackToGopaySerializerV2(CashBackToGopaySerializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )
    mobile_phone_number = serializers.CharField(required=True)
    cashback_nominal = serializers.IntegerField(required=True)


class CashBackToPaymentSerializer(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )


class CashbackSepulsaSerializerV2(CashbackSepulsaSerializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )


class CashbackTransferSerializerV2(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )


class ListSubmitOverpaidSerializer(serializers.ListSerializer):
    def validate(self, attrs):
        # Make a mapping for case and image:
        cases_images = {case['case_id']: case['image_id'] for case in attrs}

        # Duplicate case:
        if len(cases_images) != len(attrs):
            raise serializers.ValidationError("Data contains a duplicate overpaid case")

        # Duplicate image:
        if len(cases_images.values()) != len(set(cases_images.values())):
            raise serializers.ValidationError("Data contains a duplicate overpaid case")

        return cases_images

    def to_representation(self, data):
        return data


class SubmitOverpaidSerializer(serializers.Serializer):
    case_id = serializers.IntegerField()
    image_id = serializers.IntegerField()

    class Meta:
        list_serializer_class = ListSubmitOverpaidSerializer

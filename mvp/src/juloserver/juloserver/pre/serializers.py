from rest_framework import serializers


class ChangePhoneInX137Serializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    phone = serializers.CharField(required=True)


class SendLinkResetPinSerializer(serializers.Serializer):
    nik = serializers.CharField(required=True)


class ChangeApplicationDataSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    field_name = serializers.CharField(required=True)
    new_value = serializers.CharField(required=False, default="")


class ForceChangeApplicationStatusSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    status_new = serializers.CharField(required=True)
    reason = serializers.CharField(required=True)


class DeleteMtlCtlStlNullProductCustomerSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(required=True)


class Fix105NoCreditScoreSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)


class ShowCustomerInformationSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(required=True)

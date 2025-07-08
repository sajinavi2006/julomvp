from rest_framework import serializers

from juloserver.julo.models import GlobalPaymentMethod
import magic


class CreateCheckoutRequestSerializer(serializers.Serializer):
    account_payment_id = serializers.ListField(child=serializers.IntegerField(), allow_null=True)
    payment_method_id = serializers.IntegerField(required=False)
    redeem_cashback = serializers.BooleanField(required=True)
    pin = serializers.RegexField(
        r'^\d{6}$', required=False
    )
    sessionId = serializers.CharField(required=False, allow_blank=True)
    refinancing_id = serializers.IntegerField(required=False)
    total_late_fee_discount = serializers.IntegerField(required=False)


class UpdateCheckoutRequestStatusSerializer(serializers.Serializer):
    checkout_id = serializers.IntegerField(required=True)
    status = serializers.ChoiceField(
        choices=[
            'cancel',
            'finish',
        ],
        required=True
    )


class UploadCheckoutRequestSerializer(serializers.Serializer):
    checkout_id = serializers.IntegerField(required=True)
    upload = serializers.ImageField(required=True)

    def validate(self, data):
        eligible_file_types = ['image/jpg', 'image/png', 'image/jpeg']
        file_type = magic.from_buffer(data['upload'].read(1024), mime=True)
        if file_type not in eligible_file_types or not \
                str(data['upload']).lower().endswith(('.png', '.jpg', '.jpeg')):
            raise serializers.ValidationError(
                "Unsupported file type. Allowed extensions are: png, jpg, jpeg"
            )
        return data


class RepaymentInstructionSerializer(serializers.Serializer):
    payment_method_name = serializers.CharField()

    def validate(self, data):
        global_payment_method = GlobalPaymentMethod.objects.filter(
            payment_method_name__iexact=data['payment_method_name']
        ).only('id', 'payment_method_name').last()
        if not global_payment_method:
            raise serializers.ValidationError(
                'payment method name {} not found'.format(data['payment_method_name'])
            )
        data['global_payment_method'] = global_payment_method
        return data


class PaymentMethodExperimentSerializer(serializers.Serializer):
    experiment_id = serializers.IntegerField(required=True)

    def validate(self, data):
        if data["experiment_id"] not in {1, 2}:
            raise serializers.ValidationError("experiment id tidak valid")
        experiment_group_mapping = {
            1: "control",
            2: "experiment"
        }
        data["group"] = experiment_group_mapping[data["experiment_id"]]
        return data

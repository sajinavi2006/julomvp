from rest_framework import serializers

from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.loyalty.models import (
    DailyCheckin,
    LoyaltyPoint,
    PointHistory,
)


class LoyaltyPointSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoyaltyPoint
        fields = '__all__'


class DailyCheckinSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyCheckin
        fields = '__all__'


class MissionClaimRewardsSerializer(serializers.Serializer):
    mission_progress_id = serializers.IntegerField(required=True)


class PointHistorySerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='change_reason')
    created_at = serializers.DateTimeField(source='cdate')
    point_amount = serializers.SerializerMethodField()

    class Meta:
        model = PointHistory
        fields = ('title', 'created_at', 'point_amount')

    def get_point_amount(self, point_history):
        return point_history.new_point - point_history.old_point


class PointRePaymentSerializer(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )


class PointTransferBottomSheetSerializer(serializers.Serializer):
    redemption_method = serializers.CharField(required=True)
    nominal_amount = serializers.IntegerField(required=True)


class TransferToGopaySerializer(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )
    mobile_phone_number = serializers.CharField(required=True)
    nominal = serializers.IntegerField(required=True)


class CheckGopayTransferTransactionSerializer(serializers.Serializer):
    gopay_transfer_id = serializers.IntegerField(required=True)


class TransferToDanaSerializer(serializers.Serializer):
    pin = serializers.RegexField(
        r'^\d{6}$',
        error_messages=custom_error_messages_for_required("PIN")
    )
    mobile_phone_number = serializers.CharField(required=True)
    nominal = serializers.IntegerField(required=True)


class CheckDanaTransferTransactionSerializer(serializers.Serializer):
    transaction_id = serializers.IntegerField(required=True)

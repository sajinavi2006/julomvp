
from rest_framework import serializers
from django.utils import timezone

from juloserver.payment_point.models import TransactionMethod
from juloserver.promo.constants import PromoCodeMessage
from juloserver.promo.models import PromoCode

from juloserver.promo.services import get_promo_code_super_type


class PromoCodeCheckSerializer(serializers.Serializer):
    loan_xid = serializers.IntegerField(required=True)
    promo_code = serializers.CharField(required=True, max_length=80)


class PromoCodeTnCSerializer(serializers.Serializer):
    min_transaction = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    terms = serializers.SerializerMethodField()

    class Meta:
        model = PromoCode
        fields = ('min_transaction', 'start_date', 'end_date', 'terms')

    def get_min_transaction(self, obj):
        min_transaction = obj.minimum_transaction_amount()
        return 'Rp{:,}'.format(min_transaction).replace(',','.') if min_transaction else None

    def get_terms(self, obj):
        promo_benefit = obj.promo_code_benefit
        if promo_benefit and promo_benefit.promo_page:
            return promo_benefit.promo_page.content
        return None

    def get_start_date(self, obj):
        return timezone.localtime(obj.start_date).date()

    def get_end_date(self, obj):
        return timezone.localtime(obj.end_date).date()


class PromoCMSDetailSerializer(serializers.Serializer):
    nid = serializers.IntegerField()


class PromoCodeSerializer(serializers.Serializer):
    promo_code = serializers.CharField()
    promo_title = serializers.CharField(source='promo_name')
    promo_code_type = serializers.SerializerMethodField()
    start_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S %z')
    end_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S %z')
    is_eligible = serializers.BooleanField()
    ineligibility_reason = serializers.CharField(required=False)
    message = serializers.CharField(required=False)

    def get_promo_code_type(self, instance):
        return get_promo_code_super_type(instance)


class PromoCodeCheckSerializerV3(serializers.Serializer):
    loan_amount = serializers.IntegerField(required=True)
    transaction_method_id = serializers.IntegerField(required=True)
    loan_duration = serializers.IntegerField(required=True)
    promo_code = serializers.CharField(required=True, max_length=80)

    def validate_transaction_method_id(self, value):
        if not TransactionMethod.objects.filter(id=value).exists():
            raise serializers.ValidationError(PromoCodeMessage.ERROR.INVALID_TRANSACTION_METHOD)
        return value


class  PromoCodeSerializerV3(serializers.Serializer):
    promo_code = serializers.CharField()
    promo_title = serializers.CharField(source='promo_name')
    promo_code_type = serializers.SerializerMethodField()
    start_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S %z')
    end_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S %z')
    is_eligible = serializers.BooleanField()
    ineligibility_reason = serializers.CharField(required=False)
    message = serializers.CharField(required=False)

    def get_promo_code_type(self, instance):
        return get_promo_code_super_type(instance)


class PromoCodeQueryParamSerializer(serializers.Serializer):
    loan_amount = serializers.IntegerField(min_value=1, required=True)
    transaction_method_id = serializers.IntegerField(min_value=1, required=True)
    loan_duration = serializers.IntegerField(min_value=1, required=True)

    def validate_transaction_method_id(self, value):
        if not TransactionMethod.objects.filter(id=value).exists():
            raise serializers.ValidationError(PromoCodeMessage.ERROR.INVALID_TRANSACTION_METHOD)
        return value

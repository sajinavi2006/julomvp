from __future__ import unicode_literals

from datetime import datetime

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from juloserver.fraud_security.models import (
    FraudHighRiskAsn,
    FraudBlacklistedCompany,
    FraudVelocityModelResultsCheck,
    FraudAppealTemporaryBlock,
)
from juloserver.geohash.models import GeohashReverse
from juloserver.julo.models import Customer
from juloserver.julo.statuses import ApplicationStatusCodes


class BlacklistWhitelistAddSerializer(serializers.Serializer):
    CHOICE_TYPE = (('whitelist', 'Whitelist'), ('blacklist', 'Blacklist'))

    type = serializers.ChoiceField(required=True, choices=CHOICE_TYPE)
    data = serializers.CharField(required=True)
    reason = serializers.CharField(required=True)

    def validate_data(self, data):
        cleaned_data = []
        if self.initial_data.get('type') == "whitelist":
            values = data.split("\n")
            customer_ids = []
            for val in values:
                pairs = val.split(",")
                if not len(pairs) == 2:
                    raise serializers.ValidationError(
                        "Whitelist values needs (android_id,customer_id) pairs, "
                        "seperated by new line Error element - '{}'".format(str(val))
                    )

                android_id, customer_id = (pairs[0].strip(), pairs[1].strip())
                if not customer_id.isdigit():
                    raise serializers.ValidationError(
                        "Customer Ids should be digits 'customer_id' = {} is not a number".format(
                            customer_id
                        )
                    )
                customer_ids.append(int(customer_id))
                cleaned_data.append((android_id, int(customer_id)))

            existing_customer_ids = list(
                Customer.objects.filter(id__in=customer_ids).values_list('id', flat=True)
            )
            invalid_ids = list(set(customer_ids) ^ set(existing_customer_ids))
            if invalid_ids:
                raise serializers.ValidationError(
                    "Following customer ids do not exist." "\n {}".format(str(invalid_ids))
                )
            return cleaned_data

        if self.initial_data.get('type') == "blacklist":
            if "," in data:
                raise serializers.ValidationError(
                    "Blacklist values needs android_id, "
                    "seperated by new line. Commas cannot be used"
                )
            cleaned_data = [
                android_id.strip() for android_id in data.split("\n") if android_id.strip()
            ]
            return cleaned_data

        raise serializers.ValidationError("Invalid type '{}'".format(self.initial_data.get('type')))


class GeohashBucketSerializer(serializers.Serializer):
    cdate = serializers.CharField()
    geohash = serializers.CharField()
    bucket_id = serializers.CharField(source='id')

    def to_representation(self, instance):
        data = super(GeohashBucketSerializer, self).to_representation(instance)
        geohash_reverse = GeohashReverse.objects.filter(geohash=instance.geohash).last()
        if geohash_reverse:
            data['latitude'] = geohash_reverse.latitude
            data['longitude'] = geohash_reverse.longitude
            data['radius'] = geohash_reverse.estimated_radius
        return data


class GeohashUpdateStatusSerializer(serializers.ModelSerializer):
    bucket_id = serializers.CharField()

    class Meta(object):
        model = FraudVelocityModelResultsCheck
        exclude = ('id',)


class GeohashApplicationSerializer(serializers.Serializer):
    app_id = serializers.CharField(source='id')
    pline = serializers.CharField(source='product_line.product_line_type')
    email = serializers.CharField()
    fullname = serializers.CharField()
    status = serializers.CharField(source='application_status_id')

    def to_representation(self, obj):
        data = super(GeohashApplicationSerializer, self).to_representation(obj)
        x100_history = obj.applicationhistory_set.filter(
            status_old=ApplicationStatusCodes.NOT_YET_CREATED,
            status_new=ApplicationStatusCodes.FORM_CREATED,
        ).last()
        x105_history = obj.applicationhistory_set.filter(
            status_old=ApplicationStatusCodes.FORM_CREATED,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
        ).last()
        data['registration_completion_time'] = None
        if x105_history and x100_history:
            result = x105_history.cdate - x100_history.cdate
            data['registration_completion_time'] = str(result.total_seconds() * 60)
        data['x105_cdate'] = (
            datetime.strftime(x105_history.cdate, "%Y-%m-%d") if x105_history else None
        )
        device = obj.customer.device_set.last()
        data['android_id'] = device.android_id if device else None
        return data


class FraudBlacklistedCompanyAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudBlacklistedCompany
        fields = ('company_name',)

    def create(self, validated_data):
        return FraudBlacklistedCompany.objects.update_or_create(
            company_name__iexact=validated_data.get('company_name'), defaults=validated_data
        )


class FraudHighRiskAsnSerializer(serializers.ModelSerializer):
    name = serializers.CharField()

    class Meta:
        model = FraudHighRiskAsn
        fields = ('name',)

    def validate_name(self, value):
        if not value.strip():
            raise ValidationError('name must not be null or empty.')
        return value


class FraudAppealTemporaryBlockAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudAppealTemporaryBlock
        fields = ('account_id',)

    def create(self, validated_data):
        return FraudAppealTemporaryBlock.objects.update_or_create(
            account_id=validated_data.get('account_id'), defaults=validated_data
        )


class DeviceIdentityRequestSerializer(serializers.Serializer):
    julo_device_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class FraudBlockAccountRequest(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    application_id = serializers.IntegerField(required=True)
    is_appeal = serializers.BooleanField(required=True)
    is_confirmed_fraud = serializers.BooleanField(required=True)


class FraudBlockAccountResponse(serializers.Serializer):
    id = serializers.IntegerField(required=True)
    account_id = serializers.IntegerField(required=True)
    feature_name = serializers.CharField(required=True)
    is_appeal = serializers.BooleanField(required=True)
    is_confirmed_fraud = serializers.BooleanField(required=True)
    is_block = serializers.BooleanField(required=True)
    is_need_action = serializers.BooleanField(required=True)
    is_verified_by_agent = serializers.BooleanField(required=True)

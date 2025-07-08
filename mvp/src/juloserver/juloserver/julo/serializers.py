from rest_framework import serializers

from juloserver.julo.models import (
    Application,
    FraudHotspot,
    SuspiciousDomain,
)


class FraudHotspotSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudHotspot
        fields = ('latitude', 'longitude', 'radius', 'geohash', 'count_of_application',
                  'addition_date')

    def validate_count_of_application(self, value):
        return None if value == '' else value


class ApplicationSimpleSerializer(serializers.ModelSerializer):
    account_status = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = ('id', 'application_xid', 'status', 'email', 'fullname',
                  'mobile_phone_1', 'gender', 'dob', 'account_status')
        read_only_fields = ('id', 'account_status')

    def get_account_status(self, instance):
        return instance.account.status_id if instance.account else ''


class SuspiciousDomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuspiciousDomain
        fields = ('email_domain', 'reason')

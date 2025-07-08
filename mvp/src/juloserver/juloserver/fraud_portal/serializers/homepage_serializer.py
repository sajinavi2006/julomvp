from rest_framework import serializers
from juloserver.crm.fields import DateTimeTimezoneAwareField
import pytz

from juloserver.pin.models import BlacklistedFraudster
from juloserver.application_flow.models import SuspiciousFraudApps
from juloserver.fraud_security.models import (
    FraudBlacklistedGeohash5,
    FraudBlacklistedPostalCode,
    FraudBlacklistedCompany,
)
from juloserver.julo.models import (
    BlacklistCustomer,
    SuspiciousDomain,
)


class ApplicationListResponse(serializers.Serializer):
    application_id = serializers.IntegerField(source='id')
    fullname = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField(source='mobile_phone_1')
    status = serializers.IntegerField(source='application_status_id')
    product_line = serializers.IntegerField(source='product_line_id')
    account_id = serializers.IntegerField()
    account_status = serializers.IntegerField(source='account__status_id')
    customer_id = serializers.IntegerField()
    cdate = DateTimeTimezoneAwareField(default_timezone=pytz.timezone('Asia/Jakarta'))

    @classmethod
    def get_original_field_name(cls, field_name):

        field_mapping = {
            'application_id': 'id',
            'fullname': 'fullname',
            'email': 'email',
            'phone': 'mobile_phone_1',
            'status': 'application_status_id',
            'product_line': 'product_line_id',
            'account_id': 'account_id',
            'account_status': 'account__status_id',
            'customer_id': 'customer_id',
            'cdate': 'cdate',
        }
        original_field_name = field_mapping.get(field_name.replace('-', ''), field_name)
        return field_name.replace(field_name.replace('-', ''), original_field_name)


class StatusCodeListResponse(serializers.Serializer):
    status_code = serializers.IntegerField()
    status = serializers.CharField()


class ProductLineListResponse(serializers.Serializer):
    product_line_code = serializers.IntegerField()
    product_line_type = serializers.CharField()


class SuspiciousCustomerListRequest(serializers.Serializer):
    TYPE_CHOICES = (
        (0, 0),
        (1, 1),
        ("blacklist", 0),
        ("whitelist", 1),
    )
    android_id = serializers.CharField(allow_blank=True)
    phone_number = serializers.CharField(allow_blank=True)
    type = serializers.ChoiceField(choices=TYPE_CHOICES)
    reason = serializers.CharField()
    customer_id = serializers.CharField(allow_blank=True)

    def validate(self, data):
        type = data.get('type')
        android_id = data.get('android_id')
        phone_number = data.get('phone_number')
        customer_id = data.get('customer_id')

        TYPE_CHOICES_DICT = dict(self.TYPE_CHOICES)
        if TYPE_CHOICES_DICT.get(type) == 0:  # Blacklist
            if customer_id != "":
                raise serializers.ValidationError("customer_id must be empty for Blacklist.")
            if not android_id and not phone_number:
                raise serializers.ValidationError(
                    "Either android_id or phone_number must be provided for Blacklist."
                )

        elif TYPE_CHOICES_DICT.get(type) == 1:  # Whitelist
            if android_id == "":
                raise serializers.ValidationError("android_id must be provided for Whitelist.")
            if customer_id == "":
                raise serializers.ValidationError("customer_id must be provided for Whitelist.")
            if phone_number:
                raise serializers.ValidationError("phone_number must be empty for Whitelist.")

        return data

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if representation['type'] == 'blacklist':
            representation['type'] = 0
        if representation['type'] == 'whitelist':
            representation['type'] = 1
        return representation


class SuspiciousCustomerListResponse(serializers.Serializer):
    suspicious_customer_id = serializers.IntegerField()
    android_id = serializers.CharField()
    phone_number = serializers.CharField()
    type = serializers.IntegerField()
    reason = serializers.CharField()
    customer_id = serializers.CharField()
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    def get_type(self, obj):
        return 1 if obj.type == 'Whitelist' else 0


class SuspiciousAppListRequest(serializers.Serializer):
    package_names = serializers.CharField()
    transaction_risky_check = serializers.CharField()


class SuspiciousAppListResponse(serializers.ModelSerializer):
    suspicious_fraud_app_id = serializers.IntegerField(source='id')
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = SuspiciousFraudApps
        fields = ['suspicious_fraud_app_id', 'package_names', 'transaction_risky_check',
                  'cdate', 'udate']


class BlacklistedGeohash5ListRequest(serializers.Serializer):
    geohash5 = serializers.CharField()


class BlacklistedGeohash5ListResponse(serializers.ModelSerializer):
    fraud_blacklisted_geohash5_id = serializers.IntegerField(source='id')
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = FraudBlacklistedGeohash5
        fields = ['fraud_blacklisted_geohash5_id', 'geohash5', 'cdate', 'udate']


class BlacklistedPostalCodeListRequest(serializers.Serializer):
    postal_code = serializers.CharField()

    def validate(self, data):
        postal_code = data.get('postal_code')
        if len(postal_code) != 5:
            raise serializers.ValidationError(
                "({0}) postal_code must be consist of 5 numbers".format(postal_code)
            )
        return data


class BlacklistedPostalCodeListResponse(serializers.ModelSerializer):
    fraud_blacklisted_postal_code_id = serializers.IntegerField(source='id')
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = FraudBlacklistedPostalCode
        fields = ['fraud_blacklisted_postal_code_id', 'postal_code', 'cdate', 'udate']


class BlacklistedCustomerListRequest(serializers.Serializer):
    source = serializers.CharField()
    name = serializers.CharField()
    citizenship = serializers.CharField()
    dob = serializers.CharField()


class BlacklistedCustomerListResponse(serializers.ModelSerializer):
    blacklist_customer_id = serializers.IntegerField(source='id')
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = BlacklistCustomer
        fields = ['blacklist_customer_id', 'source', 'name', 'citizenship',
                  'dob', 'fullname_trim', 'cdate', 'udate']


class BlacklistedEmailDomainListRequest(serializers.Serializer):
    email_domain = serializers.CharField()
    reason = serializers.CharField()


class BlacklistedEmailDomainListResponse(serializers.ModelSerializer):
    suspicious_domain_id = serializers.IntegerField(source='id')
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = SuspiciousDomain
        fields = ['suspicious_domain_id', 'email_domain', 'reason', 'cdate', 'udate']


class BlacklistedCompanyListRequest(serializers.Serializer):
    company_name = serializers.CharField()


class BlacklistedCompanyListResponse(serializers.ModelSerializer):
    fraud_blacklisted_company_id = serializers.IntegerField(source='id')
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = FraudBlacklistedCompany
        fields = ['fraud_blacklisted_company_id', 'company_name', 'cdate', 'udate']


class SuspiciousAsnListRequest(serializers.Serializer):
    TYPE_CHOICES = (
        (0, 'Bad ASN'),
        (1, 'High Risk ASN'),
        ('bad_asn', 'Bad ASN'),
        ('high_risk_asn', 'High Risk ASN'),
    )
    name = serializers.CharField()
    type = serializers.ChoiceField(choices=TYPE_CHOICES)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if representation['type'] == 'bad_asn':
            representation['type'] = 0
        if representation['type'] == 'high_risk_asn':
            representation['type'] = 1
        return representation


class SuspiciousAsnListResponse(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(required=False)
    asn_data = serializers.CharField(required=False)
    type = serializers.IntegerField()
    cdate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')
    udate = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S')

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['fraud_high_risk_asn_id'] = representation.pop('id')
        has_asn_data = representation.get('asn_data', None)
        if has_asn_data:
            representation['name'] = representation.pop('asn_data')
        return representation

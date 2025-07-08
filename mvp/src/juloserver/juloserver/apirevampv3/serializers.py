from __future__ import unicode_literals

import logging
from builtins import object

from rest_framework import serializers

from juloserver.julo.models import Banner

logger = logging.getLogger(__name__)


class BannerSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Banner
        fields = ('name', 'image_url', 'click_action', 'banner_type')


class BankAccountValidationSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    name_in_bank = serializers.CharField(required=True)
    bank_account_number = serializers.CharField(required=True)


class CashBackToGopaySerializer(serializers.Serializer):
    mobile_phone_number = serializers.CharField(required=True)
    cashback_nominal = serializers.IntegerField(required=True)


class GopayOtpRequestsSerializer(serializers.Serializer):
    mobile_phone_number = serializers.CharField(required=True)


class GopayOtpValidationSerializer(serializers.Serializer):
    request_id = serializers.CharField(required=False)
    otp_token = serializers.CharField()


class GopayPhoneNumberValidationSerializer(serializers.Serializer):
    new_phone_number = serializers.CharField(required=True)

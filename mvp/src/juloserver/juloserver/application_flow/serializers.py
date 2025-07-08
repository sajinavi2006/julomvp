from __future__ import unicode_literals

import re
import logging
from datetime import datetime

from rest_framework import serializers

from juloserver.application_flow.models import EmulatorCheck, EmulatorCheckIOS
from juloserver.julo.models import Application
from juloserver.employee_financing.utils import verify_nik

logger = logging.getLogger(__name__)


class ReapplyJuloOneSerializer(serializers.Serializer):
    mother_maiden_name = serializers.CharField(required=False)
    app_version = serializers.CharField(required=False)
    device_id = serializers.CharField(required=False)


class EmulatorCheckSafetyNetSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField()
    service_provider = serializers.CharField(required=False)
    timestamp_ms = serializers.CharField(required=False)
    is_request_timeout = serializers.BooleanField(required=False, write_only=True)

    def validate_timestamp_ms(self, value):
        if value and not value == 'null':
            return datetime.fromtimestamp(int(value))
        else:
            return None

    def create(self, validated_data):
        if 'is_request_timeout' in validated_data:
            validated_data.pop('is_request_timeout')
        return super(EmulatorCheckSafetyNetSerializer, self).create(validated_data)

    def update(self, instance, validated_data):
        if 'is_request_timeout' in validated_data:
            validated_data.pop('is_request_timeout')
        return super(EmulatorCheckSafetyNetSerializer, self).update(instance, validated_data)

    class Meta(object):
        model = EmulatorCheck
        exclude = ['application', 'id']


class GooglePlayIntegritySerializer(serializers.ModelSerializer):
    class Meta(object):
        model = EmulatorCheck
        fields = ['original_response']


class ResubmitBankAccountSerializer(serializers.Serializer):
    bank_code = serializers.CharField(required=True)
    account_number = serializers.CharField(required=True)
    name_in_bank = serializers.CharField(required=True)


class GooglePlayIntegrityDecodeSerializer(serializers.Serializer):
    error_message = serializers.CharField(required=False)
    integrity_token = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('error_message') and not data.get('integrity_token'):
            raise serializers.ValidationError("'integrity_token' or 'error_message' is required")
        return data


class EmulatorCheckIOSSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = EmulatorCheckIOS
        fields = ['is_emulator', 'brand', 'os_name', 'os_version', 'cpu_arch', 'model']


class SelfCorrectionTypoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = ["fullname", "dob", "birth_place", "ktp"]
        read_only_fields = ["fullname", "dob", "birth_place", "ktp"]

    def to_representation(self, instance):
        import locale

        representation = super(SelfCorrectionTypoSerializer, self).to_representation(instance)
        if instance.dob:
            try:
                locale.setlocale(locale.LC_TIME, 'id_ID.UTF-8')  # Set locale to Indonesian
            except locale.Error:
                pass
            dob = instance.dob.strftime('%d %B %Y')  # Format the date
        else:
            dob = instance.dob

        representation['dob'] = dob
        return representation


class SelfMotherCorrectionSerializer(serializers.ModelSerializer):
    mother_maiden_name = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = ["mother_maiden_name"]

    def get_mother_maiden_name(self, obj):
        return obj.customer.mother_maiden_name


class SelfMotherTypoCorrectionSerializer(serializers.ModelSerializer):
    mother_maiden_name = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = ["fullname", "dob", "birth_place", "ktp", "mother_maiden_name"]
        read_only_fields = ["fullname", "dob", "birth_place", "ktp"]

    def to_representation(self, instance):
        import locale

        representation = super(SelfMotherTypoCorrectionSerializer, self).to_representation(instance)
        if instance.dob:
            try:
                locale.setlocale(locale.LC_TIME, 'id_ID.UTF-8')  # Set locale to Indonesian
            except locale.Error:
                pass
            dob = instance.dob.strftime('%d %B %Y')  # Format the date
        else:
            dob = instance.dob

        representation['dob'] = dob
        return representation

    def get_mother_maiden_name(self, obj):
        return obj.customer.mother_maiden_name

    def validate_ktp(self, value):
        if not value:
            return value

        if not re.match(r'^\d{16}$', str(value)):
            raise serializers.ValidationError("No KTP hanya boleh isi angka dan 16 digit")

        if not verify_nik(value):
            raise serializers.ValidationError("No KTP tidak valid")
        return value


class BankCorrectionSerializer(serializers.ModelSerializer):
    SAFE_NUMBER_REGEX = re.compile(r'^[0-9/.]+$')
    SAFE_STRING_REGEX = re.compile(r'^[a-zA-Z0-9-_(), /.]+$')

    bank_name = serializers.CharField()
    bank_account_number = serializers.CharField()
    name_in_bank = serializers.CharField()

    class Meta:
        model = Application
        fields = ["name_in_bank", "bank_name", "bank_account_number"]

    def validate_bank_account_number(self, value):
        if not self.SAFE_NUMBER_REGEX.match(value):
            raise serializers.ValidationError("Invalid bank_account_number")
        return value

    def validate_name_in_bank(self, value):
        if not self.SAFE_STRING_REGEX.match(value):
            raise serializers.ValidationError("Invalid name_in_bank")
        return value

    def validate_bank_name(self, value):
        if not self.SAFE_STRING_REGEX.match(value):
            raise serializers.ValidationError("Invalid bank_name")
        return value

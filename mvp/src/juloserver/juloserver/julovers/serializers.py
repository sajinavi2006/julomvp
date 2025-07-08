from __future__ import unicode_literals

import re
from builtins import object
from django.conf import settings
from rest_framework import serializers
from juloserver.julo.banks import BankManager

from juloserver.julo.utils import check_email
from juloserver.julovers.models import Julovers
from juloserver.partnership.constants import ErrorMessageConst


class JuloversSerializer(serializers.ModelSerializer):
    dob = serializers.DateField(required=True, input_formats=settings.DATE_INPUT_FORMATS)
    job_start = serializers.DateField(required=True, input_formats=settings.DATE_INPUT_FORMATS)
    resign_date = serializers.DateField(
        required=False, input_formats=settings.DATE_INPUT_FORMATS + ['']
    )
    fullname = serializers.CharField(required=True)
    email = serializers.EmailField(required=True, allow_blank=False)
    address = serializers.CharField(required=True)
    mobile_phone_number = serializers.CharField(required=True, allow_blank=False)
    gender = serializers.CharField(required=True)
    marital_status = serializers.CharField(required=True)
    job_type = serializers.CharField(required=True)
    bank_name = serializers.CharField(required=True)
    bank_account_number = serializers.CharField(required=True)
    name_in_bank = serializers.CharField(required=True)
    set_limit = serializers.CharField(required=True)
    real_nik = serializers.CharField(required=True)

    class Meta(object):
        model = Julovers
        fields = '__all__'

    def validate(self, data):
        try:
            data['set_limit'] = int(data['set_limit'].replace(',', ''))
        except ValueError:
            raise serializers.ValidationError("set limit invalid format")

        email = data['email'].strip().lower()
        if not check_email(email):
            raise serializers.ValidationError("Masukan alamat email yang valid")

        if not re.match(r'^\d{16}$', data['real_nik']):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        #  bank_name
        bank_name = data['bank_name']
        bank = BankManager.get_by_name_or_none(bank_name)
        if not bank:
            raise serializers.ValidationError('Bank name is invalid. Need full name for banks')

        mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^08\s?|^008)(\d{3,4}-?){2}\d{3,4}$')
        if not mobile_phone_regex.match(data["mobile_phone_number"]):
            raise serializers.ValidationError('Mobile phone number {}'.format(
                ErrorMessageConst.INVALID_PATTERN
            ))

        return data

    def to_internal_value(self, data):
        if data.get('resign_date', None) == '':
            data.pop('resign_date')
        email = data['email'].lower().strip()
        data['email'] = email
        return super(JuloversSerializer, self).to_internal_value(data)

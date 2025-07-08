import os
import re

from datetime import datetime
from django.contrib.auth.models import User
from rest_framework import serializers

from typing import Dict, Any

from juloserver.julo.utils import verify_nik, format_mobile_phone
from juloserver.partnership.constants import ErrorMessageConst


class WebPortalAuthenticationSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = None

    def validate(self, data: Dict) -> Dict:
        username = data.get('username')
        password = data.get('password')

        error_message = "Username or password is invalid"
        user = User.objects.filter(username=username).first()
        if not user:
            raise serializers.ValidationError(error_message)

        is_password_correct = user.check_password(password)
        if not is_password_correct:
            raise serializers.ValidationError(error_message)

        self.user = user

        return data

    def get_token(self) -> str:
        return self.user.auth_expiry_token.key


class WebPortalRegisterSerializer(serializers.Serializer):
    username = serializers.CharField(allow_blank=True)
    password = serializers.CharField(allow_blank=True)

    def validate_username(self, value):

        error_message = "NIK tidak boleh kosong"
        if not value:
            raise serializers.ValidationError(error_message)

        if not verify_nik(value):
            raise serializers.ValidationError('NIK {}'.format(ErrorMessageConst.INVALID_PATTERN))

        return value


class ImageUploadSerializer(serializers.Serializer):
    image_file = serializers.FileField(required=True)
    image_type = serializers.CharField(required=True)

    def validate_image_file(self, file):
        name_file, extension = os.path.splitext(file.name)
        if extension not in ['.jpeg', '.png', '.jpg']:
            raise serializers.ValidationError('extension not allowed')

        max_size = 1024 * 1024 * 10
        if file._size > max_size:
            raise serializers.ValidationError('Document too big. Size cannot exceed 10 Mb')

        datenow = datetime.now()   
        filename = ''

        filename = '{}_{}_{}{}'.format(
            name_file,
            datenow.strftime("%Y%m%d"),
            datenow.strftime("%H%M%S"),
            extension
        )
        file.name = filename
        return file


class OTPRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True)

    def validate_phone_number(self, value):
        error_message = 'Invalid phone number'

        if len(value) > 16:
            raise serializers.ValidationError(error_message)

        if not value.isnumeric():
            raise serializers.ValidationError(error_message)

        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(error_message)

        phone_number = format_mobile_phone(value)
        return phone_number


class OTPValidateSerializer(serializers.Serializer):
    phone_number = serializers.CharField(required=True)
    otp_token = serializers.CharField(required=True)

    def validate_phone_number(self, value):
        error_message = 'Invalid phone number'

        if len(value) > 16:
            raise serializers.ValidationError(error_message)

        if not value.isnumeric():
            raise serializers.ValidationError(error_message)

        phone_number_regex = r'^(\+62|62|0)8[1-9][0-9]{7,11}$'
        if not (re.fullmatch(phone_number_regex, value)):
            raise serializers.ValidationError(error_message)

        phone_number = format_mobile_phone(value)
        return phone_number


class ChangeLoanStatusSerializer(serializers.Serializer):
    status = serializers.CharField(
        required=True,
    )

    def validate(self, attrs):
        status = attrs['status']
        error_message = 'yang dimasukkan tidak sesuai'
        if status not in {'sign', 'cancel'}:
            raise serializers.ValidationError(error_message)

        return attrs

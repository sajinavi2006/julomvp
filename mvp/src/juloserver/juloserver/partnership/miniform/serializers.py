from typing import Dict
import re

from rest_framework import serializers

from juloserver.julo.utils import email_blacklisted, format_mobile_phone
from juloserver.partnership.utils import (
    partnership_check_email,
    miniform_verify_nik, miniform_verify_phone
)


class MiniFormPhoneOfferSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    nik = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    email = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    other_phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data: Dict) -> Dict:
        errors = []
        name = data.get('name')
        nik = data.get('nik')
        email = data.get('email')
        phone = data.get('phone_number')
        other_phone = data.get('other_phone_number')

        if not name:
            errors.append("Nama lengkap tidak boleh kosong")

        if not nik:
            errors.append("NIK tidak boleh kosong")

        if not email:
            errors.append("Email tidak boleh kosong")

        if not phone:
            errors.append("Nomor HP tidak boleh kosong")

        if name:
            if len(name) < 3:
                errors.append('Nama minimum 3 karakter')

            if any(char.isdigit() for char in name):
                errors.append('Nama tidak dapat diisi dengan angka')

            name_symbolonly = re.compile('^[^a-zA-Z]+$')
            if name_symbolonly.fullmatch(name):
                errors.append('Nama tidak boleh hanya symbol')

            name_withsymbol = re.compile("^[a-zA-Z .,'-]+$")
            if not name_withsymbol.fullmatch(name):
                errors.append('Nama tidak boleh dengan symbol')

            if re.search(r'\s{2,}', name):
                errors.append('Nama tidak boleh menggunakan 2 spasi sekaligus')

        if nik:
            err = miniform_verify_nik(nik)
            if err:
                errors.append(err)

        if email:
            if partnership_check_email(email):
                if email_blacklisted(email):
                    errors.append('Email harus google')
            else:
                errors.append('Email tidak sesuai format')

        if phone:
            err = miniform_verify_phone(phone)
            if err:
                errors.append(err)

            try:
                formatted_phone_number = format_mobile_phone(phone)
                data['phone_number'] = formatted_phone_number
            except Exception:
                errors.append('Nomor HP tidak sesuai format')

        if other_phone:
            err = miniform_verify_phone(other_phone)
            if err:
                errors.append(err)

            try:
                formatted_phone_number = format_mobile_phone(other_phone)
                data['other_phone_number'] = formatted_phone_number
            except Exception:
                errors.append('Nomor HP tidak sesuai format')

        if phone == other_phone:
            errors.append('Nomor HP dan Nomor HP Lainnya harus berbeda')

        if errors:
            raise serializers.ValidationError(errors)

        return data

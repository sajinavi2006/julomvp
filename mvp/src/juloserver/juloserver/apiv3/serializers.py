from __future__ import unicode_literals

import logging
import re

from builtins import object

from rest_framework import serializers

from juloserver.julo.models import (
    Customer,
    DeviceGeolocation,
    Application,
)
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.julo.utils import verify_nik
from juloserver.application_form.constants import ApplicationUpgradeConst

from .models import SubDistrictLookup
from juloserver.application_form.serializers.application_serializer import ApplicationValidator
from juloserver.application_form.constants import ApplicationJobSelectionOrder

logger = logging.getLogger(__name__)


class SubDistrictLookupReqSerializer(serializers.Serializer):
    province = serializers.CharField(required=True)
    city = serializers.CharField(required=True)
    district = serializers.CharField(required=True)


class SubDistrictLookupResSerializer(serializers.ModelSerializer):
    subDistrict = serializers.ReadOnlyField(source='sub_district')

    class Meta(object):
        model = SubDistrictLookup
        fields = ('subDistrict', 'zipcode')


class AddressInfoSerializer(serializers.Serializer):
    subdistrict = serializers.CharField(required=True)
    zipcode = serializers.CharField(required=True)


class AppsflyerSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Customer
        fields = ('appsflyer_device_id', 'advertising_id')


class DeviceGeolocationSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device', required=False)

    class Meta(object):
        model = DeviceGeolocation
        exclude = ('device',)


class ApplicationUpdateSerializerV3(ApplicationValidator, serializers.ModelSerializer):
    status = serializers.ReadOnlyField()
    latitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Latitude", type="Float"),
    )
    longitude = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        error_messages=custom_error_messages_for_required("Longitude", type="Float"),
    )
    onboarding_id = serializers.ReadOnlyField()
    birth_place = serializers.CharField(
        required=True,
        allow_null=False,
        allow_blank=False,
        max_length=50,
        error_messages=custom_error_messages_for_required("Tempat lahir"),
    )
    mother_maiden_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    # Android will send is_upgrade is True.
    # If customer send data by Form Upgrade from JTurbo to J1
    is_upgrade = serializers.ReadOnlyField(
        required=False,
        default=False,
    )

    application_path_tag = serializers.ChoiceField(
        choices=(
            (ApplicationJobSelectionOrder.FIRST, ApplicationJobSelectionOrder.FIRST),
            (ApplicationJobSelectionOrder.SECOND, ApplicationJobSelectionOrder.SECOND),
            (ApplicationJobSelectionOrder.THIRD, ApplicationJobSelectionOrder.THIRD),
            (ApplicationJobSelectionOrder.FOURTH, ApplicationJobSelectionOrder.FOURTH),
            (ApplicationJobSelectionOrder.FIFTH, ApplicationJobSelectionOrder.FIFTH),
            (ApplicationJobSelectionOrder.SIXTH, ApplicationJobSelectionOrder.SIXTH),
            (ApplicationJobSelectionOrder.SEVENTH, ApplicationJobSelectionOrder.SEVENTH),
            (ApplicationJobSelectionOrder.EIGHTH, ApplicationJobSelectionOrder.EIGHTH),
        ),
        required=False,
    )

    # delete this section cause https://juloprojects.atlassian.net/browse/ON-503
    # def validate(self, data):
    #     if 'payday' in data and data.get('payday', 1) > 28:
    #         data['payday'] = 28
    #
    #     return data

    def validate_birth_place(self, value):
        """
        Refer to the ticket:
        https://juloprojects.atlassian.net/browse/RUS1-1222
        Add validation for birth_place (only for J1)
        Prevent birth_place input Symbol, numeric etc.
        """

        if value:
            birth_place_format = re.compile('^[a-zA-Z ]+$')
            if not birth_place_format.search(value):
                raise serializers.ValidationError('Tempat lahir tidak valid')

        return value

    def validate_latitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('latitude tidak valid')
        return value

    def validate_longitude(self, value):
        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('longitude tidak valid')
        return value

    def fix_job_industry(self, value):
        if value and value == "Staf rumah tangga":
            return value.title()
        return None

    def to_internal_value(self, data):
        duplicated_data = data.copy()
        value = self.fix_job_industry(duplicated_data.get('job_industry'))
        if value:
            duplicated_data["job_industry"] = value

        is_upgrade = duplicated_data.get('is_upgrade', False)
        if is_upgrade:
            duplicated_data = {
                key: duplicated_data[key]
                for key in ApplicationUpgradeConst.FIELDS_UPGRADE_FORM
                if key in duplicated_data
            }

        return super(ApplicationUpdateSerializerV3, self).to_internal_value(duplicated_data)

    def validate_ktp(self, value):
        if not value:
            raise serializers.ValidationError("NIK tidak boleh kosong")

        if not verify_nik(value):
            raise serializers.ValidationError("NIK tidak valid")

        return value

    def validate_loan_purpose_desc(self, value):
        return value or None

    def validate_last_education(self, value):
        return value or None

    def validate_home_status(self, value):
        return value or None

    def validate_is_upgrade(self, value):
        if isinstance(value, str):
            return str(value).lower == 'true'
        return value

    class Meta(object):
        """
        Remove key "onboarding" from response
        And keep for key "onboarding_id"

        Refer:
        https://juloprojects.atlassian.net/browse/RUS1-1346
        """

        model = Application
        exclude = (
            'application_status',
            'onboarding',
            'is_upgrade',
            'application_path_tag',
        )

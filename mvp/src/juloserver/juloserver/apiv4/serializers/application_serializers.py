from __future__ import unicode_literals

import re

from builtins import object
from rest_framework import serializers

from juloserver.julo.models import Application
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.julo.utils import verify_nik
from juloserver.application_form.constants import ApplicationUpgradeConst
from juloserver.application_form.serializers.application_serializer import ApplicationValidator
from juloserver.application_form.constants import ApplicationJobSelectionOrder
from juloserver.apiv4.constants import CleanStringListFields
from juloserver.julo.utils import clean_string_from_special_chars


class ApplicationUpdateSerializerV4(ApplicationValidator, serializers.ModelSerializer):
    status = serializers.ReadOnlyField()
    latitude = serializers.CharField(
        required=False,
        error_messages=custom_error_messages_for_required("Latitude", type="Float"),
    )
    longitude = serializers.CharField(
        required=False,
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

        if not value:
            raise serializers.ValidationError('Bad request')

        if value:
            try:
                value = float(value)
            except ValueError:
                raise serializers.ValidationError('latitude tidak valid')
        return value

    def validate_longitude(self, value):

        if not value:
            raise serializers.ValidationError('Bad request')

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

    def validate_bank_account_number(self, value):

        if not value:
            raise serializers.ValidationError('Nomor Rekening Pribadi tidak boleh kosong')

        if not value.isnumeric():
            raise serializers.ValidationError(
                'Nomor Rekening Pribadi hanya diperbolehkan diisi dengan Angka'
            )

        return value

    def to_internal_value(self, data):

        duplicated_data = data.copy()
        value = self.fix_job_industry(duplicated_data.get('job_industry'))

        if value:
            duplicated_data["job_industry"] = value

        for field in CleanStringListFields.FIELDS:
            if field in duplicated_data:
                duplicated_data[field] = clean_string_from_special_chars(duplicated_data.get(field))

        is_upgrade = duplicated_data.get('is_upgrade', False)
        if is_upgrade:
            duplicated_data = {
                key: duplicated_data[key]
                for key in ApplicationUpgradeConst.FIELDS_UPGRADE_FORM
                if key in duplicated_data
            }

        return super(ApplicationUpdateSerializerV4, self).to_internal_value(duplicated_data)

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


class AgentAssistedSubmissionSerializer(ApplicationUpdateSerializerV4):
    def validate(self, attrs):
        """Validate all fields with explicit error messages."""
        errors = {}
        for attr in attrs:
            try:
                super().validate(attrs)
            except serializers.ValidationError as e:
                errors[attr] = e.detail.get(attr)

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def to_internal_value(self, data):
        duplicated_data = data.copy()
        value = self.fix_job_industry(duplicated_data.get('job_industry'))
        if value:
            duplicated_data["job_industry"] = value

        # Set monthly_housing_cost to 0
        if duplicated_data.get('monthly_housing_cost') is None:
            duplicated_data['monthly_housing_cost'] = 0

        return super(ApplicationUpdateSerializerV4, self).to_internal_value(duplicated_data)

    class Meta(ApplicationUpdateSerializerV4.Meta):
        exclude = (
            'application_status',
            'onboarding',
            'application_path_tag',
            'is_upgrade',
            'ktp',
            'mobile_phone_1',
            'longitude',
            'latitude',
        )

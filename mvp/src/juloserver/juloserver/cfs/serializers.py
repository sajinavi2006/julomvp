from __future__ import unicode_literals
from rest_framework import serializers

from django.core.exceptions import ValidationError

from juloserver.cfs.constants import FeatureNameConst, MissionUploadType

from juloserver.julo.models import FeatureSetting
from juloserver.julo.validators import FileValidator


import logging

from juloserver.cfs.constants import (
    PhoneRelatedType, PhoneContactType, EtlJobType, ShareSocialMediaAppName
)


logger = logging.getLogger(__name__)


class ClaimCfsRewardsSerializer(serializers.Serializer):
    action_assignment_id = serializers.IntegerField(required=True)


class CfsUploadDocument(serializers.Serializer):
    image_id = serializers.IntegerField(required=True)


class CfsAssignmentVerifyAddress(serializers.Serializer):
    latitude = serializers.FloatField(required=True)
    longitude = serializers.FloatField(required=True)


class CfsAssignmentConnectBank(serializers.Serializer):
    bank_name = serializers.CharField(required=True)


class CfsAssignmentPhoneRelated(serializers.Serializer):
    phone_related_type = serializers.ChoiceField(
        choices=[
            PhoneRelatedType.FAMILY_PHONE_NUMBER,
            PhoneRelatedType.OFFICE_PHONE_NUMBER
        ],
        required=True
    )
    phone_number = serializers.CharField(required=True)
    company_name = serializers.CharField(required=False)
    contact_type = serializers.ChoiceField(
        choices=[
            PhoneContactType.PARENT,
            PhoneContactType.SIBLINGS,
            PhoneContactType.COUPLE,
            PhoneContactType.FAMILY,
        ],
        required=False
    )
    contact_name = serializers.CharField(required=False)

    def validate(self, data):
        if data['phone_related_type'] == PhoneRelatedType.OFFICE_PHONE_NUMBER:
            if 'company_name' not in data:
                raise serializers.ValidationError('Missing company name')

        else:
            if 'contact_type' not in data:
                raise serializers.ValidationError('Missing phone contact type')

            if 'contact_name' not in data:
                raise serializers.ValidationError('Missing contact name')

        return data


class CfsAssignmentShareSocialMedia(serializers.Serializer):
    app_name = serializers.ChoiceField(
        choices=[
            ShareSocialMediaAppName.INSTAGRAM,
            ShareSocialMediaAppName.FACEBOOK,
            ShareSocialMediaAppName.TWITTER,
            ShareSocialMediaAppName.WHATSAPP,
            ShareSocialMediaAppName.TELEGRAM,
            ShareSocialMediaAppName.TIKTOK,
            ShareSocialMediaAppName.LINKEDIN,
            ShareSocialMediaAppName.LINE,
        ],
        required=True
    )


class CfsAssignmentVerifyPhoneNumberViaOTP(serializers.Serializer):
    session_token = serializers.CharField(required=True, max_length=500)


class CfsActionType(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[
            EtlJobType.CFS
        ],
        required=True
    )


class CfsMonthHistoryDetails(serializers.Serializer):
    month = serializers.RegexField(regex='^([1-9]|1[012])$',
                                   required=True)
    year = serializers.RegexField(regex='^([0-9]{4})$',
                                  required=True)


class CFSWebUploadImage(serializers.Serializer):
    upload = serializers.ImageField(required=True)
    image_type = serializers.CharField(required=True)

    def validate_upload(self, value):
        allowed_extensions = ['png', 'jpg', 'jpeg']
        max_size = self.get_max_size_from_fs()

        validator = FileValidator(
            allowed_extensions=allowed_extensions,
            max_size=max_size
        )
        validator(value)

        return value

    @classmethod
    def get_max_size_from_fs(cls):
        cfs_upload_img_fs = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.CFS_UPLOAD_IMAGE_SIZE, is_active=True
        )

        if not cfs_upload_img_fs:
            logger.error({
                'action': 'validate_upload_image_size',
                'error': 'CFS feature setting for image upload is not found or not activated'
            })
            raise ValidationError("Feature setting not found")

        params = cfs_upload_img_fs.parameters
        return int(params["max_size"])


class CFSWebUploadDocument(serializers.Serializer):
    image_ids = serializers.ListField(
        child=serializers.IntegerField(required=True)
    )
    monthly_income = serializers.IntegerField(required=False)
    upload_type = serializers.CharField(required=True)

    def validate(self, data):
        upload_types_require_income = [
            MissionUploadType.UPLOAD_BANK_STATEMENT,
            MissionUploadType.UPLOAD_SALARY_SLIP
        ]

        upload_type = data['upload_type']
        monthly_income = data.get('monthly_income')

        if upload_type in upload_types_require_income and monthly_income is None:
            raise serializers.ValidationError({
                'monthly_income': f'Monthly income is required for upload type: {upload_type}'
            })

        return data


class CfsChangePendingStatus(serializers.Serializer):
    monthly_income = serializers.IntegerField(required=False)

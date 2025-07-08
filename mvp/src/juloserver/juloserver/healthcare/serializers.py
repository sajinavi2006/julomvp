from rest_framework import serializers
from juloserver.healthcare.models import (
    HealthcareUser,
    HealthcarePlatform,
)
from juloserver.customer_module.models import BankAccountDestination

from juloserver.julo.models import Bank

from juloserver.disbursement.models import BankNameValidationLog
from juloserver.disbursement.constants import (
    NameBankValidationStatus,
    NameBankValidationVendors,
)

from juloserver.healthcare.services.feature_related import is_allow_add_new_healthcare_platform


class HealthcarePlatformUploadSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    city = serializers.CharField(required=True)


class HealthcarePlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = HealthcarePlatform
        fields = (
            'id',
            'name',
        )


class BankAccountDestinationSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    logo = serializers.SerializerMethodField()
    account_name = serializers.SerializerMethodField()

    class Meta(object):
        model = BankAccountDestination
        fields = (
            'id',
            'code',
            'name',
            'logo',
            'account_name',
            'account_number',
        )

    def get_name(self, obj):
        return obj.bank.bank_name

    def get_code(self, obj):
        return obj.bank.xfers_bank_code

    def get_logo(self, obj):
        return obj.bank.bank_logo

    def get_account_name(self, obj):
        return obj.name_bank_validation.name_in_bank


class HealthcareUserSerializer(serializers.ModelSerializer):
    healthcare_platform = HealthcarePlatformSerializer()
    bank_account_destination = BankAccountDestinationSerializer()

    class Meta:
        model = HealthcareUser
        fields = (
            'id',
            'fullname',
            'healthcare_platform',
            'bank_account_destination',
        )


class UpdateHealthcarePlatformRegisterPathParamSerializer(serializers.Serializer):
    healthcare_user_id = serializers.IntegerField(required=True)

    def validate(self, data):
        healthcare_user_id = data['healthcare_user_id']
        healthcare_user = HealthcareUser.objects.get_or_none(
            id=healthcare_user_id, account=self.context['account'], is_deleted=False
        )
        if not healthcare_user:
            raise serializers.ValidationError(
                'healthcare_user_id={} is not found'.format(healthcare_user_id)
            )
        return healthcare_user


class HealthcareFaqOutputSerializer(serializers.Serializer):
    title = serializers.CharField(required=True)
    content = serializers.CharField(required=True)


class CreateHealthcareUserPlatformSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, default=None)
    name = serializers.CharField(required=False, allow_blank=False, default=None)


class HealthcarePlatformReponseSerializer(serializers.Serializer):
    adding_enable = serializers.BooleanField()
    list = CreateHealthcareUserPlatformSerializer(many=True)


class CreateHealthcareUserBankSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, allow_blank=False)
    validated_id = serializers.CharField(required=True, allow_blank=False)


class CreateHealthcareUserSerializer(serializers.Serializer):
    healthcare_platform = CreateHealthcareUserPlatformSerializer()
    bank = CreateHealthcareUserBankSerializer()
    name = serializers.CharField(required=False, max_length=200, allow_blank=True)

    def validate(self, data):
        adding_enable = is_allow_add_new_healthcare_platform()
        healthcare_platform_id = data['healthcare_platform']['id']
        healthcare_platform_name = data['healthcare_platform']['name']

        # Check only 'name' in 'healthcare_platform' (want to add new one)
        # or only 'id' (select from list)
        # Do not have both fields at the same time
        if (healthcare_platform_id and healthcare_platform_name) or (
            not healthcare_platform_id and not healthcare_platform_name
        ):
            raise serializers.ValidationError(
                'only healthcare_platform_id or healthcare_platform_name is allowed'
            )

        # if user can't add new school -> must pass 'id'
        if not adding_enable and not healthcare_platform_id:
            raise serializers.ValidationError('healthcare_platform_id is required')

        # CREATE: healthcare_platform_id must be active and verified
        # UPDATE: only check when healthcare_platform_id need to be changed
        #         different from current_healthcare_platform_id
        current_healthcare_platform_id = self.context.get('current_healthcare_platform_id')
        healthcare_platform_exist = HealthcarePlatform.objects.filter(
            pk=healthcare_platform_id, is_active=True, is_verified=True
        ).exists()
        if (
            healthcare_platform_id
            and (
                not current_healthcare_platform_id
                or healthcare_platform_id != current_healthcare_platform_id
            )
            and not healthcare_platform_exist
        ):
            raise serializers.ValidationError(
                'healthcare_platform_id={} is not found'.format(healthcare_platform_id)
            )

        new_healthcare_platform_exist = HealthcarePlatform.objects.filter(
            name__iexact=healthcare_platform_name, is_active=True, is_verified=True
        ).exists()
        if healthcare_platform_name and new_healthcare_platform_exist:
            raise serializers.ValidationError(
                'healthcare_platform_name={} is exists. You must select from list'.format(
                    healthcare_platform_name
                )
            )

        if data['bank']:  # reuse in update. When updating, it's optional
            bank_code = data['bank']['code']
            bank = Bank.objects.filter(xfers_bank_code=bank_code, is_active=True).last()
            if not bank:
                raise serializers.ValidationError('bank_code={} is not found'.format(bank_code))
            data['bank_obj'] = bank

            # recheck data with previous step (/verify-bank-account) by validate_id
            validated_id = data['bank']['validated_id']
            bank_name_validation_log = BankNameValidationLog.objects.filter(
                validation_id=validated_id,
                validation_status=NameBankValidationStatus.SUCCESS,
                method=NameBankValidationVendors.XFERS,
                application=self.context['application'],
            ).last()
            if not bank_name_validation_log:
                raise serializers.ValidationError(
                    'bank_validated_id={} is not found'.format(validated_id)
                )
            data['bank_name_validation_log_obj'] = bank_name_validation_log

        return data


class DeleteHealthcareUserOutputSerializer(serializers.Serializer):
    message = serializers.CharField()


class HealthcareUserUpdateSerializer(CreateHealthcareUserSerializer):
    bank = CreateHealthcareUserBankSerializer(required=False, default=None)


class CreateHealthcareUpdateReponseSerializer(serializers.Serializer):
    healthcare_user_id = serializers.IntegerField()
    bank_account_destination_id = serializers.IntegerField()

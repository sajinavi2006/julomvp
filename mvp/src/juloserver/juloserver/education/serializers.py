from rest_framework import serializers

from juloserver.disbursement.constants import NameBankValidationStatus, NameBankValidationVendors
from juloserver.disbursement.models import BankNameValidationLog
from juloserver.education.models import School, StudentRegister
from juloserver.education.services.views_related import is_allow_add_new_school
from juloserver.julo.models import Bank


class CreateStudentRegisterSchoolSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, default=None)
    name = serializers.CharField(required=False, allow_blank=False, default=None)


class CreateStudentRegisterBankSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, allow_blank=False)
    validated_id = serializers.CharField(required=True, allow_blank=False)


class CreateStudentRegisterSerializer(serializers.Serializer):
    school = CreateStudentRegisterSchoolSerializer()
    bank = CreateStudentRegisterBankSerializer()
    name = serializers.CharField(required=True, max_length=200, allow_blank=False)
    note = serializers.CharField(required=False, max_length=100, allow_blank=True, default='')

    def validate(self, data):
        adding_enable = is_allow_add_new_school()
        school_id = data['school']['id']
        school_name = data['school']['name']

        # Check only 'name' in 'school' (want to add new one) or only 'id' (select from list)
        # Do not have both fields at the same time
        if (school_id and school_name) or (not school_id and not school_name):
            raise serializers.ValidationError('only school_id or school_name is allowed')

        # if user can't add new school -> must pass 'id'
        if not adding_enable and not school_id:
            raise serializers.ValidationError('school_id is required')

        # CREATE: school_id must be active and verified
        # UPDATE: only check when school_id need to be changed is different from current_school_id
        if (
            school_id
            and (
                not self.context.get('current_school_id')  # CREATE
                or school_id != self.context.get('current_school_id')  # UPDATE with other school id
            )
            and not School.objects.filter(pk=school_id, is_active=True, is_verified=True).exists()
        ):
            raise serializers.ValidationError('school_id={} is not found'.format(school_id))

        if (
            school_name
            and School.objects.filter(
                name__iexact=school_name, is_active=True, is_verified=True
            ).exists()
        ):
            raise serializers.ValidationError(
                'school_name={} is exists. You must select from list'.format(school_name)
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
            ).first()
            if not bank_name_validation_log:
                raise serializers.ValidationError(
                    'bank_validated_id={} is not found'.format(validated_id)
                )
            data['bank_name_validation_log_obj'] = bank_name_validation_log

        return data


class UpdateStudentRegisterSerializer(CreateStudentRegisterSerializer):
    bank = CreateStudentRegisterBankSerializer(required=False, default=None)


class UpdateStudentRegisterPathParamSerializer(serializers.Serializer):
    student_register_id = serializers.IntegerField(required=True)

    def validate(self, data):
        student_register_id = data['student_register_id']
        student_register = StudentRegister.objects.get_or_none(
            id=student_register_id, account=self.context['account'], is_deleted=False
        )
        if not student_register:
            raise serializers.ValidationError(
                'student_register_id={} is not found'.format(student_register_id)
            )

        return student_register


class CreateStudentRegisterReponseSerializer(serializers.Serializer):
    student_register_id = serializers.IntegerField()
    bank_account_destination_id = serializers.IntegerField()


class SchoolResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    city = serializers.CharField(allow_blank=True)


class BankResponseSerializer(serializers.Serializer):
    bank_account_destination_id = serializers.IntegerField()
    code = serializers.CharField()
    logo = serializers.URLField(allow_null=True)
    name = serializers.CharField()
    account_number = serializers.CharField()
    account_name = serializers.CharField()


class StudentRegisterReponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    school = SchoolResponseSerializer()
    bank = BankResponseSerializer()
    name = serializers.CharField()
    note = serializers.CharField(allow_blank=True)


class StudentRegisterListReponseSerializer(serializers.Serializer):
    student = StudentRegisterReponseSerializer(many=True)


class SchoolUploadSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    city = serializers.CharField(required=True)


class SchoolSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=True)
    name = serializers.CharField(required=True)


class SchoolListReponseSerializer(serializers.Serializer):
    adding_enable = serializers.BooleanField()
    list = SchoolSerializer(many=True)


class EducationFAQSerializer(serializers.Serializer):
    type = serializers.CharField(required=True)
    title = serializers.CharField(required=True)
    content = serializers.CharField(required=True)
    btn_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    url = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class DeleteStudentRegisterSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=True)

    def validate(self, data):
        student_register_id = data['id']
        student_register = StudentRegister.objects.get_or_none(
            id=student_register_id, account=self.context['account'], is_deleted=False
        )
        if not student_register:
            raise serializers.ValidationError('id={} is not found'.format(student_register_id))
        data['student_register_obj'] = student_register

        return data


class DeleteStudentRegisterReponseSerializer(serializers.Serializer):
    message = serializers.CharField()

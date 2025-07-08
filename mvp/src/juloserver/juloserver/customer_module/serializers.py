import logging
import os
from datetime import datetime, time, timedelta
from math import ceil
from typing import Optional
from uuid import UUID

from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import transaction
from django.utils import timezone
from loan_app.constants import ImageUploadType
from rest_framework import serializers

from juloserver.account.constants import AccountLockReason
from juloserver.account.models import AccountStatusHistory
from juloserver.apiv2.utils import custom_error_messages_for_required
from juloserver.application_form.serializers.application_serializer import (
    ApplicationValidator,
)
from juloserver.customer_module.constants import (
    ADJUST_AUTO_APPROVE_DATE_RELEASE,
    DELETION_REQUEST_AUTO_APPROVE_DAY_LIMIT,
    AccountDeletionRequestStatuses,
    CustomerDataChangeRequestConst,
    CustomerGeolocationConsts,
    CXDocumentType,
    ExperimentSettingSource,
    InAppAccountDeletionMessagesConst,
)
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    BankAccountDestination,
    ConsentWithdrawalRequest,
    CXDocument,
)
from juloserver.customer_module.services.customer_related import (
    CustomerDataChangeRequestNotification,
    is_consent_withdrawal_allowed,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_pending_loan_amount,
)
from juloserver.fraud_security.constants import DeviceConst
from juloserver.julo.models import (
    Application,
    Bank,
    CustomerFieldChange,
    CustomerRemoval,
    Image,
    ascii_validator,
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
)
from juloserver.julo.tasks import upload_image
from juloserver.julo.utils import (
    display_rupiah,
    execute_after_transaction_safely,
)
from juloserver.julocore.validators import (
    FileExtensionValidator,
    FileSizeValidator,
    get_available_image_extensions,
)
from juloserver.loyalty.models import PointHistory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.pin.services import validate_device

logger = logging.getLogger(__name__)


class BankAccountVerificationSerializer(serializers.Serializer):
    bank_code = serializers.CharField(required=True)
    account_number = serializers.RegexField(
        r'^\d{1,20}$',
        required=True,
        error_messages=custom_error_messages_for_required("No. rekening / VA"),
    )
    category_id = serializers.IntegerField(required=True)
    description = serializers.CharField()
    customer_id = serializers.IntegerField(required=True)


class BankAccountDestinationSerializer(BankAccountVerificationSerializer):
    name_in_bank = serializers.CharField(required=True)
    validated_id = serializers.CharField(required=True)
    reason = serializers.CharField(required=True)


class LoanCalculationSerializer(serializers.Serializer):
    loan_amount_request = serializers.IntegerField(required=True)
    customer_id = serializers.IntegerField(required=True)
    self_bank_account = serializers.BooleanField(required=True)


class ChangeCurrentEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)

        if internal_value.get('email'):
            internal_value['email'] = internal_value['email'].strip().lower()

        return internal_value


class ChangeCurrentEmailV3Serializer(ChangeCurrentEmailSerializer):
    pin_validation_token = serializers.CharField(required=True)


class EcommerceBankAccountDestinationSerializer(BankAccountDestinationSerializer):
    ecommerce_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    description = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    category_id = serializers.IntegerField(required=False, default=None)


class EcommerceBankAccountVerificationSerializer(BankAccountVerificationSerializer):
    ecommerce_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    description = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    category_id = serializers.IntegerField(required=False, default=None)
    is_forbid_all_j1_and_turbo_users_bank_account = serializers.BooleanField(
        required=False, default=False
    )


class GoogleAnalyticsInstanceDataSerializer(serializers.Serializer):
    app_instance_id = serializers.CharField(required=True)


class CustomerDeviceSerializer(serializers.Serializer):
    gcm_reg_id = serializers.CharField(required=True)
    android_id = serializers.CharField(required=True, allow_null=True)
    imei = serializers.CharField(required=False, allow_blank=True)
    device_model_name = serializers.CharField(required=False, allow_blank=True)
    julo_device_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def update(self, customer, validated_data):
        device, _ = validate_device(
            gcm_reg_id=validated_data.get('gcm_reg_id'),
            customer=customer,
            imei=validated_data.get('imei'),
            android_id=validated_data.get('android_id'),
            device_model_name=validated_data.get('device_model_name'),
            julo_device_id=validated_data.get(DeviceConst.JULO_DEVICE_ID),
        )
        return customer


class MessageSerializer(serializers.Serializer):
    title = serializers.CharField(required=True)
    body = serializers.CharField(required=True)


class LimitTimerSerializer(serializers.Serializer):
    days_after_190 = serializers.IntegerField(required=True)
    limit_utilization_rate = serializers.IntegerField(required=True)
    information = MessageSerializer(required=True)
    countdown = serializers.IntegerField(required=True)
    repeat_time = serializers.IntegerField(required=True)
    pop_up_message = MessageSerializer(required=True)


class CustomerRemovalSerializer(serializers.ModelSerializer):
    customer_id = serializers.IntegerField()
    application_id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    nik = serializers.ReadOnlyField(source='customer.get_nik')
    added_by = serializers.CharField()
    deleted_date = serializers.DateTimeField(source='udate')
    email = serializers.ReadOnlyField(source='customer.get_email')
    phone_number = serializers.ReadOnlyField(source='customer.get_phone')

    class Meta:
        model = CustomerRemoval
        fields = (
            'customer_id',
            'application_id',
            'user_id',
            'reason',
            'added_by',
            'nik',
            'email',
            'phone_number',
            'deleted_date',
        )


class SearchCustomerSerializer(serializers.Serializer):
    app_or_customer_id = serializers.IntegerField()


class DeleteCustomerSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    reason = serializers.CharField()


class BankAccountDestinationInfoSerializer(serializers.ModelSerializer):
    bank_account_destination_id = serializers.IntegerField(source='id')
    bank_name = serializers.CharField(source='bank.bank_name_frontend')
    bank_logo = serializers.CharField(source='bank.bank_logo')
    category = serializers.CharField(source='bank_account_category.category')
    category_id = serializers.CharField(source='bank_account_category_id')
    display_label = serializers.CharField(source='bank_account_category.display_label')
    name = serializers.CharField(source='name_bank_validation.name_in_bank')

    class Meta:
        model = BankAccountDestination
        fields = (
            'bank_account_destination_id',
            'bank_name',
            'bank_logo',
            'category',
            'category_id',
            'description',
            'account_number',
            'display_label',
            'name',
        )
        read_only_fields = (
            'bank_account_destination_id',
            'bank_name',
            'bank_logo',
            'category',
            'category_id',
            'description',
            'account_number',
            'display_label',
            'name',
        )


class ListBankNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = (
            'id',
            'bank_name',
        )


class UpdateCustomerActionSerializer(serializers.Serializer):
    action = serializers.CharField()
    is_completed = serializers.BooleanField()


class CustomerAppsflyerSerializer(serializers.Serializer):
    appsflyer_device_id = serializers.CharField(required=False)
    appsflyer_customer_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)


class CustomerDeleteUpdatedDataSerializer(serializers.Serializer):
    nik = serializers.IntegerField(required=False)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False)
    customer_id = serializers.IntegerField(required=True)

    def validate(self, data):
        if not any(data.get(field) for field in ['email', 'phone', 'nik']):
            raise serializers.ValidationError('Silahkan periksa input kembali')

        return data


class RequestAccountDeletionSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    detail_reason = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False
    )
    survey_submission_uid = serializers.CharField(
        required=False,
        error_messages={"blank": InAppAccountDeletionMessagesConst.SURVEY_MUST_BE_FILLED},
    )

    def validate_survey_submission_uid(self, value):
        try:
            UUID(str(value), version=4)
        except ValueError:
            # If it's a value error, then the string
            # is not a valid hex code for a UUID.
            raise serializers.ValidationError(
                InAppAccountDeletionMessagesConst.SURVEY_MUST_BE_FILLED
            )

        return value


class AccountDeletionInAppSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    application_id = serializers.ReadOnlyField(source="customer.last_application_id")
    nik = serializers.ReadOnlyField(source="customer.get_nik")
    phone = serializers.ReadOnlyField(source="customer.get_phone")
    email = serializers.ReadOnlyField(source="customer.get_email")
    active_loan = serializers.SerializerMethodField()
    account_status = serializers.SerializerMethodField()
    request_date = serializers.ReadOnlyField(source="cdate")
    reason = serializers.CharField()
    detail_reason = serializers.CharField()
    show_approve_button = serializers.SerializerMethodField()
    show_reject_button = serializers.SerializerMethodField()
    auto_deletion_date = serializers.SerializerMethodField()

    def get_account_status(self, obj):
        if not obj.customer:
            return None
        account = obj.customer.account
        if account:
            old_status = (
                AccountStatusHistory.objects.filter(
                    account=account, status_new=JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW
                )
                .values('status_old')
                .last()
            )
            if old_status:
                return old_status.get('status_old')
        return None

    def get_active_loan(self, obj):
        if not obj.customer:
            return None

        if not obj.customer.account:
            return None

        return get_pending_loan_amount(obj.customer.account)

    def get_show_approve_button(self, obj):
        today = timezone.localtime(timezone.now())
        start_date = today - timedelta(days=30)
        end_date = today - timedelta(days=10)
        pending_loan = get_pending_loan_amount(obj.customer.account) > 0
        account_deletion = AccountDeletionRequest.objects.filter(
            customer=obj.customer,
            request_status=AccountDeletionRequestStatuses.PENDING,
            cdate__date__range=(start_date, end_date),
        ).exists()
        return not pending_loan and account_deletion

    def get_show_reject_button(self, obj):
        today = timezone.localtime(timezone.now())
        start_date = today - timedelta(days=30)
        end_date = today - timedelta(days=10)
        account_deletion = AccountDeletionRequest.objects.filter(
            customer=obj.customer,
            request_status=AccountDeletionRequestStatuses.PENDING,
            cdate__date__range=(start_date, end_date),
        ).exists()
        return account_deletion

    def get_auto_deletion_date(self, obj):
        # Return time at 9 (our scheduler runs at 9AM everyday)

        if obj.cdate <= timezone.make_aware(
            ADJUST_AUTO_APPROVE_DATE_RELEASE, timezone.get_default_timezone()
        ):
            return datetime.combine(obj.cdate + timedelta(days=30), time(hour=9))

        return datetime.combine(
            obj.cdate + timedelta(days=DELETION_REQUEST_AUTO_APPROVE_DAY_LIMIT),
            time(hour=9),
        )


class UpdateStatusOfAccountDeletionRequestSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(required=True)
    status = serializers.CharField(required=True)
    reason = serializers.CharField(required=True)

    def validate_customer_id(self, customer_id):
        qs = AccountDeletionRequest.objects.filter(
            customer_id=customer_id, request_status=AccountDeletionRequestStatuses.PENDING
        ).exists()
        if not qs:
            raise serializers.ValidationError('Silakan periksa input kembali')
        return customer_id

    def validate_status(self, status):
        if status not in (
            AccountDeletionRequestStatuses.APPROVED,
            AccountDeletionRequestStatuses.REJECTED,
        ):
            raise serializers.ValidationError('Silakan periksa input kembali')
        return status


class AccountDeletionInAppHistorySerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    application_id = serializers.ReadOnlyField(source="customer.last_application_id")
    agent = serializers.CharField()
    nik = serializers.ReadOnlyField(source="customer.get_nik")
    phone = serializers.ReadOnlyField(source="customer.get_phone")
    email = serializers.ReadOnlyField(source="customer.get_email")
    request_date = serializers.ReadOnlyField(source="cdate")
    reason = serializers.CharField()
    detail_reason = serializers.CharField()
    verdict_date = serializers.ReadOnlyField(source="udate")
    verdict_reason = serializers.CharField()
    status = serializers.SerializerMethodField()

    def get_status(self, obj):
        if obj.request_status == AccountDeletionRequestStatuses.SUCCESS and obj.verdict_date:
            return AccountDeletionRequestStatuses.APPROVED

        if obj.request_status == AccountDeletionRequestStatuses.SUCCESS and not (obj.verdict_date):
            return AccountDeletionRequestStatuses.AUTO_APPROVED

        if obj.request_status == AccountDeletionRequestStatuses.REVERTED:
            return AccountDeletionRequestStatuses.CANCELLED

        return obj.request_status


class CustomerDataChangeRequestBaseSerializer(ApplicationValidator, serializers.Serializer):
    """
    Base Serializer for customer data change request for CRM and JULO App submission
    """

    allowed_string = RegexValidator(
        regex=r'^[a-zA-Z0-9.,\s\-@/()]*$',
        message=CustomerDataChangeRequestConst.ErrorMessages.TextField,
    )

    address_street_num = serializers.CharField(
        required=True, source='address.detail', validators=[allowed_string]
    )
    address_provinsi = serializers.CharField(
        required=True, source='address.provinsi', validators=[allowed_string]
    )
    address_kabupaten = serializers.CharField(
        required=True, source='address.kabupaten', validators=[allowed_string]
    )
    address_kecamatan = serializers.CharField(
        required=True, source='address.kecamatan', validators=[allowed_string]
    )
    address_kelurahan = serializers.CharField(
        required=True, source='address.kelurahan', validators=[allowed_string]
    )
    address_kodepos = serializers.CharField(
        max_length=5,
        validators=[
            RegexValidator(regex='^[0-9]{5}$', message='Kode pos has to be 5 numeric digits'),
            allowed_string,
        ],
        required=True,
        source='address.kodepos',
    )
    job_type = serializers.ChoiceField(choices=Application.JOB_TYPE_CHOICES, required=True)
    job_industry = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=100,
        validators=[allowed_string, ascii_validator],
    )
    job_description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=100,
        validators=[allowed_string, ascii_validator],
    )
    company_name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=100,
        validators=[allowed_string, ascii_validator],
    )
    company_phone_number = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[allowed_string],
    )
    payday = serializers.IntegerField(
        required=False, validators=[MinValueValidator(0), MaxValueValidator(31)], allow_null=True
    )
    monthly_income = serializers.IntegerField(min_value=0, required=True)
    monthly_expenses = serializers.IntegerField(min_value=0, required=True)
    monthly_housing_cost = serializers.IntegerField(min_value=0, required=True)
    total_current_debt = serializers.IntegerField(min_value=0, required=True)
    last_education = serializers.ChoiceField(
        default=None,
        choices=Application.LAST_EDUCATION_CHOICES,
    )

    def validate(self, data):
        data = super(CustomerDataChangeRequestBaseSerializer, self).validate(data)
        data = self._validate_no_change(data)
        data = self._validate_job_data(data)
        return data

    def _validate_no_change(self, data):
        previous_change_request = self.context.get('previous_change_request')
        if not previous_change_request:
            return data

        previous_change_serializer = CustomerDataChangeRequestBaseSerializer(
            previous_change_request
        )
        previous_data = previous_change_serializer.data
        if all(previous_data.get(field) == self.initial_data.get(field) for field in previous_data):
            raise serializers.ValidationError('No data change')
        return data

    def get_customer_data_change_request_handler(self):
        from juloserver.customer_module.services.customer_related import (
            CustomerDataChangeRequestHandler,
        )

        if 'change_request_handler' not in self.context:
            return None

        if self.context.get('change_request_handler'):
            return self.context.get('change_request_handler')

        return CustomerDataChangeRequestHandler(self.validated_data.get('customer_id'))


class CustomerDataChangeRequestCRMSerializer(CustomerDataChangeRequestBaseSerializer):
    allowed_image_extensions = get_available_image_extensions() + ['pdf']
    upload_file_error_message = (
        'Pastikan file yang diupload memiliki format png, jpg, atau pdf dan tidak melebihi 5MB'
    )
    max_upload_file_size = 5 * 1024 * 1024  # 5 MB

    customer_id = serializers.IntegerField(required=True)
    application_id = serializers.IntegerField(required=True)
    address_latitude = serializers.FloatField(source='address.latitude', required=False)
    address_longitude = serializers.FloatField(source='address.longitude', required=False)
    address_transfer_certificate_image = serializers.FileField(
        required=False,
        validators=[
            FileSizeValidator(
                max_size=max_upload_file_size,
                message=upload_file_error_message,
            ),
            FileExtensionValidator(
                allowed_extensions=allowed_image_extensions,
                message=upload_file_error_message,
            ),
        ],
    )
    company_proof_image = serializers.FileField(
        required=False,
        validators=[
            FileSizeValidator(
                max_size=max_upload_file_size,
                message=upload_file_error_message,
            ),
            FileExtensionValidator(
                allowed_extensions=allowed_image_extensions,
                message=upload_file_error_message,
            ),
        ],
        error_messages={
            'invalid_file_size': upload_file_error_message,
        },
    )
    paystub_image = serializers.FileField(
        required=False,
        validators=[
            FileSizeValidator(
                max_size=max_upload_file_size,
                message=upload_file_error_message,
            ),
            FileExtensionValidator(
                allowed_extensions=allowed_image_extensions,
                message=upload_file_error_message,
            ),
        ],
    )
    last_education = serializers.ChoiceField(
        required=True,
        choices=Application.LAST_EDUCATION_CHOICES,
        error_messages={'invalid_choice': 'This field must be valid choice and can not be blank.'},
    )

    def validate_application_id(self, application_id):
        handler = self.get_customer_data_change_request_handler()
        latest_application = handler.last_application()
        if application_id != latest_application.id:
            raise serializers.ValidationError('Application ID is not the latest')

        if latest_application.status not in ApplicationStatusCodes.active_account():
            raise serializers.ValidationError('Application is not active')

        return application_id

    def save(self, **kwargs):
        handler = self.get_customer_data_change_request_handler()
        data = self.validated_data.copy()
        data.update(
            address_transfer_certificate_image_id=self._save_image(
                'address_transfer_certificate_image',
            ),
            company_proof_image_id=self._save_image('company_proof_image'),
            paystub_image_id=self._save_image('paystub_image'),
        )
        return handler.create_change_request_no_validation(data, **kwargs)

    @transaction.atomic
    def _save_image(self, image_field_name: str) -> Optional[Image]:
        image_file = self.validated_data.get(image_field_name)
        if not image_file:
            return None

        image = Image.objects.create(
            image_type=image_field_name.replace('_image', ''),
            image_source=self.validated_data.get('customer_id'),
        )
        image.image.save(image.full_image_name(image_file.name), image_file)
        execute_after_transaction_safely(lambda image_id=image.id: upload_image.delay(image_id))
        return image.id


class CustomerDataChangeRequestSerializer(CustomerDataChangeRequestBaseSerializer):
    """
    Serializer for customer data change request from JULO App.
    """

    alpha_only = RegexValidator(
        regex=r'^[a-zA-Z ]*$',  # Allows letters and spaces
        message=CustomerDataChangeRequestConst.ErrorMessages.AlphaField,
    )

    allowed_string = RegexValidator(
        regex=r'^[a-zA-Z0-9.,\s\-@/()]*$',
        message=CustomerDataChangeRequestConst.ErrorMessages.TextField,
    )
    app_version_validator = RegexValidator(
        r'^[0-9]+\.[0-9]+(\.[0-9]+)?([-+][a-zA-Z])?$',
        CustomerDataChangeRequestConst.ErrorMessages.TextField,
    )

    address_latitude = serializers.FloatField(source='address.latitude', required=True)
    address_longitude = serializers.FloatField(source='address.longitude', required=True)
    address_transfer_certificate_image_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
    )
    address_transfer_certificate_image_url = serializers.CharField(
        source='address_transfer_certificate_image.image_url',
        read_only=True,
    )
    company_proof_image_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
    )
    company_proof_image_url = serializers.CharField(
        source='company_proof_image.image_url',
        read_only=True,
    )
    paystub_image_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
    )
    paystub_image_url = serializers.CharField(
        source='paystub_image.image_url',
        read_only=True,
    )
    latitude = serializers.FloatField(
        required=False,
        allow_null=True,
        write_only=True,
    )
    longitude = serializers.FloatField(
        required=False,
        allow_null=True,
        write_only=True,
    )
    android_id = serializers.CharField(
        required=False,
        allow_null=True,
        write_only=True,
        validators=[allowed_string],
    )
    app_version = serializers.CharField(
        required=False,
        allow_null=True,
        write_only=True,
        validators=[app_version_validator],
    )
    last_education = serializers.ChoiceField(
        required=True,
        allow_blank=True,
        allow_null=True,
        choices=Application.LAST_EDUCATION_CHOICES,
        error_messages={'invalid_choice': 'Pendidikan terakhir tidak valid.'},
    )
    payday_change_reason = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=100,
        validators=[alpha_only],
    )
    payday_change_proof_image_id = serializers.IntegerField(
        required=False,
        write_only=True,
        allow_null=True,
    )
    payday_change_proof_image_url = serializers.SerializerMethodField(read_only=True)

    def validate(self, data):
        data = super(CustomerDataChangeRequestSerializer, self).validate(data)
        data = self._validate_required_paystub_image(data)
        return data

    def get_payday_change_proof_image_url(self, obj):
        document = CXDocument.objects.filter(id=obj.payday_change_proof_image_id).first()
        return getattr(document, 'document_url', "") if document else ""

    def monthly_income_threshold(self):
        """
        Returns the monthly income threshold for the payslip required image.
        Returns:
            int: monthly income threshold
        """
        previous_change_request = self.context.get('previous_change_request')
        if not previous_change_request:
            return 0

        monthly_income_previous = (
            previous_change_request.monthly_income if previous_change_request.monthly_income else 0
        )
        payslip_income_multiplier = self.context.get('payslip_income_multiplier', 1.0)
        monthly_income_threshold = ceil(monthly_income_previous * payslip_income_multiplier)
        return monthly_income_threshold

    def _validate_image_id(self, image_type, value):
        if not value or 'customer_id' not in self.context:
            return value

        try:
            Image.objects.get(
                id=value,
                image_source=self.context['customer_id'],
                image_type=image_type,
            )
        except Image.DoesNotExist:
            raise serializers.ValidationError('{} is required'.format(image_type))

        return value

    def _validate_required_paystub_image(self, data):
        previous_change_request = self.context.get('previous_change_request')
        if not previous_change_request or data.get('paystub_image_id') is not None:
            return data

        errors = {}

        monthly_income_input = data.get('monthly_income')
        monthly_income_previous = (
            previous_change_request.monthly_income if previous_change_request.monthly_income else 0
        )
        monthly_income_threshold = self.monthly_income_threshold()
        if (
            monthly_income_previous != monthly_income_input
            and monthly_income_input >= monthly_income_threshold
        ):
            errors['paystub_image_id'] = ['is required']

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def validate_address_transfer_certificate_image_id(self, value):
        return self._validate_image_id(ImageUploadType.ADDRESS_TRANSFER_CERTIFICATE, value)

    def validate_company_proof_image_id(self, value):
        return self._validate_image_id(ImageUploadType.COMPANY_PROOF, value)

    def validate_paystub_image_id(self, value):
        return self._validate_image_id(ImageUploadType.PAYSTUB, value)

    def validate_last_education(self, last_education):
        version_code = self.context.get('version_code', 0)
        handler = self.get_customer_data_change_request_handler()
        supported_app_version_code = 0
        if handler:
            supported_app_version_code = handler.setting.supported_app_version_code
        if version_code > supported_app_version_code and not last_education:
            raise serializers.ValidationError("Pendidikan terakhir wajib diisi.")

        return last_education


class CustomerDataPaydayChangeRequestSerializer(serializers.Serializer):
    """
    Serializer for customer payday change request from JULO App.
    """

    alpha_only = RegexValidator(
        regex=r'^[a-zA-Z ]*$',  # Allows letters and spaces
        message=CustomerDataChangeRequestConst.ErrorMessages.AlphaField,
    )

    payday = serializers.IntegerField(
        required=True,
        validators=[MinValueValidator(0), MaxValueValidator(31)],
    )
    payday_change_reason = serializers.CharField(
        required=True,
        max_length=100,
        validators=[alpha_only],
    )
    payday_change_proof_image_id = serializers.IntegerField(required=True)

    def validate_payday_change_proof_image_id(self, value):
        customer = self.context.get('customer')
        document_obj = CXDocument.objects.filter(id=value).first()
        if not document_obj:
            raise serializers.ValidationError('Document is required')
        if customer and customer.id != document_obj.document_source:
            raise serializers.ValidationError('Document is not allowed')

        return value


class CustomerDataChangeRequestCRMDetailSerializer(serializers.Serializer):
    """
    Serializer used for CRM detail view. This serializer isnot used for saving data.
    """

    address_street_num = serializers.CharField(source='address.detail')
    address_provinsi = serializers.CharField(source='address.provinsi')
    address_kabupaten = serializers.CharField(source='address.kabupaten')
    address_kecamatan = serializers.CharField(source='address.kecamatan')
    address_kelurahan = serializers.CharField(source='address.kelurahan')
    address_kodepos = serializers.CharField(source='address.kodepos')
    job_type = serializers.CharField()
    job_industry = serializers.CharField()
    job_description = serializers.CharField()
    company_name = serializers.CharField()
    company_phone_number = serializers.CharField()
    payday = serializers.IntegerField()
    payday_change_reason = serializers.SerializerMethodField()
    payday_change_proof_image_url = serializers.SerializerMethodField()
    monthly_income = serializers.IntegerField()
    monthly_expenses = serializers.IntegerField()
    monthly_housing_cost = serializers.IntegerField()
    total_current_debt = serializers.IntegerField()
    address_transfer_certificate_image_url = serializers.CharField(
        source='address_transfer_certificate_image.image_url',
    )
    company_proof_image_url = serializers.CharField(
        source='company_proof_image.image_url',
    )
    paystub_image_url = serializers.CharField(
        source='paystub_image.image_url',
    )
    last_education = serializers.ChoiceField(
        choices=Application.LAST_EDUCATION_CHOICES,
    )

    def get_payday_change_reason(self, obj):
        return obj.payday_change_reason or ""

    def get_payday_change_proof_image_url(self, obj):
        document = CXDocument.objects.filter(id=obj.payday_change_proof_image_id).first()
        return getattr(document, 'document_url', "") if document else ""


class CustomerDataChangeRequestApprovalSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=CustomerDataChangeRequestConst.SubmissionStatus.approval_choices(),
        required=True,
        write_only=True,
    )
    approval_note = serializers.CharField(required=True, write_only=True)

    def validate_status(self, value):
        if (
            self.instance
            and self.instance.status != CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED
        ):
            raise serializers.ValidationError('Status is already {}'.format(self.instance.status))
        return value

    def update(self, instance, validated_data):
        if self.context.get('user'):
            validated_data['approval_user_id'] = self.context.get('user').id

        instance.update_safely(**validated_data)
        notification = CustomerDataChangeRequestNotification(instance)
        notification.send_notification()
        return instance


class CustomerDataChangeRequestListSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    application_id = serializers.IntegerField(read_only=True)
    status = serializers.CharField()
    fullname = serializers.ReadOnlyField(source='customer.get_fullname')
    source = serializers.CharField(read_only=True)
    approval_note = serializers.CharField()
    cdate = serializers.DateTimeField(read_only=True)
    udate = serializers.DateTimeField(read_only=True)


class CustomerDataChangeRequestCompareSerializer(serializers.Serializer):
    """
    This is serializer to convert CustomerDataChangeRequest object to dict
    for comparing with other objects and for UI purpose.
    """

    address = serializers.SerializerMethodField()
    job_type = serializers.CharField()
    job_industry = serializers.CharField()
    job_description = serializers.CharField()
    company_name = serializers.CharField()
    company_phone_number = serializers.CharField()
    payday = serializers.IntegerField()
    monthly_income = serializers.IntegerField()
    monthly_expenses = serializers.IntegerField()
    monthly_housing_cost = serializers.IntegerField()
    total_current_debt = serializers.IntegerField()

    def get_address(self, obj):
        return obj.address.full_address if obj.address else None

    def _format_rupiah(self, value):
        return display_rupiah(value) if value else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['monthly_income'] = self._format_rupiah(data.get('monthly_income'))
        data['monthly_expenses'] = self._format_rupiah(data.get('monthly_expenses'))
        data['monthly_housing_cost'] = self._format_rupiah(data.get('monthly_housing_cost'))
        data['total_current_debt'] = self._format_rupiah(data.get('total_current_debt'))
        return data


class ProductLockInfoSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=TransactionMethodCode.choices())
    reason_locked = serializers.CharField(required=False)

    def validate_reason_locked(self, value):
        valid_choices = dict(AccountLockReason.get_choices())
        if value and value not in valid_choices:
            raise serializers.ValidationError(
                "Invalid reason_locked: {}. Valid choices: {}".format(
                    value, list(valid_choices.keys())
                )
            )

        return value


class SubmitProductLockedSerializer(serializers.Serializer):
    product_locked_info_old = ProductLockInfoSerializer(many=True)
    product_locked_info_new = ProductLockInfoSerializer(many=True)


class SimpleCustomerRemoval(serializers.ModelSerializer):
    deletion_date = serializers.ReadOnlyField(source="cdate", default="")
    deleted_phone = serializers.ReadOnlyField(source="customer.phone", default="")
    deleted_email = serializers.ReadOnlyField(source="customer.email", default="")
    deleted_by = serializers.ReadOnlyField(source="added_by.username", default="")
    deleted_via = serializers.SerializerMethodField()
    reason = serializers.ReadOnlyField(default="")

    class Meta:
        model = CustomerRemoval
        fields = (
            "deletion_date",
            "deleted_phone",
            "deleted_email",
            "deleted_by",
            "deleted_via",
            "reason",
        )

    def get_deleted_via(self, obj):
        if not obj:
            return ""

        if hasattr(obj, "account_deletion_requests"):
            return "In App"
        return "Manual"


class ConditionalModelField(serializers.Field):
    def __init__(self, target_model, source_field, alternative_source_field=None, **kwargs):
        self._target_model = target_model
        self._source_field = source_field
        self._alternative_source_field = alternative_source_field

        kwargs['source'] = '*'
        kwargs['read_only'] = True

        super().__init__(**kwargs)

    def to_representation(self, value):
        if value is None:
            return self.default

        if value._meta.model.__name__ == self._target_model._meta.model.__name__:
            if value and value._meta.model.__name__ == "CustomerRemoval":
                obj_field_changed = CustomerFieldChange.objects.filter(
                    field_name=self._source_field, customer_id=value.customer_id
                ).last()
                if obj_field_changed:
                    return obj_field_changed.old_value

            return getattr(value, self._source_field) or self.default

        if self._alternative_source_field is not None:
            return getattr(value, self._alternative_source_field) or self.default

        return self.default


class AccountDeletionHistorySerializer(serializers.Serializer):
    registration_date = ConditionalModelField(
        target_model=CustomerRemoval,
        source_field="registered_customer_date",
        alternative_source_field="cdate",
        default="",
    )
    application_id = ConditionalModelField(
        target_model=CustomerRemoval,
        source_field="application_id",
        alternative_source_field="last_application_id",
        default=None,
    )
    customer_id = ConditionalModelField(
        target_model=CustomerRemoval,
        source_field="customer_id",
        alternative_source_field="id",
        default=None,
    )
    registration_phone = ConditionalModelField(
        target_model=CustomerRemoval,
        source_field="phone",
        alternative_source_field="phone",
        default="",
    )
    registration_email = ConditionalModelField(
        target_model=CustomerRemoval,
        source_field="email",
        alternative_source_field="email",
        default="",
    )
    nik = serializers.ReadOnlyField(default="")
    deletion_history = serializers.SerializerMethodField()

    def get_deletion_history(self, obj):
        if not obj or obj._meta.model.__name__ != "CustomerRemoval":
            return {}
        return SimpleCustomerRemoval(obj).data


class ExperimentResultSerializer(serializers.Serializer):

    value = serializers.CharField(required=True)
    hash_value = serializers.CharField(required=True)
    hash_attribute = serializers.CharField(required=True)


class ExperimentSerializer(serializers.Serializer):

    key = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    active = serializers.BooleanField()


class ExperimentDataSerializer(serializers.Serializer):

    experiment = ExperimentSerializer()
    result = ExperimentResultSerializer()
    source = serializers.ChoiceField(
        required=True,
        choices=((ExperimentSettingSource.GROWTHBOOK, ExperimentSettingSource.GROWTHBOOK),),
    )
    experiment_code = serializers.CharField(required=True)


class CustomerGeolocationSerializer(serializers.Serializer):

    latitude = serializers.FloatField(
        required=True,
        error_messages=custom_error_messages_for_required("Invalid request", type="Float"),
    )
    longitude = serializers.FloatField(
        required=True,
        error_messages=custom_error_messages_for_required("Invalid request", type="Float"),
    )
    action_type = serializers.ChoiceField(
        required=True,
        choices=((CustomerGeolocationConsts.LOGIN, CustomerGeolocationConsts.LOGIN),),
    )
    android_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_latitude(self, value):

        if not value:
            raise serializers.ValidationError('Invalid request')
        return value

    def validate_longitude(self, value):

        if not value:
            raise serializers.ValidationError('Invalid request')
        return value


class CustomerPointHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PointHistory
        fields = ('cdate', 'udate', 'id', 'change_reason', 'old_point', 'new_point')


class DocumentUploadSerializer(serializers.Serializer):
    document_source = serializers.CharField(required=True)
    document_file = serializers.FileField(required=True)
    document_type = serializers.CharField(required=True)

    def validate_document_file(self, file):
        name_file, extension = os.path.splitext(file.name.lower())
        allowed_extensions = ['.jpeg', '.png', '.jpg', '.pdf']
        if extension not in allowed_extensions:
            raise serializers.ValidationError('Extension not allowed')

        max_size = 1024 * 1024 * 5  # 5 MB
        if file._size > max_size:
            raise serializers.ValidationError('File is too large. Size should not exceed 5 MB')

        datenow = datetime.now()
        filename = ''

        filename = '{}_{}_{}{}'.format(
            name_file, datenow.strftime("%Y%m%d"), datenow.strftime("%H%M%S"), extension
        )
        file.name = filename
        return file

    def validate_document_type(self, document_type):
        if document_type not in [CXDocumentType.PAYDAY_CHANGE_REQUEST]:
            raise serializers.ValidationError('Document type not allowed')
        return document_type


class SubmitConsentWithdrawalSerializer(serializers.Serializer):
    """
    Serializer for submitting consent withdrawal
    """

    reason = serializers.CharField(
        required=True, error_messages={"required": "Reason is required."}
    )
    detail_reason = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    source = serializers.CharField(
        required=True, error_messages={"required": "Source is required."}
    )


class ConsentWithdrawalCurrentStatusSerializer(serializers.Serializer):
    application_id = serializers.ReadOnlyField(source="last_application_id")
    customer_id = serializers.IntegerField(source='id')
    user_id = serializers.IntegerField(source='user.id')
    nik = serializers.ReadOnlyField(source='get_nik')
    phone_number = serializers.ReadOnlyField(source='get_phone')
    email = serializers.ReadOnlyField(source='get_email')
    active_loan = serializers.SerializerMethodField()
    application_status = serializers.ReadOnlyField(
        source="get_active_or_last_application.status", default=""
    )
    account_status = serializers.IntegerField(source='account.status_id')
    action_status = serializers.SerializerMethodField()

    def get_active_loan(self, obj):
        if not obj.customer:
            return None

        if not obj.account:
            return None

        return get_pending_loan_amount(obj.account)

    def get_action_status(self, obj):
        consent_withdrawal = ConsentWithdrawalRequest.objects.filter(customer_id=obj.id).last()
        if not consent_withdrawal or consent_withdrawal.status in [
            'rejected',
            'cancelled',
            'regranted',
        ]:
            is_allowed, _ = is_consent_withdrawal_allowed(obj)
            if is_allowed:
                return "can_withdraw"
            else:
                return "can_not_withdraw"
        elif consent_withdrawal.status in ['approved', 'auto_approved']:
            return "can_regrant"
        else:
            return "already_requested"


class ConsentWithdrawalHistorySerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    customer_id = serializers.IntegerField()
    user_id = serializers.IntegerField()

    withdrawal_status = serializers.CharField(source='status')
    channel = serializers.SerializerMethodField()
    action_by = serializers.CharField()
    email_requestor = serializers.EmailField(required=False)
    action_date = serializers.SerializerMethodField()

    reason = serializers.CharField(required=False, allow_blank=True)
    detail_reason = serializers.CharField(required=False, allow_blank=True)

    source = serializers.CharField(required=False, write_only=True)

    def get_action_date(self, obj):
        if obj.action_date:
            return obj.action_date.strftime("%d/%m/%Y %H:%M")
        return "-"

    def get_channel(self, obj):
        return obj.get_source_display() if obj.source else "-"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for key, value in data.items():
            if value in [None, "", []]:
                data[key] = "-"
        return data


class CRMSubmitConsentWithdrawalSerializer(SubmitConsentWithdrawalSerializer):
    """
    Serializer for CRM submitting consent withdrawal
    """

    customer_id = serializers.IntegerField(
        required=True, error_messages={"required": "Customer ID is required."}
    )
    email_requestor = serializers.EmailField(
        required=True, error_messages={"required": "Email requestor is required."}
    )


class CRMChangeStatusConsentWithdrawalSerializer(serializers.Serializer):
    """
    Serializer for CRM submitting consent withdrawal
    """

    customer_id = serializers.IntegerField(
        required=True, error_messages={"required": "Customer ID is required."}
    )
    email_requestor = serializers.EmailField(required=False)
    reason = serializers.CharField(required=False)
    source = serializers.CharField(
        required=True, error_messages={"required": "Source is required."}
    )


class ConsentWithdrawalListRequestSerializer(serializers.Serializer):
    # Field from Customer
    application_id = serializers.IntegerField(source='customer.last_application_id')
    customer_id = serializers.IntegerField(source='customer.id')
    nik = serializers.ReadOnlyField(source='customer.get_nik')
    phone_number = serializers.ReadOnlyField(source='customer.get_phone')
    email = serializers.ReadOnlyField(source='customer.get_email')
    active_loan = serializers.SerializerMethodField()
    application_status = serializers.ReadOnlyField(
        source="customer.get_active_or_last_application.status", default=""
    )
    account_status = serializers.IntegerField(source='customer.account.status_id')

    # Field from ConsentWithdrawalRequest
    action_date = serializers.SerializerMethodField()
    reason = serializers.ReadOnlyField(source='withdrawal.reason')
    detail_reason = serializers.ReadOnlyField(source='withdrawal.detail_reason')

    def get_action_date(self, obj):
        action_date = getattr(obj['withdrawal'], 'action_date', None)
        if action_date:
            return action_date.strftime("%d/%m/%Y %H:%M")
        else:
            cdate = getattr(obj['withdrawal'], 'cdate', None)
            if cdate:
                return cdate.strftime("%d/%m/%Y %H:%M")
        return "-"

    def get_active_loan(self, obj):
        customer = obj.get('customer')
        if not customer:
            return None
        account = getattr(customer, 'account', None)
        if not account:
            return None

        return get_pending_loan_amount(account)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for key, value in data.items():
            if value in [None, "", []]:
                data[key] = "-"
        return data

import re
import os
from builtins import object
from rest_framework import serializers
from rest_framework.serializers import ValidationError
from juloserver.julo.models import Loan
from juloserver.julo.models import VoiceRecord
from juloserver.julo.models import Image
from juloserver.customer_module.models import BankAccountDestination
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.apiv2.utils import custom_error_messages_for_required


import logging

from juloserver.loan.services.loan_validate_with_sepulsa_payment_point_inquire import (
    is_valid_price_with_sepulsa_payment_point,
)

logger = logging.getLogger(__name__)


class LoanRequestValidationSerializer(serializers.Serializer):
    loan_amount_request = serializers.IntegerField(required=True)
    account_id = serializers.IntegerField(required=True)
    is_zero_interest = serializers.BooleanField(required=False)
    is_julo_care = serializers.BooleanField(required=False)
    is_dbr = serializers.BooleanField(required=False)
    is_tax = serializers.BooleanField(required=False)

    def validate_loan_amount_request(self, value):
        if value <= 0:
            raise ValidationError('Jumlah pinjaman harus lebih besar dari 0')
        return value

    def validate(self, data):
        """
        Check which campaign is active.
        """
        if data.get('is_zero_interest') and data.get('is_julo_care'):
            raise ValidationError("Multiple campaign active")
        return data


class LoanCalculationSerializer(LoanRequestValidationSerializer):
    self_bank_account = serializers.BooleanField()
    is_payment_point = serializers.NullBooleanField(required=False)
    transaction_type_code = serializers.IntegerField(required=False, default=None)
    # iprice
    iprice_transaction_id = serializers.IntegerField(required=False)
    is_show_saving_amount = serializers.BooleanField(required=False, default=False)
    device_brand = serializers.CharField(required=False)
    device_model = serializers.CharField(required=False)
    os_version = serializers.IntegerField(required=False)


class RenteeLoanRequestSerializer(serializers.Serializer):
    device_id = serializers.IntegerField(required=True)
    account_id = serializers.IntegerField(required=True)


class LoanRequestSerializer(LoanRequestValidationSerializer):
    loan_duration = serializers.IntegerField(required=True)
    bank_account_destination_id = serializers.IntegerField(required=False)
    bank_account_number = serializers.CharField(required=False)
    self_bank_account = serializers.BooleanField()
    loan_purpose = serializers.CharField(required=False)
    mobile_number = serializers.CharField(required=False,
                                          allow_null=True,
                                          allow_blank=True,
                                          default=None)
    customer_number = serializers.CharField(required=False,
                                            allow_null=True,
                                            allow_blank=True,
                                            default=None)
    is_payment_point = serializers.NullBooleanField(default=False, required=False)
    payment_point_product_id = serializers.IntegerField(required=False)
    customer_name = serializers.CharField(required=False, default=None)
    bpjs_times = serializers.IntegerField(required=False, default=None)
    bpjs_number = serializers.CharField(required=False, default=None)
    transaction_type_code = serializers.IntegerField(required=False, default=None)
    qr_id = serializers.IntegerField(required=False, default=None)
    is_suspicious_ip = serializers.NullBooleanField(required=False)
    is_tax = serializers.NullBooleanField(required=False)


class LoanDbrCheckSerializer(serializers.Serializer):
    monthly_installment = serializers.IntegerField(required=True)
    first_monthly_installment = serializers.IntegerField(required=False)
    duration = serializers.IntegerField(required=False)
    transaction_type_code = serializers.IntegerField(required=False, default=None)


class LoanDbrMonthlySalarySerializer(serializers.Serializer):
    transaction_type_code = serializers.IntegerField(required=True)
    self_bank_account = serializers.BooleanField()


class LoanRequestSerializerv3(LoanRequestSerializer):
    # for fraud checking
    is_suspicious_ip = serializers.NullBooleanField(required=False)
    gcm_reg_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("gcm_reg_id")
    )
    android_id = serializers.CharField(
        required=True,
        error_messages=custom_error_messages_for_required("android_id")
    )
    imei = serializers.CharField(required=False)
    # Geolocation params
    latitude = serializers.FloatField(
        required=False,
        error_messages=custom_error_messages_for_required("latitude", type="Float"),
        default=None,
    )
    longitude = serializers.FloatField(
        required=False,
        error_messages=custom_error_messages_for_required("longitude", type="Float"),
        default=None,
    )
    is_web_location_blocked = serializers.BooleanField(required=False, default=False)
    manufacturer = serializers.CharField(required=False)
    model = serializers.CharField(required=False)
    # iprice
    iprice_transaction_id = serializers.IntegerField(required=False)
    juloshop_transaction_xid = serializers.UUIDField(required=False)
    pdam_operator_code = serializers.CharField(required=False)
    total_month_bill = serializers.IntegerField(required=False)
    train_reference_number = serializers.CharField(required=False)
    student_id = serializers.IntegerField(required=False)
    sepulsa_payment_point_inquire_tracking_id = serializers.IntegerField(
        required=False, default=None, allow_null=True
    )
    healthcare_user_id = serializers.IntegerField(required=False)
    device_brand = serializers.CharField(required=False)
    device_model = serializers.CharField(required=False)
    os_version = serializers.IntegerField(required=False)
    # julo_device_id
    julo_device_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    promo_code = serializers.CharField(required=False, max_length=80)

    def validate(self, data):
        loan_duration = data['loan_duration']
        if not 24 >= loan_duration > 0:
            # duration input only 1-24 month
            raise ValidationError('Pilihan tenor tidak ditemukan')

        # The below validate is used for validate price with Sepulsa payment point
        inquire_tracking_id = data.get('sepulsa_payment_point_inquire_tracking_id')
        payment_point_product_id = data.get('payment_point_product_id')
        is_payment_point = data.get('is_payment_point')
        transaction_method_id = data.get('transaction_type_code')
        if is_payment_point and transaction_method_id:
            if not is_valid_price_with_sepulsa_payment_point(
                account=self.context['account'],
                transaction_method_id=transaction_method_id,
                price=data['loan_amount_request'],
                inquire_tracking_id=inquire_tracking_id,
                payment_point_product_id=payment_point_product_id,
            ):
                logger.error(
                    {
                        'module': 'loan',
                        'action': 'invalid_price_with_sepulsa_payment_point_inquire',
                        'account_id': self.context['account'].id,
                        'transaction_method_id': transaction_method_id,
                        'price': data['loan_amount_request'],
                        'sepulsa_payment_point_inquire_tracking_id': inquire_tracking_id,
                        'payment_point_product_id': payment_point_product_id,
                    }
                )

                raise ValidationError('Loan amount request is invalid')

        if (
            # web location is blocked => latitude and longitude must be None
            data['is_web_location_blocked']
            and (data['latitude'] is not None or data['longitude'] is not None)
        ) or (
            # web location is allowed => latitude and longitude must be not None
            not data['is_web_location_blocked']
            and (data['latitude'] is None or data['longitude'] is None)
        ):
            raise ValidationError('Wrong latitude or longitude')

        return data


class BankAccountSerializer(serializers.ModelSerializer):
    bank_name = serializers.SerializerMethodField()
    account_name = serializers.CharField(source='get_name_from_bank_validation')

    class Meta(object):
        model = BankAccountDestination
        fields = ('bank_name', 'account_name', 'account_number')

    def get_bank_name(self, obj):
        if obj.bank_account_category.category.lower() == BankAccountCategoryConst.ECOMMERCE.lower():
            return '{} Virtual Account'.format(obj.bank.bank_name_frontend)
        return obj.bank.bank_name


class LoanDetailsSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Loan
        fields = ('id', 'status', 'loan_amount', 'loan_duration',
                  'interest_rate_monthly', 'installment_amount',
                  'loan_disbursement_amount', 'transaction_method')

    def get_bank_account(self, instance):
        return_val = dict()
        return_val['bank_name'] = instance.bank_account_destination.get_bank_name
        return_val['bank_image'] = None
        return_val['account_name'] = instance.bank_account_destination.\
            get_name_from_bank_validation
        return_val['account_number'] = instance.bank_account_destination.account_number
        return return_val


class VoiceRecordSerializer(serializers.ModelSerializer):
    voice_record_id = serializers.IntegerField(source='id')
    loan_id = serializers.IntegerField(source='loan.id')

    class Meta(object):
        model = VoiceRecord
        fields = ('voice_record_id', 'loan_id', 'status', 'presigned_url')


class CreateManualSignatureSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Image
        exclude = ('url', 'thumbnail_url')


class ManualSignatureSerializer(serializers.ModelSerializer):
    created_date = serializers.DateTimeField(source='cdate')

    class Meta(object):
        model = Image
        fields = ('id', 'created_date', 'image_type',
                  'thumbnail_url_api', 'image_status')


class CreateVoiceRecordSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = VoiceRecord
        exclude = ("tmp_path", )


class LoanDurationSimulationSerializer(serializers.Serializer):
    loan_amount = serializers.IntegerField(required=True)
    self_bank_account = serializers.BooleanField()
    is_payment_point = serializers.NullBooleanField(required=False)


class EcommerceLoanRequestValidation(LoanRequestValidationSerializer):
    va_number = serializers.CharField(required=False,
                                      allow_null=True,
                                      allow_blank=True,
                                      default=None)


class UpdateLoanSerializer(serializers.Serializer):
    loan_duration = serializers.IntegerField(required=True)


class CreditCardLoanSPHPViewSerializer(UpdateLoanSerializer):
    loan_xid = serializers.IntegerField(required=True)


class JuloCareCallbackSerializer(serializers.Serializer):
    class _Document(serializers.ListField):
        url = serializers.CharField(required=True)
        filename = serializers.CharField(required=True)
        type = serializers.CharField(required=True)
        alias = serializers.CharField(required=True)

    policy_id = serializers.CharField(required=True)
    policy_number = serializers.CharField(required=True)
    transaction_id = serializers.IntegerField(required=True)
    product_code = serializers.CharField(required=True)
    quotation_number = serializers.CharField(required=True)
    status = serializers.CharField(required=True)
    documents = _Document()


class LoanSignatureUploadSerializer(serializers.Serializer):
    upload = serializers.ImageField(required=True)
    data = serializers.CharField(required=True)

    def validate_upload(self, value):
        is_jpg = value.name.endswith(".jpg")
        is_png = value.name.endswith(".png")
        is_jpeg = value.name.endswith(".jpeg")

        if True not in {is_jpg, is_png, is_jpeg}:
            raise ValidationError("invalid signature file, only image allowed")

        return value

    def validate_data(self, value):
        self.validate_extension(value)

        pattern = re.compile(r'\.{2,}|\.{2,}\/')
        result = pattern.search(value)
        if result:
            raise ValidationError("invalid path")

        if value.startswith('--') or value.endswith('--'):
            raise ValidationError("invalid path")

        if not re.match(r"^[a-zA-Z0-9-_/.]+$", value):
            raise ValidationError("invalid path")

        if os.path.split(value)[0]:
            raise ValidationError("invalid path")

    @staticmethod
    def validate_extension(value):
        _, ext = os.path.splitext(value)
        if ext and ext.lower() not in ['.jpg', '.png', '.jpeg']:
            raise ValidationError("Invalid file extension. Only .jpg, .png, and .jpeg are allowed")


class UserCampaignEligibilityV2RequestSerializer(serializers.Serializer):
    transaction_type_code = serializers.IntegerField(required=False, default=0)
    device_brand = serializers.CharField(required=False)
    device_model = serializers.CharField(required=False)
    os_version = serializers.IntegerField(required=False)

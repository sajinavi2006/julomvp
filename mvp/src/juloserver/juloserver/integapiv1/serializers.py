from datetime import datetime

from rest_framework import serializers
from rest_framework.serializers import CharField
from django.utils.translation import ugettext_lazy as _
from datetime import datetime
from juloserver.integapiv1.constants import MINIMUM_TRANSFER_AMOUNT
import re
from django.conf import settings


class PaymentInquirySerializer(serializers.Serializer):
    trx_uid = serializers.CharField(max_length=24)
    amount = serializers.IntegerField()


class PaymentNotificationSerializer(serializers.Serializer):
    trx_id = serializers.CharField(max_length=24)
    merchant_id = serializers.IntegerField()
    merchant = serializers.CharField(max_length=32)
    bill_no = serializers.CharField(max_length=32)
    amount = serializers.IntegerField(read_only=True)
    payment_reff = serializers.CharField(max_length=32, allow_null=True)
    payment_date = serializers.CharField(max_length=50)
    payment_status_code = serializers.IntegerField()
    payment_status_desc = serializers.CharField(max_length=32)
    signature = serializers.CharField(max_length=50)
    channel_resp_code = serializers.CharField(required=False, allow_null=True, max_length=5)
    payment_total = serializers.IntegerField(required=False, allow_null=True)


class SepulsaTransactionSerializer(serializers.Serializer):
    response_code = CharField(label=_("Response Code"))
    transaction_id = CharField(label=_("Transaction Id"))
    order_id = CharField(label=_("Order Id"))
    status = CharField(label=_("Status"), allow_null=True, required=False)
    serial_number = CharField(label=_("Serial Number"), allow_null=True, required=False)


class VoiceCallbackResultSerializer(serializers.Serializer):
    """
    Serializer for nexmo Voice Callback Result
    """
    uuid = serializers.UUIDField(format='hex_verbose')
    conversation_uuid = serializers.CharField()
    to = serializers.CharField(max_length=32)
    direction = serializers.CharField(max_length=32)
    start_time = serializers.CharField(max_length=32, allow_null=True, required=False)
    status = serializers.CharField(max_length=32)
    rate = serializers.CharField(max_length=32, allow_null=True, required=False)
    price = serializers.CharField(max_length=32, allow_null=True, required=False)
    duration = serializers.CharField(max_length=32, allow_null=True, required=False)
    end_time = serializers.CharField(max_length=32, allow_null=True, required=False)


class VoiceCallRecordingSerializer(serializers.Serializer):
    """
    Serializer for nexmo Voice Recording callback
    """
    conversation_uuid = serializers.CharField()
    recording_uuid = serializers.CharField()
    recording_url = serializers.CharField()
    start_time = serializers.CharField(max_length=32, allow_null=True, required=False)
    end_time = serializers.CharField(max_length=32, allow_null=True, required=False)
    size = serializers.IntegerField()


class SnapInquiryBillsSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(required=True)
    customerNo = serializers.CharField(required=True)
    virtualAccountNo = serializers.CharField(required=True)
    trxDateInit = serializers.CharField(required=True)
    inquiryRequestId = serializers.CharField(required=True)

    def validate_trxDateInit(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid trxDateInit")

        return value

    def validate_virtualAccountNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid virtualAccountNo")

        return value

    def validate_customerNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid customerNo")

        return value

    def validate_partnerServiceId(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid partnerServiceId")

        return value


class BeneficiaryCallbackSuccessSerializer(serializers.Serializer):
    beneficiaryId = serializers.CharField(required=True)
    status = serializers.IntegerField(required=True)
    customerId = serializers.CharField(required=True)
    accountType = serializers.CharField(allow_blank=True, allow_null=True, required=False)


class BeneficiaryCallbackUnSuccessSerializer(serializers.Serializer):
    customerId = serializers.CharField(required=True)


class AyoconnectDisbursementDetailsErrorsSerializer(serializers.Serializer):
    """
    Ayoconnect Disbursement callback details errors Serializer
    """
    code = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    details = serializers.CharField(required=False)


class AyoconnectDisbursementDetailsSerializer(serializers.Serializer):
    """
    Ayoconnect Disbursement callback details Serializer
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.update({"A-Correlation-ID": serializers.CharField()})

    amount = serializers.CharField(required=False)
    currency = serializers.CharField(default='IDR', required=False)
    status = serializers.IntegerField(required=False)
    beneficiaryId = serializers.CharField()
    remark = serializers.CharField(required=False)
    errors = AyoconnectDisbursementDetailsErrorsSerializer(many=True, required=False)


class AyoconnectDisbursementCallbackSerializer(serializers.Serializer):
    """
    Ayoconnect Disbursement callback Serializer
    """
    code = serializers.IntegerField()
    message = serializers.CharField()
    responseTime = serializers.CharField()
    transactionId = serializers.CharField()
    referenceNumber = serializers.CharField()
    customerId = serializers.CharField()
    details = AyoconnectDisbursementDetailsSerializer()


class SnapBcaAccessTokenSerializer(serializers.Serializer):
    grantType = serializers.CharField(required=True)

    def validate_grantType(self, value):
        if value != 'client_credentials':
            raise serializers.ValidationError("invalid value")

        return value


class SnapBcaInquiryBillsSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(required=True)
    customerNo = serializers.CharField(required=True)
    virtualAccountNo = serializers.CharField(required=True)
    trxDateInit = serializers.CharField(required=True)
    inquiryRequestId = serializers.CharField(required=True)

    def validate_trxDateInit(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid trxDateInit")

        return value

    def validate_virtualAccountNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid virtualAccountNo")

        return value

    def validate_customerNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid customerNo")

        return value

    def validate_partnerServiceId(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid partnerServiceId")

        return value


class SnapBcaPaymentFlagSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(required=True)
    customerNo = serializers.CharField(required=True)
    virtualAccountNo = serializers.CharField(required=True)
    trxDateTime = serializers.CharField(required=True)
    paymentRequestId = serializers.CharField(required=True)
    paidAmount = serializers.DictField(required=True)

    def validate_trxDateInit(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid trxDateInit")

        return value

    def validate_paidAmount(self, value):
        if not value.get("value"):
            raise serializers.ValidationError("value mandatory")
        elif not value.get("currency"):
            raise serializers.ValidationError("currency mandatory")

        try:
            float(value.get("value"))
        except ValueError:
            raise serializers.ValidationError("Amount")

        if not re.match(r'^\d+\.\d{2}$', value.get("value")):
            raise serializers.ValidationError("Amount")

        return value

    def validate_virtualAccountNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid virtualAccountNo")

        return value

    def validate_customerNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid customerNo")

        return value

    def validate_partnerServiceId(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid partnerServiceId")

        return value


class SnapFaspayInquiryBillsSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(required=True)
    customerNo = serializers.CharField(required=True)
    virtualAccountNo = serializers.CharField(required=True)
    inquiryRequestId = serializers.CharField(required=True)


class CustomerDataCootekRequestSerializer(serializers.Serializer):
    """
    Used in CallCustomerCootekRequestSerializer
    """

    customer_id = serializers.CharField(required=True)
    current_account_payment_id = serializers.CharField(required=True)


class CampaignDataRequestSerializer(serializers.Serializer):
    """
    Used in CallCustomerCootekRequestSerializer
    """

    campaign_name = serializers.CharField(required=True)
    campaign_id = serializers.CharField(required=True)


class DataCootekRequestSerializer(serializers.Serializer):
    """
    Used in CallCustomerCootekRequestSerializer
    """

    task_type = serializers.CharField(required=True)
    robot_id = serializers.CharField(required=True)
    start_time = serializers.TimeField(required=True)
    end_time = serializers.TimeField(required=True)
    attempt = serializers.IntegerField(required=True)
    intention_list = serializers.ListField(child=serializers.CharField(), required=True)
    is_group_method = serializers.BooleanField(required=False, default=False)


class CallCustomerCootekRequestSerializer(serializers.Serializer):
    """
    Serializer for CallCustomerCootekRequest
    """

    customers = CustomerDataCootekRequestSerializer(many=True, required=True)
    campaign_data = CampaignDataRequestSerializer(required=True)
    data = DataCootekRequestSerializer(required=True)


class SnapFaspayPaymentFlagSerializer(serializers.Serializer):
    partnerServiceId = serializers.CharField(required=True)
    customerNo = serializers.CharField(required=True)
    virtualAccountNo = serializers.CharField(required=True)
    trxDateTime = serializers.CharField(required=True)
    paymentRequestId = serializers.CharField(required=True)
    paidAmount = serializers.DictField(required=True)
    referenceNo = serializers.CharField(required=True)

    def validate_trxDateTime(self, value):
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise serializers.ValidationError("invalid trxDateTime")

        return value

    def validate_paidAmount(self, value):
        if not value.get("value"):
            raise serializers.ValidationError("value mandatory")
        elif not value.get("currency"):
            raise serializers.ValidationError("currency mandatory")

        try:
            amount = float(value.get("value"))
        except ValueError:
            raise serializers.ValidationError("Amount")

        if not re.match(r'^\d+\.\d{2}$', value.get("value")):
            raise serializers.ValidationError("Amount")

        if amount < float(MINIMUM_TRANSFER_AMOUNT) and not self.initial_data.get(
            'partnerServiceId', ''
        ).strip() in (
            settings.FASPAY_PREFIX_ALFAMART,
            settings.FASPAY_PREFIX_INDOMARET,
            settings.FASPAY_PREFIX_OLD_INDOMARET,
            settings.FASPAY_PREFIX_OLD_ALFAMART,
        ):
            raise serializers.ValidationError("Amount")

        return value

    def validate_virtualAccountNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid virtualAccountNo")

        return value

    def validate_customerNo(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid customerNo")

        return value

    def validate_partnerServiceId(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid partnerServiceId")

        return value


class NexmoPayloadRequestSerializer(serializers.Serializer):
    """
    Used in CallCustomerNexmoRequestSerializer
    """

    customer_id = serializers.CharField(required=True)
    account_payment_id = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    content = serializers.ListField(child=serializers.DictField(), required=True)

    def validate_content(self, value):
        for contentItem in value:
            if not isinstance(contentItem, dict):
                raise serializers.ValidationError("content item is not a dict")

            if "action" not in contentItem:
                raise serializers.ValidationError("\"action\" field is mandatory")

        return value


class CallCustomerNexmoRequestSerializer(serializers.Serializer):
    """
    Serializer for CallCustomerNexmoRequest
    """

    campaign_data = CampaignDataRequestSerializer(required=True)
    retries = serializers.ListField(child=serializers.TimeField(), required=True)
    min_retry_delay_in_minutes = serializers.IntegerField(required=False, allow_null=True)
    payload = NexmoPayloadRequestSerializer(many=True, required=True)


class AiRudderTimeFrameDataSerializer(serializers.Serializer):
    """
    Serializer for time_frames in AiRudderConfigSerializer.
    """

    repeatTimes = serializers.IntegerField(required=True)
    contactInfoSource = serializers.CharField(required=False, default="original_source")


class AiRudderConfigSerializer(serializers.Serializer):
    """
    Serializer for airudder_config in CallCustomerAiRudderRequestSerializer.
    The attributes are refers to the config in "ai_rudder_tasks_strategy_config" feature setting.
    The optional and required fields are based on
        AIRudderPDSClient.create_task() and AIRudderPDSServices.create_new_task() logic.

    With exception for these attributes:
    * groupName
    """

    groupName = serializers.CharField(required=True)
    start_time = serializers.TimeField(required=False, format="%H:%M")
    end_time = serializers.TimeField(required=True, format="%H:%M")

    # Optional fields
    autoQA = serializers.CharField(required=False)
    acwTime = serializers.IntegerField(required=False)
    rest_times = serializers.ListField(
        child=serializers.ListField(child=serializers.TimeField(format="%H:%M")),
        required=False,
    )
    ringLimit = serializers.IntegerField(required=False)
    slotFactor = serializers.FloatField(required=False)
    dialingMode = serializers.IntegerField(required=False)
    maxLostRate = serializers.IntegerField(required=False)
    qaLimitLength = serializers.IntegerField(required=False)
    qaLimitRate = serializers.IntegerField(required=False)
    repeatTimes = serializers.IntegerField(required=False)
    callInterval = serializers.IntegerField(required=False)
    dialingOrder = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    autoSlotFactor = serializers.IntegerField(required=False)
    bulkCallInterval = serializers.IntegerField(required=False)
    contactNumberInterval = serializers.IntegerField(required=False)
    timeFrameStatus = serializers.ChoiceField(
        choices=["on", "off"],
        required=False,
    )
    timeFrames = serializers.ListField(
        child=AiRudderTimeFrameDataSerializer(),
        required=False,
    )
    resultStrategies = serializers.ChoiceField(
        choices=["on", "off"],
        required=False,
    )
    resultStrategiesConfig = serializers.ListField(child=serializers.DictField(), required=False)
    callRecordingUpload = serializers.ChoiceField(
        choices=["on", "off"],
        required=False,
    )

    def validate(self, data):
        data = super(AiRudderConfigSerializer, self).validate(data)
        data = self._validate_time_frames(data)
        return data

    def _validate_time_frames(self, data):
        if "timeFrameStatus" not in data:
            return data

        if data["timeFrameStatus"] == "on":
            if "timeFrames" not in data or len(data["timeFrames"]) == 0:
                raise serializers.ValidationError(
                    {
                        "timeFrames": ["timeFrames is mandatory"],
                    }
                )

            if "resultStrategiesConfig" not in data or len(data["resultStrategiesConfig"]) == 0:
                raise serializers.ValidationError(
                    {
                        "resultStrategiesConfig": ["resultStrategiesConfig is mandatory"],
                    }
                )

        return data


class AiRudderCustomerDataSerializer(serializers.Serializer):
    """
    The data type refers to AIRudderPayloadTemp models structure
    """
    phonenumber = serializers.CharField(required=True)
    account_payment_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    customer_id = serializers.IntegerField(required=True)
    account_id = serializers.IntegerField(required=True)
    nama_customer = serializers.CharField(required=True)


class CallCustomerAiRudderRequestSerializer(serializers.Serializer):
    """
    The Serializer is used to serialize the request from CallCustomerAiRudderPDSView
    """

    customers = serializers.ListField(child=serializers.DictField(), required=True)
    bucket_name = serializers.SlugField(required=True)
    batch_number = serializers.IntegerField(required=True)
    airudder_config = AiRudderConfigSerializer(required=True)

    def validate_customers(self, value):
        for customer in value:
            customer_serializer = AiRudderCustomerDataSerializer(data=customer)
            if not customer_serializer.is_valid():
                raise serializers.ValidationError(customer_serializer.errors)

        return value

from rest_framework import serializers

from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.integapiv1.serializers import AiRudderConfigSerializer
from juloserver.sales_ops_pds.models import SalesOpsLineupAIRudderData



class SalesOpsLineupAIRudderDataSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = SalesOpsLineupAIRudderData
        exclude = ("cdate", "udate", "id", "bucket_code")

    def to_representation(self, obj):
        result = super(SalesOpsLineupAIRudderDataSerializer, self).to_representation(obj)
        if 'mobile_phone_1' in result:
            result['PhoneNumber'] = format_e164_indo_phone_number(result['mobile_phone_1'])
            del result['mobile_phone_1']
        return result


class CustomerInfoSerializer(serializers.Serializer):
    account_id = serializers.CharField()
    customer_id = serializers.CharField()
    application_id = serializers.CharField()

    application_history_x190_cdate = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    available_limit = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    set_limit = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    customer_type = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    data_date = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    fullname = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    gender = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    is_12M_user = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    is_high_value_user = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    latest_active_dates = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    latest_loan_fund_transfer_ts = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    m_score = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    r_score = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    kode_voucher = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    scheme = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    biaya_admin_sebelumnya = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    biaya_admin_baru = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    bunga_cicilan_sebelumnya = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    bunga_cicilan_baru = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    partition_date = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    customer_segment = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    schema_amount = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    schema_loan_duration = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    cicilan_per_bulan_sebelumnya = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    cicilan_per_bulan_baru = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )
    saving_overall_after_np = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=""
    )


class CustomizeResultsSerializer(serializers.Serializer):
    title = serializers.CharField()
    groupName = serializers.CharField(allow_null=True, allow_blank=True)
    value = serializers.CharField(allow_null=True, allow_blank=True)


class AIRudderCallResultSerializer(serializers.Serializer):
    taskId = serializers.CharField()
    taskName = serializers.CharField()
    callid = serializers.CharField()
    phoneNumber = serializers.CharField()
    mainNumber = serializers.CharField()
    customerName = serializers.CharField(allow_null=True, allow_blank=True)
    calltime = serializers.CharField()
    ringtime = serializers.CharField(allow_null=True, allow_blank=True)
    answertime = serializers.CharField(allow_null=True, allow_blank=True)
    talktime = serializers.CharField(allow_null=True, allow_blank=True)
    endtime = serializers.CharField(allow_null=True, allow_blank=True)
    talkDuration = serializers.IntegerField()
    waitingDuration = serializers.IntegerField()
    talkedTime = serializers.IntegerField()
    holdDuration = serializers.IntegerField()
    nthCall = serializers.IntegerField()
    biztype = serializers.CharField()
    agentName = serializers.CharField(allow_blank=True, allow_null=True)
    adminAct = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    transferReason = serializers.CharField(allow_null=True, allow_blank=True)
    hangupReason = serializers.IntegerField()
    callType = serializers.CharField()
    callResultType = serializers.CharField()
    reclink = serializers.CharField(allow_blank=True, allow_null=True)
    talkremarks = serializers.CharField(allow_blank=True, allow_null=True)
    customerInfo = CustomerInfoSerializer(required=True)
    customizeResults = serializers.ListField(
        required=True, child=CustomizeResultsSerializer()
    )

    def format_customer_info_fields(self, data):
        fields = list(data["customerInfo"].keys())
        for field in fields:
            data[field] = data["customerInfo"][field]

        del data["customerInfo"]

    def format_result_fields(self, data):
        for result in data["customizeResults"]:
            result_level = result["title"].replace(" ", "_").lower()
            data[result_level] = result["value"]

        del data["customizeResults"]

    def validate(self, data):
        data = super(AIRudderCallResultSerializer, self).validate(data)
        self.format_customer_info_fields(data)
        self.format_result_fields(data)
        return data


class AIRudderPDSConfigSerializer(AiRudderConfigSerializer):
    voiceCheck = serializers.IntegerField(required=False)
    voiceCheckDuration = serializers.IntegerField(required=False)
    voiceHandle = serializers.IntegerField(required=False)

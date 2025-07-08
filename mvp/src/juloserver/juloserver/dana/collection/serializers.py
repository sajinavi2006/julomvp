from rest_framework import serializers
from datetime import datetime

from juloserver.minisquad.services2.airudder import format_ptp_date


class DanaDialerTemporarySerializer(serializers.Serializer):
    account__dana_customer_data__application__id = serializers.CharField(
        source='application_id', required=False, allow_blank=True, allow_null=True
    )
    account__customer_id = serializers.CharField(
        source='customer_id', required=False, allow_blank=True, allow_null=True
    )
    account__dana_customer_data__full_name = serializers.CharField(
        source='nama_customer', required=False, allow_blank=True, allow_null=True
    )
    account__dana_customer_data__mobile_number = serializers.CharField(
        source='mobile_number', required=False, allow_blank=True, allow_null=True
    )
    due_date = serializers.CharField(source='tanggal_jatuh_tempo')
    team = serializers.CharField()
    id = serializers.IntegerField(source='account_payment_id')
    dpd_field = serializers.IntegerField(source='dpd')
    is_active = serializers.BooleanField(default=True)


class CustomizeResultSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    value = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AIRudderToDanaSkiptraceHistorySerializer(serializers.Serializer):
    callType = serializers.CharField(source='callback_type')
    callResultType = serializers.CharField(source='talk_results_type')
    talkResult = serializers.CharField(
        source='talk_result', required=False, allow_blank=True, allow_null=True
    )
    callid = serializers.CharField(source='unique_call_id')
    phoneNumber = serializers.CharField(source='phone_number')
    mainNumber = serializers.CharField(source='main_number')
    agentName = serializers.CharField(
        source='agent_name', required=False, allow_blank=True, allow_null=True
    )
    phoneTag = serializers.CharField(
        source='contact_source', required=False, allow_blank=True, allow_null=True
    )
    talkremarks = serializers.CharField(
        source='skiptrace_notes', required=False, allow_blank=True, allow_null=True
    )
    calltime = serializers.CharField()
    endtime = serializers.CharField(allow_blank=True, allow_null=True)
    customizeResults = CustomizeResultSerializer(
        many=True, required=False, allow_null=True, allow_empty=True
    )
    hangupReason = serializers.CharField(
        source='hangup_reason',
        required=False,
    )

    def construct_data(self, validated_data):
        customize_results_data = validated_data['customizeResults']
        customize_results = {item['title']: item['value'] for item in customize_results_data}

        ptp_date = format_ptp_date(customize_results.get('PTP Date', ''))
        customize_results['ptp_date'] = ptp_date
        spoke_with = customize_results.get('Spokewith', '')
        non_payment_reason = customize_results.get('Nopaymentreason', '')
        calltime = datetime.strptime(validated_data['calltime'], '%Y-%m-%dT%H:%M:%S%z')
        if validated_data['endtime']:
            endtime = datetime.strptime(validated_data['endtime'], '%Y-%m-%dT%H:%M:%S%z')
        else:
            endtime = calltime

        # Construct the data object using the extracted values
        skiptrace_history_data = {
            'start_ts': calltime,
            'end_ts': endtime,
            'customizeResults': customize_results,
            'spoke_with': spoke_with,
            'non_payment_reason': non_payment_reason,
        }
        construct_data = validated_data
        construct_data.update(skiptrace_history_data)
        return construct_data

    def validate(self, validated_data):
        # Call the construct_data method to construct the data object
        skiptrace_history_data = self.construct_data(validated_data)

        # Perform any additional operations if needed

        # Return the constructed data object
        return skiptrace_history_data

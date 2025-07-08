import csv
import logging
import os
from datetime import datetime

from django.utils import timezone
from rest_framework import serializers
from django import forms

from juloserver.minisquad.services2.airudder import format_ptp_date

logger = logging.getLogger(__name__)


class IntelixUploadCallSerializer(serializers.Serializer):
    csv_file = serializers.FileField(required=True)
    email_address = serializers.EmailField(required=True)

    def validate_csv_file(self, file_):
        _, extension = os.path.splitext(file_.name)
        if extension != '.csv':
            raise serializers.ValidationError('file extension harus csv')

        decoded_file = file_.read().decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        # if data_reader.fieldnames != CovidRefinancingConst.CSV_HEADER_LIST:
        #     raise serializers.ValidationError(
        #         'csv header harus sesuai dengan pattern: %s' % str(CovidRefinancingConst.CSV_HEADER_LIST)
        #     )
        return data_reader


class IntelixCallResultsRealtimeSerializer(serializers.Serializer):
    LOAN_ID = serializers.IntegerField(required=False)
    CALLBACK_TIME = serializers.CharField(required=False)
    NOTES = serializers.CharField(required=False)
    AGENT_NAME = serializers.CharField(required=True)
    START_TS = serializers.DateTimeField(required=True)
    END_TS = serializers.DateTimeField(required=True)
    NON_PAYMENT_REASON = serializers.CharField(required=False)
    SPOKE_WITH = serializers.CharField(required=False)
    CALL_STATUS = serializers.CharField(required=True)
    PTP_AMOUNT = serializers.IntegerField(required=False)
    PTP_DATE = serializers.DateField(required=False)
    ACCOUNT_ID = serializers.IntegerField(required=False)
    ACCOUNT_PAYMENT_ID = serializers.IntegerField(required=False)
    PHONE_NUMBER = serializers.CharField(required=False)


class CallRecordingDetailSerializer(serializers.Serializer):
    LOAN_ID = serializers.IntegerField(required=False)
    PAYMENT_ID = serializers.IntegerField(required=False)
    ACCOUNT_ID = serializers.IntegerField(required=False)
    ACCOUNT_PAYMENT_ID = serializers.IntegerField(required=False)
    AGENT_NAME = serializers.CharField(required=True)
    START_TS = serializers.DateTimeField(required=True)
    END_TS = serializers.DateTimeField(required=True)
    CALL_ID = serializers.CharField(required=True)
    VOICE_PATH = serializers.CharField(required=True)
    CALL_STATUS = serializers.CharField(required=True)
    BUCKET = serializers.CharField(required=True)
    CALL_TO = serializers.CharField(required=True)


class GenesysManualUploadCallSerializer(serializers.Serializer):
    csv_file = serializers.FileField(required=True)

    def validate_csv_file(self, file_):
        _, extension = os.path.splitext(file_.name)
        if extension != '.csv':
            raise serializers.ValidationError('file extension harus csv')

        decoded_file = file_.read().decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        return data_reader


class IntelixBlackListAccountSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    expire_date = serializers.DateField(
        required=True, input_formats=["%Y-%m-%d"], format="%Y-%m-%d")
    reason_removal = serializers.CharField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data['expire_date'] < timezone.localtime(timezone.now()).date():
            raise serializers.ValidationError(
                {"expire_date": "cannot < today"}
            )
        return data


class IntelixBlackListAccountPhoneSerializer(serializers.Serializer):
    contact_name = serializers.CharField(required=True)
    contact_source = serializers.CharField(required=False)
    phone_number = serializers.CharField(required=False)


class IntelixFilterSerializer(serializers.Serializer):
    filter_query_bucket = serializers.CharField(required=True)


class CollectionDialerTemporarySerializer(serializers.Serializer):
    account__customer_id = serializers.IntegerField(source='customer_id')
    account__application__id = serializers.CharField(
        source='application_id', required=False, allow_blank=True, allow_null=True)
    account__application__fullname = serializers.CharField(
        source='nama_customer', required=False, allow_blank=True, allow_null=True)
    account__application__company_name = serializers.CharField(
        source='nama_perusahaan', required=False, allow_blank=True, allow_null=True)
    account__application__position_employees = serializers.CharField(
        source='posisi_karyawan', required=False, allow_blank=True, allow_null=True)
    account__application__spouse_name = serializers.CharField(
        source='nama_pasangan', required=False, allow_blank=True, allow_null=True)
    account__application__kin_name = serializers.CharField(
        source='nama_kerabat', required=False, allow_blank=True, allow_null=True)
    account__application__kin_relationship = serializers.CharField(
        source='hubungan_kerabat', required=False, allow_blank=True, allow_null=True)
    account__application__gender = serializers.CharField(
        source='jenis_kelamin', required=False, allow_blank=True, allow_null=True)
    account__application__dob = serializers.CharField(
        source='tgl_lahir', required=False, allow_blank=True, allow_null=True)
    account__application__payday = serializers.CharField(
        source='tgl_gajian', required=False, allow_blank=True, allow_null=True)
    account__application__loan_purpose = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, source='tujuan_pinjaman')
    due_date = serializers.CharField(source='tanggal_jatuh_tempo')
    alamat = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    account__application__address_kabupaten = serializers.CharField(
        source='kota', required=False, allow_blank=True, allow_null=True)
    account__application__product_line__product_line_type = serializers.CharField(
        source='tipe_produk', required=False, allow_blank=True, allow_null=True)
    account__application__partner__name = serializers.CharField(
        source='partner_name', required=False, allow_blank=True, allow_null=True)
    team = serializers.CharField()
    id = serializers.IntegerField(source='account_payment_id')
    dpd_field = serializers.IntegerField(source='dpd')


class BulkCancelCallForm(forms.Form):
    uploaded_file = forms.FileField()

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        if not uploaded_file:
            raise forms.ValidationError('Please select a CSV file')
        file_name, file_extension = os.path.splitext(uploaded_file.name)
        if file_extension.lower() != '.csv':
            raise forms.ValidationError('Only CSV files are allowed')
        file_read = uploaded_file.read()
        decoded_file = file_read.decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        if 'phonenumber' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no phonenumber field on header')

        rows = list(data_reader)
        if len(rows) == 0:
            raise forms.ValidationError(
                'The uploaded file has no data or contains only the header row.')
        return file_read.decode('utf-8')

class CustomizeResultSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    value = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class CustomerInfoSerializer(serializers.Serializer):
    account_payment_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AIRudderToSkiptraceHistorySerializer(serializers.Serializer):
    callType = serializers.CharField(source='callback_type')
    callResultType = serializers.CharField(source='talk_results_type')
    talkResult = serializers.CharField(
        source='talk_result', required=False, allow_blank=True, allow_null=True)
    taskId = serializers.CharField(source='dialer_task_id')
    callid = serializers.CharField(source='unique_call_id')
    phoneNumber = serializers.CharField(source='phone_number')
    mainNumber = serializers.CharField(source='main_number')
    agentName = serializers.CharField(
        source='agent_name', required=False, allow_blank=True, allow_null=True)
    phoneTag = serializers.CharField(
        source='contact_source', required=False, allow_blank=True, allow_null=True)
    talkremarks = serializers.CharField(
        source='skiptrace_notes', required=False, allow_blank=True, allow_null=True)
    calltime = serializers.CharField()
    endtime = serializers.CharField(allow_blank=True, allow_null=True)
    customizeResults = CustomizeResultSerializer(
        many=True, required=False, allow_null=True, allow_empty=True)
    customerInfo = CustomerInfoSerializer(required=False, allow_null=True)
    hangupReason = serializers.CharField(
        source='hangup_reason', required=False)
    taskName = serializers.CharField(source='task_name')
    reclink = serializers.CharField(
        source='rec_link', required=False, allow_blank=True, allow_null=True)
    nthCall = serializers.CharField(source='nth_call', allow_blank=True, allow_null=True)
    answertime = serializers.CharField(allow_blank=True, allow_null=True)
    ringtime = serializers.CharField(allow_blank=True, allow_null=True)
    talktime = serializers.CharField(allow_blank=True, allow_null=True)

    def construct_data(self, validated_data):
        customize_results_data = validated_data['customizeResults']
        customer_info_data = validated_data.get('customerInfo', {})
        customize_results = {
            item['title']: item['value']
            for item in customize_results_data
        }

        ptp_date = format_ptp_date(customize_results.get('PTP Date', ''))
        customize_results['ptp_date'] = ptp_date
        spoke_with = customize_results.get('Spokewith', '')
        # on staging N is
        non_payment_reason = customize_results.get('Nopaymentreason', '') or customize_results.get(
            'nopaymentreason', ''
        )
        calltime = datetime.strptime(validated_data['calltime'], '%Y-%m-%dT%H:%M:%S%z')
        if validated_data['endtime']:
            endtime = datetime.strptime(validated_data['endtime'], '%Y-%m-%dT%H:%M:%S%z')
        else:
            endtime = calltime

        if validated_data['answertime']:
            answertime_ts = datetime.strptime(validated_data['answertime'], '%Y-%m-%dT%H:%M:%S%z')
        else:
            answertime_ts = None

        if validated_data['ringtime']:
            ringtime_ts = datetime.strptime(validated_data['ringtime'], '%Y-%m-%dT%H:%M:%S%z')
        else:
            ringtime_ts = None

        if validated_data['talktime']:
            talktime_ts = datetime.strptime(validated_data['talktime'], '%Y-%m-%dT%H:%M:%S%z')
        else:
            talktime_ts = None

        account_payment_id = customer_info_data.get('account_payment_id', '')

        # Construct the data object using the extracted values
        skiptrace_history_data = {
            'start_ts': calltime,
            'end_ts': endtime,
            'customizeResults': customize_results,
            'spoke_with': spoke_with,
            'non_payment_reason': non_payment_reason,
            'account_payment_id': account_payment_id,
            'answertime_ts': answertime_ts,
            'ringtime_ts': ringtime_ts,
            'talktime_ts': talktime_ts,
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


class AIRudderToGrabSkiptraceHistorySerializer(serializers.Serializer):
    callType = serializers.CharField(source='callback_type')
    callResultType = serializers.CharField(source='talk_results_type')
    talkResult = serializers.CharField(
        source='talk_result', required=False, allow_blank=True, allow_null=True
    )
    callid = serializers.CharField(source='unique_call_id')
    taskId = serializers.CharField(source='task_id', required=False, allow_blank=True, allow_null=True)
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


class AIRudderToGrabSkiptraceHistoryManualUploadSerializer(serializers.Serializer):
    callType = serializers.CharField(source='callback_type')
    callResultType = serializers.CharField(source='talk_results_type')
    talkResult = serializers.CharField(
        source='talk_result', required=False, allow_blank=True, allow_null=True
    )
    callid = serializers.CharField(source='unique_call_id')
    taskName = serializers.CharField(source='task_name', required=False, allow_blank=True, allow_null=True)
    taskId = serializers.CharField(source='task_id', required=False, allow_blank=True, allow_null=True)
    reclink = serializers.CharField(source='recLink', required=False, allow_blank=True, allow_null=True)
    nthCall = serializers.CharField(required=False, allow_blank=True, allow_null=True)
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


class BulkChangeUserRoleForm(forms.Form):
    uploaded_file = forms.FileField()

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        if not uploaded_file:
            raise forms.ValidationError('Please select a CSV file')
        file_name, file_extension = os.path.splitext(uploaded_file.name)
        if file_extension.lower() != '.csv':
            raise forms.ValidationError('Only CSV files are allowed')
        file_read = uploaded_file.read()
        decoded_file = file_read.decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        if 'username' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no username field on header')
        if 'remove_roles' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no remove_role field on header')
        if 'new_roles' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no new_role field on header')
        if 'new_email' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no new_email field on header')

        rows = list(data_reader)
        if len(rows) == 0:
            raise forms.ValidationError(
                'The uploaded file has no data or contains only the header row.')
        return file_read.decode('utf-8')

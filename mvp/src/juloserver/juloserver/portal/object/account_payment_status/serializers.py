from django.utils import timezone
from rest_framework import serializers
from babel.dates import format_datetime
from juloserver.account_payment.models import AccountPaymentNote, AccountPaymentStatusHistory
from juloserver.collection_vendor.models import CollectionAssignmentHistory
from juloserver.julo.models import EmailHistory, SmsHistory
from juloserver.portal.core.templatetags.unit import email_fil1


class SkiptraceHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    account_payment_id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    application_id = serializers.IntegerField()
    call_result_id = serializers.IntegerField()
    cdate = serializers.SerializerMethodField()
    agent_name = serializers.CharField()
    call_result__name = serializers.CharField()
    callback_time = serializers.CharField()
    skiptrace__phone_number = serializers.CharField()
    skiptrace__contact_source = serializers.CharField()
    spoke_with = serializers.CharField()
    loan_id = serializers.IntegerField(required=False)
    payment_id = serializers.IntegerField(required=False)
    start_ts = serializers.SerializerMethodField()
    end_ts = serializers.SerializerMethodField()
    non_payment_reason = serializers.CharField()

    def get_cdate(self, obj):
        return format_datetime(
            timezone.localtime(obj['cdate']), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj['cdate'] else ""

    def get_start_ts(self, obj):
        return format_datetime(
            timezone.localtime(obj['start_ts']), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj['start_ts'] else ""

    def get_end_ts(self, obj):
        return format_datetime(
            timezone.localtime(obj['end_ts']), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj['end_ts'] else ""


class AccountPaymentNoteSerializer(serializers.ModelSerializer):
    cdate = serializers.SerializerMethodField()
    type_data = serializers.SerializerMethodField()
    added_by = serializers.SerializerMethodField()
    note_text = serializers.SerializerMethodField()
    def get_type_data(self, obj):
        return f'Notes'

    class Meta:
        model = AccountPaymentNote
        fields = ('cdate', 'note_text', 'added_by', 'type_data', 'extra_data')

    def get_cdate(self, obj):
        return format_datetime(
            timezone.localtime(obj.cdate), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj.cdate else ""

    def get_added_by(self, obj):
        return obj.added_by.username if obj.added_by else ""

    def get_note_text(self, obj):
        if not obj.note_text:
            return ''
        formatted_text = obj.note_text.replace('\n\n', '</p><p>')
        formatted_text = formatted_text.replace('\n', '<br>')
        return f'<p>{formatted_text}</p>'

class AccountPaymentStatusHistorySerializer(serializers.ModelSerializer):
    cdate = serializers.SerializerMethodField()
    type_data = serializers.CharField()
    changed_by_name = serializers.SerializerMethodField()
    change_reason_formatted = serializers.SerializerMethodField()
    class Meta:
        model = AccountPaymentStatusHistory
        fields = '__all__'

    def get_cdate(self, obj):
        return format_datetime(
            timezone.localtime(obj.cdate), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj.cdate else ""

    def get_changed_by_name(self, obj):
        return obj.changed_by.username if obj.changed_by else ""

    def get_change_reason_formatted(self, obj):
        if not obj.change_reason:
            return ''
        formatted_text = obj.change_reason.replace('\n\n', '</p><p>')
        formatted_text = formatted_text.replace('\n', '<br>')
        return f'<p>{formatted_text}</p>'

class CollectionAssignmentHistorySerializer(serializers.ModelSerializer):
    cdate = serializers.SerializerMethodField()
    type_data = serializers.CharField()
    class Meta:
        model = CollectionAssignmentHistory
        fields = '__all__'

    def get_cdate(self, obj):
        return format_datetime(
            timezone.localtime(obj.cdate), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj.cdate else ""


class StatusHistorySerializer(serializers.Serializer):
    def to_representation(self, instance):
        if isinstance(instance, AccountPaymentNote):
            serializer = AccountPaymentNoteSerializer(instance)
        elif isinstance(instance, AccountPaymentStatusHistory):
            serializer = AccountPaymentStatusHistorySerializer(instance)
        elif isinstance(instance, CollectionAssignmentHistory):
            serializer = CollectionAssignmentHistorySerializer(instance)
        else:
            raise Exception("Unexpected type of instance")

        return serializer.data

class EmailHistorySerializer(serializers.ModelSerializer):
    type_data = serializers.CharField()
    cdate = serializers.SerializerMethodField()
    to_email_list = serializers.SerializerMethodField()
    cc_email_list = serializers.SerializerMethodField()

    class Meta:
        model = EmailHistory
        fields = '__all__'

    def get_cdate(self, obj):
        return format_datetime(
            timezone.localtime(obj.cdate), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj.cdate else ""

    def get_to_email_list(self, obj):
        return email_fil1(obj.to_email) if obj.to_email else []

    def get_cc_email_list(self, obj):
        return email_fil1(obj.cc_email) if obj.cc_email else []


class SmsHistorySerializer(serializers.ModelSerializer):
    type_data = serializers.CharField()
    cdate = serializers.SerializerMethodField()
    message_content_formatted = serializers.SerializerMethodField()

    class Meta:
        model = SmsHistory
        fields = '__all__'

    def get_cdate(self, obj):
        return format_datetime(
            timezone.localtime(obj.cdate), "dd MMM yyyy HH:mm:ss", locale='id_ID'
        ) if obj.cdate else ""

    def get_message_content_formatted(self, obj):
        if not obj.message_content:
            return ''
        formatted_text = obj.message_content.replace('\n\n', '</p><p>')
        formatted_text = formatted_text.replace('\n', '<br>')
        return f'<p>{formatted_text}</p>'

class EmailSmsHistorySerializer(serializers.Serializer):
    def to_representation(self, instance):
        if isinstance(instance, EmailHistory):
            serializer = EmailHistorySerializer(instance)
        elif isinstance(instance, SmsHistory):
            serializer = SmsHistorySerializer(instance)
        else:
            raise Exception("Unexpected type of instance")
        return serializer.data

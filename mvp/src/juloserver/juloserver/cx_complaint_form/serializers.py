from django.conf import settings
from rest_framework import serializers

from juloserver.cx_complaint_form.models import ComplaintSubmissionLog
from juloserver.julo.models import Customer
from juloserver.julo.utils import get_oss_presigned_url


class ComplaintTopicSerializer(serializers.Serializer):
    complaint_topic_id = serializers.ReadOnlyField(source='id')
    topic_name = serializers.ReadOnlyField()
    image_url = serializers.SerializerMethodField()
    slug = serializers.ReadOnlyField()
    is_shown = serializers.BooleanField()

    def get_image_url(self, obj):
        full_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, obj.image_url)
        return full_url.split('?')[0]


class ComplaintSubTopicSerializer(serializers.Serializer):
    complaint_sub_topic_id = serializers.ReadOnlyField(source='id')
    title = serializers.ReadOnlyField()
    survey_usage = serializers.ReadOnlyField()
    is_require_attachment = serializers.ReadOnlyField()
    total_required_attachment = serializers.ReadOnlyField()
    action_type = serializers.ReadOnlyField()
    action_value = serializers.ReadOnlyField()
    web_required_upload_info_banner = serializers.ReadOnlyField()
    confirmation_dialog = serializers.SerializerMethodField()

    def get_confirmation_dialog(self, obj):
        if (
            not obj.confirmation_dialog_title
            and not obj.confirmation_dialog_banner
            and not obj.confirmation_dialog_content
            and not obj.confirmation_dialog_info_text
            and not obj.confirmation_dialog_button_text
        ):
            return None

        confirmation_dialog_banner = (
            get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, obj.confirmation_dialog_banner)
            if obj.confirmation_dialog_banner
            else ""
        )

        return {
            'title': obj.confirmation_dialog_title,
            'image_url': confirmation_dialog_banner.split('?')[0],
            'content': obj.confirmation_dialog_content,
            'info': obj.confirmation_dialog_info_text,
            'button_text': obj.confirmation_dialog_button_text,
        }


class SubmitComplaintSerializer(serializers.Serializer):
    survey_submission_uid = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    complaint_sub_topic_id = serializers.IntegerField(required=True)

    def create(self, validated_data):
        customer = self.context.get("customer")
        subtopic = self.context.get("subtopic")

        submission_action_value = subtopic.action_value
        if subtopic.action_type == 'email':
            submission_action_value = customer.get_email

        validated_data["customer_id"] = customer.id
        validated_data["subtopic_id"] = subtopic.id
        validated_data["submission_action_type"] = subtopic.action_type
        validated_data["submission_action_value"] = submission_action_value
        validated_data.pop("complaint_sub_topic_id")

        return ComplaintSubmissionLog.objects.create(**validated_data)


class WebSubmitComplaintSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=True)
    nik = serializers.CharField(required=True)
    phone = serializers.CharField(required=True)
    email = serializers.CharField(required=True)
    survey_submission_uid = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    complaint_sub_topic_id = serializers.IntegerField(required=True)

    def create(self, validated_data):
        subtopic = self.context.get("subtopic")
        customer = Customer.objects.filter(
            nik=validated_data["nik"],
            phone=validated_data["phone"],
            email=validated_data["email"],
        ).first()
        if customer:
            validated_data["customer_id"] = customer.id

        submission_action_value = subtopic.action_value
        if subtopic.action_type == 'email':
            submission_action_value = validated_data["email"]

        validated_data["subtopic_id"] = subtopic.id
        validated_data["submission_action_type"] = subtopic.action_type
        validated_data["submission_action_value"] = submission_action_value
        validated_data.pop("complaint_sub_topic_id")
        return ComplaintSubmissionLog.objects.create(**validated_data)

from django.db.models import F, ExpressionWrapper, FloatField, Value
from django.db.models.functions import Coalesce
from rest_framework import serializers
import os

from rest_framework.exceptions import ValidationError

from juloserver.streamlined_communication.constant import PageType, StreamlinedCommCampaignConstants
from juloserver.streamlined_communication.models import Holiday, StreamlinedMessage
from juloserver.streamlined_communication.services import (
    is_julo_card_transaction_completed_action,
    is_transaction_status_action,
    is_julo_financing_product_action,
)

from juloserver.streamlined_communication.models import (
    StreamlinedCommunicationCampaign,
    StreamlinedCommunicationSegment,
)
from juloserver.streamlined_communication.utils import format_campaign_name
from juloserver.streamlined_communication.utils import get_total_sms_price


MAX_FILE_SIZE = 200000


def image_validation(file_):
    _, extension = os.path.splitext(file_.name)
    if extension not in ('.png', '.jpg', '.jpeg'):
        raise serializers.ValidationError('file extension harus png/jpg/jpeg')
    if file_.size > MAX_FILE_SIZE:
        raise serializers.ValidationError('ukuran gambar maximal 200kb')


class InfoCardSerializer(serializers.Serializer):
    background_card_image = serializers.FileField(required=False)
    l_button_image = serializers.FileField(required=False)
    r_button_image = serializers.FileField(required=False)
    m_button_image = serializers.FileField(required=False)
    optional_image = serializers.FileField(required=False)
    card_action = serializers.CharField(required=False)
    info_card_title = serializers.CharField(required=True)
    info_card_content = serializers.CharField(required=False)
    info_card_type = serializers.CharField(required=True)
    expiration_option = serializers.CharField(required=False)
    expiry_period = serializers.IntegerField(required=False, min_value=1)
    expiry_period_unit = serializers.CharField(required=False)
    youtube_video_id = serializers.CharField(required=False)

    def validate_background_card_image(self, file_):
        image_validation(file_)

    def validate_l_button_image(self, file_):
        image_validation(file_)

    def validate_r_button_image(self, file_):
        image_validation(file_)

    def validate_m_button_image(self, file_):
        image_validation(file_)

    def validate_optional_image(self, file_):
        image_validation(file_)

    def validate(self, data):
        expiration_option = data.get('expiration_option')
        if  expiration_option and expiration_option != "No Expiration Time":
            if data.get('expiry_period_unit') not in ['days', 'hours']:
                raise serializers.ValidationError({'expiry_period_unit': [' Please select days/hours']})
            expiry_period = data.get('expiry_period')
            if not expiry_period:
                raise serializers.ValidationError({'expiry_period': [' please enter valid integer']})
        return data


class PushNotificatonPermissionSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(required=True)
    is_pn_permission = serializers.BooleanField(required=True)
    is_do_not_disturb = serializers.BooleanField(required=True)
    feature_name = serializers.CharField(required=False, allow_blank=True)


class NotificationActionType(serializers.Serializer):
    action = serializers.CharField(required=True)

    def validate_action(self, value):
        valid_conditions = [
            lambda: value in PageType.all_pages(),
            lambda: is_julo_card_transaction_completed_action(value),
            lambda: is_transaction_status_action(value),
            lambda: is_julo_financing_product_action(value),
        ]
        if any(condition_is_met() for condition_is_met in valid_conditions):
            return value

        raise serializers.ValidationError('{} tidak sesuai'.format(value))


class NotificationSellOffWhiteList(serializers.Serializer):
    action = serializers.CharField(required=True)

    def validate_action(self, value):
        request = self.context.get('request')
        customer = request.user.customer
        if customer and customer.account and customer.account and customer.account.is_selloff:
            if value.lower() not in PageType.sell_off_white_list_pages():
                raise serializers.ValidationError('Page tidak boleh di akses'.format(value))

        return value


class HolidaySerializer(serializers.Serializer):
    holiday_date = serializers.DateField(required=True)
    is_annual = serializers.SerializerMethodField()

    class Meta():
        model = Holiday

    def get_is_annual(self, holiday):
        if 'is_annual' in holiday and holiday['is_annual'].lower() == 'true':
            return True
        elif 'is_annual' not in holiday or holiday['is_annual'].lower() == 'false':
            return False
        else:
            raise serializers.ValidationError('is_annual value should be true/TRUE or false/FALSE.')


class StreamlinedCommunicationCampaignListSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    created_time = serializers.SerializerMethodField(source="get_created_time")
    created_by = serializers.SerializerMethodField(source="get_created_by")
    name = serializers.SerializerMethodField(source='get_name')
    department = serializers.SerializerMethodField(source='get_department')
    campaign_type = serializers.CharField(required=False)
    user_segment = serializers.SerializerMethodField(source='get_user_segment')
    status = serializers.CharField(required=False)
    confirmed_by = serializers.SerializerMethodField(source="get_confirmed_by")

    class Meta:
        model = StreamlinedCommunicationCampaign

    def get_name(self, obj):
        return obj.name

    def get_department(self, obj):
        return obj.department.name

    def get_user_segment(self, obj):
        return obj.user_segment.segment_name

    def get_created_by(self, obj):
        if obj.created_by:
            return obj.created_by.email if obj.created_by.email else obj.created_by.username

    def get_confirmed_by(self, obj):
        if obj.confirmed_by:
            return obj.confirmed_by.email if obj.confirmed_by.email else obj.confirmed_by.username

    def get_created_time(self, obj):
        return obj.cdate


class StreamlinedCommunicationCampaignCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StreamlinedCommunicationCampaign
        fields = '__all__'

    def to_internal_value(self, data):
        required_fields = [
            'squad',
            'department',
            'user_segment',
            'name',
            'content',
            'schedule_mode',
        ]
        missing_fields = [field for field in required_fields if field not in data]
        for field in missing_fields:
            raise ValidationError({"Error": ['{} field is required'.format(field)]})

        data['status'] = StreamlinedCommCampaignConstants.CampaignStatus.WAITING_FOR_APPROVAL
        streamlined_message_obj = StreamlinedMessage.objects.create(message_content=data['content'])
        data['content'] = streamlined_message_obj.id
        data['name'] = format_campaign_name(data['name'], data['department'])
        return super().to_internal_value(data)

    def validate_schedule_mode(self, value):
        if value not in [
            StreamlinedCommCampaignConstants.ScheduleMode.NOW,
            StreamlinedCommCampaignConstants.ScheduleMode.LATER,
            StreamlinedCommCampaignConstants.ScheduleMode.REPEATED,
        ]:
            raise serializers.ValidationError("Invalid schedule mode")
        return value

    def validate_name(self, value):
        if len(value) > 255:
            raise serializers.ValidationError("Name cannot exceed 255 characters")
        return value

    def validate_content(self, value):
        if len(value.message_content) < 1 or len(value.message_content) > 160:
            raise serializers.ValidationError("Content must be between 1 and 160 characters")
        return value


class CommsCampaignPhoneNumberSerializer(serializers.Serializer):
    phone_number = serializers.CharField()

    def validate_phone_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone number must contain only numeric characters.")

        if not 10 <= len(value.lstrip('0')) <= 12:
            raise serializers.ValidationError(
                "Phone number must be between 10 and 12 characters long."
            )

        return value


class StreamlinedCommunicationCampaignDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    created_time = serializers.SerializerMethodField(source="get_created_time")
    created_by = serializers.SerializerMethodField(source="get_created_by")
    name = serializers.SerializerMethodField(source='get_name')
    squad = serializers.SerializerMethodField(source='get_squad')
    department = serializers.SerializerMethodField(source='get_department')
    campaign_type = serializers.CharField(required=False)
    user_segment = serializers.SerializerMethodField(source='get_user_segment')
    segment_users_count = serializers.SerializerMethodField(source='get_segment_users_count')
    status = serializers.CharField(required=False)
    sms_content = serializers.SerializerMethodField(source='get_sms_content')
    schedule_mode = serializers.CharField(required=False)

    class Meta:
        model = StreamlinedCommunicationCampaign

    def get_name(self, obj):
        return obj.name

    def get_department(self, obj):
        return obj.department.name

    def get_user_segment(self, obj):
        return obj.user_segment.segment_name

    def get_created_by(self, obj):
        return obj.created_by.email if obj.created_by.email else obj.created_by.username

    def get_created_time(self, obj):
        return obj.cdate

    def get_squad(self, obj):
        if obj.squad:
            return obj.squad.name

    def get_segment_users_count(self, obj):
        return obj.user_segment.segment_count

    def get_sms_content(self, obj):
        if obj.content:
            return obj.content.message_content

    def to_representation(self, instance):
        data = super().to_representation(instance)
        total_sms_price = (
            StreamlinedCommunicationSegment.objects.filter(id=instance.user_segment.id)
            .annotate(
                total_sms_price=ExpressionWrapper(
                    get_total_sms_price(Coalesce(F('segment_count'), Value(0))),
                    output_field=FloatField(),
                )
            )
            .values('total_sms_price')
            .last()
        )
        if total_sms_price:
            data['total_sms_price'] = total_sms_price['total_sms_price']

        return data

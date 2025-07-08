import os

from rest_framework import serializers

ALLOWED_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".bmp", ".gif"]


class CollectionFieldSerializer(serializers.Serializer):
    filter_bucket = serializers.CharField(required=False)
    filter_account_ids = serializers.CharField(required=False)
    filter_agent_username = serializers.CharField(required=False)
    filter_cdate_mode = serializers.CharField(required=False)
    filter_cdate_1 = serializers.CharField(required=False)
    filter_cdate_2 = serializers.CharField(required=False)


class CollectionFieldAgentFilterSerializer(serializers.Serializer):
    filter_account_id = serializers.IntegerField(required=False)
    filter_expiry_date = serializers.DateField(input_formats=["%d-%m-%Y"], required=False)
    filter_area = serializers.CharField(required=False)


class CollectionFieldReportSerializer(serializers.Serializer):
    visit_location = serializers.CharField(required=True)
    result_mapping_code = serializers.CharField(required=True)
    visit_description = serializers.CharField(required=True)
    other_visit_location = serializers.CharField(required=False)
    payment_channel = serializers.CharField(required=True)
    new_phone_number = serializers.CharField(required=False)
    new_address = serializers.CharField(required=False)
    ptp_date = serializers.DateField(input_formats=["%Y-%m-%d"], required=False)
    ptp_amount = serializers.CharField(required=False)
    refuse_reasons = serializers.CharField(required=False)
    text_visit_other = serializers.CharField(required=False)

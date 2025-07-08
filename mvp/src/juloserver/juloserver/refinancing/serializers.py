import csv
import os
import logging

from rest_framework import serializers
from juloserver.loan_refinancing.constants import CovidRefinancingConst

logger = logging.getLogger(__name__)


class GenerateReactiveJ1RefinancingSerializer(serializers.Serializer):
    recommendation_offer_products = serializers.CharField(
        required=True, allow_blank=True, allow_null=True
    )
    account_id = serializers.IntegerField(required=True)
    new_income = serializers.IntegerField(required=True)
    new_expense = serializers.IntegerField(required=True)
    new_employment_status = serializers.CharField(required=True)
    is_auto_populated = serializers.BooleanField(required=False)


class SimulationJ1RefinancingOfferSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=True)
    selected_offer_recommendation = serializers.CharField(required=True)
    tenure_extension = serializers.IntegerField(required=True)
    new_income = serializers.IntegerField(required=True)
    new_expense = serializers.IntegerField(required=True)


class J1RefinancingRequestSerializer(serializers.Serializer):
    selected_product = serializers.CharField(required=True)
    account_id = serializers.IntegerField(required=True)
    tenure_extension = serializers.IntegerField(required=True)
    new_income = serializers.IntegerField(required=True)
    new_expense = serializers.IntegerField(required=True)
    new_employment_status = serializers.CharField(required=True)
    comms_channels = serializers.CharField(required=True)
    is_customer_confirmed = serializers.BooleanField(required=False)
    bucket_name = serializers.CharField(required=True)
    reason = serializers.CharField(required=False, default=None)
    notes = serializers.CharField(required=False, allow_null=True, default=None)
    extra_data = serializers.JSONField(required=False, default=None)
    agent_group = serializers.CharField(required=True)
    agent_detail = serializers.JSONField(required=False)


class J1ProactiveRefinancingSerializer(serializers.Serializer):
    csv_file = serializers.FileField(required=True)

    def validate_csv_file(self, file_):
        _, extension = os.path.splitext(file_.name)
        if extension != '.csv':
            raise serializers.ValidationError('file extension harus csv')

        decoded_file = file_.read().decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        if data_reader.fieldnames != CovidRefinancingConst.J1_CSV_HEADER_LIST:
            raise serializers.ValidationError(
                'csv header harus sesuai dengan pattern: %s' % str(
                    CovidRefinancingConst.J1_CSV_HEADER_LIST
                )
            )
        return data_reader


class J1RefinancingRequestApprovalSerializer(serializers.Serializer):
    loan_refinancing_request_id = serializers.IntegerField(required=True)
    loan_refinancing_approval_id = serializers.IntegerField(required=True)
    account_id = serializers.IntegerField(required=True)
    is_accepted = serializers.BooleanField(required=True)
    reason = serializers.CharField(required=True)
    notes = serializers.CharField(required=True)
    extra_data = serializers.JSONField(required=False, default=None)

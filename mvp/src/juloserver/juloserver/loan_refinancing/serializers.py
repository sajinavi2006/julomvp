from builtins import str
from rest_framework import serializers
from rest_framework.serializers import ValidationError
import logging
import csv
import os
import re
from .constants import CovidRefinancingConst, GeneralWebsiteConst

logger = logging.getLogger(__name__)


class LoanRefinancingOfferSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    due_amount = serializers.IntegerField(required=True)
    tenure_extension = serializers.IntegerField(required=True)
    late_fee_amount = serializers.IntegerField(required=True)
    main_reason = serializers.CharField(required=True)
    additional_reason = serializers.CharField(required=True)

class CovidRefinancingSerializer(serializers.Serializer):
    csv_file = serializers.FileField(required=True)

    def validate_csv_file(self, file_):
        _, extension = os.path.splitext(file_.name)
        if extension != '.csv':
            raise serializers.ValidationError('file extension harus csv')

        decoded_file = file_.read().decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        if data_reader.fieldnames != CovidRefinancingConst.CSV_HEADER_LIST:
            raise serializers.ValidationError(
                'csv header harus sesuai dengan pattern: %s' % str(CovidRefinancingConst.CSV_HEADER_LIST)
            )
        return data_reader


class CovidRefinancingOfferSimulationSerializer(serializers.Serializer):
    loan_id = serializers.IntegerField(required=True)
    selected_offer_recommendation = serializers.CharField(required=True)
    tenure_extension = serializers.IntegerField(required=True)
    new_income = serializers.IntegerField(required=True)
    new_expense = serializers.IntegerField(required=True)


class WaiverRequestSerializer(serializers.Serializer):
    loan_id = serializers.IntegerField(required=True)
    bucket_name = serializers.CharField(required=True)
    selected_program_name = serializers.CharField(required=True)
    is_covid_risky = serializers.CharField(required=True)
    outstanding_amount = serializers.IntegerField(required=True)
    unpaid_principal = serializers.IntegerField(required=True)
    unpaid_interest = serializers.IntegerField(required=True)
    unpaid_late_fee = serializers.IntegerField(required=True)
    waiver_validity_date = serializers.DateField(required=True)
    reason = serializers.CharField(required=True)
    ptp_amount = serializers.IntegerField(required=True)
    calculated_unpaid_waiver_percentage = serializers.FloatField(required=True)
    recommended_unpaid_waiver_percentage = serializers.FloatField(required=True)
    waived_payment_count = serializers.IntegerField(required=True)
    last_payment_number = serializers.IntegerField(required=False)
    partner_product = serializers.CharField(required=True)
    is_automated = serializers.BooleanField(required=True)
    waiver_recommendation_id = serializers.IntegerField(required=True)
    requested_late_fee_waiver_percentage = serializers.CharField(required=True)
    requested_interest_waiver_percentage = serializers.CharField(required=True)
    requested_principal_waiver_percentage = serializers.CharField(required=True)
    requested_late_fee_waiver_amount = serializers.IntegerField(required=True)
    requested_interest_waiver_amount = serializers.IntegerField(required=True)
    requested_principal_waiver_amount = serializers.IntegerField(required=True)
    requested_waiver_amount = serializers.IntegerField(required=True)
    remaining_amount_for_waived_payment = serializers.IntegerField(required=True)
    agent_notes = serializers.CharField(required=True)
    first_waived_payment = serializers.IntegerField(required=True)
    last_waived_payment = serializers.IntegerField(required=True)

    def validate_is_covid_risky(self, value):
        if value == "yes":
            return True
        return False


class CovidWaiverRequestSerializer(WaiverRequestSerializer):
    comms_channels = serializers.CharField(required=True)
    is_customer_confirmed = serializers.BooleanField(required=False)
    outstanding_late_fee_amount = serializers.IntegerField(required=True)
    outstanding_interest_amount = serializers.IntegerField(required=True)
    outstanding_principal_amount = serializers.IntegerField(required=True)
    new_income = serializers.CharField(required=True)
    new_expense = serializers.CharField(required=True)
    selected_payments_waived = serializers.JSONField(required=True)
    is_multiple_ptp_payment = serializers.BooleanField(required=False)
    number_of_multiple_ptp_payment = serializers.IntegerField(required=False)
    multiple_payment_ptp = serializers.JSONField(required=False)


class RefinancingFormSubmitSerializer(serializers.Serializer):
    main_reason = serializers.CharField(required=True)
    new_income = serializers.CharField(required=True)
    new_expense = serializers.CharField(required=True)
    # mobile_phone_1 = serializers.CharField(required=True)
    # mobile_phone_2 = serializers.CharField(allow_blank=True, allow_null=True)

    # def validate_mobile_phone_1(self, value):
    #     mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')

    #     if not mobile_phone_regex.match(value):
    #         raise ValidationError('Nomor Handphone tidak valid')
    #     return value


class RefinancingFormOfferSerializer(serializers.Serializer):
    product_type = serializers.CharField(required=True)
    product_id_1 = serializers.CharField(required=True)
    product_id_2 = serializers.CharField(required=False)


class GenerateReactiveRefinancingSerializer(serializers.Serializer):
    recommendation_offer_products = serializers.CharField(
        required=True, allow_blank=True, allow_null=True
    )
    loan_id = serializers.IntegerField(required=True)
    new_income = serializers.IntegerField(required=True)
    new_expense = serializers.IntegerField(required=True)
    new_employment_status = serializers.CharField(required=True)
    is_auto_populated = serializers.BooleanField(required=False)

    # def validate_recommendation_offer_products(self, value):
    #     if not all(product in CovidRefinancingConst.reactive_products() for product in value):
    #         raise ValidationError('Rekomendasi offer product tidak valid')
    #     return value


class LoanRefinancingRequestSerializer(serializers.Serializer):
    selected_product = serializers.CharField(required=True)
    loan_id = serializers.IntegerField(required=True)
    tenure_extension = serializers.IntegerField(required=True)
    new_income = serializers.IntegerField(required=True)
    new_expense = serializers.IntegerField(required=True)
    new_employment_status = serializers.CharField(required=True)
    # is_offer_confirmed = serializers.BooleanField(required=True)
    comms_channels = serializers.CharField(required=True)
    is_customer_confirmed = serializers.BooleanField(required=False)

class LoanRefinancingSelectedOfferSerializer(serializers.Serializer):
    term_and_agreement_1 = serializers.BooleanField(required=True)
    term_and_agreement_2 = serializers.BooleanField(required=True)

class SubmitPhoneSerializer(serializers.Serializer):
    mobile_phone = serializers.CharField(required=True)

    def validate_mobile_phone(self, value):
        mobile_phone_regex = re.compile(GeneralWebsiteConst.MOBILE_PHONE_REGEX)
        if not re.match(mobile_phone_regex, value):
            raise serializers.ValidationError('Nomor telepon tidak valid')


class OtpValidationSerializer(serializers.Serializer):
    otp_token = serializers.CharField(max_length=6, required=True)
    request_id = serializers.CharField(required=False)

    def validate_otp_token(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Otp tidak valid')
        max_length = 6
        if len(value) != max_length:
            raise serializers.ValidationError('Otp tidak valid')


class WaiverPaymentApprovalSerializer(serializers.Serializer):
    outstanding_late_fee_amount = serializers.IntegerField(required=True)
    outstanding_interest_amount = serializers.IntegerField(required=True)
    outstanding_principal_amount = serializers.IntegerField(required=True)
    total_outstanding_amount = serializers.IntegerField(required=True)
    approved_late_fee_waiver_amount = serializers.IntegerField(required=True)
    approved_interest_waiver_amount = serializers.IntegerField(required=True)
    approved_principal_waiver_amount = serializers.IntegerField(required=True)
    total_approved_waiver_amount = serializers.IntegerField(required=True)
    remaining_late_fee_amount = serializers.IntegerField(required=True)
    remaining_interest_amount = serializers.IntegerField(required=True)
    remaining_principal_amount = serializers.IntegerField(required=True)
    total_remaining_amount = serializers.IntegerField(required=True)
    payment_id = serializers.IntegerField(required=True)


class WaiverApprovalSerializer(serializers.Serializer):
    loan_id = serializers.IntegerField(required=True, allow_null=True)
    waiver_request_id = serializers.IntegerField(required=True, allow_null=True)
    paid_ptp_amount = serializers.IntegerField(required=True)
    decision = serializers.CharField(required=True)
    approved_program = serializers.CharField(required=True)
    approved_late_fee_waiver_percentage = serializers.FloatField(required=True)
    approved_interest_waiver_percentage = serializers.FloatField(required=True)
    approved_principal_waiver_percentage = serializers.FloatField(required=True)
    approved_waiver_amount = serializers.IntegerField(required=True)
    approved_remaining_amount = serializers.IntegerField(required=True)
    approved_waiver_validity_date = serializers.DateField(required=True)
    notes = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    waiver_payment_approvals = serializers.ListField(required=True)
    waiver_request = serializers.DictField(required=False, allow_null=True)
    waiver_payment_requests = serializers.ListField(required=False, allow_null=True)


class WaiverPaymentRequestSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField(required=True)
    outstanding_late_fee_amount = serializers.IntegerField(required=True)
    outstanding_interest_amount = serializers.IntegerField(required=True)
    outstanding_principal_amount = serializers.IntegerField(required=True)
    total_outstanding_amount = serializers.IntegerField(required=True)
    requested_late_fee_waiver_amount = serializers.IntegerField(required=True)
    requested_interest_waiver_amount = serializers.IntegerField(required=True)
    requested_principal_waiver_amount = serializers.IntegerField(required=True)
    total_requested_waiver_amount = serializers.IntegerField(required=True)
    remaining_late_fee_amount = serializers.IntegerField(required=True)
    remaining_interest_amount = serializers.IntegerField(required=True)
    remaining_principal_amount = serializers.IntegerField(required=True)
    total_remaining_amount = serializers.IntegerField(required=True)
    is_paid_off_after_ptp = serializers.BooleanField(required=True)

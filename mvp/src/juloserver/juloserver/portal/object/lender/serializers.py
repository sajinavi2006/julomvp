"""
serializer.py

"""
from rest_framework import serializers

class MintosUpdateSerializer(serializers.Serializer):
    mintos_id = serializers.IntegerField(required=True)
    mintos_loan_id = serializers.CharField(required=True)
    loan_status = serializers.CharField(required=True)
    loan_originator_id = serializers.CharField(required=False)
    loan_originator = serializers.CharField(required=False)
    country = serializers.CharField(required=False)
    interest_rate = serializers.FloatField(required=False)
    schedule_entries = serializers.IntegerField(required=False)
    initial_term = serializers.IntegerField(required=False)
    remaining_term = serializers.IntegerField(required=False)
    listed_on = serializers.DateTimeField(required=False)
    original_principal = serializers.FloatField(required=False)
    outstanding_principal = serializers.FloatField(required=False)
    invested = serializers.FloatField(required=False)
    invested_in_percent = serializers.FloatField(required=False)
    repaid_principal_to_investors = serializers.FloatField(required=False)
    acc_interest_investors = serializers.FloatField(required=False)
    repaid_interest_to_investors = serializers.FloatField(required=False)
    acc_interest_lenders = serializers.FloatField(required=False)
    acc_interest_mintos = serializers.FloatField(required=False)
    payment_status = serializers.CharField(required=False)
    collateral_value = serializers.CharField(required=False)
    ltv = serializers.CharField(required=False)
    collateral_type = serializers.CharField(required=False)
    listing_status = serializers.CharField(required=False)
    acc_late_payment_fee_investors = serializers.FloatField(required=False)
    acc_late_payment_fee_lenders = serializers.FloatField(required=False)
    currency = serializers.CharField(required=False)
    loan_type = serializers.CharField(required=False)
    buyback = serializers.CharField(required=False)
    loan_originator_account_id = serializers.CharField(required=False)
    total_invested = serializers.CharField(required=False)
    finished_at = serializers.CharField(required=False)
    repurchased_principal_from_investors = serializers.FloatField(required=False)
    repurchased_interest_from_investors = serializers.FloatField(required=False)
    bad_debt = serializers.CharField(required=False)
    buyback_reason = serializers.CharField(required=False)

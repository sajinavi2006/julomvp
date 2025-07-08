from __future__ import unicode_literals

from builtins import object
import logging
import re

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import LenderTransaction


logger = logging.getLogger(__name__)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True)


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for password change endpoint.
    """
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        validate_password(value)


class RegisterSerializer(serializers.Serializer):
    business_type = serializers.CharField(required=True)
    lender_address = serializers.CharField(required=True)
    lender_name = serializers.CharField(required=True)
    source_of_fund = serializers.CharField(required=True)
    poc_email = serializers.CharField(required=True)
    poc_name = serializers.CharField(required=True)
    poc_phone = serializers.CharField(required=True)
    poc_position = serializers.CharField(required=True)


class RegisterLenderWebSerializer(serializers.Serializer):
    business_type = serializers.CharField(required=True)
    lender_address = serializers.CharField(required=True)
    lender_name = serializers.CharField(required=True)
    source_of_fund = serializers.CharField(required=True)
    poc_email = serializers.CharField(required=True)
    poc_name = serializers.CharField(required=True)
    poc_phone = serializers.CharField(required=True)
    poc_position = serializers.CharField(required=True)
    npwp = serializers.FileField(required=True)
    akta = serializers.FileField(required=True)
    tdp = serializers.FileField(required=True)
    siup = serializers.FileField(required=True)
    nib = serializers.FileField(required=False)
    sk_menteri = serializers.FileField(required=True)
    skdp = serializers.FileField(required=True)


class ListApplicationSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=False)
    last_application_id = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False)
    order = serializers.CharField(required=False)


class ListBucketLenderSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField(required=False)
    last_bucket_id = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False)
    order = serializers.CharField(required=False)
    is_active = serializers.BooleanField(required=False)
    is_disbursed = serializers.BooleanField(required=False)
    is_signed = serializers.BooleanField(required=False)


class BucketLenderSerializer(serializers.Serializer):
    class _ApplicationIds(serializers.Serializer):
        approved = serializers.ListField(required=True)
        rejected = serializers.ListField(required=True)

    application_ids = _ApplicationIds()


class LenderAgreementSerializer(serializers.Serializer):
    approved_loan_ids = serializers.ListField(
        child=serializers.IntegerField(required=True)
    )


class CancelBucketSerializer(serializers.Serializer):
    bucket = serializers.JSONField(required=True)


class DisbursementSerializer(serializers.Serializer):
    bucket = serializers.JSONField(required=True)


class LoanAgreementSerializer(serializers.Serializer):
    application_xid = serializers.JSONField(required=True)


class LenderTransactionSerializer(serializers.ModelSerializer):
    type_transaction = serializers.ReadOnlyField()
    class Meta(object):
        model = LenderTransaction
        fields = ('id', 'type_transaction', 'cdate', 'transaction_description', 'transaction_amount')


class WithdrawalSerializer(serializers.Serializer):
    amount = serializers.IntegerField()

    def validate(self, data):
        amount = data['amount']
        if amount < 10000 or amount > 5*(10**8):
            raise serializers.ValidationError('Invalid amount')
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.CharField(required=True)


class DocumentStatusLenderSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField(required=False)


class SignedDocumentLenderSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField(required=True)
    signature_method = serializers.CharField(required=True)


class OJKSubmitFormSerializer(serializers.Serializer):
    fullname = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    email = serializers.CharField(required=True)

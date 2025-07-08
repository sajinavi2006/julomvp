from __future__ import unicode_literals

from builtins import object
import logging

from django.db.models import Sum
from rest_framework import serializers
from juloserver.julo.utils import verify_nik

from juloserver.julo.models import Customer

from .constants import LineTransactionType
from .models import (Invoice,
                     InvoiceDetail,
                     TransactionOne,
                     Statement)

from juloserver.julo.statuses import (LoanStatusCodes,
                                      PaymentStatusCodes)

logger = logging.getLogger(__name__)

class CustomerExistCheck(object):
    def validate_customer_xid(self, value):
        customer = Customer.objects.get_or_none(customer_xid=value)
        if not customer:
            raise serializers.ValidationError(
                "customer_xid %s not found" % value)
        return value


class ActivationSerializer(serializers.Serializer):
    ktp = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    phone_number = serializers.CharField(max_length=25, required=True)
    fullname = serializers.CharField(max_length=100, required=True)
    dob = serializers.DateField(required=True)
    gender = serializers.CharField(required=True)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    callback_url = serializers.CharField(required=True)
    account_opening_date = serializers.DateField(required=True)
    birthplace = serializers.CharField(required=True)
    seller_flag = serializers.CharField(required=True)
    identity_type = serializers.CharField(required=True)
    job = serializers.CharField(required=True)
    marital_status = serializers.CharField(required=True)
    reference_date = serializers.DateField(required=True)

    def validate_ktp(self, value):
        if not verify_nik(value):
            raise serializers.ValidationError("Invalid NIK")
        return value

    def validate_gender(self, value):
        choices = [x[0] for x in Customer.GENDER_CHOICES]
        if value not in choices:
            raise serializers.ValidationError("Invalid Gender")
        return value

    def validate(self, data):
        customer_exist_by_email = Customer.objects.get_or_none(email=data['email'])
        if customer_exist_by_email:
            if customer_exist_by_email.nik and customer_exist_by_email.nik != data['ktp']:
                raise serializers.ValidationError("Email is already registered with different Nik")
        return data


class ValidateSerializer(serializers.Serializer):
    customer_xid = serializers.IntegerField(required=True)
    limit = serializers.IntegerField(required=True)
    type = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class ScrapSerializer(CustomerExistCheck, serializers.Serializer):
    customer_xid = serializers.IntegerField(required=True)
    upload = serializers.FileField(required=True)


class InvoiceDetailSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(source='partner_transaction_id',
                                           required=True)
    status = serializers.CharField(required=True, source='partner_transaction_status')
    shipping_address = serializers.CharField(max_length=1000, required=True)
    items = serializers.JSONField(source='details')

    class Meta(object):
        model = InvoiceDetail
        exclude = ('id', 'cdate', 'udate')


class InvoiceSerializer(CustomerExistCheck, serializers.Serializer):
    customer_xid = serializers.IntegerField(required=True)
    invoice_amount = serializers.IntegerField(required=True)
    admin_fee = serializers.IntegerField(source='transaction_fee_amount', required=True)
    invoice_number = serializers.CharField(max_length=100, required=True)
    invoice_date = serializers.DateTimeField()
    due_date = serializers.DateField(source='invoice_due_date')
    status = serializers.CharField(max_length=100, required=True, source='invoice_status')
    # transactions = LineInvoiceDetailSerializer(many=True)

    class Meta(object):
        model = Invoice
        exclude = ('id', 'cdate', 'udate')


class RepaymentSerializer(CustomerExistCheck, serializers.Serializer):
    customer_xid = serializers.IntegerField(required=True)
    statement_id = serializers.IntegerField(required=True)
    paid_date = serializers.DateField(format="%Y-%m-%d", required=True)
    amount = serializers.IntegerField(required=True)
    method_type = serializers.CharField(required=True)
    method_name = serializers.CharField(required=True)
    account_number = serializers.CharField(required=True)
    payment_ref = serializers.CharField(required=True)
    invoice_creation_time = serializers.DateTimeField(required=True)

class TransactionHistory(CustomerExistCheck, serializers.Serializer):
    customer_xid = serializers.IntegerField(required=True)
    statement_id = serializers.IntegerField(required=False)
    last_statement_id = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False)
    order = serializers.CharField(required=False)


class StatementSerializer(serializers.ModelSerializer):
    statement_total_due_amount = serializers.ReadOnlyField()

    class Meta(object):
        model = Statement
        exclude = ('cdate', 'udate', 'customer_credit_limit', 'account_credit_limit', 'statement_paid_transaction_fee',
                   'statement_paid_interest', 'statement_paid_principal', 'statement_late_fee_applied',
                   'statement_paid_late_fee')


class TransactionSerializer(serializers.ModelSerializer):
    invoice_number = serializers.SerializerMethodField()

    def get_invoice_number(self, transaction):
        invoice_number = None
        if transaction.invoice:
            invoice_number = transaction.invoice.invoice_number

        return invoice_number

    class Meta(object):
        model = TransactionOne
        exclude = ('cdate', 'udate', 'id', 'customer_credit_limit', 'account_credit_limit', 'statement',
                   'disbursement_amount', 'invoice', 'invoice_detail', 'disbursement')


class InquirySerializer(CustomerExistCheck, serializers.Serializer):
    customer_xid = serializers.IntegerField(required=True)


class UpdateInvoiceDetailSerializer(serializers.Serializer):
    invoice_number = serializers.CharField(max_length=100, required=True)
    transaction_id = serializers.CharField(source='partner_transaction_id',
                                           required=True)
    status = serializers.CharField(required=True, source='partner_transaction_status')


class RefundSerializer(serializers.Serializer):
    invoice_number = serializers.CharField(max_length=100, required=True)
    transaction_id = serializers.CharField(source='partner_transaction_id',
                                           required=True)
    refund_amount = serializers.IntegerField(required=True)
    type = serializers.CharField(
        default=LineTransactionType.TYPE_REFUND.get('name'))

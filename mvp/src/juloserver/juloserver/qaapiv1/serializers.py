from __future__ import unicode_literals

import logging
from builtins import object

from rest_framework import serializers

from juloserver.julo.models import ApplicationHistory, Customer, Device, ProductLine

logger = logging.getLogger(__name__)


METHOD_CHOICES = ('Manual BCA', 'Manual CIMB')


class ApplicationHistorySerializers(serializers.Serializer):
    models = ApplicationHistory
    fields = ('application_id', 'new_status', 'cdate')


class CustomerSerializers(serializers.Serializer):
    models = Customer
    fields = ('customer_id', 'is_email_verified')


class DeviceSerializers(serializers.ModelSerializer):
    class Meta(object):
        model = Device


class ProductLineSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = ProductLine


class BugChampionLoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True)


class BugChampionForceChangeStatusSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    agent = serializers.CharField(max_length=50, required=True)
    notes = serializers.CharField(max_length=999999, required=True)
    newstatus = serializers.IntegerField(required=True)
    run_handler = serializers.BooleanField()


class BugChampionRescrapeActionSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)


class BugChampionActivateLoanManualDisburseSerializer(serializers.Serializer):
    application_ids = serializers.JSONField(write_only=True)
    method = serializers.ChoiceField(choices=METHOD_CHOICES, required=True)


class BugChampionPaymentEventSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField(write_only=True, required=True)
    amount = serializers.IntegerField(write_only=True, required=True)


class BugChampionUpdateLoanStatusSerializer(serializers.Serializer):
    loan_ids = serializers.CharField(write_only=True)


class BugChampionApplicationIdsSerializer(serializers.Serializer):
    application_ids = serializers.CharField(write_only=True)


class UnlockSerializer(serializers.Serializer):
    UNLOCK_TYPE = [('payment', 'Payment'), ('application', 'Application')]
    type = serializers.ChoiceField(choices=UNLOCK_TYPE)
    ids = serializers.CharField(write_only=True)


class PaymentSerializer(serializers.Serializer):
    payment_id = serializers.CharField(write_only=True)


class BugChampionKtpNameSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(write_only=True, required=True)
    name = serializers.CharField(required=True)


class BugChampionPaymentRestructureSerializer(serializers.Serializer):
    loan_id = serializers.IntegerField(write_only=True, required=True)
    starting_payment_number = serializers.IntegerField(write_only=True, required=True)
    principal_amount = serializers.IntegerField(write_only=True, required=True)
    interest_amount = serializers.IntegerField(write_only=True, required=True)
    late_fee = serializers.IntegerField(write_only=True, required=True)
    first_due_date = serializers.DateField(required=True)
    payment_count_to_restructure = serializers.IntegerField(write_only=True, required=True)


class ManualDisburseFakeCallBackSerializer(serializers.Serializer):
    bank_reference = serializers.CharField(required=True)
    application_id = serializers.IntegerField(required=True)

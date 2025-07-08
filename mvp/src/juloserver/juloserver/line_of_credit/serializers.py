from __future__ import unicode_literals

from builtins import object
from rest_framework import serializers
from .models import LineOfCreditTransaction


class LineOfCreditPurchaseSerializer(serializers.Serializer):
    pin = serializers.CharField(required=False)
    product_id = serializers.IntegerField()
    phone_number = serializers.CharField()
    total_customer_price = serializers.IntegerField()
    meter_number = serializers.CharField(required=False)
    account_name = serializers.CharField(required=False)

    def validate(self, data):
            """
            Check optional params.
            """
            if 'meter_number' not in data:
                data['meter_number'] = None
            if 'account_name' not in data:
                data['account_name'] = None
            return data


class LineOfCreditTransactionSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = LineOfCreditTransaction
        exclude = ('loc_statement', 'line_of_credit')


class LineOfCreditProductListByTypeViewSerializer(serializers.Serializer):
    """
    Serializer for line of credit product list by type and category.
    """
    type = serializers.CharField()
    category = serializers.CharField()
    operator_id = serializers.CharField(required=False)

    def validate(self, data):
            """
            Check optional params.
            """
            if 'operator_id' not in data:
                data['operator_id'] = None
            return data


class LineOfCreditProductInquryElectricityAccountSerializer(serializers.Serializer):
    """
    Serializer for line of credit product electricity account.
    """
    product_id = serializers.IntegerField()
    meter_number = serializers.CharField()

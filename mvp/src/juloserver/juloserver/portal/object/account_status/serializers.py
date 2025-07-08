from rest_framework import serializers


class LoanPaidOffLetterGeneratorSerializer(serializers.Serializer):
    selected_loan_ids = serializers.ListField(child=serializers.CharField(), required=True)

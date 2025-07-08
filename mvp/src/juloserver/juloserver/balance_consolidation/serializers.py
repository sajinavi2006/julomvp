from __future__ import unicode_literals
from rest_framework import serializers
import logging
from juloserver.disbursement.constants import NameBankValidationVendors
from juloserver.disbursement.services import get_list_validation_method
from juloserver.disbursement.models import NameBankValidation
from juloserver.julo.models import Bank
from juloserver.balance_consolidation.models import (
    BalanceConsolidation,
    BalanceConsolidationVerification,
)
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationMessageException,
    BalanceConsolidationStatus,
    MessageBankNameValidation,
)
from django.core.exceptions import ValidationError

from .utils import check_valid_loan_amount

logger = logging.getLogger(__name__)


class BalanceConsolidationSubmitSerializer(serializers.ModelSerializer):
    bank_id = serializers.IntegerField(required=True)
    bank_name = serializers.CharField(required=False)
    loan_duration = serializers.IntegerField(required=True)

    class Meta(object):
        model = BalanceConsolidation
        exclude = ('email', 'fullname', 'loan_agreement_document', 'customer')

    def validate(self, validate_data):
        loan_outstanding_amount = validate_data['loan_outstanding_amount']
        loan_principal_amount = validate_data['loan_principal_amount']
        if not check_valid_loan_amount(loan_principal_amount, loan_outstanding_amount):
            raise ValidationError(
                BalanceConsolidationMessageException.INVALID_LOAN_AMOUNT
            )

        bank = Bank.objects.filter(pk=validate_data.pop('bank_id', 0), is_active=True).last()
        if not bank:
            raise serializers.ValidationError("Bank not found")
        validate_data['bank_name'] = bank.bank_name
        return validate_data


class BankNameValidationSerializer(serializers.Serializer):
    consolidation_verification_id = serializers.IntegerField(required=True)
    bank_name = serializers.CharField(
        required=True, error_messages={"blank": "Bank name cannot be empty."}
    )
    account_number = serializers.RegexField(
        r'^\d+$',
        required=True,
        error_messages={
            "blank": "Bank account number cannot be empty.",
            "invalid": "Bank account number should contain only numbers.",
        },
    )
    name_in_bank = serializers.CharField(
        required=True, error_messages={"blank": "Name in bank cannot be empty."}
    )
    validation_method = serializers.ChoiceField(choices=NameBankValidationVendors.VENDOR_LIST)

    def validate_bank_name(self, bank_name):
        if not Bank.objects.filter(bank_name=bank_name).exists():
            raise serializers.ValidationError("Bank not found.")
        return bank_name

    def validate(self, validate_data):
        consolidation_verification = BalanceConsolidationVerification.objects.get_or_none(
            pk=validate_data['consolidation_verification_id']
        )
        if not consolidation_verification:
            raise serializers.ValidationError("Consolidation Verification not found.")

        if consolidation_verification.validation_status != BalanceConsolidationStatus.ON_REVIEW:
            raise serializers.ValidationError(
                MessageBankNameValidation.NAME_BANK_FAIL_CAUSE_APPROVED_CONSOLIDATION
            )
        validate_data['consolidation_verification'] = consolidation_verification
        return validate_data


class BankNameValidationDetailSerializer(serializers.ModelSerializer):
    list_method = serializers.SerializerMethodField()
    bank_account_number = serializers.SerializerMethodField()
    bank_name = serializers.SerializerMethodField()

    class Meta:
        model = NameBankValidation
        fields = '__all__'

    def get_bank_account_number(self, obj):
        return obj.account_number

    def get_list_method(self, obj):
        return get_list_validation_method()

    def get_bank_name(self, obj):
        return obj.bank_name

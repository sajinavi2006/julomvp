from rest_framework import serializers

from juloserver.channeling_loan.constants.dbs_constants import (
    DBSChannelingUpdateLoanStatusConst,
    JULO_ORG_ID_GIVEN_BY_DBS,
)

from juloserver.channeling_loan.utils import parse_numbers_only


class DBSMessageHeaderSerializer(serializers.Serializer):
    msgId = serializers.CharField(
        max_length=36,
        help_text="Unique identifier for API request "
        "and it should be same as passed in HTTP header X-DBS-uuid",
    )
    timeStamp = serializers.CharField(help_text="Date and time of the request or response")


class DBSUpdateLoanStatusRequestSerializer(serializers.Serializer):
    class MessageHeaderRequestSerializer(DBSMessageHeaderSerializer):
        orgId = serializers.CharField(
            max_length=36, help_text="Unique Organization ID provided by DBS"
        )

        def validate_orgId(self, orgId):
            if orgId != self.context.get(DBSChannelingUpdateLoanStatusConst.HTTP_X_DBS_ORG_ID):
                raise serializers.ValidationError("orgId does not match with the one in header")

            if orgId != JULO_ORG_ID_GIVEN_BY_DBS:
                raise serializers.ValidationError("orgId does not match with the one given by DBS")

            return orgId

    class DataRequestSerializer(serializers.Serializer):
        class LoanApplicationStatusRequestSerializer(serializers.Serializer):
            class RejectionReasonSerializer(serializers.Serializer):
                rejectCode = serializers.CharField(
                    help_text="Code representing the reason for rejection"
                )
                rejectDescription = serializers.CharField(
                    help_text="Detailed description of the rejection reason"
                )

            contractNumber = serializers.CharField(help_text="Customer contract number")
            appStatus = serializers.CharField(help_text="Current status of loan")
            accountNumber = serializers.CharField(
                required=False, allow_null=True, help_text="DBS system account number"
            )
            interestRate = serializers.CharField(
                required=False, allow_null=True, help_text="Interest of the loan"
            )
            principalAmount = serializers.DecimalField(
                max_digits=20,
                decimal_places=2,
                required=False,
                allow_null=True,
                help_text="Principal amount of loan",
            )
            interestAmount = serializers.DecimalField(
                max_digits=20,
                decimal_places=2,
                required=False,
                allow_null=True,
                help_text="Interest amount for loan",
            )
            installmentAmount = serializers.DecimalField(
                max_digits=20,
                decimal_places=2,
                required=False,
                allow_null=True,
                help_text="Amount of each installment",
            )
            adminFee = serializers.DecimalField(
                max_digits=20,
                decimal_places=2,
                required=False,
                allow_null=True,
                help_text="Administrative fee for loan",
            )
            currency = serializers.CharField(
                max_length=3, required=False, allow_null=True, help_text="Currency of the amounts"
            )
            rejectReasons = RejectionReasonSerializer(
                many=True,
                required=False,
                help_text="List of reasons if the application is rejected",
            )

        loanApplicationStatusRequest = LoanApplicationStatusRequestSerializer()

    header = MessageHeaderRequestSerializer()
    data = DataRequestSerializer()

    @property
    def loan_xid(self):
        # e.g., JUL001217395621. Parse numbers only and convert to int to remove leading zeros
        return int(
            parse_numbers_only(
                self.validated_data['data']['loanApplicationStatusRequest']['contractNumber']
            )
        )

    @property
    def is_rejected(self):
        # rejectReasons is optional field
        return bool(
            self.validated_data['data']['loanApplicationStatusRequest'].get('rejectReasons', [])
        )

    @property
    def rejected_reason(self):
        reasons = self.validated_data['data']['loanApplicationStatusRequest'].get(
            'rejectReasons', []
        )
        return ', '.join([reason['rejectDescription'] for reason in reasons])


class DBSUpdateLoanStatusSuccessResponseSerializer(serializers.Serializer):
    class DataResponseSerializer(serializers.Serializer):
        class LoanApplicationStatusResponseSerializer(serializers.Serializer):
            receiptDateTime = serializers.CharField(
                help_text="Date and time of the request received by partner"
            )

        loanApplicationStatusResponse = LoanApplicationStatusResponseSerializer()

    header = DBSMessageHeaderSerializer()
    data = DataResponseSerializer()


class DBSUpdateLoanStatusFailedResponseSerializer(serializers.Serializer):
    class DataResponseSerializer(serializers.Serializer):
        class ErrorListResponseSerializer(serializers.Serializer):
            class ErrorResponseSerializer(serializers.Serializer):
                code = serializers.CharField(max_length=10, help_text="Error code")
                message = serializers.CharField(max_length=250, help_text="Error message")
                moreInfo = serializers.CharField(
                    max_length=36, help_text="Additional error information"
                )

            errorList = ErrorResponseSerializer(many=True)

        error = ErrorListResponseSerializer()

    header = DBSMessageHeaderSerializer()
    data = DataResponseSerializer()

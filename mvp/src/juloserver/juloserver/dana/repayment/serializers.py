from typing import Dict, List
from datetime import datetime
from django.utils.dateparse import parse_datetime

from rest_framework import serializers, status

from juloserver.dana.exceptions import APIError
from juloserver.dana.models import (
    DanaCustomerData,
    DanaPaymentBill,
    DanaRepaymentReference,
)
from juloserver.dana.constants import (
    DanaProductType,
    RepaymentResponseCodeMessage,
    BILL_STATUS_PAID_OFF,
    BILL_STATUS_PARTIAL,
)
from juloserver.julo.models import Payment


class DanaRepaymentDetailSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """

    billId = serializers.CharField()
    billStatus = serializers.CharField()
    repaymentPrincipalAmount = serializers.DictField()
    repaymentInterestFeeAmount = serializers.DictField()
    repaymentLateFeeAmount = serializers.DictField()
    totalRepaymentAmount = serializers.DictField()
    waivedPrincipalAmount = serializers.DictField(required=False)
    waivedInterestFeeAmount = serializers.DictField(required=False)
    waivedLateFeeAmount = serializers.DictField(required=False)
    totalWaivedAmount = serializers.DictField(required=False)

    def validate_repaymentPrincipalAmount(self, value: Dict) -> Dict:
        if not value.get("value") or not value.get("currency"):
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {
                        'repaymentPrincipalAmount': [
                            "repaymentPrincipalAmount objects doesn't have value or currency"
                        ]
                    }
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            float(value.get("value"))
        except ValueError:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {'repaymentPrincipalAmount': ["value is not a number"]}
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_repaymentInterestFeeAmount(self, value: Dict) -> Dict:
        if not value.get("value") or not value.get("currency"):
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {
                        'repaymentInterestFeeAmount': [
                            "repaymentInterestFeeAmount objects doesn't have value or currency"
                        ]
                    }
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            float(value.get("value"))
        except ValueError:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {'repaymentInterestFeeAmount': ["value is not a number"]}
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_repaymentLateFeeAmount(self, value: Dict) -> Dict:
        if not value.get("value") or not value.get("currency"):
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {
                        'repaymentLateFeeAmount': [
                            "repaymentLateFeeAmount objects doesn't have value or currency"
                        ]
                    }
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            float(value.get("value"))
        except ValueError:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {'errors': {'repaymentLateFeeAmount': ["value is not a number"]}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_totalRepaymentAmount(self, value: Dict) -> Dict:
        if not value.get("value") or not value.get("currency"):
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {
                        'totalRepaymentAmount': [
                            "totalRepaymentAmount objects doesn't have value or currency"
                        ]
                    }
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            float(value.get("value"))
        except ValueError:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {'errors': {'totalRepaymentAmount': ["value is not a number"]}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_waived_amount(self, value: Dict, field_name: str) -> Dict:
        if value:
            if not value.get("value") or not value.get("currency"):
                response_data = {
                    'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                    'additionalInfo': {
                        'errors': {
                            field_name: [
                                "{} objects doesn't have value or currency".format(field_name)
                            ]
                        }
                    },
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )
            try:
                float(value.get("value"))
            except ValueError:
                response_data = {
                    'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                    'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                    'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                    'additionalInfo': {'errors': {field_name: ["value is not a number"]}},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response_data,
                )
            return value

    def validate_waivedPrincipalAmount(self, value: Dict) -> Dict:
        return self.validate_waived_amount(value, "waivedPrincipalAmount")

    def validate_waivedInterestFeeAmount(self, value: Dict) -> Dict:
        return self.validate_waived_amount(value, "waivedInterestFeeAmount")

    def validate_waivedLateFeeAmount(self, value: Dict) -> Dict:
        return self.validate_waived_amount(value, "waivedLateFeeAmount")

    def validate_totalWaivedAmount(self, value: Dict) -> Dict:
        return self.validate_waived_amount(value, "totalWaivedAmount")

    def validate_billId(self, value: str) -> str:
        customer_id = self.root.initial_data.get('customerId')
        if not customer_id:
            return value

        payment_ids = Payment.objects.filter(
            loan__account__dana_customer_data__dana_customer_identifier=customer_id
        ).values_list('id', flat=True)

        payment_id_set = set(payment_ids)

        dana_payment_bill = (
            DanaPaymentBill.objects.filter(
                bill_id=value,
                payment_id__in=payment_id_set,
            )
            .only('id', 'payment_id')
            .last()
        )

        response_data = {
            'responseCode': RepaymentResponseCodeMessage.BAD_REQUEST.code,
            'responseMessage': RepaymentResponseCodeMessage.BAD_REQUEST.message,
            'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
            'additionalInfo': {},
        }
        if not dana_payment_bill:
            response_data['additionalInfo']['errors'] = {"billId": ["billId not found"]}
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        return value

    def validate_billStatus(self, value: str) -> str:
        if value not in {BILL_STATUS_PARTIAL, BILL_STATUS_PAID_OFF}:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.root.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {
                        'billStatus': [
                            "value should be {} or {}".format(
                                BILL_STATUS_PARTIAL, BILL_STATUS_PAID_OFF
                            )
                        ]
                    }
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value


class DanaRepaymentSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """

    partnerReferenceNo = serializers.CharField(max_length=128)
    customerId = serializers.CharField(max_length=64)
    repaidTime = serializers.CharField(max_length=25)
    creditUsageMutation = serializers.DictField()
    lenderProductId = serializers.CharField(max_length=64)
    repaymentDetailList = serializers.ListField(child=DanaRepaymentDetailSerializer())
    additionalInfo = serializers.DictField(required=False)

    def validate_lenderProductId(self, value: str) -> str:
        if value and value not in {DanaProductType.CASH_LOAN, DanaProductType.CICIL}:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {'errors': {'lenderProductId': ["value not valid"]}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_repaidTime(self, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {'error': {"repaidTime": ["invalid format value"]}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_customerId(self, value: str) -> str:
        dana_customer_data = DanaCustomerData.objects.filter(
            dana_customer_identifier=value
        ).exists()
        if not dana_customer_data:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.BAD_REQUEST.code,
                'responseMessage': RepaymentResponseCodeMessage.BAD_REQUEST.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {'error': {"customerId": ["customerId doesn't exists"]}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate_creditUsageMutation(self, value: Dict) -> Dict:
        if not value.get("value") or not value.get("currency"):
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {
                        'creditUsageMutation': [
                            "creditUsageMutation objects doesn't have value or currency"
                        ]
                    }
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        try:
            float(value.get("value"))
        except ValueError:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {'errors': {'creditUsageMutation': ["value is not a number"]}},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return value

    def validate(self, data: Dict) -> Dict:
        customer_id = data.get('customerId')
        partner_reference_no = data.get('partnerReferenceNo')
        repayment_detail = data.get('repaymentDetailList')

        if not repayment_detail:
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RepaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {
                    'errors': {'repaymentDetailList': ["repaymentDetailList is required"]}
                },
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )

        dana_repayment_references = DanaRepaymentReference.objects.filter(
            partner_reference_no=partner_reference_no, customer_id=customer_id
        ).order_by('bill_id')
        if self._is_inconsistent_repayment_with_dana_repayment_references(
            repayment_detail, dana_repayment_references
        ):
            response_data = {
                'responseCode': RepaymentResponseCodeMessage.INCONSISTENT_REQUEST.code,
                'responseMessage': RepaymentResponseCodeMessage.INCONSISTENT_REQUEST.message,
                'partnerReferenceNo': self.initial_data.get('partnerReferenceNo'),
                'additionalInfo': {},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response_data,
            )
        return data

    def _is_inconsistent_repayment_with_dana_repayment_references(
        self, repayments: List, dana_repayment_references: List[DanaRepaymentReference]
    ) -> bool:
        if not dana_repayment_references:
            return False
        if len(repayments) != len(dana_repayment_references):
            return True
        for idx in range(len(dana_repayment_references)):
            bill_id = repayments[idx]['billId']
            bill_status = repayments[idx]['billStatus']
            repayment_principal = float(repayments[idx]['repaymentPrincipalAmount']['value'])
            repayment_interest = float(repayments[idx]['repaymentInterestFeeAmount']['value'])
            repayment_late_fee = float(repayments[idx]['repaymentLateFeeAmount']['value'])
            repayment_total = float(repayments[idx]['totalRepaymentAmount']['value'])
            if not (
                dana_repayment_references[idx].bill_id == bill_id
                and dana_repayment_references[idx].bill_status == bill_status
                and dana_repayment_references[idx].principal_amount == repayment_principal
                and dana_repayment_references[idx].interest_fee_amount == repayment_interest
                and dana_repayment_references[idx].late_fee_amount == repayment_late_fee
                and dana_repayment_references[idx].total_repayment_amount == repayment_total
            ):
                return True
        return False


class DanaRepaymentSettlementSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """

    partnerId = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    lenderProductId = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    partnerReferenceNo = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    billId = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    billStatus = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    principalAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    interestFeeAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    lateFeeAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    totalAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    transTime = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    waivedPrincipalAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    waivedInterestFeeAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    waivedLateFeeAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    totalWaivedAmount = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, data: Dict) -> Dict:
        errors = []
        partner_reference_no = data.get('partnerReferenceNo')
        bill_id = data.get('billId')
        bill_status = data.get('billStatus')
        principal_amount = data.get('principalAmount')
        interest_fee_amount = data.get('interestFeeAmount')
        late_fee_amount = data.get('lateFeeAmount')
        total_amount = data.get('totalAmount')
        trans_time = data.get('transTime')
        waived_principal_amount = data.get('waivedPrincipalAmount')
        waived_interest_fee_amount = data.get('waivedInterestFeeAmount')
        waived_late_fee_amount = data.get('waivedLateFeeAmount')
        total_waived_amount = data.get('totalWaivedAmount')

        if not partner_reference_no:
            errors.append("Partner reference no tidak boleh kosong")

        if not bill_id:
            errors.append("Bill ID tidak boleh kosong")

        if not bill_status:
            errors.append("Bill status tidak boleh kosong")

        if bill_status and bill_status not in {BILL_STATUS_PAID_OFF, BILL_STATUS_PARTIAL}:
            errors.append("Bill status not PAID or INIT")

        if not principal_amount:
            errors.append("Principal amount tidak boleh kosong")
        elif principal_amount:
            try:
                float(principal_amount)
            except Exception:
                errors.append("Principal amount harus angka")

        if not interest_fee_amount:
            errors.append("Interest amount tidak boleh kosong")
        elif interest_fee_amount:
            try:
                float(interest_fee_amount)
            except Exception:
                errors.append("Interest amount harus angka")

        if not late_fee_amount:
            errors.append("Late fee amount tidak boleh kosong")
        elif late_fee_amount:
            try:
                float(late_fee_amount)
            except Exception:
                errors.append("Late fee amount harus angka")

        if not total_amount:
            errors.append("Total amount tidak boleh kosong")
        elif total_amount:
            try:
                float(total_amount)
            except Exception:
                errors.append("Total amount harus angka")

        if not trans_time:
            errors.append("Trans time tidak boleh kosong")
        elif trans_time:
            formatted_trans_time = parse_datetime(trans_time)
            if not formatted_trans_time:
                errors.append("Trans time Format tidak valid")

        is_exist_bill_id = DanaPaymentBill.objects.filter(bill_id=bill_id).exists()

        if not is_exist_bill_id:
            errors.append("Bill Id tidak ditemukan")

        is_all_amount_valid = (
            principal_amount and interest_fee_amount and late_fee_amount and total_amount
        )

        if is_all_amount_valid:
            total_amount_sended = (
                float(principal_amount) + float(interest_fee_amount) + float(late_fee_amount)
            )
            if total_amount_sended != float(total_amount):
                errors.append("Total amount tidak sama dengan principal + interest + late_fee ")

        err_waived_principal = validate_waived_amount(
            waived_principal_amount, "Waived principal amount"
        )
        if err_waived_principal:
            errors.append(err_waived_principal)

        err_waived_interest_fee = validate_waived_amount(
            waived_interest_fee_amount, "Waived interest fee amount"
        )
        if err_waived_interest_fee:
            errors.append(err_waived_interest_fee)

        err_waived_late_fee = validate_waived_amount(
            waived_late_fee_amount, "Waived late fee amount"
        )
        if err_waived_late_fee:
            errors.append(err_waived_late_fee)

        err_total_waived = validate_waived_amount(total_waived_amount, "Total waived amount")
        if err_total_waived:
            errors.append(err_total_waived)

        if errors:
            raise serializers.ValidationError(errors)

        return data


def validate_waived_amount(amount, field_name):
    if amount:
        try:
            float(amount)
        except ValueError:
            return "{} harus angka".format(field_name)

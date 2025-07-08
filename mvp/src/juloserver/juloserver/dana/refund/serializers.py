from typing import (
    Dict,
    List,
    Any,
)
from collections import defaultdict
from datetime import datetime
from django.utils.dateparse import parse_datetime

from rest_framework import status

from juloserver.dana.exceptions import (
    APIError,
    APIInvalidFieldFormatError,
    APIMandatoryFieldError,
)
from juloserver.dana.models import (
    DanaCustomerData,
    DanaRefundReference,
    DanaLoanReference,
    DanaPaymentBill,
    DanaRepaymentReference,
)
from juloserver.dana.constants import (
    RefundResponseCodeMessage,
    BILL_STATUS_CANCEL,
)
from juloserver.julo.models import Payment

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.dana.constants import DanaRefundErrorMessage

from rest_framework import serializers


def is_consistent_bill_id(
    dana_loan_reference: DanaLoanReference,
    refund_bill_detail_list: List,
    refunded_repayment_detail_list: list,
) -> bool:
    loan = dana_loan_reference.loan
    payments = Payment.objects.filter(loan=loan)
    payment_ids = set(payments.values_list('id', flat=True))
    dana_payment_bill_id_list = (
        DanaPaymentBill.objects.filter(payment_id__in=payment_ids)
        .values_list('bill_id', flat=True)
        .order_by('bill_id')
    )

    bill_ids_bill_detail_list = [value['billId'] for value in refund_bill_detail_list]
    bill_ids_bill_detail_list.sort()

    unique_existing_bill_id = set(dana_payment_bill_id_list)
    unique_incoming_bill_id = set(bill_ids_bill_detail_list)

    if unique_existing_bill_id != unique_incoming_bill_id:
        return True

    existing_dana_repayment_reference_bills = (
        DanaRepaymentReference.objects.filter(payment__loan=loan)
        .values('bill_id', 'partner_reference_no')
        .order_by('bill_id')
    )

    # Validation check to make sure all repayment already registered, should be check based on
    # PartnerReferenceNo and bill id from dana_repayment_reference
    incoming_repayment_bills_mapping = defaultdict(list)
    for incoming_repayment_bill in refunded_repayment_detail_list:
        incoming_repayment_bills_mapping[incoming_repayment_bill['billId']].append(
            incoming_repayment_bill['repaymentPartnerReferenceNo']
        )

    existing_repayment_bills_mapping = defaultdict(list)
    for existing_repayment_bill in existing_dana_repayment_reference_bills:
        existing_repayment_bills_mapping[existing_repayment_bill['bill_id']].append(
            existing_repayment_bill['partner_reference_no']
        )

    for refunded_repayment in refunded_repayment_detail_list:
        bill_id = refunded_repayment['billId']
        if bill_id not in existing_repayment_bills_mapping:
            return True

        partner_ref_no = str(refunded_repayment['repaymentPartnerReferenceNo'])
        if partner_ref_no not in existing_repayment_bills_mapping[bill_id]:
            return True

    for existing_repayment in existing_dana_repayment_reference_bills:
        bill_id = existing_repayment['bill_id']
        if bill_id not in incoming_repayment_bills_mapping:
            return True

        partner_ref_no = str(existing_repayment['partner_reference_no'])
        if partner_ref_no not in incoming_repayment_bills_mapping[bill_id]:
            return True

    return False


def validate_refund_format(data, field, parent_key) -> Any:
    for key, val in field.items():
        request_val = data.get(key)
        key_name = key
        if parent_key:
            key_name = parent_key + '.' + key

        if not (key in data.keys()):
            if val.get('mandatory'):
                if parent_key == 'additionalInfo.refundedRepaymentDetailList':
                    raise APIInvalidFieldFormatError(
                        detail={key_name: DanaRefundErrorMessage.REQUIRED_FIELD},
                    )
                else:
                    raise APIMandatoryFieldError(
                        detail={key_name: DanaRefundErrorMessage.REQUIRED_FIELD},
                    )
            else:
                continue

        if val.get('mandatory') and not request_val:
            if parent_key == 'additionalInfo.refundedRepaymentDetailList':
                raise APIInvalidFieldFormatError(
                    detail={key_name: DanaRefundErrorMessage.BLANK_FIELD},
                )
            else:
                raise APIMandatoryFieldError(
                    detail={key_name: DanaRefundErrorMessage.BLANK_FIELD},
                )

        if val.get('rule_type') == 'max' and len(request_val) > val.get('rule_val'):
            raise APIInvalidFieldFormatError(
                detail={key_name: DanaRefundErrorMessage.MAX_CHAR},
            )

        if val.get('rule_type') == 'money':
            value = request_val.get('value')
            currency = request_val.get('currency')
            if not ('value' in request_val.keys()) or not ('currency' in request_val.keys()):
                raise APIMandatoryFieldError(
                    detail={key_name: 'Objects does not have value or currency'},
                )

            if not value:
                raise APIMandatoryFieldError(
                    detail={key_name + '.value': DanaRefundErrorMessage.BLANK_FIELD},
                )
            if not currency:
                raise APIMandatoryFieldError(
                    detail={key_name + '.currency': DanaRefundErrorMessage.BLANK_FIELD},
                )
            try:
                float(value)
            except ValueError:
                raise APIInvalidFieldFormatError(
                    detail={key_name: DanaRefundErrorMessage.NOT_NUMBER},
                )

        if val.get('rule_type') == 'datetime':
            try:
                datetime.strptime(request_val, val['rule_val'])
            except ValueError:
                raise APIInvalidFieldFormatError(
                    detail={key_name: DanaRefundErrorMessage.INVALID_FORMAT},
                )

        if val.get('is_number'):
            try:
                float(request_val)
            except ValueError:
                raise APIInvalidFieldFormatError(
                    detail={key_name: DanaRefundErrorMessage.NOT_NUMBER},
                )


def validate_form_dana_refund(data) -> Dict:
    refund_fields = {
        'originalPartnerReferenceNo': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'originalReferenceNo': {'mandatory': False, 'rule_type': 'max', 'rule_val': 64},
        'originalExternalId': {'mandatory': False, 'rule_type': 'max', 'rule_val': 64},
        'partnerRefundNo': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'refundAmount': {'mandatory': True, 'rule_type': 'money'},
        'reason': {'mandatory': False, 'rule_type': 'max', 'rule_val': 256},
        'additionalInfo': {'mandatory': True, 'rule_type': 'object'},
    }

    validate_refund_format(data, refund_fields, '')

    refund_addt_fields = {
        'customerId': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'refundTime': {
            'mandatory': True,
            'rule_type': 'datetime',
            'rule_val': '%Y-%m-%dT%H:%M:%S%z',
        },
        'lenderProductId': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'creditUsageMutation': {'mandatory': True, 'rule_type': 'money'},
        'refundedOriginalOrderAmount': {'mandatory': True, 'rule_type': 'money'},
        'disburseBackAmount': {'mandatory': True, 'rule_type': 'money'},
        'refundedTransaction': {'mandatory': True, 'rule_type': 'object'},
        'refundedRepaymentDetailList': {'mandatory': False, 'rule_type': 'list'},
    }

    additional_info = data.get('additionalInfo')
    validate_refund_format(additional_info, refund_addt_fields, 'additionalInfo')

    refund_trx_fields = {
        'refundedPartnerReferenceNo': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'refundedBillDetailList': {'mandatory': True, 'rule_type': 'list'},
    }

    refunded_transaction = additional_info.get('refundedTransaction')
    validate_refund_format(
        refunded_transaction, refund_trx_fields, 'additionalInfo.refundedTransaction'
    )

    refund_bills_fields = {
        'periodNo': {'mandatory': True, 'rule_type': 'max', 'rule_val': 2, 'is_number': True},
        'billId': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'dueDate': {'mandatory': True, 'rule_type': 'datetime', 'rule_val': '%Y%m%d'},
        'principalAmount': {'mandatory': True, 'rule_type': 'money'},
        'interestFeeAmount': {'mandatory': True, 'rule_type': 'money'},
        'lateFeeAmount': {'mandatory': True, 'rule_type': 'money'},
        'totalAmount': {'mandatory': True, 'rule_type': 'money'},
        'paidInterestFeeAmount': {'mandatory': True, 'rule_type': 'money'},
        'paidLateFeeAmount': {'mandatory': True, 'rule_type': 'money'},
        'paidPrincipalAmount': {'mandatory': True, 'rule_type': 'money'},
        'totalPaidAmount': {'mandatory': True, 'rule_type': 'money'},
        'waivedInterestFeeAmount': {'mandatory': False, 'rule_type': 'money'},
        'waivedLateFeeAmount': {'mandatory': False, 'rule_type': 'money'},
        'waivedPrincipalAmount': {'mandatory': False, 'rule_type': 'money'},
        'totalWaivedAmount': {'mandatory': False, 'rule_type': 'money'},
    }

    refund_bills_list = refunded_transaction.get('refundedBillDetailList') or []
    for bill in refund_bills_list:
        validate_refund_format(
            bill, refund_bills_fields, 'additionalInfo.refundedTransaction.refundedBillDetailList'
        )

    refund_rpy_fields = {
        'billId': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'repaymentPartnerReferenceNo': {'mandatory': True, 'rule_type': 'max', 'rule_val': 64},
        'refundedRepaymentPrincipalAmount': {'mandatory': True, 'rule_type': 'money'},
        'refundedRepaymentInterestFeeAmount': {'mandatory': True, 'rule_type': 'money'},
        'refundedRepaymentLateFeeAmount': {'mandatory': True, 'rule_type': 'money'},
        'refundedTotalRepaymentAmount': {'mandatory': True, 'rule_type': 'money'},
        'refundedWaivedPrincipalAmount': {'mandatory': False, 'rule_type': 'money'},
        'refundedWaivedInterestFeeAmount': {'mandatory': False, 'rule_type': 'money'},
        'refundedWaivedLateFeeAmount': {'mandatory': False, 'rule_type': 'money'},
        'refundedTotalWaivedAmount': {'mandatory': False, 'rule_type': 'money'},
    }

    refund_repayment_list = additional_info.get('refundedRepaymentDetailList') or []
    for rpy in refund_repayment_list:
        validate_refund_format(rpy, refund_rpy_fields, 'additionalInfo.refundedRepaymentDetailList')

    partner_refund_no = data.get('partnerRefundNo')
    partner_reference_no = data.get('originalPartnerReferenceNo')

    dana_customer_data = DanaCustomerData.objects.get_or_none(
        dana_customer_identifier=additional_info.get('customerId'),
        lender_product_id=additional_info.get('lenderProductId'),
    )
    if not dana_customer_data:
        response_data = {
            'responseCode': RefundResponseCodeMessage.BAD_REQUEST.code,
            'responseMessage': RefundResponseCodeMessage.BAD_REQUEST.message,
            'partnerRefundNo': partner_refund_no,
            'originalPartnerReferenceNo': partner_reference_no,
            'additionalInfo': {'error': {"customerId": "customerId doesn't exists"}},
        }
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=response_data,
        )

    resp_additional_info = {}
    refunded_bill_detail_list = refund_bills_list or []
    refunded_repayment_detail_list = refund_repayment_list or []

    existed_dana_refund_reference = DanaRefundReference.objects.filter(
        partner_refund_no=partner_refund_no
    ).last()

    dana_loan_reference = DanaLoanReference.objects.filter(
        partner_reference_no=partner_reference_no
    ).last()

    if not dana_loan_reference:
        resp_additional_info['errorMessage'] = "Partner reference no is not valid"
        response_data = {
            'responseCode': RefundResponseCodeMessage.BAD_REQUEST.code,
            'responseMessage': RefundResponseCodeMessage.BAD_REQUEST.message,
            'partnerRefundNo': partner_refund_no,
            'originalPartnerReferenceNo': partner_reference_no,
            'additionalInfo': resp_additional_info,
        }
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=response_data,
        )

    if not dana_loan_reference.loan:
        resp_additional_info['errorMessage'] = "Loan not found"
        response_data = {
            'responseCode': RefundResponseCodeMessage.GENERAL_ERROR.code,
            'responseMessage': RefundResponseCodeMessage.GENERAL_ERROR.message,
            'partnerRefundNo': partner_refund_no,
            'originalPartnerReferenceNo': partner_reference_no,
            'additionalInfo': resp_additional_info,
        }
        raise APIError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=response_data,
        )

    if dana_loan_reference.loan.status < LoanStatusCodes.CURRENT:
        resp_additional_info['errorMessage'] = "Loan status is not valid"
        response_data = {
            'responseCode': RefundResponseCodeMessage.BAD_REQUEST.code,
            'responseMessage': RefundResponseCodeMessage.BAD_REQUEST.message,
            'partnerRefundNo': partner_refund_no,
            'originalPartnerReferenceNo': partner_reference_no,
            'additionalInfo': resp_additional_info,
        }
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=response_data,
        )

    if (
        existed_dana_refund_reference
        and existed_dana_refund_reference.original_partner_reference_no != partner_reference_no
    ):
        resp_additional_info['errorMessage'] = "Existing partnerRefundNo but different number"
        response_data = {
            'responseCode': RefundResponseCodeMessage.INCONSISTENT_REQUEST.code,
            'responseMessage': RefundResponseCodeMessage.INCONSISTENT_REQUEST.message,
            'partnerRefundNo': partner_refund_no,
            'originalPartnerReferenceNo': partner_reference_no,
            'additionalInfo': {
                'errorMessage': "Existing partnerRefundNo but different partnerReferenceNo"
            },
        }

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=response_data,
        )

    if is_consistent_bill_id(
        dana_loan_reference,
        refunded_bill_detail_list,
        refunded_repayment_detail_list,
    ):
        resp_additional_info[
            'errorMessage'
        ] = "Bill Id not valid with the payment partnerReferenceNo"
        response_data = {
            'responseCode': RefundResponseCodeMessage.BAD_REQUEST.code,
            'responseMessage': RefundResponseCodeMessage.BAD_REQUEST.message,
            'partnerRefundNo': partner_refund_no,
            'originalPartnerReferenceNo': partner_reference_no,
            'additionalInfo': resp_additional_info,
        }
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=response_data,
        )

    return data


class DanaRefundRepaymentSettlementSerializer(serializers.Serializer):
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
        lender_product_id = data.get('lenderProductId')
        partner_reference_no = data.get('partnerReferenceNo')
        bill_id = data.get('billId')
        bill_status = data.get('billStatus')
        principal_amount = data.get('principalAmount', None)
        interest_fee_amount = data.get('interestFeeAmount', None)
        late_fee_amount = data.get('lateFeeAmount', None)
        total_amount = data.get('totalAmount', None)
        trans_time = data.get('transTime')
        waived_principal_amount = data.get('waivedPrincipalAmount', 0)
        waived_interest_fee_amount = data.get('waivedInterestFeeAmount', 0)
        waived_late_fee_amount = data.get('waivedLateFeeAmount', 0)
        total_waived_amount = data.get('totalWaivedAmount', 0)

        if not lender_product_id:
            errors.append("lender product id tidak boleh kosong")

        if not partner_reference_no:
            errors.append("Partner reference no tidak boleh kosong")

        if not bill_id:
            errors.append("Bill ID tidak boleh kosong")

        if not bill_status:
            errors.append("Bill status tidak boleh kosong")

        if bill_status and bill_status != BILL_STATUS_CANCEL:
            errors.append("Bill status tidak valid, bill status harus CANCEL")

        # Principal
        if not principal_amount:
            errors.append("Principal amount tidak boleh kosong")

        try:
            float(principal_amount)
        except (TypeError, ValueError):
            errors.append("Principal amount harus angka")

        # Interest
        if not interest_fee_amount:
            errors.append("Interest amount tidak boleh kosong")

        try:
            float(interest_fee_amount)
        except (TypeError, ValueError):
            errors.append("Interest amount harus angka")

        # Late Fee
        if not late_fee_amount:
            errors.append("Late fee amount tidak boleh kosong")

        try:
            float(late_fee_amount)
        except (TypeError, ValueError):
            errors.append("Late fee amount harus angka")

        # Total Amount
        if not total_amount:
            errors.append("Total amount tidak boleh kosong")

        try:
            float(total_amount)
        except (TypeError, ValueError):
            errors.append("Total amount harus angka")

        if not trans_time:
            errors.append("Trans time tidak boleh kosong")

        if trans_time:
            formatted_trans_time = parse_datetime(trans_time)
            if not formatted_trans_time:
                errors.append("Trans time Format tidak valid")

        if waived_principal_amount:
            try:
                float(waived_principal_amount)
            except (TypeError, ValueError):
                errors.append("Waived principal amount harus angka")

        if waived_interest_fee_amount:
            try:
                float(waived_interest_fee_amount)
            except (TypeError, ValueError):
                errors.append("Waived interest fee amount harus angka")

        if waived_late_fee_amount:
            try:
                float(waived_late_fee_amount)
            except (TypeError, ValueError):
                errors.append("Waived late fee amount harus angka")

        if total_waived_amount:
            try:
                float(total_waived_amount)
            except (TypeError, ValueError):
                errors.append("Total waived amount harus angka")

        is_exist_bill_id = DanaPaymentBill.objects.filter(bill_id=bill_id).last()

        if not is_exist_bill_id:
            errors.append("Bill ID tidak ditemukan")

        try:
            total_amount_sended = (
                abs(float(principal_amount))
                + abs(float(interest_fee_amount))
                + abs(float(late_fee_amount))
            )
            if total_amount_sended != abs(float(total_amount)):
                errors.append(
                    "Total amount tidak sama dengan principal + interest + late_fee yang dibayar"
                )
        except (TypeError, ValueError):
            errors.append("Kesalahan dalam perhitungan jumlah total amount")

        if (
            waived_principal_amount or waived_interest_fee_amount or waived_late_fee_amount
        ) and total_waived_amount:
            try:
                total_waived_amount_sended = (
                    abs(float(waived_principal_amount))
                    + abs(float(waived_interest_fee_amount))
                    + abs(float(waived_late_fee_amount))
                )
                if total_waived_amount_sended != abs(float(total_waived_amount)):
                    error_msg = "Total waived amount tidak sama dengan "
                    error_msg += (
                        "waived principal + waived interest + waived late_fee yang diberikan"
                    )
                    errors.append(error_msg)
            except (TypeError, ValueError):
                errors.append("Kesalahan dalam perhitungan jumlah total waived amount")

        if errors:
            raise serializers.ValidationError(errors)

        return data

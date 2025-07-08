import json
from datetime import datetime
from typing import Dict, List

from django.conf import settings
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status

from juloserver.dana.constants import (
    DanaInstallmentType,
    DanaTransactionStatusCode,
    ErrorDetail,
    PaymentResponseCodeMessage,
    PaymentReferenceStatus,
    DanaProductType,
    DanaDisbursementMethod,
)
from juloserver.dana.exceptions import APIError, APIInvalidFieldFormatError
from juloserver.dana.loan.services import dana_generate_hashed_loan_xid
from juloserver.dana.loan.utils import create_redis_key_for_payment_api
from juloserver.dana.models import DanaLoanReference, DanaPaymentBill
from juloserver.dana.utils import set_redis_key
from juloserver.julo.models import Application


class DanaCurrencyValueSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    value = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    currency = serializers.CharField(required=True, allow_blank=False, allow_null=False)


class DanaBillDetailSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    billId = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    periodNo = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    principalAmount = DanaCurrencyValueSerializer(required=False)
    interestFeeAmount = DanaCurrencyValueSerializer(required=False)
    lateFeeAmount = DanaCurrencyValueSerializer(required=False)
    totalAmount = DanaCurrencyValueSerializer(required=False)
    dueDate = serializers.CharField(required=True, allow_blank=False, allow_null=False)


class DanaRepaymentPlanListSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """

    periodNo = serializers.CharField(required=True, allow_blank=False, allow_null=False)
    principalAmount = DanaCurrencyValueSerializer(required=True, allow_null=False)
    interestFeeAmount = DanaCurrencyValueSerializer(required=True, allow_null=False)
    totalAmount = DanaCurrencyValueSerializer(required=True, allow_null=False)
    dueDate = serializers.CharField(required=True, allow_blank=False, allow_null=False)


class DanaAgreementInfoSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    partnerEmail = serializers.CharField(allow_blank=True)
    partnerTnc = serializers.CharField(allow_blank=True)
    partnerPrivacyRule = serializers.CharField(allow_blank=True)
    provisionFeeAmount = serializers.DictField(required=True)
    lateFeeRate = serializers.CharField(required=False, allow_blank=True)
    maxLateFeeDays = serializers.CharField(required=True, allow_blank=False)


class DanaInterestConfigSerializer(serializers.Serializer):
    is_crm = serializers.BooleanField(required=False)
    feeMode = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    feeRate = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    roundingScale = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    roundingType = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class DanaInstallmentConfigSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """

    is_crm = serializers.BooleanField(required=False)
    installmentCount = serializers.CharField(required=False, allow_null=False)
    installmentType = serializers.CharField(required=False, allow_null=False)
    dueDateDuration = serializers.CharField(required=False, allow_null=False)
    principalRoundingScale = serializers.CharField(required=False, allow_null=False)
    dueDateConfig = serializers.JSONField(required=False, allow_null=False)
    interestConfig = DanaInterestConfigSerializer(required=False, allow_null=False)


class DanaDisbursementInfoSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    disbursementMethod = serializers.CharField(required=True, allow_blank=False)
    destinationAccountInfo = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )


class DanaAdditionalInfoSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    orderInfo = serializers.CharField(required=True, allow_blank=False)
    customerId = serializers.CharField(required=True, allow_blank=False)
    transTime = serializers.CharField(required=True, allow_blank=False)
    lenderProductId = serializers.CharField(required=True, allow_blank=False)
    creditUsageMutation = serializers.DictField()
    billDetailList = serializers.ListField(
        child=DanaBillDetailSerializer(), required=False, allow_empty=True
    )
    repaymentPlanList = serializers.ListField(
        child=DanaRepaymentPlanListSerializer(), required=False, allow_empty=True
    )
    agreementInfo = DanaAgreementInfoSerializer(required=False, allow_null=True)
    originalOrderAmount = serializers.DictField(required=True)
    isNeedApproval = serializers.BooleanField(required=False)
    paymentId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    disbursementInfo = DanaDisbursementInfoSerializer(required=False, allow_null=True)
    latestTransactionStatus = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    failCode = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    installmentConfig = DanaInstallmentConfigSerializer(required=True, allow_null=False)


class DanaPaymentSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    merchantId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    partnerReferenceNo = serializers.CharField(required=True, allow_blank=False)
    amount = serializers.DictField()
    additionalInfo = DanaAdditionalInfoSerializer()

    def validate(self, data: Dict) -> Dict:
        partner_reference_no = data.get("partnerReferenceNo")
        additionalInfo = data.get("additionalInfo")

        disbursementInfo = additionalInfo.get("disbursementInfo")
        self._validate_disbursement_info(disbursementInfo, partner_reference_no)

        installmentConfig = additionalInfo.get("installmentConfig")
        if not installmentConfig:
            additional_info = {
                "errorMessage": {"additionalInfo": {"installmentConfig": ErrorDetail.NULL}}
            }
            return_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': additional_info,
            }
            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

        self._validate_installment_config(installmentConfig, partner_reference_no)

        order_info = additionalInfo.get("orderInfo")
        try:
            json.loads(order_info)
        except json.JSONDecodeError:
            error_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': {"errorMessage": "orderInfo is not a valid JSON string"},
            }
            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        trans_time = parse_datetime(additionalInfo.get("transTime"))
        if not trans_time:
            error_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': {
                    "errorMessage": "Datetime has wrong format. "
                    "Use one of these formats instead: "
                    "YYYY-MM-DDThh:mm[:ss[.uuuuuu]][+HH:MM|-HH:MM|Z]"
                },
            }
            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        data["additionalInfo"]["transTime"] = trans_time
        amount = data.get("amount")
        self._validate_money_object("amount", amount, partner_reference_no)

        credit_usage_mutation = additionalInfo.get("creditUsageMutation")
        self._validate_money_object(
            "creditUsageMutation", credit_usage_mutation, partner_reference_no
        )

        original_order_amount = additionalInfo.get("originalOrderAmount")
        self._validate_money_object(
            "originalOrderAmount", original_order_amount, partner_reference_no
        )

        if not additionalInfo.get("isNeedApproval") and not additionalInfo.get("agreementInfo"):
            additional_info = {
                "errorMessage": {"additionalInfo": {"agreementInfo": ErrorDetail.NULL}}
            }
            return_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': additional_info,
            }
            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

        if additionalInfo.get("agreementInfo"):
            provision_fee_amount = additionalInfo.get("agreementInfo").get("provisionFeeAmount")
            self._validate_money_object(
                "provisionFeeAmount", provision_fee_amount, partner_reference_no
            )

            if not additionalInfo.get("agreementInfo").get(
                "lateFeeRate"
            ) and not additionalInfo.get("isNeedApproval"):
                additional_info = {
                    "errorMessage": {
                        "additionalInfo": {"agreementInfo": {"lateFeeRate": ErrorDetail.NULL}}
                    }
                }
                return_data = {
                    "responseCode": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    "partnerReferenceNo": partner_reference_no,
                    "additionalInfo": additional_info,
                }
                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

        bill_detail_list = additionalInfo.get("billDetailList")
        if not additionalInfo.get("isNeedApproval") and not bill_detail_list:
            additional_info = {
                "errorMessage": {
                    "additionalInfo": {"billDetailList": ["This list may not be empty."]}
                }
            }
            return_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': additional_info,
            }

            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

        bill_ids = []
        bills_dict = dict()

        for bill in bill_detail_list:
            self._validate_bill_detail(bill, partner_reference_no)
            bill_ids.append(bill["billId"])
            bills_dict[bill["billId"]] = bill

        dana_loan_reference = (
            DanaLoanReference.objects.filter(partner_reference_no=partner_reference_no)
            .select_related("loan")
            .last()
        )

        if (
            additionalInfo.get("lenderProductId") == DanaProductType.CASH_LOAN
            and additionalInfo.get("latestTransactionStatus")
            and additionalInfo.get("latestTransactionStatus")
            == DanaTransactionStatusCode.FAILED.code
        ):
            if not additionalInfo.get("failCode"):
                return_data = {
                    "responseCode": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    "referenceNo": dana_loan_reference.reference_no,
                    "partnerReferenceNo": partner_reference_no,
                    "additionalInfo": {
                        "message": "failCode is mandatory for latestTransactionStatus = 06"
                    },
                }
                status_code = status.HTTP_400_BAD_REQUEST
                raise APIError(status_code=status_code, detail=return_data)

        dana_payment_bill_bills = DanaPaymentBill.objects.filter(bill_id__in=bill_ids)
        existing_bill_details = []
        if dana_loan_reference:
            dana_customer_identifer = (
                Application.objects.filter(id=dana_loan_reference.application_id)
                .select_related("dana_customer_data")
                .values_list("dana_customer_data__dana_customer_identifier", flat=True)
                .last()
            )

            if not additionalInfo.get("isNeedApproval") and len(bill_ids) != 0:
                # If: is_whitelited = True and billDetail is empty
                # then compare the billDetail to empty array
                # because it means it is a Payment Consult Flow
                # If not: then compare the billDetail to dana_loan_reference.bill_detail
                existing_bill_details = dana_loan_reference.bill_detail

            validated_bill_detail = self._is_bills_dana_payment_bills_equals(
                bills_dict, existing_bill_details
            )

            customer_id = additionalInfo.get("customerId")
            if (
                len(existing_bill_details) == len(bill_ids)
                and dana_customer_identifer == customer_id
                and validated_bill_detail
                and dana_loan_reference.credit_usage_mutation
                == float(credit_usage_mutation["value"])
                and dana_loan_reference.amount == float(amount["value"])
            ):
                hashed_loan_xid = dana_generate_hashed_loan_xid(dana_loan_reference.id)
                try:
                    if not len(bill_ids) == 0:
                        key = create_redis_key_for_payment_api(data)
                        value = "{}++{}".format(dana_loan_reference.reference_no, hashed_loan_xid)
                        set_redis_key(key, value)
                except Exception:
                    pass

                loan_agreement_url = "{}/{}/{}".format(
                    settings.BASE_URL, "v1.0/agreement/content", hashed_loan_xid
                )

                # Handling if is payment consult, even if dana not sending 2 times
                # To not make confusing need to decide whether payment consult or not
                if dana_loan_reference.is_whitelisted and len(existing_bill_details) == 0:
                    response_code = PaymentResponseCodeMessage.ACCEPTED.code
                    response_message = PaymentResponseCodeMessage.ACCEPTED.message
                    additional_info = {
                        "rejectCode": "IDEMPOTENCY_REQUEST",
                        "rejectMessage": "partnerReferenceNo: {} has been proceed".format(
                            partner_reference_no
                        ),
                    }
                    status_code = status.HTTP_202_ACCEPTED
                else:
                    response_code = PaymentResponseCodeMessage.SUCCESS.code
                    response_message = PaymentResponseCodeMessage.SUCCESS.message
                    additional_info = {
                        "loanAgreementUrl": loan_agreement_url,
                        "rejectCode": "IDEMPOTENCY_REQUEST",
                        "rejectMessage": "partnerReferenceNo: {} has been proceed".format(
                            partner_reference_no
                        ),
                    }
                    status_code = status.HTTP_200_OK

                return_data = {
                    'responseCode': response_code,
                    'responseMessage': response_message,
                    'referenceNo': dana_loan_reference.reference_no,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': additional_info,
                }

                raise APIError(status_code=status_code, detail=return_data)
            else:
                return_data = {
                    'responseCode': PaymentResponseCodeMessage.INCONSISTENT_REQUEST.code,
                    'responseMessage': PaymentResponseCodeMessage.INCONSISTENT_REQUEST.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {"errorMessage": "partnerReferenceNo already exists"},
                }

                """
                Rules Inconsistency Because Different Data
                1. First if handling for payment consult hit 2 times
                And not payment consult
                2. Second if handling for payment consult flow but hit 2 times
                """
                if not dana_loan_reference.is_whitelisted or (
                    dana_loan_reference.is_whitelisted
                    and additionalInfo.get("isNeedApproval")
                    and dana_loan_reference.bill_detail_self
                ):
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)
                elif (
                    hasattr(dana_loan_reference, 'dana_loan_status')
                    and dana_loan_reference.dana_loan_status == PaymentReferenceStatus.SUCCESS
                ):
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

        if dana_payment_bill_bills and not additionalInfo.get("isNeedApproval"):
            dana_payment_bill_bill_ids = list(
                dana_payment_bill_bills.values_list("bill_id", flat=True)
            )

            error_data = {
                'responseCode': PaymentResponseCodeMessage.INCONSISTENT_REQUEST.code,
                'responseMessage': PaymentResponseCodeMessage.INCONSISTENT_REQUEST.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': {
                    "errorMessage": "billId {} already exists".format(dana_payment_bill_bill_ids)
                },
            }
            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

        repayment_plan_list = additionalInfo.get("repaymentPlanList")
        if (
            additionalInfo.get('lenderProductId') == DanaProductType.CASH_LOAN
            and not repayment_plan_list
        ):
            additional_info = {
                "errorMessage": {
                    "additionalInfo": {"repaymentPlanList": ["This list may not be empty."]}
                }
            }
            return_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partner_reference_no,
                'additionalInfo': additional_info,
            }

            raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

        return data

    def _validate_money_object(self, key: str, money: Dict, partnerReferenceNo: str) -> Dict:
        if not ("value" in money.keys() and "currency" in money.keys()):
            error_message = "{} objects doesn't have value or currency".format(key)
            error_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partnerReferenceNo,
                'additionalInfo': {"errorMessage": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_data,
            )
        if not money.get("value") or not money.get("currency"):
            error_message = "{} field may not be blank".format(key)
            error_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': partnerReferenceNo,
                'additionalInfo': {"errorMessage": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_data,
            )
        try:
            float(money.get("value"))
        except ValueError:
            error_message = {key: "value is not a number"}
            error_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': partnerReferenceNo,
                'additionalInfo': {"errorMessage": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_data,
            )

    def _validate_bill_detail(self, bill: Dict, partnerReferenceNo: str) -> Dict:
        keys = ["principalAmount", "interestFeeAmount", "lateFeeAmount", "totalAmount"]
        for key in keys:
            if not ("value" in bill[key].keys() and "currency" in bill[key].keys()):
                error_message = "billId {}, {} objects doesn't have value or currency".format(
                    bill["billId"], key
                )
                error_data = {
                    'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    'partnerReferenceNo': partnerReferenceNo,
                    'additionalInfo': {"errorMessage": error_message},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data,
                )

            if not bill[key].get("value") or not bill[key].get("currency"):
                error_message = "billId {}, {} field may not be blank".format(bill["billId"], key)
                error_data = {
                    'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    'partnerReferenceNo': partnerReferenceNo,
                    'additionalInfo': {"errorMessage": error_message},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data,
                )

            try:
                float(bill[key].get("value"))
            except ValueError:
                error_message = "billId {}, {} value is not a number".format(bill["billId"], key)
                error_data = {
                    'responseCode': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                    'responseMessage': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                    'partnerReferenceNo': partnerReferenceNo,
                    'additionalInfo': {"errorMessage": error_message},
                }
                raise APIError(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_data,
                )

        try:
            datetime.strptime(bill["dueDate"], "%Y%m%d")
        except ValueError:
            error_message = {"dueDate": "Format is not valid"}
            error_data = {
                'responseCode': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                'responseMessage': PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message,
                'partnerReferenceNo': partnerReferenceNo,
                'additionalInfo': {"errorMessage": error_message},
            }
            raise APIError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_data,
            )
        return bill

    def _is_bills_dana_payment_bills_equals(self, bills: List, dana_payment_bills: List) -> bool:
        for dana_payment_bill in dana_payment_bills:
            payload_bill_id = bills.get(dana_payment_bill['billId'])

            payload_bill_principal = 0
            payload_bill_interest = 0
            payload_bill_total_amount = 0
            if payload_bill_id:
                try:
                    payload_bill_principal = payload_bill_id.get('principalAmount')['value']
                    payload_bill_interest = payload_bill_id.get('interestFeeAmount')['value']
                    payload_bill_total_amount = payload_bill_id.get('totalAmount')['value']
                except KeyError:
                    payload_bill_principal = 0
                    payload_bill_interest = 0
                    payload_bill_total_amount = 0

            existing_principal = float(dana_payment_bill['principalAmount']['value'])
            existing_interest = float(dana_payment_bill['interestFeeAmount']['value'])
            existing_total_amount = float(dana_payment_bill['totalAmount']['value'])
            if not (
                existing_principal == float(payload_bill_principal)
                and existing_interest == float(payload_bill_interest)
                and existing_total_amount == float(payload_bill_total_amount)
            ):
                return False
        return True

    @staticmethod
    def _validate_disbursement_info(disbursement_info: Dict, partner_reference_no: str):
        eligible_disbursement_methods = [
            value
            for name, value in vars(DanaDisbursementMethod).items()
            if not name.startswith('_')
        ]

        if disbursement_info:
            disbursement_method = disbursement_info.get("disbursementMethod")
            destination_account_info = disbursement_info.get("destinationAccountInfo")

            if disbursement_method not in eligible_disbursement_methods:
                err_msg = "disbursementMethod " + disbursement_method + " is not valid"

                error_data = {
                    "responseCode": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    "partnerReferenceNo": partner_reference_no,
                    "additionalInfo": {"errorMessage": err_msg},
                }
                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            if (
                disbursement_method == DanaDisbursementMethod.BANK_ACCOUNT
                and not destination_account_info
            ):
                err_msg = "destinationAccountInfo is mandatory for disbursementMethod = "

                error_data = {
                    "responseCode": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    "responseMessage": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    "partnerReferenceNo": partner_reference_no,
                    "additionalInfo": {
                        "errorMessage": err_msg + DanaDisbursementMethod.BANK_ACCOUNT
                    },
                }
                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

    @staticmethod
    def _validate_installment_config(installment_config: Dict, partner_reference_no: str):
        if installment_config:
            installment_type = installment_config.get("installmentType")
            installment_count = installment_config.get("installmentCount")
            due_date_duration = installment_config.get("dueDateDuration")
            principal_rounding_scale = installment_config.get("principalRoundingScale")
            due_date_config = installment_config.get("dueDateConfig")
            interest_config = installment_config.get("interestConfig")
            is_crm = installment_config.get("is_crm")

            resp_msg_invalid_field = PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.message

            if installment_count:
                try:
                    installment_count = int(installment_count)
                    if installment_count <= 0:
                        raise ValueError("installmentCount should be greater than 0.")

                except ValueError:
                    err_msg = "installmentCount: A valid integer is required."
                    error_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                        "responseMessage": resp_msg_invalid_field,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"installmentConfig": {"errorMessage": err_msg}},
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            if installment_type:
                if not isinstance(installment_type, str):
                    err_msg = "installmentType should be a string."
                    error_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                        "responseMessage": resp_msg_invalid_field,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"installmentConfig": {"errorMessage": err_msg}},
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

                if installment_type not in DanaInstallmentType.values():
                    err_msg = "installmentType should be one of {}".format(
                        DanaInstallmentType.values()
                    )
                    error_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                        "responseMessage": resp_msg_invalid_field,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"installmentConfig": {"errorMessage": err_msg}},
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            if due_date_duration:
                try:
                    due_date_duration = int(due_date_duration)
                    if due_date_duration <= 0:
                        raise ValueError("dueDateDuration should be greater than 0.")

                except ValueError:
                    err_msg = "dueDateDuration: A valid integer is required."
                    error_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                        "responseMessage": resp_msg_invalid_field,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"installmentConfig": {"errorMessage": err_msg}},
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            if principal_rounding_scale:
                try:
                    principal_rounding_scale = int(principal_rounding_scale)
                    if principal_rounding_scale < 0:
                        raise ValueError(
                            "principalRoundingScale should be greater than or equal to 0."
                        )

                except ValueError:
                    err_msg = "principalRoundingScale: A valid integer is required."
                    error_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                        "responseMessage": resp_msg_invalid_field,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"installmentConfig": {"errorMessage": err_msg}},
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            if due_date_config == "":
                additional_info = {
                    "errorMessage": {"installmentConfig": {"dueDateConfig": ErrorDetail.NULL}}
                }
                return_data = {
                    'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': additional_info,
                }
                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

            elif due_date_config:
                try:
                    json.loads(due_date_config)
                except json.JSONDecodeError:
                    err_msg = "Invalid dueDateConfig format. It should be a valid JSON string."
                    error_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                        "responseMessage": resp_msg_invalid_field,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {"installmentConfig": {"errorMessage": err_msg}},
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

            if interest_config == {} or interest_config == "":
                additional_info = {
                    "errorMessage": {"installmentConfig": {"interestConfig": ErrorDetail.NULL}}
                }
                return_data = {
                    'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': additional_info,
                }
                raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)
            elif interest_config:
                fee_mode = interest_config.get("feeMode")
                fee_rate = interest_config.get("feeRate")
                rounding_scale = interest_config.get("roundingScale")
                rounding_type = interest_config.get("roundingType")
                is_crm = interest_config.get("is_crm")

                if fee_mode:
                    if not isinstance(fee_mode, str):
                        err_msg = "feeMode should be either 'PERCENTAGE' or 'FIXED'."
                        error_data = {
                            "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                            "responseMessage": resp_msg_invalid_field,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {
                                "installmentConfig": {"interestConfig": {"errorMessage": err_msg}}
                            },
                        }
                        raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

                    if fee_mode not in ["PERCENTAGE", "FIXED"]:
                        err_msg = "feeMode should be either 'PERCENTAGE' or 'FIXED'."
                        error_data = {
                            "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                            "responseMessage": resp_msg_invalid_field,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {
                                "installmentConfig": {"interestConfig": {"errorMessage": err_msg}}
                            },
                        }
                        raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

                if fee_rate:
                    try:
                        fee_rate = float(fee_rate)
                        if fee_rate < 0:
                            raise ValueError("feeRate should be greater than 0.")
                    except ValueError as e:
                        err_msg = str(e)
                        error_data = {
                            "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                            "responseMessage": resp_msg_invalid_field,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {
                                "installmentConfig": {
                                    "interestConfig": {"errorMessage": "feeRate " + err_msg}
                                }
                            },
                        }
                        raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

                if rounding_scale:
                    try:
                        rounding_scale = int(rounding_scale)
                        if rounding_scale < 0:
                            raise ValueError("roundingScale should be a positive integer.")
                    except ValueError as e:
                        err_msg = str(e)
                        error_data = {
                            "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                            "responseMessage": resp_msg_invalid_field,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {
                                "installmentConfig": {
                                    "interestConfig": {"errorMessage": "roundingScale " + err_msg}
                                }
                            },
                        }
                        raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

                if rounding_type:
                    if not isinstance(rounding_type, str):
                        err_msg = "roundingType should be a string."
                        error_data = {
                            "responseCode": PaymentResponseCodeMessage.INVALID_FIELD_FORMAT.code,
                            "responseMessage": resp_msg_invalid_field,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {
                                "installmentConfig": {"interestConfig": {"errorMessage": err_msg}}
                            },
                        }
                        raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=error_data)

                if not is_crm:
                    required_fields = [
                        "feeMode",
                        "feeRate",
                        "roundingScale",
                        "roundingType",
                    ]
                    missing_fields = []
                    for field in required_fields:
                        if field not in interest_config or (
                            field in required_fields and interest_config.get(field) in ["", 0, None]
                        ):
                            missing_fields.append(field)

                    if missing_fields:
                        interest_config = {
                            field: "This field is required when triggered via API."
                            for field in missing_fields
                        }
                        resp_message = PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message
                        return_data = {
                            "responseCode": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                            "responseMessage": resp_message,
                            "partnerReferenceNo": partner_reference_no,
                            "additionalInfo": {
                                "installmentConfig": {"interestConfig": interest_config}
                            },
                        }
                        raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)

            if not is_crm:
                required_fields = [
                    "installmentCount",
                    "installmentType",
                    "dueDateDuration",
                    "principalRoundingScale",
                    "dueDateConfig",
                    "interestConfig",
                ]
                missing_fields = [
                    field for field in required_fields if field not in installment_config
                ]
                if missing_fields:
                    installment_config = {
                        field: "This field is required when triggered via API."
                        for field in missing_fields
                    }
                    resp_message = PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message
                    return_data = {
                        "responseCode": PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                        "responseMessage": resp_message,
                        "partnerReferenceNo": partner_reference_no,
                        "additionalInfo": {
                            "installmentConfig": installment_config,
                        },
                    }
                    raise APIError(status_code=status.HTTP_400_BAD_REQUEST, detail=return_data)


class DanaLoanStatusSerializer(serializers.Serializer):
    """
    Set serializer as camelCase because
    Dana send a payload using that Format
    """
    originalPartnerReferenceNo = serializers.CharField(
        required=True, allow_blank=False, max_length=64
    )
    originalReferenceNo = serializers.CharField(required=False, allow_blank=True, max_length=64)
    serviceCode = serializers.CharField(required=True, allow_blank=False)

    def validate_serviceCode(self, value: str) -> str:
        if len(value) != 2:
            raise APIInvalidFieldFormatError(
                detail={'serviceCode': ['Ensure this field has 2 characters']},
            )

        return value

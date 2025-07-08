from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from django.db import transaction
from juloserver.dana.constants import (
    DanaBasePath,
    RefundResponseCodeMessage,
    RejectCodeMessage,
)
from juloserver.dana.models import DanaRefundReference
from juloserver.dana.views import DanaAPIView
from juloserver.dana.refund.services import insert_refund_data
from juloserver.dana.refund.tasks import run_refund_async_process
from juloserver.dana.refund.serializers import validate_form_dana_refund


class BaseDanaRefundAPIView(DanaAPIView):
    base_path = DanaBasePath.refund


class DanaRefundView(BaseDanaRefundAPIView):
    def post(self, request: Request) -> Response:

        # check idempotency on dana_refund_reference_table
        original_partner_reference_no = self.request.data.get('originalPartnerReferenceNo')
        if original_partner_reference_no:
            dana_refund_reference = DanaRefundReference.objects.get_or_none(
                original_partner_reference_no=original_partner_reference_no
            )

            if dana_refund_reference:
                data_response_idempotency = {
                    "responseCode": RefundResponseCodeMessage.SUCCESS.code,
                    "responseMessage": RefundResponseCodeMessage.SUCCESS.message,
                    "referenceNo": dana_refund_reference.original_reference_no,
                    "partnerReferenceNo": original_partner_reference_no,
                    "additionalInfo": {
                        "rejectCode": RejectCodeMessage.IDEMPOTENCY.code,
                        "rejectMessage": RejectCodeMessage.IDEMPOTENCY.message.format(
                            original_partner_reference_no
                        ),
                    },
                }
                return Response(status=status.HTTP_200_OK, data=data_response_idempotency)

        request_data = validate_form_dana_refund(data=self.request.data)

        refunded_bill_detail_list = request_data['additionalInfo']['refundedTransaction'][
            'refundedBillDetailList'
        ]

        if not len(refunded_bill_detail_list):
            response_data = {
                'responseCode': RefundResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                'responseMessage': RefundResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                'partnerReferenceNo': original_partner_reference_no,
                'additionalInfo': {},
            }
            return Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        with transaction.atomic():
            refund_transaction_data = insert_refund_data(request_data)

        refund_data = refund_transaction_data.dana_refund_reference

        run_refund_async_process.delay(refund_transaction_data.id)
        currency = "IDR"
        refund_amount = {
            "value": refund_data.refund_amount,
            "currency": currency,
        }

        response_data = {
            "responseCode": RefundResponseCodeMessage.SUCCESS.code,
            "responseMessage": RefundResponseCodeMessage.SUCCESS.message,
            "originalPartnerReferenceNo": refund_data.original_partner_reference_no,
            "originalReferenceNo": refund_data.original_reference_no,
            "originalExternalId": refund_data.original_external_id,
            "refundNo": refund_data.refund_no,
            "partnerRefundNo": refund_data.partner_refund_no,
            "refundAmount": refund_amount,
            "refundTime": refund_data.refund_time,
            "additionalInfo": {},
        }
        return Response(status=status.HTTP_200_OK, data=response_data)

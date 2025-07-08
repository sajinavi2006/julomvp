import io
import logging

import requests
from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView
from PyPDF2 import PdfFileReader, PdfFileWriter

from juloserver.dana.constants import (
    DanaBasePath,
    DanaDocumentConstant,
    DanaErrorMessage,
    DanaTransactionStatusCode,
    ErrorDetail,
    LoanStatusResponseCodeMessage,
    PaymentReferenceStatus,
    PaymentResponseCodeMessage,
)
from juloserver.dana.loan.serializers import (
    DanaLoanStatusSerializer,
    DanaPaymentSerializer,
)
from juloserver.dana.loan.services import (
    dana_decode_encoded_loan_xid,
    proceed_dana_payment,
    resume_dana_create_loan,
)
from juloserver.dana.loan.tasks import run_payment_async_process
from juloserver.dana.loan.utils import (
    create_redis_key_for_payment_api,
    get_dana_loan_agreement_url,
)
from juloserver.dana.models import (
    DanaLoanReference,
    DanaLoanReferenceStatus,
)
from juloserver.dana.utils import get_redis_key, set_redis_key
from juloserver.dana.views import DanaAPIView
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Document,
    FeatureSetting,
    Loan,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import get_oss_presigned_url
from juloserver.partnership.constants import (
    HTTPStatusCode,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class BaseDanaLoanAPIView(DanaAPIView):
    base_path = DanaBasePath.loan


class DanaPaymentView(BaseDanaLoanAPIView):
    serializer_class = DanaPaymentSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, ValidationError):
            str_exc = str(exc)
            if (
                ErrorDetail.REQUIRED in str_exc
                or ErrorDetail.BLANK in str_exc
                or ErrorDetail.BLANK_LIST in str_exc
            ):
                data = {
                    'responseCode': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.code,
                    'responseMessage': PaymentResponseCodeMessage.INVALID_MANDATORY_FIELD.message,
                    'partnerReferenceNo': self.request.data.get('partnerReferenceNo'),
                    'additionalInfo': {"errorMessage": exc.detail},
                }
                return Response(status=exc.status_code, data=data)

        return super().handle_exception(exc)

    def post(self, request: Request) -> Response:
        """
        loan_amount = Principal Amount + Interest
        loan_disbursement_amount = Principal Amount
        In this API, Loan created to 220 but with fund_transfer_ts = None
        And do manual change by FinOps using CRM to set fund_transfer_ts
        """
        hashed_loan_xid = ""
        feature_setting_payment_async_process = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DANA_ENABLE_PAYMENT_ASYNCHRONOUS,
        ).first()

        try:
            key = create_redis_key_for_payment_api(self.request.data)
            value = get_redis_key(key)
            if value:
                spllited_value = value.split("++")
                reference_no = spllited_value[0]
                hashed_loan_xid = spllited_value[1]
                loan_agreement_url = "{}/{}/{}".format(
                    settings.BASE_URL, "v1.0/agreement/content", hashed_loan_xid
                )
                partner_reference_no = self.request.data["partnerReferenceNo"]
                data = {
                    'responseCode': PaymentResponseCodeMessage.SUCCESS.code,
                    'responseMessage': PaymentResponseCodeMessage.SUCCESS.message,
                    'referenceNo': reference_no,
                    'partnerReferenceNo': partner_reference_no,
                    'additionalInfo': {
                        "loanAgreementUrl": loan_agreement_url,
                        "rejectCode": "IDEMPOTENCY_REQUEST",
                        "rejectMessage": "partnerReferenceNo: {} has been proceed".format(
                            partner_reference_no
                        ),
                    },
                }
                return Response(status=status.HTTP_200_OK, data=data)

        except Exception:
            pass

        dana_loan_reference, response = proceed_dana_payment(self.request.data)
        if not dana_loan_reference:
            return response

        additional_info = self.request.data.get('additionalInfo')
        partner_reference_no = dana_loan_reference.partner_reference_no
        is_need_approval = additional_info.get('isNeedApproval', False)

        if (
            feature_setting_payment_async_process
            and feature_setting_payment_async_process.is_active
            and not is_need_approval
        ):
            # Asynchronously process
            # Create Dana Loan Reference pending
            DanaLoanReferenceStatus.objects.create(
                dana_loan_reference=dana_loan_reference,
                status=PaymentReferenceStatus.PENDING,
            )

            run_payment_async_process.delay(
                dana_loan_reference_id=dana_loan_reference.id,
            )

        else:
            # Synchronously process
            is_success_to_process = resume_dana_create_loan(
                list_dana_loan_references=[dana_loan_reference],
            )

            if not is_success_to_process:
                duplicate_response = {
                    'code': PaymentResponseCodeMessage.INCONSISTENT_REQUEST.code,
                    'message': PaymentResponseCodeMessage.INCONSISTENT_REQUEST.message,
                }
                response_data = {
                    'responseCode': duplicate_response['code'],
                    'responseMessage': duplicate_response['message'],
                    'partnerReferenceNo': partner_reference_no,
                    'referenceNo': None,
                    'additionalInfo': {
                        "errors": {"partnerReferenceNo": ["duplicate partnerReferenceNo"]}
                    },
                }
                return Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        try:
            key = create_redis_key_for_payment_api(self.request_data)
            value = "{}++{}".format(dana_loan_reference.reference_no, hashed_loan_xid)
            set_redis_key(key, value)
        except Exception:
            pass

        if is_need_approval:
            response_data = {
                "responseCode": PaymentResponseCodeMessage.ACCEPTED.code,
                "responseMessage": PaymentResponseCodeMessage.ACCEPTED.message,
                "referenceNo": dana_loan_reference.reference_no,
                "partnerReferenceNo": partner_reference_no,
                "additionalInfo": {},
            }
            return Response(status=status.HTTP_202_ACCEPTED, data=response_data)

        loan_agreement_url = get_dana_loan_agreement_url(dana_loan_reference)
        response_data = {
            "responseCode": PaymentResponseCodeMessage.SUCCESS.code,
            "responseMessage": PaymentResponseCodeMessage.SUCCESS.message,
            "referenceNo": dana_loan_reference.reference_no,
            "partnerReferenceNo": partner_reference_no,
            "additionalInfo": {"loanAgreementUrl": loan_agreement_url},
        }

        return Response(status=status.HTTP_200_OK, data=response_data)


class DanaAgreementContentView(APIView):
    permission_classes = []
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request, *args, **kwargs) -> Response:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DANA_AGREEMENT_PASSWORD,
        ).first()

        encrypted_loan_xid = self.kwargs['encrypted_loan_xid']
        decrypted_loan_xid = dana_decode_encoded_loan_xid(encrypted_loan_xid)
        if not decrypted_loan_xid:
            return HttpResponse(DanaErrorMessage.INVALID_ENCRYPTED_LOAN_XID)

        decrypted_id = decrypted_loan_xid[0]
        dana_loan_reference = DanaLoanReference.objects.filter(id=decrypted_id).last()
        if dana_loan_reference:
            loan = dana_loan_reference.loan
            msg = DanaErrorMessage.AGREEMENT_IN_PROCESS
        else:
            loan = Loan.objects.filter(loan_xid=decrypted_id).last()
            msg = DanaErrorMessage.INVALID_LOAN_XID
        if not loan:
            return HttpResponse(msg)

        partner_loan = loan.partnerloanrequest_set.select_related("partner").last()
        if not partner_loan or partner_loan.partner.name != "dana":
            return HttpResponse(msg)

        document = Document.objects.filter(
            loan_xid=loan.loan_xid, document_type='dana_loan_agreement'
        ).last()
        if not document or not document.url:
            return HttpResponse(DanaErrorMessage.DOCUMENT_NOT_FOUND)

        document_url = get_oss_presigned_url(
            settings.OSS_MEDIA_BUCKET, document.url, DanaDocumentConstant.EXPIRY_TIME
        )

        if feature_setting and feature_setting.is_active:

            # Stream Document with password
            document_response = requests.get(document_url)
            pdf_file = io.BytesIO(document_response.content)
            pdf_reader = PdfFileReader(pdf_file)
            pdf_writer = PdfFileWriter()
            for page in range(pdf_reader.getNumPages()):
                pdf_writer.addPage(pdf_reader.getPage(page))

            pdf_password = loan.customer.dana_customer_data.dob.strftime('%d%m%y')
            pdf_writer.encrypt(pdf_password)  # DDMMYY
            output_stream = io.BytesIO()
            pdf_writer.write(output_stream)

            response = HttpResponse(content_type='application/pdf')
            response.write(output_stream.getvalue())
            return response
        else:
            pdf_file_response = requests.get(document_url)
            return HttpResponse(pdf_file_response.content, content_type='application/pdf')


class DanaLoanStatusView(BaseDanaLoanAPIView):
    base_path = DanaBasePath.loan_status
    serializer_class = DanaLoanStatusSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        original_partner_reference_no = validated_data.get('originalPartnerReferenceNo')
        loan_reference = (
            DanaLoanReference.objects.select_related(
                'loan',
            )
            .filter(partner_reference_no=original_partner_reference_no)
            .last()
        )

        transaction_status = ""
        transaction_status_desc = ""
        reference_no = ""

        if not loan_reference:
            transaction_status = DanaTransactionStatusCode.NOT_FOUND.code
            transaction_status_desc = DanaTransactionStatusCode.NOT_FOUND.desc
        else:
            reference_no = loan_reference.reference_no
            loan_status = loan_reference.loan.loan_status.status_code
            if loan_status == LoanStatusCodes.LENDER_APPROVAL:
                transaction_status = DanaTransactionStatusCode.PENDING.code
                transaction_status_desc = DanaTransactionStatusCode.PENDING.desc
            elif loan_status in {
                LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.LOAN_1DPD,
                LoanStatusCodes.LOAN_5DPD,
                LoanStatusCodes.LOAN_30DPD,
                LoanStatusCodes.LOAN_60DPD,
                LoanStatusCodes.LOAN_90DPD,
                LoanStatusCodes.LOAN_120DPD,
                LoanStatusCodes.LOAN_150DPD,
                LoanStatusCodes.LOAN_180DPD,
                LoanStatusCodes.LOAN_4DPD,
                LoanStatusCodes.RENEGOTIATED,
                LoanStatusCodes.HALT,
                LoanStatusCodes.PAID_OFF,
                LoanStatusCodes.SELL_OFF,
            }:
                transaction_status = DanaTransactionStatusCode.SUCCESS.code
                transaction_status_desc = DanaTransactionStatusCode.SUCCESS.desc
            elif loan_status == LoanStatusCodes.INACTIVE:
                transaction_status = DanaTransactionStatusCode.INITIATED.code
                transaction_status_desc = DanaTransactionStatusCode.INITIATED.desc
            elif loan_status == LoanStatusCodes.CANCELLED_BY_CUSTOMER:
                transaction_status = DanaTransactionStatusCode.CANCELED.code
                transaction_status_desc = DanaTransactionStatusCode.CANCELED.desc
            elif loan_status == LoanStatusCodes.LENDER_REJECT:
                transaction_status = DanaTransactionStatusCode.FAILED.code
                transaction_status_desc = DanaTransactionStatusCode.FAILED.desc

        response_data = {
            "responseCode": LoanStatusResponseCodeMessage.SUCCESS.code,
            "responseMessage": LoanStatusResponseCodeMessage.SUCCESS.message,
            "originalPartnerReferenceNo": original_partner_reference_no,
            "originalReferenceNo": reference_no,
            "serviceCode": validated_data.get('serviceCode'),
            "latestTransactionStatus": transaction_status,
            "transactionStatusDesc": transaction_status_desc,
        }

        return Response(status=status.HTTP_200_OK, data=response_data)

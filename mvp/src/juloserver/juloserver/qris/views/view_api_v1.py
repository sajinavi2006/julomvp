import logging
import uuid

from rest_framework.views import APIView
from rest_framework import serializers
from django.db import DatabaseError
from rest_framework.serializers import ValidationError
from rest_framework.response import Response
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.loan.services.logging_related import LoanErrorLogData
from juloserver.qris.services.core_services import (
    get_qris_lender_from_lender_name,
    update_linkage_status,
)
from juloserver.qris.services.logging_related import log_qris_error
from juloserver.qris.services.view_related import (
    QrisTenureRangeService,
    get_qris_user_state_service,
    AmarRegisterLoginCallbackService,
    AmarTransactionStatusCallbackService,
    QrisLimitEligibilityService,
    get_qris_landing_page_config_feature_setting,
)
from juloserver.qris.utils import is_uuid_valid
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    not_found_response,
    created_response,
)

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Loan, Partner
from juloserver.qris.services.legacy_service import QrisService, get_qris_transaction_status
from juloserver.qris.serializers import (
    SubmitOtpSerializer,
    ScanQrisSerializer,
    TransactionDetailSerializer,
    UploadImageSerializer,
    QRISTransactionSerializer,
)
from juloserver.qris.constants import (
    QrisLinkageStatus,
    QrisResponseMessages,
    AmarCallbackConst,
    QrisProductName,
)
from juloserver.qris.services.user_related import (
    QrisAgreementService,
    QrisUploadSignatureService,
    QrisListTransactionService,
)
from juloserver.qris.permissions import QRISPartnerPermission
from juloserver.pin.decorators import pin_verify_required
from juloserver.qris.services.transaction_related import TransactionConfirmationService
from juloserver.qris.exceptions import (
    AlreadySignedWithLender,
    HasNotSignedWithLender,
    NoQrisLenderAvailable,
    QrisLinkageNotFound,
    InsufficientLenderBalance,
)
from juloserver.qris.standardized_api_response import qris_success_response, qris_error_response
from juloserver.loan.exceptions import (
    LoggableException,
)
from juloserver.loan.constants import LoanErrorCodes, LoanLogIdentifierType
from juloserver.qris.services.view_related import (
    get_prefilled_data,
    get_qris_partner_linkage,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class QRISAPIView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (QRISPartnerPermission,)


class CheckUserStatus(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        account = customer.account_set.last()
        qris_service = QrisService(account)
        response_data = {"is_verified": qris_service.check_doku_account_status()}

        return success_response(response_data)


class LinkingConfirm(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        customer = request.user.customer
        account = customer.account_set.last()
        application = account.application_set.last()
        qris_service = QrisService(account)
        try:
            if qris_service.register_doku_account():
                response_data = {"is_verified": True}
            else:
                response_data = {
                    "user_phone": application.mobile_phone_1,
                    "time_limit": 300,
                    "is_verified": False,
                }
        except Exception:
            sentry_client.captureException()
            return general_error_response(QrisResponseMessages.LINKING_ACCOUNT_ERROR)

        return success_response(response_data)


class SubmitOtp(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = SubmitOtpSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = request.user.customer
        account = customer.account_set.last()

        validated_data = serializer.validated_data
        otp = validated_data["otp"]
        qris_service = QrisService(account)
        try:
            response_data = {"is_verified": qris_service.linking_account_confirm(otp)}
        except Exception:
            sentry_client.captureException()
            return general_error_response(QrisResponseMessages.INVALID_OTP)
        return success_response(response_data)


class ScanQris(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ScanQrisSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = request.user.customer
        account = customer.account_set.last()

        validated_data = serializer.validated_data
        qr_code = validated_data["qr_code_value"]
        qris_service = QrisService(account)

        response_data = qris_service.inquiry_qris(qr_code)

        if not response_data:
            return general_error_response("Invalid QR code")

        if response_data.get('is_blacklisted_transaction', False) is True:
            return general_error_response(QrisResponseMessages.BLACKLISTED_MERCHANT)

        return success_response(response_data)


class StatusQris(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, loan_xid):
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan or loan.customer.user_id != request.user.id:
            return general_error_response('Something wrong!')

        result = get_qris_transaction_status(loan)
        if not result:
            return not_found_response("Transaction not found")

        return success_response(result)


class TransactionLimitCheckView(QRISAPIView):
    class InputSerializer(serializers.Serializer):
        partnerUserId = serializers.CharField()
        totalAmount = serializers.FloatField(min_value=1)
        productId = serializers.IntegerField()
        productName = serializers.CharField()
        transactionDetail = TransactionDetailSerializer(required=False)

        def validate_partnerUserId(self, value):
            if not is_uuid_valid(value):
                raise serializers.ValidationError("invalid value")
            return value

        def validate_productId(self, value):
            if value != QrisProductName.QRIS.code:
                raise serializers.ValidationError("invalid value")

            return value

        def validate_productName(self, value):
            if value != QrisProductName.QRIS.name:
                raise serializers.ValidationError("invalid value")

            return value

    def post(self, request, *args, **kwargs):
        logger.info(
            {
                "action": "juloserver.qris.views.view_api_v1.TransactionLimitCheckView",
                "message": "Qris Transaction Limit Check API Log",
                "payload": self.request.data,
            }
        )

        serializer = self.InputSerializer(
            data=request.data,
        )

        is_valid = serializer.is_valid()
        if not is_valid:
            sentry_client.captureMessage(
                "Qris Partner sent bad TransactionLimitCheckView data",
            )
            field = list(serializer.errors.keys())[0]
            return qris_error_response(
                error_code=LoanErrorCodes.GENERAL_ERROR.code,
                message="{}: invalid value".format(field),
            )

        service = QrisLimitEligibilityService(
            data=serializer.validated_data,
            partner=request.user.partner,
        )
        try:
            service.perform_check()

            return qris_success_response()

        except (LoggableException) as e:
            error_message = e.get_fe_message()
            error_code = e.get_code()
            error_detail = e.get_detail()

        except Exception as e:
            sentry_client.captureException()
            error_message = LoanErrorCodes.GENERAL_ERROR.message
            error_code = LoanErrorCodes.GENERAL_ERROR.code
            error_detail = str(e)

        # Logging
        # get identifier for logging
        identifier = str(uuid.UUID(request.data['partnerUserId']))
        identifier_type = LoanLogIdentifierType.TO_AMAR_USER_XID
        if service.linkage:
            identifier = service.linkage.customer_id
            identifier_type = LoanLogIdentifierType.CUSTOMER_ID

            # log
        log_qris_error(
            LoanErrorLogData(
                identifier=identifier,
                identifier_type=identifier_type,
                error_code=error_code,
                error_detail=error_detail,
                http_status_code=400,
                api_url=request.path,
            )
        )

        return qris_error_response(
            error_code=error_code,
            message=error_message,
        )


class PrefilledDataView(QRISAPIView):
    class InputSerializer(serializers.Serializer):
        to_partner_user_xid = serializers.CharField()

        def validate_to_partner_user_xid(self, value):
            if not is_uuid_valid(value):
                raise ValidationError("invalid xid")

            return value

    def get(self, request, to_partner_user_xid):
        partner_xid = request.META.get('HTTP_PARTNERXID')

        serializer = self.InputSerializer(
            data={
                "to_partner_user_xid": to_partner_user_xid,
            }
        )
        serializer.is_valid(raise_exception=True)

        qris_partner_linkage = get_qris_partner_linkage(partner_xid, to_partner_user_xid)

        if not qris_partner_linkage:
            return general_error_response('Qris partner linkage not found!')

        result = get_prefilled_data(qris_partner_linkage)

        update_linkage_status(
            linkage=qris_partner_linkage,
            to_status=QrisLinkageStatus.REGIS_FORM,
        )
        return Response(result)


class QrisUserAgreementView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        partner_name = self.request.query_params.get("partner_name")
        document_type = self.request.query_params.get("document_type")
        lender_name = self.request.query_params.get("lender_name")

        lender = get_qris_lender_from_lender_name(lender_name=lender_name)
        if not lender:
            return general_error_response("Lender not valid")

        qris_agreement_service = QrisAgreementService(
            customer=request.user.customer,
            lender=lender,
        )
        is_valid, error = qris_agreement_service.validate_agreement_type(
            partner_name, document_type
        )

        if not is_valid:
            return general_error_response(error)

        content = qris_agreement_service.get_document_content(document_type)
        return success_response(data=content)


class QrisUserSignatureView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = UploadImageSerializer

    @pin_verify_required
    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        signature_image_data = serializer.validated_data
        partner_name = self.request.query_params.get("partner_name")
        lender_name = self.request.query_params.get("lender_name")

        partner = Partner.objects.get_or_none(name=partner_name)
        if not partner:
            return general_error_response("Partner not found")

        lender = get_qris_lender_from_lender_name(lender_name=lender_name)
        if not lender:
            return general_error_response("Lender not valid")

        try:
            QrisUploadSignatureService(
                customer=customer,
                signature_image_data=signature_image_data,
                partner=partner,
                lender=lender,
            ).process_linkage_and_upload_signature()

        except AlreadySignedWithLender as e:
            return general_error_response("Already signed with this lender")
        except DatabaseError as e:
            logger.info(
                {
                    "action": "juloserver.qris.views.view_api_v1.QrisUserSignatureView",
                    "message": "Database Error while uploading qris signature",
                    "customer_id": customer.id,
                    "error": str(e),
                }
            )
            return general_error_response("Duplicate request")

        return created_response()


class QrisUserState(StandardizedExceptionHandlerMixin, APIView):
    """
    Get user's linkage data based on partner
    """

    class InputSerializer(serializers.Serializer):
        partner_name = serializers.CharField(required=True)

        def validate_partner_name(self, value):
            if value not in PartnerNameConstant.qris_partners():
                raise ValidationError("Invalid Partner")

            return value

    class OutputSerializer(serializers.Serializer):
        """
        Only for reference, not to call is_valid()
        """
        email = serializers.CharField(required=True)
        phone = serializers.CharField(required=True)
        to_partner_xid = serializers.CharField(required=True)
        nik = serializers.CharField(required=True)
        signature_id = serializers.CharField(required=True)
        is_linkage_active = serializers.BooleanField(required=True)
        faq_link = serializers.CharField(required=False)
        available_limit = serializers.IntegerField(required=False)
        to_sign_lender = serializers.CharField(required=False, allow_blank=True)
        registration_progress_bar = serializers.JSONField(required=False)

    def get(self, request):
        input_serializer = self.InputSerializer(data=request.query_params)
        input_serializer.is_valid(raise_exception=True)

        # set up service object
        partner_name = input_serializer.validated_data['partner_name']
        try:
            service = get_qris_user_state_service(
                customer_id=request.user.customer.id,
                partner_name=partner_name,
            )

            response_data = service.get_response()

            output_serializer = self.OutputSerializer(response_data)

            return success_response(data=output_serializer.data)
        except NoQrisLenderAvailable:
            error_message = LoanErrorCodes.NO_LENDER_AVAILABLE.message
            error_code = LoanErrorCodes.NO_LENDER_AVAILABLE.code
        except Exception:
            sentry_client.captureException()
            error_message = LoanErrorCodes.GENERAL_ERROR.message
            error_code = LoanErrorCodes.GENERAL_ERROR.code

        logger.error(
            {
                "action": "qris.views.QrisUserState.get",
                "customer_id": request.user.customer.id,
                "error_message": error_message,
                "error_code": error_code,
                "request_data": input_serializer.validated_data,
            }
        )
        return qris_error_response(error_message, error_code)


class AmarRegisterLoginCallbackView(QRISAPIView):
    class InputSerializer(serializers.Serializer):
        partnerCustomerId = serializers.CharField()
        status = serializers.CharField()
        type = serializers.CharField()
        accountNumber = serializers.CharField(allow_blank=True)
        client_id = serializers.CharField(required=False, allow_blank=True)
        reject_reason = serializers.CharField(required=False, allow_blank=True)
        source_type = serializers.CharField(required=False, allow_blank=True)

        def validate_status(self, value):
            if value not in AmarCallbackConst.AccountRegister.statuses():
                raise serializers.ValidationError("invalid status: {}".format(value))
            return value

        def validate_type(self, value):
            if value not in AmarCallbackConst.AccountRegister.types():
                raise serializers.ValidationError("invalid type: {}".format(value))
            return value

        def validate_partnerCustomerId(self, value):
            if not is_uuid_valid(value):
                raise serializers.ValidationError("invalid value")

            return value

    def post(self, request, *args, **kwargs):
        logger.info(
            {
                "action": "juloserver.qris.views.view_api_v1.AmarRegisterLoginCallbackView",
                "message": "register/login callback from amar",
                "callback_data": request.data,
            }
        )
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # use initial data, if new field is added no need for development
        initial_data = serializer.initial_data
        service = AmarRegisterLoginCallbackService(
            data=initial_data,
        )

        service.process_callback()

        return success_response()


class TransactionConfirmationView(QRISAPIView):
    serializer_class = QRISTransactionSerializer

    def post(self, request, *args, **kwargs):
        logger.info(
            {
                "action": "qris.views.TransactionConfirmationView.post",
                "data": request.data,
            }
        )
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        service = TransactionConfirmationService(
            request_data=validated_data,
            partner_id=request.user.partner.pk,
        )
        try:
            response_data = service.process_transaction_confirmation()
            logger.info(
                {
                    "action": "qris.views.TransactionConfirmationView.post_success",
                    "response_data": response_data,
                }
            )
            return qris_success_response(response_data)

        except DatabaseError as e:
            error_message = LoanErrorCodes.DUPLICATE_TRANSACTION.message
            error_code = LoanErrorCodes.DUPLICATE_TRANSACTION.code
            error_detail = LoanErrorCodes.DUPLICATE_TRANSACTION.name
        except LoggableException as e:
            error_message = e.get_fe_message()
            error_code = e.get_code()
            error_detail = e.get_detail()
        except Exception as e:
            sentry_client.captureException()
            error_message = LoanErrorCodes.GENERAL_ERROR.message
            error_code = LoanErrorCodes.GENERAL_ERROR.code
            error_detail = str(e)

        # Logging  & return 400 response
        # get identifier for logging
        identifier = validated_data['partnerUserId']
        identifier_type = LoanLogIdentifierType.TO_AMAR_USER_XID
        if service.qris_partner_linkage:
            identifier = service.qris_partner_linkage.customer_id
            identifier_type = LoanLogIdentifierType.CUSTOMER_ID

        logger.error(
            {
                "action": "qris.views.TransactionConfirmationView.post_error",
                "error_message": error_message,
                "error_code": error_code,
                "request_data": validated_data,
                "identifier": identifier,
            }
        )

        log_qris_error(
            LoanErrorLogData(
                identifier=identifier,
                identifier_type=identifier_type,
                error_code=error_code,
                error_detail=error_detail,
                http_status_code=400,
                api_url=request.path,
            )
        )
        return qris_error_response(error_message, error_code)


class QrisTransactionListView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        limit = int(self.request.query_params.get("limit", 0))
        partner_name = self.request.query_params.get("partner_name")
        partner = Partner.objects.get_or_none(name=partner_name)
        if not partner:
            return general_error_response("Partner not found")

        customer = request.user.customer
        try:
            qris_list_transaction_service = QrisListTransactionService(
                customer_id=customer.id, partner_id=partner.pk
            )
            transactions = qris_list_transaction_service.get_successful_transaction(limit=limit)
            return success_response(transactions)
        except QrisLinkageNotFound:
            return general_error_response("Qris User Linkage not found")


class AmarLoanCallbackView(QRISAPIView):
    class InputSerializer(serializers.Serializer):
        class DataFieldSerializer(serializers.Serializer):
            merchantName = serializers.CharField()
            merchantCity = serializers.CharField()
            merchantPan = serializers.CharField(required=False, allow_blank=True)
            transactionID = serializers.CharField()
            customerPan = serializers.CharField(required=False, allow_blank=True)
            amount = serializers.CharField()

        serviceId = serializers.CharField()
        amarbankAccount = serializers.CharField()
        partnerCustomerID = serializers.CharField()
        timestamp = serializers.CharField()
        statusCode = serializers.CharField()
        data = DataFieldSerializer()

        def validate_serviceId(self, value):
            if value != AmarCallbackConst.LoanDisbursement.SERVICE_ID:
                raise serializers.ValidationError("invalid value")

            return value

        def validate_partnerCustomerID(self, value):
            if not is_uuid_valid(value):
                raise serializers.ValidationError("invalid value")

            return value

        def validate_statusCode(self, value):
            if value not in AmarCallbackConst.LoanDisbursement.statuses():
                raise serializers.ValidationError("invalid value")

            return value

    def post(self, request, *args, **kwargs):
        logger.info(
            {
                "action": "juloserver.qris.views.view_api_v1.AmarLoanCallbackView",
                "message": "Amar Transaction Status Callback API Log",
                "payload": self.request.data,
            }
        )

        serializer = self.InputSerializer(
            data=request.data,
        )

        is_valid = serializer.is_valid()
        if not is_valid:
            sentry_client.captureMessage(
                "Amar sent bad AmarLoanCallbackView data",
            )
            field = list(serializer.errors.keys())[0]
            return qris_error_response(
                error_code=LoanErrorCodes.GENERAL_ERROR.code,
                message="{}: invalid value".format(field),
            )

        # use initial data, if new field is added no need for development
        service = AmarTransactionStatusCallbackService(
            validated_data=serializer.initial_data,
        )

        service.process_callback()

        return qris_success_response()


class QrisTenureRangeView(StandardizedExceptionHandlerMixin, APIView):
    """
    User calls the view to get data about qris tenure based on loan amount
    """

    def get(self, request, *args, **kwargs):
        customer = request.user.customer

        service = QrisTenureRangeService(
            customer=customer,
        )
        response_data = service.get_response()
        return success_response(data=response_data)


class QrisConfigView(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        qris_config = get_qris_landing_page_config_feature_setting()
        return success_response(qris_config)

from __future__ import unicode_literals

import logging

from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
    response_template,
    created_response,
    internal_server_error_response,
    forbidden_error_response,
)
from juloserver.julo.clients import get_julo_sentry_client

from rest_framework.decorators import parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from juloserver.credit_card.services.registration_related import (
    card_stock_check,
    card_requests,
    image_resubmission,
    card_stock_eligibility,
    credit_card_tnc,
    customer_tnc_created,
    get_customer_tnc,
    credit_card_confirmation,
    activation_card,
    send_otp,
    data_upload
)
from juloserver.credit_card.services.ccs_related import (
    card_status_change,
    data_bucket,
    credit_card_app_details,
    credit_card_app_list,
    assign_card,
)
from juloserver.credit_card.serializers import (
    CardRequestSerializer,
    CardAgentVerificationSerializer,
    CardValidateSerializer,
    CardActivationSerializer,
    SendOTPSerializer,
    LoginCardControlSerializer,
    CreditCardTransactionSerializer,
    CreditCardChangePinSerializer,
    BlockCardSeriaizer,
    UnblockCardSerializer,
    ResetPinCreditCardSerializer,
    CheckOTPSerializer,
    CardAgentUploadDocsSerializer,
    CardApplicationListSerializer,
    ReversalJuloCardTransactionSerializer,
    NotifyJuloCardStatusChangeSerializer,
    BlockCardCCSSerializer,
    CheckCardSerializer,
    AssignCardSerializer,
    JuloCardBannerSerializer,
    TransactionHistorySerializer,
)
from juloserver.credit_card.constants import (
    ErrorMessage,
    BSSResponseConstant,
    BSSTransactionConstant,
    FeatureNameConst,
    ReasonCardApplicationHistory,
)
from juloserver.credit_card.services.card_related import (
    get_credit_card_information,
    get_credit_card_application_status,
    change_pin_credit_card,
    block_card,
    unblock_card,
    reset_pin_credit_card,
    update_card_application_history,
)
from juloserver.credit_card.services.transaction_related import (
    validate_transaction,
    get_loan_related_data,
    store_credit_card_transaction,
    submit_previous_loan,
    construct_transaction_history_data,
)
from juloserver.credit_card.models import (
    CreditCardApplication,
    CreditCard,
    CreditCardTransaction,
    JuloCardBanner,
)
from juloserver.credit_card.exceptions import (
    CreditCardNotFound,
    FailedResponseBssApiError,
    IncorrectOTP,
    CreditCardApplicationNotFound,
    CreditCardApplicationHasCardNumber,
    CardNumberNotAvailable,
)
from juloserver.credit_card.tasks.notification_tasks import (
    send_pn_change_tenor,
    send_pn_transaction_completed,
)
from juloserver.credit_card.utils import (
    ccs_agent_group_required,
    role_allowed,
)

from juloserver.julo.statuses import (
    CreditCardCodes,
    LoanStatusCodes,
)
from juloserver.julo.models import (
    OtpRequest,
    FeatureSetting,
)

import juloserver.pin.services as pin_services
from juloserver.pin.constants import VerifyPinMsg
from juloserver.pin.exceptions import (
    PinIsDOB,
    PinIsWeakness,
)
from juloserver.pin.decorators import pin_verify_required
from juloserver.pin.utils import transform_error_msg

from juloserver.otp.constants import (
    OTPRequestStatus,
    OTPResponseHTTPStatusCode,
)

from juloserver.api_token.authentication import generate_new_token

from juloserver.account.models import AccountLimit
from juloserver.account.services.credit_limit import update_available_limit

from juloserver.loan.services.loan_related import (
    generate_loan_payment_julo_one,
    update_loan_status_and_loan_history,

)

from juloserver.account_payment.services.account_payment_related import void_transaction

from juloserver.credit_card.tasks.transaction_tasks import upload_sphp_loan_credit_card_to_oss

from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.constants import TransactionMethodCode

from juloserver.portal.object.dashboard.constants import JuloUserRoles

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class CardStockView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request):
        customer_id = request.user.customer.id

        if customer_id:
            if not card_stock_eligibility(customer_id):
                return general_error_response("Customer is not authorized")

            card_stock = card_stock_check()

            return success_response({'stock_ready': card_stock})

        return general_error_response("Customer is not authorized")


class CardRequestView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CardRequestSerializer

    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer_id = request.user.customer.id

        if not customer_id:
            return not_found_response(
                "customer not found",
                {'customer_id': 'No valid customer'}
            )

        card_req = card_requests(customer_id, data)

        if not card_req:
            return general_error_response("Customer card request failed")

        return success_response()


class CardDataResubmissionView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CardRequestSerializer

    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        image_selfie = data['image_selfie']

        customer_id = request.user.customer.id

        if not customer_id:
            return not_found_response(
                "customer not found",
                {'customer_id': 'No valid customer'}
            )
        account = request.user.customer.account_set.last()

        credit_card_application = account.creditcardapplication_set.last()
        if credit_card_application.status_id != CreditCardCodes.RESUBMIT_SELFIE:
            return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)

        image_resubmit = image_resubmission(image_selfie, credit_card_application)

        if not image_resubmit:
            return general_error_response("Image resubmission failed")

        credit_card_application.address.update_safely(
            latitude=data['latitude'],
            longitude=data['longitude'],
            provinsi=data['provinsi'],
            kabupaten=data['kabupaten'],
            kecamatan=data['kecamatan'],
            kelurahan=data['kelurahan'],
            kodepos=data['kodepos'],
            detail=data['address_detail']
        )

        update_card_application_history(
            credit_card_application.id,
            credit_card_application.status_id,
            CreditCardCodes.CARD_APPLICATION_SUBMITTED,
            ReasonCardApplicationHistory.CUSTOMER_TRIGGERED,
            user_id=request.user.id
        )

        return success_response()


class CardChangeStatusView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CardAgentVerificationSerializer

    @ccs_agent_group_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        agent = user.agent

        if not agent or user.is_anonymous():
            return not_found_response(
                "agent not found",
                {'user_id': 'No valid agent'}
            )

        credit_card_application_id = data['credit_card_application_id']
        next_status = data['next_status']
        change_reason = data['change_reason']
        shipping_code = data['shipping_code']
        note_text = data['note_text']
        expedition_company = data['expedition_company']
        block_reason = data['block_reason']
        status_changed = card_status_change(credit_card_application_id,
                                            next_status, change_reason, user,
                                            shipping_code, note_text,
                                            expedition_company, block_reason)

        if not status_changed:
            return general_error_response("Customer status is not changed")

        return success_response(status_changed)


class CardBucketView(StandardizedExceptionHandlerMixin, APIView):
    @ccs_agent_group_required
    def get(self, request):
        user = request.user
        agent = user.agent

        if not agent or user.is_anonymous():
            return not_found_response(
                "agent not found",
                {'user_id': 'No valid agent'}
            )

        bucket = data_bucket()

        if not bucket:
            return general_error_response("Customer data is not retrieved")

        return success_response(bucket)


class CardApplicationListView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CardApplicationListSerializer

    @ccs_agent_group_required
    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        user = request.user
        agent = user.agent

        if not agent or user.is_anonymous():
            return not_found_response(
                "agent not found",
                {'user_id': 'No valid agent'}
            )

        app_list = credit_card_app_list(serializer.data)

        if not app_list:
            return general_error_response("Customer data is not listed")

        return success_response(app_list)


class CardApplicationDetailView(StandardizedExceptionHandlerMixin, APIView):
    @ccs_agent_group_required
    def get(self, request, *args, **kwargs):
        user = request.user
        agent = user.agent

        if not agent or user.is_anonymous():
            return not_found_response(
                "agent not found",
                {'user_id': 'No valid agent'}
            )

        credit_card_application_id = kwargs['credit_card_application_id']
        app_details = credit_card_app_details(credit_card_application_id)

        if not app_details:
            return general_error_response("Customer data is not verified")

        return success_response(app_details)


class CardInformation(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        try:
            account = request.user.customer.account_set.last()
            card_information = get_credit_card_information(account)
            if not card_information:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            return success_response(card_information)
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class CardStatus(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        try:
            account = request.user.customer.account_set.last()
            credit_card_application_status = get_credit_card_application_status(account)
            if not credit_card_application_status:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            return success_response(credit_card_application_status)
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class CardConfirmation(StandardizedExceptionHandlerMixin, APIView):
    @pin_verify_required
    def post(self, request):
        try:
            account = request.user.customer.account_set.last()
            credit_card_application = account.creditcardapplication_set.last()
            if not credit_card_application:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            if credit_card_application.status_id != CreditCardCodes.CARD_ON_SHIPPING:
                return general_error_response(ErrorMessage.FAILED_PROCESS)
            credit_card_confirmation(account)
            return success_response()
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class CardValidation(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        try:
            account = request.user.customer.account_set.last()
            serializer = CardValidateSerializer(data=request.data)
            if not serializer.is_valid():
                return general_error_response(serializer.errors)
            data = serializer.validated_data
            credit_card_application = CreditCardApplication.objects.only(
                'id', 'status',
            ).filter(account=account, status_id=CreditCardCodes.CARD_RECEIVED_BY_USER).last()
            if not credit_card_application:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            credit_card = credit_card_application.creditcard_set.only(
                'id', 'card_number', 'expired_date'
            ).last()
            if credit_card.card_number != data['card_number'] or \
                    credit_card.expired_date != data['expire_date']:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            update_card_application_history(
                credit_card_application.id, credit_card_application.status_id,
                CreditCardCodes.CARD_VALIDATED, 'customer_triggered'
            )
            return success_response()
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class CardActivation(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        try:
            serializer = CardActivationSerializer(data=request.data)
            if not serializer.is_valid():
                return general_error_response(serializer.errors)
            account = request.user.customer.account_set.last()
            data = serializer.validated_data
            try:
                pin_services.check_strong_pin(account.customer.nik, data['pin'])
            except PinIsDOB:
                return general_error_response(VerifyPinMsg.PIN_IS_DOB)
            except PinIsWeakness:
                return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)
            otp_request = OtpRequest.objects.filter(
                otp_token=data['otp'], customer=account.customer, is_used=False
            ).exists()
            if not otp_request:
                return general_error_response('OTP {}'.format(ErrorMessage.CREDIT_CARD_NOT_FOUND))
            error_message = activation_card(data, account)
            if error_message:
                return general_error_response(error_message)
            return success_response()
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class SendOTP(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        try:
            serializer = SendOTPSerializer(data=request.data)
            if not serializer.is_valid():
                return general_error_response(serializer.errors)
            account = request.user.customer.account_set.last()

            credit_card_application = CreditCardApplication.objects.only(
                'id', 'virtual_account_number', 'virtual_card_name',
            ).filter(account=account).last()

            if not credit_card_application:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)

            if credit_card_application.status_id < CreditCardCodes.CARD_RECEIVED_BY_USER and \
                    credit_card_application.status_id != CreditCardCodes.CARD_BLOCKED:
                return general_error_response(ErrorMessage.FAILED_PROCESS)

            credit_card = credit_card_application.creditcard_set.last()
            if not credit_card:
                return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            result, data = send_otp(
                serializer.validated_data['transaction_type'], credit_card_application
            )
            if result == OTPRequestStatus.RESEND_TIME_INSUFFICIENT:
                return response_template(
                    status=OTPResponseHTTPStatusCode.RESEND_TIME_INSUFFICIENT, success=False,
                    data=data,
                    message=['Too early'])

            if result == OTPRequestStatus.LIMIT_EXCEEDED:
                return response_template(
                    status=OTPResponseHTTPStatusCode.LIMIT_EXCEEDED, success=False, data=data,
                    message=['Exceeded limit of request'])
            return created_response(data)
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class LoginCardControlViews(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoginCardControlSerializer
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        data = serializer.validated_data

        user = User.objects.filter(username=data['username']).last()

        if not user or not user.check_password(data['password']):
            return general_error_response(ErrorMessage.WRONG_PASSWORD_OR_USERNAME)

        if not role_allowed(user, {JuloUserRoles.CCS_AGENT}):
            return forbidden_error_response('User not allowed')

        res_data = {
            'token': generate_new_token(user),
            'username': user.username,
        }

        return success_response(res_data)


class CreditCardTransactionView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        try:
            logger.info({
                "action": "CreditCardTransaction_payloads",
                "request_data": request.data,
            })
            serializer = CreditCardTransactionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                        'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']
                    }
                )
            data = serializer.data
            credit_card = CreditCard.objects.select_related(
                'credit_card_application', 'credit_card_application__account'
            ).filter(
                card_number=data['cardNumber'],
                credit_card_application__isnull=False,
            ).filter(credit_card_application__status=CreditCardCodes.CARD_ACTIVATED).last()
            if not credit_card:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.CARD_NOT_REGISTERED['code'],
                        'responseDescription': BSSResponseConstant.CARD_NOT_REGISTERED[
                            'description'
                        ]
                    }
                )
            account = credit_card.credit_card_application.account
            loan_related_data = get_loan_related_data(data, account)
            is_valid, bss_response, error_detail = validate_transaction(data, loan_related_data,
                                                                        credit_card)
            credit_card_transaction = store_credit_card_transaction(data, credit_card, is_valid,
                                                                    error_detail)
            if not is_valid:
                return Response(status=status.HTTP_400_BAD_REQUEST,
                                data={'responseCode': bss_response['code'],
                                      'responseDescription': bss_response['description']})
            credit_card_application = credit_card.credit_card_application
            account_limit = AccountLimit.objects.only(
                'id', 'available_limit'
            ).get(account=account)
            response_data = {
                "virtualAccountNumber": credit_card_application.virtual_account_number,
                "virtualAccountName": credit_card_application.virtual_card_name,
                "virtualAccountBalance": account_limit.available_limit,
                "responseCode": bss_response['code'],
                "responseDescription": bss_response['description']
            }
            if data['transactionType'] == BSSTransactionConstant.DECLINE_FEE:
                return Response(
                    status=status.HTTP_201_CREATED,
                    data=response_data
                )
            """
                if customer had loan with credit card product and status is 210, loan need move
                to the next process. submit_previous_loan function for checking and move the
                loan to the next process
            """
            submit_previous_loan(account)
            with transaction.atomic():
                loan = generate_loan_payment_julo_one(
                    account.last_application, loan_related_data, None,
                    loan_related_data['credit_matrix']
                )
                update_available_limit(loan)
                account_limit.refresh_from_db()
                response_data["virtualAccountBalance"] = account_limit.available_limit
                credit_card_transaction.update_safely(
                    loan=loan, tenor_options=loan_related_data["available_durations"]
                )
                credit_card_transaction_method = TransactionMethod.objects.get(
                    pk=TransactionMethodCode.CREDIT_CARD.code
                )
                loan.update_safely(transaction_method=credit_card_transaction_method)
                current_ts = timezone.localtime(timezone.now())
                loan.update_safely(sphp_accepted_ts=current_ts)
            upload_sphp_loan_credit_card_to_oss.delay(loan.id)
            if len(loan_related_data['available_durations']) > 1:
                send_pn_change_tenor.delay(account.customer.id)
            else:
                send_pn_transaction_completed.delay(
                    account.customer.id, loan.loan_duration, loan.loan_xid
                )

            return Response(
                status=status.HTTP_201_CREATED,
                data=response_data
            )
        except Exception as e:
            sentry_client.capture_exceptions()
            logger.error({
                "action": "juloserver.credit_card.views.views_api_v1.CreditCardTransaction",
                "error": str(e),
                "request_data": request.data,
            })
            return Response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                      'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']}
            )


class CreditCardChangePinViews(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = CreditCardChangePinSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        data = serializer.validated_data
        account = request.user.customer.account_set.last()
        credit_card = CreditCard.objects.select_related(
            'credit_card_application'
        ).filter(
            credit_card_application__isnull=False,
            credit_card_application__account=account,
        ).filter(credit_card_application__status=CreditCardCodes.CARD_ACTIVATED).last()
        if not credit_card:
            return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
        try:
            pin_services.check_strong_pin(account.customer.nik, data['new_pin'])
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)
        response = change_pin_credit_card(credit_card, data['old_pin'], data['new_pin'])
        if 'error' in response or response['responseCode'] != '00':
            get_credit_card_application_status(account)
            return general_error_response(ErrorMessage.FAILED_PIN_RELATED)
        return success_response()


class BlockCard(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        try:
            serializer = BlockCardSeriaizer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            account = request.user.customer.account_set.last()
            credit_card_application = account.creditcardapplication_set.last()
            if not credit_card_application:
                return not_found_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            if credit_card_application.status_id != CreditCardCodes.CARD_ACTIVATED:
                return general_error_response(ErrorMessage.FAILED_PROCESS)

            block_card(credit_card_application, data['block_reason'])
            return success_response()
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class CCSBlockCard(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        try:
            serializer = BlockCardCCSSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            user = request.user
            agent = user.agent

            if not agent or user.is_anonymous():
                return not_found_response(
                    "agent not found",
                    {'user_id': 'No valid agent'}
                )

            block_reason = data['block_reason']
            credit_card_application_id = data['credit_card_application_id']
            credit_card_application = CreditCardApplication.objects.filter(
                id=credit_card_application_id
            ).last()
            if not credit_card_application:
                return not_found_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
            if credit_card_application.status_id != CreditCardCodes.CARD_ACTIVATED:
                return general_error_response(ErrorMessage.FAILED_PROCESS)

            block_card(credit_card_application, block_reason, block_from_ccs=True)
            return success_response()
        except Exception as e:
            return internal_server_error_response(message=str(e))


class BlockReason(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        try:
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.CREDIT_CARD_BLOCK_REASON
            ).last()
            if not feature_setting or not feature_setting.parameters:
                return not_found_response('reason not found')
            return success_response(feature_setting.parameters)
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class UnblockCardView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = UnblockCardSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        data = serializer.validated_data
        account = request.user.customer.account_set.last()

        try:
            unblock_card(account, data['pin'])
            return success_response()
        except CreditCardNotFound:
            return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
        except FailedResponseBssApiError:
            return general_error_response(ErrorMessage.FAILED_PIN_RELATED)


class ResetPinCreditCardViews(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ResetPinCreditCardSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )
        data = serializer.validated_data
        account = request.user.customer.account_set.last()
        try:
            pin_services.check_strong_pin(account.customer.nik, data['pin'])
            reset_pin_credit_card(account, data['pin'], data['otp'])
            return success_response()
        except PinIsDOB:
            return general_error_response(VerifyPinMsg.PIN_IS_DOB)
        except PinIsWeakness:
            return general_error_response(VerifyPinMsg.PIN_IS_TOO_WEAK)
        except CreditCardNotFound:
            return general_error_response(ErrorMessage.CREDIT_CARD_NOT_FOUND)
        except IncorrectOTP:
            return general_error_response(ErrorMessage.INCORRECT_OTP)
        except FailedResponseBssApiError:
            return general_error_response(ErrorMessage.FAILED_PROCESS)


class CheckOTP(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        serializer = CheckOTPSerializer(data=request.GET)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors)[0]
            )
        data = serializer.validated_data
        customer = request.user.customer
        otp_request = OtpRequest.objects.only('id', 'otp_token', 'is_used').filter(
            customer=customer, action_type=data['otp_type']
        ).last()
        if not otp_request or otp_request.is_used or otp_request.otp_token != data['otp']:
            return general_error_response('OTP tidak valid')
        return success_response()


class CreditCardFaq(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        try:
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.CREDIT_CARD_FAQ
            ).last()
            if not feature_setting or not feature_setting.parameters:
                return not_found_response('faq not found')
            return success_response(feature_setting.parameters)
        except Exception as e:
            sentry_client.capture_exceptions()
            return internal_server_error_response(message=str(e))


class CardAgentUploadDocsView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CardAgentUploadDocsSerializer

    @ccs_agent_group_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        agent = user.agent

        if not agent or user.is_anonymous():
            return not_found_response(
                "agent not found",
                {'user_id': 'No valid agent'}
            )

        credit_card_csv = data['credit_card_csv']

        data_uploaded = data_upload(credit_card_csv)

        if not data_uploaded:
            return general_error_response("Agent upload data failed")

        return success_response({'data_uploaded': True})


class CardTNCView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request):
        customer_id = request.user.customer.id

        if customer_id:
            if not card_stock_eligibility(customer_id):
                return general_error_response("Customer is not authorized")

            tnc = credit_card_tnc(customer_id)

            return success_response({'tnc': tnc})

        return general_error_response("Customer is not authorized")


class CustomerTNCAgreementView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request):
        customer_id = request.user.customer.id

        if not customer_id:
            return not_found_response(
                "customer not found",
                {'customer_id': 'No valid customer'}
            )

        tnc_created = customer_tnc_created(customer_id)

        if not tnc_created:
            return general_error_response("Customer TNC Document not Created")

        return success_response({"tnc_created": True})


class CustomerTNCAgreementGetCustomerTNCAgreementView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request):
        customer_id = request.user.customer.id

        if not customer_id:
            return not_found_response(
                "customer not found",
                {'customer_id': 'No valid customer'}
            )

        customer_tnc = get_customer_tnc(customer_id)

        if not customer_tnc:
            return general_error_response("Customer TNC not available")

        return success_response({'tnc_pdf_url': customer_tnc})


class ReversalJuloCardTransactionView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = ReversalJuloCardTransactionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                    'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']
                }
            )
        data = serializer.data
        try:
            if data['transactionType'] != BSSTransactionConstant.EDC:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                        'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']
                    }
                )
            credit_card = CreditCard.objects.select_related(
                'credit_card_application', 'credit_card_application__account'
            ).filter(
                card_number=data['cardNumber'],
                credit_card_application__isnull=False,
            ).last()
            if not credit_card:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.CARD_NOT_REGISTERED['code'],
                        'responseDescription': BSSResponseConstant.CARD_NOT_REGISTERED[
                            'description'
                        ]
                    }
                )
            credit_card_transaction = CreditCardTransaction.objects.filter(
                reference_number=data['referenceNumber'],
                amount=data['amount'],
                fee=data['fee'],
                terminal_type=data['terminalType'],
                terminal_id=data['terminalId'],
                loan__isnull=False,
            ).last()
            if not credit_card_transaction:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.TRANSACTION_NOT_FOUND['code'],
                        'responseDescription': BSSResponseConstant.TRANSACTION_NOT_FOUND[
                            'description'
                        ]
                    }
                )
            loan = credit_card_transaction.loan
            with transaction.atomic():
                update_loan_status_and_loan_history(loan.id, LoanStatusCodes.TRANSACTION_FAILED)
                void_transaction(loan)

                return Response(
                    status=status.HTTP_200_OK,
                    data={
                        "responseCode": BSSResponseConstant.TRANSACTION_SUCCESS['code'],
                        "responseDescription": BSSResponseConstant.TRANSACTION_SUCCESS[
                            'description']
                    }
                )
        except Exception:
            sentry_client.capture_exceptions()
            return Response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={
                    'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                    'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']
                }
            )


class NotifyJuloCardStatusChangeView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        try:
            logger.info({
                "action": "NotifyJuloCardStatusChangeView_payloads",
                "request_data": request.data,
            })
            serializer = NotifyJuloCardStatusChangeSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                        'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']
                    }
                )
            data = serializer.validated_data
            credit_card = CreditCard.objects.only(
                'id', 'credit_card_application__id',
                'credit_card_application__status__status_code'
            ).filter(
                card_number=data['cardNumber'],
                credit_card_application__isnull=False,
            ).select_related(
                'credit_card_application'
            ).last()
            if not credit_card:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        'responseCode': BSSResponseConstant.CARD_NOT_REGISTERED['code'],
                        'responseDescription': BSSResponseConstant.CARD_NOT_REGISTERED[
                            'description'
                        ]
                    }
                )
            credit_card_application = credit_card.credit_card_application
            if credit_card_application.status_id == CreditCardCodes.CARD_BLOCKED_WRONG_PIN:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                          'responseDescription': BSSResponseConstant.TRANSACTION_FAILED[
                              'description']}
                )
            if 'pin tries' != data['currentCardStatus'].lower():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={'responseCode': BSSResponseConstant.DATA_NOT_COMPLETE['code'],
                          'responseDescription': BSSResponseConstant.DATA_NOT_COMPLETE[
                              'description']}
                )
            update_card_application_history(
                credit_card_application.id,
                credit_card_application.status_id,
                CreditCardCodes.CARD_BLOCKED_WRONG_PIN,
                "Change by system",
                "Wrong pin 3 times",
            )
            return Response(
                status=status.HTTP_200_OK,
                data={'responseCode': BSSResponseConstant.TRANSACTION_SUCCESS['code'],
                      'responseDescription': BSSResponseConstant.TRANSACTION_SUCCESS['description']}
            )
        except Exception:
            sentry_client.capture_exceptions()
            return Response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data={'responseCode': BSSResponseConstant.TRANSACTION_FAILED['code'],
                      'responseDescription': BSSResponseConstant.TRANSACTION_FAILED['description']}
            )


class CheckCardView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CheckCardSerializer

    @ccs_agent_group_required
    def get(self, request):
        serializer = self.serializer_class(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)

        credit_card = CreditCard.objects.filter(
            card_number=serializer.validated_data['card_number'],
        ).last()

        if not credit_card:
            return not_found_response(ErrorMessage.CARD_NUMBER_INVALID)

        if credit_card.credit_card_application:
            return general_error_response(ErrorMessage.CARD_NUMBER_NOT_AVAILABLE)

        return success_response()


class AssignCardView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = AssignCardSerializer

    @ccs_agent_group_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            assign_card(data['card_number'], data['credit_card_application_id'])
        except CreditCardNotFound:
            return not_found_response(ErrorMessage.CARD_NUMBER_INVALID)
        except CreditCardApplicationNotFound:
            return not_found_response(ErrorMessage.CARD_APPLICATION_ID_INVALID)
        except CreditCardApplicationHasCardNumber:
            return general_error_response(ErrorMessage.CARD_APPLICATION_HAS_CARD_NUMBER)
        except CardNumberNotAvailable:
            return general_error_response(ErrorMessage.CARD_NUMBER_NOT_AVAILABLE)

        return success_response()


class BannerView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        julo_card_banners = JuloCardBanner.objects.select_related('image').filter(
            is_active=True,
        ).order_by('display_order')
        serializer = JuloCardBannerSerializer(julo_card_banners, many=True)
        return success_response(serializer.data)


class TransactionHistoryView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        serializer = TransactionHistorySerializer(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        credit_card_application = CreditCardApplication.objects.only('id').filter(
            account__customer=request.user.customer
        ).last()
        if not credit_card_application:
            return general_error_response('Julo Card tidak ditemukan')
        credit_card_transaction_id = data.get('credit_card_transaction_id')
        limit = data.get('limit', 50)
        query_filter = {
            'credit_card_application_id': credit_card_application.id,
            'loan__loan_status_id__gte': LoanStatusCodes.LENDER_APPROVAL
        }
        if credit_card_transaction_id:
            query_filter['pk__lt'] = credit_card_transaction_id
        credit_card_transactions = (
            CreditCardTransaction.objects
            .select_related('loan', 'loan__loan_status')
            .only('id', 'terminal_location', 'transaction_date', 'loan__id', 'loan__loan_amount',
                  'loan__loan_duration', 'loan__loan_xid', 'loan__loan_status_id',
                  'loan__loan_status__status_code', 'amount')
            .filter(**query_filter)
            .exclude(loan__loan_status_id__in={LoanStatusCodes.TRANSACTION_FAILED,
                                               LoanStatusCodes.CANCELLED_BY_CUSTOMER})
            .order_by('-id')[:limit]
        )
        transaction_history_data = construct_transaction_history_data(credit_card_transactions)
        return success_response(transaction_history_data)

import logging
from datetime import timedelta, datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http.response import JsonResponse
from django.utils import timezone
from rest_framework.status import HTTP_200_OK, HTTP_404_NOT_FOUND

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.autodebet.services.benefit_services import (
    is_eligible_to_get_benefit,
    give_benefit,
)
from juloserver.julo.models import PaybackTransaction
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin
)
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    forbidden_error_response,
)

from juloserver.autodebet.serializers import (
    BNIActivationNotificationSerializer,
    BNIDeactivationSerializer,
    AutodebetSuspendReactivationSerializer,
    BNIPurchaseNotificationSerializer,
    BNIAccessTokenSerializer,
)
from juloserver.autodebet.services.task_services import get_autodebet_payment_method
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    AutodebetBNILatestTransactionStatusConst,
    VendorConst,
    BNICardBindCallbackResponseCodeMessageDescription,
    AutodebetBNIErrorMessageConst,
    AutodebetStatuses,
    BNIPurchaseCallbackResponseCodeMessageDescription,
    AutodebetBNIResponseCodeConst,
    BNIErrorCode,
    RedisKey,
    BNIAyoConnectAccessTokenCodeMessageDescription,
)
from juloserver.autodebet.models import (
    AutodebetBniAccount,
    AutodebetBniTransaction,
    AutodebetBenefit,
)
from juloserver.autodebet.services.bni_services import (
    activation_bni_autodebet,
    bind_bni_autodebet,
    bni_account_unbinding,
    bni_unbinding_otp_verification,
    bni_generate_access_token,
    bni_check_authorization,
)
from juloserver.autodebet.tasks import (
    store_autodebet_api_log,
    send_slack_notify_autodebet_bni_failed_deduction,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment

from juloserver.moengage.tasks import (
    update_moengage_for_payment_received_task,
    send_event_autodebit_failed_deduction_task,
)
from juloserver.autodebet.services.account_services import (
    autodebet_account_reactivation_from_suspended,
)
from juloserver.autodebet.services.autodebet_services import (
    suspend_autodebet_insufficient_balance,
    is_fully_paid_or_limit,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class BNIActivationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        web_view_url, error_message = activation_bni_autodebet(account)
        if error_message:
            error_response = general_error_response
            if error_message == AutodebetBNIErrorMessageConst.WRONG_OTP_THREE_TIMES:
                error_response = forbidden_error_response
            return error_response(error_message)
        response_data = {
            "account_status": "PENDING",
            "web_linking": web_view_url,
        }
        return success_response(response_data)


class BNICardBindCallbackView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        headers = {'HTTP_AUTHORIZATION': request.META.get('HTTP_AUTHORIZATION', None)}
        data_to_log = {
            "action": "BNIActivationNotificationCallbackView",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        store_autodebet_api_log.delay(
            request_body, response.content, response.status_code,
            '[POST] {}'.format(request.get_full_path()), VendorConst.BNI,
            self.kwargs.get('account_id'),
            self.kwargs.get('account_payment_id'), self.kwargs.get('error_message'),
        )
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)
        return

    def post(self, request):
        redis_client = get_redis_client()
        response_data = {
            "responseCode": BNICardBindCallbackResponseCodeMessageDescription.SUCCESS.code,
            "responseMessage": BNICardBindCallbackResponseCodeMessageDescription.SUCCESS.message,
        }
        try:
            authorization = request.META.get('HTTP_AUTHORIZATION', None)
            access_token = redis_client.get(RedisKey.BNI_AYOCONNECT_TOKEN + authorization)

            is_authentication_valid, error_data = bni_check_authorization(
                authorization, access_token
            )

            if not is_authentication_valid:
                return JsonResponse(data=error_data, status=status.HTTP_401_UNAUTHORIZED)

            serializer = BNIActivationNotificationSerializer(data=request.data)
            if not serializer.is_valid():
                field, error = list(serializer.errors.items())[0]
                response_data["responseCode"] = (
                    BNICardBindCallbackResponseCodeMessageDescription.INVALID_FIELD.code)
                response_data["responseDescription"] = "{} {}".format(field, error[0])
                response_data["responseMessage"] = "Invalid field {}".format(field)
                self.kwargs['error_message'] = response_data["responseDescription"]
                return JsonResponse(data=response_data, status=status.HTTP_400_BAD_REQUEST)
            data = serializer.validated_data
            x_external_id = data['additionalInfo']['X-External-ID']
            autodebet_bni_account = AutodebetBniAccount.objects.filter(
                x_external_id=x_external_id
            ).last()
            if not autodebet_bni_account:
                response_data["responseCode"] = (
                    BNICardBindCallbackResponseCodeMessageDescription.CARD_NOT_FOUND.code)
                response_data["responseDescription"] = (
                    BNICardBindCallbackResponseCodeMessageDescription.CARD_NOT_FOUND.description)
                response_data["responseMessage"] = (
                    BNICardBindCallbackResponseCodeMessageDescription.CARD_NOT_FOUND.message)
                self.kwargs['error_message'] = response_data["responseDescription"]
                return JsonResponse(data=response_data, status=status.HTTP_404_NOT_FOUND)
            if data['latestTransactionStatus'] == AutodebetBNILatestTransactionStatusConst.SUCCESS:
                get_autodebet_payment_method(
                    autodebet_bni_account.autodebet_account.account,
                    AutodebetVendorConst.BNI,
                    AutodebetVendorConst.PAYMENT_METHOD.get(AutodebetVendorConst.BNI)
                )
                autodebet_bni_account.update_safely(
                    status='active',
                )
                autodebet_bni_account.autodebet_account.update_safely(
                    activation_ts=timezone.localtime(timezone.now()),
                    is_use_autodebet=True,
                    status=AutodebetStatuses.REGISTERED
                )
            return JsonResponse(data=response_data, status=status.HTTP_200_OK)
        except Exception as e:
            response_data["responseCode"] = (
                BNICardBindCallbackResponseCodeMessageDescription.INTERNAL_SERVER_ERROR.code)
            response_data["responseMessage"] = (
                BNICardBindCallbackResponseCodeMessageDescription.INTERNAL_SERVER_ERROR.message)
            response_data["responseDescription"] = (
                BNICardBindCallbackResponseCodeMessageDescription.INTERNAL_SERVER_ERROR.description)
            sentry_client.captureException()
            self.kwargs['error_message'] = str(e)
            return JsonResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)


class BNIBindView(APIView):
    def post(self, request):
        account = request.user.customer.account
        error_message = bind_bni_autodebet(account)
        if error_message:
            return general_error_response(error_message)
        response_data = {
            "status": "ACTIVE"
        }
        return success_response(response_data)


class BNIAccountUnbinding(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        message, status = bni_account_unbinding(account)

        if not status:
            return general_error_response(message)

        return success_response({'unlinkResult': 'pending_user_verification'})


class BNIOtpVerification(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = BNIDeactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = request.user.customer.account
        message, status = bni_unbinding_otp_verification(account, serializer.data['otp_key'])

        if not status:
            return general_error_response(message)

        return success_response({'status': 'SUCCESS'})


class BNIPurchaseCallbackView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        is_send_slack_alert = self.kwargs.get('is_send_slack_alert', False)

        if (
            response.status_code != HTTP_200_OK and response.status_code != HTTP_404_NOT_FOUND
        ) or is_send_slack_alert:
            send_slack_notify_autodebet_bni_failed_deduction.delay(
                self.kwargs.get('account_id'),
                self.kwargs.get('account_payment_id'),
                self.kwargs.get('x_external_id'),
                self.kwargs.get('slack_error_message'),
            )

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        headers = {'HTTP_AUTHORIZATION': request.META.get('HTTP_AUTHORIZATION', None)}
        data_to_log = {
            "action": "BNIPurchaseNotificationCallbackView",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        store_autodebet_api_log.delay(
            request_body,
            response.content,
            response.status_code,
            '[POST] {}'.format(request.get_full_path()),
            VendorConst.BNI,
            self.kwargs.get('account_id'),
            self.kwargs.get('account_payment_id'),
            self.kwargs.get('error_message'),
        )
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)
        return

    def post(self, request):
        redis_client = get_redis_client()

        response_data = {
            "responseCode": BNIPurchaseCallbackResponseCodeMessageDescription.SUCCESS.code,
            "responseMessage": BNIPurchaseCallbackResponseCodeMessageDescription.SUCCESS.message,
        }
        try:
            authorization = request.META.get('HTTP_AUTHORIZATION', None)
            access_token = redis_client.get(RedisKey.BNI_AYOCONNECT_TOKEN + authorization)
            is_authentication_valid, error_data = bni_check_authorization(
                authorization, access_token
            )

            if not is_authentication_valid:
                return JsonResponse(data=error_data, status=status.HTTP_401_UNAUTHORIZED)

            serializer = BNIPurchaseNotificationSerializer(data=request.data)
            if not serializer.is_valid():
                field, error = list(serializer.errors.items())[0]
                response_data[
                    "responseCode"
                ] = BNICardBindCallbackResponseCodeMessageDescription.INVALID_FIELD.code
                response_data["responseDescription"] = "{} {}".format(field, error[0])
                response_data["responseMessage"] = "Invalid field {}".format(field)
                self.kwargs['error_message'] = response_data["responseDescription"]
                return JsonResponse(data=response_data, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data
            x_external_id = data['additionalInfo']['X-External-ID']
            self.kwargs['x_external_id'] = x_external_id
            self.kwargs['original_partner_reference_no'] = data["originalPartnerReferenceNo"]
            autodebet_bni_transaction = AutodebetBniTransaction.objects.filter(
                x_external_id=x_external_id,
                status=AutodebetBNILatestTransactionStatusConst.PROCESSING,
            ).last()

            if not autodebet_bni_transaction:
                response_data[
                    "responseCode"
                ] = BNIPurchaseCallbackResponseCodeMessageDescription.BILL_NOT_FOUND.code
                response_data[
                    "responseDescription"
                ] = BNIPurchaseCallbackResponseCodeMessageDescription.BILL_NOT_FOUND.description
                response_data[
                    "responseMessage"
                ] = BNIPurchaseCallbackResponseCodeMessageDescription.BILL_NOT_FOUND.message
                self.kwargs['slack_error_message'] = response_data["responseDescription"]
                return JsonResponse(data=response_data, status=status.HTTP_404_NOT_FOUND)

            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=x_external_id, is_processed=True
            ).exists()

            if payback_transaction:
                response_data[
                    "responseCode"
                ] = BNIPurchaseCallbackResponseCodeMessageDescription.BILL_IS_PAID.code
                response_data[
                    "responseDescription"
                ] = BNIPurchaseCallbackResponseCodeMessageDescription.BILL_IS_PAID.description
                response_data[
                    "responseMessage"
                ] = BNIPurchaseCallbackResponseCodeMessageDescription.BILL_IS_PAID.message
                self.kwargs['slack_error_message'] = response_data["responseDescription"]
                return JsonResponse(data=response_data, status=status.HTTP_404_NOT_FOUND)

            account_payment = autodebet_bni_transaction.account_payment
            account = account_payment.account
            amount = autodebet_bni_transaction.amount
            transaction_date = timezone.localtime(timezone.now())
            vendor = AutodebetVendorConst.BNI
            self.kwargs['account_id'] = account.id
            self.kwargs['account_payment_id'] = autodebet_bni_transaction.account_payment_id
            existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)

            if (
                data['latestTransactionStatus'].lower()
                == AutodebetBNILatestTransactionStatusConst.FAILED
            ):
                status_desc = response_data["responseDescription"]
                response_code = data.get('additionalInfo', {}).get('responseCode', None)
                if response_code == AutodebetBNIResponseCodeConst.FAILED_INSUFFICIENT_FUND_CALLBACK:
                    status_desc = BNIErrorCode.INSUFFICIENT_FUND
                self.kwargs['is_send_slack_alert'] = True
                send_event_autodebit_failed_deduction_task.delay(
                    account_payment.id, account.customer.id, vendor
                )
                self.kwargs['slack_error_message'] = data['transactionStatusDesc']
                autodebet_bni_transaction.update_safely(
                    status=AutodebetBNILatestTransactionStatusConst.FAILED,
                    status_desc=status_desc,
                )
                if response_code == AutodebetBNIResponseCodeConst.FAILED_INSUFFICIENT_FUND_CALLBACK:
                    autodebet_account = (
                        autodebet_bni_transaction.autodebet_bni_account.autodebet_account
                    )
                    suspend_autodebet_insufficient_balance(autodebet_account, VendorConst.BNI)
                return JsonResponse(data=response_data, status=status.HTTP_200_OK)

            with transaction.atomic():
                payback_transaction = PaybackTransaction.objects.create(
                    is_processed=False,
                    customer=account.customer,
                    payback_service='autodebet',
                    status_desc='Autodebet {}'.format(vendor),
                    transaction_id=x_external_id,
                    transaction_date=transaction_date,
                    amount=amount,
                    account=account,
                    payment_method=get_autodebet_payment_method(
                        account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
                    ),
                )
                j1_refinancing_activation(
                    payback_transaction, account_payment, payback_transaction.transaction_date
                )
                process_j1_waiver_before_payment(
                    account_payment, amount, payback_transaction.transaction_date
                )
                account_trx = process_repayment_trx(
                    payback_transaction,
                    note='payment with autodebet {} amount {}'.format(vendor, amount),
                )
                execute_after_transaction_safely(
                    lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
                )

                if account_trx:
                    autodebet_bni_transaction.update_safely(
                        status=AutodebetBNILatestTransactionStatusConst.SUCCESS,
                    )

                    if existing_benefit:
                        if is_eligible_to_get_benefit(account) and is_fully_paid_or_limit(
                            account_payment, account, AutodebetVendorConst.BNI
                        ):
                            give_benefit(existing_benefit, account, account_payment)

            return JsonResponse(data=response_data, status=status.HTTP_200_OK)

        except Exception as e:
            response_data[
                "responseCode"
            ] = BNIPurchaseCallbackResponseCodeMessageDescription.INTERNAL_SERVER_ERROR.code
            response_data[
                "responseMessage"
            ] = BNIPurchaseCallbackResponseCodeMessageDescription.INTERNAL_SERVER_ERROR.message
            response_data[
                "responseDescription"
            ] = BNIPurchaseCallbackResponseCodeMessageDescription.INTERNAL_SERVER_ERROR.description
            sentry_client.captureException()
            self.kwargs['slack_error_message'] = str(e)
            return JsonResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)


class BNIReactivateView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, AutodebetVendorConst.BNI
        )

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, AutodebetVendorConst.BNI
        )


class BNIAccessTokenView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        data_to_log = {
            "action": "BNIAccessTokenView",
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }

        store_autodebet_api_log.delay(
            request_body,
            response.content,
            response.status_code,
            '[POST] {}'.format(request.get_full_path()),
            VendorConst.BNI,
            error_message=self.kwargs.get('error_message'),
        )
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)
        return

    def post(self, request):
        redis_client = get_redis_client()
        now = timezone.localtime(datetime.now())
        response_data = {
            "tokenType": "BearerToken",
            "responseTime": now.strftime("%Y%m%d%H%M%S"),
            "clientId": settings.AUTODEBET_BNI_AYO_CONNECT_CLIENT_ID,
            "accessToken": "",
            "expiresIn": "",
        }

        error_response = {
            "code": 400,
            "message": "",
            "responseTime": now.strftime("%Y%m%d%H%M%S"),
            "errors": {"code": 400, "message": "", "details": ""},
        }

        try:
            params = request.GET.dict()
            data = {**params, **request.data}
            serializer = BNIAccessTokenSerializer(data=data)

            if not serializer.is_valid():
                field, error = list(serializer.errors.items())[0]
                error_response[
                    "code"
                ] = BNIAyoConnectAccessTokenCodeMessageDescription.INVALID_FIELD.code
                error_response["message"] = "Invalid field {}".format(field)
                error_response["errors"]["message"] = "Invalid field {}".format(field)
                error_response["errors"]["details"] = "{} {}".format(field, error[0])
                self.kwargs['error_message'] = error_response["errors"]["details"]
                return JsonResponse(data=error_response, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data

            if data['client_id'] == settings.AUTODEBET_BNI_AYO_CONNECT_CLIENT_ID:
                if data['client_secret'] == settings.AUTODEBET_BNI_AYO_CONNECT_CLIENT_SECRET:
                    token = bni_generate_access_token()
                    redis_client.set(
                        RedisKey.BNI_AYOCONNECT_TOKEN + token, token, timedelta(seconds=3600)
                    )

                    response_data['accessToken'] = token
                    response_data['expiresIn'] = redis_client.get_ttl(
                        RedisKey.BNI_AYOCONNECT_TOKEN + token
                    )
                    return JsonResponse(data=response_data, status=status.HTTP_200_OK)

            error_response[
                'code'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.UNAUTHORIZED.code
            error_response[
                'message'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.UNAUTHORIZED.message
            error_response['errors'][
                'code'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.UNAUTHORIZED.code
            error_response['errors'][
                'message'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.UNAUTHORIZED.message
            error_response['errors'][
                'details'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.UNAUTHORIZED.description
            return JsonResponse(data=error_response, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            error_response[
                'code'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.INTERNAL_SERVER_ERROR.code
            error_response[
                'message'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.INTERNAL_SERVER_ERROR.message
            error_response['errors'][
                'code'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.INTERNAL_SERVER_ERROR.code
            error_response['errors'][
                'message'
            ] = BNIAyoConnectAccessTokenCodeMessageDescription.INTERNAL_SERVER_ERROR.description
            self.kwargs['slack_error_message'] = str(e)
            return JsonResponse(data=error_response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

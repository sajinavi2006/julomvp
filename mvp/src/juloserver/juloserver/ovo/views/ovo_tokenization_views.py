import json

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status

from juloserver.account.models import Account
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    VendorConst,
)
from juloserver.autodebet.models import AutodebetOvoTransaction
from juloserver.autodebet.services.task_services import get_autodebet_payment_method
from juloserver.julo.models import PaymentMethod, PaybackTransaction
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
)
from juloserver.ovo.serializers import (
    OvoTokenizationBindingSerializer,
    OvoBindingNotificationSerializer,
    OvoTokenizationBindingStatusSerializer,
    OvoTokenizationPaymentSerializer,
    OvoTokenizationPaymentNotificationSerializer,
)
from juloserver.ovo.services.ovo_tokenization_services import (
    request_webview_url,
    activate_ovo_wallet_account,
    ovo_unbinding,
    process_ovo_repayment,
)
from django.conf import settings
from juloserver.ovo.constants import (
    OvoWalletRequestBindingResponseCodeAndMessage,
    OvoBindingResponseCodeAndMessage,
    OvoWalletAccountStatusConst,
    OvoStatus,
    OvoPaymentErrorResponseCodeAndMessage,
    OvoPaymentNotificationResponseCodeAndMessage,
    OvoPaymentType,
)
from django.http.response import JsonResponse
from juloserver.integapiv1.services import (
    get_snap_expiry_token,
    is_expired_snap_token,
    authenticate_snap_request,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.ovo.models import OvoWalletAccount, OvoWalletTransaction
from typing import Any
from django.db import transaction
from juloserver.ovo.services.ovo_tokenization_services import (
    get_ovo_wallet_account,
    get_ovo_wallet_balance,
    get_ovo_tokenization_onboarding_data,
    payment_request,
)
import logging
from juloserver.integapiv1.constants import (
    SnapVendorChoices,
    EXPIRY_TIME_TOKEN_DOKU_SNAP,
)
from juloserver.autodebet.tasks import store_autodebet_api_log

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class OvoTokenizationOnboardingView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        response, error = get_ovo_tokenization_onboarding_data()

        if error:
            return general_error_response(error)

        return success_response(response)


class OvoTokenizationBinding(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        user = self.request.user
        if not hasattr(user, 'customer'):
            return general_error_response('Invalid user')

        account = user.customer.account
        if not account:
            return general_error_response('Account not found')

        serializer = OvoTokenizationBindingSerializer(data=request.data)
        status_code = OvoWalletRequestBindingResponseCodeAndMessage.PHONE_NUMBER_REQUIRED.code
        if not serializer.is_valid():
            errors = serializer.errors
            error_messages = [
                "{} {}".format(key, ', '.join(value)) for key, value in errors.items()
            ]

            return general_error_response(
                error_messages[0],
                {
                    'status_code': status_code,
                    'status_message': error_messages[0],
                },
            )

        data = serializer.validated_data
        response, error = request_webview_url(account, data['phone_number'])
        if error:
            return general_error_response(
                error.message, {'status_code': error.code, 'status_message': error.message}
            )

        return success_response(response)


class OvoTokenizationException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class OvoCallbackView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from juloserver.autodebet.tasks import (
            send_slack_alert_ovo_failed_subscription_and_deduction_linking,
        )
        from rest_framework.status import HTTP_200_OK
        raw_body = request.body

        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        if response.status_code != HTTP_200_OK:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=self.kwargs.get('error_message'),
                topic=request.get_full_path(),
                account_id=self.kwargs.get('account_id'),
                account_payment_id=self.kwargs.get('account_payment_id'),
                is_autodebet=self.kwargs.get('is_autodebet'),
            )

        if hasattr(response, 'render'):
            response.render()

        if hasattr(response, 'content'):
            redis_client = get_redis_client()
            response_data = json.loads(response.content)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
            key = '{}_snap:external_id:{}'.format(SnapVendorChoices.DOKU, external_id)
            external_id_redis = redis_client.get(key)
            if external_id and not external_id_redis:
                today_datetime = timezone.localtime(timezone.now())
                tomorrow_datetime = today_datetime + relativedelta(
                    days=1, hour=0, minute=0, second=0
                )
                redis_client.set(key, json.dumps(response_data), tomorrow_datetime - today_datetime)

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        headers = {'HTTP_AUTHORIZATION': request.META.get('HTTP_AUTHORIZATION', None)}
        data_to_log = {
            "action": self.view_name,
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }

        is_autodebet = self.kwargs.get('is_autodebet')
        if is_autodebet:
            store_autodebet_api_log.delay(
                request_body,
                response.content,
                response.status_code,
                '[POST] {}'.format(request.get_full_path()),
                VendorConst.OVO,
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


class OvoBindingNotificationView(OvoCallbackView):
    view_name = "OvoBindingNotificationView"

    def post(self, request):
        response_data = {
            "responseCode": OvoBindingResponseCodeAndMessage.SUCCESSFUL.code,
            "responseMessage": OvoBindingResponseCodeAndMessage.SUCCESSFUL.message,
        }

        try:
            # authorization
            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.DOKU)

            if not snap_expiry_token or is_expired_snap_token(
                snap_expiry_token, EXPIRY_TIME_TOKEN_DOKU_SNAP
            ):
                response_data = {
                    'responseCode': OvoBindingResponseCodeAndMessage.INVALID_TOKEN.code,
                    'responseMessage': OvoBindingResponseCodeAndMessage.INVALID_TOKEN.message,
                }
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_data)

            data = request.data
            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
            }
            request_header_map = {
                "x_timestamp": 'HTTP_X_TIMESTAMP',
                "x_signature": 'HTTP_X_SIGNATURE',
            }
            for key, header_name in request_header_map.items():
                headers[key] = request.META.get(header_name)

            is_authenticated = authenticate_snap_request(
                headers,
                data,
                request.method,
                settings.DOKU_SNAP_CLIENT_SECRET_INBOUND,
                relative_url,
            )
            if not is_authenticated:
                response_data = {
                    'responseCode': (OvoBindingResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code),
                    'responseMessage': (
                        OvoBindingResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                }
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = OvoBindingNotificationSerializer(data=request.data)
            if not serializer.is_valid():
                field, error = list(serializer.errors.items())[0]
                response_data[
                    "responseCode"
                ] = OvoBindingResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                response_data["responseMessage"] = "Invalid field {}".format(field)
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(data=response_data, status=status.HTTP_400_BAD_REQUEST)
            data = serializer.validated_data

            auth_code = data["additionalInfo"]["authCode"]
            customer_xid = data["additionalInfo"]["custIdMerchant"]

            ovo_wallet = get_ovo_wallet_account(auth_code, customer_xid)

            if not ovo_wallet:
                response_data["responseCode"] = OvoBindingResponseCodeAndMessage.NOT_FOUND.code
                response_data[
                    "responseMessage"
                ] = OvoBindingResponseCodeAndMessage.NOT_FOUND.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(data=response_data, status=status.HTTP_404_NOT_FOUND)
            self.kwargs["account_id"] = ovo_wallet.account_id

            if ovo_wallet.status == OvoWalletAccountStatusConst.ENABLED:
                return JsonResponse(status=status.HTTP_200_OK, data=response_data)

            with transaction.atomic(using='repayment_db'):
                if data["additionalInfo"]["status"] == OvoStatus.PENDING:
                    return JsonResponse(status=status.HTTP_200_OK, data=response_data)

                elif data["additionalInfo"]["status"] == OvoStatus.FAILED:
                    ovo_wallet.status = OvoWalletAccountStatusConst.FAILED
                    ovo_wallet.save()
                    return JsonResponse(status=status.HTTP_200_OK, data=response_data)

                elif data["additionalInfo"]["status"] == OvoStatus.SUCCESS:

                    ovo_wallet, error_message = activate_ovo_wallet_account(ovo_wallet)

                    if error_message:
                        raise OvoTokenizationException(error_message)

                    return JsonResponse(status=status.HTTP_200_OK, data=response_data)

            response_data["responseCode"] = OvoBindingResponseCodeAndMessage.BAD_REQUEST.code
            response_data["responseMessage"] = OvoBindingResponseCodeAndMessage.BAD_REQUEST.message
            self.kwargs["error_message"] = response_data["responseMessage"]
            return JsonResponse(data=response_data, status=status.HTTP_400_BAD_REQUEST)

        except Exception:
            response_data["responseCode"] = OvoBindingResponseCodeAndMessage.GENERAL_ERROR.code
            response_data[
                "responseMessage"
            ] = OvoBindingResponseCodeAndMessage.GENERAL_ERROR.message
            sentry_client.captureException()
            self.kwargs["error_message"] = response_data["responseMessage"]
            return JsonResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)


class OvoGetLinkingStatus(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        account = customer.account

        ovo_wallet = OvoWalletAccount.objects.filter(
            account_id=account.id,
        ).last()

        if ovo_wallet:
            return_response = {
                "account_status": ovo_wallet.status,
            }
            if ovo_wallet.status == OvoWalletAccountStatusConst.ENABLED:
                # get balance
                balance, error_message = get_ovo_wallet_balance(ovo_wallet)

                # CHECK IF ALREADY DISABLED FROM UNLINKED OVO APP
                ovo_wallet.refresh_from_db()
                if ovo_wallet.status == OvoWalletAccountStatusConst.DISABLED:
                    return_response = {
                        "account_status": ovo_wallet.status,
                    }
                    return success_response(return_response)

                if error_message:
                    return general_error_response(error_message)

                return_response["balance"] = balance

            return success_response(return_response)
        return not_found_response("Ovo wallet is not found")


class OvoTokenizationBindingStatus(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = OvoTokenizationBindingStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer = request.user.customer
        account = customer.account
        ovo_wallet = OvoWalletAccount.objects.filter(
            account_id=account.id,
        ).last()

        if not ovo_wallet:
            return not_found_response("Ovo wallet is not found")

        if data["status"] == OvoStatus.SUCCESS:
            if ovo_wallet.status != OvoWalletAccountStatusConst.ENABLED:
                ovo_wallet, error_message = activate_ovo_wallet_account(ovo_wallet)
                if error_message:
                    return general_error_response(error_message)

        elif data["status"] == OvoStatus.FAILED:
            ovo_wallet.status = OvoWalletAccountStatusConst.FAILED
            ovo_wallet.save()

        return success_response()


class OvoTokenizationPayment(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = OvoTokenizationPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer = request.user.customer
        account = customer.account
        amount = data["amount"]

        ovo_wallet = OvoWalletAccount.objects.filter(
            account_id=account.id,
            status=OvoWalletAccountStatusConst.ENABLED,
        ).last()

        if not ovo_wallet:
            return general_error_response(
                OvoPaymentErrorResponseCodeAndMessage.NOT_FOUND.message,
                data={
                    "status_code": OvoPaymentErrorResponseCodeAndMessage.NOT_FOUND.code,
                    "status_message": OvoPaymentErrorResponseCodeAndMessage.NOT_FOUND.message,
                },
            )

        response_data, error_response = payment_request(account, ovo_wallet, amount)
        if error_response:
            return general_error_response(
                error_response.message,
                data={"status_code": error_response.code, "status_message": error_response.message},
            )

        return success_response(response_data)


class OvoTokenizationUnbinding(StandardizedExceptionHandlerMixin, APIView):
    def delete(self, request):
        customer = request.user.customer
        account = customer.account

        response, error = ovo_unbinding(account)

        if error:
            return general_error_response(error)

        return success_response(response)


class OvoTokenizationPaymentNotification(OvoCallbackView):
    def post(self, request):
        self.view_name = 'OvoTokenizationPaymentNotification'
        response_data = {
            "responseCode": OvoPaymentNotificationResponseCodeAndMessage.SUCCESSFUL.code,
            "responseMessage": OvoPaymentNotificationResponseCodeAndMessage.SUCCESSFUL.message,
        }

        try:
            data = request.data
            if data.get('additionalInfo', {}).get('paymentType') == OvoPaymentType.RECURRING:
                self.kwargs["is_autodebet"] = True

            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.DOKU)
            if not snap_expiry_token or is_expired_snap_token(
                snap_expiry_token, EXPIRY_TIME_TOKEN_DOKU_SNAP
            ):
                response_data = {
                    'responseCode': OvoPaymentNotificationResponseCodeAndMessage.INVALID_TOKEN.code,
                    # fmt: off
                    'responseMessage':
                        OvoPaymentNotificationResponseCodeAndMessage.INVALID_TOKEN.message,
                    # fmt: on
                }
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_data)

            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
            }
            request_header_map = {
                "x_timestamp": 'HTTP_X_TIMESTAMP',
                "x_signature": 'HTTP_X_SIGNATURE',
            }
            for key, header_name in request_header_map.items():
                headers[key] = request.META.get(header_name)

            is_authenticated = authenticate_snap_request(
                headers,
                data,
                request.method,
                settings.DOKU_SNAP_CLIENT_SECRET_INBOUND,
                relative_url,
            )

            if not is_authenticated:
                response_data = {
                    # fmt: off
                    'responseCode':
                        OvoPaymentNotificationResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
                    'responseMessage':
                        OvoPaymentNotificationResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message,
                    # fmt: on
                }
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = OvoTokenizationPaymentNotificationSerializer(data=data)

            if not serializer.is_valid():
                field, error = list(serializer.errors.items())[0]
                response_data[
                    "responseCode"
                ] = OvoPaymentNotificationResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                response_data["responseMessage"] = "Invalid field {}".format(field)
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(data=response_data, status=status.HTTP_400_BAD_REQUEST)

            data = serializer.validated_data

            access_token_b2b2c = request.META.get('HTTP_AUTHORIZATION_CUSTOMER', '').split(' ')[-1]
            ovo_wallet = OvoWalletAccount.objects.filter(
                access_token=access_token_b2b2c, status=OvoWalletAccountStatusConst.ENABLED
            ).last()

            if not ovo_wallet:
                response_data[
                    "responseCode"
                ] = OvoPaymentNotificationResponseCodeAndMessage.INVALID_CUSTOMER_TOKEN.code
                response_data[
                    "responseMessage"
                ] = OvoPaymentNotificationResponseCodeAndMessage.INVALID_CUSTOMER_TOKEN.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(data=response_data, status=status.HTTP_401_UNAUTHORIZED)

            external_id = request.META.get('HTTP_X_EXTERNAL_ID')

            if not external_id:
                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                response_data['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    OvoPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_400_BAD_REQUEST, data=response_data)

            key = '{}:external_id:{}'.format(SnapVendorChoices.DOKU, external_id)
            redis_client = get_redis_client()
            raw_value = redis_client.get(key)

            if raw_value:
                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                response_data[
                    'responseMessage'
                ] = OvoPaymentNotificationResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(data=response_data, status=status.HTTP_409_CONFLICT)

            ovo_transaction = OvoWalletTransaction.objects.filter(
                partner_reference_no=data['originalPartnerReferenceNo'],
                ovo_wallet_account=ovo_wallet,
            ).last()

            if data['additionalInfo']['paymentType'] == OvoPaymentType.RECURRING:
                self.kwargs["is_autodebet"] = True
                ovo_transaction = AutodebetOvoTransaction.objects.filter(
                    original_partner_reference_no=data['originalPartnerReferenceNo'],
                    ovo_wallet_account=ovo_wallet,
                ).last()

            if not ovo_transaction:
                # PREVENT NOT FOUND ERROR ON FAILED TRANSACTION EDGE CASE
                if data.get('latestTransactionStatus') == '06':
                    return JsonResponse(status=status.HTTP_200_OK, data=response_data)

                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_data)

            account = Account.objects.get_or_none(pk=ovo_wallet.account_id)

            if not account:
                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.message
                return JsonResponse(data=response_data, status=status.HTTP_404_NOT_FOUND)

            ovo_payment_method = PaymentMethod.objects.filter(
                customer=account.customer, payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
            ).last()

            if data['additionalInfo']['paymentType'] == OvoPaymentType.RECURRING:
                ovo_payment_method = get_autodebet_payment_method(
                    account,
                    AutodebetVendorConst.OVO,
                    AutodebetVendorConst.PAYMENT_METHOD[AutodebetVendorConst.OVO],
                )

            if not ovo_payment_method:
                response_data[
                    "responseCode"
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.code
                response_data[
                    "responseMessage"
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(data=response_data, status=status.HTTP_404_NOT_FOUND)
            self.kwargs["account_id"] = account.id
            account_payment = account.get_oldest_unpaid_account_payment()
            if not account_payment:
                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_data)

            payback_transaction = PaybackTransaction.objects.filter(
                payment_method=ovo_payment_method,
                transaction_id=data['originalPartnerReferenceNo'],
            ).last()

            if not payback_transaction:
                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = OvoPaymentNotificationResponseCodeAndMessage.NOT_FOUND.message
                self.kwargs["error_message"] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_data)
            elif payback_transaction.is_processed:
                response_data[
                    'responseCode'
                ] = OvoPaymentNotificationResponseCodeAndMessage.PAID_BILL.code
                response_data[
                    'responseMessage'
                ] = OvoPaymentNotificationResponseCodeAndMessage.PAID_BILL.message
                return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_data)

            with transaction.atomic():
                transaction_date = timezone.localtime(timezone.now())
                process_ovo_repayment(
                    payback_transaction.id,
                    transaction_date,
                    int(float(data['amount']['value'])),
                    data.get('originalReferenceNo'),
                    data['latestTransactionStatus'],
                    data['transactionStatusDesc'].upper(),
                    ovo_transaction,
                    data['additionalInfo']['paymentType'],
                    account,
                )

                return JsonResponse(status=status.HTTP_200_OK, data=response_data)
        except Exception as e:  # noqa
            sentry_client.captureException()
            response_data[
                'responseCode'
            ] = OvoPaymentNotificationResponseCodeAndMessage.GENERAL_ERROR.code
            response_data[
                'responseMessage'
            ] = OvoPaymentNotificationResponseCodeAndMessage.GENERAL_ERROR.message
            self.kwargs["error_message"] = response_data["responseMessage"]
            return JsonResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)

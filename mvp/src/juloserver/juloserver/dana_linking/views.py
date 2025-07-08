from rest_framework.views import APIView
from datetime import datetime
import logging
from typing import Any
import json
from django.utils import timezone
from django.http import (
    JsonResponse,
)
from django.template.response import ContentNotRenderedError
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from django.db import transaction

from juloserver.dana_linking.services import get_dana_onboarding_data
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    not_found_response,
    internal_server_error_response,
)
from juloserver.dana_linking.models import (
    DanaWalletAccount,
    DanaWalletTransaction,
)

from juloserver.dana_linking import get_dana_linking_client
from juloserver.dana_linking.utils import (
    is_customer_exists,
    generate_string_to_sign_asymmetric,
)
from juloserver.dana_linking.constants import (
    GRANT_TYPE,
    DanaWalletAccountStatusConst,
    ErrorMessage,
    DanaPaymentNotificationResponseCodeAndMessage,
    DanaUnbindNotificationResponseCode,
    ErrorDetail,
    FeatureNameConst,
)
from juloserver.dana_linking.serializers import (
    DanaApplyTokenSerializer,
    DanaPaymentNotificationSerializer,
    DanaPaymentSerializer,
    DanaUnlinkNotificationSerializer,
)
from juloserver.dana_linking.tasks import (
    send_slack_notification,
    store_repayment_api_log,
)
from juloserver.dana_linking.services import (
    get_access_token,
    get_dana_balance_amount,
    create_dana_payment_method,
    unbind_dana_account_linking,
    process_dana_repayment,
    create_debit_payment,
    fetch_dana_other_page_details,
)

from juloserver.integapiv1.utils import verify_asymmetric_signature

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.payback.services.dana_biller import (
    generate_signature,
)
from juloserver.julo.models import FeatureSetting
import copy

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


class DanaOnboardingPageView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        response, error = get_dana_onboarding_data()

        if error:
            return general_error_response(error)

        return success_response(response)


class DanaLinkingView(StandardizedExceptionHandlerMixinV2, APIView):
    @is_customer_exists
    def get(self, request):
        customer = request.user.customer
        account = customer.account
        dana_wallet_account = DanaWalletAccount.objects.filter(
            account=account,
            status=DanaWalletAccountStatusConst.ENABLED,
        ).exists()
        if dana_wallet_account:
            return general_error_response("Akun dana sudah terhubung")
        customer_xid = customer.customer_xid
        if not customer_xid:
            customer_xid = customer.generated_customer_xid
        dana_linking_client = get_dana_linking_client(account=account)
        dana_binding_url = dana_linking_client.construct_oauth_url(customer_xid)
        DanaWalletAccount.objects.get_or_create(
            account=account,
            status=DanaWalletAccountStatusConst.PENDING,
        )
        return success_response({"web_linking": dana_binding_url})


class DanaFinalizeLinkingView(StandardizedExceptionHandlerMixinV2, APIView):
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if response.status_code != 200:
            account = self.kwargs.get("account")
            account_id = None
            application_id = None
            if account:
                account_id = account.id
                application_id = account.last_application.id
            send_slack_notification.delay(
                account_id,
                application_id,
                self.kwargs.get("error_message"),
                request.get_full_path(),
            )
        return response

    @is_customer_exists
    def post(self, request):
        try:
            customer = request.user.customer
            account = customer.account
            self.kwargs["account"] = account
            serializer = DanaApplyTokenSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            dana_wallet_account = DanaWalletAccount.objects.filter(
                account=account,
                status=DanaWalletAccountStatusConst.PENDING,
            ).last()
            if not dana_wallet_account:
                self.kwargs["error_message"] = ErrorMessage.DANA_NOT_FOUND
                return not_found_response(ErrorMessage.DANA_NOT_FOUND)
            dana_linking_client = get_dana_linking_client(account=account)
            response_data, error_message = dana_linking_client.apply_token(
                GRANT_TYPE["activation"], serializer.validated_data["auth_code"]
            )
            if error_message:
                self.kwargs["error_message"] = error_message
                return general_error_response(ErrorMessage.GENERAL_ERROR)

            public_user_id = (
                response_data.get("additionalInfo", {})
                .get("userInfo", {})
                .get("publicUserId")
            )
            if not public_user_id:
                self.kwargs["error_message"] = ErrorMessage.PUBLIC_USER_ID_NULL
                return general_error_response(ErrorMessage.PUBLIC_USER_ID_NULL)

            try:
                access_token_expiry_time = datetime.strptime(
                    response_data.get("accessTokenExpiryTime"), "%Y-%m-%dT%H:%M:%S%z"
                )
                refresh_token_expiry_time = datetime.strptime(
                    response_data.get("refreshTokenExpiryTime"), "%Y-%m-%dT%H:%M:%S%z"
                )
            except (TypeError, ValueError) as e:
                self.kwargs["error_message"] = str(e)
                return general_error_response(ErrorMessage.GENERAL_ERROR)
            with transaction.atomic():
                create_dana_payment_method(customer)
                dana_wallet_account.update_safely(
                    status=DanaWalletAccountStatusConst.ENABLED,
                    access_token=response_data.get("accessToken"),
                    access_token_expiry_time=access_token_expiry_time,
                    refresh_token=response_data.get("refreshToken"),
                    refresh_token_expiry_time=refresh_token_expiry_time,
                    public_user_id=public_user_id,
                )
            return success_response({"message": "success binding"})
        except Exception as e:
            self.kwargs["error_message"] = str(e)
            return internal_server_error_response(ErrorMessage.GENERAL_ERROR)


class DanaAccountStatusView(StandardizedExceptionHandlerMixinV2, APIView):
    @is_customer_exists
    def get(self, request):
        customer = request.user.customer
        account = customer.account
        dana_wallet_account = DanaWalletAccount.objects.filter(
            account=account,
        ).last()
        if not dana_wallet_account:
            return success_response(
                {
                    "account_status": DanaWalletAccountStatusConst.DISABLED,
                    "balance": None,
                }
            )
        balance_amount = None
        if dana_wallet_account.status == DanaWalletAccountStatusConst.ENABLED:
            customer_xid = customer.customer_xid
            if not customer_xid:
                customer_xid = customer.generated_customer_xid
            device = customer.device_set.last()
            access_token = get_access_token(dana_wallet_account)
            if access_token:
                balance_amount = get_dana_balance_amount(
                    dana_wallet_account,
                    device.android_id,
                    customer_xid,
                    account=account,
                )
                if (
                    isinstance(balance_amount, int)
                    and balance_amount != dana_wallet_account.balance
                ):
                    dana_wallet_account.update_safely(balance=balance_amount)
        data = {
            "account_status": dana_wallet_account.status,
            "balance": balance_amount,
        }
        return success_response(data)


class DanaAccountUnbindingView(StandardizedExceptionHandlerMixin, APIView):
    @is_customer_exists
    def post(self, request):
        account = request.user.customer.account
        response, error = unbind_dana_account_linking(account)

        if error:
            return general_error_response(error)

        return success_response(response)


class DanaPaymentView(StandardizedExceptionHandlerMixin, APIView):
    @is_customer_exists
    def post(self, request):
        self._pre_log_request(request)
        customer = request.user.customer
        account = customer.account
        serializer = DanaPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dana_wallet_account = DanaWalletAccount.objects.filter(
            account=account,
            status=DanaWalletAccountStatusConst.ENABLED,
        ).last()
        if not dana_wallet_account:
            return general_error_response(ErrorMessage.DANA_NOT_FOUND)
        customer_xid = customer.customer_xid
        if not customer_xid:
            customer_xid = customer.generated_customer_xid
        account_payment = account.get_oldest_unpaid_account_payment()
        if not account_payment:
            return general_error_response(ErrorMessage.BILL_NOT_FOUND)
        amount = serializer.validated_data.get("amount")
        device = customer.device_set.only("id", "android_id").last()
        web_redirect_url = create_debit_payment(
            customer_xid,
            amount,
            account_payment,
            dana_wallet_account,
            device.android_id,
            customer,
        )
        if not web_redirect_url:
            return general_error_response(ErrorMessage.GENERAL_ERROR)
        data = {"message": "Successful", "webRedirectUrl": web_redirect_url}
        return success_response(data)

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "DanaPaymentView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "customer_id": request.user.customer.id,
            }
        )


class BaseDanaInboundView(APIView):
    permission_classes = (AllowAny,)

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        headers = {
            "HTTP_X_TIMESTAMP": request.META.get("HTTP_X_TIMESTAMP", None),
            "HTTP_X_SIGNATURE": request.META.get("HTTP_X_SIGNATURE", None),
            "HTTP_X_PARTNER_ID": request.META.get("HTTP_X_PARTNER_ID", None),
            "HTTP_X_EXTERNAL_ID": request.META.get("HTTP_X_EXTERNAL_ID", None),
        }
        data_to_log = {
            "action": "dana_linking_inbound_api",
            "headers": headers,
            "request_body": request_body.decode("utf-8"),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        error_message = None
        try:
            response_data = json.loads(response.content)
        except ContentNotRenderedError:
            response_data = response.data
        if response.status_code != status.HTTP_200_OK and response_data.get(
            "responseMessage"
        ):
            error_message = response_data.get("responseMessage")
        store_repayment_api_log.delay(
            "[POST] {}".format(request.get_full_path()),
            response.status_code,
            "DANA",
            error_message,
            self.kwargs.get("application_id"),
            self.kwargs.get("account_id"),
            response_data,
            self.kwargs.get("account_payment_id"),
            request_body,
        )
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)
        return


class DanaPaymentNotificationView(BaseDanaInboundView):
    def post(self, request):
        self._pre_log_request(request)
        relative_url = request.get_full_path()
        skip_process = False
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SKIP_PROCESS_AUTH, is_active=True
        ).exists()
        if settings.ENVIRONMENT != "prod" and feature_setting:
            skip_process = True

        data = request.data
        method = request.method
        x_signature = request.META.get("HTTP_X_SIGNATURE")
        timestamp = request.META.get("HTTP_X_TIMESTAMP")
        string_to_sign = generate_string_to_sign_asymmetric(
            timestamp, data, method, relative_url
        )
        is_verify_signature = verify_asymmetric_signature(
            settings.DANA_LINKING_PUBLIC_KEY, x_signature, string_to_sign
        )
        is_verify_signature = skip_process if skip_process else is_verify_signature
        if not is_verify_signature:
            response_message = (
                DanaPaymentNotificationResponseCodeAndMessage.UNAUTHORIZED.message
            )
            response_data = {
                "responseCode": DanaPaymentNotificationResponseCodeAndMessage.UNAUTHORIZED.code,
                "responseMessage": response_message + " [invalid signature]",
            }

            return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_data)

        serializer = DanaPaymentNotificationSerializer(data=request.data)
        if not serializer.is_valid():
            errors = list(serializer.errors.items())[0][1][0]
            response_message = (
                DanaPaymentNotificationResponseCodeAndMessage.INVALID_FIELD_FORMAT.message
            )
            response_code = (
                DanaPaymentNotificationResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
            )
            if errors in ErrorDetail.mandatory_field_errors():
                response_code = (
                    DanaPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                )
                response_message = (
                    DanaPaymentNotificationResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
            response_data = {
                "responseCode": response_code,
                "responseMessage": response_message,
            }
            return JsonResponse(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        partner_reference_no = data.get("originalPartnerReferenceNo", "")
        dana_wallet_transaction = (
            DanaWalletTransaction.objects.select_related("payback_transaction")
            .filter(partner_reference_no=partner_reference_no)
            .last()
        )

        if not dana_wallet_transaction:
            response_data = {
                "responseCode": (
                    DanaPaymentNotificationResponseCodeAndMessage.TRANSACTION_NOT_FOUND.code
                ),
                "responseMessage": (
                    DanaPaymentNotificationResponseCodeAndMessage.TRANSACTION_NOT_FOUND.message
                ),
            }
            return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_data)
        dana_wallet_transaction.update_safely(
            transaction_status_code=data.get("latestTransactionStatus"),
            transaction_status_description=data.get("transactionStatusDesc"),
        )
        account = dana_wallet_transaction.dana_wallet_account.account
        application = account.last_application
        account_payment = account.get_oldest_unpaid_account_payment()
        self.kwargs["account_id"] = account.id
        self.kwargs["account_payment_id"] = (
            account_payment.id if account_payment else None
        )
        self.kwargs["application_id"] = application.id

        if data.get("latestTransactionStatus") != "00":
            send_slack_notification.delay(
                account.id,
                application.id,
                data.get("transactionStatusDesc"),
                request.get_full_path(),
            )

        if dana_wallet_transaction.payback_transaction.is_processed:
            response_data = {
                "responseCode": DanaPaymentNotificationResponseCodeAndMessage.SUCCESS.code,
                "responseMessage": DanaPaymentNotificationResponseCodeAndMessage.SUCCESS.message,
            }

            return JsonResponse(status=status.HTTP_200_OK, data=response_data)

        http_status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        response_message = (
            DanaPaymentNotificationResponseCodeAndMessage.INTERNAL_SERVER.message
        )
        response_code = (
            DanaPaymentNotificationResponseCodeAndMessage.INTERNAL_SERVER.code
        )
        try:
            data_process_payment = {
                "amount": data["amount"]["value"],
                "transaction_time": data["finishedTime"],
            }
            if data.get("latestTransactionStatus") == "00":
                process_dana_repayment(
                    dana_wallet_transaction.payback_transaction.id, data_process_payment
                )
            response_message = (
                DanaPaymentNotificationResponseCodeAndMessage.SUCCESS.message
            )
            response_code = DanaPaymentNotificationResponseCodeAndMessage.SUCCESS.code
            http_status_code = status.HTTP_200_OK
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
        response_data = {
            "responseCode": response_code,
            "responseMessage": response_message,
        }
        return JsonResponse(status=http_status_code, data=response_data)

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "DanaPaymentNotificationView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "trx_id": request.data.get("originalPartnerReferenceNo", ""),
            }
        )


class DanaAccountOtherPageDetailsView(StandardizedExceptionHandlerMixin, APIView):
    @is_customer_exists
    def get(self, request):
        account = request.user.customer.account
        response, error = fetch_dana_other_page_details(account)

        if error:
            return general_error_response(error)

        return success_response(response)


class DanaUnbindNotificationView(BaseDanaInboundView):
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        try:
            data = json.loads(response.content)
            signature = generate_signature(
                data.get("response"), settings.DANA_LINKING_PRIVATE_KEY
            )
            data["signature"] = signature

            return JsonResponse(
                data,
                status=response.status_code,
                json_dumps_params={"separators": (",", ":")},
            )
        except Exception:
            julo_sentry_client.captureException()
            return response

    def post(self, request):
        from juloserver.autodebet.constants import (
            AutodebetVendorConst,
            AutodebetStatuses,
        )
        from juloserver.autodebet.models import AutodebetAccount
        from juloserver.account.models import Account
        from juloserver.payback.services.dana_biller import verify_signature

        data = json.loads(request.body)
        response_body = {
            "response": copy.deepcopy(data.get("request")),
            "signature": data.get("signature"),
        }
        del response_body["response"]["head"]["reqTime"]
        resp_time = timezone.localtime(timezone.now()).replace(microsecond=0).isoformat()
        response_body["response"]["head"]["respTime"] = resp_time
        if not verify_signature(data, settings.DANA_LINKING_PUBLIC_KEY):
            response_body["response"]["body"] = {
                "resultInfo": {
                    "resultStatus": "F",
                    "resultCodeId": DanaUnbindNotificationResponseCode.GENERAL_ERROR.code,
                    "resultCode": DanaUnbindNotificationResponseCode.GENERAL_ERROR.result_code,
                    "resultMsg": DanaUnbindNotificationResponseCode.GENERAL_ERROR.message,
                }
            }

            return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_body)

        serializer = DanaUnlinkNotificationSerializer(data=data)
        if not serializer.is_valid():
            response_body["response"]["body"] = {
                "resultInfo": {
                    "resultStatus": "F",
                    "resultCodeId": DanaUnbindNotificationResponseCode.GENERAL_ERROR.code,
                    "resultCode": DanaUnbindNotificationResponseCode.GENERAL_ERROR.result_code,
                    "resultMsg": DanaUnbindNotificationResponseCode.GENERAL_ERROR.message,
                }
            }
            return JsonResponse(status=status.HTTP_400_BAD_REQUEST, data=response_body)
        data = data["request"]["body"]
        unbind_access_token_list = data["unbindAccessToken"]
        dana_wallet_account_list = DanaWalletAccount.objects.filter(
            access_token__in=unbind_access_token_list
        )
        if not dana_wallet_account_list:
            response_body["response"]["body"] = {
                "resultInfo": {
                    "resultStatus": "F",
                    "resultCodeId": DanaUnbindNotificationResponseCode.GENERAL_ERROR.code,
                    "resultCode": DanaUnbindNotificationResponseCode.GENERAL_ERROR.result_code,
                    "resultMsg": DanaUnbindNotificationResponseCode.GENERAL_ERROR.message,
                }
            }
            return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_body)
        with transaction.atomic():
            dana_wallet_account_list.update(
                status=DanaWalletAccountStatusConst.DISABLED
            )
            accounts = Account.objects.filter(
                id__in=dana_wallet_account_list.values_list("account_id", flat=True)
            )
            _filter = {
                "account__in": accounts,
                "is_deleted_autodebet": False,
                "vendor": AutodebetVendorConst.DANA,
                "activation_ts__isnull": False,
                "is_use_autodebet": True,
            }
            existing_autodebet_account = AutodebetAccount.objects.filter(**_filter)
            if existing_autodebet_account:
                existing_autodebet_account.update(
                    deleted_request_ts=timezone.localtime(timezone.now()),
                    deleted_success_ts=timezone.localtime(timezone.now()),
                    is_deleted_autodebet=True,
                    is_use_autodebet=False,
                    status=AutodebetStatuses.REVOKED,
                    notes="Unlink from DANA side",
                )
        response_body["response"]["body"] = {
            "resultInfo": {
                "resultStatus": "S",
                "resultCodeId": DanaUnbindNotificationResponseCode.SUCCESS.code,
                "resultCode": DanaUnbindNotificationResponseCode.SUCCESS.result_code,
                "resultMsg": DanaUnbindNotificationResponseCode.SUCCESS.message,
            }
        }

        return JsonResponse(status=status.HTTP_200_OK, data=response_body)

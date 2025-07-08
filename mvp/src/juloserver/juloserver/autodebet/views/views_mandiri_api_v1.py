import logging
from typing import Any
from datetime import datetime
import json

from juloserver.autodebet.models import AutodebetMandiriAccount, AutodebetAPILog
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)
from rest_framework.request import Request

from juloserver.autodebet.services.mandiri_services import (
    mandiri_autodebet_deactivation,
    check_mandiri_callback_activation
)
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin
)
from django.http import (
    JsonResponse,
)
from django.utils import timezone
from django.conf import settings
from celery import chain

from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.standardized_api_response.mixin import StrictStandardizedExceptionHandlerMixin

from juloserver.autodebet.serializers import (
    MandiriOTPVerifySerializer,
    MandiriActivationSerializer,
    AutodebetSuspendReactivationSerializer,
)

from juloserver.autodebet.services.mandiri_services import (
    is_mandiri_request_otp_success,
    is_mandiri_verify_otp_success,
)
from juloserver.autodebet.services.task_services import get_autodebet_payment_method

from juloserver.autodebet.services.mandiri_services import (
    process_mandiri_activation,
    validate_mandiri_activation_signature,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    PaybackTransaction,
    FeatureSetting,
)
from juloserver.julo.utils import generate_hex_sha256

from juloserver.autodebet.models import (
    AutodebetMandiriTransaction,
)
from juloserver.autodebet.serializers import (
    MandiriPurchaseNotificationSerializer,
)
from juloserver.autodebet.services.task_services import (
    check_and_create_debit_payment_process_after_callback_mandiriv2,
)
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    FeatureNameConst,
    VendorConst,
)
from juloserver.autodebet.services.mandiri_services import (
    process_mandiri_autodebet_repayment,
)
from juloserver.integapiv1.utils import verify_asymmetric_signature
from django.views.decorators.csrf import csrf_exempt

from juloserver.autodebet.tasks import (
    store_autodebet_api_log,
    send_slack_alert_mandiri_purchase_notification,
    suspend_autodebet_mandiri_insufficient_balance,
)
from juloserver.autodebet.services.account_services import (
    autodebet_account_reactivation_from_suspended
)
from juloserver.moengage.tasks import send_event_autodebit_failed_deduction_task

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class MandiriAccountDeactivationView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request, *args, **kwargs):
        account = request.user.customer.account
        message, status = mandiri_autodebet_deactivation(account)

        if not status:
            return general_error_response(message)

        return success_response({'message': message})


class RequestOTPView(StrictStandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        account = customer.account
        message, status = is_mandiri_request_otp_success(account)
        if not status:
            return general_error_response(message)
        return success_response({"message": message})


class VerifyOTPView(StrictStandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = MandiriOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        account = customer.account
        message, status = is_mandiri_verify_otp_success(serializer.data['otp'], account)
        if not status:
            return general_error_response(message)

        # create payment method mandiri autodebet
        get_autodebet_payment_method(
            account,
            AutodebetVendorConst.MANDIRI,
            AutodebetVendorConst.PAYMENT_METHOD.get(AutodebetVendorConst.MANDIRI)
        )
        return success_response({"message": message})


class PurchaseNotificationView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = MandiriPurchaseNotificationSerializer

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        today = timezone.localtime(timezone.now())
        response['X-TIMESTAMP'] = "{}+07:00".format(today.strftime("%Y-%m-%dT%H:%M:%S"))
        response['X-SIGNATURE'] = request.META.get('HTTP_X_SIGNATURE', None)
        response['X-EXTERNAL-ID'] = request.META.get('HTTP_X_EXTERNAL_ID', None)
        response['X-PARTNER-ID'] = request.META.get('HTTP_X_PARTNER_ID', None)
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.MANDIRI_SLACK_ALERT_PAYMENT_NOTIFICATION,
            is_active=True
        ).first()
        is_send_slack_alert = self.kwargs.get('is_send_slack_alert', False)
        if feature_setting and (response.status_code != HTTP_200_OK or is_send_slack_alert):
            send_slack_alert_mandiri_purchase_notification.delay(
                self.kwargs.get('slack_error_message'),
                self.kwargs.get('original_partner_reference_no'),
                self.kwargs.get('account_id'),
                self.kwargs.get('account_payment_id'),
                self.kwargs.get('application_id'),
            )

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        headers = {
            'HTTP_X_TIMESTAMP': request.META.get('HTTP_X_TIMESTAMP', None),
            'HTTP_X_SIGNATURE': request.META.get('HTTP_X_SIGNATURE', None),
            'HTTP_X_PARTNER_ID': request.META.get('HTTP_X_PARTNER_ID', None),
            'HTTP_X_EXTERNAL_ID': request.META.get('HTTP_X_EXTERNAL_ID', None),
        }
        data_to_log = {
            "action": "juloserver.autodebet.views.views_mandiri_api_v1.PurchaseNotificationView",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }

        # init chain of tasks
        task_chain = [
            store_autodebet_api_log.si(
                request_body, response.content, response.status_code,
                '[POST] {}'.format(request.get_full_path()), VendorConst.MANDIRI,
                self.kwargs.get('account_id'),
                self.kwargs.get('account_payment_id'), self.kwargs.get('slack_error_message'),
            )
        ]

        # validate and append tasks to chain
        is_insufficient_funds = self.kwargs.get('is_insufficient_funds', False)
        if is_insufficient_funds:
            task_chain.append(
                suspend_autodebet_mandiri_insufficient_balance.si(
                    self.kwargs.get('autodebet_account_id')
                )
            )

        # Execute the chain
        chain(task_chain).apply_async()

        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)
        return

    def post(self, request: Request) -> JsonResponse:
        response_data = {"responseCode": "2005600", "responseMessage": "SUCCESS"}
        try:
            response_code = request.data.get('responseCode')
            if response_code and response_code == '4095600':
                return JsonResponse(status=HTTP_200_OK, data=response_data)
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                response_data["responseCode"] = "4005600"
                response_data["responseMessage"] = "INVALID FIELD FORMAT"
                self.kwargs['slack_error_message'] = response_data["responseMessage"]
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            data = serializer.validated_data
            timestamp = request.META.get('HTTP_X_TIMESTAMP')
            signature = request.META.get('HTTP_X_SIGNATURE')
            body = json.dumps(request.data, separators=(',', ':'))
            encrypted_data = generate_hex_sha256(body)
            string_to_sign = '%s:%s:%s:%s' % ('POST', request.get_full_path(),
                                              encrypted_data, timestamp)
            if not verify_asymmetric_signature(settings.AUTODEBET_MANDIRI_PUBLIC_KEY,
                                               signature, string_to_sign):
                response_data["responseCode"] = "401560"
                response_data["responseMessage"] = "INVALID SIGNATURE"
                self.kwargs['slack_error_message'] = response_data["responseMessage"]
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            self.kwargs['original_partner_reference_no'] = data["originalPartnerReferenceNo"]
            autodebet_mandiri_transaction = AutodebetMandiriTransaction.objects.select_related(
                "autodebet_mandiri_account"
            ).filter(
                original_partner_reference_no=data["originalPartnerReferenceNo"]
            ).first()
            if not autodebet_mandiri_transaction:
                response_data["responseCode"] = "4045600"
                response_data["responseMessage"] = "TRANSACTION NOT FOUND"
                self.kwargs['slack_error_message'] = response_data["responseMessage"]
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)
            vendor = (
                autodebet_mandiri_transaction.autodebet_mandiri_account.autodebet_account.vendor
            )
            paid_datetime = datetime.fromisoformat(timestamp)
            data['transaction_time'] = paid_datetime
            account = (
                autodebet_mandiri_transaction.autodebet_mandiri_account.autodebet_account.account
            )
            self.kwargs['account_id'] = account.id
            self.kwargs['account_payment_id'] = autodebet_mandiri_transaction.account_payment_id
            self.kwargs['application_id'] = account.last_application.id
            payback_transaction, _ = PaybackTransaction.objects.get_or_create(
                customer=account.customer,
                payback_service='autodebet',
                status_desc='Autodebet {}'.format(vendor),
                transaction_id=autodebet_mandiri_transaction.original_partner_reference_no,
                amount=autodebet_mandiri_transaction.amount,
                account=account,
                payment_method=get_autodebet_payment_method(
                    account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
                ),
                defaults={"is_processed": False, "transaction_date": paid_datetime}
            )
            if payback_transaction.is_processed:
                response_data["responseCode"] = "400560"
                response_data["responseMessage"] = "TRANSACTION ALREADY PROCESSED"
                self.kwargs['slack_error_message'] = response_data["responseMessage"]
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)
            if data['responseCode'] == '2005600' and data['responseMessage'] == 'SUCCESSFUL':
                payment_processed = process_mandiri_autodebet_repayment(
                    payback_transaction, data, autodebet_mandiri_transaction
                )
                if payment_processed:
                    check_and_create_debit_payment_process_after_callback_mandiriv2(account)
            else:
                self.kwargs['is_send_slack_alert'] = True
                self.kwargs['slack_error_message'] = data['responseMessage']
                response_data["responseCode"] = data['responseCode']
                response_data["responseMessage"] = data['responseMessage']
                autodebet_mandiri_transaction.update_safely(status="failed")
                if data.get('responseMessage', '').upper() == 'INSUFFICIENT FUNDS':
                    self.kwargs['is_insufficient_funds'] = True
                    self.kwargs['autodebet_account_id'] = \
                        autodebet_mandiri_transaction.autodebet_mandiri_account.autodebet_account.id
                    send_event_autodebit_failed_deduction_task.apply_async(
                        (
                            self.kwargs['account_payment_id'],
                            account.customer.id,
                            vendor,
                        ),
                        countdown=5,
                    )
            return JsonResponse(status=HTTP_200_OK, data=response_data)

        except Exception as e:
            response_data["responseCode"] = "5005600"
            response_data["responseMessage"] = "INTERNAL SERVER ERROR"
            sentry_client.captureException()
            self.kwargs['slack_error_message'] = str(e)
            return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)


class ActivationView(StrictStandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = MandiriActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = request.user.customer.account
        message, status, journey_id = process_mandiri_activation(account, serializer.data)

        if not status:
            return general_error_response(message)

        AutodebetMandiriAccount.objects.create(
            autodebet_account=account.autodebetaccount_set.last(),
            journey_id=journey_id
        )
        return success_response(message)


class ActivationNotificationCallbackView(StrictStandardizedExceptionHandlerMixin, APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request):
        x_signature = request.META.get('HTTP_X_SIGNATURE')
        data = request.data
        is_valid = validate_mandiri_activation_signature(data, x_signature)

        if is_valid:
            autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
                journey_id=data['journeyID']
            ).last()
            if autodebet_mandiri_account:
                if data['responseMessage'].lower() == 'successful':
                    autodebet_mandiri_account.update_safely(charge_token=data['chargeToken'])

                account = autodebet_mandiri_account.autodebet_account.account
                AutodebetAPILog.objects.create(
                    application_id=account.last_application.id,
                    account_id=account.id,
                    request_type='[POST] /WEBHOOK/MANDIRI/V1/BINDING_NOTIFICATION',
                    http_status_code=200,
                    request=data,
                    response='',
                    error_message='',
                    vendor=AutodebetVendorConst.MANDIRI
                )

        return success_response(json.dumps(
            {'responseCode': '2000100', 'responseMessage': 'SUCCESS'}, separators=(',', ':')))


class CheckCallbackActivation(StrictStandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        message, status = check_mandiri_callback_activation(account)
        if not status:
            return general_error_response(message)
        return success_response(message)


class ReactivateView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, AutodebetVendorConst.MANDIRI)

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, AutodebetVendorConst.MANDIRI)

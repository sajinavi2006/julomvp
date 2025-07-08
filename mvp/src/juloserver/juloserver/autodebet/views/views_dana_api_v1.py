import logging
from typing import Any
from datetime import datetime
from django.http.response import JsonResponse
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from django.db import transaction
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment

from juloserver.autodebet.services.dana_services import (
    dana_autodebet_activation,
    dana_autodebet_deactivation,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.autodebet.tasks import (
    store_autodebet_api_log,
)
from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    VendorConst,
    AutodebetDANAPaymentResultStatusConst,
    DanaPaymentNotificationResponse,
    DanaErrorCode,
)
from juloserver.dana_linking.constants import (
    ErrorDetail,
    FeatureNameConst,
)
from juloserver.julo.models import FeatureSetting
from juloserver.dana_linking.utils import generate_string_to_sign_asymmetric
from juloserver.integapiv1.utils import verify_asymmetric_signature
from juloserver.autodebet.services.task_services import get_autodebet_payment_method
from juloserver.dana_linking.serializers import DanaPaymentNotificationSerializer
from juloserver.autodebet.serializers import AutodebetSuspendReactivationSerializer
from juloserver.autodebet.models import AutodebetDanaTransaction
from juloserver.julo.models import PaybackTransaction
from juloserver.moengage.tasks import (
    update_moengage_for_payment_received_task,
    send_event_autodebit_failed_deduction_task,
)
from juloserver.autodebet.models import AutodebetBenefit
from juloserver.autodebet.services.benefit_services import is_eligible_to_get_benefit, give_benefit
from juloserver.autodebet.tasks import send_slack_alert_dana_failed_subscription_and_deduction
from juloserver.autodebet.services.account_services import (
    autodebet_account_reactivation_from_suspended,
)
from juloserver.autodebet.services.autodebet_services import suspend_autodebet_insufficient_balance


logger = logging.getLogger(__name__)


class ActivationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        response, status = dana_autodebet_activation(account)

        if not status:
            return general_error_response(response.message, data={"error_code": response.code})

        return success_response(response.message)


class DeactivationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        response, status = dana_autodebet_deactivation(account)

        if not status:
            return general_error_response(response.message, data={"error_code": response.code})

        return success_response(response.message)


class PaymentNotificationCallbackView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)

        if response.status_code != HTTP_200_OK:
            send_slack_alert_dana_failed_subscription_and_deduction.delay(
                error_message=self.kwargs.get('error_message'),
                account_id=self.kwargs.get('account_id'),
                account_payment_id=self.kwargs.get('account_payment_id'),
                application_id=self.kwargs.get('application_id'),
                original_partner_reference_no=self.kwargs.get('original_partner_reference_no'),
            )

        return response

    def _log_request(self, request_body: bytes, request: Request, response: Response):
        headers = {'HTTP_AUTHORIZATION': request.META.get('HTTP_AUTHORIZATION', None)}
        data_to_log = {
            "action": "AutodebetDanaPaymentNotificationCallback",
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
            VendorConst.DANA,
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
        try:
            relative_url = request.get_full_path()
            skip_process = False
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.SKIP_PROCESS_AUTH, is_active=True
            ).exists()
            if settings.ENVIRONMENT != 'prod' and feature_setting:
                skip_process = True

            data = request.data
            method = request.method
            self.kwargs['original_partner_reference_no'] = data.get("originalPartnerReferenceNo")
            x_signature = request.META.get('HTTP_X_SIGNATURE')
            timestamp = request.META.get('HTTP_X_TIMESTAMP')
            string_to_sign = generate_string_to_sign_asymmetric(
                timestamp, data, method, relative_url
            )
            is_verify_signature = verify_asymmetric_signature(
                settings.DANA_LINKING_PUBLIC_KEY, x_signature, string_to_sign
            )
            is_verify_signature = skip_process if skip_process else is_verify_signature
            if not is_verify_signature:
                response_message = DanaPaymentNotificationResponse.UNAUTHORIZED.message
                response_data = {
                    'responseCode': DanaPaymentNotificationResponse.UNAUTHORIZED.code,
                    'responseMessage': response_message + " [invalid signature]",
                }
                self.kwargs['error_message'] = response_data["responseMessage"]

                return JsonResponse(status=status.HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = DanaPaymentNotificationSerializer(data=request.data)
            if not serializer.is_valid():
                errors = list(serializer.errors.items())[0][1][0]
                response_message = DanaPaymentNotificationResponse.INVALID_FIELD_FORMAT.message
                response_code = DanaPaymentNotificationResponse.INVALID_FIELD_FORMAT.code
                if errors in ErrorDetail.mandatory_field_errors():
                    response_code = DanaPaymentNotificationResponse.INVALID_MANDATORY_FIELD.code
                    response_message = (
                        DanaPaymentNotificationResponse.INVALID_MANDATORY_FIELD.message
                    )
                response_data = {
                    "responseCode": response_code,
                    "responseMessage": response_message,
                }
                self.kwargs['error_message'] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_400_BAD_REQUEST, data=response_data)

            partner_reference_no = data['originalPartnerReferenceNo']
            autodebet_dana_transaction = AutodebetDanaTransaction.objects.filter(
                original_partner_reference_no=partner_reference_no,
                status=AutodebetDANAPaymentResultStatusConst.PENDING,
            ).last()

            if not autodebet_dana_transaction:
                response_data = {
                    "responseCode": (DanaPaymentNotificationResponse.TRANSACTION_NOT_FOUND.code),
                    "responseMessage": (
                        DanaPaymentNotificationResponse.TRANSACTION_NOT_FOUND.message
                    ),
                }
                self.kwargs['error_message'] = response_data["responseMessage"]
                return JsonResponse(status=status.HTTP_404_NOT_FOUND, data=response_data)

            account_payment = autodebet_dana_transaction.account_payment
            account = account_payment.account
            amount = int(float(data['amount']['value']))
            vendor = AutodebetVendorConst.DANA
            self.kwargs['account_id'] = account.id
            self.kwargs['account_payment_id'] = account_payment.id if account_payment else None
            self.kwargs['application_id'] = account.last_application.id

            # FAILED TRANSACTION
            if data["latestTransactionStatus"] != "00":
                send_event_autodebit_failed_deduction_task.delay(
                    account_payment.id, account.customer.id, vendor
                )
                autodebet_dana_transaction.update_safely(
                    status=AutodebetDANAPaymentResultStatusConst.FAILED,
                )

                if autodebet_dana_transaction.status_desc == DanaErrorCode.INSUFFICIENT_FUND:
                    autodebet_account = account.autodebetaccount_set.filter(
                        is_use_autodebet=True
                    ).last()
                    suspend_autodebet_insufficient_balance(autodebet_account, VendorConst.DANA)
                    self.kwargs['error_message'] = DanaErrorCode.INSUFFICIENT_FUND

                response_data = {
                    "responseCode": DanaPaymentNotificationResponse.SUCCESS.code,
                    "responseMessage": DanaPaymentNotificationResponse.SUCCESS.message,
                }
                return JsonResponse(data=response_data, status=status.HTTP_200_OK)

            # SUCCESS TRANSACTION
            with transaction.atomic():
                is_partial = amount < autodebet_dana_transaction.amount
                paid_date = datetime.strptime(data['finishedTime'], "%Y-%m-%dT%H:%M:%S%z")

                payback_transaction, _ = PaybackTransaction.objects.get_or_create(
                    customer=account.customer,
                    payback_service='autodebet',
                    status_desc='Autodebet {}'.format(vendor),
                    transaction_id=partner_reference_no,
                    amount=amount,
                    account=account,
                    payment_method=get_autodebet_payment_method(
                        account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
                    ),
                    defaults={"is_processed": False, "transaction_date": paid_date},
                )
                if payback_transaction.is_processed:
                    response_data = {
                        "responseCode": DanaPaymentNotificationResponse.SUCCESS.code,
                        "responseMessage": DanaPaymentNotificationResponse.SUCCESS.message,
                    }
                    return JsonResponse(status=status.HTTP_200_OK, data=response_data)

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

                autodebet_dana_transaction.update_safely(
                    status=AutodebetDANAPaymentResultStatusConst.SUCCESS,
                    is_partial=is_partial,
                    paid_amount=amount,
                    status_desc=None,
                )

                # GIVE BENEFIT
                benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
                if benefit and not is_partial and autodebet_dana_transaction.is_eligible_benefit:
                    if is_eligible_to_get_benefit(account):
                        give_benefit(benefit, account, account_payment)

                execute_after_transaction_safely(
                    lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
                )

            response_data = {
                "responseCode": DanaPaymentNotificationResponse.SUCCESS.code,
                "responseMessage": DanaPaymentNotificationResponse.SUCCESS.message,
            }
            return JsonResponse(status=status.HTTP_200_OK, data=response_data)

        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            response_message = DanaPaymentNotificationResponse.INTERNAL_SERVER.message
            response_code = DanaPaymentNotificationResponse.INTERNAL_SERVER.code
            response_data = {
                "responseCode": response_code,
                "responseMessage": response_message,
            }
            self.kwargs['error_message'] = response_data["responseMessage"]
            return JsonResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR, data=response_data)


class ReactivationView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, AutodebetVendorConst.DANA
        )

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, AutodebetVendorConst.DANA
        )

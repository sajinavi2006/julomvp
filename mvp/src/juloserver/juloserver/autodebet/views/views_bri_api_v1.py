import logging

from rest_framework.views import APIView

from juloserver.autodebet.constants import (
    BRIErrorCode,
    BRITransactionCallbackStatus,
    AutodebetVendorConst,
)
from juloserver.autodebet.security import AutodebetBRIAuthentication
from juloserver.autodebet.services.account_services import \
    autodebet_account_reactivation_from_suspended
from juloserver.autodebet.services.task_services import process_fund_collection
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    forbidden_error_response,
)

from juloserver.autodebet.serializers import (
    BRIAccountRegistrationSerializer,
    BRIOTPVerifySerializer,
    BRIDeactivationSerializer,
    AutodebetSuspendReactivationSerializer,
)
from juloserver.autodebet.services.authorization_services import (
    process_bri_account_registration,
    process_bri_registration_otp_verify,
    process_bri_transaction_otp_verify,
    process_bri_transaction_callback,
    process_bri_account_revocation,
)
from juloserver.autodebet.views.views_bca_api_v1 import AccountResetView
from juloserver.autodebet.services.autodebet_bri_services import (
    check_and_create_debit_payment_process_after_callback,
)

from juloserver.autodebet.services.autodebet_bri_services import create_debit_payment_process_otp
from juloserver.julo.models import PaybackTransaction


logger = logging.getLogger(__name__)


class BRIAccountRegistrationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = BRIAccountRegistrationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data

        account = request.user.customer.account
        result, error_msg = process_bri_account_registration(account, data)
        if error_msg:

            if result and result['error_code'] == BRIErrorCode.INVALID_ACCOUNT_DETAILS:
                return forbidden_error_response(error_msg)

            return general_error_response(error_msg)

        return success_response(result)


class BRIRegistrationOTPVerifyView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = BRIOTPVerifySerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data

        account = request.user.customer.account

        result, error_msg = process_bri_registration_otp_verify(account, data)
        if error_msg:
            return general_error_response(error_msg)

        return success_response(result)


class BRIAccountResetView(AccountResetView):
    pass


class BRITransactionRequestOTPView(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        account = request.user.customer.account
        result, error_msg = create_debit_payment_process_otp(account)
        if error_msg:
            return general_error_response(error_msg)

        return success_response(result)


class BRITransactionOTPVerifyView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = BRIOTPVerifySerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data

        account = request.user.customer.account

        error_msg = process_bri_transaction_otp_verify(account, data["otp"])
        if error_msg:
            return general_error_response(error_msg)

        return success_response({"status": "SUCCESS"})


class BRITransactionCallbackView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (AutodebetBRIAuthentication, )
    permission_classes = ()

    def post(self, request):
        data = request.data
        status_callback, account_payment, amount, account, autodebet_api_log = \
            process_bri_transaction_callback(data)
        if status_callback == BRITransactionCallbackStatus.COMPLETED:
            payback_transaction = PaybackTransaction.objects.get_or_none(
                transaction_id=data["id"]
            )
            if payback_transaction and payback_transaction.is_processed:
                logger.warning(
                    {
                        "action": "juloserver.autodebet.views.views_bri_api_v1."
                                  "BRITransactionCallbackView",
                        "data": data,
                        "error": "Transaction has been "
                                 "processed, reference_id: %s" % data["reference_id"],
                    }
                )
                return success_response({"status": "SUCCESS"})
            error = process_fund_collection(account_payment, AutodebetVendorConst.BRI, amount,
                                            data['id'])
            autodebet_api_log.update_safely(
                error_message=error,
                http_status_code=400 if error else 200,
                vendor=AutodebetVendorConst.BRI
            )

            if not error:
                message = check_and_create_debit_payment_process_after_callback(account)
                autodebet_api_log.update_safely(
                    response=message,
                    vendor=AutodebetVendorConst.BRI
                )

        return success_response({"status": "SUCCESS"})


class BRIDeactivationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = BRIDeactivationSerializer

    def post(self, request, *args, **kwargs):
        account = request.user.customer.account
        error_msg = process_bri_account_revocation(account)

        if error_msg:
            return general_error_response(error_msg)

        return success_response({"status": "SUCCESS"})


class ReactivateView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, AutodebetVendorConst.BRI)

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, AutodebetVendorConst.BRI)

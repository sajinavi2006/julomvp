import logging
from rest_framework.views import APIView

from juloserver.autodebet.services.ovo_services import (
    ovo_autodebet_activation,
    ovo_autodebet_deactivation,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.autodebet.tasks import (
    send_slack_alert_ovo_failed_subscription_and_deduction_linking,
)
from juloserver.autodebet.serializers import AutodebetSuspendReactivationSerializer
from juloserver.autodebet.services.account_services import (
    autodebet_account_reactivation_from_suspended,
)


logger = logging.getLogger(__name__)


class ActivationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        response, status = ovo_autodebet_activation(account)

        if not status:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=response.message,
                topic=request.get_full_path(),
                account_id=request.user.customer.account,
                is_autodebet=True,
            )
            return general_error_response(response.message, data={"error_code": response.code})

        return success_response(response.message)


class DeactivationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        response, status = ovo_autodebet_deactivation(account)

        if not status:
            send_slack_alert_ovo_failed_subscription_and_deduction_linking.delay(
                error_message=response.message,
                topic=request.get_full_path(),
                account_id=request.user.customer.account,
                is_autodebet=True,
            )
            return general_error_response(response.message, data={"error_code": response.code})

        return success_response(response.message)


class ReactivationView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, AutodebetVendorConst.OVO
        )

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, AutodebetVendorConst.OVO
        )

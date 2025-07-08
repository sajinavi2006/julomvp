from rest_framework.views import APIView

from juloserver.autodebet.services.authorization_services import (
    gopay_registration_autodebet,
    gopay_autodebet_revocation,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response
from juloserver.autodebet.services.account_services import (
    autodebet_account_reactivation_from_suspended
)
from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.autodebet.serializers import AutodebetSuspendReactivationSerializer


class GopayRegistrationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        message, status = gopay_registration_autodebet(account)

        if not status:
            return general_error_response(message)

        return success_response(message)


class GopayRevocationView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        account = request.user.customer.account
        message, status = gopay_autodebet_revocation(account)

        if not status:
            return general_error_response(message)

        return success_response(message)


class ReactivateView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, AutodebetVendorConst.GOPAY)

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, AutodebetVendorConst.GOPAY)

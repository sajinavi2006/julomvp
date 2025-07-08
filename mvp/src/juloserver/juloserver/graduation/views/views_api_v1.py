from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    not_found_response,
)

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.graduation.services import (
    get_customer_downgrade_info_alert,
)


class DowngradeInfoAlertAPIView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.get_active_application()
        if not application:
            return not_found_response(message='Application not found')

        data_response = get_customer_downgrade_info_alert(customer)
        return success_response(data_response)

import logging
from rest_framework.views import APIView
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import success_response, \
    general_error_response
from juloserver.streamlined_communication.services2.web_services import construct_web_infocards

logger = logging.getLogger(__name__)


class WebInfoCards(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        if not application:
            return general_error_response("Aplikasi tidak ditemukan")

        application_status_no_need_credit_score = [
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationStatusCodes.FORM_PARTIAL
        ]
        if not hasattr(application, 'creditscore') and \
           application.application_status_id not in application_status_no_need_credit_score:
            empty_data = {'cards': []}
            return success_response(empty_data)
        info_cards = construct_web_infocards(customer, application)
        return success_response(info_cards)

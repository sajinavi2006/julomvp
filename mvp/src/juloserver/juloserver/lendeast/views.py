import logging

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
)

from django.http import JsonResponse

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

from juloserver.julo.utils import generate_base64
from juloserver.julo.models import Partner

from juloserver.integapiv1.views import LoggedResponse

from juloserver.lendeast.constants import LendEastConst
from juloserver.lendeast.services import (
    get_data_by_month,
    construct_general_response_data,
)

from .utils import get_first_day_in_month

logger = logging.getLogger(__name__)


class LoanInformation(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        lendeast_partner = Partner.objects.get(name=LendEastConst.PARTNER_NAME)
        req_auth = request.META.get('HTTP_AUTHORIZATION')
        lendeast_auth = 'Basic ' + generate_base64(
            "{}, {}".format(LendEastConst.PARTNER_NAME, lendeast_partner.token))
        logger.info({
            'action': 'juloserver.lendeast.views.LoanInformation',
            'request': request.__dict__,
        })

        if req_auth != lendeast_auth:
            return LoggedResponse(status=HTTP_401_UNAUTHORIZED, data={})

        page_number = int(request.GET.get('page', 1))
        current_month_year = get_first_day_in_month()

        data = get_data_by_month(current_month_year, page_number)
        res = construct_general_response_data(
            HTTP_200_OK, "Success", current_month_year, page_number, data
        )
        return JsonResponse(res)

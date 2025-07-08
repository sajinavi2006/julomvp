import logging

from django.http import HttpRequest, HttpResponse
from functools import wraps

from juloserver.julo.models import FeatureSetting
from juloserver.partnership.api_response import error_response
from juloserver.partnership.constants import HTTPGeneralErrorMessage
from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting

from rest_framework import status

from typing import Callable, Any

logger = logging.getLogger(__name__)


def allowed_leadgen_partner(function: Callable):
    @wraps(function)
    def wrapper(view, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        partner_name = request.partner_name

        leadgen_config_params = (
            FeatureSetting.objects.filter(feature_name=LeadgenFeatureSetting.API_CONFIG)
            .values_list('parameters', flat=True)
            .last()
        )

        allowed_partners = (
            leadgen_config_params.get('allowed_partner', []) if leadgen_config_params else []
        )

        if not allowed_partners:
            logger.error(
                {
                    'action': 'leadgen_partner_config',
                    'error': 'allowed_partner configuration not yet set',
                }
            )

            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        if partner_name not in allowed_partners:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=HTTPGeneralErrorMessage.FORBIDDEN_ACCESS,
            )

        return function(view, request, *args, **kwargs)

    return wrapper


def make_request_mutable(func):
    @wraps(func)
    def wrapper(self, request, *args, **kwargs):
        request.data._mutable = True
        request.query_params._mutable = True

        return func(self, request, *args, **kwargs)

    return wrapper

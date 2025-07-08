from builtins import str
from builtins import object
import logging
from django.conf import settings
from django.utils import translation
from rest_framework import status
from raven.contrib.django.raven_compat.models import client

logger = logging.getLogger(__name__)

class StandardizedApiURLMiddleware(object):

    successful_statuses = [
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
        status.HTTP_202_ACCEPTED,
    ]

    def process_response(self, request, response):
        # Code to be executed for each api request before
        # the view (and later middleware) are called.

        path = request.path
        api_str = ['/api/v1/', '/api/v2/', '/api/v3/', '/api/sdk/', '/api/revamp/']

        if not any(endpoint in str(path) for endpoint in api_str):
            return response

        if response.status_code not in self.successful_statuses:

            error_data = dict()

            error_data["request_path"] = request.path
            error_data["request_method"] = request.method
            if request.method == "GET":
                error_data["request_params"] = request.GET.dict()
            else:
                error_data["request_body"] = request.POST.dict()

            error_data["response_status_code"] = response.status_code
            error_data["response_content"] = response.content

            logger.error(error_data)

        return response

    def process_request(self, request):
        if 'HTTP_X_APP_MODULE' in request.META:
            client.tags_context({'app_module': request.META['HTTP_X_APP_MODULE']})
        if 'HTTP_X_APP_VERSION' in request.META:
            client.tags_context({'app_version': request.META['HTTP_X_APP_VERSION']})
        if request.path.startswith('/api/revamp') or \
                request.path.startswith('/api/pin/web/') or\
                ('/api/' in request.path and '/web/' in request.path):
            request.LANG = getattr(
                settings, 'STANDARDIZED_API_LANGUAGE_CODE', settings.LANGUAGE_CODE)
            translation.activate(request.LANG)
            request.LANGUAGE_CODE = request.LANG


class StandardizedTestApiURLMiddleware(StandardizedApiURLMiddleware):
    def process_response(self, request, response):
        translation.deactivate()
        return super(StandardizedTestApiURLMiddleware, self).process_response(request, response)

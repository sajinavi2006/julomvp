from builtins import object, str


import time
import logging
import json
from django.conf import settings
from django.http import RawPostDataException
from rest_framework import status

from juloserver.julocore.utils import get_client_ip


class ApiLoggingMiddleware(object):
    def process_request(self, request):
        request.start_time_to_log = time.time()

    def process_response(self, request, response):
        if not hasattr(request, 'start_time_to_log'):
            return response

        try:
            request.post_to_log = request.POST
            request.body_to_log = request.body
        except RawPostDataException:
            request.post_to_log = b''
            request.body_to_log = b''
        path = request.path

        if any(
            p in str(path)
            for p in [
                'api/liveness-detection/',
                'api/application-form/v2/application',
                'api/application-form/v1/cancel',
                'api/application-form/v2/reapply',
                'api/application_flow/v1/bottom-sheet-tutorial',
                'api/julo-starter/v1/application',
                'api/otp/v1/validate',
                'api/otp/v2/validate',
                'api/otp/v1/request',
                'api/otp/v2/request',
                'api/pin/v3/login',
                'api/pin/v4/login',
                'api/otp/v1/check-user-allowed',
                'api/customer-module/v1/appsflyer',
            ]
        ):
            return response

        if response.status_code < status.HTTP_400_BAD_REQUEST:
            return response

        ip_address = get_client_ip(request)

        request_body = None
        if request.method in ('POST', 'PATCH', 'PUT'):
            if request.post_to_log:
                request_body = request.post_to_log.dict()
            else:
                if (
                    'CONTENT_TYPE' in request.META
                    and 'json' in request.META['CONTENT_TYPE'].lower()
                ):
                    try:
                        request_body = json.loads(request.body_to_log.decode(errors='replace'))
                    except json.JSONDecodeError as jde:
                        request_body = "%s: %s\n %s" % (
                            jde.__class__.__name__,
                            str(jde),
                            request.body_to_log.decode(errors='replace'),
                        )
                else:
                    request_body = request.body_to_log.decode(errors='replace')

        log_content = {
            'action': 'logging_api_error',
            'ip_address': ip_address,
            'method': request.method,
            'path': path,
            'request_params': request.GET.dict(),
            'request_body': request_body,
            'payload_size': len(response.content),
            'response_status': response.status_code,
            'response_body': response.content.decode(errors='replace'),
            'duration': round(time.time() - request.start_time_to_log, 3),
        }

        if any(p in str(path) for p in settings.LOGGING_BLACKLISTED_PATHS):
            del log_content['request_params']
            del log_content['request_body']

        response_logger = logging.getLogger('api.request')
        response_logger.error(json.dumps(log_content))

        return response

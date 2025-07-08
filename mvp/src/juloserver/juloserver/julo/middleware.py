from __future__ import unicode_literals

from builtins import str
from builtins import object
import json
import logging
import coverage
from uuid import uuid4

from amqp import AMQPError
from rest_framework import status

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.tasks import capture_device_ip
from juloserver.julocore.utils import get_client_ip
import threading

# Thread-local storage for request-specific data
_thread_locals = threading.local()

logger = logging.getLogger(__name__)


def get_request_id():
    return getattr(_thread_locals, 'request_id', None)


class DeviceIpMiddleware(object):

    def process_response(self, request, response):

        path = request.path

        api_str = [
            '/api/v1/',
            '/api/v2/',
            '/api/sdk/',
            '/api/v3/',
            '/api/application-form/',
            '/api/application_flow/',
            '/api/customer-module/',
            '/api/liveness-detection/',
            '/api/ocr/',
            '/api/face_recognition/',
            '/api/v3/healthcheck'
        ]

        # if path does not contain string in api_str, skip the middleware
        if not any(endpoint in str(path) for endpoint in api_str):
            return response

        unauthed_api_endpoints = [
            'rest-auth/registration',
            'rest-auth/password',
            'rest-auth/login',
            'auth/v2/login',
            'devices/',
            'first-product-lines',
            'login/',
            'login2/',
            'otp/',
            'registration/',
            'register2/',
            'master-agreement-template'
        ]

        # if path contains string in unauthed_api_endpoints, skip the middleware
        for unauthed_api_endpoint in unauthed_api_endpoints:
            if unauthed_api_endpoint in path:
                return response

        response_status = response.status_code
        successful_statuses = [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_202_ACCEPTED,
            status.HTTP_203_NON_AUTHORITATIVE_INFORMATION,
            status.HTTP_204_NO_CONTENT,
            status.HTTP_205_RESET_CONTENT,
            status.HTTP_206_PARTIAL_CONTENT,
        ]

        if response_status not in successful_statuses:
            logger.warning({
                'path': path,
                'response_status': response_status,
                'status': 'not_successful_response'
            })
            return response

        has_user = hasattr(request, 'user')
        if not has_user or not request.user or request.user.is_anonymous():
            return response

        user = request.user
        ip_address = get_client_ip(request)

        if ip_address is None:
            logger.warning({
                'status': 'ip_address is None',
                'path': path,
                'ip_address': ip_address,
                'user': user
            })
            return response

        logger.info({
            'action': 'call_capture_device_ip',
            'path': path,
            'ip_address': ip_address,
            'user': user
        })

        try:
            capture_device_ip.delay(user, ip_address, path)
        except AMQPError:
            logger.exception('Something wrong with AMQP service.')
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
        
        return response


class RequestIDMiddleware:
    def process_request(self, request):
        # Generate or retrieve the request ID
        request_id = request.META.get("X-Request-ID", str(uuid4()))
        
        # Store the request_id in thread-local storage
        _thread_locals.request_id = request_id

    def process_response(self, request, response):
        # Attach the request_id to the response headers for tracking
        request_id = getattr(_thread_locals, 'request_id', 'NO_REQUEST_ID')
        response['X-Request-ID'] = request_id
        return response


class ApiRequestLoggingMiddleware(object):

    def process_response(self, request, response):
        request_logger = logging.getLogger('api.request')
        path = request.path

        # logged only for api/v1 and api/v2 endpoint
        valid_api_endpoints = ['/api/v1/', '/api/v2/', '/api/sdk']
        if not any(endpoint in str(path) for endpoint in valid_api_endpoints):
            return response

        # do not logged these endpoints for security reasons
        unlogged_api_endpoints = [
            '/v1/rest-auth/registration/',
            '/v2/registration/',
            '/v1/rest-auth/login/',
            '/v2/login/',
            '/v2/otp/login/',
            '/v2/otp/change-password/',
            '/v1/rest-auth/password/',
            '/v1/applications/external-data-imports/'
        ]
        if any(api in str(path) for api in unlogged_api_endpoints):
            return response

        ip_address = get_client_ip(request)

        request_body = None
        method_get_list = ['GET', 'PATCH', 'PUT']
        if request.method in method_get_list:
            request_body = json.dumps(request.GET)

        if request.method == 'POST':
            request_body = json.dumps(request.POST)

        request_logger.info({
            'action': 'api_request',
            'ip_address': ip_address,
            'path': path,
            'method': request.method,
            'response_status': response.status_code,
            'request_body': request_body
        })
        return response


class CatchCoverageMiddleware(object):
    def __init__(self):
        self.cov = coverage.coverage(auto_data=True, config_file='.coveragerc_python')

    def process_request(self, request):
        self.cov.start()
        return None

    def process_response( self, request, response):
        self.cov.stop()
        self.cov.save()
        return response

from rest_framework import exceptions, status
from rest_framework.response import Response

HTTP_209_TEMPORARY_TOKEN_CREATED = 209
HTTP_419_INVALID_OTP_TOKEN = 419
HTTP_423_LOCKED = 423
HTTP_425_TOO_EARLY = 425


def dict_template(**kwargs):
    return {
        'success': kwargs["success"],
        'data': kwargs["data"],
        'errors': kwargs["message"],
    }


def response_template(data=None, status=status.HTTP_200_OK, success=True, message=[]):
    response_dict = dict_template(success=success, data=data, message=message)
    return Response(status=status, data=response_dict)


def success_response(data=None, message=[]):
    return response_template(data, message=message)


def created_response(data=None):
    """Indicating update using post, patch, or put was successful"""
    return response_template(data, status.HTTP_201_CREATED)


def not_found_response(message, data=None):
    """Indicating that resource requested cannot be found"""
    return response_template(
        data, status.HTTP_404_NOT_FOUND, False, [message])


def not_found_response_custom_message(message, data=None):
    """Indicating that resource requested cannot be found"""
    """The message must be array"""
    return response_template(
        data, status.HTTP_404_NOT_FOUND, False, message)


def general_error_response(message, data=None):
    """Indicating that request parameters or payload failed valication"""
    return response_template(
        data, status.HTTP_400_BAD_REQUEST, False, [message])


def forbidden_error_response(message, data=None):
    """Indicating that request parameters or payload failed valication"""
    return response_template(
        data, status.HTTP_403_FORBIDDEN, False, [message])


def unauthorized_error_response(message, data=None):
    return response_template(
        data, status.HTTP_401_UNAUTHORIZED, False, [message])


def required_otp_token_response(data=None):
    return response_template(
        data, status.HTTP_203_NON_AUTHORITATIVE_INFORMATION)


def required_temporary_token_response(data=None):
    return response_template(
        data, HTTP_209_TEMPORARY_TOKEN_CREATED)


def invalid_otp_token_response(message, data=None):
    return response_template(
        data, HTTP_419_INVALID_OTP_TOKEN, False, [message])


def locked_response(message, data=None):
    return response_template(
        data, HTTP_423_LOCKED, False, [message])


def not_acceptable_response(message, data=None):
    return response_template(
        data, status.HTTP_406_NOT_ACCEPTABLE, False, [message])


def custom_bad_request_response(message, data=None):
    return response_template(
        data, status.HTTP_400_BAD_REQUEST, False, message)


def request_timeout_response(message, data=None):
    return response_template(
        data, status.HTTP_408_REQUEST_TIMEOUT, False, message
    )


def too_many_requests_response(message, retry_time_expired=None):
    if retry_time_expired:
        message = '%s. Coba lagi pada: %s' % (message, retry_time_expired)
    return response_template(
        None, status.HTTP_429_TOO_MANY_REQUESTS, False, message
    )


def internal_server_error_response(message, data=None):
    return response_template(
        data, status.HTTP_500_INTERNAL_SERVER_ERROR, False, [message])


def service_unavailable_error_response(message, data=None):
    return response_template(
        data, status.HTTP_503_SERVICE_UNAVAILABLE, False, [message])


def force_logout_response(message):
    raise exceptions.AuthenticationFailed(message)


def too_early_error_response(message, data=None):
    return response_template(data, HTTP_425_TOO_EARLY, False, [message])

from rest_framework.response import Response
from rest_framework import status


def response_template_success(status=status.HTTP_200_OK, data=None, meta={}):
    response_dict = {
        'data':data,
        'meta': meta
    }
    return Response(status=status, data=response_dict)

def response_template_error(status=status.HTTP_400_BAD_REQUEST, message='', meta={}, errors=[]):
    response_dict = {
        'message':message,
        'meta': meta,
        'errors': errors
    }
    return Response(status=status, data=response_dict)

def success_response_web_portal(data=[], meta={}):
    return response_template_success(data=data, meta=meta)

def error_response_web_portal(status=status.HTTP_400_BAD_REQUEST, message='', errors=[]):
    result = {}
    for field in errors:
        result[field] = errors[field][0]
    return response_template_error(status=status, message=message, errors=result)

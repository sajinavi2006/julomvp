from rest_framework import status
from rest_framework.response import Response


def qris_dict_template(**kwargs):
    return {
        'success': kwargs["success"],
        'data': kwargs["data"],
        'errors': kwargs["message"],
        'errorCode': kwargs["errorCode"],
    }


def qris_response_template(
    data=None, status=status.HTTP_200_OK, success=True, message=[], errorCode=None
):
    response_dict = qris_dict_template(
        success=success, data=data, message=message, errorCode=errorCode
    )
    return Response(status=status, data=response_dict)


def qris_success_response(data=None):
    return qris_response_template(data)


def qris_error_response(message, error_code=None, status=status.HTTP_400_BAD_REQUEST):
    return qris_response_template(None, status, False, [message], error_code)

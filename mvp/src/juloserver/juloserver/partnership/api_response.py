from typing import Dict

from rest_framework import status
from rest_framework.response import Response


def success_response(
    status: int = status.HTTP_200_OK,
    data: Dict = {},
    meta: Dict = {},
    is_display_data_field: bool = False,
    is_display_meta_field: bool = False,
    message: str = None,
):
    """
    Returns a JSON response with a success status.
    status: int = 2xx
    data: Dict = {'message': 'Data successfully created'}
    meta: Dict = {'description': 'Invalid JSON response'}
    """

    response_data = dict()

    if data or is_display_data_field:
        response_data['data'] = data

    if meta or is_display_meta_field:
        response_data['meta'] = meta

    if message:
        response_data['message'] = message

    return Response(status=status, data=response_data)


def error_response(
    status: int = status.HTTP_400_BAD_REQUEST,
    errors: Dict = {},
    meta: Dict = {},
    data: Dict = {},
    message: str = None,
):
    """
    Returns a JSON response with an error status.
    status: int = 4xx, 5xx
    errors: Dict = {'type': ['Jenis dokumen tidak diperbolehkan']}
    meta: Dict = {'type': ErrorType.ALERT}
    """
    response_data = dict()

    if errors:
        errors_data = dict()
        for field in errors:
            errors_data[field] = errors[field][0]

        response_data['errors'] = errors_data

    if meta:
        response_data['meta'] = meta

    if message:
        response_data['message'] = message

    if data:
        response_data['data'] = data

    return Response(status=status, data=response_data)

from rest_framework import status
from rest_framework.response import Response

from typing import Dict


def success_response(status: int = status.HTTP_200_OK, data: Dict = {}, meta: Dict = {}):
    """
    Returns a JSON response with a success status.
    status: int = 2xx
    data: Dict = {'message': 'Data successfully created'}
    meta: Dict = {'description': 'Invalid JSON response'}
    """

    response_data = dict()

    if data:
        response_data['data'] = data

    if meta:
        response_data['meta'] = meta

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
            if isinstance(errors[field], list):
                errors_data[field] = errors[field][0]
            else:
                # This for formatting child field error. example:
                # from:
                # {
                #     'company_photo': {
                #         'risk': "Harap pilih 'Risiko tinggi' atau 'Risiko rendah'.",
                #         'notes': "Melebihi batas maksimum karakter (100 karakter)."
                #     }
                # }
                # to:
                # {
                #     'company_photo.risk': "Harap pilih 'Risiko tinggi' atau 'Risiko rendah'.",
                #     'company_photo.risk': "Melebihi batas maksimum karakter (100 karakter)."
                # }
                error_field = errors[field]
                for child_field in error_field:
                    child_field_key = "{}.{}".format(field, child_field)
                    errors_data[child_field_key] = error_field[child_field][0]

        response_data['errors'] = errors_data

    if meta:
        response_data['meta'] = meta

    if data:
        response_data['data'] = data

    if message:
        response_data['message'] = message

    return Response(status=status, data=response_data)

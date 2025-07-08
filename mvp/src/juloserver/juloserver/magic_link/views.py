import logging

from rest_framework.views import APIView
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from juloserver.magic_link.services import *

logger = logging.getLogger(__name__)


class MagicLinkView(APIView):

    permission_classes = (AllowAny,)

    def get(self, _request, token):
        is_valid_token = is_valid_magic_link_token(token)
        if is_valid_token:
            response_data = {'status': 'success'}
        else:
            response_data = {'status': 'failed'}

        return Response(data=response_data, status=200)

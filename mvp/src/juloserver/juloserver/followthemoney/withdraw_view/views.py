from future import standard_library
standard_library.install_aliases()
from builtins import str
import logging
import random
import string
import os
import tempfile
import json
import urllib.request, urllib.parse, urllib.error

from rest_framework.parsers import FormParser
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException

from ..utils import (CustomExceptionHandlerMixin,
                     success_response,
                     server_error_response,
                     not_found_response,
                     general_error_response,
                     convert_timestamp,
                     spoof_text,
                     spoofing_response)
from ..serializers import WithdrawalSerializer
from ..models import LenderWithdrawal
from ..views.application_views import FollowTheMoneyAPIView

from ..constants import BankAccountType

from .services import process_lender_withdrawal_callback_data, new_lender_withdrawal


# Create your views here.
LOGGER = logging.getLogger(__name__)

sentry_client = get_julo_sentry_client()


class BankAccountViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        bank_type = request.query_params.get('type')
        res = []
        lender = getattr(self.request.user, 'lendercurrent', None)
        if not lender:
            return general_error_response('not found lender')
        if bank_type:
            bank_accounts = lender.lenderbankaccount_set.filter(bank_account_type=bank_type)
        else:
            bank_accounts = lender.lenderbankaccount_set.all()
        for bank in bank_accounts:
            res.append({
                "account_name": bank.account_name,
                "account_number": bank.account_number,
                "bank_name": bank.bank_name,
                "bank_account_type": bank.bank_account_type,
            })
        return success_response(res)

class WithdrawViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = WithdrawalSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        lender = getattr(self.request.user, 'lendercurrent', None)
        if not lender:
            return general_error_response('not found lender')
        bank_account = lender.lenderbankaccount_set.filter(
            bank_account_type=BankAccountType.WITHDRAWAL
        ).first()
        if not bank_account:
            return general_error_response('not found bank account')
        try:
            new_lender_withdrawal(lender, data['amount'], bank_account)
        except JuloException as error:
            return general_error_response(str(error))
        return success_response('withdrawal recorded')


class LenderWithdrawalCallbackView(FollowTheMoneyAPIView):
    permission_classes = ()
    authentication_classes = ()
    parser_classes = (FormParser, JSONParser, )
    renderer_classes = (JSONRenderer,)

    def post(self, request):
        data = request.data
        try:
            process_lender_withdrawal_callback_data(data)
        except JuloException as error:
            sentry_client.captureException()
            return general_error_response(str(error))
        return success_response('received callback')

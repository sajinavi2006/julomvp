from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from juloserver.channeling_loan.constants.dbs_constants import DBSChannelingUpdateLoanStatusConst


class DBSAPIKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        api_key = request.META.get(DBSChannelingUpdateLoanStatusConst.HTTP_X_API_KEY)
        if not api_key:
            raise AuthenticationFailed('No API key provided')

        # Check if the API key is valid
        if api_key != settings.DBS_CALLBACK_API_KEY:
            raise AuthenticationFailed('Invalid API key')

        # If the API key is valid, we return a tuple of (user, auth) is (None, None)
        # to indicate successful authentication without associating the request with a specific user
        return None, None

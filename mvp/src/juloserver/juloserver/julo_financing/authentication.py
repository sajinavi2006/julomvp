from typing import Optional

from rest_framework.authentication import BaseAuthentication

from juloserver.julo.models import Customer
from juloserver.julo_financing.services.token_related import JFinancingToken


class FinancingTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        financing_token = request.resolver_match.kwargs.get('financing_token')
        if not financing_token:
            return None

        customer = self.__get_customer_from_token(token=financing_token)
        if not customer:
            return None

        # return a tuple of (user, auth)
        return customer.user, financing_token

    @staticmethod
    def __get_customer_from_token(token: str) -> Optional[Customer]:
        is_valid, token_data = JFinancingToken().is_token_valid(token=token)
        if not is_valid:
            return None

        return Customer.objects.get_or_none(pk=token_data.customer_id)

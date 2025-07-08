import logging

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Partner

from . import get_doku_client
from .exceptions import ExpiredTokenDokuApiError

logger = logging.getLogger(__name__)


class DokuClientWrapper():

    MAX_RETRY = 3

    def __init__(self):
        self._doku_client = self._get_new_client()

    def __getattr__(self, attr):
        def wrapper(*args, **kwargs):
            for _x in range(0, self.MAX_RETRY):
                func = getattr(self._doku_client, attr)
                # Execute the function catching exceptions
                try:
                    return func(*args, **kwargs)
                # Specify here the exceptions you expect
                except ExpiredTokenDokuApiError:
                    self._refresh_token()
            raise JuloException('Exceed max retries of DOKU api')
        return wrapper

    def _get_new_client(self, token=None, systrace=None):
        if token and systrace:
            client = get_doku_client(token, systrace)
        else:
            client = get_doku_client(*self._get_token_from_db())

        return client

    def _get_token_from_db(self):
        doku_partner = Partner.objects.get(name='doku')
        return doku_partner.token, doku_partner.systrace

    def _store_token_to_db(self, new_token, new_systrace):
        doku_partner = Partner.objects.get(name='doku')
        doku_partner.token = new_token
        doku_partner.systrace = new_systrace
        doku_partner.save()

    def _refresh_token(self):
        token, _expires_in, systrace = self._doku_client.get_fresh_token()
        self._store_token_to_db(token, systrace)
        self._doku_client = self._get_new_client(token, systrace)

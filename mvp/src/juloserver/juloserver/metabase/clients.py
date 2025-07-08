from django.conf import settings
import requests  # noqa

from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client


logger = JuloLog(__name__)


def get_metabase_client():
    return MetabaseClient(
        settings.METABASE_BASE_URL,
    )


class MetabaseClient(object):
    def __init__(self, base_url):
        self.base_url = base_url
        self.sentry_client = get_julo_sentry_client()

    def send_request(self, request_type, request_path, data=None, headers=None, timeout=None):
        if timeout:
            request_params = {
                'url': "%s%s" % (self.base_url, request_path),
                'json': data,
                'headers': headers,
                'timeout': (timeout, timeout),
                # For now, make the `connect_timeout` and the `read_timeout` values the same.
                # No need to differentiate their value.
            }
        else:
            request_params = {
                'url': "%s%s" % (self.base_url, request_path),
                'json': data,
                'headers': headers,
            }

        return_response = None
        error_message = None

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)
            try:
                return_response = response.json()
                if return_response and 'errors' in return_response:
                    if len(return_response['errors']) > 0:
                        error_message = return_response['errors']

                if not return_response:
                    logger.error({
                        'action': 'juloserver.metabase.clients.send_request',
                        'error': error_message,
                        'data': data,
                        'request_path': request_params['url']
                    })
            except ValueError:
                error_message = response.text
            response.raise_for_status()
        except Exception as e:
            self.sentry_client.captureException()
            response = str(e)
            exception_type = type(e).__name__

            if not error_message:
                error_message = response

            if exception_type == 'ReadTimeout':
                error_message = exception_type

            logger.error({
                'action': 'juloserver.metabase.clients.send_request',
                'error': response,
                'data': data,
                'request_path': request_params['url']
            })

        return return_response, error_message

    def get_session_token(self):
        data = {
            'username': settings.METABASE_API_USER,
            'password': settings.METABASE_API_PASSWORD,
        }
        url = 'session'

        return self.send_request('post', url, data)

    def get_metabase_data_json(self, card_id, timeout=None):
        response, error = self.get_session_token()

        if error:
            return {}, error

        session_id = response['id']
        headers = {'X-Metabase-Session': session_id}
        url = ('card/{}/query/json'.format(card_id))

        return self.send_request('post', url, None, headers, timeout)

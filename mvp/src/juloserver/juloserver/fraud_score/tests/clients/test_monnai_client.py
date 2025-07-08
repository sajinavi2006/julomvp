import responses
from django.test import (
    TestCase,
    override_settings,
)
from requests.exceptions import HTTPError

from juloserver.fraud_score.clients.monnai_client import (
    NotAuthenticated,
    get_monnai_client,
)


def override_monnai_setting():
    return override_settings(
        MONNAI_AUTH_BASE_URL='https://monnai-auth-url',
        MONNAI_INSIGHT_BASE_URL='https://monnai-insight-url',
        MONNAI_CLIENT_ID='monnai-client-id',
        MONNAI_CLIENT_SECRET='monnai-client-secret',
    )


@override_monnai_setting()
class TestMonnaiAuthAPI(TestCase):
    @responses.activate
    def test_200_success(self):
        monnai_client = get_monnai_client()

        expected_request_data = {
            'client_id': 'monnai-client-id',
            'client_secret': 'monnai-client-secret',
            'grant_type': 'client_credentials',
            'scope': "scope-1 scope-2 scope-3"
        }
        expected_request_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        }
        responses.add(
            'POST',
            url='https://monnai-auth-url/oauth2/token',
            status=200,
            json={
                "access_token": "response-access-token",
                "expires_in": 1234,
                "token_type": "Bearer"
            },
            match=[
                responses.matchers.urlencoded_params_matcher(expected_request_data),
                responses.matchers.header_matcher(expected_request_header),
            ]
        )

        access_token, expire_in_secs = monnai_client.fetch_access_token(
            scopes=['scope-1', 'scope-2', 'scope-3'],
        )

        self.assertEqual('response-access-token', access_token)
        self.assertEqual(1234, expire_in_secs)
        self.assertEqual('response-access-token', monnai_client._access_token)

    @responses.activate
    def test_200_invalid_body(self):
        monnai_client = get_monnai_client()

        responses.add(
            'POST',
            url='https://monnai-auth-url/oauth2/token',
            status=200,
            json={
                "no_access_token": "response-access-token",
                "expires_in": 1234,
            },
        )

        with self.assertRaises(HTTPError) as context:
            monnai_client.fetch_access_token(
                scopes=['scope-1', 'scope-2', 'scope-3'],
            )

        response = context.exception.response
        self.assertEqual('Unexpected body format.', str(context.exception))
        self.assertEqual(200, response.status_code)

    @responses.activate
    def test_400_error(self):
        monnai_client = get_monnai_client()

        responses.add(
            'POST',
            url='https://monnai-auth-url/oauth2/token',
            status=400,
            json={
                "error": "invalid_client"
            },
        )

        with self.assertRaises(HTTPError) as context:
            monnai_client.fetch_access_token(
                scopes=['scope-1', 'scope-2', 'scope-3'],
            )

        response = context.exception.response
        response_json = response.json()
        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_client", response_json.get('error'), response.text)


@override_monnai_setting()
class TestMonnaiFetchInsightAPI(TestCase):
    @responses.activate
    def test_200_success(self):
        monnai_client = get_monnai_client()
        monnai_client.set_access_token('access_token')

        expected_request_data = {
            'packages': ['package-1', 'package-2',],
            'key': 'value',
        }
        expected_request_header = {
            'Authorization': 'Bearer access_token',
            'Content-Type': 'application/vnd.monnai.v1.1+json',
        }
        responses.add(
            'POST',
            url='https://monnai-insight-url/api/insights',
            status=200,
            json={
                "data": {
                    "phone": {},
                    "email": {},
                    "address": None,
                    "name": None,
                    "ip": {},
                    "identity": {},
                    "upi": None,
                    "device": None,
                    "bre": None
                },
                "meta": {},
                "errors": []
            },
            match=[
                responses.matchers.json_params_matcher(expected_request_data),
                responses.matchers.header_matcher(expected_request_header),
            ]
        )

        response = monnai_client.fetch_insight(
            packages=['package-1', 'package-2'],
            payload={'key': 'value'}
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({}, response.json()['data']['phone'])

    @responses.activate
    def test_unauthorized(self):
        monnai_client = get_monnai_client()
        monnai_client.set_access_token('access_token')

        responses.add(
            'POST',
            url='https://monnai-insight-url/api/insights',
            status=401,
        )

        with self.assertRaises(NotAuthenticated) as context:
            monnai_client.fetch_insight(
                packages=['package-1', 'package-2'],
                payload={'key': 'value'}
            )

        exception = context.exception
        self.assertEqual('Unauthorized access', str(exception))
        self.assertIsNotNone(exception.response)
        self.assertEqual(401, exception.response.status_code)

    @responses.activate
    def test_400_response(self):
        monnai_client = get_monnai_client()
        monnai_client.set_access_token('access_token')

        responses.add(
            'POST',
            url='https://monnai-insight-url/api/insights',
            status=400,
            json={
                "data": None,
                "meta": None,
                "errors": [
                    {
                        "package": None,
                        "message": "invalid package name",
                        "code": "INVALID_PACKAGE_NAME",
                        "type": "INVALID_INPUT"
                    }
                ]
            }
        )

        response = monnai_client.fetch_insight(
            packages=['package-1', 'package-2'],
            payload={'key': 'value'}
        )

        response_json = response.json()
        self.assertEqual(400, response.status_code)
        self.assertEqual('invalid package name', response_json['errors'][0]['message'])

    @responses.activate
    def test_no_access_token(self):
        monnai_client = get_monnai_client()

        with self.assertRaises(NotAuthenticated) as context:
            monnai_client.fetch_insight(
                packages=['package-1', 'package-2'],
                payload={'key': 'value'}
            )

        exception = context.exception
        self.assertEqual('Not authenticated', str(exception))
        self.assertIsNone(exception.response)

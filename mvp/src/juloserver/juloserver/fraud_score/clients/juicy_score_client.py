import requests
from django.conf import settings
from requests import Response


def get_juicy_score_client():
    return JuicyScoreClient(
        base_url=settings.JUICY_SCORE_BASE_URL,
        get_score_token=settings.JUICY_SCORE_GET_SCORE_TOKEN,
    )


class JuicyScoreClient:
    """
    Class to communicate with Juicy Score API:
    https://juloprojects.atlassian.net/browse/ANTIFRAUD-115
    Can be found at attachment
    """

    GET_SCORE_ENDPOINT = '/getscore'

    def __init__(self, base_url, get_score_token):
        self.base_url = base_url
        self.get_score_token = get_score_token

    def fetch_get_score_api(self, params: dict) -> Response:
        """
        Fetch get score API result from  Juicy Score.
        Args:
            data (Dict): Parsed Dict data for Params.

        Returns:
            Response: Response object.
        """
        url = self.base_url + self.GET_SCORE_ENDPOINT
        headers = {
            'session': self.get_score_token
        }

        response = requests.get(url, headers=headers, params=params)
        return response

from builtins import object
import logging
import os
import requests
from rest_framework.status import HTTP_204_NO_CONTENT

from django.conf import settings

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from juloserver.julo.exceptions import JuloException

logger = logging.getLogger(__name__)


class GoogleAnalyticsClient(object):
    def __init__(self):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = settings.GOOGLE_ANALYTICS_CREDENTIALS_PATH
        self.firebase_app_id = settings.GOOGLE_ANALYTICS_FIREBASE_APP_ID
        self.api_secret_key = settings.GOOGLE_ANALYTICS_API_SECRET_KEY

    def batch_run_reports(self, batch_request):
        return BetaAnalyticsDataClient().batch_run_reports(batch_request)

    def send_event_to_ga(self, customer, event_name, extra_params={}):
        # extra_params : dict() can pass any extra key value pair with events
        app_instance_id = customer.app_instance_id
        if extra_params.get('credit_limit_balance'):
            extra_params['currency'] = 'IDR'
            extra_params['value'] = extra_params['credit_limit_balance']
            extra_params.pop("credit_limit_balance")

        if app_instance_id:
            customer_id = '{}'.format(customer.id)
            payload = {
                "app_instance_id": app_instance_id,
                "user_id": customer_id,
                "non_personalized_ads": 'false',
                "events": [
                    {
                        "name": event_name,
                        "params": {
                            "user_id": customer_id,
                            "user_id_ga": customer_id,
                            "source": 'backend',
                            "is_logged_in": 'true',
                            **(extra_params or {}),
                        },
                    }
                ],
            }

            firebase_app_id = self.firebase_app_id
            api_secret_key = self.api_secret_key

            url = 'https://www.google-analytics.com/mp/collect?firebase_app_id={}&api_secret={}'.format(  # noqa
                firebase_app_id, api_secret_key
            )
            result = requests.post(url, json=payload)

            logger.info(
                {
                    'task': 'send_event_to_ga',
                    'body': payload,
                    'response': result.content,
                }
            )

            if result.status_code not in [HTTP_204_NO_CONTENT]:
                err_msg = "failed to send {} event to google analytics for customer {}".format(
                    event_name, customer_id
                )

                raise JuloException(err_msg)

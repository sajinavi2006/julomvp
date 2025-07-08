import json
import logging

from django.conf import settings
import requests
from celery import task

logger = logging.getLogger(__name__)


@task(queue="normal")
def submit_rating_task(headers, data) -> None:
    """
    submit_rating_task is a celery task that will submit rating to the rating-service
    Args:
        data (dict), expected keys:
            - customer_id (int): the corresponding customer id that will be checked
            - score (int): the score of the rating
            - description (str): the description of the rating
            - csat_score (int): the csat score of the rating
            - csat_description (str): the csat description of the rating
            - form_type (int): the form type used to submit the rating
    Returns:
        None
    """

    request_body = {
        "rating": data['score'],
        "description": data['description'],
        "csat_description": data['csat_description'],
        "csat_score": data['csat_score'],
        "form_type": data['form_type'],
        "form_source": data['source'],
    }

    response = requests.post(
        settings.RATING_SERVICE_HOST + "/api/v1/inapp/rating",
        headers=headers,
        json=request_body,
    )
    if response.status_code != 200:
        try:
            json_response = response.json()
            logger.error(
                {
                    'action': 'submit_rating_task',
                    'message': 'Hit rating-service API fail',
                    'response': json_response,
                    'customer_id': data['customer_id'],
                }
            )
        except json.JSONDecodeError as e:
            resp = str(e)
            logger.error(
                {
                    'action': 'submit_rating_task',
                    'message': 'Hit rating-service API fail',
                    'response': resp,
                    'customer_id': data['customer_id'],
                }
            )

    return

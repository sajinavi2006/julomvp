import logging
from typing import (
    Dict,
    Union,
)

import requests
import json

from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


class NsqHttpProducer:
    def __init__(self, nsqd_http_url, nsqd_http_port):
        """Initialize the HTTP producer with the NSQD HTTP address."""
        self.nsqd_http_address = f"{nsqd_http_url}:{nsqd_http_port}"

    def publish_message(self, topic: str, message: Union[Dict, str], defer_ms: int = 0):
        """
        Publish a message to a given NSQ topic via HTTP.

        Args:
            topic (str): The NSQ topic to publish the message to.
            message (Union[Dict, str]): The message to publish.
            defer_ms (int, optional): The number of milliseconds to defer before sending a message.
        """
        url = f"{self.nsqd_http_address}/pub?topic={topic}"

        if defer_ms > 0:
            url += f"&defer={defer_ms}"

        try:
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, headers=headers, data=json.dumps(message))

            if response.status_code == 200:
                logger.info(
                    {
                        'action': 'NSQHTTPProducer.publish_message',
                        'message': 'Successfully published message to NSQ server.',
                        'topic': topic,
                        'publish_message': message,
                    }
                )
            else:
                raise Exception(f"Failed to publish message: {response.text}")
        except requests.RequestException as e:
            sentry.captureException()
            raise Exception(f"Error connecting to NSQD: {e}")

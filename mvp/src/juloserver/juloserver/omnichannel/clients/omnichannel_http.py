import json
import logging
import os
from typing import List

import requests
from juloserver.omnichannel.models import (
    OmnichannelCustomer,
    OmnichannelEventTrigger,
    OmnichannelPDSActionLog
)

logger = logging.getLogger(__name__)


class OmnichannelHTTPClient:
    PATH_UPDATE_CUSTOMER = '_/v1/data/customer/'
    PATH_EVENT_TRIGGER = '_/v1/event/trigger/'
    PATH_SEND_PDS_ACTION_LOG = '_/v1/data/customer/pds-comm-result/'

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    def _construct_url(self, path: str) -> str:
        """
        Construct a full URL for a given API path.

        Args:
            path (str): The path to append to the base URL.

        Returns:
            str
        """
        return os.path.join(self.base_url, path.lstrip('/'))

    def _construct_headers(self, custom_headers: dict = {}) -> dict:
        """
        Construct the headers for an API request.

        Args:
            custom_headers (dict, optional): Any additional headers to include in the request.

        Returns:
            dict: The headers for the request.
        """
        headers = {
            'Authorization': f'{self.token}',
            'Content-Type': 'application/json',
        }
        headers.update(custom_headers)
        return headers

    def update_customers(self, customers: List[OmnichannelCustomer]) -> requests.Response:
        """
        Update a list of customers via the Omnichannel API.

        Args:
            customers (List[OmnichannelCustomer]): The customers to update.

        Returns:
            requests.Response: The response from the API.
        """
        url = self._construct_url(self.PATH_UPDATE_CUSTOMER)
        headers = self._construct_headers()

        customers = [customer.to_json_dict() for customer in customers]
        data = json.dumps(customers)

        response = requests.post(
            url,
            data=data,
            headers=headers,
        )
        response.raise_for_status()
        return response

    def send_event_trigger(self, events: List[OmnichannelEventTrigger]) -> requests.Response:

        """
        Send event trigger to the Omnichannel API.

        Args:
            events (List[OmnichannelEventTrigger]): List of events to be triggered.

        Returns:
            requests.Response: The response from the API.
        """
        url = self._construct_url(self.PATH_EVENT_TRIGGER)
        headers = self._construct_headers()

        events = [event.to_json_dict() for event in events]
        data = json.dumps({"events": events})

        response = requests.post(
            url,
            data=data,
            headers=headers,
        )
        response.raise_for_status()
        return response


    def send_pds_action_log(self, action_logs: List[OmnichannelPDSActionLog]) -> requests.Response:

        """
        Send action logs to the Omnichannel API.

        Args:
            action_logs (List[OmnichannelPDSActionLog]): List of PDS communications result.

        Returns:
            requests.Response: The response from the API.
        """
        url = self._construct_url(self.PATH_SEND_PDS_ACTION_LOG)
        headers = self._construct_headers()

        action_logs = [action_log.to_json_dict() for action_log in action_logs]
        data = json.dumps({"pds_action_logs": action_logs})

        response = requests.post(
            url,
            data=data,
            headers=headers,
        )
        response.raise_for_status()
        return response


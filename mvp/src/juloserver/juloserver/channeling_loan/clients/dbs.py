import logging
import requests
from requests import RequestException

from juloserver.channeling_loan.constants.dbs_constants import DBS_API_CONTENT_TYPE
from juloserver.channeling_loan.exceptions import DBSApiError

logger = logging.getLogger(__name__)


class DBSChannelingClient:
    def __init__(self, base_url: str, api_key: str, org_id: str):
        self.base_url = base_url.rstrip('/')  # Remove trailing slash if present
        self.api_key = api_key
        self.org_id = org_id

    def send_loan(
        self,
        loan_id: int,
        x_dbs_uuid: str,
        x_dbs_timestamp: str,
        disbursement_request_body: str,
    ) -> requests.Response:
        """
        Submit loan to DBS Channeling
        :param loan_id: loan id used to log
        :param x_dbs_uuid: unique identifier for each API request
        :param x_dbs_timestamp: date and time of the request-initiated
        :param disbursement_request_body: request body after mapping from loan
        :return: Response object, raise DBSApiError when catch RequestException
        """
        relative_url = '/unsecuredLoans/application'
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'Content-Type': DBS_API_CONTENT_TYPE,
            'X-DBS-ORG_ID': self.org_id,
            'x-api-key': self.api_key,
            'X-DBS-uuid': x_dbs_uuid,
            'X-DBS-timestamp': x_dbs_timestamp,
        }
        base_logger_data = {
            'action': 'DBSChannelingClient.send_loan',
            'loan_id': loan_id,
        }
        try:
            logger.info(
                {
                    **base_logger_data,
                    'message': 'Start to send loan to DBS',
                    'url': url,
                    'headers': headers,
                    'disbursement_request_body': disbursement_request_body,
                }
            )
            return requests.post(url, headers=headers, data=disbursement_request_body)
        except RequestException as error:
            response_status_code = error.response.status_code if error.response else 0
            response_text = error.response.text if error.response else ""
            logger.error(
                {
                    **base_logger_data,
                    'message': 'Failed to send loan to DBS',
                    'error': str(error),
                    'response_status_code': response_status_code,
                    'response': response_text,
                }
            )
            raise DBSApiError(
                message=str(error),
                response_status_code=response_status_code,
                response_text=response_text,
            )

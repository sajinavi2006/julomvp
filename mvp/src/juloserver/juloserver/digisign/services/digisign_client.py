import json
import logging
import requests
from typing import Tuple, Dict, Any

from juloserver.digisign.constants import SigningStatus

logger = logging.getLogger(__name__)

from django.conf import settings


logger = logging.getLogger(__name__)


class DigisignClient:
    REQUEST_TIMEOUT = 10
    REGISTER_URL = '/api/v1/register'
    REGISTER_STATUS_URL = '/api/v1/register/status'
    REGISTER_CALLBACK_URL = '/api/v1/register/callback'
    SIGN_DOCUMENT_URL = '/api/v1/sign'

    def __init__(self):
        self.base_url = settings.NEW_DIGISIGN_BASE_URL

    def get_default_headers(self):
        return {
            'Authorization': settings.NEW_DIGISIGN_TOKEN,
            'Content-Type': 'application/json',
        }

    def make_request(self, method, url, headers=None, *args, **kwargs):
        if headers is None:
            headers = self.get_default_headers()

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=self.REQUEST_TIMEOUT,
                **kwargs
            )
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': 'Request timeout, it took longer than {} sec'.format(self.REQUEST_TIMEOUT)
            }

        resp_data = {'success': False}
        try:
            resp_data.update(response.json())
        except Exception as e:
            logger.error({
                'action': 'DigisignClient.make_request',
                'message': str(e),
            })

        return resp_data

    def register(self, application_id):
        url = self.base_url + self.REGISTER_URL
        return self.make_request('POST', url, json={'application_id': str(application_id)})

    def get_registration_status_code(self, application_id):
        url = self.base_url + self.REGISTER_STATUS_URL
        return self.make_request('GET', url, params={'application_id': str(application_id)})

    def sign_documents(self, request_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Sign multiple documents using the Digisign API.

        Args:
            request_data: Dictionary containing:
                - signer_xid: Unique identifier for the customer
                - file_paths: List of paths to document files
                - document_details: Dictionary containing document metadata

        Returns:
            Tuple of (success: bool, response_data: dict)
        """
        file_paths = request_data['file_paths']
        if not file_paths:
            raise ValueError("No file paths provided")

        url = self.base_url + self.SIGN_DOCUMENT_URL
        headers = {
            'Authorization': settings.NEW_DIGISIGN_TOKEN,
        }

        try:
            # Open the files directly since they're managed externally
            files = [('document_files', open(file_path, 'rb')) for file_path in file_paths]
            payload = {
                'customer_xid': request_data['signer_xid'],
                'document_details': str(json.dumps(request_data['document_details']))
            }

            response = requests.post(
                url,
                headers=headers,
                data=payload,
                files=files,
                timeout=self.REQUEST_TIMEOUT
            )

            if response.status_code != 201:
                logger.error("Failed to sign documents. Status: %d, Response: %s",
                             response.status_code, response.text)
                return False, {'status': SigningStatus.FAILED, 'error': response.text}

            response_data = response.json()
            result = {}
            for item in response_data["data"]["responses"]:
                result[item['digisign_document_id']] = item

            return True, result

        except (requests.RequestException, requests.exceptions.Timeout) as e:
            logger.error("Failed to sign documents, request timeout: %s", str(e))
            return False, {'status': SigningStatus.FAILED, 'error': str(e)}

    def sign_document(self, request_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Sign a single document using the Digisign API.

        Args:
            request_data: Dictionary containing:
                - signer_xid: Unique identifier for the customer
                - file_path: Path to document file
                - document_detail: Dictionary containing document metadata

        Returns:
            Tuple of (success: bool, response_data: dict)
        """
        multi_doc_request = {
            'signer_xid': request_data['signer_xid'],
            'file_paths': [request_data['file_path']],
            'document_details': {
                'documents': [request_data['document_detail']]
            }
        }
        return self.sign_documents(multi_doc_request)

    def get_signature_status(self):
        pass


def get_digisign_client():
    return DigisignClient()

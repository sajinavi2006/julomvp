import json
import logging
from typing import Any, Dict, Tuple

import requests
import os

from django.conf import settings
from django.db import transaction

from juloserver.digisign.constants import RegistrationStatus, SigningStatus
from juloserver.digisign.exceptions import DigitallySignedRegistrationException
from juloserver.digisign.models import DigisignRegistration, DigisignDocument
from juloserver.digisign.services.common_services import is_eligible_for_digisign
from juloserver.julo.models import Application, Loan
from juloserver.partnership.models import PartnershipDocument
from juloserver.digisign.utils import parse_data_signed_document
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.pii_vault.constants import PiiSource
from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from juloserver.partnership.models import PartnershipLoanAdditionalFee

logger = logging.getLogger(__name__)


class PartnershipDigisignClient:
    REQUEST_TIMEOUT = 10
    REGISTER_URL = '/api/v1/register'
    REGISTER_STATUS_URL = '/api/v1/register/status'
    REGISTER_CALLBACK_URL = '/api/v1/register/callback'
    SIGN_DOCUMENT_URL = '/api/v1/sign'
    TOKEN_AUTH = ''

    def __init__(self, product_line=None):
        self.base_url = settings.NEW_DIGISIGN_BASE_URL
        # using token based on product_line application
        if product_line == ProductLineCodes.AXIATA_WEB:
            self.TOKEN_AUTH = settings.PARTNERSHIP_AXIATA_DIGISIGN_TOKEN
        elif product_line == ProductLineCodes.J1:
            self.TOKEN_AUTH = settings.PARTNERSHIP_LEADGEN_STANDARD_PRODUCT_DIGISIGN_TOKEN
        else:
            # If not have product_line raise an error
            raise ValueError("Authorization token must be provided by product_line.")

    def get_default_headers(self):
        return {
            'Authorization': self.TOKEN_AUTH,
            'Content-Type': 'application/json',
        }

    def make_request(self, method, url, headers=None, *args, **kwargs):
        if headers is None:
            headers = self.get_default_headers()

        try:
            response = requests.request(
                method, url, headers=headers, timeout=self.REQUEST_TIMEOUT, **kwargs
            )
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': 'Request timeout, it took longer than {} sec'.format(self.REQUEST_TIMEOUT),
            }

        resp_data = {'success': False}
        try:
            resp_data.update(response.json())
        except Exception as e:
            logger.error(
                {
                    'action': 'DigisignClient.make_request',
                    'message': str(e),
                }
            )

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
            'Authorization': self.TOKEN_AUTH,
        }

        try:
            # Open the files directly since they're managed externally
            files = [('document_files', open(file_path, 'rb')) for file_path in file_paths]
            payload = {
                'customer_xid': request_data['signer_xid'],
                'document_details': str(json.dumps(request_data['document_details'])),
            }

            response = requests.post(
                url, headers=headers, data=payload, files=files, timeout=self.REQUEST_TIMEOUT
            )

            if response.status_code != 201:
                logger.error(
                    "Failed to sign documents. Status: %d, Response: %s",
                    response.status_code,
                    response.text,
                )
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
            'document_details': {'documents': [request_data['document_detail']]},
        }
        return self.sign_documents(multi_doc_request)

    def get_signature_status(self):
        pass

    def get_signature_callback(self):
        pass


def get_partnership_digisign_client(product_line):
    return PartnershipDigisignClient(product_line)


def is_eligible_for_partnership_sign_document(loan):
    is_borrower_sign_exists = PartnershipLoanAdditionalFee.objects.filter(
        loan_id=loan.id, fee_type=ParntershipDigisign.BORROWER_SIGN
    ).exists()
    application = loan.account.get_active_application()
    return (
        is_borrower_sign_exists
        and is_eligible_for_digisign(application)
        and can_make_partnership_digisign(application, force=True)
    )


def can_make_partnership_digisign(application: Application, force: bool = False) -> bool:
    status = partnership_get_registration_status(application)
    if force and status is None:
        try:
            registration = partnership_register_digisign(application)
        except DigitallySignedRegistrationException:
            logger.error(
                {
                    'action': 'can_make_partnership_digisign',
                    'message': 'Application already registered: {}'.format(application.id),
                }
            )
            return False

        if registration:
            status = registration.registration_status

    return status in RegistrationStatus.DONE_STATUS


def partnership_get_registration_status(application: Application) -> str:
    registration = DigisignRegistration.objects.filter(customer_id=application.customer_id).last()

    if registration and registration.registration_status in RegistrationStatus.DONE_STATUS:
        return registration.registration_status

    status_str = None
    product_line_code = application.product_line_code
    client = get_partnership_digisign_client(product_line_code)
    resp_status = client.get_registration_status_code(application.id)

    if resp_status.get('success'):
        data = resp_status.get('data', {})
        status_code = data['registration_status']
        status_str = RegistrationStatus.get_status(status_code)

        if status_str:
            if registration:
                if status_str != registration.registration_status:
                    registration.registration_status = status_str
                    registration.save()
            else:
                DigisignRegistration.objects.create(
                    customer_id=application.customer_id,
                    reference_number=data['reference_number'],
                    registration_status=status_str,
                    error_code=data['error_code'],
                )
    else:
        logger.error(
            {
                'action': 'get_registration_status',
                'message': 'Request is failed',
                'response': resp_status,
            }
        )

    return status_str


def partnership_register_digisign(application: Application) -> DigisignRegistration:
    registration = DigisignRegistration.objects.filter(customer_id=application.customer_id).last()

    if registration:
        raise DigitallySignedRegistrationException()
    product_line_code = application.product_line_code
    client = get_partnership_digisign_client(product_line_code)
    resp_registration = client.register(application.id)
    if resp_registration.get('success'):
        data = resp_registration['data']
        status_str = RegistrationStatus.get_status(data['registration_status'])
        registration = DigisignRegistration.objects.create(
            customer_id=application.customer_id,
            reference_number=data['reference_number'],
            registration_status=status_str,
            error_code=data['error_code'],
        )
    else:
        logger.error(
            {
                'action': 'register_digisign',
                'message': 'Request is failed',
                'response': resp_registration,
            }
        )

    return registration


def partnership_sign_with_digisign(
    digisign_document, signer_xid, file_path, document_detail, product_line_code
):
    """Send document to Digisign for signing."""
    request_data = {
        'signer_xid': str(signer_xid),
        'file_path': file_path,
        'document_detail': document_detail,
    }
    digi_client = get_partnership_digisign_client(product_line_code)
    is_success, response_dict = digi_client.sign_document(request_data)
    if is_success:
        digisign_document_id_req = '{}_{}'.format(
            digisign_document.id, digisign_document.document_type
        )

        return True, response_dict[digisign_document_id_req]
    return False, response_dict


class ParntershipDigisign:
    BORROWER_SIGN = "borrower_sign"
    LENDER_SIGN = "lender_sign"
    JULO_SIGN = "julo_sign"

    def __init__(self, params: dict):
        """
        params example:
        {
            "is_active": true,
            "fee_type": {
                "borrower_sign": {
                    "fee_amount": 500,
                    "charged_to": "borrower"
                },
                "lender_sign": {
                    "fee_amount": 500,
                    "charged_to": "lender"
                },
                "julo_sign": {
                    "fee_amount": 500,
                    "charged_to": "partner"
                },
                "ekyc": {
                    "fee_amount": 500,
                    "charged_to": "borrower"
                }
            }
        }
        """
        self.params = params
        self.charged_to_borrower = 0
        self.borrower_fee = {}
        self.charged_to_lender = 0
        self.lender_fee = {}
        self.charged_to_partner = 0
        self.partner_fee = {}
        self.calculate_charged_amount()

    def calculate_charged_amount(self):
        fee_types = self.params["fee_types"]
        for fee_type, detail in fee_types.items():
            if detail["charged_to"] == PartnershipLoanAdditionalFee.BORROWER:
                self.charged_to_borrower += detail["fee_amount"]
                self.borrower_fee[fee_type] = detail["fee_amount"]
            elif detail["charged_to"] == PartnershipLoanAdditionalFee.LENDER:
                self.charged_to_lender += detail["fee_amount"]
                self.lender_fee[fee_type] = detail["fee_amount"]
            elif detail["charged_to"] == PartnershipLoanAdditionalFee.PARTNER:
                self.charged_to_partner += detail["fee_amount"]
                self.partner_fee[fee_type] = detail["fee_amount"]

    def get_fee_charged_to_borrower(self):
        return self.charged_to_borrower

    def create_partnership_loan_additional_fee(self, loan_id: int):
        partnership_loan_additional_fees = []
        fee_types = self.params["fee_types"]
        for fee_type, detail in fee_types.items():
            partnership_loan_additional_fees.append(
                PartnershipLoanAdditionalFee(
                    loan_id=loan_id,
                    fee_type=fee_type,
                    fee_amount=detail["fee_amount"],
                    charged_to=detail["charged_to"],
                )
            )
        PartnershipLoanAdditionalFee.objects.bulk_create(partnership_loan_additional_fees)


def process_digisign_callback_sign(callback_data):
    from juloserver.digisign.services.digisign_document_services import (
        can_moving_status,
        upload_signed_document_to_oss,
    )

    reference_number = callback_data["reference_number"]
    status = callback_data["status"]
    signed_document = callback_data["signed_document"]
    log_data = {
        "action": "process_callback_digisign",
        "reference_number": reference_number,
        "status": status,
    }
    log_data.update({"message": "callback received"})
    logger.info(log_data)

    try:
        metadata = parse_data_signed_document(signed_document)
    except ValueError:
        err_msg = "Can not parse signed_document data"
        log_data.update({"message": err_msg})
        logger.error(log_data)
        return False, err_msg

    if not metadata.is_pdf:
        err_msg = "Mime type should be application/pdf"
        log_data.update({"message": err_msg})
        logger.error(log_data)
        return False, err_msg

    with transaction.atomic():
        digisign_document = (
            DigisignDocument.objects.select_for_update()
            .filter(reference_number=reference_number)
            .first()
        )
        if not digisign_document:
            err_msg = "digisign_document not found"
            log_data.update({"message": err_msg})
            logger.error(log_data)
            return False, err_msg

        if not can_moving_status(status, digisign_document.signing_status):
            err_msg = "can not move status {} to {}".format(
                digisign_document.signing_status, status
            )
            log_data.update(
                {
                    "based64": callback_data["signed_document"],
                    "message": err_msg,
                }
            )
            logger.error(log_data)
            return False, err_msg

        loan_id = digisign_document.document_source
        loan = Loan.objects.select_for_update().filter(id=loan_id).first()
        if not loan:
            err_msg = "loan not found"
            log_data.update({"message": err_msg})
            logger.error(log_data)
            return False, err_msg

        is_success_digisign = status in SigningStatus.success()
        if is_success_digisign:
            partner = loan.get_application.partner
            detokenize_partner_name = partnership_detokenize_sync_object_model(
                PiiSource.PARTNER,
                partner,
                None,
                ['name'],
            )
            partner_name = detokenize_partner_name.name
            document_type = "{}_skrtp".format(partner_name.lower())
            document_url = upload_signed_document_to_oss(metadata.content, loan.customer_id)
            filename = os.path.basename(document_url)
            PartnershipDocument.objects.create(
                document_source=loan.id,
                filename=filename,
                document_type=document_type,
                url=document_url,
            )
            digisign_document.update_safely(signing_status=status, document_url=document_url)
            log_data.update(
                {
                    "document_url": document_url,
                    "message": "success upload and update digisign_document",
                }
            )
            logger.info(log_data)
        return True, None

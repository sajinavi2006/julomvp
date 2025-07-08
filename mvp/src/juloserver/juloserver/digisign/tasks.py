import logging
import os
import tempfile
import pdfkit
from celery import task
from django.db import transaction
from django.utils import timezone
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.digisign.constants import LoanAgreementSignature, DocumentType, SigningStatus, \
    DEFAULT_WAITING_DIGISIGN_CALLBACK_TIMEOUT_SECONDS, LoanDigisignErrorMessage
from juloserver.digisign.services.digisign_client import get_digisign_client
from juloserver.julo.exceptions import JuloException
from juloserver.digisign.models import DigisignDocument
from juloserver.julo.models import Loan, FeatureSetting
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.services.agreement_related import get_julo_loan_agreement_template
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Application
from juloserver.digisign.services.digisign_register_services import (
    register_digisign
)
from juloserver.digisign.exceptions import (
    DigitallySignedRegistrationException,
)
from juloserver.loan.services.sphp import accept_julo_sphp

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()
digi_client = get_digisign_client()


def initial_record_digisign_document(loan_id):
    return DigisignDocument.objects.create(
        document_source=loan_id,
        document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
        signing_status=SigningStatus.PROCESSING,
    )


def get_agreement_template(loan_id):
    """Get loan agreement template and handle errors."""
    body, *_ = get_julo_loan_agreement_template(loan_id, is_new_digisign=True)
    if not body:
        error_msg = "Template tidak ditemukan."
        logger.error({
            'action_view': 'digisign.tasks.sign_document',
            'data': {'loan_id': loan_id},
            'errors': error_msg
        })
        raise JuloException('SPHP / SKRTP template is not found.')
    return body


def generate_filename(loan):
    """Generate a filename for the PDF document."""
    now = timezone.localtime(timezone.now())
    application = loan.get_application
    return '{}_{}_{}_{}.pdf'.format(
        application.fullname,
        loan.loan_xid,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S")
    )


def get_signature_position(application):
    """Get signature position based on product line."""
    fs = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.DIGISIGN)
    parameters = fs.parameters if fs else {}
    borrower_position = parameters.get("sign_position", {}).get("borrower", {})
    product_line_code = application.product_line.product_line_code
    if product_line_code == ProductLineCodes.JTURBO:
        if "j_turbo" in borrower_position:
            return LoanAgreementSignature.j_turbo(borrower_position["j_turbo"])
        return LoanAgreementSignature.j_turbo()
    elif product_line_code == ProductLineCodes.AXIATA_WEB:
        if "axiata_web" in borrower_position:
            return LoanAgreementSignature.axiata_web(borrower_position["axiata_web"])
        return LoanAgreementSignature.axiata_web()

    if "j1" in borrower_position:
        return LoanAgreementSignature.j1(borrower_position["j1"])
    return LoanAgreementSignature.j1()


def prepare_request_structs(digisign_document, filename, pos_x, pos_y, sign_page):
    """Create document details for signing."""
    digisign_document_id_req = '{}_{}'.format(
        digisign_document.id, digisign_document.document_type
    )
    return {
        "digisign_document_id": digisign_document_id_req,
        "file_name": filename,
        "sign_positions": [
            {
                "pos_x": str(pos_x),
                "pos_y": str(pos_y),
                "sign_page": str(sign_page)
            }
        ]
    }


def generate_pdf(body, filename):
    """Generate PDF from template."""
    file_path = os.path.join(tempfile.gettempdir(), filename)
    pdfkit.from_string(body, file_path)
    return file_path


def sign_with_digisign(digisign_document, signer_xid, file_path, document_detail):
    """Send document to Digisign for signing."""
    request_data = {
        'signer_xid': str(signer_xid),
        'file_path': file_path,
        'document_detail': document_detail
    }
    is_success, response_dict = digi_client.sign_document(request_data)
    if is_success:
        digisign_document_id_req = '{}_{}'.format(
            digisign_document.id, digisign_document.document_type
        )

        return True, response_dict[digisign_document_id_req]
    return False, response_dict


def update_digisign_document(is_success, digisign_document, response_data):
    """Update a document with signing response."""
    update_data = {
        'signing_status': response_data['status']
    }
    if is_success:
        update_data.update({
            'document_token': response_data['document_token'],
            'reference_number': response_data['reference_number'],
        })
    else:
        extra_data = digisign_document.extra_data or {}
        extra_data['error'] = response_data['error']
        update_data['extra_data'] = extra_data

    digisign_document.update_safely(**update_data)


@task(queue="loan_high")
def sign_document(digisign_document_id):
    digisign_document = DigisignDocument.objects.get(pk=digisign_document_id)
    loan = Loan.objects.get(pk=digisign_document.document_source)
    application = loan.account.get_active_application()
    body = get_agreement_template(loan.id)
    filename = generate_filename(loan)
    pos_x, pos_y, sign_page = get_signature_position(application)
    document_detail = prepare_request_structs(digisign_document, filename, pos_x, pos_y, sign_page)
    file_path = generate_pdf(body, filename)
    signer_xid = loan.customer.customer_xid
    try:
        is_request_success, response_data = sign_with_digisign(
            digisign_document, signer_xid, file_path, document_detail
        )
    except Exception as error:
        is_request_success = False
        response_data = {'status': SigningStatus.FAILED, 'error': str(error)}
    finally:
        remove_temporary_file_path(file_path)

    update_digisign_document(is_request_success, digisign_document, response_data)
    if not is_request_success:
        logger.error({
            'action_view': 'digisign.tasks.sign_document',
            'loan_id': loan.id,
            'errors': response_data['error']
        })
        accept_julo_sphp(loan, "JULO", is_success_digisign=False)
        return

    if response_data['status'] == SigningStatus.PROCESSING:
        timeout_seconds = get_waiting_callback_timeout_seconds()
        trigger_waiting_callback_timeout.apply_async(
            (loan.id,), countdown=timeout_seconds
        )
        # if success, we will handle accept_julo_sphp in callback api
        return

    # Handle completion
    accept_julo_sphp(loan, "JULO", is_success_digisign=False)


def get_waiting_callback_timeout_seconds():
    fs = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.DIGISIGN, is_active=True)
    parameters = fs.parameters if fs else {}
    return parameters.get(
        'timeout_seconds', DEFAULT_WAITING_DIGISIGN_CALLBACK_TIMEOUT_SECONDS
    )


def remove_temporary_file_path(file_path):
    if file_path and os.path.exists(file_path):
        os.remove(file_path)


@task(queue="loan_normal")
def trigger_waiting_callback_timeout(loan_id):
    with transaction.atomic():
        digisign_document = DigisignDocument.objects.select_for_update().get(
            document_source=loan_id,
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER
        )
        loan = Loan.objects.select_for_update().get(id=loan_id)
        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            return

        handle_digisign_timeout(loan, digisign_document)


@task(queue='loan_low')
def register_digisign_task(application_id):
    application = Application.objects.get(id=application_id)
    try:
        register_digisign(application)
    except DigitallySignedRegistrationException:
        logger.error({
            'action': 'register_digisign_task',
            'message': 'Application already registered: {}'.format(application_id),
        })
        raise


def handle_digisign_timeout(loan, digisign_document):
    digisign_document.update_safely(
        signing_status=SigningStatus.INTERNAL_TIMEOUT,
        extra_data={'error': LoanDigisignErrorMessage.INTERNAL_CALLBACK_TIMEOUT}
    )
    logger.info({
        'action': 'handle_digisign_timeout',
        'message': 'already moved to status timeout'
    })
    accept_julo_sphp(loan, "JULO", is_success_digisign=False)
    return

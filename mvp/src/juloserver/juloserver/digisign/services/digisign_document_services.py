import logging
import os

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from juloserver.digisign.services.common_services import is_eligible_for_digisign
from juloserver.digisign.services.digisign_register_services import can_make_digisign
from juloserver.digisign.utils import parse_data_signed_document
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import upload_file_as_bytes_to_oss
from juloserver.digisign.constants import SigningStatus, DocumentType
from juloserver.digisign.models import DigisignDocument
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, Loan, Document

logger = logging.getLogger(__name__)


def get_consent_page():
    fs = FeatureSetting.objects.get(feature_name=FeatureNameConst.DIGISIGN)
    parameters = fs.parameters or {}
    return parameters


def is_eligible_for_sign_document(loan):
    application = loan.account.get_active_application()
    return is_eligible_for_digisign(application) and can_make_digisign(application, force=True)


def can_moving_status(request_status, db_status):
    allow_moving_statuses = SigningStatus.allow_moving_statuses()
    available_statuses = allow_moving_statuses.get(db_status, set())
    if request_status in available_statuses:
        return True

    return False


def process_callback_digisign(callback_data):
    reference_number = callback_data["reference_number"]
    status = callback_data["status"]
    signed_document = callback_data["signed_document"]
    log_data = {
        "action": "process_callback_digisign",
        "reference_number": reference_number,
        "status": status,
    }
    try:
        metadata = parse_data_signed_document(signed_document)
    except ValueError:
        return False, "Can not parse signed_document data"

    if not metadata.is_pdf:
        return False, "Mime type should be application/pdf"

    with transaction.atomic():
        digisign_document = DigisignDocument.objects.select_for_update().get(
            reference_number=reference_number
        )
        if not can_moving_status(status, digisign_document.signing_status):
            log_data.update({
                "based64": callback_data["signed_document"],
                "message": "status can not tobe move"
            })
            logger.error(log_data)
            return True, None

        loan_id = digisign_document.document_source
        loan = Loan.objects.select_for_update().get(id=loan_id)
        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            log_data.update({
                "based64": callback_data["signed_document"],
                "message": "status can not tobe move"
            })
            logger.error(log_data)
            log_data['message'] = "Loan already changed by task trigger_waiting_callback_timeout"
            logger.error(log_data)

            return True, None
        is_success_digisign = status in SigningStatus.success()
        if is_success_digisign:
            document_url = upload_signed_document_to_oss(metadata.content, loan.customer_id)
            filename = os.path.basename(document_url)
            Document.objects.create(
                document_source=loan.id,
                filename=filename,
                loan_xid=loan.loan_xid,
                document_type="skrtp_julo",
                url=document_url
            )
            digisign_document.update_safely(signing_status=status, document_url=document_url)
        accept_julo_sphp(loan, "JULO", is_success_digisign)
        return True, None


def upload_signed_document_to_oss(signed_document_bytes, customer_id):
    current_time = timezone.localtime(timezone.now())
    file_name = 'signed_document{}.pdf'.format(current_time.strftime("%Y-%m-%d-%H-%M"))
    document_remote_path = get_remote_path(customer_id, file_name)
    upload_file_as_bytes_to_oss(
        settings.OSS_MEDIA_BUCKET, signed_document_bytes, document_remote_path
    )

    return document_remote_path


def get_remote_path(customer_id: str, file_name: str) -> str:
    """Generate remote path for document storage."""
    return "cust_{}/application_{}/{}".format(
        customer_id,
        DocumentType.LOAN_AGREEMENT_BORROWER,
        file_name
    )


def get_digisign_document_success(loan_id):
    return DigisignDocument.objects.get_or_none(
        document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
        document_source=loan_id,
        signing_status__in=SigningStatus.success()
    )


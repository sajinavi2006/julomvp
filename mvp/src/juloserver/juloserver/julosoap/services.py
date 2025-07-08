import logging
import pytz
from django.utils import timezone

from ..julo.exceptions import JuloException
from ..julo.models import Application
from ..julo.models import PartnerLoan
from ..julo.services import process_application_status_change
from ..julo.statuses import ApplicationStatusCodes

logger = logging.getLogger(__name__)


def store_partner_loan_to_db(data):
    wib = timezone.get_current_timezone_name()
    application = Application.objects.filter(application_xid=int(data['SubmissionID'])).first()
    partner_loan = PartnerLoan.objects.filter(application=application).first()

    if partner_loan is None:
        raise JuloException()

    partner_loan.agreement_number = data['AgreementNo']
    partner_loan.approval_status = data['ApprovalStatus']
    partner_loan.approval_date = pytz.timezone(wib).localize((data['ApprovalDate']))
    partner_loan.loan_amount = loan_amount=data['NTFAmount']

    partner_loan.save()

    logger.info({
        'status': 'updated_partner_loan',
        'partner_loan_id': partner_loan.id,
        'approval_status': partner_loan.approval_status
    })

    if partner_loan.approval_status == 'Approved':
        process_application_status_change(
            application.id, ApplicationStatusCodes.PARTNER_APPROVED,
            change_reason='partner_triggered')
    if partner_loan.approval_status == 'Reject':
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='partner_triggered')
    if partner_loan.approval_status == 'Cancel':
        process_application_status_change(
            application.id, ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            change_reason='partner_triggered')


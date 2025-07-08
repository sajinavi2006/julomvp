from builtins import str
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..julo.application_checklist import application_checklist
from ..julo.clients import get_julo_xendit_client
from ..julo.models import Application
from ..julo.models import ApplicationCheckList
from ..julo.models import Collateral
from ..julo.models import Disbursement
from ..julo.models import DokuTransaction
from ..julo.models import Image
from ..julo.models import Loan
from ..julo.models import PartnerLoan
from ..julo.models import PartnerReferral
from ..julo.models import Payment
from ..julo.models import PaymentEvent
from ..julo.models import PaymentMethod
from ..julo.models import VoiceRecord
from ..julo.models import VirtualAccountSuffix
from ..julo.models import PaybackTransaction
from ..julo.models import KycRequest
from ..julo.utils import post_anaserver
from ..julo.partners import PartnerConstant
from ..julo.statuses import ApplicationStatusCodes
from ..julo.statuses import PaymentStatusCodes
from ..julo.statuses import LoanStatusCodes
from .notifications import notify_failure


logger = logging.getLogger(__name__)


def check_late_fee_applied():
    max_days_pass_due = 5
    late_payments_no_late_fee = list(
        Payment.objects.dpd(max_days_pass_due).filter(late_fee_amount=0)
    )
    if len(late_payments_no_late_fee) > 0:
        text_data = {
            'message': 'Some late payments have no late fee',
            'dpd': max_days_pass_due,
            'payments': [p.id for p in late_payments_no_late_fee],
            'count': len(late_payments_no_late_fee)
        }
        notify_failure(text_data)


def check_paid_amount_is_correct():
    payments = Payment.objects.filter(
        payment_status__status_code__in=PaymentStatusCodes.paid_status_codes())

    inaccurate_payments = []
    for payment in payments:

        first_payment_event = payment.paymentevent_set.all().order_by('cdate').first()
        pes = payment.paymentevent_set.all()

        events_amount = 0
        for pe in pes:
            events_amount += pe.event_payment
        if first_payment_event.event_due_amount != events_amount:
            inaccurate_payments.append(payment)

    if len(inaccurate_payments) > 0:
        text_data = {
            'message': 'Some paid payments have incorrect paid amount',
            'payments': [p.id for p in inaccurate_payments],
            'count': len(inaccurate_payments)
        }
        notify_failure(text_data)


def check_doku_referred_customers_are_properly_linked():
    partner_referrals = PartnerReferral.objects.all().exclude(customer=None)
    inaccurate_partner_referral = []
    inaccurate_partner_in_application = []

    for partner_referral in partner_referrals:
        customer = partner_referral.customer
        applications = customer.application_set.all()
        application_partner = 0

        for application in applications:
            if application.partner != partner_referral.partner:
                inaccurate_partner_in_application.append({
                    'partner_referral': partner_referral.id,
                    'application': application.id
                })
            else:
                application_partner += 1

        incorrect_customer_email = customer.email != partner_referral.cust_email
        incorrect_pre_exist = partner_referral.pre_exist is not False
        incorrect_partner_in_application = application_partner != len(applications)

        if incorrect_customer_email or incorrect_pre_exist or incorrect_partner_in_application:
            inaccurate_partner_referral.append(partner_referral)

    if len(inaccurate_partner_referral) == 0 and len(inaccurate_partner_in_application) == 0:
        return

    text_data = {}
    if len(inaccurate_partner_referral) > 0:
        text_data_1 = {
            'message': 'Some partner referral are not properly linked',
            'partner_referral': [pr.id for pr in inaccurate_partner_referral],
            'count': len(inaccurate_partner_referral)
        }
        text_data['inaccurate_partner_referral_link'] = text_data_1
    if len(inaccurate_partner_in_application) > 0:
        text_data_2 = {
            'message': 'Some applications have incorrect partner',
            'application': [d['application'] for d in inaccurate_partner_in_application],
            'partner_referral': [d['partner_referral'] for d in inaccurate_partner_in_application],
        }
        text_data['incorrect_partner_application'] = text_data_2

    notify_failure(text_data)


def check_resubmission_requested_images():

    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED)

    inaccurate_resubmission_requests = []
    for application in applications:
        images = Image.objects.filter(
            image_source=application.id,
            image_type='signature',
            image_status=Image.RESUBMISSION_REQ)
        voices = VoiceRecord.objects.filter(
            application=application,
            status=VoiceRecord.RESUBMISSION_REQ)

        if len(images) == 0 and len(voices) == 0:
            inaccurate_resubmission_requests.append(application)

    if len(inaccurate_resubmission_requests) > 0:
        text_data = {
            'message': 'Some application in resubmission request have no images nor voice',
            'applications': [application.id for application in inaccurate_resubmission_requests],
            'count': len(inaccurate_resubmission_requests)
        }
        notify_failure(text_data)


def check_doku_payment_are_processed():

    processed_transactions = DokuTransaction.objects.filter(is_processed=True)

    inaccurate_processed_transactions = []
    for transaction in processed_transactions:
        payment_events = PaymentEvent.objects.filter(
            payment_receipt=transaction.transaction_id)
        if len(payment_events) == 0 or len(payment_events) > 1:
            inaccurate_processed_transactions.append(transaction)

    if len(inaccurate_processed_transactions) > 0:
        text_data = {
            'message': 'Some doku transactions in autochecks are not properly processed',
            'transactions': [t.id for t in inaccurate_processed_transactions],
            'count': len(inaccurate_processed_transactions)
        }
        notify_failure(text_data)


def check_assigned_loans_to_vas():

    loans_without_va = []
    loans_active = Loan.objects.filter(
        loan_status_id__lt=LoanStatusCodes.PAID_OFF).exclude(
        loan_status_id__in=LoanStatusCodes.inactive_status()).order_by('-cdate')
    for loan in loans_active:
        va_count = PaymentMethod.objects.filter(loan=loan).count()
        if va_count < 2 and 'julofinance' not in loan.customer.email:
            loans_without_va.append(loan)

    if len(loans_without_va) > 0:
        text_data = {
            'message': 'active loans without VAs',
            'loans': [l.id for l in loans_without_va],
            'count': len(loans_without_va)
        }
        notify_failure(text_data)


def check_no_unprocessed_doku_payments():
    unprocessed_transactions = DokuTransaction.objects.exclude(is_processed=True)
    if len(unprocessed_transactions) > 0:
        text_data = {
            'message': 'Some doku transactions in autochecks are not yet processed',
            'transactions': [t.id for t in unprocessed_transactions],
            'count': len(unprocessed_transactions)
        }
        notify_failure(text_data)


def check_skiptrace_data_generated():

    applications = Application.objects\
        .filter(application_status__status_code__gte=ApplicationStatusCodes.DOCUMENTS_SUBMITTED)\
        .exclude(application_status__status_code__in=ApplicationStatusCodes.graveyards())\
        .order_by('-cdate')\
        .select_related('customer')

    customers_with_applications = set()
    for application in applications:
        customers_with_applications.add(application.customer)

    customers_without_skiptrace = []
    for customer in customers_with_applications:
        if customer.skiptrace_set.all().count() < 3 and 'julofinance' not in customer.email:
            customers_without_skiptrace.append(customer)

    if len(customers_without_skiptrace) > 0:
        text_data = {
            'message': 'Customers with application but without skiptrace',
            'customers': [c.id for c in customers_without_skiptrace],
            'count': len(customers_without_skiptrace)
        }
        for cust in customers_without_skiptrace:
            application_id = Application.objects.filter(customer_id=cust).last().pk
            ana_data = {'application': application_id}
            post_anaserver('/api/etl/v1/skiptrace_create/', json=ana_data)
        notify_failure(text_data)


def check_application_checklist():
    total_application_checklist = len(application_checklist)
    inaccurate_application_checklist = []
    applications = Application.objects.filter(
        application_status__status_code__lt=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
    applications = applications.exclude(
        application_status__status_code__in=ApplicationStatusCodes.graveyards())
    for application in applications:
        application_checklists = ApplicationCheckList.objects.filter(
            application=application).count()
        if application_checklists != total_application_checklist:
            inaccurate_application_checklist.append(application)

    if len(inaccurate_application_checklist) > 0:
        text_data = {
            'message': 'application has inaccurate application_checklist',
            'applications': [a.id for a in inaccurate_application_checklist],
            'count': len(inaccurate_application_checklist)
        }
        notify_failure(text_data)


def check_inaccurate_product_line():
    catched_statuses = (
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
    )
    inaccurate_product_lines = []
    applications = Application.objects.filter(
        application_status_id=catched_statuses)
    for application in applications:
        offer = application.offer_set.first()
        if application.product_line != offer.product.product_line:
            inaccurate_product_lines.append(application.id)

    if len(inaccurate_product_lines) > 0:
        text_data = {
            'message': 'application has inaccurate product line',
            'applications': [a.id for a in inaccurate_product_lines],
            'count': len(inaccurate_product_lines)
        }
        notify_failure(text_data)


def check_agent_in_loan():
    agentless_loans = Loan.objects.filter(agent=None).not_inactive()
    count = agentless_loans.count()
    if count > 0:
        text_data = {
            'message': 'Loans without agent',
            'loans': [loan.id for loan in agentless_loans],
            'count': count
        }
        notify_failure(text_data)


def check_inaccurate_collateral_partner():
    collaterals = Collateral.objects.all()
    inaccurate_collateral_partners = []

    for collateral in collaterals:
        if collateral.partner.name not in PartnerConstant.collateral_partners():
            inaccurate_collateral_partners.append(collateral.application.id)

    if len(inaccurate_collateral_partners) > 0:
        text_data = {
            'message': 'application collateral partner has inaccurate partner',
            'applications': [application_id for application_id in inaccurate_collateral_partners],
            'count': len(inaccurate_collateral_partners)
        }
        notify_failure(text_data)


def check_unsent_application_collateral_partner():
    unsent_partner_loans = PartnerLoan.objects.filter(approval_status="not_sent")
    if len(unsent_partner_loans) > 0:
        text_data = {
            'message': 'applications are failed to sent to collateral partner',
            'applications': [partnerloan.application.id for partnerloan in unsent_partner_loans],
            'count': len(unsent_partner_loans)
        }
        notify_failure(text_data)


def check_application_in_110_has_images():
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.FORM_SUBMITTED).order_by('-cdate')
    customer_with_images = []
    for app in applications:
        if Image.objects.filter(image_source=app.id).count() > 3 and 'julofinance' not in app.email:
            customer_with_images.append(app)

    if len(customer_with_images) > 0:
        text_data = {
            'message': 'applications in 110 that have images',
            'applications': ['%d - %s' % (a.id, a.email) for a in customer_with_images],
            'count': len(customer_with_images)
        }
        notify_failure(text_data)

def check_application_in_105_has_images():
    applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.FORM_PARTIAL).order_by('-cdate')
    customer_with_images = []
    for app in applications:
        if Image.objects.filter(image_source=app.id).count() > 3 and 'julofinance' not in app.email:
            customer_with_images.append(app)

    if len(customer_with_images) > 0:
        text_data = {
            'message': 'applications in 110 that have images',
            'applications': ['%d - %s' % (a.id, a.email) for a in customer_with_images],
            'count': len(customer_with_images)
        }
        notify_failure(text_data)

def check_va_by_loan():
    all_loans = Loan.objects.exclude(loan_status_id=LoanStatusCodes.PAID_OFF)\
        .exclude(loan_status_id__in=LoanStatusCodes.inactive_status()).order_by('id')
    list_data = []
    for loan in all_loans:
        payment_method = loan.paymentmethod_set.first()
        if payment_method:
            va = payment_method.virtual_account
            method_va_suffix = va[len(va) - 10:]
            va_suffix = VirtualAccountSuffix.objects.get_or_none(virtual_account_suffix=method_va_suffix)
            if va_suffix:
                if int(loan.id) != (va_suffix.loan.id):
                    list_data.append(loan)
            else:
                list_data.append(loan)
        else:
            list_data.append(loan)

    if len(list_data) > 0:
        text_data = {
            'message': 'check va by loan',
            'loan': [(a.id) for a in list_data],
            'count': len(list_data)
        }
        notify_failure(text_data)


def check_faspay_transaction_id():
    list_transaction = PaybackTransaction.objects.filter(is_processed=True)
    list_data = []
    for transaction in list_transaction:
        pmt_event = PaymentEvent.objects.get_or_none(payment_receipt=transaction.transaction_id)
        if not pmt_event:
            list_data.append(transaction)

    if len(list_data) > 0:
        text_data = {
            'message': 'faspay transaction not in payment_event',
            'faspay_id': [(a.id) for a in list_data],
            'count': len(list_data)
        }
        notify_failure(text_data)


def check_faspay_status_code():
    list_data = PaybackTransaction.objects.exclude(status_code=2)

    if len(list_data) > 0:
        text_data = {
            'message': 'faspay transaction not sukses',
            'faspay': [(a.id,a.status_desc) for a in list_data],
            'count': len(list_data)
        }
        notify_failure(text_data)


def check_kyc_application():
    list_kyc = KycRequest.objects.all()
    list_data = []
    for kyc in list_kyc:
        if kyc.is_expired and not kyc.is_processed:
            list_data.append(kyc)

    if len(list_data) > 0:
        text_data = {
            'message': 'kyc expired but is_processed nont True',
            'kyc': [(a.id,a.application.id) for a in list_data],
            'count': len(list_data)
        }
        notify_failure(text_data)


def check_pending_disbursements():

    if settings.ENVIRONMENT != 'prod':
        return

    pending_disbursements = []

    disbursements = Disbursement.objects.exclude(disburse_status='COMPLETED').order_by('id')
    for disbursement in disbursements:
        incomplete_duration = timezone.now() - disbursement.cdate
        if incomplete_duration > timedelta(minutes=60):
            pending_disbursements.append(disbursement)

    if len(pending_disbursements) > 0:
        text_data = {
            'message': 'disbursements still pending',
            'disbursements': [
                {
                    'disburse_id': pd.disburse_id,
                    'validation_status': pd.validation_status,
                    'disburse_status': pd.disburse_status,
                    'validated_name': pd.validated_name,
                    'loan_id': pd.loan.id,
                    'loan_disbursement_amount': pd.loan.loan_disbursement_amount,
                    'pending_duration': str(timezone.now() - pd.cdate),
                    'bank_name': pd.loan.application.bank_name,
                    'email': pd.loan.application.email
                }
                for pd in pending_disbursements
            ],
            'count': len(pending_disbursements)
        }
        notify_failure(text_data, channel="#xendit-dev")


def check_xendit_balance():

    if settings.ENVIRONMENT != 'prod':
        return

    xendit_client = get_julo_xendit_client()
    response = xendit_client.get_balance()
    minimum_balance = 10000000
    if response['balance'] <= minimum_balance:
        text_data = {
            'message': 'xendit cash balance low',
            'balance': response['balance']
        }
        notify_failure(text_data, channel="#xendit-dev")

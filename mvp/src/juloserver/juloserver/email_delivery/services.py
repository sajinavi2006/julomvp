from builtins import range
from builtins import next
from builtins import str
import logging
from datetime import date
from typing import (
    Dict,
    Optional,
)

from dateutil.relativedelta import relativedelta
import itertools

from django.utils import timezone
from django.conf import settings

from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.email_delivery.utils import email_status_prioritization
from juloserver.julo.banks import BankCodes
from juloserver.julo.models import (
    Payment,
    PaymentMethodLookup,
    EmailHistory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import get_google_calendar_for_email_reminder
from juloserver.julo.utils import (
    splitAt,
    display_rupiah,
)
from juloserver.loan_refinancing.services.loan_related import \
    get_payments_refinancing_pending_by_dpd
from juloserver.streamlined_communication.services import (
    process_streamlined_comm_without_filter,
    process_streamlined_comm_email_subject,
    process_streamlined_comm_context_for_ptp,
)
from juloserver.moengage.services.data_constructors import (
    construct_user_attributes_for_realtime_basis
)
from juloserver.moengage.constants import EmailStatusType
from juloserver.account_payment.models import AccountPayment
from juloserver.integapiv1.utils import contains_word
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

logger = logging.getLogger(__name__)

JULO_TITLE = "JULO"


# Public interface #############################################################


def create_email_history_for_payment(payment_id, is_account_payment=False):
    if is_account_payment:
        payment_or_account_payment = AccountPayment.objects.get_or_none(pk=payment_id)
        application = payment_or_account_payment.account.application_set.last()

        return EmailHistory.objects.create(account_payment=payment_or_account_payment,
                                           application=application,
                                           customer_id=application.customer_id)
    else:
        payment_or_account_payment = Payment.objects.select_related(
            "loan__application__customer").get(id=payment_id)
        application = payment_or_account_payment.loan.application

        return EmailHistory.objects.create(payment=payment_or_account_payment,
                                           application=application,
                                           customer_id=application.customer_id)


# Callback logic ###############################################################


def parse_callback_from_sendgrid(data):
    """
    Groups SendGrid's callback data by sg_message_id and biggest timestamp

    Args:
        data: SendGrid callback's data.
    """
    def unique_key(d):
        return d["sg_message_id"]

    def order_by(d):
        return -d["timestamp"]

    cleaned_data = [sendgrid_item for sendgrid_item in data if "sg_message_id" in sendgrid_item]
    if len(cleaned_data) < len(data):
        logger.info({
            'message': "Some sendgrid data does not have 'sg_message_id'",
            'action': 'parse_callback_from_sendgrid',
            'module': 'email_delivery',
            'data': data
        })

    sort_func = (
        lambda v: (unique_key(v), order_by(v))) if order_by else unique_key

    groups = itertools.groupby(sorted(cleaned_data, key=sort_func), unique_key)
    return [next(group) for unused_key, group in groups]


# Reminder logic ###############################################################


def get_payment_info_for_email_reminder(payment, streamlined_comm):
    """
    Generate the email content and the email address to be sent to the customer.
    Args:
        payment (Payment|Account_payment):
            The payment object for non PTP. For PTP streamlined, this is AccountPayment.
        streamlined_comm (StreamlinedCommunication): The StreamlinedCommunication object

    Returns:
        email_content (EmailContent): The email content
        email_to (EmailAddress): the customer email address
        email_from (EmailAddress): The sender email address
    """
    # payment => payment_or_account_payment
    is_dpd_plus = False
    today = timezone.localtime(timezone.now()).date()
    today_formated = today.strftime('%d-%b-%Y')

    if (streamlined_comm.dpd or 0) > 0:
        is_dpd_plus = True

    if streamlined_comm.product in ("j1", "jturbo"):
        application = payment.account.application_set.last()
        is_for_j1 = True
    else:
        application = payment.loan.application
        is_for_j1 = False

    is_ptp = False
    if streamlined_comm.ptp is not None:
        is_ptp = True
        context = process_streamlined_comm_context_for_ptp(payment,
                                                           streamlined_comm,
                                                           is_for_j1)
    else:
        loan = payment.loan
        fullname = application.full_name_only
        payment_number = payment.payment_number
        due_amount = payment.due_amount
        due_date = date.strftime(payment.notification_due_date, '%d-%b-%Y')
        bank_name = payment.loan.julo_bank_name
        account_number = " ".join(splitAt(payment.loan.julo_bank_account_number, 4))
        payment_cashback_amount = (0.01 / loan.loan_duration) * loan.loan_amount
        total_cashback_amount = int(payment.cashback_multiplier * payment_cashback_amount)
        bank_code = PaymentMethodLookup.objects.filter(name=payment.loan.julo_bank_name).first()
        if bank_code and bank_code.code != BankCodes.BCA:
            code = bank_code.code
            bank_code_text = "(Kode Bank: " + code + ")"
        else:
            code = ""
            bank_code_text = ""

        context = {
            'fullname': fullname,
            'payment_number': payment_number,
            'due_amount': display_rupiah(due_amount),
            'due_date': due_date,
            'bank_name': bank_name,
            'account_number': account_number,
            'due_date_minus_' + str(streamlined_comm.dpd): today_formated,
            'cashback_multiplier': payment.cashback_multiplier,
            'payment_cashback_amount': display_rupiah(int(payment_cashback_amount)),
            'bank_code': code,
            'bank_code_text': bank_code_text,
            'year': today.strftime('%Y'),
            'base_url': settings.BASE_URL,
            'today': today_formated,
            'first_name_with_title': application.first_name_with_title,
            'display_calendar_reminder': 'none',
            'today_str': date.strftime(timezone.localtime(timezone.now()).date(), '%d %b'),
            'total_cashback_amount': display_rupiah(total_cashback_amount),
            'icon_whatsapp': settings.EMAIL_STATIC_FILE_PATH + 'icon_whatsapp.png',
            'icon_email': settings.EMAIL_STATIC_FILE_PATH + 'icon_email.png',
            'icon_call': settings.EMAIL_STATIC_FILE_PATH + 'icon_call.png',
            'icon_calendar': settings.EMAIL_STATIC_FILE_PATH + 'icon_calendar.png',
            'banner_MTL_dpd_4': settings.EMAIL_STATIC_FILE_PATH + 'banner_MTL_dpd-4.png',
            'banner_MTL_dpd_2': settings.EMAIL_STATIC_FILE_PATH + 'banner_MTL_dpd-2.png',
            'banner_STL_dpd_2': settings.EMAIL_STATIC_FILE_PATH + 'banner_STL_dpd-2.png',
            'banner_MTL_STL_dpd_4': settings.EMAIL_STATIC_FILE_PATH + 'banner_MTL_STL_dpd_4.png',
            'banner_STL_dpd_4': settings.EMAIL_STATIC_FILE_PATH + 'banner_STL_dpd-4.png',
            'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png'
        }

    attachment_dict, content_type, google_url = None, None, None
    product_line_code = application.product_line.product_line_code
    if product_line_code in ProductLineCodes.mtl() \
            or product_line_code == ProductLineCodes.J1 \
            or product_line_code in ProductLineCodes.jturbo():
        attachment_dict, content_type, google_url = \
            get_google_calendar_for_email_reminder(application, is_dpd_plus, is_for_j1, is_ptp)

        context['google_calendar_url'] = google_url

        if attachment_dict:
            context['display_calendar_reminder'] = 'block'

    from juloserver.comms.services.email_service import EmailAddress, EmailContent, EmailAttachment

    email_attachments = []
    if attachment_dict and attachment_dict.get('content'):
        email_attachments.append(
            EmailAttachment.from_base64(
                attachment_dict.get('content'),
                attachment_dict.get('filename'),
                attachment_dict.get('type'),
            )
        )
    msg = process_streamlined_comm_without_filter(streamlined_comm, context)
    subject = process_streamlined_comm_email_subject(streamlined_comm.subject, context)
    email_content = EmailContent.create_html(subject, msg, email_attachments)
    if streamlined_comm.pre_header:
        email_content.add_pre_header(streamlined_comm.pre_header)

    email_to = EmailAddress(application.email if application.email else application.customer.email)
    email_from = EmailAddress("collections@julo.co.id")

    return email_content, email_to, email_from


def get_payment_ids_for_reminders_dpd_plus(payment_queryset, today, days_past_due):
    regular_payment_queryset = payment_queryset.filter(ptp_date__isnull=True)
    regular_payment_ids = list(
        regular_payment_queryset.filter(
            due_date=today - relativedelta(days=days_past_due)).values_list("id", flat=True)
    )
    return regular_payment_ids


def get_payment_ids_for_reminders_dpd_minus(payment_queryset, today, days_before_due):
    regular_payment_queryset = payment_queryset.filter(ptp_date__isnull=True)
    ptp_payments_queryset = payment_queryset.filter(ptp_date__isnull=False)
    regular_payment_ids = list(
        regular_payment_queryset.filter(
            due_date=today + relativedelta(days=days_before_due)).values_list("id", flat=True)
    )
    ptp_payment_ids = list(
        ptp_payments_queryset.filter(
            due_date=today + relativedelta(days=days_before_due)).values_list("id", flat=True)
    )
    all_payment_ids = regular_payment_ids + ptp_payment_ids
    return all_payment_ids


def get_all_payments_for_reminder(today):
    today_minus_4 = today - relativedelta(days=4)
    dpd_exclude = [
        today_minus_4,
    ]
    payments_id_exclude_pending_refinancing = get_payments_refinancing_pending_by_dpd(dpd_exclude)

    payment_queryset = Payment.objects.not_paid_active().filter(
        loan__application__customer__can_notify=True
    ).exclude(id__in=payments_id_exclude_pending_refinancing)
    return payment_queryset


def update_email_details(data: Dict, is_stream=False):
    """
    Updates email data after receiving callback data from MoEngage.

    Args:
        data (Dict): Parsed Dict data from MoEngageStream's callback.
        is_stream (bool): If True, this function is for MoengageStream.
    """
    if not data:
        return

    moengage_stream_status_map = EmailStatusMapping['MoEngageStream']
    # Possibly obsolete logic.
    if not is_stream:
        if data['event_code'] not in list(EmailStatusType.keys()):
            return
        status = EmailStatusType[data['event_code']]
    else:
        if data['event_code'] not in list(moengage_stream_status_map.keys()):
            logger.info({
                'action': 'update_email_details',
                'message': 'Unexpected MoEngageStream event_code detected.',
                'event_code': data['event_code']
            })
        status = moengage_stream_status_map.get(data['event_code'], 'unknown')

    list_account_payment_id = [data['account_payment_id']]
    if data['account_payment_id']:
        flag_account_payment = True
    else:
        flag_account_payment = False
    for i in range(1, 6):
        list_account_payment_id.append(data['account{}_payment_id'.format(i)])
        if data['account{}_payment_id'.format(i)]:
            flag_account_payment = True
    for account_payment_id in list_account_payment_id:
        if not account_payment_id:
            continue
        update_email(data, status, account_payment_id)
    if not flag_account_payment:
        update_email(data, status)


def update_email(data: Dict, status: str, account_payment_id: Optional[int] = None):
    """
    Updates or creates email history based on provided arguments.
    TODO: Unfortunately, PEP8 and typehint clashes so cannot add Union typehint with default value.

    Args:
        data (Dict): A dictionary to find if specific EmailHistory exist.
        status (str): Status for the EmailHistory.
        account_payment_id (int, None): ID of AccountPayment that has the EmailHistory if existed.
    """
    email_history = None

    if data['customer_id']:
        email_history = EmailHistory.objects.filter(
            customer_id=data['customer_id'],
            template_code=data['template_code'],
            to_email=data['to_email'],
            campaign_id=data['campaign_id']).first()

    if not email_history and data['application_id']:
        email_history = EmailHistory.objects.filter(
            application_id=data['application_id'],
            template_code=data['template_code'],
            to_email=data['to_email'],
            campaign_id=data['campaign_id']).first()

    if not email_history:
        email_history = EmailHistory.objects.create(
            customer_id=data['customer_id'],
            application_id=data['application_id'] or None,
            status=status,
            to_email=data['to_email'],
            payment_id=data['payment_id'],
            source=data['event_source'],
            template_code=data['template_code'],
            sg_message_id=None,
            subject=data.get('email_subject'),
            message_content=None,
            cc_email=None,
            partner_id=None,
            lender_id=None,
            account_payment_id=account_payment_id,
            campaign_id=data['campaign_id']
        )
    else:
        current_status = email_history.status
        processed_status = email_status_prioritization(current_status, status)
        email_history.update_safely(status=processed_status)

    # For logging bounce reason
    if status in ('soft_bounce', 'hard_bounce'):
        logger.info({
            'action': 'update_email',
            'message': 'Recording bounce reason for bounced email by MoEngage.',
            'email_history': email_history.id,
            'reason': data.get('reason')
        })


def get_payment_info_for_email_reminder_for_unsent_moengage(account_payment, streamlined_comm):
    """
    Generate the email content and the email address to be sent to the customer.
    Args:
        account_payment (AccountPayment): The account payment object.
        streamlined_comm (StreamlinedCommunication): The streamlined communication object.

    Returns:
        email_content: juloserver.comms.services.EmailContent
        email_to: juloserver.comms.services.EmailAddress
        email_from: juloserver.comms.services.EmailAddress
    """
    from juloserver.account_payment.services.earning_cashback import (
        get_paramters_cashback_new_scheme,
    )

    customer = account_payment.account.customer
    user_attributes = construct_user_attributes_for_realtime_basis(customer)
    application = account_payment.account.application_set.last()

    context = user_attributes['attributes']

    _, cashback_percentage_mapping = get_paramters_cashback_new_scheme()
    cashback_counter = account_payment.account.cashback_counter_for_customer
    cashback_percentage = cashback_percentage_mapping.get(str(cashback_counter))
    context['email_cashback_counter'] = cashback_counter
    context['email_cashback_percentage'] = cashback_percentage
    if 'autodebet' in streamlined_comm.template_code:
        context['full_name'] = customer.fullname
    elif streamlined_comm.template_code in ('j1_email_dpd_+4', 'jturbo_email_dpd_+4'):
        if len(context['first_name'] + context['lastname']) != 0:
            context['full_name'] = context['first_name'] + ' ' + context['lastname']
        else:
            context['full_name'] = "Yang Terhormat"

    if 'j1_email_dpd' in streamlined_comm.template_code:
        order_payment_methods_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
        ).last()

        is_wallet_payment_method = contains_word(
            context.get('va_method_name', '').lower(),
            order_payment_methods_feature.parameters.get('e_wallet_group', [])
            + order_payment_methods_feature.parameters.get('direct_debit_group', []),
        )
        if is_wallet_payment_method:
            context['va_number'] = ''
        is_direct_debit = contains_word(
            context.get('va_method_name', '').lower(),
            order_payment_methods_feature.parameters.get('direct_debit_group', []),
        )
        if is_direct_debit:
            context['va_method_name'] = 'Direct Debit ' + context.get('va_method_name', '')
        context['va_method_name'] = (
            context.get('va_method_name', '').replace(' Biller', '').replace(' Tokenization', '')
        )

    from juloserver.comms.services.email_service import (
        EmailAddress,
        EmailContent,
    )
    msg = process_streamlined_comm_without_filter(streamlined_comm, context)
    subject = process_streamlined_comm_email_subject(streamlined_comm.subject, context)
    email_content = EmailContent.create_html(subject, msg, None)

    email_to = EmailAddress(application.email if application.email else customer.email)
    email_from = EmailAddress("collections@julo.co.id")
    if streamlined_comm.pre_header:
        email_content.add_pre_header(streamlined_comm.pre_header)

    return email_content, email_to, email_from


def email_history_kwargs_for_account_payment(account_payment_id):
    """
    Generate the email history kwargs for account payment.
    Args:
        account_payment_id (integer): The account payment id.
    Returns:
        dict: The email history kwargs for EmailHistory
    """
    from juloserver.moengage.constants import INHOUSE
    account_payment = AccountPayment.objects.get(id=account_payment_id)
    customer = account_payment.account.customer
    application_id = customer.current_application_id
    return dict(
        account_payment_id=account_payment.id,
        application_id=application_id,
        customer_id=customer.id,
        source=INHOUSE,
    )


def email_history_kwargs_for_payment(payment_id):
    """
    Generate the email history kwargs for payment.
    Args:
        payment_id (integer): the payment id
    Returns:
        dict: The email history kwargs for EmailHistory
    """
    from juloserver.moengage.constants import INHOUSE

    payment = Payment.objects.get(id=payment_id)
    customer = payment.loan.customer

    return dict(
        payment_id=payment.id,
        application_id=customer.current_application_id,
        customer_id=customer.id,
        source=INHOUSE,
    )

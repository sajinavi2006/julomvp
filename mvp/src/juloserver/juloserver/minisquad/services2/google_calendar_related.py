import time
from datetime import timedelta
import json
import logging
import os.path
import re
from typing import Tuple, Optional

from celery.task import task
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from django.db import models, transaction

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.minisquad.constants import GoogleCalendar, FeatureNameConst
from juloserver.julo.models import (
    Application,
    FeatureSetting,
    PaymentMethod,
    Customer,
)
from juloserver.minisquad.models import (
    CollectionCalendarsParameter,
    CollectionCalendarsReminder,
    CollectionCalendarsEvent,
    CollectionCalendarsDistributionSender,
)
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from babel.dates import format_date
from babel.numbers import format_number
from google_auth_httplib2 import AuthorizedHttp, httplib2

from juloserver.minisquad.utils import (
    collection_detokenize_sync_primary_object_model_in_bulk,
    collection_detokenize_sync_object_model,
)
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


def get_google_calendar_service(**kwargs):
    dpd = kwargs.get('dpd')
    account_payment_id = kwargs.get('account_payment_id', None)
    timeout = kwargs.get('timeout', 120)
    is_ptp = kwargs.get('is_ptp', False)
    sender_id = kwargs.get('sender_id', None)

    calendar_collection = None
    if not sender_id:
        today = timezone.localtime(timezone.now())
        dpd_object = today + timedelta(days=dpd)
        calendar_collection_qs = (
            CollectionCalendarsEvent.objects.annotate(
                current_usage=models.F('collection_calendars_distribution_sender__current_usage')
            )
            .filter(
                is_ptp=is_ptp,
                event_date=dpd_object,
                collection_calendars_distribution_sender__daily_limit__gt=models.F('current_usage'),
            )
            .exclude(collection_calendars_distribution_sender__status='inactive')
        )

        if account_payment_id:
            calendar_collection_qs = calendar_collection_qs.filter(
                collectioncalendarsreminder__account_payment_id=account_payment_id
            )

        calendar_collection = calendar_collection_qs.last()

        if calendar_collection:
            sender_id = calendar_collection.collection_calendars_distribution_sender_id

    creds, sender = get_google_calendar_token_from_distribution_sender(sender_id)

    if not creds:
        logger.warning(
            {
                'action': 'get_google_calendar_service',
                'timeout': timeout,
                'message': 'Error during build service google calendar',
            }
        )
        get_julo_sentry_client().captureException()
        return None, None, None

    http_calendar = AuthorizedHttp(credentials=creds, http=httplib2.Http(timeout=timeout))
    service = build('calendar', 'v3', http=http_calendar)

    return service, sender, calendar_collection


def check_google_calendar_invitation():
    # Check feature on / off    
    return FeatureSetting.objects.get_or_none(
        feature_name='google_calendar_invitation', is_active=True)


def get_google_calendar_token_from_distribution_sender(
    sender_id: int = None,
) -> Tuple[Optional[Credentials], Optional[CollectionCalendarsDistributionSender]]:
    sender_qs = CollectionCalendarsDistributionSender.objects.exclude(status='inactive').filter(
        daily_limit__gt=models.F('current_usage')
    )

    sender = sender_qs.first()
    if sender_id:
        sender_by_id = sender_qs.filter(id=sender_id).first()
        sender = sender_by_id if sender_by_id else sender

    if not sender:
        today = timezone.localtime(timezone.now())
        yesterday = (today - timedelta(days=1)).replace(hour=23, minute=59, second=59)
        sender = sender_qs.filter(udate__lte=yesterday).first()
        if not sender:
            logger.info(
                {
                    "action": "get_google_calendar_token_from_distribution_sender",
                    "message": "there is no distribution sender available",
                }
            )
            return None, None
        with transaction.atomic():
            sender.update_safely(current_usage=0)

    # handle limit 100 every 5 minute
    if sender.current_usage > 0 and sender.current_usage % 100 is 0:
        logger.info(
            {
                "action": "get_google_calendar_token_from_distribution_sender",
                "message": "account {} reaches limit 100 per 5 minutes, must wait for 5 minutes first".format(
                    sender.email
                ),
            }
        )
        time.sleep(300)

    creds = Credentials.from_authorized_user_info(sender.token, settings.GOOGLE_CALENDAR_SCOPES)
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with transaction.atomic():
            sender.update_safely(token=json.loads(creds.to_json()))

    return creds, sender


def get_google_calendar_token():
    token_file_dir = settings.GOOGLE_CALENDAR_TOKEN_DIR
    token_file_name = 'token.json'
    token_file_path = os.path.join(token_file_dir, token_file_name)

    token_from_infra = settings.GOOGLE_CALENDAR_TOKEN

    # checking file token.json
    if not os.path.exists(token_file_path) or os.path.getsize(token_file_path) <= 0:
        # process add token
        token_file = open(token_file_path, "w")
        token_file.write(token_from_infra)
        token_file.close()

    with open(token_file_path) as token_file:
        token_str = token_file.read()
        token = eval(token_str)

    creds = Credentials.from_authorized_user_info(token, settings.GOOGLE_CALENDAR_SCOPES)

    # check creds and is valid
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.GOOGLE_CALENDAR_CREDENTIALS_PATH, settings.GOOGLE_CALENDAR_SCOPES)
            creds = flow.console()

        with open(token_file_path, 'w') as token:
            token.write(creds.to_json())

    return creds


def mapping_data_google_calendar_event(
    account_payments, parameter, dpd, action_log, service, sender, calendar_collection, is_ptp=False
):
    google_calendar_invitation = check_google_calendar_invitation()

    if not google_calendar_invitation:
        logger.warning(
            {
                'action': 'mapping_data_google_calendar_event',
                'message': 'google calendar feature setting inactive',
            }
        )
        return

    google_calendar_parameter = (
        google_calendar_invitation.parameters if google_calendar_invitation.parameters else dict()
    )

    max_participants = google_calendar_parameter.get('max_participants')
    max_participants = max_participants if max_participants else GoogleCalendar.MAX_PARTICIPANTS

    fs_detokenized = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_IN_BULK_DETOKENIZED_METHOD, is_active=True
    ).last()
    max_detokenized_row = 100
    if fs_detokenized:
        max_detokenized_row = fs_detokenized.parameters.get('detokenize_row', 100)

    account_ids_list = list(account_payments.values_list('account_id', flat=True))
    customers = Customer.objects.filter(account__id__in=account_ids_list)
    paginator = Paginator(customers, max_detokenized_row)
    email_list = []
    for page_number in paginator.page_range:
        page = paginator.page(page_number)
        detokenized_customers = collection_detokenize_sync_primary_object_model_in_bulk(
            PiiSource.CUSTOMER, page.object_list, ['email']
        )

        email_list.extend([{'email': ns.email} for ns in detokenized_customers.values()])

    if not len(email_list):
        return

    new_event = {
        'summary': parameter.summary,
        'description': parameter.description,
        'params': {
            'sendNotifications': True,
        },
        'start': {
            'dateTime': '{year}-{month}-{day}T12:00:00+07:00'.
            format(year=dpd.year, month=dpd.month, day=dpd.day),
            'timeZone': 'Asia/Jakarta',
        },
        'end': {
            'dateTime': '{year}-{month}-{day}T13:00:00+07:00'.
            format(year=dpd.year, month=dpd.month, day=dpd.day),
            'timeZone': 'Asia/Jakarta',
        },
        'attendees': email_list,
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 5 * 60},
                {'method': 'popup', 'minutes': 10},
            ],
        },
        'visibility': "private",
        'guestsCanSeeOtherGuests': False
    }

    total_service_use = 0
    total_participants = calendar_collection.total_participants if calendar_collection else 0
    total_participants += len(email_list)

    if is_ptp:
        ptp_calendar_cleansing.delay(account_payments[0])
    if not calendar_collection or total_participants > max_participants:
        event = sent_google_calendar_service(service, 'insert', '', new_event)
        if not event:
            logger.warning(
                {
                    'action': "{} insert_event".format(action_log),
                    'account_payments': account_payments,
                    'message': 'Error during build service google calendar',
                }
            )
            return

        info_data = {"action": "insert_event"}
        total_service_use += 1
    else:
        old_event = sent_google_calendar_service(
            service, 'get', str(calendar_collection.google_calendar_event_id), None
        )
        if not old_event:
            logger.warning(
                {
                    'action': "{} update_event".format(action_log),
                    'account_payments': account_payments,
                    'message': 'Error during build service google calendar',
                }
            )
            return

        total_service_use += 1
        if old_event.get('status') != 'cancelled':
            old_event['attendees'] += email_list
            event = sent_google_calendar_service(
                service,
                'update',
                str(calendar_collection.google_calendar_event_id),
                old_event,
            )

            info_data = {
                "action": "update_event",
                "old_event_id": old_event.get('id'),
                "old_response": old_event,
            }
            total_service_use += 1
        else:
            event = sent_google_calendar_service(service, 'insert', '', new_event)
            if not event:
                logger.warning(
                    {
                        'action': "{} insert_event2".format(action_log),
                        'account_payments': account_payments,
                        'message': 'Error during build service google calendar',
                    }
                )
                return

            info_data = {"action": "insert_event2"}
            total_service_use += 1
            for data in event['attendees']:
                data.pop('responseStatus', None)

    event_id = event.get('id')
    event_htmllink = event.get('htmlLink')

    with transaction.atomic():
        collection_calendars_event = create_or_update_collection_calendars_event(
            event_id, sender, dpd, event['attendees'], is_ptp
        )

        sender.update_safely(current_usage=models.F('current_usage') + total_service_use)

        google_calendar_event_list = []
        for account_payment in account_payments:
            collection_calendar = CollectionCalendarsReminder.objects.create(
                account_payment_id=account_payment.id,
                collection_calendars_event_id=collection_calendars_event.id,
                is_ptp=is_ptp,
            )
            google_calendar_event_list.append(collection_calendar.id)

    logger.info(
        {
            **info_data,
            "event_id": event_id,
            "response": event,
            "google_calendar_event_list": google_calendar_event_list,
            "email_list": email_list,
        }
    )

    logger.info({"action": action_log, "event_id": event_id, "response": event_htmllink})


@task(queue='collection_normal')
def ptp_calendar_cleansing(account_payment):
    today = timezone.localtime(timezone.now())
    is_paid = True if account_payment.due_amount == 0 else False
    fetch_old_cce = (
        CollectionCalendarsEvent.objects.annotate(
            current_usage=models.F('collection_calendars_distribution_sender__current_usage')
        )
        .filter(
            event_date__gt=today,
            collectioncalendarsreminder__account_payment=account_payment,
            collection_calendars_distribution_sender__daily_limit__gt=models.F('current_usage'),
        )
        .exclude(collection_calendars_distribution_sender__status='inactive')
    ).all()

    if not fetch_old_cce:
        return

    previous_sender_id = None
    service = None
    sender = None

    detokenized_customer_email = collection_detokenize_sync_object_model(
        PiiSource.CUSTOMER,
        account_payment.account.customer,
        account_payment.account.customer.customer_xid,
        ['email'],
    )
    email = detokenized_customer_email.email
    total_service_use = 0
    for cce in fetch_old_cce:
        if cce.collection_calendars_distribution_sender_id != previous_sender_id:
            service, sender, _ = get_google_calendar_service(
                sender_id=cce.collection_calendars_distribution_sender_id
            )
            previous_sender_id = cce.collection_calendars_distribution_sender_id

        event = sent_google_calendar_service(
            service, 'get', str(cce.google_calendar_event_id), None
        )
        if not event:
            return

        total_service_use += 1
        if event.get('status') != 'cancelled' and 'attendees' in event:
            event['attendees'] = list(
                filter(
                    lambda item: item['email'] != email,
                    event['attendees'],
                )
            )
            sent_google_calendar_service(
                service, 'update', str(cce.google_calendar_event_id), event
            )
            total_service_use += 1

            with transaction.atomic():
                cce.update_safely(
                    collection_calendars_distribution_sender=sender,
                    total_participants=len(event['attendees']),
                )

                CollectionCalendarsReminder.objects.filter(
                    account_payment=account_payment,
                    collection_calendars_event=cce,
                ).update(is_paid=is_paid, collection_calendars_event=None)

        with transaction.atomic():
            sender.update_safely(current_usage=models.F('current_usage') + total_service_use)


# mapping_data_google_calendar_single is deprecated function
def mapping_data_google_calendar_single(
    account_payment, dpd, action_log, service, sender, calendar_collection, is_ptp=False
):
    # for account_payment in account_payments:
    parameter = custom_calendar_parameter(account_payment, is_ptp)

    if not parameter:
        logger.error({
            'action': action_log,
            'error': 'Single content parameter not found.'
        })
        raise Exception('Single content parameter not found.')

    email = {'email': account_payment.account.customer.email}
    new_event = {
        'summary': parameter['summary'],
        'description': parameter['description'],
        'params': {
            'sendNotifications': True,
        },
        'start': {
            'dateTime': '{year}-{month}-{day}T12:00:00+07:00'.
            format(year=dpd.year, month=dpd.month, day=dpd.day),
            'timeZone': 'Asia/Jakarta',
        },
        'end': {
            'dateTime': '{year}-{month}-{day}T13:00:00+07:00'.
            format(year=dpd.year, month=dpd.month, day=dpd.day),
            'timeZone': 'Asia/Jakarta',
        },
        'attendees': [email],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 5 * 60},
                {'method': 'popup', 'minutes': 10},
            ],
        },
        'visibility': "private",
        'guestsCanSeeOtherGuests': False
    }

    if is_ptp:
        ptp_calendar_cleansing.delay(account_payment)
    total_service_use = 0
    event = None
    if not calendar_collection:
        event = sent_google_calendar_service(service, 'insert', '', new_event)
        if not event:
            logger.warning(
                {
                    'action': "{} insert_event".format(action_log),
                    'account_payments_id': account_payment.id,
                    'message': 'Error during build service google calendar',
                }
            )
            return
        total_service_use += 1
    else:
        old_event = sent_google_calendar_service(
            service, 'get', str(calendar_collection.google_calendar_event_id), new_event
        )
        if not old_event:
            logger.warning(
                {
                    'action': "{} update_event".format(action_log),
                    'account_payments_id': account_payment.id,
                    'message': 'Error during build service google calendar',
                }
            )
            return

        total_service_use += 1
        if old_event.get('status') == 'cancelled':
            event = sent_google_calendar_service(service, 'insert', '', new_event)
            total_service_use += 1

    with transaction.atomic():
        collection_calendars_event = create_or_update_collection_calendars_event(
            event.get('id'), sender, dpd, new_event['attendees'], is_ptp
        )

        sender.update_safely(current_usage=models.F('current_usage') + total_service_use)

        CollectionCalendarsReminder.objects.create(
            account_payment=account_payment,
            collection_calendars_event=collection_calendars_event,
            method='insert',
            status_code=200,
            is_single_event=True,
        )

    logger.info(
        {
            "action": action_log,
            "event_id": new_event.get('id'),
            "response": new_event.get('htmlLink'),
            "message": "google calendar created",
        }
    )


def custom_calendar_parameter(account_payment, is_ptp):
    customer_data = account_payment.account.customer
    payment_method = PaymentMethod.objects.get_or_none(customer=customer_data, is_primary=True)
    application_data = Application.objects.filter(customer=customer_data).last()
    parameter = {}

    if application_data.fullname:
        fullname = application_data.fullname
    elif customer_data.fullname:
        fullname = customer_data.fullname
    else:
        fullname = ''

    if fullname:
        first_name = fullname.split()[0]
    else:
        first_name = ''

    if application_data.gender:
        gender = 'Bapak' if application_data.gender == 'Pria' else 'Ibu'
    elif customer_data.gender:
        gender = 'Bapak' if customer_data.gender == 'Pria' else 'Ibu'
    else:
        gender = ''

    data = {
        'fullname': fullname,
        'first_name': first_name,
        'primary_va_name': payment_method.payment_method_name,
        'primary_va_number': payment_method.virtual_account,
        'due_date': format_date(account_payment.due_date, 'd MMM yyyy', locale='id_ID'),
        'due_amount': format_number(account_payment.due_amount, locale='id_ID'),
        'greet': gender,
        'ptp_date': format_date(account_payment.ptp_date, 'd MMM yyyy', locale='id_ID'),
        'ptp_amount': format_number(account_payment.ptp_amount, locale='id_ID'),
    }

    calendar_parameter_data = CollectionCalendarsParameter.objects.filter(
        is_active=True, is_single_parameter=True, is_ptp_parameter=is_ptp).last()

    if not calendar_parameter_data:
        return None

    parameter['summary'] = extract_words(data, calendar_parameter_data.summary)
    parameter['description'] = extract_words(data, calendar_parameter_data.description)
    return parameter


def extract_words(data, parameter):
    return re.sub(r'{{(.*?)}}', lambda x: str(data.get(x.group(1), x.group(0))), parameter)


def sent_google_calendar_service(service, method: str, event_id: str, body: dict = None):
    try:
        if not service:
            return

        if method in ('get', 'update', 'insert'):
            if method == 'update':
                event = (
                    service.events()
                    .update(calendarId='primary', eventId=event_id, body=body)
                    .execute()
                )
            elif method == 'insert':
                event = (
                    service.events()
                    .insert(calendarId='primary', body=body, sendUpdates='all')
                    .execute()
                )
            else:
                event = service.events().get(calendarId='primary', eventId=event_id).execute()

            return event
    except Exception as error:
        raise error


def create_or_update_collection_calendars_event(
    google_event_id: str, sender: CollectionCalendarsDistributionSender, dpd, attendees, is_ptp
) -> CollectionCalendarsEvent:
    collection_calendars_event, created = CollectionCalendarsEvent.objects.get_or_create(
        google_calendar_event_id=google_event_id
    )
    collection_calendars_event.update_safely(
        collection_calendars_distribution_sender=sender,
        is_ptp=is_ptp,
        event_date=dpd,
        total_participants=len(attendees),
    )

    return collection_calendars_event

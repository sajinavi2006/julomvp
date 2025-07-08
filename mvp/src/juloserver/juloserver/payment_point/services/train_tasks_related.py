import logging
import pdfkit
import tempfile
import os

from babel.dates import format_date, format_datetime
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string

from juloserver.julo.constants import EmailDeliveryAddress
from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_julo_email_client,
)
from juloserver.julo.models import (
    Document,
    EmailHistory,
)
from juloserver.julo.services import get_pdf_content_from_html
from juloserver.julo.tasks import upload_document

from juloserver.loan.utils import get_default_pdf_options

from juloserver.payment_point.utils import get_train_duration

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def get_passanger_seat(train_transaction):
    passengers = []
    for train_passenger in train_transaction.trainpassanger_set.order_by("number"):
        passenger = train_passenger.passanger
        if passenger.passanger_type == 'adult':
            passenger_type = 'Dewasa'
        else:
            passenger_type = 'Bayi'

        passengers.append(
            {
                "number": train_passenger.number,
                "type": passenger_type,
                "title": passenger.title,
                "name": passenger.name,
                "identity_number": passenger.identity_number,
                "seat": {
                    "wagon": train_passenger.wagon,
                    "row": train_passenger.row,
                    "column": train_passenger.column,
                },
            }
        )

    return passengers


def get_eticket_template(train_transaction, template):
    if not train_transaction:
        raise Exception

    image_url = settings.STATIC_ALICLOUD_BUCKET_URL + 'train_ticket/'

    depart_station = train_transaction.depart_station
    destination_station = train_transaction.destination_station

    passengers = get_passanger_seat(train_transaction)

    train_duration = get_train_duration(train_transaction.duration)

    schedule = {
        'date': format_date(
            timezone.localtime(train_transaction.departure_datetime), format='full', locale='id_ID'
        ),
        'departure_date': format_date(
            timezone.localtime(train_transaction.departure_datetime), "d MMM yyyy", locale='id_ID'
        ),
        'departure_time': format_datetime(
            timezone.localtime(train_transaction.departure_datetime), "HH:mm", locale="id_ID"
        ),
        'arrival_date': format_date(
            timezone.localtime(timezone.localtime(train_transaction.arrival_datetime)),
            "d MMM yyyy",
            locale='id_ID',
        ),
        'arrival_time': format_datetime(
            timezone.localtime(train_transaction.arrival_datetime), "HH:mm", locale="id_ID"
        ),
    }

    i = 1
    for passenger in passengers:
        passenger['index'] = i
        if i % 2 == 0:
            passenger['passenger_detail_class'] = 'passenger-body2'
        else:
            passenger['passenger_detail_class'] = 'passenger-body'
        i += 1

    context = {
        'image_url': image_url,
        'train_transaction': train_transaction,
        'train_duration': train_duration,
        'depart_station': depart_station,
        'destination_station': destination_station,
        'passengers': passengers,
        'schedule': schedule,
    }
    return render_to_string(template, context=context)


def generate_eticket(train_transaction):
    if not train_transaction:
        raise Exception

    template = get_eticket_template(
        train_transaction,
        settings.BASE_DIR + '/juloserver/payment_point/templates/train_ticket_pdf.html',
    )

    loan = train_transaction.sepulsa_transaction.loan
    filename = 'eticket_{}{}.pdf'.format(train_transaction.booking_code, loan.loan_xid)
    local_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        pdfkit.from_string(template, local_path, options=get_default_pdf_options(zoom=1.5))
    except Exception as e:
        logger.info({'action': 'generate_eticket', 'error': str(e)})
        sentry_client.captureException()
        raise "Failed to generate PDF"

    document = Document.objects.create(
        document_source=loan.id,
        document_type='train_ticket',
        filename=filename,
        loan_xid=loan.loan_xid,
    )

    upload_document(document.id, local_path, is_loan=True)


def get_eticket_attachment(document, train_transaction):
    template = get_eticket_template(
        train_transaction,
        settings.BASE_DIR + '/juloserver/payment_point/templates/train_ticket_pdf.html',
    )
    filename = document.filename
    pdf_content = get_pdf_content_from_html(template, filename)
    attachment_dict = {"content": pdf_content, "filename": filename, "type": "application/pdf"}

    return attachment_dict


def send_eticket_email(train_transaction):
    if not train_transaction:
        raise Exception

    email_client = get_julo_email_client()
    template = get_eticket_template(
        train_transaction,
        settings.BASE_DIR + '/juloserver/payment_point/templates/train_ticket.html',
    )
    loan = train_transaction.sepulsa_transaction.loan
    account = loan.account
    application = account.get_active_application()
    customer = account.customer
    document = Document.objects.filter(document_source=loan.id, document_type='train_ticket').last()
    file_attachment = get_eticket_attachment(document, train_transaction)

    email_to = train_transaction.account_email

    subject = "Pembelian Tiket Kereta di JULO"
    status, body, headers = email_client.send_email(
        subject,
        template,
        email_to,
        attachment_dict=file_attachment,
        email_from=EmailDeliveryAddress.CS_JULO,
        name_from='JULO',
        content_type="text/html",
    )

    template_code = 'eticket_train_template'
    logger.info({'action': 'send_eticket_email', 'email': email_to, 'template': template_code})

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=email_to,
        subject=subject,
        application=application,
        message_content=template,
        template_code=template_code,
    )

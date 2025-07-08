from celery import task
from django.db import transaction

import tempfile
import logging
import os
from datetime import date
from xhtml2pdf import pisa
from juloserver.credit_card.models import (
    CreditCardApplication,
    CreditCardApplicationHistory,
    CreditCardMobileContentSetting,
    CreditCardStatus,
    CreditCard,
    CreditCardApplicationNote,
)

from juloserver.account.models import Account
from juloserver.julo.tasks import upload_document
from juloserver.julo.models import (
    Customer,
    Document,
    FeatureSetting,
)
from django.contrib.auth.models import User
from juloserver.loan_refinancing.templatetags.format_date import format_date_to_locale_format
from juloserver.julo.constants import FeatureNameConst
from juloserver.credit_card.constants import CreditCardStatusConstant
from juloserver.julo.exceptions import JuloException

logger = logging.getLogger(__name__)


@task(name='update_card_application_note')
@transaction.atomic
def update_card_application_note(credit_card_application_id, user_id,
                                 note_text, credit_card_history_id):
    credit_card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id).last()
    credit_card_history = CreditCardApplicationHistory.objects.filter(
        pk=credit_card_history_id).last()
    user = User.objects.filter(pk=user_id).last()
    credit_card_application_note = CreditCardApplicationNote.objects.create(
        note_text=note_text,
        added_by=user,
        credit_card_application=credit_card_application,
        credit_card_application_history=credit_card_history
    )
    credit_card_application_note.update_safely()


@task(name='generate_customer_tnc_agreement')
@transaction.atomic
def generate_customer_tnc_agreement(customer_id):
    mobile_content_setting = CreditCardMobileContentSetting.objects \
        .filter(content_name='Credit Card TNC', is_active=True) \
        .last()

    if not mobile_content_setting:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {},
            'errors': 'TNC Setting tidak ditemukan'
        })
        return

    if len(mobile_content_setting.content) == 0:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {},
            'errors': 'Body content tidak ada'
        })
        return

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDIT_CARD,
        is_active=True).last()

    if not feature_setting:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {},
            'errors': 'Feature Setting tidak ditemukan'
        })
        return

    parameters = feature_setting.parameters
    customer_name = parameters['customer_name']
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {},
            'errors': 'Customer tidak ditemukan'
        })
        return

    if customer.fullname:
        customer_name = customer.fullname

    today = date.today()
    date_now = format_date_to_locale_format(today)

    account = Account.objects \
        .select_related('customer') \
        .filter(customer=customer_id) \
        .last()
    if not account:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {'customer_id': customer_id},
            'errors': 'Account tidak ditemukan'
        })
        return

    application = account.last_application
    if not application:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {'application_id': application.id},
            'errors': 'Application tidak ditemukan'
        })
        return

    tnc_content = mobile_content_setting.content
    try:
        tnc_content_replaced = tnc_content.format(
            card_name=parameters['card_name'],
            customer_name=customer_name,
            julo_email=parameters['julo_email'],
            current_date=date_now
        )

        template = parameters['doc_template']

        body = template.format(
            card_name=parameters['card_name'],
            customer_id=customer_id,
            credit_card_tnc=tnc_content_replaced
        )

        temp_dir = tempfile.gettempdir()

        credit_card_counter = 1

        credit_card_docs = Document.objects.filter(
            document_source=application.id
        ).count()

        if credit_card_docs:
            credit_card_counter += credit_card_docs

        filename = 'perjanjian_credit_card-{}-{}.pdf'.format(
            customer_id,
            credit_card_counter
        )
        file_path = os.path.join(temp_dir, filename)

        file = open(file_path, "w+b")
        pdf = pisa.CreatePDF(body, dest=file, encoding="UTF-8")
        file.close()

        if pdf.err:
            logger.error({
                'action_view': 'Credit Card - generate_customer_tnc_agreement',
                'data': {'customer_id': customer.id},
                'errors': "Failed to create PDF"
            })
            return

        lla = Document.objects.create(document_source=application.id,
                                      document_type='credit_card_tnc',
                                      filename=filename,
                                      application_xid=application.application_xid)

        logger.info({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {'customer_id': customer.id, 'document_id': lla.id},
            'message': "success create PDF"
        })

        upload_document(lla.id, file_path)

    except Exception as e:
        logger.error({
            'action_view': 'Credit Card - generate_customer_tnc_agreement',
            'data': {'customer_id': customer.id},
            'errors': str(e)
        })
        JuloException(e)


@task(name='upload_credit_card', queue='loan_normal')
def upload_credit_card(card_data: list) -> None:
    credit_card_status = CreditCardStatus.objects \
        .filter(description=CreditCardStatusConstant.UNASSIGNED).last()
    card_numbers = [item['card_number'] for item in card_data]
    card_numbers_already_exists = CreditCard.objects.filter(
        card_number__in=card_numbers
    ).values_list('card_number', flat=True)
    card_data_filtered = card_data
    if card_numbers_already_exists:
        card_data_filtered = list(
            filter(lambda item: item['card_number'] not in card_numbers_already_exists,
                   card_data)
        )
    credit_card_list = []
    for card_datum in card_data_filtered:
        credit_card_list.append(CreditCard(
            card_number=card_datum['card_number'],
            expired_date=card_datum['expired_date'],
            credit_card_status=credit_card_status
        ))
    CreditCard.objects.bulk_create(credit_card_list, batch_size=25)

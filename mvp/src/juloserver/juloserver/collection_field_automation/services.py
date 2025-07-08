import os
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from juloserver.account.models import AdditionalCustomerInfo
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.julo.models import (
    PTP,
    PaymentMethod,
    Application,
    Skiptrace,
    Image,
)
from juloserver.julo.services import ptp_create
from juloserver.collection_field_automation.constant import VisitResultCodes
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    upload_file_to_oss,
)
from juloserver.portal.core import functions


def format_field_assignment_data(field_assignments):
    data_to_show = []
    i = 0
    for field_assignment in field_assignments:
        i += 1
        account = field_assignment.account
        application = account.application_set.last()
        if not account.get_oldest_unpaid_account_payment():
            continue

        data = dict(
            id=field_assignment.id,
            data_number=i,
            account_id=account.id,
            fullname=application.fullname,
            agent_username=field_assignment.agent.username,
            area=application.address_kelurahan,
            current_dpd=account.get_oldest_unpaid_account_payment().dpd,
            assignment_date=field_assignment.assign_date,
            expiry_date=field_assignment.expiry_date,
            overdue_amount=account.get_total_overdue_amount() or 0,
            result=field_assignment.result or '-',
            ptp_date='-', ptp_amount=0, done_status=True if field_assignment.result else False,
            visit_photo=field_assignment.visit_proof_image_url,
            outstanding_amount=account.get_total_outstanding_amount() or 0
        )
        ptp = field_assignment.ptp
        if ptp:
            data.update(ptp_date=ptp.ptp_date, ptp_amount=ptp.ptp_amount)

        data_to_show.append(data)
    return data_to_show


def update_report_agent_field_visit_data(
        agent_user, field_assignment, data, uploaded_image):
    field_assignment_id = field_assignment.id
    visit_location = data.get('visit_location')
    result_mapping_code = data.get('result_mapping_code')
    result = result_mapping_code
    data_to_update = dict(
        visit_location=visit_location,
        visit_description=data.get('visit_description'),
        result=result_mapping_code
    )
    if visit_location == VisitResultCodes.OTHER:
        data_to_update.update(
            visit_location="{} - {}".format(
                visit_location, data.get('text_visit_other'))
        )
    with transaction.atomic():
        account = field_assignment.account
        account_payment = account.get_oldest_unpaid_account_payment()
        payment_channel = data.get('payment_channel')
        new_phone_number = data.get('new_phone_number')
        customer_new_address = data.get('new_address')
        ptp_notes = ''
        if result_mapping_code == 'PTP':
            ptp_date = data.get('ptp_date')
            ptp_amount = int(data.get('ptp_amount').replace(',', ''))
            ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
            ptp_create(
                account_payment, ptp_date, ptp_amount, agent_user,
                is_julo_one=True
            )
            account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
            data_to_update.update(
                ptp=PTP.objects.filter(
                    account_payment=account_payment,
                    ptp_date=ptp_date,
                    agent_assigned=agent_user).last()
            )
        elif result_mapping_code == VisitResultCodes.REFUSE_PAY:
            result = "{} - {}".format(
                result_mapping_code, data.get('refuse_reasons')
            )
            data_to_update.update(result=result)

        if payment_channel:
            payment_method = PaymentMethod.objects.get_or_none(
                pk=payment_channel)
            if payment_method:
                PaymentMethod.objects.filter(
                    customer=account.customer, is_primary=True).update(is_primary=False)
                payment_method.update_safely(is_primary=True)
        if new_phone_number and new_phone_number != '':
            application = Application.objects.get_or_none(account_id=account.id)
            contact_source = 'dari agent field collection'
            Skiptrace.objects.create(
                contact_source=contact_source,
                phone_number=format_e164_indo_phone_number(new_phone_number),
                customer_id=account.customer.id,
                application=application
            )
        if customer_new_address and customer_new_address != '':
            AdditionalCustomerInfo.objects.create(
                additional_customer_info_type='new_address_from_field_collection',
                customer=account.customer,
                street_number=customer_new_address,
                latest_updated_by=agent_user
            )
        if 'visit_proof_image' in uploaded_image:
            image_data = uploaded_image['visit_proof_image']
            _, file_extension = os.path.splitext(image_data.name)
            today = timezone.localtime(timezone.now())
            extension = file_extension.replace(".", "")
            file_name = "visit_proof_{}_{}".format(
                field_assignment_id, today.strftime("%m%d%Y%H%M%S")
            )
            dest_name = "{}/images/{}.{}".format(
                settings.ENVIRONMENT, file_name, extension
            )
            file = functions.upload_handle_media(image_data, "collection-field-visit-proof")
            upload_file_to_oss(
                settings.OSS_JULO_COLLECTION_BUCKET,
                file['file_name'], dest_name
            )
            image = Image()
            image.image_source = field_assignment_id
            image.image_type = 'visit_proof_field_collection'
            image.url = dest_name
            image.save()
            if os.path.isfile(file['file_name']):
                os.remove(file['file_name'])

        field_notes = "Visit Results from Field Agent {} - {}".format(
            result, data.get('visit_description'))
        if ptp_notes:
            field_notes = "{};{}".format(field_notes, ptp_notes)

        AccountPaymentNote.objects.create(
            note_text=field_notes,
            account_payment=account_payment,
            added_by=agent_user,
        )
        field_assignment.update_safely(**data_to_update)

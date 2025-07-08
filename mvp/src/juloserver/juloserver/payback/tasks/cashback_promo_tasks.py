from future import standard_library
standard_library.install_aliases()
import os
import logging
import tempfile
import urllib.request, urllib.error, urllib.parse
from celery import task
from juloserver.julo.models import (Document,
                                    FeatureSetting,
                                    EmailHistory,
                                    Customer)
from ..models import CashbackPromo
from juloserver.julo.utils import upload_file_to_oss
from django.conf import settings
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.constants import FeatureNameConst
from django.core.urlresolvers import reverse
from juloserver.sdk.services import xls_to_dict
from django.db import transaction
from ..serializers import CashbackPromoSerializer
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.payback.constants import CashbackPromoConst

logger = logging.getLogger(__name__)

EMAIL_CREATED_RESPONSE_CODE = 202

sentry_client = get_julo_sentry_client()

@task(queue="collection_high")
def sent_cashback_promo_approval(cashback_promo_id):
    cashback_promo = CashbackPromo.objects.get(pk=cashback_promo_id)
    document = Document.objects.filter(
        document_source=cashback_promo.id, document_type='cashback_promo').last()
    if not document:
        logger.error({"document_source_id": cashback_promo_id,
                      "status": "document_not_found"})
        return

    local_path = "{}/{}".format(tempfile.gettempdir(), document.filename)
    document_remote_filepath = "cashback_promo/{}/{}".format(
        cashback_promo.id, document.filename)

    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_path, document_remote_filepath)
    document.url = document_remote_filepath
    document.save()
    # Delete local document
    if os.path.isfile(local_path):
        logger.info(
            {
                "action": "deleting_local_document",
                "document_path": local_path,
                "cashback_promo_name": cashback_promo.promo_name
            }
        )
        os.remove(local_path)
    email_client = get_julo_email_client()
    data = {'promo_name': cashback_promo.promo_name}

    #send email to requester
    status, headers, msg = email_client.cashback_management_email(
        cashback_promo.pic_email, CashbackPromoConst.EMAIL_TYPE_REQUESTER_NOTIF, data)

    logger.info({
        'task': 'sent_cashback_promo_approval',
        'action': 'sent_email_to_requester',
        'email': cashback_promo.pic_email
    })
    # record email history
    if status == EMAIL_CREATED_RESPONSE_CODE:
        message_id = headers['X-Message-Id']
        EmailHistory.objects.create(
            sg_message_id=message_id,
            to_email=cashback_promo.pic_email,
            subject='Permohonan Pengajuan Cashback',
            message_content=msg,
            template_code='email_notif_for_requester',
        )

    feature_setting = FeatureSetting.objects.get(feature_name=FeatureNameConst.MANUAL_CASHBACK_PROMO)
    approvers = feature_setting.parameters['approvers']
    for approver in approvers:
        link = (settings.BASE_URL +
                                 reverse('cashback_promo_decision',
                                         kwargs={'approval_token': cashback_promo.approval_token}) +
                                 '?approver={}'.format(approver))
        data['approval_link'] = link + '&decision={}'.format('approved')
        data['rejection_link'] = link + '&decision={}'.format('rejected')
        data['document_url'] = document.document_url
        data['filename'] = document.filename
        data['department'] = cashback_promo.department
        status, headers, msg = email_client.cashback_management_email(
            approver, CashbackPromoConst.EMAIL_TYPE_APPROVER_NOTIF, data)

        logger.info({
            'task': 'sent_cashback_promo_approval',
            'action': 'sent_email_to_approvers',
            'email': cashback_promo.pic_email
        })
        # record email history
        if status == EMAIL_CREATED_RESPONSE_CODE:
            message_id = headers['X-Message-Id']
            EmailHistory.objects.create(
                sg_message_id=message_id,
                to_email=cashback_promo.pic_email,
                subject='Permohonan Pengajuan Cashback',
                message_content=msg,
                template_code='email_notif_for_approvers',
            )

    logger.info(
        {
            "status": "successfull upload document",
            "document_remote_filepath": document_remote_filepath,
            "cashback_promo_id": document.document_source,
            "document_type": document.document_type,
        }
    )

@task(name="inject_cashback_task")
def inject_cashback_task(cashback_promo_id):
    """
    we set execution time to almost midnight to prevent performance issue
    we can't break down this task, because we need run whole data in atomic transaction.
    process all data or rollback all (don't proceed partial)
    """
    cashback_promo = CashbackPromo.objects.get(pk=cashback_promo_id)
    document = Document.objects.filter(
        document_source=cashback_promo.id, document_type='cashback_promo').last()
    if not document:
        logger.error({"document_source_id": cashback_promo_id,
                      "status": "document_not_found"})
        return

    excel_file = urllib.request.urlopen(document.document_url)
    delimiter =','
    excel_data = xls_to_dict(excel_file, delimiter)
    try:
        with transaction.atomic():
            for idx_sheet, sheet in enumerate(excel_data):
                for idx_rpw, row in enumerate(excel_data[sheet]):
                    serializer = CashbackPromoSerializer(data=row)
                    if serializer.is_valid():
                        customer_id = int(row['customer_id'])
                        cashback_inject = int(row['cashback'])
                        customer = Customer.objects.get(pk=customer_id)
                        loan = customer.loan_set.last()

                        payment = loan.payment_set.filter(
                            payment_status_id=PaymentStatusCodes.PAID_ON_TIME).last()
                        if not payment: #if there's no paid off payment, get first payment
                            payment = loan.payment_set.first()
                        payment.cashback_earned += cashback_inject
                        payment.save()
                        customer.change_wallet_balance(
                            change_accruing=cashback_inject,
                            change_available=0,
                            reason=cashback_promo.promo_name,
                            payment=payment)

                        #set injected cashback immediately available for paid off loan
                        if loan.status == 250:
                            customer.change_wallet_balance(
                                change_accruing=0,
                                change_available=cashback_inject,
                                reason='cashback_available')
                        loan.update_cashback_earned_total(cashback_inject)
                        loan.save()
                    else:
                        error_data = {'error_message': 'invalid data',
                                      'filename': document.filename,
                                      'row': idx_rpw}
                        raise JuloException(error_data)
    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                "status": "inject_cashback_task failed",
                "cashback_promo_id": document.document_source,
                "error" : e
            }
        )
    else:
        cashback_promo.update_safely(is_completed=True)

@task(queue="collection_high")
def sent_cashback_promo_notification_to_requester(cashback_promo_id):
    cashback_promo = CashbackPromo.objects.get(pk=cashback_promo_id)
    email_type = CashbackPromoConst.EMAIL_TYPE_REJECTION
    if cashback_promo.decision == 'approved':
        email_type = CashbackPromoConst.EMAIL_TYPE_APPROVAL
    email_client = get_julo_email_client()
    data = {'promo_name': cashback_promo.promo_name}
    status, headers, msg = email_client.cashback_management_email(
        cashback_promo.pic_email, email_type, data)

    logger.info({
        'task': 'sent_cashback_promo_approval',
        'action': 'sent_email_to_requester',
        'email': cashback_promo.pic_email
    })
    # record email history
    if status == EMAIL_CREATED_RESPONSE_CODE:
        message_id = headers['X-Message-Id']
        EmailHistory.objects.create(
            sg_message_id=message_id,
            to_email=cashback_promo.pic_email,
            subject='Permohonan Pengajuan Cashback',
            message_content=msg,
            template_code='email_decision_notif_for_requester',
        )
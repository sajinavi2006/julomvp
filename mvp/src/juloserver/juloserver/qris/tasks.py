import csv
import io
import logging
import os
import tempfile
from typing import Dict

from django.conf import settings
import pdfkit
from celery import task
from django.db import transaction
from django.utils import timezone

from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.constants import CloudStorage
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.utils import get_file_from_oss
from juloserver.julo_financing.services.core_services import JFinancingSignatureService
from juloserver.julo.models import Customer, Document, Image, Loan, RedisWhiteListUploadHistory
from juloserver.julocore.common_services.redis_service import (
    set_redis_ids_whitelist,
    set_latest_success_redis_whitelist,
)
from juloserver.julocore.constants import RedisWhiteList
from juloserver.loan.services.lender_related import (
    julo_one_loan_disbursement_success,
    mark_loan_transaction_failed,
)
from juloserver.qris.exceptions import AmarStatusChangeCallbackInvalid
from juloserver.qris.models import QrisLinkageLenderAgreement, QrisPartnerTransaction
from juloserver.julo.tasks import upload_document
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Partner
from juloserver.qris.constants import AmarCallbackConst, QrisLinkageStatus, QrisTransactionStatus
from juloserver.qris.models import QrisPartnerLinkage
from juloserver.qris.services.core_services import (
    create_linkage_history,
    create_transaction_history,
)


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='loan_normal')
def upload_qris_signature_and_master_agreement_task(qris_lender_agreement_id: int):
    agreement = QrisLinkageLenderAgreement.objects.select_related('qris_partner_linkage').get(
        pk=qris_lender_agreement_id
    )

    customer_id = agreement.qris_partner_linkage.customer_id
    logger.info(
        {
            "action": "upload_qris_signature_and_master_agreement_task",
            "customer_id": customer_id,
            "qris_linkage_lender_agreement_id": qris_lender_agreement_id,
        }
    )

    signature_image = Image.objects.get(pk=agreement.signature_image_id)
    # resuse jfinancing signature service
    JFinancingSignatureService(
        signature_image=signature_image,
        customer_id=customer_id,
        folder_prefix='master_agreement__',
    ).upload_jfinancing_signature_image()

    generate_qris_master_agreement_task.delay(agreement.id)


@task(queue='loan_normal')
def generate_qris_master_agreement_task(qris_linkage_lender_agreement_id: int):
    from juloserver.qris.services.user_related import get_master_agreement_html

    agreement = QrisLinkageLenderAgreement.objects.get(pk=qris_linkage_lender_agreement_id)

    if agreement.master_agreement_id:
        logger.warning(
            {
                'action': 'generate_qris_master_agreement_task',
                "qris_linkage_lender_agreement_id": agreement.id,
                'message': "Master agreement has already been generated",
            }
        )
        return

    try:
        # Get customer and application info
        customer = Customer.objects.get(pk=agreement.qris_partner_linkage.customer_id)
        application = customer.account.get_active_application()

        # Generate PDF content and filename
        signature_image = Image.objects.get(pk=agreement.signature_image_id)
        lender = LenderCurrent.objects.get(pk=agreement.lender_id)
        qris_user_state = agreement.qris_partner_linkage.qris_user_state
        template = get_master_agreement_html(
            application, lender=lender, signature_image=signature_image
        )
        now = timezone.localtime(timezone.now())
        filename = 'qris_master_agreement_{}_{}_{}.pdf'.format(
            customer.pk,
            lender.lender_name,
            now.strftime('%Y%m%d_%H%M%S'),
        )

        # Create PDF file
        file_path = os.path.join(tempfile.gettempdir(), filename)
        pdfkit.from_string(template, file_path)

        # Create and save document
        with transaction.atomic():
            qris_master_agreement = Document.objects.create(
                document_source=qris_user_state.id,
                document_type=LoanAgreementType.MASTER_AGREEMENT,
                filename=filename,
            )
            # update user state for first time when it doesn't have record
            # but we always update on QrisLinkageLenderAgreement
            if not qris_user_state.master_agreement_id:
                qris_user_state.master_agreement_id = qris_master_agreement.id
                qris_user_state.save(update_fields=['master_agreement_id'])

            agreement.master_agreement_id = qris_master_agreement.id
            agreement.save(update_fields=['master_agreement_id'])

            logger.info(
                {
                    'action': 'generate_qris_master_agreement_task',
                    'data': {
                        'qris_user_state_id': qris_user_state.id,
                        'qris_linkage_lender_agreement_id': agreement.id,
                        'qris_master_agreement_id': qris_master_agreement.id,
                        'customer_id': customer.id,
                        'filename': filename,
                    },
                    'message': "Successfully created PDF",
                }
            )
            upload_document(qris_master_agreement.id, file_path, is_qris=True)

    except Exception as e:
        logger.exception(
            {
                'action': 'generate_qris_master_agreement_task',
                'qris_linkage_lender_agreement_id': agreement.id,
                'error': str(e),
            }
        )
        raise e


@task(queue='loan_high')
def process_callback_register_from_amar_task(
    to_partner_user_xid: str,
    amar_status: str,
    payload: Dict,
):
    """
    Update linkage status & create history after success callback
    When: After registration or first time login
    Callback after every login's also configurable from Android
    """
    amar_partner = Partner.objects.get(
        name=PartnerNameConstant.AMAR,
    )
    linkage = QrisPartnerLinkage.objects.filter(
        to_partner_user_xid=to_partner_user_xid, partner_id=amar_partner.id
    ).last()

    if not linkage:
        sentry_client.captureMessage(
            "Amar sent non existing user_xid: {}".format(to_partner_user_xid)
        )
        return

    current_payload = linkage.partner_callback_payload
    current_status = linkage.status

    to_status = (
        QrisLinkageStatus.SUCCESS
        if amar_status == AmarCallbackConst.AccountRegister.ACCEPTED_STATUS
        else QrisLinkageStatus.FAILED
    )

    # check if status path is valid
    is_valid = QrisLinkageStatus.amar_status_path_check(
        from_status=current_status,
        to_status=to_status,
    )

    if is_valid:
        with transaction.atomic():
            # update status & create history
            linkage = QrisPartnerLinkage.objects.select_for_update().get(
                to_partner_user_xid=to_partner_user_xid, partner_id=amar_partner.id
            )

            # call is_valid again case concurrent callback
            is_valid = QrisLinkageStatus.amar_status_path_check(
                from_status=linkage.status,
                to_status=to_status,
            )
            if not is_valid:
                return

            linkage.status = to_status
            linkage.partner_callback_payload = payload
            linkage.save(update_fields=['status', 'partner_callback_payload'])

            create_linkage_history(
                linkage_id=linkage.id,
                field='status',
                old_value=current_status,
                new_value=to_status,
            )
            create_linkage_history(
                linkage_id=linkage.id,
                field='partner_callback_payload',
                old_value=current_payload,
                new_value=payload,
            )


def _handle_amar_callback_pending_status(payload: Dict):
    """
    When status pending from amar, only needs to store callback data
    """
    to_partner_user_xid = payload['partnerCustomerID']
    from_partner_transaction_xid = payload['data']['transactionID']

    amar_partner = Partner.objects.get(name=PartnerNameConstant.AMAR)

    with transaction.atomic():
        # update payload only
        qris_transaction = (
            QrisPartnerTransaction.objects.select_for_update()
            .filter(
                from_partner_transaction_xid=from_partner_transaction_xid,
                qris_partner_linkage__to_partner_user_xid=to_partner_user_xid,
                qris_partner_linkage__partner_id=amar_partner.id,
            )
            .last()
        )

        # only update callback if status is pending
        # happens if success & pending callbacks occur at same time
        if qris_transaction.status != QrisTransactionStatus.PENDING:
            return

        current_payload = qris_transaction.partner_callback_payload
        qris_transaction.partner_callback_payload = payload
        qris_transaction.save(update_fields=['partner_callback_payload'])

        # create history
        create_transaction_history(
            transaction_id=qris_transaction.id,
            field='partner_callback_payload',
            old_value=current_payload,
            new_value=payload,
        )


def _update_qris_loan(loan_id: int, to_loan_status: LoanStatusCodes):
    """
    Update loan status for qris loan
    """
    loan = Loan.objects.get(pk=loan_id)
    if to_loan_status == LoanStatusCodes.CURRENT:
        julo_one_loan_disbursement_success(loan=loan)
    elif to_loan_status == LoanStatusCodes.TRANSACTION_FAILED:
        # mark failed, no need for retry
        mark_loan_transaction_failed(loan=loan)


@task(queue='loan_high')
def process_callback_transaction_status_from_amar_task(
    payload: Dict,  # serializable Dict
):
    """
    - For case pending status, don't update loan status only logging
    - Qris Transaction Status to success/failed
    - Loan Status to successs/failed
    """
    amar_status = payload['statusCode']

    if amar_status == AmarCallbackConst.LoanDisbursement.PENDING_STATUS:
        _handle_amar_callback_pending_status(payload)
        return

    to_partner_user_xid = payload['partnerCustomerID']

    to_transaction_status = (
        QrisTransactionStatus.SUCCESS
        if amar_status == AmarCallbackConst.LoanDisbursement.SUCESS_STATUS
        else QrisTransactionStatus.FAILED
    )

    to_loan_status = (
        LoanStatusCodes.CURRENT
        if to_transaction_status == QrisTransactionStatus.SUCCESS
        else LoanStatusCodes.TRANSACTION_FAILED
    )

    from_partner_transaction_xid = payload['data']['transactionID']

    amar_partner = Partner.objects.get(name=PartnerNameConstant.AMAR)

    with transaction.atomic():
        # update status
        qris_transaction = (
            QrisPartnerTransaction.objects.select_for_update()
            .filter(
                from_partner_transaction_xid=from_partner_transaction_xid,
                qris_partner_linkage__to_partner_user_xid=to_partner_user_xid,
                qris_partner_linkage__partner_id=amar_partner.id,
            )
            .last()
        )

        from_transaction_status = qris_transaction.status

        is_valid = QrisTransactionStatus.amar_status_path_check(
            from_status=from_transaction_status,
            to_status=to_transaction_status,
        )
        if not is_valid:
            raise AmarStatusChangeCallbackInvalid

        qris_transaction.status = to_transaction_status

        current_payload = qris_transaction.partner_callback_payload
        qris_transaction.partner_callback_payload = payload
        qris_transaction.save(update_fields=['status', 'partner_callback_payload'])

        # create histories
        create_transaction_history(
            transaction_id=qris_transaction.id,
            field='status',
            old_value=from_transaction_status,
            new_value=to_transaction_status,
        )

        create_transaction_history(
            transaction_id=qris_transaction.id,
            field='partner_callback_payload',
            old_value=current_payload,
            new_value=payload,
        )

        # update loan success/failed
        _update_qris_loan(
            loan_id=qris_transaction.loan_id,
            to_loan_status=to_loan_status,
        )


@task(queue='loan_high')
def bulk_process_callback_transaction_status_from_amar_task(loan_status_map: Dict):
    """
    Meant to be run MANUALLY for special cases with django command
    Param:
    - loan_status_map: {3012001312: 'success', }
    """
    total_loans = len(loan_status_map)
    logger.info(
        {
            "action": "bulk_process_callback_transaction_status_from_amar_task",
            "message": f"Starting updating status for {total_loans} amar loans",
        }
    )

    for i, (loan_id, to_transaction_status) in enumerate(loan_status_map.items(), start=1):
        to_loan_status = (
            LoanStatusCodes.CURRENT
            if to_transaction_status == QrisTransactionStatus.SUCCESS
            else LoanStatusCodes.TRANSACTION_FAILED
        )

        try:
            with transaction.atomic():
                # update status
                qris_transaction = (
                    QrisPartnerTransaction.objects.select_for_update()
                    .filter(loan_id=loan_id)
                    .last()
                )

                from_transaction_status = qris_transaction.status

                is_valid = QrisTransactionStatus.amar_status_path_check(
                    from_status=from_transaction_status,
                    to_status=to_transaction_status,
                )
                if not is_valid:
                    raise AmarStatusChangeCallbackInvalid

                qris_transaction.status = to_transaction_status

                qris_transaction.save(update_fields=['status'])

                # create histories
                create_transaction_history(
                    transaction_id=qris_transaction.id,
                    field='status',
                    old_value=from_transaction_status,
                    new_value=to_transaction_status,
                    reason="manually run via script",
                )

                # update loan success/failed
                _update_qris_loan(
                    loan_id=qris_transaction.loan_id,
                    to_loan_status=to_loan_status,
                )

        except Exception:
            sentry_client.captureException()
            continue

        finally:
            # logging progress for debugging
            current_progress = round((i / total_loans) * 100, 2)

            logger.info(
                {
                    "action": "bulk_process_callback_transaction_status_from_amar_task",
                    "last_loan_id_processed": loan_id,
                    "current_progress": f"{current_progress}%",
                }
            )


@task(queue='loan_high')
def retrieve_and_set_qris_redis_whitelist_csv():
    """
    Retrieve .csv of customer_ids from cloud storage (currently OSS)
    Set the ids on redis
    Update status
    """
    # retrieve csv
    history = RedisWhiteListUploadHistory.objects.filter(
        whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
        status=RedisWhiteList.Status.UPLOAD_SUCCESS,
        cloud_storage=CloudStorage.OSS,
    ).last()

    try:
        csv_stream = get_file_from_oss(
            bucket_name=history.remote_bucket,
            remote_filepath=history.remote_file_path,
        )

        csv_text = csv_stream.read().decode().splitlines()

        # generate set & set it on redis
        reader = csv.DictReader(csv_text)
        generator = (int(row['customer_id']) for row in reader)

        len_ids = set_redis_ids_whitelist(
            ids=generator,
            key=RedisWhiteList.Key.SET_QRIS_WHITELISTED_CUSTOMER_IDS,
            temp_key=RedisWhiteList.Key.TEMP_SET_QRIS_WHITELISTED_CUSTOMER_IDS,
        )

    except Exception:
        sentry_client.captureException()
        history.status = RedisWhiteList.Status.WHITELIST_FAILED
        history.save(update_fields=['status'])
        return

    # update status & set latest success
    with transaction.atomic():
        history.status = RedisWhiteList.Status.WHITELIST_SUCCESS
        history.len_ids = len_ids
        history.save(update_fields=['len_ids', 'status'])

        set_latest_success_redis_whitelist(history)

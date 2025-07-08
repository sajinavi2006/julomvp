import logging
import base64
from celery.task import task

from datetime import datetime
from babel.dates import format_datetime
from django.conf import settings
from django.template.loader import get_template

from juloserver.julo.clients import get_julo_email_client
from juloserver.merchant_financing.web_app.constants import MFWebAppUploadAsyncStateType
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.models import UploadAsyncState, Partner, EmailHistory, Loan
from django.utils import timezone

from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


@task(queue='partner_mf_global_queue')
def process_mf_web_app_register_file_task(upload_async_state_id: int, partner_name: str) -> None:
    from juloserver.merchant_financing.web_app.crm.services import (
        process_mf_web_app_register_result
    )

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=MFWebAppUploadAsyncStateType.MERCHANT_FINANCING_WEB_APP_REGISTER,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "MF_web_app_process_register_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    pii_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': partner_name})
    partner = Partner.objects.filter(**pii_filter_dict).last()
    if not partner:
        logger.info(
            {
                "action": "MF_web_app_process_register_task_failed",
                "message": "Partner not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )
        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = process_mf_web_app_register_result(upload_async_state, partner)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        logger.exception(
            {
                'module': 'mf_web_app',
                'action': 'process_mf_web_app_register_file_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue='partner_mf_global_queue')
def send_email_skrtp(
    loan_id: int,
    interest_rate: float,
    loan_request_date: str,
    timestamp: datetime,
) -> str:
    from juloserver.merchant_financing.utils import get_fs_send_skrtp_option_by_partner
    try:
        loan = (
            Loan.objects.filter(id=loan_id)
            .select_related(
                'customer', 'application', 'account', 'account__partnership_customer_data'
            )
            .first()
        )
        if not loan:
            logger.info(
                {
                    'action': 'send_email_skrtp',
                    'loan_id': str(loan_id),
                    'message': "Loan not found",
                }
            )
            return "Loan not found"

        loan_xid_str = str(loan.loan_xid)
        now = timestamp
        now_str = now.strftime("%Y%m%d%H%M%S")
        token_str = '{}_{}'.format(loan_xid_str, now_str)

        token_bytes = token_str.encode("ascii")
        base64_bytes = base64.b64encode(token_bytes)
        base64_string = base64_bytes.decode("ascii")

        skrtp_link = settings.JULO_WEB_URL + '/skrtp/{}'.format(base64_string)

        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            loan.account.partnership_customer_data,
            loan.customer.customer_xid,
            ['email'],
        )

        detokenize_customer = partnership_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            loan.customer,
            loan.customer.customer_xid,
            ['fullname'],
        )

        application = loan.get_application
        email = detokenize_partnership_customer_data.email
        partner_name = application.partner.name_detokenized
        err_msg, partner_email, _ = get_fs_send_skrtp_option_by_partner(partner_name)
        if err_msg and not partner_email:
            logger.error(
                {
                    'action': 'send_email_skrtp',
                    'loan_id': str(loan_id),
                    'email': email,
                    'message': err_msg,
                }
            )
            return err_msg

        if partner_email:
            email = partner_email

        subject = "Yuk, Konfirmasi Persetujuan Pinjamanmu"
        template = get_template('email_skrtp_link.html')
        application_date = datetime.strptime(loan_request_date, '%d/%m/%Y')
        context = {
            "loan_xid": str(loan.loan_xid),
            "skrtp_link": skrtp_link,
            "fullname": detokenize_customer.fullname,
            "application_date": format_datetime(application_date, "d MMMM yyyy", locale='id_ID'),
            "loan_amount": '{:,}'.format(loan.loan_amount).replace(',', '.'),
            "interest": interest_rate,
            "tenor": loan.loan_duration,
        }
        html_content = template.render(context)
        status, _, headers = get_julo_email_client().send_email(
            subject, html_content, email, settings.EMAIL_FROM
        )
        message_id = headers['X-Message-Id']
        EmailHistory.objects.create(
            customer=loan.customer,
            application=application,
            to_email=email,
            subject=subject,
            message_content=html_content,
            sg_message_id=message_id,
            template_code='email_skrtp_link',
            status=str(status),
        )

        loan.sphp_sent_ts = timezone.localtime(now)
        loan.save()
        logger.info(
            {
                'action': 'send_email_skrtp',
                'loan_id': str(loan_id),
                'email': email,
                'context': context,
                'message': "Success",
            }
        )
        return None

    except Exception as e:
        logger.exception(
            {
                'action': 'send_email_skrtp',
                'loan_id': str(loan_id),
                'email': email,
                'error': str(e),
            }
        )
        return "Error Exception - {}".format(str(e))

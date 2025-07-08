import logging
from datetime import date, timedelta

from bulk_update.helper import bulk_update
from celery import task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.template.loader import get_template

from juloserver.customer_module.constants import (
    ADJUST_AUTO_APPROVE_DATE_RELEASE,
    AccountDeletionRequestStatuses,
)
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    WebAccountDeletionRequest,
)
from juloserver.customer_module.services.account_deletion import (
    delete_ktp_and_selfie_file_from_oss,
    forward_web_account_deletion_request_to_ops,
    send_web_account_deletion_received_failed,
    send_web_account_deletion_received_success,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_deletion_email_format,
    get_deletion_nik_format,
)
from juloserver.julo.clients import get_julo_email_client, get_julo_sentry_client
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.models import (
    Application,
    ApplicationFieldChange,
    AuthUserFieldChange,
    Customer,
    CustomerFieldChange,
    CustomerRemoval,
    EmailHistory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import get_file_from_oss
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pin.utils import get_first_name

logger = logging.getLogger(__name__)


@task(queue="normal")
def handle_web_account_deletion_request(data: dict):
    """
    Function to handle web account deletion request
    Args:
        - data: dict (with expected fields down below)
            - nik: str
            - phone: str
            - email: str
            - reason: str
            - details: str
            - image_ktp_filepath: str
            - image_selfie_filepath: str
    Returns:
        None
    """
    try:
        customer = Customer.objects.get(
            nik=data["nik"],
            phone=data["phone"],
            email=data["email"],
        )

    except Customer.DoesNotExist:
        WebAccountDeletionRequest.objects.create(
            full_name=data["fullname"],
            nik=data["nik"],
            phone=data["phone"],
            email=data["email"],
            reason=data["reason"],
            details=data["details"],
        )

        send_web_account_deletion_received_failed(
            data["email"],
        )

        # delete ktp and selfie file from oss
        delete_ktp_and_selfie_file_from_oss(
            data["image_ktp_filepath"], data["image_selfie_filepath"]
        )

        return

    WebAccountDeletionRequest.objects.create(
        nik=data["nik"],
        full_name=data["fullname"],
        phone=data["phone"],
        email=data["email"],
        reason=data["reason"],
        details=data["details"],
        customer_id=customer.id,
    )

    # get images from blob
    image_ktp = get_file_from_oss(settings.OSS_PUBLIC_BUCKET, data["image_ktp_filepath"])
    image_selfie = get_file_from_oss(settings.OSS_PUBLIC_BUCKET, data["image_selfie_filepath"])

    # send email to cs@julo.co.id
    forward_web_account_deletion_request_to_ops(
        fullname=data["fullname"],
        phone=data["phone"],
        email=data["email"],
        reason=data["reason"],
        details=data["details"],
        image_ktp=image_ktp,
        image_ktp_file_path=data["image_ktp_filepath"],
        image_selfie=image_selfie,
        image_selfie_file_path=data["image_selfie_filepath"],
    )

    # send success email to the customer email
    send_web_account_deletion_received_success(customer)

    # delete ktp and selfie file from oss
    delete_ktp_and_selfie_file_from_oss(data["image_ktp_filepath"], data["image_selfie_filepath"])

    return


@task(queue='application_high')
def send_create_deletion_request_success_email(customer_id):
    customer = Customer.objects.get(id=customer_id)
    if not customer:
        return

    detokenize_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenize_customers[0]
    if not customer.email:
        return

    first_name = get_first_name(customer)

    subject = 'Permintaan Hapus Akun Diproses'
    variable = {"first_name": first_name}
    template = get_template('hapus_akun_request_successfully_sent.html')
    html_content = template.render(variable)

    message_id = None
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            customer.email,
            'cs@julofinance.com',
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers['X-Message-Id']
    except Exception as e:
        status = 'error'
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception(
                'send_create_deletion_request_success_email_failed, data={} | err={}'.format(
                    customer, e
                )
            )

    EmailHistory.objects.create(
        to_email=customer.email,
        subject=subject,
        sg_message_id=message_id,
        template_code='hapus_akun_request_successfully_sent',
        customer=customer,
        status=str(status),
        error_message=error_message,
    )


@task(queue='application_high')
def send_cancel_deletion_request_success_email(customer_id):
    customer = Customer.objects.get(id=customer_id)
    if not customer:
        return

    detokenize_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenize_customers[0]
    if not customer.email:
        return

    first_name = get_first_name(customer)

    subject = 'Permintaan Hapus Akun Dibatalkan'
    variable = {"first_name": first_name}
    template = get_template('hapus_akun_cancelled_by_user.html')
    html_content = template.render(variable)

    message_id = None
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            customer.email,
            'cs@julofinance.com',
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers['X-Message-Id']
    except Exception as e:
        status = 'error'
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception(
                'send_cancel_deletion_request_success_email_failed, data={} | err={}'.format(
                    customer, e
                )
            )

    EmailHistory.objects.create(
        to_email=customer.email,
        subject=subject,
        sg_message_id=message_id,
        template_code='hapus_akun_cancelled_by_user',
        customer=customer,
        status=str(status),
        error_message=error_message,
    )


@task(queue='application_high')
def send_follow_up_deletion_request_email():
    now = date.today()
    date_14_days_ago = now - timedelta(days=14)
    date_5_days_ago = now - timedelta(days=5)

    requests = AccountDeletionRequest.objects.filter(
        Q(
            cdate__date__gte=ADJUST_AUTO_APPROVE_DATE_RELEASE,
            cdate__date=date_5_days_ago,
        )
        | Q(
            cdate__date__lt=ADJUST_AUTO_APPROVE_DATE_RELEASE,
            cdate__date=date_14_days_ago,
        ),
        request_status=AccountDeletionRequestStatuses.PENDING,
    )

    for req in requests.iterator():
        customer = req.customer
        if not customer:
            continue

        if not customer.email:
            continue

        first_name = get_first_name(customer)

        subject = 'Permintaan Hapus Akun Masih Bisa Dibatalkan, Lho!'
        variable = {"first_name": first_name}
        template = get_template('hapus_akun_follow_up.html')
        html_content = template.render(variable)

        message_id = None
        try:
            status, _, headers = get_julo_email_client().send_email(
                subject,
                html_content,
                customer.email,
                'cs@julofinance.com',
            )
            if status == 202:
                status = 'sent_to_sendgrid'
                error_message = None
            message_id = headers['X-Message-Id']
        except Exception as e:
            status = 'error'
            error_message = str(e)
            if not isinstance(e, EmailNotSent):
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                logger.exception(
                    'send_follow_up_deletion_request_success_email_failed, data={} | err={}'.format(
                        customer, e
                    )
                )

        EmailHistory.objects.create(
            to_email=customer.email,
            subject=subject,
            sg_message_id=message_id,
            template_code='hapus_akun_follow_up',
            customer=customer,
            status=str(status),
            error_message=error_message,
        )


@task(queue='application_high')
def send_approved_deletion_request_success_email(customer_id):
    from juloserver.customer_module.services.pii_vault import (
        detokenize_sync_object_model,
    )
    from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

    customer = Customer.objects.get(id=customer_id)
    if not customer:
        return

    target_email = ''
    if customer.is_active and customer.email:
        target_email = customer.email
    else:
        customer_removal = CustomerRemoval.objects.filter(
            customer_id=customer_id,
        ).last()

        detokenized_customer_removal = detokenize_sync_object_model(
            PiiSource.CUSTOMER_REMOVAL, PiiVaultDataType.KEY_VALUE, [customer_removal]
        )

        if len(detokenized_customer_removal) == 0:
            return

        target_email = detokenized_customer_removal[0].email

    if not target_email:
        return

    first_name = get_first_name(customer)

    subject = 'Kami Sedih Melihatmu Pergi 😔'
    variable = {"first_name": first_name}
    template = get_template('hapus_akun_approved.html')
    html_content = template.render(variable)

    message_id = None
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            target_email,
            'cs@julofinance.com',
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers['X-Message-Id']
    except Exception as e:
        status = 'error'
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception(
                'send_approved_deletion_request_success_email_failed, data={} | err={}'.format(
                    customer, e
                )
            )

    EmailHistory.objects.create(
        to_email=target_email,
        subject=subject,
        sg_message_id=message_id,
        template_code='hapus_akun_approved',
        customer=customer,
        status=str(status),
        error_message=error_message,
    )


@task(queue='application_high')
def send_rejected_deletion_request_success_email(customer_id):
    customer = Customer.objects.get(id=customer_id)
    if not customer:
        return

    if not customer.email:
        return

    first_name = get_first_name(customer)

    subject = 'Permintaan Hapus Akun Gagal'
    variable = {"first_name": first_name}
    template = get_template('hapus_akun_failed.html')
    html_content = template.render(variable)

    message_id = None
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            customer.email,
            'cs@julofinance.com',
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers['X-Message-Id']
    except Exception as e:
        status = 'error'
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception(
                'send_rejected_deletion_request_success_email_failed, data={} | err={}'.format(
                    customer, e
                )
            )

    EmailHistory.objects.create(
        to_email=customer.email,
        subject=subject,
        sg_message_id=message_id,
        template_code='hapus_akun_failed',
        customer=customer,
        status=str(status),
        error_message=error_message,
    )


@task(queue='retrofix_normal')
def update_deleted_application_status_to_186(limit_count=100_000):
    from juloserver.julo.services import process_application_status_change

    applications = Application.objects.filter(
        Q(product_line_id=ProductLineCodes.J1) | Q(workflow_id__name=WorkflowConst.JULO_STARTER),
        is_deleted=True,
    ).exclude(application_status_id=ApplicationStatusCodes.CUSTOMER_DELETED)[:limit_count]

    for app in applications.iterator():
        try:
            process_application_status_change(
                app.id,
                ApplicationStatusCodes.CUSTOMER_DELETED,
                change_reason='Customer Deleted',
            )
        except Exception as e:
            logger.exception(
                {
                    'action': 'update_deleted_application_status_to_186',
                    'message': 'cannot update application status to deleted',
                    'customer_id': app.customer.id,
                    'application_id': app.id,
                    'current_app_status': app.application_status_id,
                    'target_app_status': ApplicationStatusCodes.CUSTOMER_DELETED,
                    'error': str(e),
                },
            )


@task(queue='retrofix_normal')
def update_deletion_data_to_new_format(limit_count=75_000):
    from juloserver.customer_module.services.pii_vault import (
        detokenize_sync_object_model,
    )
    from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

    '''
    Retrofix deletion data to match with the new format after the remove deletion limit adjustment

    Parameters:
        limit_count (int): Limiter of the applications processed
    '''
    logger.info(
        {
            'action': 'update_deletion_data_to_new_format',
            'message': 'job triggered',
        },
    )
    customer_removals = CustomerRemoval.objects.filter(
        Q(customer__email__contains='.deleted')
        | Q(customer__nik__contains='555555')
        | Q(customer__nik__contains='666666')
        | Q(customer__nik__contains='777777')
        | Q(customer__nik__contains='888888')
        | Q(customer__nik__contains='999999'),
        customer__is_active=False,
    )[:limit_count]

    detokenized_customer_removals = detokenize_sync_object_model(
        PiiSource.CUSTOMER_REMOVAL, PiiVaultDataType.KEY_VALUE, customer_removals
    )

    logger.info(
        {
            'action': 'update_deletion_data_to_new_format',
            'message': 'updating {} customer removals'.format(len(detokenized_customer_removals)),
        },
    )

    for customer_removal in detokenized_customer_removals.iterator():
        try:
            with transaction.atomic():
                customer = customer_removal.customer
                applications = customer.application_set.all()
                last_application = customer.last_application
                nik = customer.get_nik

                # update user data
                user_field_changes = []
                is_user_data_updated = False
                user = customer_removal.customer.user
                if nik and nik == user.username:
                    edited_username = get_deletion_nik_format(customer.id)
                    if user.username != edited_username:
                        user_field_changes.append(
                            AuthUserFieldChange(
                                user=user,
                                customer=customer,
                                field_name='username',
                                old_value=user.username,
                                new_value=edited_username,
                            )
                        )
                        user.username = edited_username
                        is_user_data_updated = True

                if user.email and customer_removal.email:
                    edited_email = get_deletion_email_format(customer_removal.email, customer.id)
                    if user.email != edited_email:
                        user_field_changes.append(
                            AuthUserFieldChange(
                                user=user,
                                customer=customer,
                                field_name='email',
                                old_value=user.email,
                                new_value=edited_email,
                            )
                        )
                        user.email = edited_email
                        is_user_data_updated = True

                if is_user_data_updated:
                    AuthUserFieldChange.objects.bulk_create(user_field_changes)
                    user.save()

                # update customer data
                customer_field_changes = []
                is_customer_data_updated = False
                if customer.nik:
                    edited_nik = get_deletion_nik_format(customer.id)
                    if customer.nik != edited_nik:
                        customer_field_changes.append(
                            CustomerFieldChange(
                                customer=customer,
                                application=last_application,
                                field_name='nik',
                                old_value=customer.nik,
                                new_value=edited_nik,
                            )
                        )
                        customer.nik = edited_nik
                        is_customer_data_updated = True

                if customer.email:
                    edited_email = get_deletion_email_format(customer_removal.email, customer.id)
                    if customer.email != edited_email:
                        customer_field_changes.append(
                            CustomerFieldChange(
                                customer=customer,
                                application=last_application,
                                field_name='email',
                                old_value=customer.email,
                                new_value=edited_email,
                            )
                        )
                        customer.email = edited_email
                        is_customer_data_updated = True

                if is_customer_data_updated:
                    CustomerFieldChange.objects.bulk_create(customer_field_changes)
                    customer.save()

                # update application data
                application_field_changes = []
                deleted_applications = applications.filter(
                    is_deleted=True,
                )
                for application in deleted_applications:
                    if application.ktp:
                        edited_ktp = get_deletion_nik_format(application.customer_id)
                        if edited_ktp != application.ktp:
                            application_field_changes.append(
                                ApplicationFieldChange(
                                    application=application,
                                    field_name='ktp',
                                    old_value=application.ktp,
                                    new_value=edited_ktp,
                                )
                            )
                            application.ktp = edited_ktp

                    if application.email:
                        edited_email = get_deletion_email_format(
                            customer_removal.email, application.customer_id
                        )
                        if edited_email != application.email:
                            application_field_changes.append(
                                ApplicationFieldChange(
                                    application=application,
                                    field_name='email',
                                    old_value=application.email,
                                    new_value=edited_email,
                                )
                            )
                            application.email = edited_email

                ApplicationFieldChange.objects.bulk_create(application_field_changes)
                bulk_update(
                    deleted_applications,
                    update_fields=['ktp', 'email', 'udate'],
                )
        except Exception as e:
            logger.error(
                {
                    'action': 'update_deletion_data_to_new_format',
                    'message': 'error updating customer removals',
                    'exception': str(e),
                    'customer_id': customer_removal.customer_id,
                    'customer_removal_id': customer_removal.id,
                },
            )

    logger.info(
        {
            'action': 'update_deletion_data_to_new_format',
            'message': 'success updating {} customer removals'.format(
                len(detokenized_customer_removals)
            ),
        },
    )

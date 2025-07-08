from datetime import datetime
from juloserver.julo.utils import delete_public_file_from_oss
from django.conf import settings
from django.template.loader import get_template
from django.db.models import Q
from juloserver.julo.models import ApplicationHistory, Customer, FeatureSetting
from juloserver.customer_module.models import AccountDeletionRequest
from juloserver.customer_module.constants import (
    AccountDeletionFeatureName,
    AccountDeletionRequestStatuses,
    ongoing_account_deletion_request_statuses,
)
from juloserver.customer_module.services.email import send_email_with_html
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.customer_module.utils.utils_crm_v1 import (
    is_account_status_deleteable,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.pin.utils import get_first_name
from juloserver.customer_module.services.email import (
    generate_image_attachment,
)

import logging

logger = logging.getLogger(__name__)


def delete_ktp_and_selfie_file_from_oss(
    image_ktp_filepath: str,
    image_selfie_filepath: str,
):
    delete_public_file_from_oss(
        settings.OSS_PUBLIC_BUCKET,
        image_ktp_filepath,
    )
    delete_public_file_from_oss(
        settings.OSS_PUBLIC_BUCKET,
        image_selfie_filepath,
    )
    return


def send_web_account_deletion_received_success(
    customer: Customer,
):

    first_name = get_first_name(customer)

    subject = "Permintaan Hapus Akun Diterima"
    variable = {"first_name": first_name}
    template = get_template('website_hapus_akun_success.html')
    html_content = template.render(variable)

    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=customer.email,
        sender_email='cs@julo.co.id',
        template_code='website_hapus_akun_success',
    )


def send_web_account_deletion_received_failed(
    email: str,
):

    first_name = get_first_name(None)

    subject = "Permintaan Hapus Akun Gagal"
    variable = {"first_name": first_name}
    template = get_template('website_hapus_akun_failed.html')
    html_content = template.render(variable)

    send_email_with_html(
        subject,
        html_content,
        email,
        'cs@julo.co.id',
        'website_hapus_akun_failed',
    )


def forward_web_account_deletion_request_to_ops(
    fullname,
    phone,
    email,
    reason,
    details,
    image_ktp,
    image_ktp_file_path,
    image_selfie,
    image_selfie_file_path,
):
    subject_prefix = ''
    if settings.ENVIRONMENT != 'prod':
        subject_prefix = '[Squad8QAtest] '

    subject = subject_prefix + "Permintaan Hapus Akun"
    template = get_template('website_hapus_akun_forward_to_cs.html')
    variable = {
        "fullname": fullname,
        "phone": phone,
        "email": email,
        "reason": reason,
        "details": details,
    }
    html_content = template.render(variable)
    sender_email = email
    recipient_email = "cs@julo.co.id"

    image_ktp_extension = image_ktp_file_path.split('.')[-1]
    image_ktp_attachment = generate_image_attachment(
        image=image_ktp,
        filename="ktp-" + fullname,
        ext=image_ktp_extension,
    )

    image_selfie_extension = image_selfie_file_path.split('.')[-1]
    image_selfie_attachment = generate_image_attachment(
        image=image_selfie,
        filename="selfie-" + fullname,
        ext=image_selfie_extension,
    )

    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=recipient_email,
        sender_email=sender_email,
        template_code='website_hapus_akun_forward_to_cs',
        attachments=[image_ktp_attachment, image_selfie_attachment],
        fullname=fullname,
    )


def mark_request_deletion_manual_deleted(agent, customer, reason):
    if not customer:
        return

    AccountDeletionRequest.objects.filter(
        customer=customer,
        request_status__in=ongoing_account_deletion_request_statuses,
    ).update(
        request_status=AccountDeletionRequestStatuses.MANUAL_DELETED,
        agent=agent,
        verdict_date=datetime.now(),
        verdict_reason=reason,
    )


def process_revert_applications_status_deletion(customer, change_reason, changed_by=None):
    if not customer:
        return

    for application in customer.application_set.all():
        if application.application_status_id != ApplicationStatusCodes.CUSTOMER_ON_DELETION:
            continue

        last_app_status = ApplicationHistory.objects.filter(
            application=application,
        ).last()
        if not last_app_status:
            logger.info(
                {
                    'action': 'process_revert_applications_status_deletion',
                    'message': """not reverting application's status:
                        there is no application_history for this application""",
                    'customer_id': customer.id,
                    'account_id': application.id,
                }
            )
            return

        ApplicationHistory.objects.create(
            application=application,
            status_old=last_app_status.status_new,
            status_new=last_app_status.status_old,
            change_reason=change_reason,
            changed_by=changed_by,
        )
        application.update_safely(
            application_status_id=last_app_status.status_old,
        )


def is_customer_manual_deletable(customer, account=None):
    '''
    Checks if customer is eligible for a manual deletion

    Args:
        customer (Customer): The Customer object
        account (Account): The Account of the customer

    Returns:
        bool: Is eligible for a manual soft deletion
        string: Message if not eligible
    '''
    if not account:
        account = customer.account

    if account and not is_account_status_deleteable(account.status_id):
        return False, 'Account status not deletable'

    is_deleted = is_deleteable_application_already_deleted(customer)
    if is_deleted:
        return False, 'Deleteable applications already deleted'

    return True, ''


def get_deleteable_application(customer):
    allowed_product_line_deletion = get_allowed_product_line_for_deletion()
    return customer.application_set.filter(
        Q(product_line_id__in=allowed_product_line_deletion) | Q(product_line__isnull=True)
    ).order_by('cdate')


def customer_deleteable_application_check(customer):
    if not customer.application_set.exists():
        return True

    deleteable_applications = get_deleteable_application(customer)
    if deleteable_applications:
        return True

    return False


def is_complete_deletion(customer):
    '''
    Check whether the customer allowed to be full deleted (customer, account, user, and application)

    Args:
        customer (Customer): The target customer

    Return:
        bool: True means the customer allowed to be full deleted
    '''

    return customer.application_set.count() == get_deleteable_application(customer).count()


def is_deleteable_application_already_deleted(customer):
    deletable_applications = get_deleteable_application(customer)
    if not deletable_applications.exists():
        return False

    if deletable_applications.filter(Q(is_deleted=False) | Q(is_deleted__isnull=True)).exists():
        return False

    return True


def get_allowed_product_line_for_deletion():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=AccountDeletionFeatureName.SUPPORTED_PRODUCT_LINE_DELETION,
    ).first()

    default_product_lines = [
        None,
        ProductLineCodes.J1,
        ProductLineCodes.JTURBO,
        ProductLineCodes.MTL1,
        ProductLineCodes.MTL2,
        ProductLineCodes.CTL1,
        ProductLineCodes.CTL2,
        ProductLineCodes.STL1,
        ProductLineCodes.STL2,
        ProductLineCodes.LOC,
    ]
    if not feature_setting or not feature_setting.is_active:
        return default_product_lines

    if not feature_setting.parameters['supported_product_line']:
        return default_product_lines

    supported_plines = feature_setting.parameters['supported_product_line']
    for default_product_line in default_product_lines:
        if default_product_line not in supported_plines:
            supported_plines.append(default_product_line)

    return supported_plines

from builtins import str
import logging
from celery import task
from requests import codes

from .constants import PRIVY_IMAGE_TYPE, CustomerStatusPrivy
from .services import (
    create_privy_user,
    upload_document_to_privy,
    get_privy_customer_data,
    re_upload_privy_user_photo,
    get_failover_feature,
)

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.models import (Application,
                                    MobileFeatureSetting,
                                    AwsFaceRecogLog, Image,
                                    Loan)
from juloserver.julo.exceptions import InvalidBankAccount
from juloserver.disbursement.constants import NameBankValidationStatus
from ..julo.constants import DigitalSignatureProviderConstant
from .services.privy_integrate import (check_privy_registeration_verified,
                                       upload_document_and_verify_privy)
from juloserver.julo.utils import have_pn_device
from .constants import DocumentStatusPrivy
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo_privyid.clients.privy import JuloPrivyIDClient
from juloserver.julo_privyid.services.privy_integrate import (
    check_status_privy_user,
    update_digital_signature_face_recognition
)
from juloserver.julo_privyid.exceptions import JuloPrivyLogicException, \
    JuloPrivyException

logger = logging.getLogger(__name__)


@task(queue='application_normal')
def create_new_privy_user(application_id):
    failover = get_failover_feature()
    application = Application.objects.get_or_none(pk=application_id)
    is_julo_one = application.is_julo_one()
    is_grab = application.is_grab()

    if not application:
        logger.info({
            'action': 'create_new_privy_user',
            'application_id': application_id,
            'message': 'Application Not Found'
        })
        return False

    privy_customer_data = get_privy_customer_data(application.customer)
    if privy_customer_data:
        digital_signature_face_result = None
        aws_data = AwsFaceRecogLog.objects.filter(customer=application.customer, application=application,
                                                  is_indexed=True,
                                                  is_quality_check_passed=True).last()
        if aws_data:
            digital_signature_face_result = aws_data.digital_signature_face_result
            if not digital_signature_face_result.is_used_for_registration:
                digital_signature_face_result.update_safely(
                    is_used_for_registration=False,
                    digital_signature_provider=DigitalSignatureProviderConstant.PRIVY,
                    is_passed=None)
        logger.info({
            'action': 'create_new_privy_user',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Customer has been registered to privyid'
        })
        if privy_customer_data.privy_customer_status == CustomerStatusPrivy.INVALID:
            if not failover:
                if is_julo_one or is_grab:
                    status_change = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
                    change_reason = 'Dokumen pendukung (KTP / Selfie / Other) belum diganti'
                else:
                    status_change = ApplicationStatusCodes.DIGISIGN_FAILED
                    change_reason = 'Dokumen pendukung (KTP / Selfie / Other) belum diganti'
                process_application_status_change(application.id, status_change, change_reason)
            else:
                if is_julo_one or is_grab:
                    status_change = ApplicationStatusCodes.LOC_APPROVED
                    change_reason = 'Dialihkan ke tanda tangan JULO'
                else:
                    status_change = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
                    change_reason = 'Dialihkan ke tanda tangan JULO'
                process_application_status_change(application.id, status_change, change_reason)
        if privy_customer_data.privy_customer_status in [CustomerStatusPrivy.VERIFIED,
                                                         CustomerStatusPrivy.REGISTERED,
                                                         CustomerStatusPrivy.WAITING]:
            task_check_privy_registeration_verified.apply_async((application.customer,))
        return False

    registered_data = create_privy_user(application)
    if registered_data:
        task_check_privy_registeration_verified.apply_async((application.customer,))

    if not registered_data:
        logger.info({
            'action': 'create_new_privy_user',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Customer failed to register to privyid'
        })
        return False

    return True

@task(name='update_data_privy_user')
def update_data_privy_user(application_id):
    application = Application.objects.get_or_none(pk=application_id)

    if not application:
        logger.info({
            'action': 'update_data_privy_user',
            'application_id': application_id,
            'message': 'Application Not Found'
        })
        return False

    privy_customer_data = get_privy_customer_data(application.customer)
    if not privy_customer_data:
        logger.info({
            'action': 'update_data_privy_user',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Customer did not registered to privyid yet'
        })
        return False

    user_token = privy_customer_data.privy_customer_token
    updated_data = []
    for category in list(PRIVY_IMAGE_TYPE.keys()):
        updated = re_upload_privy_user_photo(category, user_token, application_id)

        if updated:
            updated_data.append(updated_data)

    if not updated_data:
        logger.info({
            'action': 'update_data_privy_user',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Failed to update data customer to privyid'
        })
        return False

    return True

@task(name='upload_document_privy')
def upload_document_privy(application_id):
    application = Application.objects.get_or_none(pk=application_id)

    if not application:
        logger.info({
            'action': 'upload_document_privy',
            'application_id': application_id,
            'message': 'Application Not Found'
        })
        return False

    privy_customer_data = get_privy_customer_data(application.customer)
    if not privy_customer_data:
        logger.info({
            'action': 'upload_document_privy',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Customer did not registered to privyid yet'
        })
        return False

    document_data = upload_document_to_privy(privy_customer_data, application)

    if not document_data:
        logger.info({
            'action': 'upload_document_privy',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Upload document to privy failed'
        })
        return False

    return True


@task(name='update_existing_privy_customer')
def update_existing_privy_customer(application_id):
    reuploaded = False
    failover = get_failover_feature()
    application = Application.objects.get_or_none(pk=application_id)

    if not application:
        logger.info({
            'action': 'update_existing_privy_customer',
            'application_id': application_id,
            'message': 'Application Not Found'
        })
        return False

    privy_customer_data = get_privy_customer_data(application.customer)
    if not privy_customer_data:
        logger.info({
            'action': 'update_existing_privy_customer',
            'application_id': application_id,
            'customer_id': application.customer_id,
            'message': 'Customer did not registered to privyid yet'
        })
        return False

    is_julo_one = application.is_julo_one()
    if privy_customer_data.privy_customer_status in [CustomerStatusPrivy.WAITING,
                                                     CustomerStatusPrivy.VERIFIED,
                                                     CustomerStatusPrivy.REGISTERED]:
        task_check_privy_registeration_verified.apply_async((application.customer,))
        return False
    user_token = privy_customer_data.privy_customer_token
    status_flag = False
    reupload_image_types = ['selfie_reupload', 'ktp_reupload']
    for reuploaded_image_type in reupload_image_types:
        reuploaded_image = Image.objects.filter(image_source=application_id,
                                                image_type=PRIVY_IMAGE_TYPE[reuploaded_image_type]
                                                ).last()
        if reuploaded_image:
            if reuploaded_image.image_type == PRIVY_IMAGE_TYPE[reuploaded_image_type]:
                reuploaded = re_upload_privy_user_photo(reuploaded_image_type,
                                                        user_token, application_id)
                status_flag = status_flag or reuploaded
    if not status_flag:
        if not failover:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.DIGISIGN_FAILED,
                'Dokumen pendukung (KTP / Selfie / Other) tidak tepat'
            )
        else:
            if is_julo_one:
                status_change = ApplicationStatusCodes.LOC_APPROVED
                change_reason = 'Dialihkan ke tanda tangan JULO'
            else:
                status_change = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
                change_reason = 'Dialihkan ke tanda tangan JULO'
            process_application_status_change(application.id, status_change, change_reason)
        return
    task_check_privy_registeration_verified.apply_async((application.customer, True,))


@task(queue='application_high')
def send_reminder_sign_sphp(application_id):
    """sub task to send pn on sphp reminderr"""
    from juloserver.julo_privyid.services.privy_integrate import get_privy_document_data
    application = Application.objects.get(pk=application_id)
    device = application.device
    document = get_privy_document_data(application)
    if not document:
        return
    if document.privy_document_status != DocumentStatusPrivy.IN_PROGRESS:
        return

    if have_pn_device(device):
        logger.info(
            {
                "action": "sending_sphp_sign_ready_reminder",
                "application_id": application_id,
                "device_id": device.id,
                "gcm_reg_id": device.gcm_reg_id,
            }
        )

        julo_pn_client = get_julo_pn_client()
        julo_pn_client.send_reminder_sign_sphp(
            application_id
        )


@task(name='task_check_privy_registeration_verified')
def task_check_privy_registeration_verified(customer, is_updated_customer=False, retry_value=0):
    application = customer.application_set.regular_not_deletes().last()
    if not application:
        raise JuloPrivyLogicException('Application not found for customer '
                                      'id {}'.format(customer.id))
    failover = get_failover_feature()
    user_data = None
    privy_customer = get_privy_customer_data(customer)
    user_token = privy_customer.privy_customer_token
    user_data, response = check_status_privy_user(user_token, application)
    if retry_value > JuloPrivyIDClient.TIMEOUT_ATTEMPTS:
        raise JuloPrivyException("Failed Register for customer {}".format(customer.id))
    try:
        if user_data or (response and response['code'] > codes.internal_server_error):
            logger.info({
                "action": "task_check_privy_registeration_verified",
                "customer": customer.id,
                "retry_value": retry_value,
                "status": user_data.privy_customer_status
            })
            if user_data.privy_customer_status in [CustomerStatusPrivy.REGISTERED,
                                                   CustomerStatusPrivy.VERIFIED,
                                                   CustomerStatusPrivy.INVALID,
                                                   CustomerStatusPrivy.REJECTED]:
                if not is_updated_customer:
                    update_digital_signature_face_recognition(application, user_data)
            else:
                task_check_privy_registeration_verified.apply_async(
                    (customer,), {'retry_value': retry_value + 1},
                    countdown=JuloPrivyIDClient.API_CALL_TIME_GAP*(retry_value+1))
                return
        else:
            raise JuloPrivyException('Julo privy api exception')

        if user_data.reject_reason is not None:
            if not failover:
                if user_data.privy_customer_status == CustomerStatusPrivy.INVALID:
                    if application.is_julo_one() or application.is_grab():
                        status = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
                    else:
                        status = ApplicationStatusCodes.DIGISIGN_FAILED
                    reject_message = 'Unggah ulang ' + user_data.reject_reason
                else:
                    reject_message = user_data.reject_reason
                    if application.is_julo_one() or application.is_grab():
                        status = ApplicationStatusCodes.APPLICATION_DENIED
                    else:
                        status = ApplicationStatusCodes.DIGISIGN_FAILED

                process_application_status_change(
                    application.id,
                    status,
                    reject_message
                )
            else:
                if user_data.privy_customer_status == CustomerStatusPrivy.INVALID:
                    reject_message = user_data.reject_reason.split('.', 1)[-1].lstrip()
                    reject_message = reject_message + ', dialihkan ke tanda tangan JULO'
                else:
                    reject_message = user_data.reject_reason + ', dialihkan ke tanda tangan JULO'

                if application.is_julo_one() or application.is_grab():
                    status_change = ApplicationStatusCodes.LOC_APPROVED
                else:
                    status_change = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
                process_application_status_change(
                    application.id,
                    status_change,
                    reject_message,
                    'Failover to Julo'
                )
    except InvalidBankAccount as e:
        if 'go_to_175' in str(e):
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                'Name validation failed',
                NameBankValidationStatus.INVALID_NOTE.format(application.app_version))

    if application.is_julo_one or application.is_grab():
        if user_data.privy_customer_status not in [CustomerStatusPrivy.REJECTED,
                                                   CustomerStatusPrivy.INVALID]:
            status_change = ApplicationStatusCodes.LOC_APPROVED
            change_reason = 'Credit limit activated'
            process_application_status_change(application.id, status_change, change_reason)
    else:
        upload_document_and_verify_privy(application.customer)

from builtins import str
from builtins import range
import os
import logging
import requests
import tempfile
import time

from ..clients import get_julo_privyid_client
from ..models import PrivyCustomerData
from ..models import PrivyDocumentData
from ..utils import convert_str_to_datetime
from ..constants import PRIVY_IMAGE_TYPE, CustomerStatusPrivy, DocumentStatusPrivy
from ..services import get_failover_feature
from ..clients.privyid import JuloPrivyIDClient

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.models import (AwsFaceRecogLog, Document, Application)
from juloserver.julo.constants import DigitalSignatureProviderConstant
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tasks import upload_document
from juloserver.julo.exceptions import JuloException

from datetime import datetime, timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)
privy_client = get_julo_privyid_client()


# Customer Section

def store_privy_customer_data(customer, data):
    reject_reason = None
    if 'reject' in data:
        if data['reject']['handlers']:
            reject_category = ''
            for handler in data['reject']['handlers']:
                reject_category += handler['category'] + '. '
        else:
            reject_category = ''
        reject_reason = '{}{}-{}'.format(reject_category,
                                         data['reject']['code'],
                                         data['reject']['reason'])

    privy_data = {
        'customer': customer,
        # when customer has not verified/registered privyid will be None
        'privy_id': data.get('privyId', None),
        'privy_customer_token': data['userToken'],
        'privy_customer_status': data['status'],
        'reject_reason': reject_reason
    }

    privy_customer_data = PrivyCustomerData.objects.get_or_none(
        privy_customer_token=data['userToken']
    )

    if privy_customer_data:
        privy_customer_data.update_safely(**privy_data)
    else:
        privy_customer_data = PrivyCustomerData.objects.create(**privy_data)

    return privy_customer_data


def get_privy_customer_data(customer):
    if not hasattr(customer, 'privycustomerdata'):
        return None

    privy_customer_data = customer.privycustomerdata

    return privy_customer_data


def create_privy_user(application):
    response = privy_client.registration_proccess(application)

    digital_signature_face_result = None
    aws_data = AwsFaceRecogLog.objects.filter(customer=application.customer, application=application,
                                              is_indexed=True,
                                              is_quality_check_passed=True).last()
    if aws_data:
        digital_signature_face_result = aws_data.digital_signature_face_result
        if not digital_signature_face_result.is_used_for_registration:
            digital_signature_face_result.update_safely(
                is_used_for_registration=False,
                digital_signature_provider=DigitalSignatureProviderConstant.PRIVY)

    if not response or 'data' not in response:
        failover = get_failover_feature()
        reject_message = 'privy_registration_failed. ' + \
                         str(response['errors'][0]['field']) + " Error: "
        for i in range(len(response['errors'][0]['messages'])):
            reject_message += str(response['errors'][0]['messages'][i]) + ". "
        if not failover:
            if application.is_julo_one() or application.is_grab():
                status_change = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
                change_reason = reject_message
            else:
                status_change = ApplicationStatusCodes.DIGISIGN_FAILED
                change_reason = reject_message
            process_application_status_change(application.id, status_change, change_reason)
        else:
            if application.is_julo_one() or application.is_grab():
                status_change = ApplicationStatusCodes.LOC_APPROVED
            else:
                status_change = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
            process_application_status_change(
                application.id,
                status_change,
                reject_message + '_failoveron',
                'Failover to Julo'
            )
        return None

    data = response['data']
    privy_user_data = store_privy_customer_data(application.customer, data)
    if response['data']:
        if digital_signature_face_result:
            digital_signature_face_result.update_safely(
                is_used_for_registration=True,
                digital_signature_provider=DigitalSignatureProviderConstant.PRIVY)

    return privy_user_data


def check_status_privy_user(privy_customer_token, application):
    response = privy_client.registration_status(privy_customer_token, application.id)

    if not response or 'data' not in response:
        return None, response

    data = response['data']
    privy_user_data = store_privy_customer_data(application.customer, data)

    return privy_user_data, response


def re_upload_privy_user_photo(category, user_token, application_id):
    if category not in list(PRIVY_IMAGE_TYPE.keys()):
        return False

    response = privy_client.reregistration_photos(category, user_token, application_id)

    if not response or response['code'] not in (200, 201,):
        return False

    return True


# Document Section

def store_privy_document_data(application, privy_customer, data):
    document_data = {
        'application_id': application,
        'privy_customer': privy_customer,
        'privy_document_token': data['docToken'],
        # we not got documentStatus when is just created
        'privy_document_status': data.get('documentStatus', 'Initial'),
        'privy_document_url': data['urlDocument']
    }

    privy_document_data = PrivyDocumentData.objects.get_or_none(
        privy_document_token=data['docToken']
    )

    if privy_document_data:
        if privy_document_data.privy_document_status == DocumentStatusPrivy.COMPLETED:
            return privy_document_data
        privy_document_data.update_safely(**document_data)
    else:
        privy_document_data = PrivyDocumentData.objects.create(**document_data)

    return privy_document_data


def get_privy_document_data(application):
    document_data = PrivyDocumentData.objects.get_or_none(application_id=application)

    return document_data


def upload_document_to_privy(privy_customer, application):
    response = privy_client.document_upload(privy_customer.privy_id, application.id)

    if not response or 'data' not in response:
        return None

    data = response['data']

    privy_document_data = store_privy_document_data(application, privy_customer, data)
    return privy_document_data


def check_privy_document_status(privy_document, application):
    response = privy_client.document_status(privy_document.privy_document_token, application.id)

    if not response or 'data' not in response:
        return None

    data = response['data']
    document_data = store_privy_document_data(application, privy_document.privy_customer, data)

    if data['documentStatus'] == DocumentStatusPrivy.COMPLETED:
        download_url = data['download']['url']
        if application.status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            if download_url:
                upload_sphp_privy_doc(download_url, application)
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                'privy_triggered'
            )

    return document_data


def proccess_signing_document(document_token, otp_token, application_id):
    response = privy_client.document_multiple_sign([document_token], otp_token, application_id)

    if not response or response['code'] not in (200, 201,):
        return False

    return True


# OTP Section

def store_otp_token(privy_id, data):
    redis_client = get_redis_client()

    otp_token = data['token']
    created_date = convert_str_to_datetime(data['created_at'], '%Y-%m-%dT%H:%M:%S.000+07:00')
    expired_date = convert_str_to_datetime(data['expired_at'], '%Y-%m-%dT%H:%M:%S.000+07:00')
    delta_time = expired_date - created_date

    redis_client.set(privy_id, otp_token, delta_time)


def get_otp_token(privy_id, application_id, create_flag=False):
    redis_client = get_redis_client()
    otp_token = redis_client.get(privy_id)

    if otp_token and not create_flag:
        return otp_token

    response = privy_client.create_otp_token(privy_id, application_id)

    if not response or 'data' not in response:
        return None

    data = response['data']
    # store otp token to redis
    store_otp_token(privy_id, data)

    return data['token']


def request_otp_to_privy(otp_token, application_id):
    response = privy_client.request_user_otp(otp_token, application_id)

    if not response or response['code'] not in (200, 201, 400):
        return False
    if response['code'] in (400,):
        application = Application.objects.get(id=application_id)
        customer = application.customer
        privy_customer = get_privy_customer_data(customer)
        otp_token = get_otp_token(privy_customer.privy_id, application.id, create_flag=True)
        return_status = request_otp_to_privy(otp_token, application.id)
        return return_status
    return True


def confirm_otp_to_privy(otp_code, otp_token, application_id):
    response = privy_client.confirm_user_otp(otp_code, otp_token, application_id)

    if not response or response['code'] not in (200, 201,):
        return False

    return True


def is_privy_custumer_valid(application):
    if not application:
        return False
    customer = application.customer
    privy_customer = get_privy_customer_data(customer)
    return privy_customer


def update_digital_signature_face_recognition(application, user_data):
    aws_data = AwsFaceRecogLog.objects.filter(customer=application.customer, application=application,
                                              is_indexed=True,
                                              is_quality_check_passed=True).last()
    if not aws_data:
        return False
    digital_signature_face_result = aws_data.digital_signature_face_result
    if not digital_signature_face_result:
        return
    if user_data.privy_customer_status in [CustomerStatusPrivy.REGISTERED,
                                           CustomerStatusPrivy.VERIFIED]:
        if digital_signature_face_result.is_used_for_registration:
            digital_signature_face_result.update_safely(is_passed=True)
        else:
            digital_signature_face_result.update_safely(is_passed=None)
        return True
    elif user_data.privy_customer_status in [CustomerStatusPrivy.REJECTED,
                                             CustomerStatusPrivy.INVALID]:
        if user_data.reject_reason is not None:
            reject_code = user_data.reject_reason.split('-')[0].split(' ')[-1]
            if reject_code in ['PRVS003','PRVS006']:
                digital_signature_face_result.update_safely(is_passed=False)
            else:
                digital_signature_face_result.update_safely(is_passed=None)
    return False


def upload_sphp_privy_doc(url, application):
    from juloserver.followthemoney.tasks import generate_sphp

    now = datetime.now()
    filename = '{}_{}_{}_{}.pdf'.format(
        application.fullname,
        application.application_xid,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S"))
    file_path = os.path.join(tempfile.gettempdir(), filename)
    download_req = requests.get(url, allow_redirects=True)
    open(file_path, 'wb').write(download_req.content)
    document_types = ['sphp_privy', 'sphp_julo']
    document = Document.objects.filter(application_xid=application.application_xid,
                                       document_type__in=document_types).last()
    if not document:
        generate_sphp(application.id)
        document = Document.objects.filter(application_xid=application.application_xid,
                                           document_type__in=document_types).last()

    if document:
        upload_document(document.id, file_path)
        document.document_type = 'sphp_privy'
        document.save()


def check_privy_registeration_verified(customer, is_updated_customer=False):
    failover = get_failover_feature()
    user_data = None
    application = customer.application_set.regular_not_deletes().last()
    privy_customer = get_privy_customer_data(customer)
    user_token = privy_customer.privy_customer_token
    timeout = timezone.localtime(timezone.now()) + timedelta(
        minutes=JuloPrivyIDClient.TIMEOUT_DURATION)
    restart_time = timezone.localtime(timezone.now())
    while True:
        if timezone.localtime(timezone.now()) > timeout:
            if failover:
                if application.is_julo_one() or application.is_grab():
                    status_change = ApplicationStatusCodes.LOC_APPROVED
                else:
                    status_change = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
                process_application_status_change(
                    application.id,
                    status_change,
                    'Registrasi akun tanda tangan digital gagal, '
                    'dialihkan ke tanda tangan JULO',
                    'Failover to Julo')
                return
            error_message = "The privy_registeration timed out after {}".format(
                JuloPrivyIDClient.TIMEOUT_DURATION)
            raise JuloException(error_message)
        if timezone.localtime(timezone.now()) > restart_time:
            user_data, response = check_status_privy_user(user_token, application)
            restart_time = timezone.localtime(timezone.now()) + timedelta(
                seconds=JuloPrivyIDClient.API_CALL_TIME_GAP)
            if user_data:
                if user_data.privy_customer_status in [CustomerStatusPrivy.REGISTERED,
                                                       CustomerStatusPrivy.VERIFIED,
                                                       CustomerStatusPrivy.INVALID,
                                                       CustomerStatusPrivy.REJECTED]:
                    if not is_updated_customer:
                        update_digital_signature_face_recognition(application, user_data)
                    break
                else:
                    continue

    if user_data.reject_reason is not None:
        if not failover:
            if user_data.privy_customer_status == CustomerStatusPrivy.INVALID:
                if application.is_julo_one():
                    status = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
                else:
                    status = ApplicationStatusCodes.DIGISIGN_FAILED
                reject_message = 'Unggah ulang ' + user_data.reject_reason
            else:
                reject_message = user_data.reject_reason
            if application.is_julo_one() or application.is_grab():
                status = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
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

    if application.is_julo_one() or application.is_grab():
        if user_data.privy_customer_status not in [CustomerStatusPrivy.REJECTED,
                                                   CustomerStatusPrivy.INVALID]:
            status_change = ApplicationStatusCodes.LOC_APPROVED
            change_reason = 'Credit limit activated'
            process_application_status_change(application.id, status_change, change_reason)
    else:
        upload_document_and_verify_privy(application.customer)


def upload_document_and_verify_privy(customer):
    from juloserver.julo_privyid.tasks import upload_document_privy

    application = customer.application_set.regular_not_deletes().last()

    document_max_retry = 3
    for upload_retry_count in range(document_max_retry):
        privy_customer = get_privy_customer_data(customer)
        if not privy_customer:
            error_message = 'No Customer Found for application - {} not found'.format(
                application.id)
            raise JuloException(error_message)
        if privy_customer.privy_customer_status in [CustomerStatusPrivy.REJECTED,
                                                    CustomerStatusPrivy.INVALID]:
            return
        if privy_customer.privy_customer_status not in CustomerStatusPrivy.ALLOW_UPLOAD:
            error_message = 'Customer not in Verified/Registered status - {} not found'.format(
                application.id)
            raise JuloException(error_message)

        privy_document = get_privy_document_data(application)
        if privy_document:
            break

        upload_document_privy.delay(application.id)
        time.sleep(JuloPrivyIDClient.API_CALL_TIME_GAP)
        if document_max_retry == upload_retry_count + 1:
            privy_document = get_privy_document_data(application)
            if privy_document:
                break
            else:
                if not get_failover_feature():
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.DIGISIGN_FAILED,
                        'Gagal unggah dokumen SPHP untuk tanda tangan digital'
                    )
                else:
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                        'Gagal unggah dokumen SPHP untuk tanda tangan digital, '
                        'dialihkan ke tanda tangan JULO',
                        'Failover to Julo'
                    )
                return

    privy_document = get_privy_document_data(application)
    if not privy_document:
        error_message = 'The privy document for application - {} not found'.format(
            application.id)
        raise JuloException(error_message)
    timout_time = timezone.localtime(timezone.now()) + timedelta(minutes=30)
    reset_time = timezone.localtime(timezone.now())
    while True:
        if timezone.localtime(timezone.now()) > reset_time:
            document_data = check_privy_document_status(privy_document, application)
            reset_time = timezone.localtime(timezone.now()) + timedelta(
                seconds=JuloPrivyIDClient.API_CALL_TIME_GAP)
            if not document_data:
                error_message = 'No response from document status API - {} not found'.format(
                    application.id)
                raise JuloException(error_message)

            if document_data.privy_document_status == DocumentStatusPrivy.IN_PROGRESS:
                break
        if timezone.localtime(timezone.now()) > timout_time:
            error_message = "The privy_registeration timed out after {}".format(
                JuloPrivyIDClient.TIMEOUT_DURATION)
            raise JuloException(error_message)

    process_application_status_change(
        application.id,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        "Privy Document uploaded successfully",
    )


def store_privy_document_data_julo_one(loan, privy_customer, data):
    document_data = {
        "loan_id": loan,
        "privy_customer": privy_customer,
        "privy_document_token": data["docToken"],
        # we not got documentStatus when is just created
        "privy_document_status": data.get("documentStatus", "Initial"),
        "privy_document_url": data["urlDocument"],
    }

    privy_document_data = PrivyDocumentData.objects.get_or_none(
        privy_document_token=data["docToken"]
    )

    if privy_document_data:
        if privy_document_data.privy_document_status == DocumentStatusPrivy.COMPLETED:
            return privy_document_data
        privy_document_data.update_safely(**document_data)
    else:
        privy_document_data = PrivyDocumentData.objects.create(**document_data)

    return privy_document_data

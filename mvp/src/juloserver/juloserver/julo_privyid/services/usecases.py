from builtins import str
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo_privyid.clients import get_julo_privy_client
from juloserver.julo_privyid.exceptions import (JuloPrivyLogicException,
                                                PrivyDocumentExistException,
                                                PrivyNotFailoverException,
                                                PrivyApiResponseException)
from juloserver.julo_privyid.models import PrivyDocument
from juloserver.julo_privyid.services.common import get_privy_feature
from juloserver.julo_privyid.services.common import get_failover_feature
from juloserver.julo_privyid.services.common import upload_privy_sphp_document
from juloserver.julo_privyid.services.common import store_privy_api_data
from .privy_integrate import get_privy_customer_data
from ..constants import CustomerStatusPrivy, DocumentStatusPrivy
from .privy_services import (get_otp_token_privy, request_otp_to_privy,
                             )
from juloserver.julo_privyid.services.privy_integrate import store_privy_customer_data
from juloserver.julo_privyid.services.privy_integrate import store_privy_document_data_julo_one
from juloserver.julo.services import process_application_status_change
from juloserver.loan.services.sphp import accept_julo_sphp
from ..constants import PrivyReUploadCodes
from juloserver.julo.models import FeatureSetting, Image
from juloserver.julo.constants import FeatureNameConst, ApplicationStatusCodes
from .privy_services import get_image_for_reupload

privy_client = get_julo_privy_client()


def check_document_status_for_upload(user, loan_xid):
    loan = user.customer.loan_set.filter(
        loan_xid=loan_xid,
        loan_status=LoanStatusCodes.INACTIVE
    ).last()
    if not loan:
        raise JuloPrivyLogicException(
            "Cannot found inactive loan with loan_id: %s" % loan_xid)

    is_privy_mode = get_privy_feature()
    is_failover_active = get_failover_feature()
    if not is_privy_mode:
        return 'not_exist', is_privy_mode, is_failover_active

    privy_document = PrivyDocument.objects.get_or_none(loan_id=loan.id)
    if not privy_document:
        return 'not_exist', is_privy_mode, is_failover_active

    data, api_data = privy_client.get_document_status(privy_document.privy_document_token)
    store_privy_api_data.delay(loan_xid, api_data)

    document_data = {
        'loan_id': loan,
        'privy_customer': privy_document.privy_customer,
        'privy_document_token': data['docToken'],
        'privy_document_status': data.get('documentStatus', 'Initial'),
        'privy_document_url': data['urlDocument']
    }

    privy_document = PrivyDocument.objects.get_or_none(privy_document_token=data['docToken'])
    if not privy_document:
        privy_document = PrivyDocument.objects.create(**document_data)
        return privy_document.privy_document_status, is_privy_mode, is_failover_active

    privy_document.update_safely(**document_data)

    if data.get('documentStatus') == DocumentStatusPrivy.COMPLETED:
        download_url = data['download']['url']
        application = loan.account.application_set.last()
        if loan.status == LoanStatusCodes.INACTIVE:
            accept_julo_sphp(loan, "Privy")
            upload_privy_sphp_document.delay(
                download_url, loan.id, loan.loan_xid, application.fullname)

    return privy_document.privy_document_status, is_privy_mode, is_failover_active


def upload_document_privy_service(user, loan_xid, data):
    loan = user.customer.loan_set.filter(
        loan_xid=loan_xid,
        loan_status=LoanStatusCodes.INACTIVE
    ).last()
    if not loan or loan.status != LoanStatusCodes.INACTIVE:
        raise JuloPrivyLogicException(
            "Cannot found inactive loan with loan_xid: %s" % loan_xid)
    customer = loan.customer
    document_max_retry = int(data['max_count'])
    upload_retry_count = int(data['retry_count'])
    if not document_max_retry or (not upload_retry_count and upload_retry_count != 0):
        raise JuloPrivyLogicException(
            'Something wrong!! parameters incomplete for upload')
    privy_customer = get_privy_customer_data(customer)
    if not privy_customer:
        raise JuloPrivyLogicException(
            'Customer {} did not registered to privy yet'.format(customer.id))

    if privy_customer.privy_customer_status not in CustomerStatusPrivy.ALLOW_UPLOAD:
        raise JuloPrivyLogicException(
            'Customer {} not verifed yet'.format(customer.id))

    document_data = PrivyDocument.objects.get_or_none(loan_id=loan)
    if document_data:
        raise PrivyDocumentExistException(
            'Document already exist for loan {}'.format(loan.id)
        )

    data, api_data = privy_client.upload_document(privy_customer.privy_id, loan.id)
    try:
        if 'files' in api_data["request_params"]:
            api_data["request_params"]["files"] = str(api_data["request_params"]["files"])
    except TypeError:
        raise PrivyApiResponseException("No response")
    store_privy_api_data.delay(loan_xid, api_data)
    if not data or not api_data:
        raise PrivyApiResponseException("No response")

    privy_document_data = store_privy_document_data_julo_one(loan, privy_customer, data)

    if document_max_retry == upload_retry_count + 1:
        privy_document = PrivyDocument.objects.get_or_none(loan_id=loan)
        if privy_document:
            pass
        else:
            if not get_failover_feature():
                raise PrivyNotFailoverException("Document Upload Failed. Failover")


def request_otp_privy_service(user, loan_xid):
    loan = user.customer.loan_set.filter(
        loan_xid=loan_xid,
        loan_status=LoanStatusCodes.INACTIVE
    ).last()
    if not loan:
        raise JuloPrivyLogicException(
            "loan_xid Not Found: %s" % loan_xid)
    customer = loan.customer

    privy_customer = get_privy_customer_data(customer)
    if not privy_customer:
        raise JuloPrivyLogicException('Customer did not registered to privy yet')

    otp_token = get_otp_token_privy(privy_customer.privy_id, loan.loan_xid)
    request_otp_to_privy(otp_token, loan, privy_customer)

    application = loan.account.application_set.last()
    return application.mobile_phone_1


def confirm_otp_privy_service(user, loan_xid, otp_code):
    loan = user.customer.loan_set.filter(
        loan_xid=loan_xid,
        loan_status=LoanStatusCodes.INACTIVE
    ).last()
    if not loan:
        raise JuloPrivyLogicException(
            "loan_xid Not Found: %s" % loan_xid)
    customer = loan.customer
    privy_customer = get_privy_customer_data(customer)

    if not privy_customer:
        raise JuloPrivyLogicException('Customer did not registered to privy yet')

    otp_token = get_otp_token_privy(privy_customer.privy_id, loan.loan_xid)
    if not otp_token:
        raise PrivyApiResponseException('Something wrong!! failed generate otp token')
    data, api_data = privy_client.confirm_otp_token(otp_code, otp_token)
    store_privy_api_data.delay(loan_xid, api_data)
    if not api_data or api_data['response_status_code'] not in (200, 201,):
        raise PrivyApiResponseException('Invalid or expired code OTP')


def sign_document_privy_service(user, loan_xid):
    loan = user.customer.loan_set.filter(
        loan_xid=loan_xid,
        loan_status=LoanStatusCodes.INACTIVE
    ).last()
    if not loan:
        raise JuloPrivyLogicException(
            "loan_xid Not Found: %s" % loan_xid)
    privy_document = PrivyDocument.objects.get_or_none(loan_id=loan)
    if not privy_document:
        raise JuloPrivyLogicException(
            "Document Doesn't Exist")

    privy_customer = privy_document.privy_customer
    otp_token = get_otp_token_privy(privy_customer.privy_id, loan.loan_xid)

    data, api_data = privy_client.sign_document([privy_document.privy_document_token], otp_token)
    store_privy_api_data.delay(loan_xid, api_data)

    if not api_data or api_data['response_status_code'] not in (200, 201,):
        raise PrivyApiResponseException("Signing Document Failed")

    data, api_data = privy_client.get_document_status(privy_document.privy_document_token)
    store_privy_api_data.delay(loan_xid, api_data)

    if not api_data or not data:
        raise PrivyApiResponseException("Document Status API Failed")

    if data["documentStatus"] == DocumentStatusPrivy.COMPLETED:
        download_url = data["download"]["url"]
        application = loan.account.application_set.last()
        if loan.status == LoanStatusCodes.INACTIVE:
            if download_url:
                upload_privy_sphp_document.delay(
                    download_url, loan.id, loan.loan_xid, application.fullname
                )
            accept_julo_sphp(loan, "Privy")

    store_privy_document_data_julo_one(
        loan, privy_document.privy_customer, data
    )


def reregister_privy_service(customer, application):
    failover = get_failover_feature()
    privy = get_privy_feature()
    return_response = {
        'privy_status': 'unregistered',
        'is_privy_mode': privy,
        'is_failover_active': failover,
        'failed': False
    }
    privy_settings = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PRIVY_REUPLOAD_SETTINGS,
        is_active=True
    )
    privy_customer = get_privy_customer_data(customer)
    if not privy_customer:
        if privy:
            raise JuloPrivyLogicException(
                'No Privy Customer found for customer id: {}'.format(customer.id))

    if not privy:
        for category_type in PrivyReUploadCodes.LIST_CODES:
            reuploaded_image = get_image_for_reupload(application.id, category_type)
            if reuploaded_image:
                reuploaded_image.update_safely(image_status=Image.DELETED)
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            'Privy Mode Off'
        )
        return

    user_token = privy_customer.privy_customer_token
    data, api_data = privy_client.register_status(user_token)
    store_privy_api_data(None, api_data, application)
    if not api_data or api_data['response_status_code'] not in (200, 201):
        raise PrivyApiResponseException('Customer Status API failed')
    privy_user_data = store_privy_customer_data(customer, data)
    if not privy_user_data:
        return_response['privy_status'] = privy_customer.privy_customer_status
        return return_response
    if privy_user_data.reject_reason is not None:
        code = data['reject']['code']
        handlers = data['reject']['handlers']
        file_support_category_list = []
        if not code:
            raise JuloPrivyLogicException("Not invalid application")
        list_codes = PrivyReUploadCodes.LIST_CODES
        for category_type in list_codes:
            if code in privy_settings.parameters[category_type]:
                reuploaded_image = get_image_for_reupload(application.id, category_type)
                if not reuploaded_image:
                    raise JuloPrivyLogicException("SUPPORT IMAGE NOT FOUND: {}".format(
                        PrivyReUploadCodes.IMAGE_MAPPING[category_type]))
        for handler in handlers:
            if handler['category'] == 'FILE-SUPPORT':
                file_support_category_list += handler['file_support']
        for category_type in list_codes:
            if code in privy_settings.parameters[category_type]:
                if category_type in [PrivyReUploadCodes.KTP, PrivyReUploadCodes.E_KTP]:
                    category = 'ktp'
                elif category_type == PrivyReUploadCodes.SELFIE:
                    category = 'selfie'
                else:
                    category = 'file-support'
                reuploaded_image = get_image_for_reupload(application.id, category_type)
                if not reuploaded_image:
                    raise JuloPrivyLogicException("SUPPORT IMAGE NOT FOUND: {}".format(
                        PrivyReUploadCodes.IMAGE_MAPPING[category_type]))
                data, api_data = privy_client.reregister_photos(
                    category, user_token, application_id=application.id,
                    image_obj=reuploaded_image, code=category_type,
                    file_support=file_support_category_list)
                store_privy_api_data(None, api_data, application)
    data, api_data = privy_client.register_status(user_token)
    store_privy_api_data(None, api_data, application)
    if not api_data or api_data['response_status_code'] not in (200, 201):
        raise PrivyApiResponseException('Customer Status API failed')
    privy_user_data = store_privy_customer_data(customer, data)
    return_response['privy_status'] = privy_user_data.privy_customer_status

    if return_response['privy_status'] == CustomerStatusPrivy.WAITING and application.status \
            == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            'Privy Reupload Successful'
        )
    return return_response

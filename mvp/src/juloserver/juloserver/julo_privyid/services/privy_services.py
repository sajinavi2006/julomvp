from juloserver.julo.services2 import get_redis_client
from ..utils import convert_str_to_datetime
from juloserver.julo_privyid.clients import get_julo_privy_client
from juloserver.julo_privyid.services.common import store_privy_api_data
from juloserver.julo_privyid.exceptions import (JuloPrivyLogicException,
                                                PrivyDocumentExistException,
                                                PrivyNotFailoverException,
                                                PrivyApiResponseException)
from juloserver.julo_privyid.services.privy_integrate import store_privy_customer_data, get_privy_customer_data
from juloserver.julo_privyid.services.common import get_failover_feature, get_privy_feature
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo_privyid.tasks import create_new_privy_user
from juloserver.julo.services import process_application_status_change
from .privy_integrate import update_digital_signature_face_recognition
from ..constants import PrivyReUploadCodes, PRIVY_IMAGE_TYPE, CustomerStatusPrivy
from juloserver.julo.models import FeatureSetting, Image, Application
from juloserver.julo.constants import FeatureNameConst
from juloserver.streamlined_communication.constant import CardProperty, CommunicationPlatform
from juloserver.streamlined_communication.models import StreamlinedCommunication

privy_client = get_julo_privy_client()


def store_otp_token_privy(privy_id, data):
    redis_client = get_redis_client()

    otp_token = data['token']
    created_date = convert_str_to_datetime(data['created_at'], '%Y-%m-%dT%H:%M:%S.000+07:00')
    expired_date = convert_str_to_datetime(data['expired_at'], '%Y-%m-%dT%H:%M:%S.000+07:00')
    delta_time = expired_date - created_date

    redis_client.set(privy_id, otp_token, delta_time)


def get_otp_token_privy(privy_id, loan_xid, create_flag=False):
    redis_client = get_redis_client()
    otp_token = redis_client.get(privy_id)

    if otp_token and not create_flag:
        return otp_token

    data, api_data = privy_client.create_token(privy_id)
    store_privy_api_data.delay(loan_xid, api_data)
    if not api_data or api_data['response_status_code'] not in (200, 201):
        raise PrivyApiResponseException('Something wrong!! failed generate otp token')

    # store otp token to redis
    store_otp_token_privy(privy_id, data)

    return data['token']


def request_otp_to_privy(otp_token, loan, privy_customer):
    data, api_data = privy_client.request_otp_token(otp_token)
    store_privy_api_data.delay(loan.loan_xid, api_data)
    if not api_data or api_data['response_status_code'] not in (200, 201, 400):
        raise PrivyApiResponseException('Something wrong!! failed request OTP')
    if api_data['response_status_code'] in (400,):
        otp_token = get_otp_token_privy(privy_customer.privy_id, loan.loan_xid, create_flag=True)
        return_status = request_otp_to_privy(otp_token, loan, privy_customer)
        return return_status
    return True


def check_customer_status(customer, application):
    failover = get_failover_feature()
    privy = get_privy_feature()
    return_response = {
        'privy_status': 'unregistered',
        'is_privy_mode': privy,
        'is_failover_active': failover,
        'failed': False,
        'failed_images': [],
        'failed_image_types': [],
        'uploaded_failed_images': []
    }
    privy_settings = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PRIVY_REUPLOAD_SETTINGS,
        is_active=True
    )
    privy_customer = get_privy_customer_data(customer)
    if not privy_customer:
        if privy:
            if (application.status ==
                    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING):
                create_new_privy_user.delay(application.id)
        return return_response

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
        if application.status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING:
            rejected_codes = privy_settings.parameters[PrivyReUploadCodes.REJECTED]
            if data['reject']['code'] in rejected_codes:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    privy_user_data.reject_reason
                )
            elif not failover:
                if not application.is_julo_one() and not application.is_grab():
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.DIGISIGN_FAILED,
                        privy_user_data.reject_reason
                    )
                else:
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
                        privy_user_data.reject_reason
                    )

        if data['reject']:
            if data['reject']['code']:
                list_image_types = list()
                list_uploaded_images = list()
                for category in PrivyReUploadCodes.LIST_CODES:
                    for codes in privy_settings.parameters[category]:
                        if data['reject']['code'] in codes:
                            image_type = PrivyReUploadCodes.IMAGE_MAPPING[category]
                            if image_type not in list_image_types:
                                reuploaded_image = Image.objects.filter(
                                    image_source=application.id,
                                    image_type=PRIVY_IMAGE_TYPE[image_type],
                                    image_status__in=[Image.CURRENT,
                                                      Image.RESUBMISSION_REQ]
                                ).order_by('-udate').first()
                                if reuploaded_image:
                                    image_type = reuploaded_image.image_type \
                                        if reuploaded_image.image_type else None
                                    if image_type:
                                        image_type = list(PRIVY_IMAGE_TYPE.keys())[list(
                                            PRIVY_IMAGE_TYPE.values()).index(image_type)]
                                    list_uploaded_images.append({
                                        "image_url": reuploaded_image.image_url if
                                        reuploaded_image.image_url else None,
                                        "image_type": image_type
                                    })
                                list_image_types.append(image_type)
                    return_response['failed_image_types'] = list_image_types
                    return_response['uploaded_failed_images'] = list_uploaded_images
            for handler in data['reject']['handlers']:
                failed_images_dict = dict()
                failed_images_dict['category'] = handler['category']
                failed_images_dict['handler'] = handler['handler']
                return_response['failed_images'].append(failed_images_dict)

    update_digital_signature_face_recognition(application, privy_user_data)

    return_response['privy_status'] = privy_user_data.privy_customer_status

    if return_response['privy_status'] == CustomerStatusPrivy.WAITING and application.status \
            == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            'Privy Reupload Successful'
        )

    return return_response


def get_image_for_reupload(application_id, category):
    image_type = PrivyReUploadCodes.IMAGE_MAPPING[category]
    reuploaded_image = Image.objects.filter(image_source=application_id,
                                            image_type=PRIVY_IMAGE_TYPE[image_type],
                                            image_status__in=[Image.CURRENT,
                                                              Image.RESUBMISSION_REQ]
                                            ).order_by('-udate').first()
    return reuploaded_image


def get_info_cards_privy(application_id):
    application = Application.objects.get_or_none(id=application_id)
    privy_settings = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PRIVY_REUPLOAD_SETTINGS,
        is_active=True
    )
    customer = application.customer
    privy_customer = get_privy_customer_data(customer)
    if not privy_customer:
        return []
    user_token = privy_customer.privy_customer_token
    data, api_data = privy_client.register_status(user_token)
    store_privy_api_data(None, api_data, application)
    if not api_data or api_data['response_status_code'] not in (200, 201):
        raise PrivyApiResponseException('Customer Status API failed')
    privy_user_data = store_privy_customer_data(customer, data)
    external_condition = None
    if privy_user_data.reject_reason is None:
        return []
    if data['reject']:
        if data['reject']['code']:
            code = data['reject']['code']
            if code in privy_settings.parameters[PrivyReUploadCodes.KTP] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.SELFIE]:
                external_condition = CardProperty.REUPLOAD_KTP_SELFIE_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.KTP] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.KK]:
                external_condition = CardProperty.REUPLOAD_KTP_KK_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.KTP] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.DRIVING_LICENSE]:
                external_condition = CardProperty.REUPLOAD_KTP_SIM_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.KTP]:
                external_condition = CardProperty.REUPLOAD_KTP_ONLY_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.DRIVING_LICENSE] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.KK]:
                external_condition = CardProperty.REUPLOAD_SIM_KK_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.SELFIE] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.KK]:
                external_condition = CardProperty.REUPLOAD_SELFIE_KK_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.SELFIE] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.PASSPORT]:
                external_condition = CardProperty.REUPLOAD_SELFIE_PASSPORT_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.SELFIE] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.PASSPORT]:
                external_condition = CardProperty.REUPLOAD_SELFIE_PASSPORT_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.SELFIE] and code in \
                    privy_settings.parameters[PrivyReUploadCodes.DRIVING_LICENSE]:
                external_condition = CardProperty.REUPLOAD_SIM_SELFIE_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.PASSPORT_SELFIE] and \
                    code in privy_settings.parameters[PrivyReUploadCodes.PASSPORT]:
                external_condition = CardProperty.REUPLOAD_SELFIE_WITH_PASSPORT_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.SELFIE_WITH_KTP]:
                external_condition = CardProperty.REUPLOAD_SELFIE_WITH_KTP_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.DRIVING_LICENSE]:
                external_condition = CardProperty.REUPLOAD_SIM_ONLY_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.KK]:
                external_condition = CardProperty.REUPLOAD_KK_ONLY_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.E_KTP]:
                external_condition = CardProperty.REUPLOAD_EKTP_ONLY_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.PASSPORT]:
                external_condition = CardProperty.REUPLOAD_PASSPORT_ONLY_INFOCARD
            elif code in privy_settings.parameters[PrivyReUploadCodes.SELFIE]:
                external_condition = CardProperty.REUPLOAD_SELFIE_ONLY_INFOCARD
            if external_condition:
                info_cards = list(StreamlinedCommunication.objects.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=external_condition,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
                return info_cards
            else:
                return []

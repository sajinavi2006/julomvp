from builtins import str
import logging
import boto3

from django.conf import settings

logger = logging.getLogger(__name__)


def get_julo_sentry_client():
    from raven.contrib.django.raven_compat.models import client
    return client


def get_julo_pn_client():
    from .pn import JuloPNClient
    return JuloPNClient()


def get_julo_email_client():
    from .email import JuloEmailClient

    return JuloEmailClient(settings.SENDGRID_API_KEY, settings.EMAIL_FROM)


def get_external_email_client(sendgrid_api_key: str, email_from: str):
    from .email import JuloEmailClient

    return JuloEmailClient(sendgrid_api_key, email_from)


def get_julo_sms_client():
    from .sms import JuloSmsClient
    return JuloSmsClient()

def get_julo_sms_after_robocall():
    from .sms import JuloSmsAfterRobocall
    return JuloSmsAfterRobocall(
        settings.SMS_API_KEY,
        settings.SMS_API_SECRET,
        settings.SMS_API_BASE_URL)


def get_julo_perdana_sms_client():
    from .sms import JuloSmsClient
    return JuloSmsClient(source='JULO')


def get_julo_whatsapp_client():
    from .whatsapp import JuloWhatsappClient
    return JuloWhatsappClient(
        settings.WAVECELL_SUB_ACC_ID,
        settings.WAVECELL_API_KEY,
    )

def get_julo_whatsapp_client_go():
    from .whatsapp import JuloWhatsappClientgo
    return JuloWhatsappClientgo(
        settings.JULO_WHATSAPP_API_KEY,
        settings.JULO_WHATSAPP_API_SECRET
    )

def get_julo_autodialer_client():
    from .autodialer import JuloAutodialerClient
    return JuloAutodialerClient(
        settings.SIP_API_KEY_CLICK2CALL,
        settings.SIP_API_KEY_ROBODIAL,
        settings.SIP_BASE_URL,
        settings.SIP_BASE_URL_ROBODIAL,
    )


def get_julo_xendit_client():
    from .xendit import JuloXenditClient
    return JuloXenditClient(
        settings.XENDIT_API_KEY,
        settings.XENDIT_BASE_URL
    )


def get_julo_bri_client():
    from .bri import JuloBriClient
    return JuloBriClient(
        settings.BRI_X_KEY,
        settings.BRI_CODE,
        settings.BRI_CLIENT_ID,
        settings.BRI_CLIENT_SECRET,
        settings.BRI_BASE_URL,
    )


def get_julo_tokopedia_client():
    from .tokopedia import JuloTokopediaClient
    return JuloTokopediaClient(
        settings.TOKOPEDIA_CLIENT_ID,
        settings.TOKOPEDIA_CLIENT_SECRET,
        settings.TOKOPEDIA_BASE_URL,
    )


def get_julo_apps_flyer():
    from .appsflyer import JuloAppsFlyer
    return JuloAppsFlyer(
        settings.APPS_FLYER_IOS_CLIENT_ID,
        settings.APPS_FLYER_CLIENT_ID,
        settings.APPS_FLYER_API_KEY,
        settings.APPS_FLYER_BASE_URL,
    )


def get_julo_sepulsa_client():
    from .sepulsa import JuloSepulsaClient
    from juloserver.payment_point.services import sepulsa as sepulsa_services
    return JuloSepulsaClient(
        sepulsa_services.get_sepulsa_base_url(),
        settings.SEPULSA_USERNAME,
        settings.SEPULSA_SECRET_KEY
    )


def get_object_storage_client():
    return boto3.resource(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)


def get_s3_url(bucket, object_path, expires_in_seconds=120):
    """
    Return the static absolute pre-signed S3 url, region agnostic.
    """
    if bucket == '' or object_path == '':
        logger.warn({
            'bucket': bucket,
            'object_path': object_path
        })
        return ''

    s3 = get_object_storage_client()
    client = s3.meta.client
    url = client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': bucket,
            'Key': object_path.__str__(),
        },
        ExpiresIn=expires_in_seconds, )

    logger.info({
        'bucket': bucket,
        'object_path': object_path,
        'url': url
    })
    return url


def get_autodial_client(token=None):
    from .telephony import AutodialClient
    return AutodialClient(settings.QUIROS_AUTODIAL_BASE_URL, token)


def get_robocall_client():
    from .telephony import RobocallClient
    robocall_client = RobocallClient(settings.QUIROS_ROBOCALL_BASE_URL)
    robocall_client.login(
        settings.QUIROS_ROBOCALL_USERNAME, settings.QUIROS_ROBOCALL_PASSWORD)
    return robocall_client


def get_qismo_client():
    from .qismo import JuloQismoClient
    qismo_client = JuloQismoClient(settings.QISMO_BASE_URL)
    qismo_client.sign_in(settings.QISMO_USERNAME,
                         settings.QISMO_PASSWORD)
    return qismo_client


def get_voice_client():
    from .voice import JuloVoiceClient
    from juloserver.julo.services import get_nexmo_from_phone_number
    NEXMO_PHONE_NUMBER, TEST_NUMBER = get_nexmo_from_phone_number()
    voice_client = JuloVoiceClient(
        settings.NEXMO_API_KEY,
        settings.NEXMO_API_SECRET,
        settings.NEXMO_VOICE_URL,
        settings.NEXMO_APPLICATION_ID,
        settings.NEXMO_PRIVATE_KEY,
        NEXMO_PHONE_NUMBER,
        settings.BASE_URL
    )
    return voice_client


def get_voice_client_v2():
    from .voice_v2 import JuloVoiceClientV2
    from juloserver.julo.services import get_nexmo_from_phone_number

    NEXMO_PHONE_NUMBER, TEST_NUMBER = get_nexmo_from_phone_number()
    voice_client = JuloVoiceClientV2(
        settings.NEXMO_API_KEY,
        settings.NEXMO_API_SECRET,
        settings.NEXMO_APPLICATION_ID,
        settings.NEXMO_PRIVATE_KEY,
        NEXMO_PHONE_NUMBER,
        settings.BASE_URL,
        TEST_NUMBER,
    )
    return voice_client


def get_voice_client_v2_for_loan():
    from .voice_v2 import JuloVoiceClientV2
    from juloserver.julo.services import get_nexmo_from_phone_number
    NEXMO_PHONE_NUMBER, TEST_NUMBER = get_nexmo_from_phone_number()
    voice_client = JuloVoiceClientV2(
        settings.LOAN_NEXMO_API_KEY,
        settings.LOAN_NEXMO_API_SECRET,
        settings.LOAN_NEXMO_APPLICATION_ID,
        settings.LOAN_NEXMO_PRIVATE_KEY,
        NEXMO_PHONE_NUMBER,
        settings.BASE_URL,
        TEST_NUMBER
    )
    return voice_client


def get_primo_client():
    from .primo import JuloPrimoClient
    primo_client = JuloPrimoClient(
        settings.PRIMO_BASE_URL,
        settings.PRIMO_USERNAME,
        settings.PRIMO_PASSWORD
    )

    return primo_client


def get_julo_bca_client():
    from .bca import JuloBcaClient
    return JuloBcaClient(
        settings.BCA_API_KEY,
        settings.BCA_API_SECRET_KEY,
        settings.BCA_CLIENT_ID,
        settings.BCA_CLIENT_SECRET,
        settings.BCA_BASE_URL,
        settings.BCA_CORPORATE_ID,
        settings.BCA_ACCOUNT_NUMBER,
        settings.BCA_CHANNEL_ID,
    )


def get_julo_repayment_bca_client():
    from .bca import JuloBcaClient
    return JuloBcaClient(
        settings.BCA_REPAYMENT_API_KEY,
        settings.BCA_REPAYMENT_API_SECRET_KEY,
        settings.BCA_REPAYMENT_CLIENT_ID,
        settings.BCA_REPAYMENT_CLIENT_SECRET,
        settings.BCA_BASE_URL,
        settings.BCA_REPAYMENT_CORPORATE_ID,
        settings.BCA_REPAYMENT_ACCOUNT_NUMBER,
        settings.BCA_CHANNEL_ID,
    )


def get_julo_va_bca_client():
    from .bca import JuloBcaClient
    return JuloBcaClient(
        settings.VA_BCA_API_KEY,
        settings.VA_BCA_API_SECRET_KEY,
        settings.VA_BCA_CLIENT_ID,
        settings.VA_BCA_CLIENT_SECRET,
        settings.BCA_BASE_URL,
        settings.VA_BCA_CORPORATE_ID,
        settings.BCA_ACCOUNT_NUMBER,
        settings.BCA_CHANNEL_ID,
    )


def get_julo_sim_client():
    from .sim import JuloSimClient
    return JuloSimClient(
        settings.SIM_USERNAME,
        settings.SIM_PASSWORD,
        settings.SIM_BASE_URL
    )


def get_julo_xfers_client():
    from .xfers import XfersClient
    return XfersClient(
        settings.XFERS_APP_API_KEY,
        settings.XFERS_APP_SECRET_KEY,
        settings.XFERS_JTF_USER_TOKEN,
        settings.XFERS_BASE_URL,
        settings.XFERS_CALLBACK_URL
    )


def get_lender_xfers_client(lender_id):
    from .xfers import XfersClient
    from juloserver.followthemoney.models import LenderCurrent
    xfer_jtp_user_token = LenderCurrent.get_xfers_token_by_lender(lender_id)
    return XfersClient(
        settings.XFERS_APP_API_KEY,
        settings.XFERS_APP_SECRET_KEY,
        xfer_jtp_user_token,
        settings.XFERS_BASE_URL,
        settings.LENDER_WITHDRAWAL_CALLBACK_URL
    )


def get_url_shorten_service():
    from .shortner import UrlShortenServices
    return UrlShortenServices()


def get_julo_advanceai_client():
    from .advanceai import JuloAdvanceaiClient
    return JuloAdvanceaiClient(
        settings.ADVANCE_AI_API_KEY,
        settings.ADVANCE_AI_SECRET_KEY,
        settings.ADVANCE_AI_BASE_URL
        )


def get_julo_digisign_client():
    from .digisign import JuloDigisignClient
    return JuloDigisignClient(
        settings.DIGISIGN_BASE_URL,
        settings.DIGISIGN_TOKEN,
        settings.DIGISIGN_USERID,
        settings.DIGISIGN_PWD,
        settings.DIGISIGN_PLATFORM_EMAIL,
        settings.DIGISIGN_PLATFORM_NAME,
        settings.DIGISIGN_PLATFORM_KEY
        )


def get_bukalapak_client(dummy=False):
    from .bukalapak import BukalapakClient
    if dummy:
        username="dummy_bukalapak_basic_auth"
        secret="dummy_bukalapak_basic_auth_password"
    else:
        username=settings.BUKALAPAK_USERNAME
        secret=settings.BUKALAPAK_SECRET_KEY

    return BukalapakClient(username, secret)


def get_julo_nemesys_client():
    from .nemesys import JuloNemesysClient
    return JuloNemesysClient(settings.NEMESYS_BASE_URL, settings.NEMESYS_TOKEN)


def get_julo_centerix_client():
    from .centerix import JuloCenterixClient
    return JuloCenterixClient(
        settings.CENTERIX_USER_ID,
        settings.CENTERIX_PASSWORD,
        settings.CENTERIX_BASE_URL
    )


def get_julo_face_rekognition():
    from .aws_rekognition import JuloFaceRekognition
    from ..constants import FaceRecognition
    from juloserver.julo.models import FaceRecognition as FaceRecognitionModel

    index = FaceRecognitionModel.objects.filter(feature_name='IndexFace Filter').first()
    return JuloFaceRekognition(
        settings.AWS_ACCESS_KEY_ID,
        settings.AWS_SECRET_ACCESS_KEY,
        settings.REKOGNITION_DEFAULT_COLLECTION,
        index.quality_filter,
        FaceRecognition.MAX_FACES,
        settings.AWS_DEFAULT_REGION
    )


def get_julo_mintos_client():
    from .mintos import JuloMintosClient

    return JuloMintosClient(
        settings.MINTOS_BASE_URL,
        settings.MINTOS_TOKEN,  # token
    )


def get_julo_bca_snap_client(
    customer_id=None, loan_id=None, account_payment_id=None, payback_transaction_id=None
):
    from .bca import JuloBcaSnapClient
    return JuloBcaSnapClient(
        settings.BCA_SNAP_CLIENT_ID_OUTBOND,
        settings.BCA_SNAP_CLIENT_SECRET_OUTBOND,
        settings.BCA_SNAP_BASE_URL_OUTBOND,
        settings.VA_BCA_CORPORATE_ID,
        settings.BCA_SNAP_CHANNEL_ID_OUBTOND,
        settings.BCA_SNAP_PRIVATE_KEY_OUTBOND,
        settings.BCA_SNAP_COMPANY_VA_OUTBOND,
        customer_id,
        loan_id,
        account_payment_id,
        payback_transaction_id,
    )


def get_doku_snap_client(customer_id=None, loan_id=None, payback_transaction_id=None):
    from .doku import DokuSnapClient

    return DokuSnapClient(
        settings.DOKU_SNAP_BASE_URL_OUTBOND,
        settings.DOKU_SNAP_CLIENT_ID_OUTBOND,
        settings.DOKU_SNAP_CLIENT_SECRET_OUTBOND,
        settings.DOKU_SNAP_PRIVATE_KEY_OUTBOND,
        customer_id=customer_id,
        loan_id=loan_id,
        payback_transaction_id=payback_transaction_id,
    )


def get_doku_snap_ovo_client(
    ovo_wallet_account=None, account=None, account_payment=None, is_autodebet=False
):
    from .doku import DokuSnapOvoClient

    return DokuSnapOvoClient(
        settings.DOKU_SNAP_BASE_URL_OUTBOND,
        settings.DOKU_SNAP_CLIENT_ID_OUTBOND,
        settings.DOKU_SNAP_CLIENT_SECRET_OUTBOND,
        settings.DOKU_SNAP_PRIVATE_KEY_OUTBOND,
        ovo_wallet_account,
        account,
        account_payment,
        is_autodebet,
    )


def get_nsq_producer():
    from .nsq import NsqHttpProducer

    return NsqHttpProducer(
        settings.NSQD_HTTP_URL,
        settings.NSQD_HTTP_PORT,
    )

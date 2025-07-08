from django.conf import settings
from .bss import BSSChannelingClient
from .dbs import DBSChannelingClient
from .sftp import SFTPClient
from ..constants.dbs_constants import JULO_ORG_ID_GIVEN_BY_DBS
from .smf import SMFChannelingAPIClient


def get_bss_channeling_client():
    return BSSChannelingClient(settings.BSS_CHANNELING_BASE_URL)


def get_bss_va_client():
    return BSSChannelingClient(settings.BSS_VA_BASE_URL)


def get_fama_sftp_client():
    return SFTPClient(
        host=settings.FAMA_SFTP_HOST,
        username=settings.FAMA_SFTP_USERNAME,
        port=settings.FAMA_SFTP_PORT,
        rsa_private_key=settings.FAMA_SFTP_RSA_PRIVATE_KEY,
        remote_directory=settings.FAMA_SFTP_REMOTE_DIRECTORY,
    )


def get_permata_sftp_client():
    return SFTPClient(
        host=settings.PERMATA_SFTP_HOST,
        username=settings.PERMATA_SFTP_USERNAME,
        port=settings.PERMATA_SFTP_PORT,
        password=settings.PERMATA_SFTP_PASSWORD,
    )


def get_bni_sftp_client():
    return SFTPClient(
        host=settings.BNI_SFTP_HOST,
        username=settings.BNI_SFTP_USERNAME,
        port=settings.BNI_SFTP_PORT,
        password=settings.BNI_SFTP_PASSWORD,
    )


def get_dbs_channeling_client():
    return DBSChannelingClient(
        base_url=settings.DBS_CHANNELING_BASE_URL,
        api_key=settings.DBS_API_KEY,
        org_id=JULO_ORG_ID_GIVEN_BY_DBS,
    )


def get_dbs_sftp_client():
    return SFTPClient(
        host=settings.DBS_SFTP_HOST,
        username=settings.DBS_SFTP_USERNAME,
        port=settings.DBS_SFTP_PORT,
        rsa_private_key=settings.DBS_SFTP_RSA_PRIVATE_KEY,
        remote_directory=settings.DBS_SFTP_REMOTE_DIRECTORY,
    )


def get_smf_channeling_api_client():
    return SMFChannelingAPIClient(
        gtw_access_key=settings.SMF_CHANNELING_GTW_ACCESS_KEY,
        gtw_api_key=settings.SMF_CHANNELING_GTW_API_KEY,
        hmac_secret_key=settings.SMF_CHANNELING_HMAC_SECRET_KEY,
        base_url=settings.SMF_CHANNELING_API_BASE_URL,
        url_prefix=settings.SMF_CHANNELING_API_URL_PREFIX
    )

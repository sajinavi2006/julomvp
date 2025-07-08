import logging
from django.conf import settings


logger = logging.getLogger(__name__)


def get_julo_intelix_client():
    from .intelix import JuloIntelixClient
    return JuloIntelixClient(
        settings.INTELIX_API_KEY,
        settings.INTELIX_BASE_URL,
    )


def get_julo_intelix_sftp_client():
    from juloserver.minisquad.clients.intelix import JuloIntelixSFTPClient
    return JuloIntelixSFTPClient(
        settings.INTELIX_SFTP_HOST,
        settings.INTELIX_SFTP_USERNAME,
        settings.INTELIX_SFTP_PASSWORD,
        settings.INTELIX_SFTP_PORT,
    )


def get_julo_ai_rudder_pds_client():
    from juloserver.minisquad.clients.airudder_pds import AIRudderPDSClient
    return AIRudderPDSClient(
        settings.AI_RUDDER_PDS_APP_KEY,
        settings.AI_RUDDER_PDS_APP_SECRET,
        settings.AI_RUDDER_PDS_BASE_URL,
    )


def get_julo_field_collection_client():
    from juloserver.minisquad.clients.field_collection import FieldCollectionClient

    return FieldCollectionClient(settings.FIELDCOLL_TOKEN, settings.FIELDCOLL_BASE_URL)


def get_julo_kangtau_client():
    from juloserver.minisquad.clients.kangtau import KangtauClient

    return KangtauClient(
        settings.KANGTAU_BASE_URL,
        settings.KANGTAU_COMPANY_ID,
        settings.KANGTAU_PROJECT_ID,
        settings.KANGTAU_API_INTEGRATION_TOKEN,
    )

from django.conf import settings


def get_dukcapil_client(application=None, pass_criteria=None):
    from .dukcapil_client import DukcapilClient

    return DukcapilClient(
        api_key=settings.DUKCAPIL_API_KEY,
        api_url=settings.DUKCAPIL_API_BASE_URL,
        application=application,
        pass_criteria=pass_criteria,
    )


def get_dukcapil_direct_client(application=None, pass_criteria=None):
    from .dukcapil_direct_client import DukcapilDirectClient

    return DukcapilDirectClient(
        username=settings.DUKCAPIL_OFFICIAL_USER_ID,
        password=settings.DUKCAPIL_OFFICIAL_PASSWORD,
        verify_api_url=settings.DUKCAPIL_OFFICIAL_API_VERIFY_URL,
        store_api_url=settings.DUKCAPIL_OFFICIAL_API_STORE_URL,
        application=application,
        pass_criteria=pass_criteria,
        api_token=settings.DUKCAPIL_OFFICIAL_API_TOKEN,
        organization_id=settings.DUKCAPIL_OFFICIAL_ORGANIZATION_ID,
        organization_name=settings.DUKCAPIL_OFFICIAL_ORGANIZATION_NAME,
    )


def get_bureau_client(application, service, session_id=None):
    from .bureau_client import BureauClient

    api_url = None
    if service:
        if service in ('email-attributes', 'device-fingerprint'):
            api_url = settings.BUREAU_SUPPLIER_URL + service
        else:
            api_url = settings.BUREAU_SERVICE_URL + service

    return BureauClient(
        username=settings.BUREAU_USERNAME,
        password=settings.BUREAU_PASSWORD,
        application=application,
        api_url=api_url,
        service=service,
        session_id=session_id)

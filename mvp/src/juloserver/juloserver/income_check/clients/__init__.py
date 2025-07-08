from django.conf import settings


def get_julo_izidata_client():
    from juloserver.income_check.clients.izidata import IziDataClient

    return IziDataClient(
        settings.IZIDATA_APP_ACCESS_KEY, settings.IZIDATA_APP_SECRET_KEY, settings.IZIDATA_BASE_URL
    )

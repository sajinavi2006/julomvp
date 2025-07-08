from django.conf import settings


def get_scapper_client():
    from .clients import JuloScraperClient

    return JuloScraperClient(settings.SCRAPER_TOKEN, settings.SCRAPER_BASE_URL)

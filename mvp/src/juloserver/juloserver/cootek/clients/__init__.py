from django.conf import settings


def get_julo_cootek_client():
    from .cootek import CootekClient

    return CootekClient(
        settings.COOTEK_API_KEY,
        settings.COOTEK_API_SECRET_KEY,
        settings.COOTEK_API_BASE_URL,
    )

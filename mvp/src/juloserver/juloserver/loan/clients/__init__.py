from django.conf import settings
from .julo_care import JULOCaresClient


def get_julo_care_client():
    return JULOCaresClient(settings.JULO_CARE_BASE_URL)

from django.conf import settings
from juloserver.credit_card.clients.bss import BSSCreditCardClient


def get_bss_credit_card_client():
    return BSSCreditCardClient(settings.BSS_CREDIT_CARD_BASE_URL)

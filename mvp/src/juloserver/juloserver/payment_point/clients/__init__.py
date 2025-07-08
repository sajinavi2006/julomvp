from django.conf import settings

from juloserver.julo.clients.sepulsa import JuloSepulsaClient


def get_julo_sepulsa_loan_client():
    from juloserver.payment_point.services import sepulsa as sepulsa_services
    return JuloSepulsaClient(
        sepulsa_services.get_sepulsa_base_url(),
        settings.SEPULSA_LOAN_USERNAME,
        settings.SEPULSA_LOAN_SECRET_KEY
    )

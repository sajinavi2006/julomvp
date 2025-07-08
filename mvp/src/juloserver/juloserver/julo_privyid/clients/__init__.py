from django.conf import settings
import warnings


def get_julo_privyid_client():
    warnings.warn("", PendingDeprecationWarning)
    from .privyid import JuloPrivyIDClient

    return JuloPrivyIDClient(
        base_url=settings.PRIVY_BASE_URL,
        merchant_key=settings.PRIVY_MERCHANT_KEY,
        username=settings.PRIVY_USERNAME,
        secret_key=settings.PRIVY_SECRET_KEY,
        enterprise_token=settings.PRIVY_ENTERPRISE_TOKEN,
        enterprise_id=settings.PRIVY_ENTERPRISE_ID,
    )


def get_julo_privy_client():
    from .privy import JuloPrivyClient

    return JuloPrivyClient(
        base_url=settings.PRIVY_BASE_URL,
        merchant_key=settings.PRIVY_MERCHANT_KEY,
        username=settings.PRIVY_USERNAME,
        secret_key=settings.PRIVY_SECRET_KEY,
        enterprise_token=settings.PRIVY_ENTERPRISE_TOKEN,
        enterprise_id=settings.PRIVY_ENTERPRISE_ID,
    )

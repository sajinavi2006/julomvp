def get_dana_linking_client(account=None, account_payment=None):
    from django.conf import settings
    from .clients import DanaLinkingClient

    return DanaLinkingClient(
        settings.DANA_LINKING_CLIENT_ID,
        settings.DANA_LINKING_CLIENT_SECRET,
        settings.DANA_LINKING_API_BASE_URL,
        settings.DANA_LINKING_WEB_BASE_URL,
        settings.DANA_LINKING_MERCHANT_ID,
        settings.DANA_LINKING_CHANNEL_ID,
        settings.DANA_LINKING_PUBLIC_KEY,
        settings.DANA_LINKING_PRIVATE_KEY,
        account,
        account_payment,
    )

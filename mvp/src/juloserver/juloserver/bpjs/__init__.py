from django.conf import settings


def get_julo_tongdun_client():
    from .clients import TongdunClient

    return TongdunClient(
        settings.TONGDUN_PARTNER_CODE,
        settings.TONGDUN_PARTNER_KEY,
        settings.TONGDUN_APP_NAME_ANDROID,
        settings.TONGDUN_APP_NAME_WEB,
        settings.TONGDUN_BOX_TOKEN_ANDROID,
        settings.TONGDUN_BOX_TOKEN_WEB,
        settings.TONGDUN_BPJS_LOGIN_URL,
        settings.TONGDUN_INTERFACE_API_BASE_URL,
    )


def get_anaserver_client():
    from .clients import AnaserverClient

    return AnaserverClient(settings.ANASERVER_TOKEN, settings.ANASERVER_BASE_URL)


def get_brick_client(user_access_token=None):
    from .clients import BrickClient

    client = BrickClient(
        settings.BRICK_CLIENT_ID, settings.BRICK_CLIENT_SECRET, settings.BRICK_BASE_URL
    )

    if user_access_token is not None:
        client.set_user_access_token(user_access_token)

    return client


def get_bpjs_direct_client():
    from .clients import BPJSDirectClient

    client = BPJSDirectClient(
        settings.BPJS_DIRECT_BASE_URL
    )

    return client

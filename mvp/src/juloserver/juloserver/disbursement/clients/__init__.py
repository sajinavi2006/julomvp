import logging

from django.conf import settings


logger = logging.getLogger(__name__)


def get_bca_client(use_token=True):
    from .bca import BcaClient
    return BcaClient(
        settings.BCA_API_KEY,
        settings.BCA_API_SECRET_KEY,
        settings.BCA_CLIENT_ID,
        settings.BCA_CLIENT_SECRET,
        settings.BCA_BASE_URL,
        settings.BCA_CORPORATE_ID,
        settings.BCA_ACCOUNT_NUMBER,
        use_token
    )


def get_xendit_client():
    from .xendit import XenditClient
    return XenditClient(
        settings.XENDIT_API_KEY,
        settings.XENDIT_BASE_URL
    )


def get_instamoney_client():
    from .instamoney import InstamoneyClient
    return InstamoneyClient(
        settings.INSTAMONEY_API_KEY,
        settings.INSTAMONEY_BASE_URL
    )


def get_jtf_xfers_client():
    from .xfers import XfersClient
    return XfersClient(
        settings.XFERS_APP_API_KEY,
        settings.XFERS_APP_SECRET_KEY,
        settings.XFERS_JTF_USER_TOKEN,
        settings.XFERS_BASE_URL,
        settings.XFERS_CALLBACK_URL_STEP_TWO
    )


def get_jtp_xfers_client(lender_id):
    from .xfers import XfersClient
    from juloserver.followthemoney.models import LenderCurrent
    xfer_jtp_user_token = LenderCurrent.get_xfers_token_by_lender(lender_id)

    return XfersClient(
        settings.XFERS_APP_API_KEY,
        settings.XFERS_APP_SECRET_KEY,
        xfer_jtp_user_token,
        settings.XFERS_BASE_URL,
        settings.XFERS_CALLBACK_URL_STEP_ONE
    )


def get_default_xfers_client():
    from .xfers import XfersClient
    return XfersClient(
        settings.XFERS_APP_API_KEY,
        settings.XFERS_APP_SECRET_KEY,
        settings.XFERS_JTF_USER_TOKEN,
        settings.XFERS_BASE_URL,
        settings.XFERS_CALLBACK_URL
    )


def get_gopay_client():
    from .gopay import GopayClient
    return GopayClient(
        settings.GOPAY_API_KEY,
        settings.GOPAY_APPROVER_API_KEY,
        settings.GOPAY_CASHBACK_BASE_URL
    )


def get_ayoconnect_client():
    from juloserver.disbursement.clients.ayoconnect import AyoconnectClient
    return AyoconnectClient(
        settings.AYOCONNECT_BASE_URL,
        settings.AYOCONNECT_CLIENT_ID,
        settings.AYOCONNECT_CLIENT_SECRET,
        settings.AYOCONNECT_MERCHANT_CODE,
        settings.AYOCONNECT_LATITUDE,
        settings.AYOCONNECT_LONGITUDE,
        settings.AYOCONNECT_IP_ADDRESS
    )


def get_payment_gateway_client(client_id, api_key):
    from juloserver.disbursement.clients.payment_gateway import PaymentGatewayClient

    return PaymentGatewayClient(
        settings.PAYMENT_GATEWAY_BASE_URL,
        client_id,
        settings.PAYMENT_GATEWAY_CLIENT_SECRET,
        api_key,
    )

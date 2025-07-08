import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def get_cashback_redemption_service():
    from .cashback import CashbackRedemptionService
    return CashbackRedemptionService()


def get_cashback_service():
    from .cashback import CashbackService
    return CashbackService()


def get_appsflyer_service():
    from .appsflyer import AppsFlyerService
    return AppsFlyerService()

def get_bypass_iti_experiment_service():
    from .experiment import BypassITIExperimentService
    return BypassITIExperimentService()

def get_agent_service():
    from .agent import AgentService
    return AgentService()

def get_payment_event_service():
    from .payment_event import PaymentEventServices
    return PaymentEventServices()

def get_advance_ai_service():
    from .advance_ai import AdvanceAiService
    return AdvanceAiService()

def encrypt():
    from .encryption import Encryption
    return  Encryption()

def get_customer_service():
    from .customer import CustomerServices
    return CustomerServices()

def get_redis_client():
    from .redis_helper import RedisHelper
    return RedisHelper(
        settings.REDIS_URL,
        settings.REDIS_PASSWORD,
        settings.REDIS_PORT,
        settings.REDIS_DB
    )

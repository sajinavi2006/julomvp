import json
import logging
from typing import Tuple, Optional
from datetime import timedelta, datetime
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from juloserver.julo_financing.constants import (
    ELEMENTS_IN_TOKEN,
    TOKEN_EXPIRED_HOURS,
    RedisKey,
    JFinancingEntryPointType,
)
from cryptography.fernet import Fernet, InvalidToken
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.services2 import get_redis_client
from juloserver.julo_financing.models import JFinancingProduct

logger = logging.getLogger(__name__)


@dataclass
class TokenData:
    """
    Data fields in jfinancing token
    """

    customer_id: int
    event_time: float  # timestamp
    expiry_time: float  # timestamp

    @property
    def event_time_datetime(self) -> datetime:
        return timezone.localtime(datetime.fromtimestamp(self.event_time))

    @property
    def expiry_time_datetime(self) -> datetime:
        return timezone.localtime(datetime.fromtimestamp(self.expiry_time))


class JFinancingToken:
    def __init__(self):
        self.fernet = Fernet(settings.J_FINANCING_SECRET_KEY_TOKEN)

    def generate_token(self, customer_id, token_expired_hours=TOKEN_EXPIRED_HOURS) -> str:
        event_time = timezone.localtime(timezone.now())
        expiry_time = event_time + timedelta(hours=token_expired_hours, minutes=1)

        token_data = TokenData(
            customer_id=customer_id,
            event_time=event_time.timestamp(),
            expiry_time=expiry_time.timestamp(),
        )

        encrypted_key = self.encrypt(token_data)

        logger.info(
            {
                'action': 'JFinancingToken.generate_token',
                **token_data.__dict__,
                'encrypted_key': encrypted_key,
            }
        )
        return encrypted_key

    def encrypt(self, data: TokenData) -> str:
        """
        Encrypt data to token
        """
        encrypted_info = json.dumps(data.__dict__)
        token = self.fernet.encrypt(encrypted_info.encode()).decode()
        return token

    def decrypt(self, token: str) -> TokenData:
        """
        Decrypt token to data
        """
        decrypted_info = self.fernet.decrypt(token.encode()).decode()
        info_dict = json.loads(decrypted_info)

        if len(info_dict) != ELEMENTS_IN_TOKEN:
            raise InvalidToken

        return TokenData(**info_dict)

    def is_token_valid(self, token: str) -> Tuple[bool, TokenData]:
        """
        used in views to validate in-coming tokens
        """
        try:
            token_data = self.decrypt(token)
        except InvalidToken:
            return False, None

        # validate
        now = timezone.localtime(timezone.now()).timestamp()
        if now > token_data.expiry_time:
            return False, None

        return True, token_data


def get_j_financing_token_config_fs() -> dict:
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.J_FINANCING_TOKEN_CONFIG, is_active=True
    ).last()
    return fs.parameters if fs else dict()


def get_or_create_customer_token(customer_id: int) -> Tuple[str, TokenData]:
    """
    Retrieve or Generate token, also returns token data
    """
    redis_client = get_redis_client()
    redis_key = RedisKey.J_FINANCING_CUSTOMER_TOKEN.format(customer_id)
    customer_token = redis_client.get(redis_key)

    jfinancing_token = JFinancingToken()
    if customer_token:
        return customer_token, jfinancing_token.decrypt(customer_token)

    token_config = get_j_financing_token_config_fs()
    expired_hours = token_config.get('token_expired_hours', TOKEN_EXPIRED_HOURS)

    encrypted_key = jfinancing_token.generate_token(customer_id, expired_hours)
    redis_client.set(key=redis_key, value=encrypted_key, expire_time=timedelta(hours=expired_hours))

    return encrypted_key, jfinancing_token.decrypt(encrypted_key)


def get_entry_point(customer_id: int, type: str, query_params: dict) -> str:
    """
    we will have some entry points with token
    format:: domain + endpoint + token
    """
    customer_token, _ = get_or_create_customer_token(customer_id)
    if type == JFinancingEntryPointType.LANDING_PAGE:
        endpoint = '/smartphone-financing/landing'
        return "{}{}?token={}".format(settings.JULO_LITE_BASE_URL, endpoint, customer_token)

    elif type == JFinancingEntryPointType.PRODUCT_DETAIL:
        endpoint = '/smartphone-financing/catalogue/'
        product_id = query_params['product_id']
        return "{}{}{}?token={}".format(
            settings.JULO_LITE_BASE_URL, endpoint, product_id, customer_token
        )


def validate_entry_point_type(type: str, query_params: dict) -> Tuple[bool, Optional[str]]:
    if type not in JFinancingEntryPointType.list_entry_point_types():
        return False, "Entry point not found"

    if type == JFinancingEntryPointType.PRODUCT_DETAIL:
        product_id = int(query_params.get('product_id', 0))
        if not JFinancingProduct.objects.filter(pk=product_id).exists():
            return False, "Product not found"

    return True, None

import json
import logging
from typing import Tuple
from datetime import timedelta, datetime
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from cryptography.fernet import Fernet, InvalidToken

from juloserver.loan.exceptions import LoanTokenExpired
from juloserver.payment_point.constants import TransactionMethodCode

logger = logging.getLogger(__name__)


@dataclass
class LoanTokenData:
    """
    Data fields in loan selection token
    """

    loan_requested_amount: int
    loan_duration: int
    customer_id: int
    transaction_method_code: int

    expiry_time: float  # timestamp

    def __post_init__(self):
        """
        Validation for input
        """
        if not isinstance(self.loan_requested_amount, int) or self.loan_requested_amount <= 0:
            raise TypeError("loan_requested_amount must be a positive integer")

        if not isinstance(self.loan_duration, int) or self.loan_duration <= 0:
            raise TypeError("loan_duration must be a positive integer")

        if not isinstance(self.customer_id, int) or self.customer_id <= 0:
            raise TypeError("customer_id must be a positive integer")

        if not isinstance(self.expiry_time, (int, float)) or self.expiry_time <= 0:
            raise TypeError("expiry_time must be a positive number (timestamp)")

        code = self.transaction_method_code
        if not isinstance(code, int) or code not in TransactionMethodCode.all_code():
            raise TypeError("Invalid transaction method code")

    @property
    def expiry_time_datetime(self) -> datetime:
        return timezone.localtime(datetime.fromtimestamp(self.expiry_time))


class LoanTokenService:
    """
    For Generating loan token encypting some useful data
    """

    TOKEN_EXPIRED_MINUTES = 10

    def __init__(self):
        self.fernet = Fernet(settings.LOAN_TOKEN_SECRET_KEY)

    @staticmethod
    def get_expiry_time(minutes_to_expire=TOKEN_EXPIRED_MINUTES) -> float:
        """
        Expiry time in POSIX timestamp
        """
        now = timezone.localtime(timezone.now())
        expiry_time = now + timedelta(minutes=minutes_to_expire)

        return expiry_time.timestamp()

    def encrypt(self, data: LoanTokenData) -> str:
        """
        Encrypt data to token
        """
        encrypted_info = json.dumps(data.__dict__)
        token = self.fernet.encrypt(encrypted_info.encode()).decode()

        logger.info(
            {
                'action': 'LoanToken.encrypt',
                'message': 'encrypting loan duration data',
                **data.__dict__,
                'customer_id': data.customer_id,
            }
        )
        return token

    def decrypt(self, token: str) -> LoanTokenData:
        """
        Decrypt token to data, can raise Invalid Token
        """
        decrypted_info = self.fernet.decrypt(token.encode()).decode()
        info_dict = json.loads(decrypted_info)

        return LoanTokenData(**info_dict)

    def is_token_valid(self, token: str) -> Tuple[bool, LoanTokenData]:
        """
        used in views to validate in-coming tokens
        """
        try:
            token_data = self.decrypt(token)

            # validate expiry
            now = timezone.localtime(timezone.now()).timestamp()
            if now > token_data.expiry_time:
                raise LoanTokenExpired

        except LoanTokenExpired:
            logger.info(
                {
                    'action': 'LoanToken.encrypt',
                    'message': 'loan duration token expired',
                    'customer_id': token_data.customer_id,
                    'loan token': token,
                    'expiry_time': token_data.expiry_time_datetime,
                }
            )
            return False, None
        except InvalidToken:
            logger.info(
                {
                    'action': 'LoanToken.encrypt',
                    'message': 'loan token invalid',
                    'loan token': token,
                }
            )
            return False, None

        return True, token_data

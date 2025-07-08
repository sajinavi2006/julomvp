import logging
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timedelta,
)
from functools import wraps
from itertools import chain
from typing import Union, List

from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.db import (
    DatabaseError,
    transaction,
)
from django.db.models import (
    Min,
    Q,
)
from django.utils import timezone
from django_request_cache import cache_for_request

from juloserver.account.constants import (
    AccountConstant,
    AccountChangeReason,
)
from juloserver.account.models import Account
from juloserver.account.services.account_related import process_change_account_status
from juloserver.ana_api.models import PdApplicationFraudModelResult
from juloserver.antifraud.constant.binary_checks import (
    StatusEnum as ABCStatus,
)
from juloserver.antifraud.tasks.loan_related import (
    event_loan_fraud_block,
)
from juloserver.api_token.authentication import generate_new_token_and_refresh_token
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountDestination
from juloserver.fraud_security.constants import (
    FraudFlagSource,
    FraudFlagTrigger,
    FraudFlagType,
    SwiftLimitDrainerConditionValues,
    FraudBlockAccountConst,
)
from juloserver.fraud_security.models import (
    FraudBlacklistedASN,
    FraudFlag,
    FraudVelocityModelGeohash,
    FraudVelocityModelGeohashBucket,
    FraudVelocityModelResultsCheck,
    SecurityWhitelist,
    FraudAppealTemporaryBlock,
    FraudTelcoMaidTemporaryBlock,
    FraudBlockAccount,
)
from juloserver.geohash.constants import SUPPORTED_GEOHASH_PRECISIONS
from juloserver.geohash.models import AddressGeolocationGeohash
from juloserver.geohash.services import (
    geohash_precision,
    get_geohash_reverse,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    ApplicationHistory,
    Customer,
    DeviceIpHistory,
    FeatureSetting,
    FraudHotspot,
    Loan,
    VPNDetection,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    calculate_distance,
    process_application_status_change,
)
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.loan.constants import LoanStatusChangeReason
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.moengage.services.use_cases import send_fraud_ato_device_change_event
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.pin.models import (
    LoginAttempt,
    BlacklistedFraudster,
)
from juloserver.streamlined_communication.tasks import send_pn_fraud_ato_device_change

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@cache_for_request
def get_ato_device_change_setting():
    return ATODeviceChangeSetting()


class ATODeviceChangeSetting:
    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.FRAUD_ATO_DEVICE_CHANGE)

    @property
    def is_active(self):
        return self.setting.is_active

    @property
    def fraud_distance_in_km(self):
        return int(self.setting.get('fraud_distance_in_km', 50))

    @property
    def transaction_range_in_day(self):
        return int(self.setting.get('transaction_range_in_day', 5))

    @property
    def push_notification_delay_in_second(self):
        return int(self.setting.get('push_notification_delay_in_second', 20))


class ATODeviceChangeLoanChecker:
    CHECK_TRANSACTION_METHODS = (
        TransactionMethodCode.DOMPET_DIGITAL.code,
        TransactionMethodCode.OTHER.code,
        TransactionMethodCode.PULSA_N_PAKET_DATA.code,
        TransactionMethodCode.E_COMMERCE.code,
        TransactionMethodCode.SELF.code,
    )

    def __init__(self, loan: Loan, android_id: str):
        self.loan = loan
        self.android_id = android_id
        self.setting = get_ato_device_change_setting()
        self._check_data = None
        self._can_be_block = False
        logger.debug(
            {
                'message': 'Initial ATO Device change transaction Checker',
                'loan_id': loan.id,
                'android_id': android_id,
            }
        )

    def is_fraud(self):
        if not self.setting.is_active:
            return False

        # Early return to exclude julo email accounts from the logic
        if self.loan.customer.email:
            email = self.loan.customer.email
            is_julo_email = any(
                substring in email for substring in ['julofinance.com', 'julo.co.id']
            )
            if is_julo_email:
                return False

        logger.info(
            {
                'message': 'ATO Device change transaction checking',
                'loan_id': self.loan.id,
                'android_id': self.android_id,
            }
        )
        if self.loan.transaction_method_id not in self.CHECK_TRANSACTION_METHODS:
            return False

        if is_android_whitelisted_by_customer(self.loan.customer_id, self.android_id):
            return False

        suspicious_flag = get_suspicious_device_change_flag(
            self.android_id,
            self.loan.cdate,
            setting=self.setting,
        )

        if suspicious_flag is None:
            return False

        if self.loan.transaction_method_id == TransactionMethodCode.SELF.code:
            if not self._is_change_bank_account_destination_day_diff_under_config():
                logger.info(
                    {
                        'message': 'ATO Device change transaction '
                        'checked negative, the bank account is not suspicious',
                        'loan_id': self.loan.id,
                        'android_id': self.android_id,
                    }
                )
                return False

        self._can_be_block = True
        self._check_data = {
            'transaction_method_id': self.loan.transaction_method_id,
            'fraud_flag_id': suspicious_flag.id,
            'current_android_id': self.android_id,
            'checked_android_id': suspicious_flag.extra.get('prev_android_id'),
        }
        logger.info(
            {
                'message': 'ATO Device change transaction checked positive',
                'loan_id': self.loan.id,
                'android_id': self.android_id,
                'check_data': self._check_data,
            }
        )

        return True

    def block(self):
        if not self._can_be_block:
            return None

        fraud_flag = self._flag_as_fraud()
        execute_after_transaction_safely(
            lambda: send_fraud_ato_device_change_event.delay(fraud_flag.id)
        )
        self._force_logout()

        # Send PN to the customer device
        execute_after_transaction_safely(
            lambda: send_pn_fraud_ato_device_change.apply_async(
                [self.loan.customer_id],
                countdown=self.setting.push_notification_delay_in_second,
            ),
        )

        logger.info(
            {
                'message': 'ATO Device change transaction block successful',
                'loan_id': self.loan.id,
                'check_data': self._check_data,
            }
        )
        return fraud_flag

    def _force_logout(self):
        user_id = (
            Customer.objects.filter(id=self.loan.customer_id)
            .values_list('user_id', flat=True)
            .first()
        )
        generate_new_token_and_refresh_token(user_id)

    @transaction.atomic
    def _flag_as_fraud(self):
        change_reason = self._change_reason_message()
        if self.loan.account is not None:
            process_change_account_status(
                account=self.loan.account,
                new_status_code=JuloOneCodes.FRAUD_REPORTED,
                change_reason=change_reason,
            )

        update_loan_status_and_loan_history(
            loan_id=self.loan.id,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_reason=change_reason,
        )
        return FraudFlag.objects.create(
            customer_id=self.loan.customer_id,
            fraud_type=FraudFlagType.ATO_DEVICE_CHANGE,
            trigger=FraudFlagTrigger.LOAN_CREATION,
            flag_source_type=FraudFlagSource.LOAN,
            flag_source_id=self.loan.id,
            extra=self._check_data,
        )

    def _change_reason_message(self):

        return "Fraud ATO Device Change"

    def _is_change_bank_account_destination_day_diff_under_config(self):
        back_account_destinations = BankAccountDestination.objects.filter(
            customer_id=self.loan.customer_id,
            bank_account_category__category=BankAccountCategoryConst.SELF,
        ).order_by('cdate')
        total_bank_account_destination = len(back_account_destinations)
        if total_bank_account_destination < 2:
            return False

        target_bank = back_account_destinations[total_bank_account_destination - 1]

        if total_bank_account_destination >= 3:
            if (
                back_account_destinations[0].account_number
                == back_account_destinations[total_bank_account_destination - 1].account_number
            ):
                target_bank = back_account_destinations[total_bank_account_destination - 2]

        now = datetime.now(timezone.utc)
        day_diff = abs((now - target_bank.cdate).days)
        day_diff_threshold = self.setting.setting.get('day_different', 4)

        return day_diff <= day_diff_threshold


def check_login_for_ato_device_change(current_attempt: LoginAttempt) -> Union[FraudFlag, None]:
    """
    Mark the android_id if fit for ATO device change rules:
    1. Different android_id than the previous login's android_id
    2. More than 50km from the previous login

    Args:
        current_attempt (LoginAttempt): Current login attempt.

    Returns:
        None, if pass the check. FraudFlag, if fit for all the rules.

    """
    ato_device_change_setting = get_ato_device_change_setting()
    if not ato_device_change_setting.is_active:
        return None

    logger.info(
        {
            'message': 'ATO Device change login checking',
            'login_attempt_id': current_attempt.id,
            'customer_id': current_attempt.customer_id,
            'android_id': current_attempt.android_id,
        }
    )
    # Skip if the android_id is whitelisted for the customer.
    if is_android_whitelisted_by_customer(current_attempt.customer_id, current_attempt.android_id):
        return None

    # Get 2 latest login_attempt to compare their geolocation and android_id
    prev_attempt = LoginAttempt.objects.filter(
        id__lt=current_attempt.id,
        customer_id=current_attempt.customer_id,
        is_success=True,
    ).last()

    # For first login attempt, compare with coordinates stored during regsiteration
    if prev_attempt is None:
        address_geolocation = AddressGeolocation.objects.filter(
            application__customer_id=current_attempt.customer_id
        ).last()
        if not address_geolocation:
            return None

        device = current_attempt.customer.device_set.filter(android_id__isnull=False).first()
        if not device:
            return None
        prev_attempt_android_id = device.android_id

        prev_attempt_latitude = address_geolocation.latitude
        prev_attempt_longitude = address_geolocation.longitude

    else:
        # Skip if the both latest login_attempts have the same android_id.
        prev_attempt_android_id = prev_attempt.android_id

        if not prev_attempt.has_geolocation or not current_attempt.has_geolocation:
            return None

        prev_attempt_latitude = prev_attempt.latitude
        prev_attempt_longitude = prev_attempt.longitude

    if not prev_attempt_android_id or prev_attempt_android_id == current_attempt.android_id:
        return None

    # Skip if the the latest login_attempt's geolocation is < 50km from the 2nd.
    distance = calculate_distance(
        prev_attempt_latitude,
        prev_attempt_longitude,
        current_attempt.latitude,
        current_attempt.longitude,
    )
    if distance < ato_device_change_setting.fraud_distance_in_km:
        return None

    # Store the android_id to fraud_flag.
    extra_data = {
        'current_login_attempt_id': current_attempt.id,
        'prev_login_attempt_id': prev_attempt.id if prev_attempt else None,
        'distance': distance,
        'current_android_id': current_attempt.android_id,
        'prev_android_id': prev_attempt_android_id,
    }
    fraud_flag = FraudFlag.objects.create(
        customer_id=current_attempt.customer_id,
        fraud_type=FraudFlagType.ATO_DEVICE_CHANGE,
        flag_source_type=FraudFlagSource.ANDROID,
        flag_source_id=current_attempt.android_id,
        trigger=FraudFlagTrigger.LOGIN_SUCCESS,
        extra=extra_data,
    )
    logger.info(
        {
            'message': 'ATO Device change login checking',
            'login_attempt_id': current_attempt.id,
            'customer_id': current_attempt.customer_id,
            'android_id': current_attempt.android_id,
            'fraud_flag_id': fraud_flag.id,
        }
    )
    return fraud_flag


def get_suspicious_device_change_flag(
    android_id: str,
    check_time: datetime,
    setting: ATODeviceChangeSetting = None,
) -> FraudFlag:
    if setting is None:
        setting = get_ato_device_change_setting()
    return (
        FraudFlag.objects.suspicious_device_change(android_id)
        .filter(
            cdate__gte=check_time - timedelta(days=setting.transaction_range_in_day),
        )
        .last()
    )


def is_android_whitelisted_by_customer(customer_id: int, android_id: str) -> bool:
    """
    Check if the android is whitelisted for a specific customer or not.
    Args:
        customer_id (int): The customer id
        android_id (str): The android id
    Returns:
        bool
    """
    return SecurityWhitelist.objects.filter(
        customer_id=customer_id,
        object_type=FraudFlagSource.ANDROID,
        object_id=android_id,
    ).exists()


def is_android_whitelisted(android_id: str) -> bool:
    """
    Check if the android is whitelisted
    Args:
        android_id (str): The android id
    Returns:
        bool
    """
    return SecurityWhitelist.objects.filter(
        object_type=FraudFlagSource.ANDROID,
        object_id=android_id,
    ).exists()


def fetch_blacklist_whitelist_records(query=None):
    blacklisted = BlacklistedFraudster.objects.all()
    whitelisted = SecurityWhitelist.objects.all()
    if query:
        whitelisted = whitelisted.filter(
            Q(customer__id__icontains=str(query)) | Q(object_id__icontains=str(query))
        )
        blacklisted = blacklisted.filter(android_id__icontains=str(query))
    result_list = sorted(
        chain(blacklisted, whitelisted), key=lambda instance: instance.cdate, reverse=True
    )
    result_list = result_list[:10]
    return result_list


def process_and_save_whitelist_blacklist_data(validated_data):
    type = validated_data.get("type")
    data_list = validated_data.get("data")
    reason = validated_data.get("reason")
    try:
        with transaction.atomic():
            if type == "blacklist":
                for android_id in data_list:
                    BlacklistedFraudster.objects.get_or_create(
                        android_id=android_id, defaults={'blacklist_reason': str(reason)}
                    )
                return True, None

            if type == "whitelist":
                for android_id, customer_id in data_list:
                    SecurityWhitelist.objects.get_or_create(
                        object_id=android_id,
                        customer_id=customer_id,
                        object_type="android_id",
                        defaults={"reason": str(reason)},
                    )
                return True, None

            return False, "Invalid type."
    except DatabaseError as e:
        logger.exception(
            {
                "action": "process_and_save_whitelist_blacklist_data",
                "message": "Database error during save",
                "exc_str": str(e),
            }
        )
        return False, str(e)


@cache_for_request
def get_fraud_velocity_model_geohash_setting():
    return FraudVelocityModelGeohashSetting()


def fraud_velocity_model_geohash_enabled_wrapper(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        feature_setting = get_fraud_velocity_model_geohash_setting()
        if feature_setting.is_active:
            return func(*args, **kwargs)
        return None

    return wrapper


def is_enable_fraud_geohash_verification_wrapper(func):
    """
    Decorator function so that the function is executed with these criteria:
    1. Feature setting "fraud_velocity_model_geohash" is enable.
    2. The parameter "is_enable_fraud_verification" is True

    Args:
        func (callable):

    Returns:
        callable
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        feature_setting = get_fraud_velocity_model_geohash_setting()
        if feature_setting.is_active and feature_setting.is_enable_fraud_verification:
            return func(*args, **kwargs)
        return None

    return wrapper


@dataclass
class GeohashPrecisionParameter:
    """
    Geohash Precision Parameter for Fraud Velocity Model Geohash (Part of Faster Fraud Hotspot).
    """

    check_period_day: int  # flake8: noqa 701
    check_period_compare_day: int  # flake8: noqa 701
    threshold_total_app_in_period: int  # flake8: noqa 701
    threshold_rate_app_in_period: float  # flake8: noqa 701
    flag_period_day: int  # flake8: noqa 701


class FraudVelocityModelGeohashSetting:
    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.FRAUD_VELOCITY_MODEL_GEOHASH)

    @property
    def is_active(self):
        return self.setting.is_active

    def get_geohash_parameter(self, precision: int) -> GeohashPrecisionParameter:
        """
        Get the geohash parameter based on the precision.

        Args:
            precision (int): The geohash precision. ex: 8,9

        Returns:
            GeohashPrecisionParameter
        """
        parameter_key = "geohash{}".format(precision)
        geohash_parameter_dict = self.setting.get(parameter_key)
        if geohash_parameter_dict is None:
            raise JuloException('Fraud Velocity Model Geohash is not configured properly.')

        return GeohashPrecisionParameter(
            check_period_day=int(
                geohash_parameter_dict.get(
                    'check_period_day',
                    7,
                )
            ),
            check_period_compare_day=int(
                geohash_parameter_dict.get(
                    'check_period_compare_day',
                    14,
                )
            ),
            threshold_total_app_in_period=int(
                geohash_parameter_dict.get(
                    'threshold_total_app_in_period',
                    6,
                )
            ),
            threshold_rate_app_in_period=float(
                geohash_parameter_dict.get('threshold_rate_app_in_period', 2.0)
            ),
            flag_period_day=int(geohash_parameter_dict.get('flag_period_day', 21)),
        )

    @property
    def skip_verified_geohash_day(self):
        """
        The total day we should skip the check if the geohash has been verified in
        ops.fraud_velocity_model_geohash_bucket and ops.fraud_velocity_model_result_check.

        Returns:
            integer
        """
        return int(self.setting.get('skip_verified_geohash_day', 3))

    @property
    def check_period_day(self):
        """
        Deprecated. Please see `get_geohash_parameter()`
        The total day that will be used to calculate the total registered application.

        Returns:
            integer
        """
        return int(self.setting.get('check_period_day', 7))

    @property
    def check_period_compare_day(self):
        """
        Deprecated. Please see `get_geohash_parameter()`

        The total day that will be used as the comparison of the total registered application.
        This value should be higher than `check_period_day`.
        Returns:
            integer
        """
        return int(self.setting.get('check_period_compare_day', 14))

    @property
    def threshold_total_app_in_period(self):
        """
        Deprecated. Please see `get_geohash_parameter()`

        The threshold for total registered application from `check_period_day` data.

        Returns:
            integer
        """
        return int(self.setting.get('threshold_total_app_in_period', 6))

    @property
    def threshold_rate_app_in_period(self):
        """
        Deprecated. Please see `get_geohash_parameter()`

        The threshold for the rate registered application.
            rate = <total application from check_period_day>
                    / (<total application from check_period_compare_day>
                        - <total application from check_period_day>)

        Returns:
            float
        """
        return float(self.setting.get('threshold_rate_app_in_period', 2))

    @property
    def flag_period_day(self):
        """
        Deprecated. Please see `get_geohash_parameter()`

        All registered applications in this period day will be flag and stored in
        `ops.fraud_velocity_model_geohash`.

        Returns:
            integer
        """
        return int(self.setting.get('flag_period_day', 21))

    @property
    def is_enable_fraud_verification(self):
        """
        Flag for fraud verification logic. If this is turn off,
        1. No application/account will be moved to fraud suspicious status.
        2. No new geohash in the velocity model bucket.

        Returns:
            bool
        """
        return bool(self.setting.get('is_enable_fraud_verification', False))


def get_x105_velocity_model_data(application_ids):
    """
    Get application data for fraud_velocity_model_geohash table data.

    Args:
        application_ids (List): List of application ids

    Returns:
        Dict: Map to look up based on application_id with this sample
            ```
                {
                    "20000001": {
                        "x105_cdate": '2022-01-01",
                        "x105_complete_duration": 1234,
                    }
                }
            ```
    """
    x105_data = (
        ApplicationHistory.objects.filter(
            application_id__in=application_ids,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
        )
        .annotate(
            x105_date=Min('cdate'),
            x105_complete_duration=Min('cdate') - Min('application__cdate'),
        )
        .values('application_id', 'x105_date', 'x105_complete_duration')
    )

    return {
        data['application_id']: {
            'x105_date': timezone.localtime(data['x105_date']).date(),
            'x105_complete_duration': data['x105_complete_duration'].seconds,
        }
        for data in x105_data
    }


def add_android_id_to_blacklisted_fraudster(android_id, change_reason):
    """
    Add android_id to the `ops.blacklisted_fraudster` if not exist
    Args:
        android_id (str): The android_id
        change_reason (str): The change reason of the blacklist.

    Returns:
        BlacklistedFraudster
    """
    blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(
        android_id=android_id, defaults={'blacklist_reason': change_reason}
    )
    return blacklisted_fraudster


def add_geohash_to_fraud_hotspot(geohash_str):
    """
    Add the geohash string to the fraud hotspot if not created.

    Args:
        geohash_str (str): the geohash string

    Returns:
        FraudHotspot
    """
    geohash_reverse = get_geohash_reverse(geohash_str, is_create=True)

    fraud_hotspot, _ = FraudHotspot.objects.get_or_create(
        geohash=geohash_str,
        defaults={
            'latitude': geohash_reverse.latitude,
            'longitude': geohash_reverse.longitude,
            'radius': geohash_reverse.estimated_radius,
        },
    )
    return fraud_hotspot


class VelocityModelGeohashService:
    """
    This class only to wrap related function.
    Especially for protected function.
    """

    @classmethod
    def update_application_or_account_status(cls, application, is_fraud, change_reason):
        """
        Update the application/account based on is_fraud status in geohash verification process.
        if the application status is 190, we will update the account status.

        If is_fraud, we will update the application/account to fraud status. If not, we update
        the status before it move to suspicious status.

        Args:
            application (Application): The application object that will be monitor.
            is_fraud (bool): Is fraud or not.
            change_reason (str): The change reason

        Returns:

        """
        if application.status != ApplicationStatusCodes.LOC_APPROVED:
            return cls._update_application_status(application, is_fraud, change_reason)

        return cls._update_account_status(application.account, is_fraud, change_reason)

    @staticmethod
    def _update_application_status(application, is_fraud, change_reason):
        old_status = application.status
        if application.status in (
            ApplicationStatusCodes.LOC_APPROVED,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ):
            return application.status, application.status

        if is_fraud:
            new_status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
            is_success = process_application_status_change(
                application.id,
                new_status,
                change_reason=change_reason,
            )
            return old_status, new_status if is_success else old_status

        last_history = application.applicationhistory_set.last()
        if not last_history or last_history.status_new != (
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
        ):
            return old_status, application.status

        is_success = process_application_status_change(
            application.id,
            last_history.status_old,
            change_reason=change_reason,
        )
        return old_status, last_history.status_old if is_success else old_status

    @staticmethod
    def _update_account_status(account, is_fraud, change_reason):
        old_status = account.status_id
        if is_fraud:
            new_status = JuloOneCodes.FRAUD_REPORTED
            process_change_account_status(
                account,
                new_status,
                change_reason=change_reason,
            )
            return old_status, new_status

        last_history = account.accountstatushistory_set.last()
        if not last_history or last_history.status_new_id != JuloOneCodes.FRAUD_SUSPICIOUS:
            return old_status, account.status_id

        process_change_account_status(
            account,
            last_history.status_old_id,
            change_reason=change_reason,
        )
        return old_status, last_history.status_old_id

    @staticmethod
    @transaction.atomic()
    def add_application_to_velocity_model_geohash(
        geohash_str: str,
        risky_date: date,
        filter_date: date,
    ):
        """
        Add the application data to `ops.fraud_velocity_model_geohash` table based on the geohash.

        Args:
            geohash_str (string): The geohash string.
            risky_date (date): The risky date or the checking date.
            filter_date (date): Minimum date to filter the application cdate data.

        Returns:
            list[int]: list of application_ids.
        """
        precision = geohash_precision(geohash_str)
        if precision not in SUPPORTED_GEOHASH_PRECISIONS:
            raise ValueError('Geohash precision is not support.')

        geohash_filter = {
            'geohash{}'.format(precision): geohash_str,
        }
        application_ids = (
            AddressGeolocationGeohash.objects.filter(
                address_geolocation__application__product_line_id__in=ProductLineCodes.j1(),
                address_geolocation__application__cdate__date__gt=filter_date,
                **geohash_filter,
            )
            .order_by('-address_geolocation__application_id')
            .values_list(
                'address_geolocation__application_id',
                flat=True,
            )
        )
        exist_application_ids = FraudVelocityModelGeohash.objects.filter(
            application_id__in=application_ids,
            geohash=geohash_str,
        ).values_list('application_id', flat=True)
        not_exist_application_ids = set(application_ids) - set(exist_application_ids)

        map_x105_velocity_model = get_x105_velocity_model_data(not_exist_application_ids)
        velocity_model_geohashes = []
        for application_id in not_exist_application_ids:
            velocity_model_geohashes.append(
                FraudVelocityModelGeohash(
                    application_id=application_id,
                    geohash=geohash_str,
                    risky_date=risky_date,
                    x105_date=map_x105_velocity_model.get(application_id, {}).get('x105_date'),
                    x105_complete_duration=(
                        map_x105_velocity_model.get(application_id, {}).get(
                            'x105_complete_duration'
                        )
                    ),
                )
            )
        FraudVelocityModelGeohash.objects.bulk_create(velocity_model_geohashes, batch_size=40)
        return application_ids

    @classmethod
    def verify_fraud_velocity_geohash_bucket(
        cls,
        velocity_geohash_bucket: FraudVelocityModelGeohashBucket,
        model_result_check: FraudVelocityModelResultsCheck,
        auth_user: User = None,
    ):
        """
        Verify the geohash bucket using the velocity model results check from the CRM.

        Args:
            velocity_geohash_bucket (FraudVelocityModelGeohashBucket): The bucket object.
            model_result_check (FraudVelocityModelResultsCheck): The result of the verification.
            auth_user (User): The user who verify the geohash bucket.

        Returns:
            None

        """
        from juloserver.fraud_security.tasks import (
            store_verification_result_for_velocity_model_geohash,
        )

        # Update the bucket first to mark as verified so that the processing data from
        # add_geohash_to_velocity_model_geohash_bucket() task will not change the status for
        # application/account.
        with transaction.atomic():
            velocity_geohash_bucket = (
                FraudVelocityModelGeohashBucket.objects.select_for_update().get(
                    id=velocity_geohash_bucket.id,
                )
            )

            # Skip if the bucket has been verified.
            if velocity_geohash_bucket.is_verified:
                return

            velocity_geohash_bucket.fraud_velocity_model_results_check = model_result_check
            velocity_geohash_bucket.agent_user = auth_user
            velocity_geohash_bucket.save(
                update_fields=['fraud_velocity_model_results_check', 'agent_user'],
            )

            if model_result_check.is_fraud:
                # Add the geohash to fraud_hotspot table.
                add_geohash_to_fraud_hotspot(velocity_geohash_bucket.geohash)

                # Add the new application data to `ops.fraud_velocity_model_geohash
                now = timezone.localtime(timezone.now())
                cls.add_application_to_velocity_model_geohash(
                    geohash_str=velocity_geohash_bucket.geohash,
                    risky_date=now.date(),
                    filter_date=now.date() - relativedelta(days=1),
                )

        store_verification_result_for_velocity_model_geohash.delay(velocity_geohash_bucket.id)


def fetch_unchecked_geohashes(search_q=None, sort_q=None):
    data = FraudVelocityModelGeohashBucket.objects.filter(
        fraud_velocity_model_results_check__isnull=True
    )

    if search_q:
        unchecked_geohashes_query = FraudVelocityModelGeohash.objects.filter(
            geohash__in=data.values_list('geohash', flat=True),
            application__fraudverificationresults__isnull=True,
        )
        if search_q.isnumeric():
            unchecked_geohashes = unchecked_geohashes_query.filter(
                application_id=search_q
            ).values_list('geohash', flat=True)
        else:
            unchecked_geohashes = unchecked_geohashes_query.filter(
                Q(application__email=search_q)
                | Q(application__fullname__icontains=search_q)
                | Q(application__customer__device__android_id=search_q)
            ).values_list('geohash', flat=True)
        data = data.filter(Q(geohash__icontains=search_q) | Q(geohash__in=unchecked_geohashes))

    if sort_q:
        data = data.order_by(sort_q)

    return data


def fetch_geohash_applications(bucket_id, search_q=None, sort_q=None):
    geohash_bucket = FraudVelocityModelGeohashBucket.objects.get(id=bucket_id)
    application_ids = FraudVelocityModelGeohash.objects.filter(
        geohash=geohash_bucket.geohash, application__fraudverificationresults__isnull=True
    ).values_list('application_id', flat=True)
    applications = Application.objects.filter(id__in=application_ids)

    if search_q:
        if search_q.isnumeric():
            applications = applications.filter(id=search_q)
        else:
            applications = applications.filter(
                Q(email=search_q)
                | Q(fullname__icontains=search_q)
                | Q(customer__device__android_id=search_q)
            )

    if sort_q:
        applications = applications.order_by(sort_q)

    return applications


def update_and_record_geohash_result_check(validated_data, agent_user):
    bucket_id = validated_data.pop('bucket_id')
    results_check = FraudVelocityModelResultsCheck.objects.create(**validated_data)
    velocity_geohash_bucket = FraudVelocityModelGeohashBucket.objects.get(id=bucket_id)
    VelocityModelGeohashService.verify_fraud_velocity_geohash_bucket(
        velocity_geohash_bucket, results_check, agent_user
    )
    return results_check


def blacklisted_asn_check(application):
    """
    To check if application falls under blacklisted ASN and if it does
    we move it to Application status x133 (APPLICATION_FLAGGED_FOR_FRAUD)

    Args:
        application: application object.
    Returns:
        bool: True If blacklisted ASN is detected,
              False If not blacklisted ASN or bypass due to insufficient data for the check
    """
    blocked_asn_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BLACKLISTED_ASN, is_active=True
    ).last()
    if not blocked_asn_feature:
        return False

    app_risky_check = ApplicationRiskyCheck.objects.filter(application=application).last()
    device_ip_history = DeviceIpHistory.objects.filter(customer=application.customer).last()

    if not device_ip_history:
        return False
    vpn_detection = VPNDetection.objects.filter(ip_address=device_ip_history.ip_address).last()
    if (
        vpn_detection
        and vpn_detection.extra_data
        and (vpn_detection.is_vpn_detected or (app_risky_check and app_risky_check.is_vpn_detected))
    ):
        asn_data = vpn_detection.extra_data.get('org')
        if not asn_data:
            return False
        if FraudBlacklistedASN.objects.filter(asn_data=asn_data).exists():
            return True
    return False


def check_swift_limit_drainer(application: Application, transaction_code: int) -> bool:
    """
    Checks if a customer making loan is considered Swift Limit Drainer.
    The ruleset for checking is dictated based on the analysis of the data team.
    For more details: https://juloprojects.atlassian.net/browse/ANTIFRAUD-34

    Args:
        application (Application): Application model object to be checked for swift limit drainer.
        transaction_code (int): The transaction type code based of the TransactionMethodCode class
            in juloserver.payment_point.constants.

    Returns:
        (bool): Returns True if detected as Swift Limit Drainer, False otherwise.
    """
    log_data = {
        'action': 'check_swift_limit_drainer',
        'application_id': application.id,
        'transaction_code': transaction_code,
    }

    try:
        if not FeatureSetting.fetch_feature_state(FeatureNameConst.SWIFT_LIMIT_DRAINER):
            logger.info(
                {
                    'message': 'Cancel check because FeatureSetting us turned off.',
                    **log_data,
                }
            )
            return False

        customer_id = application.customer.id
        account = application.account
        customer_mycroft = PdApplicationFraudModelResult.objects.filter(
            customer_id=customer_id, application_id=application.id
        ).last()
        if customer_mycroft is None:
            logger.info(
                {
                    'message': 'Customer bypass swift limit drainer check due to missing mycroft '
                    'record.',
                    **log_data,
                }
            )
            return False
        mycroft_score = customer_mycroft.pgood
        application_status_code = application.application_status.status_code
        log_data.update(
            mycroft_score=mycroft_score, application_status_code=application_status_code
        )
        if mycroft_score < 0.8 or application_status_code != ApplicationStatusCodes.LOC_APPROVED:
            logger.info({'message': 'Customer passes swift limit drainer check.', **log_data})
            return False

        first_status_190 = ApplicationHistory.objects.filter(
            application=application, status_new=190
        ).first()
        valid_loans = application.customer.loan_set.filter(
            loan_status__in=LoanStatusCodes.loan_status_eligible_swift_limit(),
        )
        loan_count = valid_loans.count()
        log_data.update(loan_count=loan_count)

        if loan_count >= 2:
            # (Mycroft >= 0.8 AND time from x190 to Loan Number >= 2 is under 20 minutes)
            last_loan_time = valid_loans.last().cdate
            application_190_to_last_loan_time = (
                last_loan_time - first_status_190.cdate
            ).total_seconds()
            log_data.update(application_190_to_last_loan_time=application_190_to_last_loan_time)
            if mycroft_score >= 0.8 and application_190_to_last_loan_time < 1200:
                logger.info(
                    {
                        'message': 'Swift Limit Drainer detected.',
                        **log_data,
                    }
                )
                return True
        else:
            first_loan_time = valid_loans.first().cdate
            application_190_to_first_loan_time = (
                first_loan_time - first_status_190.cdate
            ).total_seconds()

            # (Mycroft: 0.8-0.85 AND Heimdall >= 0.8 AND time from x190 to first loan <= 20 minutes
            #   AND (Transaction Type = Pulsa & Paket Data OR Transaction Type = Self))
            customer_heimdall = PdCreditModelResult.objects.filter(
                application_id=application.id, customer_id=customer_id
            ).last()
            heimdall_score = customer_heimdall.pgood
            log_data.update(
                application_190_to_first_loan_time=application_190_to_first_loan_time,
                heimdall_score=heimdall_score,
            )
            if (
                0.8 <= mycroft_score <= 0.85
                and heimdall_score >= 0.8
                and application_190_to_first_loan_time <= 1200
                and transaction_code in TransactionMethodCode.swift_limit_transaction_codes()
            ):
                logger.info(
                    {
                        'message': 'Swift Limit Drainer detected.',
                        **log_data,
                    }
                )
                return True

            # (Mycroft: 0.8-0.9 AND time from x190 to first loan <= 10 minutes
            #   AND (Account Limit >= 5,000,000 OR the first loan amount >= 4,000,000))
            if 0.8 <= mycroft_score <= 0.9 and application_190_to_first_loan_time <= 600:
                account_limit = account.accountlimit_set.last()
                first_loan_amount = valid_loans.first().loan_amount
                log_data.update(
                    account_limit=account_limit.set_limit, loan_amount=first_loan_amount
                )
                if (
                    account_limit.set_limit >= SwiftLimitDrainerConditionValues.ACCOUNT_SET_LIMIT
                    or first_loan_amount >= SwiftLimitDrainerConditionValues.FIRST_LOAN_AMOUNT
                ):
                    logger.info(
                        {
                            'message': 'Swift Limit Drainer detected.',
                            **log_data,
                        }
                    )
                    return True

        logger.info({'message': 'Customer passes swift limit drainer check.', **log_data})

        return False
    except Exception as e:
        sentry_client.captureException()

        logger.info(
            {
                'message': 'Swift limit check bypassed due to error.',
                'error': e,
                **log_data,
            }
        )

        return False


def block_swift_limit_drainer_account(account: Account, loan_id: int) -> None:
    """
    Move account to 440 - Blocked Swift Limit Drainer and insert into
        juloserver.fraud_security.FraudSwiftLimitDrainerAccount.

    Args:
        account_id (Account): juloserver.account.models.Account object.
        loan_id (int): id property of juloserver.julo.models.Loan model.
    """
    update_loan_status_and_loan_history(
        loan_id,
        new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
        change_reason=LoanStatusChangeReason.SWIFT_LIMIT_DRAINER,
    )
    process_change_account_status(
        account, AccountConstant.STATUS_CODE.fraud_reported, AccountChangeReason.SWIFT_LIMIT_DRAINER
    )
    FraudBlockAccount.objects.create(
        account=account,
        feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
        is_appeal=False,
        is_confirmed_fraud=False,
        is_block=False,
        is_need_action=True,
        is_verified_by_agent=False,
    )


def is_account_appeal_temporary_block(account: Account) -> bool:
    fraud_appeal_temporary_block_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUD_APPEAL_TEMPORARY_BLOCK
    ).last()
    is_active_fraud_appeal_temporary_block_fs = (
        fraud_appeal_temporary_block_fs.is_active if fraud_appeal_temporary_block_fs else False
    )
    if not is_active_fraud_appeal_temporary_block_fs:
        return False
    return FraudAppealTemporaryBlock.objects.filter(account_id=account.id).exists()


def loan_fraud_block(
    application: Application,
    account: Account,
    loan: Loan,
    binary_check_status: ABCStatus,
) -> Union[int, None]:
    """
    Block loan and account if the loan is fraud.

    Args:
        application (Application): Application object.
        account (Account): Account object.
        loan (Loan): Loan object.
        binary_check_status (ABCStatus): The binary check status.

    Returns:
        int: The new loan status code.
    """

    new_loan_status = LoanStatusCodes.TRANSACTION_FAILED
    change_reason = None

    if binary_check_status == ABCStatus.TELCO_MAID_LOCATION:
        change_reason = LoanStatusChangeReason.TELCO_MAID_LOCATION
    elif binary_check_status == ABCStatus.FRAUD_REPORTED_LOAN:
        change_reason = LoanStatusChangeReason.FRAUD_LOAN_BLOCK
    elif binary_check_status == ABCStatus.SWIFT_LIMIT_DRAINER:
        change_reason = LoanStatusChangeReason.SWIFT_LIMIT_DRAINER

    update_loan_status_and_loan_history(
        loan_id=loan.id,
        new_status_code=new_loan_status,
        change_reason=change_reason,
    )
    process_change_account_status(
        account=account,
        new_status_code=AccountConstant.STATUS_CODE.__dict__.get('fraud_reported', None),
        change_reason=change_reason,
    )

    event_loan_fraud_block.delay(
        binary_check_status,
        application.customer_id,
    )

    # create fraud block account related to appeal feature
    if binary_check_status == ABCStatus.SWIFT_LIMIT_DRAINER:
        FraudBlockAccount.objects.create(
            account=account,
            feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
            is_appeal=False,
            is_confirmed_fraud=False,
            is_block=False,
            is_need_action=True,
            is_verified_by_agent=False,
        )
    elif binary_check_status == ABCStatus.FRAUD_REPORTED_LOAN:
        if (
            application.is_julo_starter()
            and application.application_status.status_code
            == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        ):
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                change_reason=JuloOneChangeReason.FRAUD_CHANGE_REASON,
            )

    return new_loan_status


def block_telco_maid_location_account(account: Account, loan_id: int) -> None:
    """
    Move account to 440 - Blocked telco maid location.

    Args:
        account_id (Account): juloserver.account.models.Account object.
        loan_id (int): id property of juloserver.julo.models.Loan model.
    """
    update_loan_status_and_loan_history(
        loan_id,
        new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
        change_reason=LoanStatusChangeReason.TELCO_MAID_LOCATION,
    )
    process_change_account_status(
        account, AccountConstant.STATUS_CODE.fraud_reported, AccountChangeReason.TELCO_MAID_LOCATION
    )
    FraudTelcoMaidTemporaryBlock.objects.create(account=account)


def get_fraud_block_account_list(jail_day_j1: int, jail_day_jturbo: int) -> List[dict]:

    longest_jail_days = jail_day_j1 if jail_day_j1 >= jail_day_jturbo else jail_day_jturbo

    longest_jail_date = timezone.localtime(timezone.now()).date() - timedelta(
        days=longest_jail_days
    )
    jail_date_j1 = timezone.localtime(timezone.now()).date() - timedelta(days=jail_day_j1)
    jail_date_jturbo = timezone.localtime(timezone.now()).date() - timedelta(days=jail_day_jturbo)

    fraud_block_accounts = FraudBlockAccount.objects.filter(
        cdate__date__lte=longest_jail_date, is_need_action=True
    )
    fraud_block_account_list = []
    for fraud_block_account in fraud_block_accounts:
        fraud_block_account_data = {}
        application = Application.objects.filter(account_id=fraud_block_account.account_id).last()
        if not application:
            continue
        if application.is_julo_one() and fraud_block_account.cdate.date() <= jail_date_j1:

            fraud_block_account_data[FraudBlockAccountConst.APPLICATION] = application
            fraud_block_account_data[
                FraudBlockAccountConst.FRAUD_BLOCK_ACCOUNT
            ] = fraud_block_account
            fraud_block_account_list.append(fraud_block_account_data)

        elif application.is_julo_starter() and fraud_block_account.cdate.date() <= jail_date_jturbo:

            fraud_block_account_data[FraudBlockAccountConst.APPLICATION] = application
            fraud_block_account_data[
                FraudBlockAccountConst.FRAUD_BLOCK_ACCOUNT
            ] = fraud_block_account
            fraud_block_account_list.append(fraud_block_account_data)

    return fraud_block_account_list


def fraud_block_account_action(fraud_block_account: FraudBlockAccount, application: Application):
    feature_name = fraud_block_account.feature_name
    if feature_name == FeatureNameConst.SWIFT_LIMIT_DRAINER:
        if not fraud_block_account.is_block:
            is_block = is_block_swift_limit_drainer_check_by_scheduler(
                fraud_block_account, application
            )
            fraud_block_account.is_block = is_block
            fraud_block_account.save()
        fraud_block_account_status_action(
            fraud_block_account=fraud_block_account,
            application=application,
            block_reason=AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
            unblock_reason=AccountChangeReason.SWIFT_LIMIT_DRAINER_RETURN,
            application_block_reason=JuloOneChangeReason.FRAUD_CHANGE_REASON,
        )


def fraud_block_account_status_action(
    fraud_block_account: FraudBlockAccount,
    application: Application,
    block_reason: str,
    unblock_reason: str,
    application_block_reason: str,
):
    if fraud_block_account.is_block:
        process_change_account_status(
            fraud_block_account.account,
            AccountConstant.STATUS_CODE.terminated,
            block_reason,
        )
        mark_application_as_fraudster(
            application=application, change_reason=application_block_reason
        )
    else:
        process_change_account_status(
            fraud_block_account.account,
            AccountConstant.STATUS_CODE.active,
            unblock_reason,
        )
    fraud_block_account.update_safely(is_need_action=False)


def update_fraud_block_account_by_agent(
    fraud_block_account: FraudBlockAccount,
    application: Application,
    is_appeal: bool,
    is_confirmed_fraud: bool,
):
    if fraud_block_account.feature_name == FeatureNameConst.SWIFT_LIMIT_DRAINER:
        fraud_block_account = fraud_block_account_swift_limit_drainer(
            fraud_block_account, application, is_appeal, is_confirmed_fraud
        )

    return fraud_block_account


def fraud_block_account_swift_limit_drainer(
    fraud_block_account: FraudBlockAccount,
    application: Application,
    is_appeal: bool,
    is_confirmed_fraud: bool,
) -> FraudBlockAccount:
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
        is_active=True,
    ).last()

    mycroft_param_key = 'mycroft_j1'
    if application.is_julo_starter():
        mycroft_param_key = 'mycroft_jturbo'

    if not feature_setting or mycroft_param_key not in feature_setting.parameters:
        logger.info(
            {
                'action': 'create_or_update_fraud_block_account',
                'message': 'Swift Limit Drainer is off or invalid will let is_block as is',
                'account_id': fraud_block_account.account.id,
            }
        )
        if fraud_block_account:
            fraud_block_account.is_appeal = is_appeal
            fraud_block_account.is_confirmed_fraud = is_confirmed_fraud
            fraud_block_account.is_verified_by_agent = True
            fraud_block_account.save()

        return fraud_block_account

    mycroft_threshold = feature_setting.parameters[mycroft_param_key]
    is_block = swift_limit_drainer_check(
        application, mycroft_threshold, is_appeal, is_confirmed_fraud
    )
    if fraud_block_account:
        fraud_block_account.is_appeal = is_appeal
        fraud_block_account.is_confirmed_fraud = is_confirmed_fraud
        fraud_block_account.is_verified_by_agent = True
        fraud_block_account.is_block = is_block
        fraud_block_account.is_need_action = False
        if is_block:
            process_change_account_status(
                account=fraud_block_account.account,
                new_status_code=AccountConstant.STATUS_CODE.__dict__.get('terminated', None),
                change_reason=AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
            )
            mark_application_as_fraudster(
                application=application,
                change_reason=JuloOneChangeReason.FRAUD_CHANGE_REASON,
            )
        else:
            process_change_account_status(
                account=fraud_block_account.account,
                new_status_code=AccountConstant.STATUS_CODE.__dict__.get('active', None),
                change_reason=AccountChangeReason.SWIFT_LIMIT_DRAINER_RETURN,
            )
        fraud_block_account.save()

    return fraud_block_account


def is_block_swift_limit_drainer_check_by_scheduler(
    fraud_block_account: FraudBlockAccount, application: Application
) -> bool:
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
        is_active=True,
    ).last()
    mycroft_param_key = 'mycroft_j1'
    if application.is_julo_starter():
        mycroft_param_key = 'mycroft_jturbo'
    if not feature_setting or mycroft_param_key not in feature_setting.parameters:
        logger.info(
            {
                'action': 'is_block_swift_limit_drainer_check_by_scheduler',
                'message': 'Swift Limit Drainer is off or invalid will let is_block as is',
                'account_id': fraud_block_account.account.id,
            }
        )
        return fraud_block_account.is_block

    mycroft_threshold = feature_setting.parameters[mycroft_param_key]
    return swift_limit_drainer_check(
        application,
        mycroft_threshold,
        fraud_block_account.is_appeal,
        fraud_block_account.is_confirmed_fraud,
    )


def swift_limit_drainer_check(
    application: Application,
    my_croft_threshold: int,
    is_appeal: bool = False,
    is_confirmed_fraud: bool = False,
) -> bool:
    # add this stage the application should have mycroft and fdc
    mycroft = PdApplicationFraudModelResult.objects.filter(application_id=application.id).last()
    mycroft_score = mycroft.pgood
    heimdall = PdCreditModelResult.objects.filter(application_id=application.id).last()
    is_has_fdc = heimdall.has_fdc

    is_block = True

    if is_appeal:
        if not is_confirmed_fraud and is_has_fdc and mycroft_score >= my_croft_threshold:
            is_block = False
    elif not is_appeal:
        if is_has_fdc and mycroft_score >= my_croft_threshold:
            is_block = False

    return is_block


def mark_application_as_fraudster(application: Application, change_reason: str):
    if application.application_status.status_code != ApplicationStatusCodes.LOC_APPROVED:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            change_reason=change_reason,
        )

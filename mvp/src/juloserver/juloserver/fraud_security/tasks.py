import json
import logging
from datetime import timedelta, datetime
from typing import Union, List

from celery import task
from dateutil.relativedelta import relativedelta
from django.db import (
    transaction,
)
from django.db.models import Max
from django.db.models import (
    Q,
    F,
)
from django.utils import timezone

from juloserver.account.constants import (
    AccountChangeReason,
)
from juloserver.account.constants import AccountConstant
from juloserver.account.models import (
    Account,
)
from juloserver.account.services.account_related import process_change_account_status
from juloserver.ana_api.models import PdApplicationFraudModelResult
from juloserver.antifraud.constant.call_back import CallBackType
from juloserver.antifraud.tasks.call_back_related import hit_anti_fraud_call_back_async
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.fraud_score.models import (
    MonnaiPhoneBasicInsight,
    MonnaiEmailBasicInsight,
)
from juloserver.fraud_score.monnai_services import get_monnai_repository
from juloserver.fraud_security.constants import (
    FraudBucket,
    FraudChangeReason,
    FraudFlagSource,
    FraudFlagTrigger,
    FraudFlagType,
    RedisKeyPrefix,
    FraudApplicationBucketType,
    FraudBlockAccountConst,
)
from juloserver.fraud_security.models import (
    FraudApplicationBucket,
    FraudFlag,
    FraudHighRiskAsn,
    FraudVelocityModelGeohash,
    FraudVelocityModelGeohashBucket,
    FraudVerificationResults,
    FraudSwiftLimitDrainerAccount,
    FraudTelcoMaidTemporaryBlock,
    BankNameVelocityThresholdHistory,
)
from juloserver.fraud_security.services import (
    VelocityModelGeohashService,
    add_android_id_to_blacklisted_fraudster,
    fraud_velocity_model_geohash_enabled_wrapper,
    get_fraud_velocity_model_geohash_setting,
    is_enable_fraud_geohash_verification_wrapper,
    is_account_appeal_temporary_block,
    get_fraud_block_account_list,
    fraud_block_account_action,
)
from juloserver.geohash.constants import SUPPORTED_GEOHASH_PRECISIONS
from juloserver.geohash.models import AddressGeolocationGeohash
from juloserver.geohash.services import (
    geohash_precision,
    get_geohash_reverse,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    Device,
    DeviceIpHistory,
    FeatureSetting,
    FraudHotspot,
    ApplicationHistory,
    VPNDetection,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.pin.models import BlacklistedFraudster

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='fraud')
@fraud_velocity_model_geohash_enabled_wrapper
def scan_fraud_hotspot_geohash_velocity_model():
    now = timezone.localtime(timezone.now())
    # In the midnight (0 AM) process, We want to make sure we process all the previous data.
    if now.hour == 0:
        now = now - relativedelta(days=1, hour=23, minute=59, second=59)

    today = now.date()
    geohash_qs = AddressGeolocationGeohash.objects.filter(cdate__date=today)

    # Cache the processed geohash
    try:
        redis_client = get_redis_client()
        redis_key = RedisKeyPrefix.SCAN_FRAUD_HOTSPOT_VELOCITY_MODEL
        latest_address_geolocation_geohash_id = redis_client.get(redis_key)
        if latest_address_geolocation_geohash_id:
            geohash_qs = geohash_qs.filter(id__gt=latest_address_geolocation_geohash_id)

        latest_address_geolocation_geohash = geohash_qs.last()
        redis_client.set(redis_key, latest_address_geolocation_geohash.id, timedelta(hours=6))
    except Exception as e:
        logger.exception(
            {
                'action': 'scan_fraud_hotspot_geohash_velocity_model',
                'message': 'Something wrong with the redis',
                'exception': str(e),
            }
        )
    # End of cache the processed geohash

    geohash8_list = geohash_qs.distinct().order_by('geohash8').values_list('geohash8', flat=True)
    geohash9_list = geohash_qs.distinct().order_by('geohash9').values_list('geohash9', flat=True)

    # Process geohash8
    for geohash8 in geohash8_list.iterator():
        process_fraud_hotspot_geohash_velocity_model.delay(geohash8, check_time=now)

    # Process geohash9
    for geohash9 in geohash9_list.iterator():
        process_fraud_hotspot_geohash_velocity_model.delay(geohash9, check_time=now)


@task(queue='fraud')
@fraud_velocity_model_geohash_enabled_wrapper
def process_fraud_hotspot_geohash_velocity_model(geohash_str, check_time):
    precision = geohash_precision(geohash_str)
    if precision not in SUPPORTED_GEOHASH_PRECISIONS:
        raise ValueError('Geohash precision is not support.')

    setting = get_fraud_velocity_model_geohash_setting()
    geohash_parameter = setting.get_geohash_parameter(precision)
    skip_verified_geohash_time = check_time - relativedelta(days=setting.skip_verified_geohash_day)
    check_period_time = check_time - relativedelta(
        days=geohash_parameter.check_period_day,
    )
    check_period_compare_time = check_time - relativedelta(
        days=geohash_parameter.check_period_compare_day,
    )
    flag_period_time = check_time - relativedelta(
        days=geohash_parameter.flag_period_day,
    )

    logger_data = {
        "action": "process_fraud_hotspot_geohash_velocity_model",
        "geohash": geohash_str,
        "check_time": check_time,
    }

    # Skip if the geohash has been verified.
    if FraudVelocityModelGeohashBucket.objects.filter(
        geohash=geohash_str,
        fraud_velocity_model_results_check__isnull=False,
        fraud_velocity_model_results_check__cdate__date__gte=skip_verified_geohash_time,
    ).exists():
        logger.info(
            {
                "message": "Skip because already verified in FraudVelocityModelGeohashBucket",
                **logger_data,
            }
        )
        return

    # Skip if the geohash is in fraud_hotspot
    if FraudHotspot.objects.filter(geohash=geohash_str).exists():
        logger.info(
            {
                "message": "Skip because already exists in FraudHotspot",
                **logger_data,
            }
        )
        return

    # Skip if the lower precision geohash has been marked as risky
    lower_geohash = geohash_str[:-1]
    if FraudVelocityModelGeohash.objects.filter(
        geohash=lower_geohash,
        risky_date=check_time.date(),
    ).exists():
        logger.info(
            {
                "message": "Skip because the lower precision geohash has been risky",
                "lower_geohash": lower_geohash,
                **logger_data,
            }
        )
        return

    geohash_filter = {'geohash{}'.format(precision): geohash_str}
    total_app_in_check_period = AddressGeolocationGeohash.objects.filter(
        address_geolocation__application__product_line_id__in=ProductLineCodes.j1(),
        address_geolocation__application__cdate__date__gt=check_period_time.date(),
        **geohash_filter,
    ).count()
    total_app_in_check_period_compare = AddressGeolocationGeohash.objects.filter(
        address_geolocation__application__product_line_id__in=ProductLineCodes.j1(),
        address_geolocation__application__cdate__date__lte=check_period_time.date(),
        address_geolocation__application__cdate__date__gt=check_period_compare_time.date(),
        **geohash_filter,
    ).count()

    # Skip total_app_in_7d < 6 and 7 days rate < 2 (Based on the setting)
    rate_app_registration = 0
    if total_app_in_check_period_compare > 0:
        rate_app_registration = total_app_in_check_period / total_app_in_check_period_compare
    logger_data.update(
        total_app_in_check_period=total_app_in_check_period,
        total_app_in_check_period_compare=total_app_in_check_period_compare,
        rate_app_registration=rate_app_registration,
    )
    if (
        total_app_in_check_period < geohash_parameter.threshold_total_app_in_period
        or rate_app_registration < geohash_parameter.threshold_rate_app_in_period
    ):
        logger.info(
            {
                "message": "Skip because does not fit with velocity model rules",
                **logger_data,
            }
        )
        return

    # Flag all application as risky in `ops.fraud_velocity_model_geohash`
    application_ids = VelocityModelGeohashService.add_application_to_velocity_model_geohash(
        geohash_str=geohash_str,
        risky_date=check_time.date(),
        filter_date=flag_period_time.date(),
    )

    # Move the application/account status as fraud suspicious.
    add_geohash_to_velocity_model_geohash_bucket.delay(geohash_str, application_ids)

    logger.info(
        {
            "message": "Finish processing the velocity model geohash",
            **logger_data,
            "application_ids": application_ids,
        }
    )


@task(queue='fraud')
@is_enable_fraud_geohash_verification_wrapper
def add_geohash_to_velocity_model_geohash_bucket(geohash_str, application_ids):
    """
    Add the geohash to the `ops.velocity_model_geohash_bucket`.
    Process all application_ids for fraud suspicious.

    Args:
        geohash_str (String): The geohash string.
        application_ids (List[Integer]): List of application_id.

    Returns:
         None
    """
    geohash_bucket, _ = FraudVelocityModelGeohashBucket.objects.get_or_create(
        geohash=geohash_str,
        fraud_velocity_model_results_check__isnull=True,
    )
    change_reason = "Suspicious fraud hotspot velocity model ({})".format(geohash_str)

    logger_data = {
        "action": "mark_application_as_suspicious_fraud_hotspot",
        "geohash": geohash_str,
        "geohash_bucket_id": geohash_bucket.id,
    }

    logger.info(
        {
            "message": "Start processing",
            "total_applications": len(application_ids),
            **logger_data,
            "application_ids": application_ids,
        }
    )

    exclude_application_ids = FraudVerificationResults.objects.filter(
        application_id__in=application_ids,
    ).values_list('application_id', flat=True)
    application_ids = set(application_ids) - set(exclude_application_ids)
    for application_id in application_ids:
        flag_application_as_fraud_suspicious.delay(application_id, change_reason)


@task(queue='fraud')
@is_enable_fraud_geohash_verification_wrapper
@transaction.atomic()
def flag_application_as_fraud_suspicious(application_id, change_reason):
    """
    Flag the application or account to as fraud suspicious to be check later.
    Args:
        application_id (Integer): The primary key of application table.
        change_reason (String): The change reason of the fraud suspicious.

    Returns:
        None
    """
    application = Application.objects.select_for_update().get(id=application_id)
    logger_data = {
        "action": "flag_application_as_fraud_suspicious",
        "application_id": application_id,
        "application_status": application.status,
    }

    if application.status in (
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    ):
        logger.info(
            {
                "message": "Skipped because application status.",
                **logger_data,
            }
        )
        return

    # if the application is 190.
    # Move the account status to x444.
    if application.status == ApplicationStatusCodes.LOC_APPROVED:
        account = application.account
        if account.status_id in (
            JuloOneCodes.DEACTIVATED,
            JuloOneCodes.TERMINATED,
            JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
            JuloOneCodes.FRAUD_SUSPICIOUS,
        ):
            logger.info(
                {
                    "message": "Skipped account status.",
                    "account_id": application.account_id,
                    "account_status": account.status_id,
                    **logger_data,
                }
            )
            return

        process_change_account_status(
            account,
            JuloOneCodes.FRAUD_SUSPICIOUS,
            change_reason=change_reason,
        )
        return

    # If the application status is not 190.
    # Move the application to x115
    process_application_status_change(
        application.id,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
        change_reason=change_reason,
    )


@task(queue='fraud')
def store_verification_result_for_velocity_model_geohash(velocity_geohash_bucket_id):
    """
    Do actions based on the verification results if fraud or not.
    1. Update the application/account status.
    2. if fraud, add the android_id to ops.blacklisted_fraudster.
    3. Store each application in `ops.fraud_verification_results.

    The process will be skipped if the verification hasn't been done yet.
    The application that has been added to `ops.fraud_verification_results` with the same
    `ops.fraud_velocity_model_results_check` will be skipped. So It is safe to trigger this task
    multiple times.

    Args:
        velocity_geohash_bucket_id (Integer): The primary key of
            ops.fraud_velocity_model_geohash_bucket

    Returns:
        None
    """
    velocity_geohash_bucket = FraudVelocityModelGeohashBucket.objects.get(
        id=velocity_geohash_bucket_id,
    )

    model_result_check = velocity_geohash_bucket.fraud_velocity_model_results_check

    # Skip if the bucket has not been verified.
    if not velocity_geohash_bucket.is_verified or not model_result_check:
        raise Exception('Fraud Velocity Model Geohash Bucket is not verified')

    is_fraud = model_result_check.is_fraud
    change_reason = "{} (geohash:{}) (result_id:{})".format(
        (
            FraudChangeReason.VELOCITY_MODEL_GEOHASH_FRAUD
            if is_fraud
            else FraudChangeReason.VELOCITY_MODEL_GEOHASH_NOT_FRAUD
        ),
        velocity_geohash_bucket.geohash,
        model_result_check.id,
    )

    # Get geohash reverse for verification_result_data
    geohash_reverse = get_geohash_reverse(velocity_geohash_bucket.geohash, is_create=True)
    verification_result_data_template = {
        'geohash': velocity_geohash_bucket.geohash,
        'fraud_velocity_model_results_check_id': model_result_check.id,
        'bucket': FraudBucket.VELOCITY_MODEL_GEOHASH,
        'agent_user_id': velocity_geohash_bucket.agent_user_id,
        'reason': change_reason,
        'latitude': geohash_reverse.latitude,
        'longitude': geohash_reverse.longitude,
        'radius': geohash_reverse.estimated_radius,
    }

    logger_data = {
        "action": "store_verification_result_for_velocity_model_geohash",
        "geohash": velocity_geohash_bucket.geohash,
        "result_check_id": model_result_check.id,
        "bucket_id": velocity_geohash_bucket_id,
    }
    logger.info(
        {
            "message": "Executing...",
            "change_reason": change_reason,
            "is_fraud": is_fraud,
            **logger_data,
        }
    )

    # Process all application datas
    verification_results = []
    model_geohashes = FraudVelocityModelGeohash.objects.filter(
        geohash=velocity_geohash_bucket.geohash,
        application__fraudverificationresults__isnull=True,
    ).select_related('application__account')
    for model_geohash in model_geohashes.iterator():
        try:
            logger_data.update(
                application_id=model_geohash.application_id,
                model_geohash_id=model_geohash.id,
            )
            logging.info(
                {
                    'message': "Processing...",
                    **logger_data,
                }
            )
            application = model_geohash.application
            verification_result_data = {
                'application_id': application.id,
                **verification_result_data_template,
            }

            # Skip if the fraud verification results already created for the application.
            if FraudVerificationResults.objects.filter(
                application_id=application.id,
                bucket=verification_result_data.get('bucket'),
                geohash=verification_result_data.get('geohash'),
                fraud_velocity_model_results_check_id=verification_result_data.get(
                    'fraud_velocity_model_results_check_id',
                ),
            ).exists():
                logger.info(
                    {
                        "message": (
                            "Skipped because already exists in " "fraud_verification_result table"
                        ),
                        **logger_data,
                    }
                )
                continue

            # Blacklist the android_id if fraud.
            first_device = Device.objects.filter(customer_id=application.customer_id).first()
            verification_result_data['android_id'] = (
                first_device.android_id if first_device else None
            )
            if first_device and is_fraud:
                add_android_id_to_blacklisted_fraudster(first_device.android_id, change_reason)

            # Move the application/account status
            (
                prev_status,
                new_status,
            ) = VelocityModelGeohashService.update_application_or_account_status(
                application=application,
                is_fraud=is_fraud,
                change_reason=change_reason,
            )

            verification_result_data.update(
                previous_status_code=prev_status,
                next_status_code=new_status,
            )
            verification_results.append(FraudVerificationResults(**verification_result_data))
        except Exception as e:
            logger.exception(
                {
                    "exc": str(e),
                    **logger_data,
                }
            )
            sentry_client.captureException()

    FraudVerificationResults.objects.bulk_create(verification_results, batch_size=40)


@task(queue='fraud')
def insert_fraud_application_bucket(application_id: int, change_reason: str) -> None:
    """
    Create a new fraud_application_bucket entry everytime a task is moved into 115

    Args:
        application_id (integer): The application primary keys.
        change_reason (string): The change reason during application status code.

    Returns:
        None
    """

    current_status_code = (
        Application.objects.filter(id=application_id)
        .values_list('application_status', flat=True)
        .last()
    )

    logger_data = {
        "action": "insert_fraud_application_bucket",
        "application_id": application_id,
        "change_reason": change_reason,
        "current_status_code": current_status_code,
    }

    if current_status_code != ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS:
        logger.warning(
            {
                "message": "Unexpected status code access fraud_application_bucket insertion",
                **logger_data,
            }
        )
        return

    stored_reason = (
        ApplicationHistory.objects.filter(application_id=application_id)
        .values_list('change_reason', flat=True)
        .last()
    )

    if stored_reason == change_reason == FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS:
        FraudApplicationBucket.objects.update_or_create(
            application_id=application_id,
            type=FraudApplicationBucketType.SELFIE_IN_GEOHASH,
            defaults={"is_active": True},
        )
    elif stored_reason != FraudChangeReason.ANTI_FRAUD_API_UNAVAILABLE:
        execute_after_transaction_safely(
            lambda: hit_anti_fraud_call_back_async.delay(
                CallBackType.MOVE_APPLICATION_STATUS,
                application_id,
                str(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS),
            )
        )


@task(queue='fraud')
def remove_application_from_fraud_application_bucket(application_id: int) -> int:
    """
    Remove the application from FraudApplicationBucket. We only set the is_active to False.

    Args:
        application_id (integer): The application primary keys

    Returns:
        integer: The number of removed application.
    """
    return FraudApplicationBucket.objects.filter(
        application_id=application_id,
        is_active=True,
    ).update(is_active=False)


def check_high_risk_asn(application_id: int) -> Union[bool, None]:
    """
    Checks whether an application is detected with high risk ASN.

    Args:
        application_id (int): The id of Application object to be checked.

    Returns:
        Union[bool, None]: True if application is detected to have high risk ASN.
            False if application is not high risk. None if it is not being checked properly.

    """
    logger_data = {
        'action': 'check_high_risk_asn',
    }

    high_risk_asn_feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.HIGH_RISK_ASN_TOWER_CHECK
    )
    if not high_risk_asn_feature_setting.is_active:
        logger.info(
            {
                **logger_data,
                'message': 'Skip check as FeatureSetting for high_risk_asn_tower_check is off.',
            }
        )
        return None

    high_risk_asn_parameters = high_risk_asn_feature_setting.parameters
    try:
        application = Application.objects.get(id=application_id)
        logger_data.update({'application_id': application_id})

        application_risky_check = ApplicationRiskyCheck.objects.get_or_none(
            application_id=application_id
        )
        if not application_risky_check:
            logger.info(
                {
                    **logger_data,
                    'message': 'ApplicationRiskyCheck not found for this application_id.',
                }
            )
            return None

        if not application_risky_check.is_vpn_detected:
            logger.info(
                {
                    **logger_data,
                    'application_risky_check_id': application_risky_check.id,
                    'message': 'Application does not have VPN detected.',
                }
            )
            return False

        mycroft_result = PdApplicationFraudModelResult.objects.filter(
            application_id=application_id
        ).last()
        if not mycroft_result:
            logger.info({**logger_data, 'message': 'Application has no mycroft result found.'})
            return False

        if (
            high_risk_asn_parameters['mycroft_threshold_min']
            <= mycroft_result.pgood
            <= high_risk_asn_parameters['mycroft_threshold_max']
        ):
            logger_data.update(
                {
                    'customer_id': application.customer.id,
                    'pd_application_fraud_model_result_id': mycroft_result.id,
                }
            )

            last_device_ip_history = DeviceIpHistory.objects.filter(
                customer=application.customer
            ).last()
            if not last_device_ip_history:
                logger.info(
                    {
                        **logger_data,
                        'message': 'Customer\'s device has no IP history.',
                    }
                )
                return None

            vpn_detection = VPNDetection.objects.filter(
                ip_address=last_device_ip_history.ip_address
            ).last()
            fraud_high_risk_asn = FraudHighRiskAsn.objects.filter(
                name=vpn_detection.extra_data['org']
            ).exists()
            if fraud_high_risk_asn:
                application_risky_check.update_safely(is_high_risk_asn_mycroft=True)
                logger.info(
                    {
                        **logger_data,
                        'message': 'Application flagged as high risk ASN.',
                    }
                )

            return True

        else:
            logger.info(
                {**logger_data, 'message': 'Application\'s mycroft score not within threshold.'}
            )

        return False
    except Exception:
        sentry_client.captureException()
        logger.info({**logger_data})
        return None


@task(queue='fraud')
def process_mobile_user_action_log_checks(log_data_list):
    for log in log_data_list:
        if log['activity'] == 'ChangePhoneActivity':
            json_log = json.dumps(log, default=str)
            FraudFlag.objects.create(
                customer_id=log['customer_id'],
                fraud_type=FraudFlagType.CHANGE_PHONE_ACTIVITY,
                trigger=FraudFlagTrigger.CHANGE_PHONE_ACTIVITY,
                flag_source_type=FraudFlagSource.CUSTOMER,
                flag_source_id=log['customer_id'],
                extra=json_log,
            )
            return


@task(queue='fraud')
def flag_blacklisted_android_id_for_j1_and_jturbo_task(blacklisted_fraudster_id: int) -> int:
    """
    Move account status to x440 for blacklisted android_id customers

    Args:
        blacklisted_fraudster_id (integer): The blacklisted_fraudster primary keys.

    Returns:
        None
    """
    blacklisted_fraudster = BlacklistedFraudster.objects.get(id=blacklisted_fraudster_id)
    detected_customers = (
        Device.objects.annotate(max_date=Max('customer__device__cdate'))
        .filter(cdate=F('max_date'), android_id=blacklisted_fraudster.android_id)
        .values_list('customer_id')
    )
    accounts = Account.objects.filter(
        customer_id__in=detected_customers, status_id=AccountConstant.STATUS_CODE.active
    ).distinct('id')
    change_reason = 'Android ID is Blacklisted'
    for account in accounts:
        process_change_account_status(
            account, AccountConstant.STATUS_CODE.fraud_reported, change_reason=change_reason
        )


@task(queue='fraud')
def flag_blacklisted_phone_for_j1_and_jturbo_task(blacklisted_fraudster_id: int) -> int:
    """
    Move account status to x440 for blacklisted phone_number customers

    Args:
        blacklisted_fraudster_id (integer): The blacklisted_fraudster primary keys.

    Returns:
        None
    """
    blacklisted_fraudster = BlacklistedFraudster.objects.get(id=blacklisted_fraudster_id)
    accounts = Account.objects.filter(
        Q(customer__phone=blacklisted_fraudster.phone_number)
        | Q(application__mobile_phone_1=blacklisted_fraudster.phone_number),
        status_id=AccountConstant.STATUS_CODE.active,
    ).distinct('id')
    change_reason = 'Phone Number is Blacklisted'
    for account in accounts:
        process_change_account_status(
            account, AccountConstant.STATUS_CODE.fraud_reported, change_reason=change_reason
        )


@task(queue='fraud')
def swift_limit_drainer_account_daily_action() -> None:
    """
    Checks for account in status 440 due to Swift Limit Drainer detection
    and update the account status to 432 or 440
    if they have been blocked for x days
    based on FeatureNameConst.SWIFT_LIMIT_DRAINER feature setting.
    """
    log_data = {
        'action': 'swift_limit_drainer_account_daily_action',
    }
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER
    )
    if not feature_setting or not feature_setting.is_active:
        logger.info(
            {
                'message': 'Stop unblocking due to feature setting inactive or not found.',
                **log_data
            }
        )
        return

    jail_day = feature_setting.parameters['jail_days']
    jail_date = timezone.localtime(timezone.now()).date() - timedelta(days=jail_day)
    unblock_account_list = FraudSwiftLimitDrainerAccount.objects.filter(cdate__date__lte=jail_date)

    log_data.update(
        {
            'total_fraud_swift_limit_drainer_account': unblock_account_list.count(),
            'jail_day': jail_day,
        }
    )
    logger.info({'message': 'Fetched account list to be unblocked.', **log_data})
    for unblock_account in unblock_account_list:
        logger.info({'fraud_swift_limit_drainer_id': unblock_account.id, **log_data})
        if is_account_appeal_temporary_block(unblock_account.account):
            process_change_account_status(
                unblock_account.account,
                AccountConstant.STATUS_CODE.terminated,
                AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
            )
            logger.info(
                {
                    'change_reason': AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
                    'fraud_swift_limit_drainer_id': unblock_account.id,
                    **log_data,
                }
            )
        else:
            process_change_account_status(
                unblock_account.account,
                AccountConstant.STATUS_CODE.active,
                AccountChangeReason.SWIFT_LIMIT_DRAINER_RETURN,
            )
            logger.info(
                {
                    'change_reason': AccountChangeReason.SWIFT_LIMIT_DRAINER_RETURN,
                    'fraud_swift_limit_drainer_id': unblock_account.id,
                    **log_data,
                }
            )
        unblock_account.delete()

    logger.info({'message': 'Swift Limit Drainer unblock or block successful.', **log_data})


@task(queue='fraud')
def telco_maid_temporary_block_daily_action() -> None:
    """
    Checks for account in status 440 due to Telco Maid location detection
    and update the account status to 420
    if they have been blocked for x days
    based on FeatureNameConst.TELCO_MAID_LOCATION_FEATURE feature setting.
    """
    log_data = {
        'action': 'telco_maid_temporary_block_daily_action',
    }
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.TELCO_MAID_LOCATION_FEATURE
    )
    if not feature_setting or not feature_setting.is_active:
        logger.info(
            {
                'message': 'Stop unblocking due to feature setting inactive or not found.',
                **log_data
            }
        )
        return
    jail_day = feature_setting.parameters['jail_days']
    unblock_account_list = get_telco_maid_unblock_account_list(jail_day)
    log_data.update(
        {
            'total_telco_maid_temporary_account': unblock_account_list.count(),
            'jail_day': jail_day,
        }
    )
    logger.info({'message': 'Fetched account list to be unblocked.', **log_data})
    for unblock_account in unblock_account_list:
        process_change_account_status(
            unblock_account.account,
            AccountConstant.STATUS_CODE.active,
            AccountChangeReason.TELCO_MAID_LOCATION_RETURN,
        )
        unblock_account.delete()
    logger.info({'message': 'Telco Maid unblock successful.', **log_data})


@task(queue='fraud')
def fetch_and_store_phone_insights_task(application_id, source=''):
    try:
        monnai_repository = get_monnai_repository()
        monnai_repository.set_mock('phone_social_basic')
        monnai_repository.set_retry_on_error(True)
        application = Application.objects.get(id=application_id)

        if MonnaiPhoneBasicInsight.objects.filter(application=application).exists():
            logger.info(
                "Phone basic insight for application ID {0} already exists".format(application_id)
            )
            return

        logger.info(
            {
                'message': 'fetch_and_store_phone_insights_task',
                'source': source,
                'application_id': application.id,
            }
        )

        success = monnai_repository.fetch_and_store_phone_insights(application, source)
        if success:
            logger.info(
                "Successfully processed Monnai phone insights for application ID {0}".format(
                    application_id
                )
            )
            # Trigger email insights task only after successful completion of phone insights
            fetch_and_store_email_insights_task.delay(application_id)
        else:
            logger.error(
                "Failed to process Monnai phone insights for application ID {0}".format(
                    application_id
                )
            )
    except Application.DoesNotExist:
        logger.error("Application with ID {0} does not exist".format(application_id))
    except Exception as e:
        logger.error(
            "Unexpected error occurred while processing Monnai phone "
            "insights for application ID {0}: "
            "{1}".format(application_id, str(e))
        )
        raise


@task(queue='fraud')
def fetch_and_store_email_insights_task(application_id):
    try:
        monnai_repository = get_monnai_repository()
        monnai_repository.set_mock('email_social_basic')
        monnai_repository.set_retry_on_error(True)
        application = Application.objects.get(id=application_id)

        if MonnaiEmailBasicInsight.objects.filter(application=application).exists():
            logger.info(
                "Email insights for application ID {0} already exists".format(application_id)
            )
            return

        success = monnai_repository.fetch_and_store_email_insights(application)
        if success:
            logger.info(
                "Successfully processed Monnai email insights for application ID {0}".format(
                    application_id
                )
            )
        else:
            logger.error(
                "Failed to process Monnai email insights for application ID {0}".format(
                    application_id
                )
            )
    except Application.DoesNotExist:
        logger.error("Application with ID {0} does not exist".format(application_id))
    except Exception as e:
        logger.error(
            "Unexpected error occurred while processing "
            "Monnai email insights for application ID {0}: "
            "{1}".format(application_id, str(e))
        )
        raise


@task(queue='fraud')
def save_bank_name_velocity_threshold_history() -> None:
    log_data = {
        'action': 'save_bank_name_velocity_threshold_history',
    }
    try:
        logger.info({'message': 'Run save_bank_name_velocity_threshold_history', **log_data})

        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.ABC_BANK_NAME_VELOCITY,
        )
        if not feature_setting:
            logger.info(
                {
                    'message': 'Feature setting not found',
                    **log_data,
                }
            )
            return

        """
            get the current date time, add set the hour time to 12:00:00
            use case run at 23 August 2024 14:00:00
            if the machine run in UTC time
                -> it will change the date to 23 August 2024 12:00:00
                -> and store the data as is
            if the machine run in JKT time
                -> it will change the date to 23 August 2024 12:00:00
                -> and store the date will be 23 August 2024 05:00:00
            need to change the hour time to support get_or_create operations,
            to prevent data duplication
        """
        current_date = datetime.now().date()
        target_time = datetime.strptime("12:00:00", "%H:%M:%S").time()
        target_datetime = datetime.combine(current_date, target_time)
        threshold = feature_setting.parameters['threshold']

        BankNameVelocityThresholdHistory.objects.get_or_create(
            threshold_date=target_datetime, threshold=threshold
        )
        logger.info({'message': 'Done run save_bank_name_velocity_threshold_history', **log_data})

    except Exception as error:
        logger.error(
            {
                'message': 'Failed run save_bank_name_velocity_threshold_history',
                'error_message': str(error),
                **log_data,
            }
        )
        sentry_client.captureException()


@task(queue='fraud')
def fraud_block_account_daily_action() -> None:
    """
    Checks for account in Fraud Block Account
    and update the account according to the block status
    if they have been blocked for x days
    based on FeatureNameConst.FRAUD_BLOCK_ACCOUNT_FEATURE feature setting.
    """
    log_data = {
        'action': 'fraud_block_account_daily_action',
    }
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FRAUD_BLOCK_ACCOUNT_FEATURE
    )

    # remove the active status check
    if not feature_setting:
        logger.info(
            {
                'message': 'Stop running fraud_block_account_daily_action due '
                'to feature setting inactive or not found.',
                **log_data,
            }
        )
        return
    jail_day_j1 = feature_setting.parameters['jail_days_j1']
    jail_day_jturbo = feature_setting.parameters['jail_days_jturbo']
    fraud_block_accounts_list = get_fraud_block_account_list(jail_day_j1, jail_day_jturbo)
    log_data.update(
        {
            'total_fraud_block_account': len(fraud_block_accounts_list),
            'jail_day_j1': jail_day_j1,
            'jail_day_jturbo': jail_day_jturbo,
        }
    )
    logger.info({'message': 'Get a list of accounts to be processed.', **log_data})
    for fraud_block_account_data in fraud_block_accounts_list:
        if fraud_block_account_data[FraudBlockAccountConst.FRAUD_BLOCK_ACCOUNT].is_need_action:
            fraud_block_account_action(
                fraud_block_account_data[FraudBlockAccountConst.FRAUD_BLOCK_ACCOUNT],
                fraud_block_account_data[FraudBlockAccountConst.APPLICATION],
            )
    logger.info({'message': 'Fraud Block Account process successful.', **log_data})


def get_telco_maid_unblock_account_list(jail_day: int) -> List[FraudTelcoMaidTemporaryBlock]:
    jail_date = timezone.localtime(timezone.now()).date() - timedelta(days=jail_day)
    return FraudTelcoMaidTemporaryBlock.objects.filter(cdate__date__lte=jail_date)

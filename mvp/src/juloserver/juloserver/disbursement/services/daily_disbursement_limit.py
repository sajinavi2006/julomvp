import csv
import logging
import urllib
from io import StringIO
from typing import Generator, Dict, List

from django.utils import timezone
from django.db.utils import IntegrityError
from django.db import transaction

from juloserver.julo.models import (
    Loan,
    FeatureSetting,
)
from juloserver.account.models import Account
from juloserver.julo.constants import FeatureNameConst
from juloserver.disbursement.models import (
    DailyDisbursementLimit,
    DailyDisbursementScoreLimit,
    DailyDisbursementLimitWhitelist,
    DailyDisbursementLimitWhitelistHistory,
)
from juloserver.disbursement.constants import DailyDisbursementLimitWhitelistConst

from juloserver.account.services.account_related import get_account_property_by_account

from juloserver.apiv2.models import PdBscoreModelResult

logger = logging.getLogger(__name__)


class log():
    def error(msg: str, method):
        logger.error({
            "action": (
                "juloserver.disbursement.services"
                ".daily_disbursement_limit.{}".format(method)
            ),
            "error": msg,
        })

    def info(msg: str, method):
        logger.info({
            'action': 'juloserver.disbursement.services'
                      '.daily_disbursement_limit.{}'.format(method),
            'msg': msg
        })


def is_daily_disbursement_limit_feature_active():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DAILY_DISBURSEMENT_LIMIT, is_active=True,
    ).last()


def reconstruct_product(products, transaction_methods):
    for product in products:
        if product["code"] in transaction_methods and not product["is_locked"]:
            product["is_locked"] = True
            existing_foreground = product["foreground_icon"].split("/")
            filename = existing_foreground[-1].split(".")
            filename[-2] += "_locked"
            existing_foreground[-1] = ".".join(filename)
            product["foreground_icon"] = "/".join(existing_foreground)
            product.pop("background_icon")
    return products


def validate_account_for_daily_disbursement_limit(account):
    daily_disbursement_limit_setting = is_daily_disbursement_limit_feature_active()
    if not daily_disbursement_limit_setting:
        return False, None

    daily_disbursement_limit = DailyDisbursementLimit.objects.filter(
        limit_date=timezone.localtime(timezone.now())
    ).last()
    total_amount = daily_disbursement_limit.total_amount if daily_disbursement_limit else 0
    daily_disbursement_limit_amount = daily_disbursement_limit_setting.parameters["amount"]

    if not account:
        return False, None

    account_property = get_account_property_by_account(account)
    if not account_property:
        return False, None

    parameters = daily_disbursement_limit_setting.parameters

    if total_amount >= daily_disbursement_limit_amount:
        return False, None

    bscore_config = parameters.get("bscore", 0)
    bscore_model_result = (
        PdBscoreModelResult.objects.filter(customer_id=account.customer_id, pgood__isnull=False)
        .order_by("cdate")
        .last()
    )

    if bscore_model_result and bscore_model_result.pgood >= bscore_config:
        return True, daily_disbursement_limit_setting.parameters

    pgood_config = parameters.get("pgood", 0)
    if account_property.pgood >= pgood_config:
        return True, daily_disbursement_limit_setting.parameters

    return False, None


def check_daily_disbursement_limit(account, data):
    is_valid, parameters = validate_account_for_daily_disbursement_limit(account)
    if not is_valid:
        return data

    if 'creditInfo' in data:
        data["creditInfo"].update(
            {
                "limit_message": parameters["message"],
                "set_limit": None,
                "available_limit": None,
                "used_limit": None,
            }
        )

    transaction_methods = parameters["transaction_method"]
    if "product" in data:
        data["product"] = reconstruct_product(data["product"], transaction_methods)

    if "all_products" in data:
        for product_category in data["all_products"]:
            product_category["product"] = reconstruct_product(
                product_category["product"], transaction_methods
            )

    return data


def check_product_lock_by_limit_disbursement(account, transaction_method):
    is_valid, parameters = validate_account_for_daily_disbursement_limit(account)
    if not is_valid:
        return is_valid

    return transaction_method in parameters["transaction_method"]


def store_daily_disbursement_limit_amount(loan):
    try:
        daily_disbursement_limit, _ = DailyDisbursementLimit.objects.get_or_create(
            limit_date=timezone.localtime(timezone.now())
        )
        daily_disbursement_limit.total_amount += loan.loan_amount
        daily_disbursement_limit.save()
    except IntegrityError as e:
        logger.error({
            "method": (
                "juloserver.disbursement.services"
                ".daily_disbursement_limit.store_daily_disbursement_limit_amount"
            ),
            "error": str(e),
            "loan": loan
        })


def store_daily_disbursement_score_limit_amount(loan: Loan):
    try:
        # Check is bscore/non-repeat bscore/pgood
        if is_bscore(loan.customer_id):
            score_type = 'bscore'
        elif is_repeat_customer(loan.customer.account):
            score_type = 'non_repeat_bscore'
        else:
            score_type = 'pgood'
        log.info(
            'store_daily_disbursement_score_limit_amount',
            'check is {} is exist'.format(score_type))
        daily_disbursement_limit, _ = DailyDisbursementScoreLimit.objects.get_or_create(
            limit_date=timezone.localtime(timezone.now()),
            score_type=score_type
        )

        daily_disbursement_limit.total_amount += loan.loan_amount
        daily_disbursement_limit.save()
    except IntegrityError as e:
        log.error(
            str(e),
            'store_daily_disbursement_score_limit_amount',
        )


def check_daily_disbursement_limit_by_transaction_method(account, transaction_method_id):
    """
    Check if the daily disbursement limit is affected by a specific transaction method.

    :param account: The account to check against.
    :param transaction_method_id: The ID of the transaction method.
    :return: Tuple (bool, message, bool)
    indicating if the limit is reached and a message if applicable and flag if eligible for bypass.
    """
    is_eligible_for_threshold_bypass = False

    # Get the active feature setting for daily disbursement limit
    daily_disbursement_limit_setting = is_daily_disbursement_limit_feature_active()
    if not daily_disbursement_limit_setting:
        return False, None, is_eligible_for_threshold_bypass

    # Check if account is provided
    if not account:
        return False, None, is_eligible_for_threshold_bypass

    # Get account properties
    account_property = get_account_property_by_account(account)
    if not account_property:
        return False, None, is_eligible_for_threshold_bypass

    parameters = daily_disbursement_limit_setting.parameters

    # Check if the transaction method is part of the allowed list
    if transaction_method_id not in parameters["transaction_method"]:
        return False, None, is_eligible_for_threshold_bypass

    bscore_model_result = is_bscore(account.customer_id)
    is_whitelisted_customer = check_customer_disbursement_whitelist(account.customer_id)
    if bscore_model_result:
        bscore_config = parameters.get("bscore", 0)
        amount_limit = parameters["bscore_amount"]

        if check_daily_limit('bscore', amount_limit):
            if is_whitelisted_customer:
                return False, None, is_eligible_for_threshold_bypass

            if bscore_model_result.pgood >= bscore_config:
                return False, None, is_eligible_for_threshold_bypass
            else:
                # check if eligible for bypass
                is_eligible_for_threshold_bypass = True
                log.error('bscore customer_id {} bscore : {} '
                          'less than bscore_config {}'.format(account.customer_id,
                                                              bscore_model_result.pgood,
                                                              bscore_config),
                          'check_daily_disbursement_limit_by_transaction_method')
    else:
        # Check P-good configuration for FTC and Non-repeat Bscore
        pgood_config = parameters.get("pgood", 0)

        # non_repeat_bscore means repeat customer without bscore, wrong naming
        if is_repeat_customer(account):
            score_type = "non_repeat_bscore"
            amount_limit = parameters["non_repeat_bscore_amount"]
        else:
            score_type = "pgood"
            amount_limit = parameters["pgood_amount"]
        if check_daily_limit(score_type, amount_limit):
            if is_whitelisted_customer:
                return False, None, is_eligible_for_threshold_bypass

            if account_property.pgood >= pgood_config:
                return False, None, is_eligible_for_threshold_bypass
            else:
                log.error('pgood customer_id {} pgood : {} '
                          'less than pgood_config {}'.format(account.customer_id,
                                                             account_property.pgood,
                                                             pgood_config),
                          'check_daily_disbursement_limit_by_transaction_method')

    # Return true if none of the conditions block the transaction
    return True, parameters["message"], is_eligible_for_threshold_bypass


def is_bscore(customer_id: int):
    return (
        PdBscoreModelResult.objects.filter(customer_id=customer_id, pgood__isnull=False)
        .order_by("cdate")
        .last()
    )


def is_repeat_customer(account: Account) -> bool:
    return account.accountpayment_set.paid_or_partially_paid().exists()


def check_customer_disbursement_whitelist(customer_id: int) -> bool:
    daily_disbursment_whitelist_fs = (
        FeatureSetting.objects
        .filter(
            feature_name=FeatureNameConst.DAILY_DISBURSEMENT_LIMIT_WHITELIST,
            is_active=True
        )
        .last()
    )
    if not daily_disbursment_whitelist_fs:
        return False

    return (
        DailyDisbursementLimitWhitelist.objects
        .filter(customer_id=customer_id)
        .exists()
    )


def check_daily_limit(score_type: str, limit_amount) -> bool:
    daily_disbursement_limit = DailyDisbursementScoreLimit.objects.filter(
        limit_date=timezone.localtime(timezone.now()),
        score_type=score_type
    ).last()
    total_amount = daily_disbursement_limit.total_amount if daily_disbursement_limit else 0
    if total_amount >= limit_amount:
        log.error("already exceeded, "
                  "max disburse for {} is {} ".format(score_type, limit_amount),
                  'check_daily_limit')
        return False
    return True


def load_data_from_presigned_url_oss(url: str) -> Generator[Dict[str, str], None, None]:
    with urllib.request.urlopen(url) as response:
        content = response.read().decode('utf-8')

    csv_file = StringIO(content)
    csv_reader = csv.DictReader(csv_file)

    sub_data = []
    for ele in list(csv_reader):
        sub_data.append(ele)
        if len(sub_data) == DailyDisbursementLimitWhitelistConst.QUERY_SIZE:
            yield sub_data
            sub_data = []

    if sub_data:
        yield sub_data


def load_whitelist_data() -> Generator[Dict[str, str], None, None]:
    whitelist_data = (
        DailyDisbursementLimitWhitelist.objects
        .values('cdate', 'customer_id', 'source', 'user_id')
    )

    sub_data = []
    for ele in list(whitelist_data):
        sub_data.append(ele)
        if len(sub_data) == DailyDisbursementLimitWhitelistConst.QUERY_SIZE:
            yield sub_data
            sub_data = []

    if sub_data:
        yield sub_data


def process_daily_disbursement_limit_whitelist(url: str, user_id: int):
    with transaction.atomic():
        record_old_whitelist_data()
        insert_new_whitelist_data(url, user_id)


def record_old_whitelist_data():
    for sub_whitelist_data in load_whitelist_data():
        insert_daily_disbursement_limit_whitelist_history(sub_whitelist_data)
    DailyDisbursementLimitWhitelist.objects.all().delete()


def insert_new_whitelist_data(url, user_id):
    for sub_data in load_data_from_presigned_url_oss(url):
        insert_daily_disbursement_limit_whitelist(sub_data, user_id)


def insert_daily_disbursement_limit_whitelist_history(whitelist_data: List[Dict[str, str]]):
    history_data = []
    for data in whitelist_data:
        data['start_date'] = data.pop('cdate').date()
        history_data.append(
            DailyDisbursementLimitWhitelistHistory(**data)
        )
    DailyDisbursementLimitWhitelistHistory.objects.bulk_create(history_data)


def insert_daily_disbursement_limit_whitelist(data: List[Dict[str, str]], user_id: int):
    whitelist_data = []
    for row in data:
        insert_data = {
            "customer_id": row["customer_id"],
            "source": row["source"],
            "user_id": user_id
        }
        whitelist_data.append(DailyDisbursementLimitWhitelist(**insert_data))

    DailyDisbursementLimitWhitelist.objects.bulk_create(whitelist_data)

import random
import re
import json

from babel.numbers import format_number
from datetime import timedelta, datetime
from django.utils import timezone
from django.core.exceptions import MultipleObjectsReturned
from django.db.models import Count, Sum, F
from hashids import Hashids

from django.db import transaction
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.account.constants import AccountConstant
from juloserver.customer_module.services.customer_related import (
    get_or_create_cashback_balance,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import (
    JuloException,
)
from juloserver.julo.models import (
    Customer,
    CustomerWalletHistory,
    RefereeMapping,
    ReferralSystem,
    logger,
    FeatureSetting,
    Application,
    ApplicationHistory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
)
from juloserver.julo.utils import display_rupiah
from juloserver.julocore.python2.utils import py2round
from juloserver.referral.constants import (
    LATEST_REFERRAL_MAPPING_ID,
    FeatureNameConst,
    ReferralBenefitConst,
    ReferralPersonTypeConst,
    MAPPING_COUNT_START_DATE,
    ReferralLevelConst,
    MIN_REFEREE_GET_BONUS,
    REFERRAL_DEFAULT_LEVEL,
    ReferralRedisConstant,
    REFERRAL_BENEFIT_EXPIRY_DAYS,
)
from juloserver.cashback.constants import CashbackChangeReason
from juloserver.referral.models import ReferralBenefit, ReferralLevel, ReferralBenefitHistory
from juloserver.loyalty.services.services import (
    update_customer_total_points,
    get_and_lock_loyalty_point,
)
CUSTOMER_BASE_ID = 1000000000
SALT = "Julo Referral Code"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"
NUMBER = "23456789"


def generate_referral_code(customer):
    hashids = Hashids(salt=SALT, alphabet=(ALPHABET + NUMBER), min_length=4)
    unique_id = customer.id - CUSTOMER_BASE_ID
    postfix = hashids.encode(unique_id)
    referral_code = build_referral_code(customer.fullname, postfix)
    return referral_code


def build_referral_code(customer_name, postfix):
    customer_name = '' if customer_name is None else customer_name.replace(" ", "")
    customer_name = re.sub("[IL1O0]", "", customer_name.upper())
    customer_name = ''.join(e for e in customer_name if e.isalnum())
    if len(customer_name) < 4:
        customer_name += ''.join((random.choice(ALPHABET)) for x in range(4 - len(customer_name)))
    elif len(customer_name) > 4:
        customer_name = customer_name[:4]
    return (customer_name + postfix).upper()


def get_total_referral_invited_and_total_referral_benefits(customer):
    wallet_hist_agg = CustomerWalletHistory.objects.filter(
        customer=customer, change_reason=CashbackChangeReason.PROMO_REFERRAL
    ).annotate(
        amount=F('wallet_balance_accruing') - F('wallet_balance_accruing_old')
    ).aggregate(
        total_amount=Sum('amount'), num_hist=Count('amount')
    )

    return wallet_hist_agg['num_hist'] or 0, wallet_hist_agg['total_amount'] or 0


def get_total_referral_invited_and_total_referral_benefits_v2(customer):
    benefit_histories = ReferralBenefitHistory.objects.filter(
        customer=customer,
        referral_person_type=ReferralPersonTypeConst.REFERRER,
        benefit_unit=ReferralBenefitConst.CASHBACK,
    ).aggregate(
        total_amount=Sum('amount'), count_referee=Count('amount')
    )

    return benefit_histories['count_referee'] or 0, benefit_histories['total_amount'] or 0


def check_referral_cashback_v2(referee, referrer, activate_referee_benefit, loan_amount,
                               referral_fs):
    """Check referral code
    - Check if referrer has application or not
    - Apply referral benefit and referral level benefit to users
    """
    referral_benefit = get_referral_benefit(loan_amount)
    if not referral_benefit:
        return

    referrer_application = referrer.application_set.regular_not_deletes().exists()
    referee_mapping = RefereeMapping.objects.create(referrer=referrer, referee=referee)
    benefit_histories = []

    # not apply deleted referrer
    if referrer_application:
        referral_level = get_referrer_level_benefit(referrer, referral_fs, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        benefit_histories = apply_referral_benefits(
            referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, referee_mapping
        )
    if activate_referee_benefit:
        referee_benefits = get_referee_benefits(referral_benefit)
        benefit_histories.extend(
            apply_referral_benefits(
                referee, referee_benefits, ReferralPersonTypeConst.REFEREE, referee_mapping
            )
        )

    ReferralBenefitHistory.objects.bulk_create(benefit_histories)


def is_valid_referral_date(referral_system, referral_fs, application):
    referral_benefit_expiry_days = referral_system.extra_params.get(
        'referral_benefit_expiry_days', REFERRAL_BENEFIT_EXPIRY_DAYS
    )
    today = timezone.localtime(timezone.now()).date()
    date_expiry = today - timedelta(days=referral_benefit_expiry_days)

    count_start_date = timezone.localtime(datetime.strptime(
        referral_fs.parameters.get('count_start_date', MAPPING_COUNT_START_DATE),
        "%Y-%m-%d")
    ).date()
    max_valid_date = max(
        date_expiry,
        count_start_date
    )
    is_valid = ApplicationHistory.objects.filter(
        application=application,
        status_new=ApplicationStatusCodes.LOC_APPROVED,
        cdate__date__gte=max_valid_date
    ).exists()
    return is_valid


def process_referral_code_v2(application, loan, referral_fs):
    referral_system = ReferralSystem.objects.filter(name='PromoReferral', is_active=True).last()
    if not referral_system:
        return

    # check referral system is on, application has referral code and product line in product code
    condition_check = [
        not application.referral_code,
        application.product_line_id not in referral_system.product_code,
        not is_valid_referral_date(referral_system, referral_fs, application)
    ]
    if any(condition_check):
        return

    # check if referrer is active or not
    referrer = Customer.objects.filter(
        self_referral_code=application.referral_code.upper(),
        account__status_id=AccountConstant.STATUS_CODE.active
    ).last()
    if not referrer:
        return

    referee = application.customer
    # check referee mapping
    if RefereeMapping.objects.filter(referrer=referrer, referee=referee).exists():
        return

    # check referral bonus limit
    if referral_system.referral_bonus_limit and check_referral_code_is_limit(
        referral_system, referrer
    ):
        return

    try:
        get_or_create_cashback_balance(referee)
        get_or_create_cashback_balance(referrer)
        check_referral_cashback_v2(
            referee,
            referrer,
            referral_system.activate_referee_benefit,
            loan.loan_amount,
            referral_fs
        )
    except MultipleObjectsReturned:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()


def check_referral_code_is_limit(referral_system, referrer):
    referral_mapping_id = referral_system.extra_params.get(LATEST_REFERRAL_MAPPING_ID)
    referee_count = RefereeMapping.objects.filter(
        referrer=referrer, pk__gt=int(referral_mapping_id)
    ).count()

    return referee_count >= referral_system.referral_bonus_limit


def generate_customer_level_referral_code(application):
    from juloserver.moengage.constants import MoengageEventType
    from juloserver.moengage.services.use_cases import update_moengage_referral_event

    if not is_eligible_for_referral(application):
        return

    customer = application.customer
    referral_code = generate_referral_code(customer)
    customer.update_safely(self_referral_code=referral_code)

    if application.is_julo_one_or_starter():
        event = MoengageEventType.BEx190_NOT_YET_REFER
    else:
        event = MoengageEventType.BEx190_NOT_YET_REFER_JULOVER
    update_moengage_referral_event.delay(customer, event)


def show_referral_code(customer):
    account = customer.account
    if not account:
        return False

    if not account.get_active_application():
        return False

    return (
        customer.self_referral_code
        and ReferralSystem.objects.filter(name='PromoReferral', is_active=True).exists()
    )


def is_eligible_for_referral(application):
    if not application:
        raise JuloException('Application not found')

    customer = application.customer
    if customer.self_referral_code:
        logger.info(
            {'self_referral_code': customer.self_referral_code, 'status': 'already_generated'}
        )
        return False

    referral_system = ReferralSystem.objects.filter(name='PromoReferral', is_active=True).last()
    if not referral_system:
        return False

    partner_name = 'julo'
    if application.partner:
        partner_name = application.partner.name

    invalid_product_line_code = application.product_line_id not in referral_system.product_code
    invalid_partner_name = partner_name not in referral_system.partners
    if invalid_product_line_code or invalid_partner_name:
        logger.info({'self_referral_code': customer.self_referral_code, 'action': 'generating'})
        return False

    return True


def get_shareable_referral_image():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SHAREABLE_REFERRAL_IMAGE, is_active=True
    ).last()
    if not feature_setting:
        return None, None

    parameters = feature_setting.parameters or {}
    return parameters.get('text'), parameters.get('image')


def get_referral_benefit(referee_loan_amount):
    # get main referral benefit
    return (
        ReferralBenefit.objects.filter(min_disburse_amount__lte=referee_loan_amount, is_active=True)
        .order_by('min_disburse_amount')
        .last()
    )


def get_referrer_level_benefit(referrer, referral_fs, referral_benefit):
    # Get available level benefit, prevent to get cashback and points in 1 loan
    available_level_benefit = ReferralLevelConst.AVAILABLE_LEVEL_BENEFIT_MAPPING.get(
        referral_benefit.benefit_type
    )
    if not available_level_benefit:
        raise JuloException(
            "No available level benefit for benefit type: {}".format(
                referral_benefit.benefit_type
            )
        )
    # get extra referral level benefit
    count_refers = RefereeMapping.objects.filter(
        referrer=referrer,
        cdate__date__gte=referral_fs.parameters.get('count_start_date', MAPPING_COUNT_START_DATE)
    ).count()
    return (
        ReferralLevel.objects.filter(
            min_referees__lte=count_refers,
            benefit_type__in=available_level_benefit,
            is_active=True
        )
        .order_by('min_referees')
        .last()
    )


def get_referrer_benefits(referral_benefit, referral_level):
    benefit_type = referral_benefit.benefit_type

    # main benefit
    benefits = {benefit_type: referral_benefit.referrer_benefit}

    # extra level benefit
    if referral_level:
        level_type = referral_level.benefit_type
        level_benefit = referral_level.referrer_level_benefit
        if level_type == ReferralLevelConst.PERCENTAGE:
            benefits[benefit_type] += py2round((level_benefit / 100) * benefits[benefit_type])
        else:
            benefits[level_type] = level_benefit + benefits.get(level_type, 0)

    return benefits


def get_referee_benefits(referral_benefit):
    return {referral_benefit.benefit_type: referral_benefit.referee_benefit}


def apply_referral_benefits(customer, benefits, referral_person_type, referee_mapping):
    """
    benefits: {'cashback': 20000, 'points':100}
    referral_person_type: referrer/referee
    """
    from juloserver.moengage.services.use_cases import (
        update_moengage_referral_event,
        trigger_moengage_after_freeze_unfreeze_cashback
    )
    from juloserver.moengage.constants import MoengageEventType

    moengage_referral_data = {
        'customer_id': customer.id,
        'referral_type': referral_person_type
    }

    if referral_person_type == ReferralPersonTypeConst.REFERRER:
        change_reason = CashbackChangeReason.PROMO_REFERRAL
        moengage_event = MoengageEventType.BEx220_GET_REFERRER
    else:
        change_reason = CashbackChangeReason.PROMO_REFERRAL_FRIEND
        moengage_event = MoengageEventType.BEX220_GET_REFEREE

    benefit_histories = []

    for benefit_type, amount, in benefits.items():
        if benefit_type == ReferralBenefitConst.CASHBACK:
            customer.change_wallet_balance(amount, amount, change_reason)
            moengage_referral_data['cashback_earned'] = amount
            update_moengage_referral_event.delay(customer, moengage_event, amount)
            trigger_moengage_after_freeze_unfreeze_cashback.delay(
                [moengage_referral_data], is_freeze=True
            )
        elif benefit_type == ReferralBenefitConst.POINTS:
            with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
                loyalty_point = get_and_lock_loyalty_point(customer_id=customer.pk)
                update_customer_total_points(
                    customer_id=customer.pk,
                    customer_point=loyalty_point,
                    point_amount=amount,
                    reason=change_reason,
                    adding=True
                )
            moengage_referral_data['point_earning'] = amount
            update_moengage_referral_event.delay(customer, moengage_event, amount)

        benefit_histories.append(
            ReferralBenefitHistory(
                referee_mapping=referee_mapping, customer=customer,
                referral_person_type=referral_person_type, benefit_unit=benefit_type,
                amount=amount
            )
        )

    return benefit_histories


def get_referral_benefit_logic_fs():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REFERRAL_BENEFIT_LOGIC, is_active=True
    ).last()


def get_count_start_date():
    referral_fs = get_referral_benefit_logic_fs()
    return referral_fs.parameters.get('count_start_date', MAPPING_COUNT_START_DATE)


def get_referees_code_used(referrer):
    return Application.objects.filter(
        product_line_id__in=ProductLineCodes.julo_product(),
        referral_code__iexact=referrer.self_referral_code.upper(),
        cdate__date__gte=get_count_start_date(),
    ).distinct('customer').values_list('customer_id', flat=True)


def get_referees_approved_count(customer_ids):
    return Application.objects.filter(
        application_status_id__gte=ApplicationStatusCodes.LOC_APPROVED,
        customer_id__in=customer_ids,
        cdate__date__gte=get_count_start_date(),
    ).distinct('customer').count()


def get_referee_information_by_referrer(referrer, force_query=False):
    """
    get count of referees code used (referee application status < 190)
    get count of referees already approved (referee application status >= 190)
    exclude referees already got benefit from referee_mapping
    :params: referrer -> Customer
    :params: force_query:
        + True - call from api
        + False - call from signals
    :return: The result of the count of referees code used
    :rtype: tuple(int, int)
    """
    redis_client = get_redis_client()
    referrer_id = referrer.id
    code_used_count_key = ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(referrer_id)
    approved_count_key = ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(referrer_id)
    counting_referees_disbursement_key = \
        ReferralRedisConstant.COUNTING_REFEREES_DISBURSEMENT_KEY.format(referrer_id)
    total_referees_bonus_amount_key = \
        ReferralRedisConstant.TOTAL_REFERRAL_BONUS_AMOUNT_KEY.format(referrer_id)
    if not force_query:
        code_used_count = redis_client.get(code_used_count_key)
        approved_count = redis_client.get(approved_count_key)
        disbursement_count = redis_client.get(counting_referees_disbursement_key)
        total_bonus_amount = redis_client.get(total_referees_bonus_amount_key)
        if code_used_count is not None and approved_count is not None \
           and disbursement_count is not None and total_bonus_amount is not None:
            return code_used_count, approved_count, disbursement_count, total_bonus_amount

    referees_code_used = get_referees_code_used(referrer)
    disbursement_count, total_bonus_amount = (
        get_total_referral_invited_and_total_referral_benefits_v2(referrer))

    approved_count = get_referees_approved_count(referees_code_used)

    code_used_count = len(referees_code_used)
    redis_client.set(
        code_used_count_key, code_used_count, ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
    redis_client.set(
        approved_count_key, approved_count, ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )

    redis_client.set(
        counting_referees_disbursement_key, disbursement_count,
        ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
    redis_client.set(
        total_referees_bonus_amount_key, total_bonus_amount,
        ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )
    return code_used_count, approved_count, disbursement_count, total_bonus_amount


def display_bonus_benefit(value, benefit_type):
    if benefit_type == ReferralBenefitConst.CASHBACK:
        return display_rupiah(value)
    else:  # POINT
        return format_number(value, locale='id_ID') + " Point"


def display_bonus_level(referral_level):
    if referral_level.benefit_type == ReferralLevelConst.PERCENTAGE:
        return str(referral_level.referrer_level_benefit) + "%"
    elif referral_level.benefit_type == ReferralLevelConst.CASHBACK:
        return display_rupiah(referral_level.referrer_level_benefit)
    else:  # POINT
        return format_number(referral_level.referrer_level_benefit, locale='id_ID') + " Point"


def get_referral_benefits_by_level():
    feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.REFERRAL_LEVEL_BENEFIT_CONFIG
    )
    parameters = feature_setting.parameters
    referral_benefits = ReferralBenefit.objects.filter(is_active=True)
    referral_level_dict = get_referral_level_by_level_name()
    result = []
    for parameter in parameters:
        if parameter.get("level") == REFERRAL_DEFAULT_LEVEL:
            # build Basic level without referral_level
            result.append(build_response_referral_benefit_by_level(parameter, referral_benefits))
            continue

        referral_level = referral_level_dict.get(parameter["level"])
        if not referral_level:
            # does not have config => return
            continue

        result.append(
            build_response_referral_benefit_by_level(parameter, referral_benefits, referral_level)
        )
    return result


def build_response_referral_benefit_by_level(parameter, referral_benefits, referral_level=None):
    referee_required = parameter["referee_required"]
    has_bonus = parameter["has_bonus"]
    min_transaction = parameter["min_transaction"]
    referee_benefit = parameter["referee_benefit"]
    if referral_level:
        referee = referral_level.min_referees
    else:
        referee = MIN_REFEREE_GET_BONUS
    response = {
        "level": parameter["level"],
        "color": parameter["color"],
        "icon": parameter["icon"],
        "benefit": [
            {
                "name": referee_required["label"],
                "value": referee_required["value"].format(referee=referee),
            },
            {
                "name": has_bonus["label"],
                "value": has_bonus["value"],
            },
        ],
    }
    for referral_benefit in referral_benefits:
        benefit_amount = display_bonus_benefit(
            referral_benefit.referrer_benefit, referral_benefit.benefit_type
        )
        if referral_level:
            benefit_amount = benefit_amount + " +" + display_bonus_level(referral_level)

        response["benefit"].extend([
            {
                "name": min_transaction["label"].format(
                    min_amount_thres=display_rupiah(referral_benefit.min_disburse_amount)
                ),
                "value": min_transaction["value"].format(benefit_amount=benefit_amount),
            },
            {
                "name": referee_benefit["label"].format(
                    min_amount_thres=display_rupiah(referral_benefit.min_disburse_amount)
                ),
                "value": referee_benefit["value"].format(
                    referee_cashback=display_rupiah(referral_benefit.referee_benefit)
                ),
            }],
        )
    return response


def get_referral_level_by_level_name():
    referral_levels = ReferralLevel.objects.filter(is_active=True)
    return {
        referral_level.level: referral_level for referral_level in referral_levels
    }


def update_referrer_counting(referee_app):
    referrer_cust = None
    if referee_app.referral_code:
        referrer_cust = Customer.objects.filter(
            self_referral_code=referee_app.referral_code.upper(),
            account__status_id=AccountConstant.STATUS_CODE.active
        ).last()

    if referrer_cust:
        # trigger update redis
        get_referee_information_by_referrer(referrer=referrer_cust, force_query=True)


def get_current_referral_level(referrer):
    _, _, count_referees, _ = get_referee_information_by_referrer(referrer=referrer)
    referral_level = ReferralLevel.objects.filter(
        is_active=True, min_referees__lte=count_referees
    ).order_by('min_referees').last()
    if referral_level:
        return referral_level.level
    return REFERRAL_DEFAULT_LEVEL


def get_template_data_for_referral():
    template = {
        'header': '',
        'image': '',
        'benefits': [],
        'referral_code': '',
        'referral_level': '',
        'message': '',
        'terms': '',
        'referee_registered': 0,
        'referee_approved': 0,
        'referee_disbursed': 0,
        'total_cashback': 0,
        'shareable_referral_image': {}
    }

    return template


def get_data_from_referral_system(customer):
    from juloserver.cfs.services.core_services import get_cfs_referral_bonus_by_application

    application = customer.account.get_active_application()
    cfs_referral_bonus = get_cfs_referral_bonus_by_application(application)
    referral_system = ReferralSystem.objects.get(name='PromoReferral')
    referral_bonus = (
        cfs_referral_bonus if cfs_referral_bonus else referral_system.caskback_amount
    )

    content = referral_system.extra_data['content']
    cashback_currency = display_rupiah(referral_bonus)
    cashback_referee_currency = display_rupiah(referral_system.referee_cashback_amount)

    return {
        "header": content['header'],
        "image": referral_system.banner_static_url,
        'referral_code': customer.self_referral_code or '',
        'terms': content['terms'].format(cashback_currency),
        'message': content['message'].format(
            cashback_referee_currency, customer.self_referral_code
        ),
        'referral_benefit_image': referral_system.extra_data.get('referral_benefit_image', ''),
    }


def get_additional_info():
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.ADDITIONAL_INFO,
        is_active=True,
        category='referral'
    )

    return fs.parameters['info_content'] if fs and fs.parameters else None


def get_referral_data(referrer_cust):
    data = get_template_data_for_referral()

    text, image = get_shareable_referral_image()
    if text and image:
        data['shareable_referral_image'] = {
            'text_x_coordinate': text['coordinates']['x'],
            'text_y_coordinate': text['coordinates']['y'],
            'text_size': text['size'],
            'image_url': image,
        }

    data.update(get_data_from_referral_system(referrer_cust))

    code_used_count, approved_count, disbursement_count, total_bonus_amount = \
        get_referee_information_by_referrer(referrer_cust)
    data['referee_registered'] = code_used_count
    data['referee_approved'] = approved_count
    data['referee_disbursed'] = disbursement_count
    data['total_cashback'] = total_bonus_amount

    # referrer level
    data['benefits'] = get_referral_benefits_by_level()
    data['referral_level'] = get_current_referral_level(referrer_cust)

    # additional info
    data['additional_info'] = get_additional_info()

    return data


def mask_customer_name(fullname: str) -> str:
    """Masks customer name keeping only first character visible."""
    if not fullname:
        return ""
    return "{}{}".format(fullname[0], '*' * (len(fullname) - 1))


def get_top_referral_cashbacks() -> list:
    """
    Gets top referral cashbacks from Redis. If no cached data is available,
    returns an empty list to the frontend.

    Returns:
        list: A list of top referral cashbacks if available, otherwise an empty list.
    """
    redis_client = get_redis_client()
    cache_key = ReferralRedisConstant.TOP_REFERRAL_CASHBACKS
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)
    return []


def refresh_top_referral_cashbacks() -> list:
    """
    Fetches fresh data from DB, updates Redis cache, and returns the top referral cashbacks.

    Returns:
        list: A list of dictionaries containing masked customer names and their cashback amounts.
    """
    redis_client = get_redis_client()
    top_referral_cashbacks_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.TOP_REFERRAL_CASHBACKS, is_active=True
    )
    if not top_referral_cashbacks_fs:
        return []

    top_referral_cashback_limit = top_referral_cashbacks_fs.parameters.get(
        'top_referral_cashbacks_limit')
    message_format = top_referral_cashbacks_fs.parameters.get('message')
    one_month_ago = timezone.localtime(timezone.now() - timedelta(days=30))

    top_cashbacks = (
        ReferralBenefitHistory.objects
        .filter(cdate__gte=one_month_ago)  # Filter records from the last 1 month
        .values("customer__fullname")  # Group by customer and include fullname
        .annotate(total_amount=Sum("amount"))  # Sum cashback amounts per customer
        .order_by("-total_amount")[:top_referral_cashback_limit]  # Get top N
    )

    result = [
        message_format.format(
            customer_name=mask_customer_name(entry["customer__fullname"]),
            amount=display_rupiah(entry["total_amount"])
        )
        for entry in top_cashbacks
    ]

    # Cache the result
    redis_client.set(
        ReferralRedisConstant.TOP_REFERRAL_CASHBACKS,
        json.dumps(result),
        ReferralRedisConstant.REDIS_CACHE_TTL_DAY
    )

    return result

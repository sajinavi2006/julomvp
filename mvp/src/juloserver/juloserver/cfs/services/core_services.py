import calendar
import itertools
import logging
from datetime import timedelta, datetime

import semver
from django.db import (
    IntegrityError,
    transaction,
    DatabaseError,
)
from django.db.models import Sum, Count
from django.utils import timezone
from django.conf import settings
from dateutil.relativedelta import relativedelta

from juloserver.autodebet.constants import AutodebetStatuses, AutodebetVendorConst
from juloserver.autodebet.models import AutodebetAccount, AutodebetBenefit
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.apiv2.models import (
    EtlJob,
    PdClcsPrimeResult,
    PdCreditModelResult,
    PdWebModelResult,
)
from juloserver.application_flow.services import AddressFraudPrevention
from juloserver.cfs.exceptions import (
    CfsActionAssignmentInvalidStatus,
    CfsActionAssignmentNotFound,
    CfsActionNotFound,
    CfsFeatureNotEligible,
    CfsFeatureNotFound,
    CfsTierNotFound,
    DoMissionFailed,
    InvalidImage,
    UserForbidden, InvalidStatusChange,
)
from juloserver.ana_api.models import SdBankAccount
from juloserver.julo.statuses import ApplicationStatusCodes, PaymentStatusCodes
from juloserver.boost.services import get_bank_and_bpjs_status
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.customer_module.models import CashbackBalance, CashbackStatusHistory
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.portal.core.templatetags.unit import convert_datetime_to_string
from juloserver.cfs.constants import (
    ActionPointsBucket,
    ActionPointsReason,
    AddressVerification,
    CfsActionId,
    CfsActionPointsActivity,
    CfsActionType,
    CfsProgressStatus,
    CfsStatus,
    EtlJobType,
    GoogleAnalyticsActionTracking,
    MAP_ACCOUNT_STATUS_WITH_CFS_STATUS,
    MAP_CFS_ACTION_WITH_GOOGLE_ANALYTICS_EVENT,
    MAP_CFS_ACTION_WITH_TRANSACTION_NOTE,
    MAP_IMAGE_UPLOAD_TYPE_WITH_ACTION,
    MAP_PHONE_RELATED_TYPE_WITH_ACTION,
    MULTIPLIER_CUSTOMER_J_SCORE,
    PhoneRelatedType,
    TierId,
    VerifyAction,
    CfsEtlJobStatus,
    CustomerCfsAction,
    CFSTierTransactionCodeMapping,
    CfsMissionWebStatus,
    VerifyStatus, EasyIncomeConstant, MissionUploadType,
)
from juloserver.cfs.models import (
    CfsAction,
    CfsActionAssignment,
    CfsActionPoints,
    CfsActionPointsAssignment,
    CfsAddressVerification,
    CfsAssignmentVerification,
    CfsTier,
    TotalActionPoints,
    TotalActionPointsHistory,
)
from juloserver.julo.models import (
    Customer,
    FeatureSetting,
    Image,
    MobileFeatureSetting,
    Application,
)
from juloserver.cfs.authentication import EasyIncomeWebToken
from juloserver.otp.constants import SessionTokenAction
from juloserver.pin.models import TemporarySession
from juloserver.referral.services import show_referral_code
from juloserver.google_analytics.tasks import send_event_to_ga_task_async

logger = logging.getLogger(__name__)


def get_faqs():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CFS,
        is_active=True
    ).last()
    if not feature_setting:
        raise CfsFeatureNotFound

    faqs = feature_setting.parameters['faqs']
    return faqs


def get_cfs_status(application):
    if not application.eligible_for_cfs:
        raise CfsFeatureNotEligible

    customer = application.customer
    account = application.account
    account_limit = account.accountlimit_set.last()

    account_property = account.accountproperty_set.last()
    is_entry_level = account_property.is_entry_level
    cashback_balance = CashbackBalance.objects.filter(customer=customer).last()
    set_limit = account_limit.set_limit if account_limit else 0
    tiers_dict = get_tiers_dict()
    status = MAP_ACCOUNT_STATUS_WITH_CFS_STATUS.get(account.status_id, CfsStatus.BLOCKED)
    result = {
        'account_limit': set_limit,
        'cashback_balance': cashback_balance.cashback_balance if cashback_balance else 0,
        'rank_icon': tiers_dict[TierId.STARTER]['icon'],
        'is_entry_level': True,
        'status': status
    }
    if is_entry_level:
        return result

    j_score, tier_info = get_customer_tier_info(application)
    result.update({
        'rank_icon': tier_info.icon,
        'is_entry_level': False,
    })
    if status == CfsStatus.ACTIVE:
        result.update({
            'j_score': j_score,
            'rank_title': tier_info.name,
        })
    return result


def get_mission_enable_state(application):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CFS,
        is_active=True
    ).last()
    if feature_setting and application.eligible_for_cfs:
        return True

    return False


def get_all_cfs_actions_infos_dict():
    cfs_actions = list(CfsAction.objects.filter(is_active=True).all())

    return {
        cfs_action.id: cfs_action for cfs_action in cfs_actions
    }


def detect_create_or_update_cfs_action(customer, action_id, new_progress_status):
    latest_action_assignment = CfsActionAssignment.objects.filter(
        customer=customer, action_id=action_id
    ).last()
    if not latest_action_assignment:
        return CustomerCfsAction.CREATE, None

    today = timezone.localtime(timezone.now()).date()
    progress_status = latest_action_assignment.progress_status
    if progress_status in CfsProgressStatus.updatable_statuses():
        if (progress_status, new_progress_status) in CfsProgressStatus.status_pair_valid(action_id):
            return CustomerCfsAction.UPDATE, latest_action_assignment
        raise InvalidStatusChange('Invalid status change')

    if progress_status in CfsProgressStatus.creatable_statuses():
        if progress_status == CfsProgressStatus.FAILED or \
                (latest_action_assignment.action.action_type != CfsActionType.ONETIME and
                 latest_action_assignment.expiry_date.date() < today):
            return CustomerCfsAction.CREATE, latest_action_assignment

    raise DoMissionFailed('Can not do mission')


def check_distance_more_than_1_km(application, latitude, longitude):
    reverse_geolocation = AddressFraudPrevention(application)
    reverse_geolocation.get_address_coordinates()

    if reverse_geolocation.coordinates:
        distance_result = reverse_geolocation.calculate_distance(
            latitude,
            longitude,
            reverse_geolocation.coordinates['lat'],
            reverse_geolocation.coordinates['lng']
        )

        result = {
            'device_lat': latitude,
            'device_long': longitude,
            'application_address_lat': reverse_geolocation.coordinates['lat'],
            'application_address_long': reverse_geolocation.coordinates['lng'],
            'distance_in_km': distance_result,
            'decision': False
        }

        if distance_result > AddressVerification.DISTANCE_MAX:
            result['decision'] = True
            return False, result

        return True, result

    return False, None


def get_distinct_latest_assignments_action(customer, cfs_actions_infos_dict):
    distinct_latest_cfs_action_assignments = CfsActionAssignment.objects.\
        filter(customer=customer, action__in=cfs_actions_infos_dict.keys()).\
        exclude(progress_status=CfsProgressStatus.FAILED).\
        order_by('action', '-expiry_date').distinct('action')
    return {
        cfs_action_assignment.action_id: cfs_action_assignment
        for cfs_action_assignment in distinct_latest_cfs_action_assignments
    }


def convert_to_mission_response(tier, cfs_action, action_assignment=None,
                                is_mission_repeat=False, is_registered_bca_autodebet=False):
    result = {
        'title': cfs_action.title,
        'display_order': cfs_action.display_order,
        'action_code': cfs_action.action_code,
        'icon': cfs_action.icon,
        'app_link': cfs_action.app_link,
        'tag_info': {},
    }
    tag_info = cfs_action.tag_info
    if tag_info and tag_info['is_active']:
        result['tag_info'] = {
            'name': tag_info['name'],
        }
    multiplier = tier.cashback_multiplier
    if cfs_action.id not in [CfsActionId.REFERRAL, CfsActionId.BCA_AUTODEBET]:
        result['multiplier'] = multiplier
    if action_assignment:
        result.update({
            'progress_status': action_assignment.progress_status,
            'action_assignment_id': action_assignment.id,
            'cashback_amount': action_assignment.cashback_amount,
        })
        if action_assignment.progress_status == CfsProgressStatus.CLAIMED:
            if action_assignment.multiplier is not None \
                    and cfs_action.id != CfsActionId.BCA_AUTODEBET:
                result['multiplier'] = action_assignment.multiplier
            result['completed_time'] = convert_datetime_to_string(action_assignment.udate)
    else:
        result['progress_status'] = CfsProgressStatus.START
        if cfs_action.id == CfsActionId.REFERRAL:
            result['cashback_amount'] = tier.referral_bonus
        else:
            result['cashback_amount'] = cfs_action.repeat_occurrence_cashback_amount \
                if is_mission_repeat else cfs_action.first_occurrence_cashback_amount

    if cfs_action.id == CfsActionId.BCA_AUTODEBET and is_registered_bca_autodebet:
        result['progress_status'] = CfsProgressStatus.CLAIMED

    return result


def get_cfs_missions(application):
    customer = application.customer
    account = application.account
    today = timezone.localtime(timezone.now()).date()
    cfs_actions_infos_dict = get_all_cfs_actions_infos_dict()
    distinct_latest_assignments_by_action_code_dict = \
        get_distinct_latest_assignments_action(customer, cfs_actions_infos_dict)
    is_enable_bank, is_enable_bpjs = get_bank_and_bpjs_status()
    mfs_otp = MobileFeatureSetting.objects.get_or_none(feature_name='otp_setting', is_active=True)
    autodebet_bca = FeatureSetting.objects.get_or_none(feature_name='autodebet_bca', is_active=True)
    is_registered_bca_autodebet = AutodebetAccount.objects.filter(
        account=customer.account, activation_ts__isnull=False,
        vendor=AutodebetVendorConst.BCA
    ).exists()
    autodebet_benefit = AutodebetBenefit.objects.filter(
        account_id=account.id, pre_assigned_benefit__in=['cashback', 'waive_interest']
    ).last()
    _, tier = get_customer_tier_info(application)
    special_missions = []
    on_going_missions = []
    completed_missions = []
    for action_id, cfs_action in cfs_actions_infos_dict.items():
        skip_conditions = [
            action_id == CfsActionId.CONNECT_BANK and not is_enable_bank,
            action_id == CfsActionId.CONNECT_BPJS and not is_enable_bpjs,
            action_id in (
                CfsActionId.VERIFY_PHONE_NUMBER_1,
                CfsActionId.VERIFY_PHONE_NUMBER_2,
            ) and not mfs_otp,
            not account.app_version or not cfs_action.app_version or
            semver.match(account.app_version, "<%s" % cfs_action.app_version),
            action_id == CfsActionId.BCA_AUTODEBET and (not autodebet_bca or not autodebet_benefit),
            action_id == CfsActionId.REFERRAL and cfs_action.action_type == CfsActionType.UNLIMITED
            and not show_referral_code(customer)
        ]
        if any(skip_conditions):
            continue

        mission = on_going_missions
        is_mission_repeat = False
        existed_mission = distinct_latest_assignments_by_action_code_dict.get(action_id)
        if cfs_action.action_type == CfsActionType.UNLIMITED:
            mission = special_missions
        elif cfs_action.action_type == CfsActionType.ONETIME:
            if is_registered_bca_autodebet or existed_mission and \
                    existed_mission.progress_status in (
                    CfsProgressStatus.UNCLAIMED, CfsProgressStatus.CLAIMED
            ):
                mission = completed_missions
        else:
            if existed_mission:
                if existed_mission.progress_status == CfsProgressStatus.CLAIMED:
                    if existed_mission.expiry_date.date() < today:
                        is_mission_repeat = True
                        existed_mission = None
                    else:
                        mission = completed_missions

        mission_response = convert_to_mission_response(
            tier=tier,
            cfs_action=cfs_action,
            action_assignment=existed_mission,
            is_mission_repeat=is_mission_repeat,
            is_registered_bca_autodebet=is_registered_bca_autodebet,
        )
        mission.append(mission_response)

    return special_missions, on_going_missions, completed_missions


def get_cfs_mission_web_url(user, application, action=None):
    if not application:
        return None

    action_codes = get_available_action_codes(application.customer_id, action)
    if not action_codes:
        return None

    mission_url = get_cfs_mission_url(
        application=application, action=action, action_codes=action_codes
    )

    if not mission_url:
        return None

    web_url = "{base_url}/app/mission_list/{mission_url}token={token}".format(
        base_url=settings.MISSION_WEB_URL,
        mission_url=mission_url,
        token=EasyIncomeWebToken.generate_token_from_user(user)
    )
    return web_url


def get_available_action_codes(customer_id, action=None):
    action_code_mapping = {
        None: [
            MissionUploadType.UPLOAD_BANK_STATEMENT,
            MissionUploadType.UPLOAD_SALARY_SLIP,
            MissionUploadType.UPLOAD_CREDIT_CARD
        ],
        MissionUploadType.UPLOAD_BANK_STATEMENT: [MissionUploadType.UPLOAD_BANK_STATEMENT],
        MissionUploadType.UPLOAD_SALARY_SLIP: [MissionUploadType.UPLOAD_SALARY_SLIP],
        MissionUploadType.UPLOAD_CREDIT_CARD: [MissionUploadType.UPLOAD_CREDIT_CARD],
    }
    action_codes = action_code_mapping.get(action)
    if 'upload_credit_card' in action_codes:
        if not check_easy_income_upload_whitelist(
                customer_id, EasyIncomeConstant.FEATURE_SETTING_WHITELIST_CREDIT_CARD
        ):
            action_codes.remove('upload_credit_card')
    return action_codes


def get_cfs_mission_url(application, action, action_codes):
    customer = application.customer
    available_missions = get_available_mission_eligible_and_status(
        customer=customer, action_codes=action_codes
    )

    mission_url = ""
    if not action:
        for action_code in action_codes:
            if mission_url:
                mission_url += "&"

            is_eligible, status = available_missions.get(action_code, (None, None))
            if isinstance(is_eligible, bool) and isinstance(status, str):
                mission_url += construct_mission_param_url(
                    action_code=action_code, is_eligible=is_eligible, status=status
                )
        if mission_url:
            mission_url = "?{mission_url}&".format(mission_url=mission_url)
    else:
        is_eligible, _ = available_missions.get(action)
        if is_eligible:
            mission_url = "{action_code}/?".format(action_code=action)
    return mission_url


def get_available_mission_eligible_and_status(customer, action_codes):
    missions = {}
    cfs_actions = CfsAction.objects.filter(
        is_active=True,
        action_code__in=action_codes
    )
    if not cfs_actions:
        return missions

    distinct_latest_assignments = get_latest_distinct_cfs_assignment_verification(
        customer=customer, cfs_actions=cfs_actions
    )
    for action in cfs_actions:
        last_assignment_verification = distinct_latest_assignments.get(action.id)
        is_eligible, status = get_mission_eligible_and_status(
            action=action, last_assignment_verification=last_assignment_verification
        )
        missions[action.action_code] = (is_eligible, status)
    return missions


def get_mission_eligible_and_status(action, last_assignment_verification):
    if not last_assignment_verification:
        return True, CfsMissionWebStatus.START

    today = timezone.localtime(timezone.now()).date()
    verify_status = last_assignment_verification.verify_status
    if action.action_type == CfsActionType.UNLIMITED:
        return True, CfsMissionWebStatus.START
    elif action.action_type == CfsActionType.ONETIME:
        is_eligible, status = get_mission_eligible_status_from_verify_status(
            verify_status=verify_status
        )
        return is_eligible, status
    else:
        # If last action assignment is finished, check from expiry_date
        cfs_action_assignment = last_assignment_verification.cfs_action_assignment
        expiry_date = cfs_action_assignment.expiry_date
        if verify_status == VerifyStatus.APPROVE and expiry_date.date() < today:
            return True, CfsMissionWebStatus.START

        # If last action assignment is not finished, check from cdate
        default_expiry = cfs_action_assignment.action.default_expiry
        last_verification_cdate = last_assignment_verification.cdate
        if last_verification_cdate.date() + timedelta(days=default_expiry) < today:
            return True, CfsMissionWebStatus.START

        is_eligible, status = get_mission_eligible_status_from_verify_status(
            verify_status=verify_status
        )
        return is_eligible, status


def get_mission_eligible_status_from_verify_status(verify_status):
    verify_status_mapping = {
        None: (True, CfsMissionWebStatus.IN_PROGRESS),
        VerifyStatus.APPROVE: (False, CfsMissionWebStatus.APPROVED),
        VerifyStatus.REFUSE: (True, CfsMissionWebStatus.REJECTED)
    }
    return verify_status_mapping.get(verify_status, (None, None))


def get_latest_distinct_cfs_assignment_verification(customer, cfs_actions):
    distinct_latest_cfs_assignment_verifications = (
        CfsAssignmentVerification.objects
        .filter(
            cfs_action_assignment__customer=customer,
            cfs_action_assignment__action__in=cfs_actions
        )
        .order_by('cfs_action_assignment__action', '-pk')
        .distinct('cfs_action_assignment__action')
    )
    return {
        verification.cfs_action_assignment.action_id: verification
        for verification in distinct_latest_cfs_assignment_verifications
    }


def construct_mission_param_url(action_code, is_eligible, status):
    """
        Construct CFS mission and its status as URL param:
        Parameters:
            - action_code (str)
            - is_eligible (bool)
            - status (str)
    """
    mission_url = (
        "{action_code}={is_eligible}&{action_code}_status={status}"
    ).format(
        action_code=action_code,
        is_eligible=str(is_eligible).lower(),
        status=status
    )
    return mission_url


def claim_cfs_rewards(action_assignment_id, customer):
    with transaction.atomic():
        action_assignment = CfsActionAssignment.objects.select_for_update().filter(
            id=action_assignment_id
        ).first()
        if not action_assignment:
            raise CfsActionAssignmentNotFound

        if action_assignment.progress_status != CfsProgressStatus.UNCLAIMED:
            raise CfsActionAssignmentInvalidStatus

        if action_assignment.customer_id != customer.id:
            raise UserForbidden

        action_id = action_assignment.action_id

        cashback_balance = CashbackBalance.objects.filter(customer=customer).last()
        with transaction.atomic():
            if not cashback_balance:
                cashback_balance = CashbackBalance.objects.create(
                    customer=customer,
                    status=CashbackBalanceStatusConstant.UNFREEZE
                )
                CashbackStatusHistory.objects.create(
                    cashback_balance=cashback_balance,
                    status_new=cashback_balance.status
                )

            cashback_earned = \
                action_assignment.cashback_amount * action_assignment.extra_data['multiplier']
            new_wallet_history = action_assignment.customer.change_wallet_balance(
                change_accruing=cashback_earned,
                change_available=cashback_earned,
                reason='cfs_claim_reward'
            )
            if new_wallet_history:
                action_assignment.customer_wallet_history = new_wallet_history
                action_assignment.progress_status = CfsProgressStatus.CLAIMED
                action_assignment.save()
                send_cfs_ga_event(customer, action_id, GoogleAnalyticsActionTracking.KLAIM)
                return True, cashback_earned

            return False, None


def get_expiry_date(default_expiry):
    today = timezone.localtime(timezone.now()).date()
    return today + timedelta(days=default_expiry)


def create_or_update_cfs_action_assignment(application, action_id, progress_status,
                                           extra_data=None):
    customer = application.customer

    cfs_actions_infos_dict = get_all_cfs_actions_infos_dict()
    action = cfs_actions_infos_dict.get(action_id)
    if not action:
        raise CfsActionNotFound

    customer_action, latest_action_assignment = detect_create_or_update_cfs_action(
        customer, action_id, progress_status
    )

    _, tier = get_customer_tier_info(application)
    multiplier = tier.cashback_multiplier

    if extra_data is not None:
        extra_data['multiplier'] = multiplier
    else:
        extra_data = {'multiplier': multiplier}

    if customer_action == CustomerCfsAction.CREATE:
        if latest_action_assignment:
            repeat_action_no = latest_action_assignment.repeat_action_no + 1
            cashback_amount = action.repeat_occurrence_cashback_amount
        else:
            cashback_amount = action.first_occurrence_cashback_amount
            repeat_action_no = 1
        data_create = {
            'customer': customer,
            'repeat_action_no': repeat_action_no,
            'action_id': action_id,
            'progress_status': progress_status,
            'cashback_amount': cashback_amount,
            'extra_data': extra_data,
        }
        if progress_status == CfsProgressStatus.UNCLAIMED:
            data_create['expiry_date'] = get_expiry_date(action.default_expiry)

        cfs_action_assignment = CfsActionAssignment.objects.create(**data_create)
        send_cfs_ga_event(customer, action.id, GoogleAnalyticsActionTracking.MULAI)
        return cfs_action_assignment
    else:
        data_update = {
            'progress_status': progress_status,
            'extra_data': extra_data,
        }
        if progress_status == CfsProgressStatus.UNCLAIMED:
            data_update['expiry_date'] = get_expiry_date(action.default_expiry)

        CfsActionAssignment.objects.filter(id=latest_action_assignment.id).update(**data_update)
        latest_action_assignment.refresh_from_db()
        return latest_action_assignment


def create_cfs_assignment_verification(cfs_action_assignment, account, image_ids=None, monthly_income=None):
    extra_data = {}
    if image_ids is not None:
        extra_data['image_ids'] = image_ids
    data_create = {
        'cfs_action_assignment': cfs_action_assignment,
        'account': account,
    }
    if extra_data is not None:
        data_create['extra_data'] = extra_data

    if monthly_income is not None:
        data_create['monthly_income'] = monthly_income

    cfs_action_assignment = CfsAssignmentVerification.objects.create(**data_create)
    return cfs_action_assignment


def create_cfs_action_assignment_verify_address(application, latitude, longitude):
    is_valid, distance_result = check_distance_more_than_1_km(
        application,
        latitude,
        longitude
    )

    with transaction.atomic():
        action_assignment = create_or_update_cfs_action_assignment(
            application, CfsActionId.VERIFY_ADDRESS, CfsProgressStatus.START
        )
        if distance_result:
            distance_result['cfs_action_assignment_id'] = action_assignment.id
            CfsAddressVerification.objects.create(**distance_result)

        if is_valid:
            create_or_update_cfs_action_assignment(
                application, CfsActionId.VERIFY_ADDRESS, CfsProgressStatus.UNCLAIMED
            )
        else:
            action_assignment.update_safely(progress_status=CfsProgressStatus.FAILED)

        return is_valid, action_assignment


def create_cfs_action_assignment_upload_document(application, image_id):
    image = Image.objects.filter(id=image_id).first()
    if not image or image.image_source != application.id or \
            image.image_type not in MAP_IMAGE_UPLOAD_TYPE_WITH_ACTION.keys():
        raise InvalidImage('Invalid Image')

    action_id = MAP_IMAGE_UPLOAD_TYPE_WITH_ACTION[image.image_type]

    with transaction.atomic():
        action_assignment = create_or_update_cfs_action_assignment(
            application, action_id, CfsProgressStatus.PENDING
        )
        create_cfs_assignment_verification(
            action_assignment, application.account, image_ids=[image_id]
        )
        return action_assignment


def create_cfs_web_action_assignment_upload_document(application, image_ids,
                                                     upload_type, monthly_income):
    if not check_uploaded_images(application, image_ids, upload_type):
        raise InvalidImage('Invalid Image')

    action_id = MAP_IMAGE_UPLOAD_TYPE_WITH_ACTION.get(upload_type)
    if not action_id:
        raise InvalidImage('Invalid Image Upload Type')

    with transaction.atomic():
        action_assignment = create_or_update_cfs_action_assignment(
            application, action_id, CfsProgressStatus.PENDING
        )
        create_cfs_assignment_verification(
            action_assignment, application.account,
            image_ids=image_ids, monthly_income=monthly_income
        )
        return action_assignment


def check_uploaded_images(application, image_ids, upload_type):
    return Image.objects.filter(
        id__in=image_ids, image_type=upload_type, image_source=application.id
    ).count() == len(image_ids)


def create_cfs_action_assignment_share_social_media(application, app_name):
    extra_data = {'app_name': app_name}
    return create_or_update_cfs_action_assignment(
        application, CfsActionId.SHARE_TO_SOCIAL_MEDIA, CfsProgressStatus.UNCLAIMED, extra_data
    )


def create_cfs_action_assignment_verify_phone_via_otp(application, user, session_token,
                                                      session_token_action):
    action_id = None
    if session_token_action == SessionTokenAction.VERIFY_PHONE_NUMBER:
        action_id = CfsActionId.VERIFY_PHONE_NUMBER_1
    elif session_token_action == SessionTokenAction.VERIFY_PHONE_NUMBER_2:
        action_id = CfsActionId.VERIFY_PHONE_NUMBER_2

    now = timezone.localtime(timezone.now())
    session = TemporarySession.objects.filter(
        user=user,
        access_key=session_token,
        is_locked=False,
        expire_at__gt=now).last()
    phone_number = session.otp_request.phone_number

    with transaction.atomic():
        action_assignment = create_or_update_cfs_action_assignment(
            application, action_id, CfsProgressStatus.UNCLAIMED,
            extra_data={'phone_number': phone_number}
        )
        if session_token_action == SessionTokenAction.VERIFY_PHONE_NUMBER_2 and \
                phone_number != application.mobile_phone_2:
            application.mobile_phone_2 = phone_number
            application.save()
        return action_assignment


def create_cfs_action_assignment_phone_related(
        application, phone_related_type, phone_number,
        company_name=None, contact_type=None, contact_name=None):

    if phone_related_type == PhoneRelatedType.OFFICE_PHONE_NUMBER:
        extra_data = {
            'phone_number': phone_number,
            'company_name': company_name,
        }
    else:
        extra_data = {
            'phone_number': phone_number,
            'contact_type': contact_type,
            'contact_name': contact_name,
        }

    action_id = MAP_PHONE_RELATED_TYPE_WITH_ACTION[phone_related_type]
    with transaction.atomic():
        action_assignment = create_or_update_cfs_action_assignment(
            application, action_id, CfsProgressStatus.PENDING, extra_data=extra_data
        )
        create_cfs_assignment_verification(action_assignment, application.account)
        return action_assignment


def create_cfs_action_assignment_connect_bank(
    application, bank_name, progress_status, extra_data=None
):
    if not extra_data:
        extra_data = {}

    extra_data.update(bank_name=bank_name)
    return create_or_update_cfs_action_assignment(
        application, CfsActionId.CONNECT_BANK, progress_status, extra_data
    )


def create_cfs_action_assignment_connect_bpjs(application, progress_status):
    return create_or_update_cfs_action_assignment(
        application, CfsActionId.CONNECT_BPJS, progress_status
    )


def process_post_connect_bank(application, etl_job):
    if (
        etl_job.job_type != EtlJobType.CFS
        or etl_job.status not in CfsEtlJobStatus.AVAILABLE_FOR_BANK
    ):
        return False

    if application.application_status_id < ApplicationStatusCodes.LOC_APPROVED:
        return False

    customer = application.customer
    action_assignment = CfsActionAssignment.objects.filter(
        customer_id=customer.id, action_id=CfsActionId.CONNECT_BANK,
        progress_status__in=(CfsProgressStatus.START, CfsProgressStatus.PENDING)
    ).last()

    extra_data = {}
    sd_bank_account = SdBankAccount.objects.filter(
        application_id=application.id,
        customer_id=customer.id,
        bank_name=etl_job.data_type
    ).last()
    extra_data['bank_name'] = etl_job.data_type
    extra_data['etl_job_id'] = etl_job.id
    if sd_bank_account:
        extra_data['sd_bank_account_id'] = sd_bank_account.id

    if etl_job.status == EtlJob.AUTH_SUCCESS:
        if action_assignment and action_assignment.progress_status == CfsProgressStatus.PENDING:
            return True

        try:
            create_cfs_action_assignment_connect_bank(
                application, etl_job.data_type, CfsProgressStatus.PENDING, extra_data=extra_data)
            return True
        except (DoMissionFailed, CfsActionNotFound):
            sentry_client = get_julo_sentry_client()
            sentry_client.capture_exceptions()
            return False

    if not action_assignment:
        return False

    if etl_job.status == EtlJob.LOAD_SUCCESS:
        assignment_verification = CfsAssignmentVerification.objects.\
            filter(cfs_action_assignment=action_assignment).last()
        if assignment_verification and assignment_verification.is_pending:
            return True

        with transaction.atomic():
            action_assignment.progress_status = CfsProgressStatus.PENDING
            action_assignment.extra_data.update(extra_data)
            action_assignment.save(update_fields=['progress_status', 'extra_data'])
            create_cfs_assignment_verification(action_assignment, application.account)
            return True

    # To prevent rejecting the current action_assignment.
    if etl_job.data_type != action_assignment.extra_data.get('bank_name'):
        return True

    with transaction.atomic():
        from juloserver.cfs.services.crm_services import change_pending_state_assignment
        if action_assignment.progress_status == CfsProgressStatus.PENDING:
            assignment_verification = create_cfs_assignment_verification(
                action_assignment, application.account)
            change_pending_state_assignment(
                application, action_assignment, assignment_verification, CfsProgressStatus.START,
                VerifyAction.REFUSE, agent=None
            )

    return True


def process_post_connect_bpjs_success(application_id, customer_id, bpjs_task=None):
    from juloserver.bpjs.services import Bpjs

    application = Application.objects.get(pk=application_id)
    action_assignment = CfsActionAssignment.objects.filter(
        customer_id=customer_id, action_id=CfsActionId.CONNECT_BPJS
    ).last()
    if action_assignment:
        extra_data = action_assignment.extra_data or {}
        if bpjs_task:
            extra_data['bpjs_task_id'] = bpjs_task.id

        bpjs = Bpjs(application=application)
        bpjs_profile = bpjs.profiles.last()
        if bpjs_profile:
            extra_data['sd_bpjs_profile_id'] = bpjs_profile.id
            action_assignment.extra_data = extra_data
        if action_assignment.progress_status == CfsProgressStatus.START:
            action_assignment.update_safely(progress_status=CfsProgressStatus.PENDING)
            create_cfs_assignment_verification(action_assignment, application.account)
        return True

    customer = Customer.objects.get_or_none(pk=customer_id)
    send_cfs_ga_event(customer, CfsActionId.CONNECT_BPJS, GoogleAnalyticsActionTracking.REFUSE)
    return False


def send_cfs_ga_event(customer, action_id, action_tracking):
    ga_event = MAP_CFS_ACTION_WITH_GOOGLE_ANALYTICS_EVENT[action_id].get(action_tracking, {})
    if ga_event:
        if customer.app_instance_id:
            send_event_to_ga_task_async.apply_async(
                kwargs={'customer_id': customer.id, 'event': ga_event}
            )
        else:
            logger.info(
                'send_cfs_ga_event|app_instance_id not found|customer_id=%s' % customer.id
            )


def convert_to_tier_info(tier):
    return {
        'id': tier.id,
        'name': tier.name,
        'point': tier.point,
        'message': tier.message,
        'icon': tier.icon,
        'cashback_multiplier': tier.cashback_multiplier,
        'referral_bonus': tier.referral_bonus,
        'qris': tier.qris,
        'ppob': tier.ppob,
        'ecommerce': tier.ecommerce,
        'tarik_dana': tier.tarik_dana,
        'dompet_digital': tier.dompet_digital,
        'transfer_dana': tier.transfer_dana,
        'pencairan_cashback': tier.pencairan_cashback,
    }


def get_tiers_dict():
    tiers = CfsTier.objects.all().order_by('id')
    if not tiers:
        raise CfsTierNotFound
    return {tier.id: convert_to_tier_info(tier) for tier in tiers}


def get_pgood(application_id):
    pd_credit_model_result = PdCreditModelResult.objects.filter(
        application_id=application_id
    ).last()
    if pd_credit_model_result:
        return pd_credit_model_result.pgood
    else:
        pd_web_model_result = PdWebModelResult.objects.filter(
            application_id=application_id
        ).last()
        if pd_web_model_result:
            return pd_web_model_result.pgood


def get_clcs_prime_score(application):
    pd_clcs_prime_result = PdClcsPrimeResult.objects.filter(
        customer_id=application.customer_id
    ).order_by('partition_date').last()
    if pd_clcs_prime_result:
        clcs_prime_score = pd_clcs_prime_result.clcs_prime_score
    else:
        clcs_prime_score = get_pgood(application.id)
    return clcs_prime_score


def get_customer_tier_info(application):
    from juloserver.entry_limit.services import is_entry_level_type
    if not application.eligible_for_cfs:
        return None, None

    total_action_points = TotalActionPoints.objects.filter(
        customer=application.customer
    ).last()
    point = total_action_points.point if total_action_points else 0

    clcs_prime_score = get_clcs_prime_score(application)
    j_score = int(clcs_prime_score * MULTIPLIER_CUSTOMER_J_SCORE * 1000 + point)
    if j_score < 0 or is_entry_level_type(application):
        tier_info = CfsTier.objects.get(pk=TierId.STARTER)
    else:
        tier_info = CfsTier.objects.filter(point__lte=j_score).order_by('point').last()

    return j_score, tier_info


def get_latest_action_point_by_month(customer):
    """this functions returns a list/dic of customers's new point by lastest by each month

    {
       # if there is (2022-12-03), 2022-12-04 is displayed
       datetime(2022-12-01) : new_point,
       datetime(2022-11-01): new_point,
    }
    """
    histories = TotalActionPointsHistory.objects.filter(
        customer_id=customer.id
    ).order_by('id').values('partition_date', 'new_point')
    groups = itertools.groupby(
        histories,
        lambda d: datetime.now().replace(
            day=1, month=d['partition_date'].month, year=d['partition_date'].year
        ).date()
    )
    return {key_report: list(group)[-1]['new_point'] for key_report, group in groups}


def get_latest_clcs_prime_score_by_month(customer):
    histories = list(PdClcsPrimeResult.objects.filter(
        customer_id=customer.id
    ).order_by('id').values('partition_date', 'clcs_prime_score'))
    groups = itertools.groupby(
        histories,
        lambda d: datetime.now().replace(
            day=1, month=d['partition_date'].month, year=d['partition_date'].year
        ).date()
    )
    return {key_report: list(group)[-1]['clcs_prime_score'] for key_report, group in groups}


def get_latest_clcs_prime_score_in_one_month(customer, month, year):
    """
    Purpose: get the clcs prime score based on the month and year passed in. If there isn't any,
    return 0
    """
    datetime_str = '{}-{}-{}'.format(year, month, 1)
    datetime_obj = datetime.strptime(datetime_str, '%Y-%m-%d').date()
    found_score = get_latest_clcs_prime_score_by_month(customer).get(datetime_obj)
    return 0 if not found_score else found_score


def get_j_score_history_message(messages_config, gap_score):
    for message_config in messages_config:
        if message_config['min_value'] <= gap_score <= message_config['max_value']:
            return message_config['message']

    return


def get_customer_j_score_histories(application):
    feature_setting = FeatureSetting.objects.get(feature_name='cfs')
    jscore_messages_config = feature_setting.parameters['jscore_messages']
    today = timezone.localtime(timezone.now())
    latest_action_point_by_month = get_latest_action_point_by_month(application.customer)
    latest_clcs_prime_score_by_month = get_latest_clcs_prime_score_by_month(application.customer)

    start_date_report = get_start_date_report(
        latest_action_point_by_month, latest_clcs_prime_score_by_month
    )
    if not start_date_report:
        return []

    current_date_report = today.replace(month=today.month, year=today.year).date()

    result = []
    action_point = 0
    clcs_prime_score = get_pgood(application.id)
    previous_j_score = 0
    while start_date_report <= current_date_report:
        if latest_action_point_by_month.get(start_date_report):
            action_point = latest_action_point_by_month[start_date_report]

        if latest_clcs_prime_score_by_month.get(start_date_report):
            clcs_prime_score = latest_clcs_prime_score_by_month[start_date_report]

        current_j_score = calculate_j_score(clcs_prime_score, action_point)
        gap_score = current_j_score - previous_j_score
        result.append({
            'report_time': '{}-{}'.format(start_date_report.month, start_date_report.year),
            'j_score': gap_score,
            'message': get_j_score_history_message(jscore_messages_config, gap_score)
        })
        start_date_report = start_date_report + relativedelta(months=1)
        previous_j_score = current_j_score
    result.reverse()
    return result


def get_start_date_report(latest_action_point_by_month, latest_clcs_prime_score_by_month):
    if latest_action_point_by_month and latest_clcs_prime_score_by_month:
        return min(
            list(latest_action_point_by_month.keys())[0],
            list(latest_clcs_prime_score_by_month.keys())[0]
        )
    if latest_action_point_by_month:
        return list(latest_action_point_by_month.keys())[0]
    if latest_clcs_prime_score_by_month:
        return list(latest_clcs_prime_score_by_month.keys())[0]
    return None


def check_lock_by_customer_tier(account, method_code, application_direct=None):
    is_locked = False

    # Split code for optimize v2 Credit Info only.
    application = application_direct or account.application_set.last()

    _, tier_info = get_customer_tier_info(application)
    if not tier_info:
        return is_locked

    tier_method = CFSTierTransactionCodeMapping.MAP_TRANSACTION_METHOD_WITH_CFS_TIER.get(
        method_code, CFSTierTransactionCodeMapping.DEFAULT_CFS_TRANSACTION_METHOD
    )
    is_locked = not getattr(tier_info, tier_method)

    return is_locked


def is_graduate_of(application, tier_id):
    """
    Check whether a customer is at least a certain tier level
    """
    _, tier = get_customer_tier_info(application)
    if tier:
        return tier.id >= tier_id

    return False


def calculate_action_points(amount, multiplier, floor, ceiling):
    multiplied_amount = amount * multiplier / 100  # multipler is a percentage
    result = floor if multiplied_amount < floor else \
        (ceiling if multiplied_amount > ceiling else multiplied_amount)

    return result


def get_activity_based_on_payment_history(payment_history):
    activity_id = None
    # returns the actitivity id/activity_id
    if payment_history.due_amount == 0 and payment_history.paid_date:  # has been paid
        if payment_history.payment_new_status_code == PaymentStatusCodes.PAID_ON_TIME:
            # on time or early:
            if payment_history.paid_date == payment_history.due_date:
                activity_id = CfsActionPointsActivity.ON_TIME_REPAYMENT
            else:
                activity_id = CfsActionPointsActivity.EARLY_REPAYMENT
        elif payment_history.payment_new_status_code == PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD:
            # case grace
            activity_id = CfsActionPointsActivity.GRACE_REPAYMENT
        elif payment_history.payment_new_status_code == PaymentStatusCodes.PAID_LATE:
            # case: b1, b2, b3, b4, wo
            gap = (payment_history.paid_date - payment_history.due_date).days
            # gap is always > 0
            if ActionPointsBucket.B1_DPD['to'] >= gap >= ActionPointsBucket.B1_DPD['from']:
                activity_id = CfsActionPointsActivity.B1_REPAYMENT
            elif ActionPointsBucket.B2_DPD['to'] >= gap >= ActionPointsBucket.B2_DPD['from']:
                activity_id = CfsActionPointsActivity.B2_REPAYMENT
            elif ActionPointsBucket.B3_DPD['to'] >= gap >= ActionPointsBucket.B3_DPD['from']:
                activity_id = CfsActionPointsActivity.B3_REPAYMENT
            elif ActionPointsBucket.B4_DPD['to'] >= gap >= ActionPointsBucket.B4_DPD['from']:
                activity_id = CfsActionPointsActivity.B4_REPAYMENT
            elif gap > ActionPointsBucket.B4_DPD['to']:
                activity_id = CfsActionPointsActivity.WO

    return activity_id


def update_total_points_and_create_history(data, activity_id):
    """
    data param is expected to be a dict, like so:
    data = {
            'customer': customer,
            'amount': amount,
            'assignment_info': assignment_info (see each tracking case)
        }
    """
    activity = CfsActionPoints.objects.get(pk=activity_id)

    now = timezone.localtime(timezone.now())
    amount = data['amount']
    customer = data['customer']
    assignment_info = data.get('assignment_info', {})

    extra_data = {
        'multiplier': activity.multiplier,
        'floor': activity.floor,
        'ceiling': activity.ceiling,
        'amount': amount
    }

    action_points = calculate_action_points(
        amount=amount,
        multiplier=activity.multiplier,
        floor=activity.floor,
        ceiling=activity.ceiling,
    )
    assignment_info.update({
        'customer_id': customer.id,
        'cfs_action_points_id': activity.id,
        'points_changed': action_points,
        'extra_data': extra_data,
        'expiry_date': now + timedelta(days=activity.default_expiry),
    })

    change_reason = ActionPointsReason.ACTION_POINTS
    partition_date = now.date()

    try:
        TotalActionPoints.objects.get_or_create(
            customer=customer,
        )
    except IntegrityError:
        # handle case duplicate requests, do nothing
        pass

    with transaction.atomic(), transaction.atomic(using='utilization_db'):
        customer_points = TotalActionPoints.objects\
            .select_for_update()\
            .filter(customer=customer).first()

        # insert activity record into table:
        new_assignment = CfsActionPointsAssignment.objects.create(**assignment_info)

        old_point = customer_points.point
        new_point = old_point + action_points
        customer_points.point = new_point
        customer_points.save(update_fields=['point'])

        record = {
            'customer_id': customer.id,
            'partition_date': partition_date,
            'old_point': old_point,
            'new_point': new_point,
            'change_reason': change_reason,
            'cfs_action_point_assignment_id': new_assignment.id
        }
        TotalActionPointsHistory.objects.create(**record)


def tracking_fraud_case_for_action_points(account, activity_id):
    # calculate the outstanding amount for fraudster
    from juloserver.account_payment.services.account_payment_related import (
        get_unpaid_account_payment)

    unpaid_account_payments = get_unpaid_account_payment(account.id)
    amount = 0
    for account_payment in unpaid_account_payments:
        amount += account_payment.due_amount

    data = {
        'customer': account.customer,
        'amount': amount
    }
    update_total_points_and_create_history(data, activity_id=activity_id)


def bulk_update_total_points_and_create_history(data, activity_id):
    """
    data param is expected to be a list of dicts, like so:
    data = [
        {
            'customer_id': customer1_id,
            'amount': amount,
            'assignment_info': {}   ## pass in loan & payment if exists
        },
        {
            'customer_id': customer2_id,
            ...
        }
    ]
    """
    activity = CfsActionPoints.objects.get(pk=activity_id)

    now = timezone.localtime(timezone.now())
    action_assignments = []
    customer_ids = set()
    points_changed = {}
    for each_data in data:
        assignment_info = each_data.get('assignment_info', {})
        extra_data = {
            'multiplier': activity.multiplier,
            'floor': activity.floor,
            'ceiling': activity.ceiling,
            'amount': each_data['amount']
        }
        action_points = calculate_action_points(
            amount=each_data['amount'],
            multiplier=activity.multiplier,
            floor=activity.floor,
            ceiling=activity.ceiling
        )
        assignment_info.update({
            'customer_id': each_data['customer_id'],
            'cfs_action_points_id': activity.id,
            'points_changed': action_points,
            'extra_data': extra_data,
            'expiry_date': now + timedelta(days=activity.default_expiry)
        })
        action_assignment = CfsActionPointsAssignment(**assignment_info)
        action_assignments.append(action_assignment)
        customer_ids.add(each_data['customer_id'])
        points_changed[each_data['customer_id']] = action_points

    change_reason = ActionPointsReason.ACTION_POINTS
    partition_date = now.date()

    with transaction.atomic(), transaction.atomic(using='utilization_db'):
        total_points = TotalActionPoints.objects\
            .select_for_update()\
            .filter(customer_id__in=customer_ids)

        customer_points = {}
        # update existing customers' total points:
        for total_point in total_points:
            old_point = total_point.point
            new_point = old_point + points_changed[total_point.customer_id]
            total_point.point = new_point
            total_point.save()

            customer_points[total_point.customer_id] = {
                'old_point': old_point,
                'new_point': new_point
            }
            # remove this customer after done
            customer_ids.remove(total_point.customer_id)

        # create rows for the rest
        new_total_points = []
        for customer_id in customer_ids:
            new_point = points_changed[customer_id]
            customer_points[customer_id] = {
                'old_point': 0,
                'new_point': new_point
            }
            new_total_point = TotalActionPoints(customer_id=customer_id, point=new_point)
            new_total_points.append(new_total_point)
        TotalActionPoints.objects.bulk_create(new_total_points)

        records = []
        for action_assignment in action_assignments:
            action_assignment.save()
            customer_id = action_assignment.customer_id
            record = {
                'customer_id': customer_id,
                'partition_date': partition_date,
                'old_point': customer_points[customer_id]['old_point'],
                'new_point': customer_points[customer_id]['new_point'],
                'change_reason': change_reason,
                'cfs_action_point_assignment_id': action_assignment.id
            }
            point_history = TotalActionPointsHistory(**record)
            records.append(point_history)
        TotalActionPointsHistory.objects.bulk_create(records)


def get_cfs_transaction_note(transaction_id):
    cfs_action_assignment = CfsActionAssignment.objects.filter(
        customer_wallet_history__id=transaction_id
    ).first()
    if not cfs_action_assignment:
        return
    cfs_action_id = cfs_action_assignment.action_id
    return MAP_CFS_ACTION_WITH_TRANSACTION_NOTE[cfs_action_id]


def get_cfs_referral_bonus_by_application(application):
    _, tier = get_customer_tier_info(application)
    if tier:
        return tier.referral_bonus

    return None


def lock_assignment_verification(assignment_verification_id, agent_id):
    logger_data = {
        'module': 'cfs',
        'action': 'services.core_services.lock_assignment_verification',
        'assignment_verification_id': assignment_verification_id,
        'agent_id': agent_id
    }
    try:
        with transaction.atomic():
            assignment_verification = CfsAssignmentVerification.objects\
                .select_for_update(nowait=True)\
                .get(id=assignment_verification_id)
            if assignment_verification.locked_by_id:
                logger.info({
                    'message': 'The assignment is locked by another agent',
                    'locked_by_id': assignment_verification.locked_by_id,
                    **logger_data,
                })
                return False

            assignment_verification.locked_by_id = agent_id
            assignment_verification.save(update_fields=['locked_by_id', 'udate'])
            return True
    except DatabaseError:
        logger.warning({
            'message': 'The assignment is locked from DB',
            **logger_data,
        }, exc_info=True)
        return False


def unlock_assignment_verification(assignment_verification_id):
    CfsAssignmentVerification.objects\
        .filter(id=assignment_verification_id)\
        .update(locked_by_id=None)


def get_locked_assignment_verifications(agent_id):
    return list(
        CfsAssignmentVerification.objects.filter(locked_by_id=agent_id).order_by('cdate').all()
    )


def calculate_score_point_diff(score_diff, customer, month, year):
    point_diff = TotalActionPointsHistory.objects.filter(
        customer_id=customer.id,
        partition_date__month=month,
        partition_date__year=year,
    ).aggregate(
        difference=Sum('new_point') - Sum('old_point')
    )
    gap = score_diff - point_diff['difference']
    return gap


def get_number_of_change_reasons_in_one_month(customer, month, year):
    change_reason_list = TotalActionPointsHistory.objects.filter(
        customer_id=customer.id,
        partition_date__month=month,
        partition_date__year=year
    ).distinct().values_list('change_reason', flat=True)
    return change_reason_list


def calculate_j_score_diff_current_previous_month(customer, month, year, cur_clcs_score):
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    prev_clcs_score = get_latest_clcs_prime_score_in_one_month(customer, prev_month, prev_year)

    previous_month_history = TotalActionPointsHistory.objects.filter(
        customer_id=customer.id,
        partition_date__lt=datetime(year, month, 1)
    ).exists()
    if not previous_month_history and not prev_clcs_score:
        return None

    current_month_history = TotalActionPointsHistory.objects.filter(
        customer_id=customer.id,
        partition_date__month=month,
        partition_date__year=year
    ).values('partition_date', 'old_point', 'new_point')

    cur_last_transaction = current_month_history.last()
    cur_new_point_last_transaction = cur_last_transaction['new_point']

    prev_clcs_score = get_latest_clcs_prime_score_in_one_month(customer, prev_month, prev_year)
    cur_old_point_first_transaction = current_month_history.first()['old_point']

    return calculate_j_score(cur_clcs_score, cur_new_point_last_transaction) - \
        calculate_j_score(prev_clcs_score, cur_old_point_first_transaction)


def get_j_score_history_details_per_change_reason(month, year, customer, change_reason,
                                                  score_diff, num_change_reasons):
    gap = calculate_score_point_diff(score_diff, customer, month, year)
    total_change_point_change_reason = TotalActionPointsHistory.objects.filter(
        customer_id=customer.id, partition_date__month=month, partition_date__year=year,
        change_reason=change_reason
    ).aggregate(diff=Sum('new_point') - Sum('old_point'))
    score_change_reason = total_change_point_change_reason['diff'] + (gap / num_change_reasons)

    if score_change_reason != 0:
        title, message = get_j_score_details_history_title_message(
            score_change_reason, change_reason)
        return {
            'title': title,
            'score': score_change_reason,
            'message': message,
        }
    return {}


def get_j_score_history_details(month, year, customer):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.J_SCORE_HISTORY_CONFIG,
        is_active=True
    ).exists()
    if not feature_setting:
        return {}

    cur_clcs_score = get_latest_clcs_prime_score_in_one_month(customer, month, year)
    if not cur_clcs_score:
        return {}

    details = {reason: {} for reason in ActionPointsReason.get_action_points_reasons()}

    change_reason_list = get_number_of_change_reasons_in_one_month(customer, month, year)
    if not change_reason_list:
        return details

    score_diff = calculate_j_score_diff_current_previous_month(customer, month,
                                                               year, cur_clcs_score)
    if not score_diff:
        return details

    for reason in change_reason_list:
        details[reason] = get_j_score_history_details_per_change_reason(month, year, customer,
                                                                        reason, score_diff,
                                                                        len(change_reason_list))

    return details


def get_j_score_details_history_title_message(score, change_reason):
    """
    Purpose: Based on the calculated score (negative, 0 or positive),
    return the corresponding title and message
    """
    month_history_details = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.J_SCORE_HISTORY_CONFIG
    ).parameters['j_score_history_details'][change_reason]
    title = message = ''
    for detail in month_history_details:
        if detail['max_value'] >= score >= detail['min_value']:
            title = detail['title']
            message = detail['message']

    return title, message


def calculate_j_score(clcs_prime_score, action_points):
    return int(1000 * MULTIPLIER_CUSTOMER_J_SCORE * clcs_prime_score + action_points)


def check_easy_income_upload_whitelist(customer_id, feature_name):
    whitelist_fs = FeatureSetting.objects.filter(
        feature_name=feature_name, is_active=True
    ).last()
    if whitelist_fs:
        whitelist_customer_ids = whitelist_fs.parameters.get('customer_ids', [])
        return customer_id in whitelist_customer_ids
    return True

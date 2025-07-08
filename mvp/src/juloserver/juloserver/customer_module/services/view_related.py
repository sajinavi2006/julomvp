import semver

from juloserver.julo.constants import MobileFeatureNameConst
from django.db.models import Sum
from datetime import timedelta
from django.utils import timezone

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import (
    ApplicationHistory,
    MobileFeatureSetting,
    FeatureSetting,
    ApplicationUpgrade,
    Application,
    AddressGeolocation,
    CreditScore,
)
from juloserver.account.models import AccountLimit
from juloserver.loan.models import Loan
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.customer_module.constants import FeatureNameConst
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.account.models import CreditLimitGeneration
from juloserver.julo.constants import WorkflowConst, ProductLineCodes
from juloserver.julo.exceptions import JuloException
from juloserver.customer_module.exceptions import CustomerGeolocationException
from juloserver.limit_validity_timer.models import LimitValidityTimer
from juloserver.limit_validity_timer.services import (
    get_validity_campaign_timer_response,
    get_soonest_campaign_for_customer_from_redis,
)


logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def get_limit_card_action(data):
    limit_card_call_to_action = MobileFeatureSetting.objects.filter(
        feature_name="limit_card_call_to_action"
    ).last()

    data['limit_action'] = {}

    if limit_card_call_to_action.is_active:
        for key in limit_card_call_to_action.parameters:
            if limit_card_call_to_action.parameters[key]['is_active']:
                data['limit_action'][key] = limit_card_call_to_action.parameters[key]
            else:
                data['limit_action'][key] = None
    else:
        for key in limit_card_call_to_action.parameters:
            data['limit_action'][key] = None

    return data


def get_transaction_method_whitelist_feature(transaction_method_name):
    whitelist_setting = MobileFeatureSetting.objects.filter(
        feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_WHITELIST,
        is_active=True,
    ).last()

    # return None in 2 cases:
    # 1. Whitelist is inactive
    # 2. Whitelist is active, but the transaction method name is not configured in the parameters
    if not whitelist_setting or transaction_method_name not in whitelist_setting.parameters:
        return None

    return whitelist_setting


def is_transaction_method_whitelist_user(
    transaction_method_name, application_id, feature_setting=None
):
    feature_setting = feature_setting or get_transaction_method_whitelist_feature(
        transaction_method_name
    )
    if not feature_setting:
        return True

    parameters = feature_setting.parameters.get(transaction_method_name, {})
    return application_id in parameters.get('application_ids', [])


def check_whitelist_transaction_method(transaction_methods, transaction_method, application_id):
    if not is_transaction_method_whitelist_user(transaction_method.name, application_id):
        return transaction_methods.exclude(id=transaction_method.code)
    return transaction_methods


def get_validity_timer_feature_setting():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.VALIDITY_TIMER, is_active=True
    ).first()


class LimitTimerService:
    def __init__(self, limit_timer_data, today):
        self.today = today
        self.limit_timer_data = limit_timer_data
        self.days_after_190 = limit_timer_data['days_after_190']

    def calculate_rest_of_countdown(self, app_x190_history_cdate):
        countdown = self.limit_timer_data['countdown']
        repeat_time = self.limit_timer_data['repeat_time']

        show_pop_up = False
        rest_of_countdown = None
        # include the first time of showing timer
        total_days_feature = (repeat_time + 1) * countdown
        cdate_after_app_x190_history = app_x190_history_cdate + timedelta(days=self.days_after_190)
        passed_days = (self.today - cdate_after_app_x190_history).days

        if passed_days < total_days_feature:
            rest_of_countdown = countdown - (passed_days % countdown)
            app_repeat_time = passed_days // countdown

            if app_repeat_time > 0 and rest_of_countdown == countdown:
                show_pop_up = True

        return rest_of_countdown, show_pop_up

    def get_app_history_lte_days_after_190(self, application_id):
        return (
            ApplicationHistory.objects.filter(
                application_id=application_id,
                status_new=ApplicationStatusCodes.LOC_APPROVED,
                cdate__date__lte=self.today - timedelta(days=self.days_after_190),
            )
            .values('cdate')
            .last()
        )

    def check_limit_utilization_rate(self, customer_id, account_id):
        limit_utilization_rate = self.limit_timer_data['limit_utilization_rate']
        customer_limit_rate = 0

        loan = Loan.objects.filter(
            customer_id=customer_id, loan_status__gte=LoanStatusCodes.CURRENT
        ).aggregate(total_loan_amount=Sum('loan_amount'))
        total_loan_amount = loan['total_loan_amount'] or 0

        # if no loan, don't need getting limit
        if total_loan_amount > 0:
            account_limit = (
                AccountLimit.objects.filter(account_id=account_id).values('set_limit').last()
            )
            customer_limit_rate = total_loan_amount / account_limit['set_limit']
            return customer_limit_rate * 100 < limit_utilization_rate
        return True


def is_julo_turbo_upgrade_calculation_process(application):
    if not application.is_julo_starter():
        return False

    application_upgrade = ApplicationUpgrade.objects.filter(
        application_id_first_approval=application.id,
        is_upgrade=1,
    ).last()
    if not application_upgrade:
        return False

    j_one_application = Application.objects.get_or_none(pk=application_upgrade.application_id)
    if not j_one_application:
        return False

    if application.application_status_id != ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE:
        return False

    if j_one_application.application_status_id not in [
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    ]:
        if j_one_application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:

            # get credit score
            credit_score = CreditScore.objects.filter(application_id=j_one_application.id).last()

            # will return false to hide julo upgrade process banner
            # banner is Limit JULO Kredit Digital sedang diproses
            if not credit_score or credit_score.score in ['C', '--']:
                return False

        return True

    return False


@sentry.capture_exceptions
def determine_set_limit_for_j1_in_progress(application, customer, account_limit):

    # check application only allow for JTurbo
    if application.is_julo_starter():

        # check application j1
        application_j1 = Application.objects.filter(
            customer=customer,
            workflow__name=WorkflowConst.JULO_ONE,
            product_line=ProductLineCodes.J1,
        ).last()

        if not application_j1:
            # return originally set limit
            return account_limit.set_limit

        # check if application j1 still not approved
        if application_j1.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
            credit_limit_jturbo = CreditLimitGeneration.objects.filter(
                application_id=application.id
            ).last()

            if not credit_limit_jturbo:
                error_message = 'Not found credit limit generation'
                logger.error({'message': error_message, 'application': application.id})
                raise JuloException(error_message)

            return credit_limit_jturbo.set_limit

    if application.is_julo_one():

        application_jturbo = Application.objects.filter(
            customer=customer,
            application_status=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
            workflow__name=WorkflowConst.JULO_STARTER,
            product_line=ProductLineCodes.JULO_STARTER,
        ).last()

        if (
            not application_jturbo
            or application.application_status_id == ApplicationStatusCodes.LOC_APPROVED
        ):
            # return originally set limit
            return account_limit.set_limit

        credit_limit_j1 = CreditLimitGeneration.objects.filter(application_id=application.id).last()
        credit_limit_jturbo = CreditLimitGeneration.objects.filter(
            application_id=application_jturbo.id
        ).last()

        if not credit_limit_j1 or not credit_limit_jturbo:
            error_message = 'Not found credit limit generation'
            logger.error({'message': error_message, 'application': application.id})
            raise JuloException(error_message)

        if credit_limit_j1.set_limit <= credit_limit_jturbo.set_limit:
            return credit_limit_jturbo.set_limit

        return credit_limit_j1.set_limit

    # return originally set limit
    return account_limit.set_limit


@sentry.capture_exceptions
def process_customer_update_location(validated_data, customer):
    from juloserver.julo.utils import execute_after_transaction_safely
    from juloserver.pin.tasks import trigger_login_success_signal
    from juloserver.pin.services import (
        get_last_success_login_attempt,
        get_last_application,
    )
    from juloserver.apiv2.tasks import generate_address_from_geolocation_async
    from juloserver.application_flow.constants import PartnerNameConstant

    latitude = validated_data.get('latitude')
    longitude = validated_data.get('longitude')
    login_attempt = get_last_success_login_attempt(customer.id)

    logger.info(
        {
            'function': 'process_customer_update_location',
            'customer_id': customer.id,
            'login_attempt_exist': True if login_attempt else None,
        }
    )
    if not login_attempt:
        raise CustomerGeolocationException('Empty for data login attempt')

    if login_attempt.latitude and login_attempt.longitude:
        # skip process update if the data already available
        logger.info(
            {
                'message': 'Skip process update latitude and longitude',
                'function': 'process_customer_update_location',
                'customer_id': customer.id,
                'reason': 'available the data on login_attempt',
                'login_attemp_latitude': login_attempt.latitude,
                'login_attemp_longitude': login_attempt.longitude,
                'latitude_param': latitude,
                'longitude_param': longitude,
            }
        )
        return True

    # Update latitude and longitude to login attempt
    login_attempt.update_safely(
        latitude=latitude,
        longitude=longitude,
    )

    # get last application id
    application = get_last_application(customer)
    if (
        application
        and not hasattr(application, 'addressgeolocation')
        and application.partner_name != PartnerNameConstant.LINKAJA
        and latitude
        and longitude
    ):
        address_geolocation = AddressGeolocation.objects.create(
            application=application,
            latitude=latitude,
            longitude=longitude,
        )
        generate_address_from_geolocation_async.delay(address_geolocation.id)

    # Defer login_success signals so that it will not impact the login endpoint performance.
    # Don't pass any confidential data in the event_login_data.
    event_login_data = {
        **{
            key: value
            for key, value in validated_data.items()
            if key in {'latitude', 'longitude', 'android_id'}
        },
        'login_attempt_id': login_attempt.id if login_attempt else None,
        'event_timestamp': timezone.now().timestamp(),
    }
    logger.info(
        {
            'function': 'process_customer_update_location',
            'customer_id': customer.id,
            'message': 'continue to trigger_login_success_signal',
        }
    )
    execute_after_transaction_safely(
        lambda: {trigger_login_success_signal.delay(customer.id, event_login_data)}
    )
    return True


def get_limit_validity_timer_first_time_x190(application):
    from juloserver.customer_module.serializers import LimitTimerSerializer

    account = application.account
    customer = application.customer
    limit_timer_feature = get_validity_timer_feature_setting()
    if limit_timer_feature:
        serializer = LimitTimerSerializer(data=limit_timer_feature.parameters)
        serializer.is_valid(raise_exception=True)
        timer_data = serializer.validated_data

        today = timezone.localtime(timezone.now()).date()
        timer_service = LimitTimerService(timer_data, today)
        app_x190_history = timer_service.get_app_history_lte_days_after_190(application.id)
        if app_x190_history and timer_service.check_limit_utilization_rate(
            customer.id, account.id
        ):
            rest_of_countdown, show_pop_up = timer_service.calculate_rest_of_countdown(
                timezone.localtime(app_x190_history['cdate']).date()
            )
            if rest_of_countdown:
                context = dict(
                    rest_of_countdown_days=rest_of_countdown,
                    information=timer_data['information'],
                    pop_up_message=timer_data['pop_up_message'] if show_pop_up else None,
                )
                return context

    return None


def get_limit_validity_timer_campaign(account, api_version):
    """
    api_version:
    - v2: return campaign for transaction method
    - v3: return campaign for deeplink url
    """

    customer = account.customer
    available_limit = account.get_account_limit.available_limit
    now = timezone.localtime(timezone.now())
    campaigns_qs = LimitValidityTimer.objects.filter(
        is_active=True,
        start_date__lte=now,
        end_date__gte=now,
        minimum_available_limit__lte=available_limit,
    )

    if api_version == 'v2':
        campaigns_qs = campaigns_qs.filter(transaction_method_id__isnull=False)
    elif api_version == 'v3':
        campaigns_qs = campaigns_qs.filter(deeplink_url__isnull=False)
    else:
        raise ValueError("api_version only support values = v2 or v3")

    if not campaigns_qs:
        return None

    campaigns_qs = campaigns_qs.order_by('end_date', 'start_date')
    campaign = get_soonest_campaign_for_customer_from_redis(campaigns_qs, customer)
    if campaign:
        context = get_validity_campaign_timer_response(campaign)
        return context

    return campaign


def determine_neo_banner_by_app_version(application, app_version, is_android_device):

    is_ios_device = True if not is_android_device else False
    has_neo_banner = application.has_neo_banner(app_version, is_ios_device)

    if not is_android_device:
        return has_neo_banner

    # add new key-value as needed, mostly when having new template
    version_status_code = {
        # support for B_BUTTON and B_FAILED
        "<=8.5.1": [
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            ApplicationStatusCodes.ACTIVATION_AUTODEBET,
        ],
        # support for button_action_type
        "<=8.16.0": [
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusCodes.APPLICATION_DENIED,
        ],
        # support for bank_correction action
        "<=8.40.0": [
            ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        ],
    }

    for version in version_status_code.keys():
        if (
            app_version
            and semver.match(app_version, version)
            and application.status in version_status_code[version]
        ):
            has_neo_banner = False
            break

    return has_neo_banner

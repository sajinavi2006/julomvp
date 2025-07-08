import json
import math
import logging
from contextlib import contextmanager

from django.db import transaction
from django.db.models import Q, Avg
from django.utils import timezone
from django.conf import settings
from past.utils import old_div

from juloserver.account.constants import (
    AccountConstant,
    CreditMatrixType,
    TransactionType,
    LimitAdjustmentFactorConstant,
)
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLimitHistory,
    AccountLookup,
    AccountProperty,
    AccountPropertyHistory,
    CreditLimitGeneration,
    CurrentCreditMatrix,
)
from juloserver.account.services.account_related import get_account_property_by_account
from juloserver.account.utils import round_down_nearest
from juloserver.ana_api.services import check_positive_processed_income
from juloserver.ana_api.utils import check_app_cs_v20b
from juloserver.apiv2.models import (
    AutoDataCheck,
    PdClcsPrimeResult,
    PdCreditModelResult,
    PdWebModelResult,
    PdAffordabilityModelResult,
)
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.application_flow.services import (
    JuloOneService,
    check_application_version,
    is_experiment_application,
    still_in_experiment,
    ApplicationTagTracking,
    is_121_via_brick_revival,
    is_goldfish,
    is_eligible_lannister,
)
from juloserver.application_flow.services2 import AutoDebit
from juloserver.application_flow.services2.shopee_scoring import ShopeeWhitelist
from juloserver.application_flow.services2.bank_statement import BankStatementClient
from juloserver.customer_module.models import CustomerLimit
from juloserver.early_limit_release.constants import ReleaseTrackingType
from juloserver.entry_limit.constants import CreditLimitGenerationReason
from juloserver.julo.constants import ApplicationStatusCodes, FeatureNameConst, ExperimentConst
from juloserver.julo.formulas.underwriting import compute_affordable_payment
from juloserver.julo.models import (
    AffordabilityHistory,
    Application,
    ApplicationNote,
    CreditMatrix,
    CreditMatrixProductLine,
    CreditScore,
    FeatureSetting,
    FDCInquiry,
    FDCInquiryLoan,
    JobType,
    Loan,
    ExperimentSetting,
    BankStatementSubmit,
    BankStatementSubmitBalance,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.julocore.python2.utils import py2round
from juloserver.julovers.constants import JuloverConst
from juloserver.partnership.constants import PartnershipAccountLookup, PartnershipFeatureNameConst
from juloserver.partnership.models import PartnerLoanRequest, PartnershipFeatureSetting
from juloserver.rentee.services import RENTEE_RESIDUAL_PERCENTAGE
from juloserver.application_flow.constants import CacheKey
from juloserver.application_flow.services import (
    has_good_fdc_el_tag,
    check_success_submitted_bank_statement,
)
from juloserver.tokopedia.constants import TokoScoreConst
from juloserver.monitors.notifications import send_slack_bot_message

logger = logging.getLogger(__name__)


def get_credit_limit_reject_affordability_value(application, is_sonic_shortform=None):
    try:
        credit_limit_feature_setting = FeatureSetting.objects.cache(timeout=60 * 60 * 24).get(
            is_active=True,
            feature_name=FeatureNameConst.CREDIT_LIMIT_REJECT_AFFORDABILITY,
        )
    except FeatureSetting.objects.model.DoesNotExist:
        credit_limit_feature_setting = None

    credit_limit_reject_value = AccountConstant.CREDIT_LIMIT_REJECT_AFFORBABILITY_VALUE
    if credit_limit_feature_setting:
        if is_sonic_shortform:
            credit_limit_reject_value = credit_limit_feature_setting.parameters['limit_value_sf']
        else:
            credit_limit_reject_value = credit_limit_feature_setting.parameters['limit_value_lf']

    is_app_sonic = application.applicationhistory_set.filter(
        change_reason=JuloOneChangeReason.SONIC_AFFORDABILITY
    ).exists()
    if is_app_sonic:
        pamr = PdAffordabilityModelResult.objects.filter(application=application).last()
        if pamr and pamr.affordability_threshold:
            credit_limit_reject_value = pamr.affordability_threshold

    return credit_limit_reject_value


def _get_limit_adjustment_factor(pgood):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LIMIT_ADJUSTMENT_FACTOR, is_active=True
    ).last()
    if fs:
        if pgood > fs.parameters['high']['min pgood']:
            return fs.parameters['high']['factor']
        elif pgood > fs.parameters['medium']['min pgood']:
            return fs.parameters['medium']['factor']
        elif pgood > fs.parameters['low']['min pgood']:
            return fs.parameters['low']['factor']
    else:
        if pgood > LimitAdjustmentFactorConstant.HIGH_MIN_PGOOD:
            return LimitAdjustmentFactorConstant.HIGH_FACTOR
        elif pgood > LimitAdjustmentFactorConstant.MEDIUM_MIN_PGOOD:
            return LimitAdjustmentFactorConstant.MEDIUM_FACTOR
        elif pgood > LimitAdjustmentFactorConstant.LOW_MIN_PGOOD:
            return LimitAdjustmentFactorConstant.LOW_FACTOR


# returns maxlimit, setlimit
def generate_credit_limit(application):
    from juloserver.julo.services import process_application_status_change
    from juloserver.application_flow.services import (
        check_good_fdc_bypass,
        check_good_fdc,
        check_bpjs_found,
        is_c_plus_score,
        check_click_pass,
        is_offline_activation_low_pgood,
        clik_model_decision,
        eligible_entry_level,
    )
    from juloserver.tokopedia.services.common_service import is_success_revive_by_tokoscore
    from juloserver.tokopedia.services.credit_matrix_service import build_credit_matrix_parameters
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.entry_limit.services import is_entry_level_type

    logger.info({"application_id": application.id, "message": "Generate credit limit, starting"})

    app_sonic = application.applicationhistory_set.filter(
        change_reason=JuloOneChangeReason.SONIC_AFFORDABILITY
    )

    revive_good_fdc = application.applicationhistory_set.filter(
        change_reason=JuloOneChangeReason.REVIVE_BY_GOOD_FDC
    )

    affordability_history = AffordabilityHistory.objects.filter(application=application).last()
    affordability_value = affordability_history.affordability_value

    is_sonic_shortform = check_application_version(application)
    credit_limit_reject_value = get_credit_limit_reject_affordability_value(
        application, is_sonic_shortform
    )
    is_affordable = True

    julo_one_service = JuloOneService()
    input_params = julo_one_service.construct_params_for_affordability(application)
    sonic_affordability_value = None
    if app_sonic:
        sonic_affordability_value = affordability_value
        is_monthly_income_changed = ApplicationNote.objects.filter(
            application_id=application.id, note_text='change monthly income by bank scrape model'
        ).last()
        if is_monthly_income_changed and check_positive_processed_income(application.id):
            affordability_result = compute_affordable_payment(**input_params)
            affordability_value = affordability_result['affordable_payment']

    if affordability_value < credit_limit_reject_value or (
        sonic_affordability_value and sonic_affordability_value < credit_limit_reject_value
    ):
        is_affordable = False

    bank_statement_success = check_success_submitted_bank_statement(application)

    lbs_bypass_setting = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConst.LBS_130_BYPASS
    ).last()
    min_afford_bp_quota = (
        lbs_bypass_setting.criteria.get("limit_total_of_application_min_affordability", 0)
        if lbs_bypass_setting
        else 0
    )
    bypass_min_affordability = False

    redis_client = get_redis_client()
    min_afford_bp_count = redis_client.get(CacheKey.LBS_MIN_AFFORDABILITY_BYPASS_COUNTER)
    if not min_afford_bp_count:
        redis_client.set(CacheKey.LBS_MIN_AFFORDABILITY_BYPASS_COUNTER, 0)
        min_afford_bp_count = 0
    else:
        min_afford_bp_count = int(min_afford_bp_count)
    if not is_affordable and bank_statement_success and min_afford_bp_count < min_afford_bp_quota:
        logger.info(
            {
                "application_id": application.id,
                "message": "Generate credit limit, bypass min affordability",
            }
        )
        redis_client.increment(CacheKey.LBS_MIN_AFFORDABILITY_BYPASS_COUNTER)
        min_afford_bp_quota_left = min_afford_bp_quota - min_afford_bp_count - 1
        if min_afford_bp_quota_left in (0, 25, 50, 75, 100):
            slack_channel = "#alerts-backend-onboarding"
            mentions = "<@U04EDJJTX6Y> <@U040BRBR5LM>\n"
            title = ":alert: ===LBS Bypass Quota Alert=== :alert: \n"
            message = (
                "Minimum Affordability Bypass Quota : " + str(min_afford_bp_quota_left) + " left\n"
            )
            text = mentions + title + message
            if settings.ENVIRONMENT != 'prod':
                text = "*[" + settings.ENVIRONMENT + " notification]*\n" + text
            send_slack_bot_message(slack_channel, text)
        bypass_min_affordability = True

    if not is_affordable and not bypass_min_affordability:
        if not application.is_grab():
            if bank_statement_success:
                bank_statement = BankStatementClient(application)
                bank_statement.update_tag_to_failed()
            new_status_code = ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER
            change_reason = 'Affordability value lower than threshold'
            process_application_status_change(
                application.id, new_status_code, change_reason=change_reason
            )

        logger.info(
            {"application_id": application.id, "message": "Generate credit limit, not affordable"}
        )
        return 0, 0
    else:
        # NIK and dukcapil Validation for fraud
        from juloserver.julo.utils import verify_nik

        valid_nik = verify_nik(application.ktp)
        if not valid_nik:
            new_status_code = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
            change_reason = 'Invalid NIK and not Dukcapil Eligible'
            process_application_status_change(
                application.id, new_status_code, change_reason=change_reason
            )
            logger.info(
                {
                    "application_id": application.id,
                    "message": "Generate credit limit, not valid_nik",
                }
            )
            return 0, 0

        custom_matrix_parameters = get_credit_matrix_parameters(application)
        if not custom_matrix_parameters:
            logger.info(
                {
                    "application_id": application.id,
                    "message": "Generate credit limit, has no custom matrix parameters",
                }
            )
            return 0, 0
        transaction_type = get_transaction_type()
        credit_matrix = None
        shopee_whitelist = ShopeeWhitelist(application)
        revive_semi_good = is_c_plus_score(application)
        revive_brick_x105 = is_121_via_brick_revival(application)

        eligible_goldfish = is_goldfish(application)
        eligible_el = eligible_entry_level(application.id)
        eligible_lannister = is_eligible_lannister(application)
        lannister_setting = ExperimentSetting.objects.filter(
            code=ExperimentConst.LANNISTER_EXPERIMENT, is_active=True
        ).last()
        lannister_quota = 0 if not lannister_setting else lannister_setting.criteria.get("limit", 0)
        action_data = None if not lannister_setting else json.loads(lannister_setting.action)
        lannister_count = 0 if not action_data else action_data["count"]

        if eligible_goldfish and not is_entry_level_type(application):
            cm_parameter = 'feature:is_goldfish'
            custom_matrix_parameters["credit_matrix_type"] = CreditMatrixType.JULO1
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters},
                transaction_type,
                parameter=Q(parameter=cm_parameter),
            )

            logger_data = {
                "message": "got credit matrix, is goldfish",
                "application": application.id,
            }
            if credit_matrix:
                logger_data["credit_matrix"] = credit_matrix.id
            logger.info(logger_data)

        elif (
            lannister_setting
            and eligible_lannister
            and lannister_count < lannister_quota
            and not is_entry_level_type(application)
            and not check_success_submitted_bank_statement(application)
        ):
            experiment_group = lannister_setting.criteria.get("experiment_group", '')
            lannister_application_ids = (
                [int(x) for x in experiment_group.split(',')] if experiment_group else []
            )
            lannister_cm_parameter = lannister_setting.criteria.get(
                "cm_parameter", 'feature:is_goldfish'
            )
            if application.id % 10 in lannister_application_ids:
                credit_matrix = get_credit_matrix(
                    {**custom_matrix_parameters},
                    transaction_type,
                    parameter=Q(parameter=lannister_cm_parameter),
                )
                logger_data = {
                    "message": "got credit matrix, is {}".format(lannister_cm_parameter),
                    "application": application.id,
                }
                if credit_matrix:
                    logger_data["credit_matrix"] = credit_matrix.id
                logger.info(logger_data)
                application_tag_tracking_task.delay(
                    application.id, None, None, None, 'is_lannister', 1
                )
                lannister_count += 1
                action_data['count'] = lannister_count
                lannister_setting.update_safely(action=json.dumps(action_data))
                lannister_quota_left = lannister_quota - lannister_count
                if lannister_quota_left in (0, 25, 50, 75, 100):
                    slack_channel = "#alerts-backend-onboarding"
                    mentions = "<@U04EDJJTX6Y> <@U040BRBR5LM>\n"
                    title = ":alert: ===Lannister Quota Alert=== :alert: \n"
                    message = "Lannister Quota : " + str(lannister_quota_left) + " left\n"
                    text = mentions + title + message
                    if settings.ENVIRONMENT != 'prod':
                        text = "*[" + settings.ENVIRONMENT + " notification]*\n" + text
                    send_slack_bot_message(slack_channel, text)
            else:
                credit_matrix = get_credit_matrix(custom_matrix_parameters, transaction_type)
                logger_data = {
                    "message": "got credit matrix, regular",
                    "application": application.id,
                }
                if credit_matrix:
                    logger_data["credit_matrix"] = credit_matrix.id
                logger.info(logger_data)
                application_tag_tracking_task.delay(
                    application.id, None, None, None, 'is_lannister', 0
                )
        elif revive_brick_x105:
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters},
                transaction_type,
            )
            logger.info(
                {"message": "got credit matrix, revive_brick_x105", "application": application.id}
            )
        elif (
            clik_model_decision(application)
            and is_c_plus_score(application)
        ):
            custom_matrix_parameters.pop("credit_matrix_type", None)
            cm_parameter = 'feature:is_clik_model'
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters},
                transaction_type,
                parameter=Q(parameter=cm_parameter),
            )
            logger.info(
                {"message": "got credit matrix, CLIK Model Swap In", "application": application.id}
            )
        elif revive_semi_good:
            custom_matrix_parameters.pop("credit_matrix_type", None)
            cm_parameter = 'feature:is_semi_good'
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters},
                transaction_type,
                parameter=Q(parameter=cm_parameter),
            )
            logger.info(
                {"message": "got credit matrix, revive_semi_good", "application": application.id}
            )
        elif shopee_whitelist.has_success_tags:

            if shopee_whitelist.has_anomaly():
                shopee_whitelist.reject_application()
            else:
                additional_parameters = shopee_whitelist.build_additional_credit_matrix_parameters()
                credit_matrix = get_credit_matrix(
                    {**custom_matrix_parameters, **additional_parameters},
                    transaction_type,
                    parameter=Q(parameter=ShopeeWhitelist.CREDIT_MATRIX_PARAMETER),
                )
            logger.info(
                {
                    "message": "got credit matrix, success Shopee whitelist",
                    "application": application.id,
                }
            )
        elif AutoDebit(application).has_pending_tag or check_bpjs_found(application):
            custom_matrix_parameters.pop("credit_matrix_type", None)
            custom_matrix_parameters["credit_matrix_type"] = "julo1_entry_level"
            credit_matrix = get_credit_matrix(
                custom_matrix_parameters,
                transaction_type,
            )
            logger.info(
                {
                    "message": "got credit matrix, pending autodebit or check BPJS",
                    "application": application.id,
                }
            )
        elif (
            not eligible_el
            and (
                check_good_fdc_bypass(application)
                or is_offline_activation_low_pgood(application)
            )
        ):
            cm_parameter = 'feature:good_fdc_bypass'
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters},
                transaction_type,
                parameter=Q(parameter=cm_parameter),
            )
            logger.info(
                {"message": "got credit matrix, good FDC bypass", "application": application.id}
            )
        elif is_success_revive_by_tokoscore(application):
            # check is success revive by tokoscore to x120 and will use CM Tokoscore
            additional_parameters = build_credit_matrix_parameters(application.id)
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters, **additional_parameters},
                transaction_type,
                parameter=Q(parameter=TokoScoreConst.CREDIT_MATRIX_PARAMETER),
            )
            logger.info({"message": "got credit matrix, tokoscore", "application": application.id})
        elif bank_statement_success:
            cm_parameter = 'feature:leverage_bank_statement'
            credit_matrix = get_credit_matrix(
                {**custom_matrix_parameters},
                transaction_type,
                parameter=Q(parameter=cm_parameter),
            )
            logger_data = {
                "message": "got credit matrix, bank_statement_success",
                "application": application.id,
            }
            if credit_matrix:
                logger_data["credit_matrix"] = credit_matrix.id
            logger.info(logger_data)
        else:
            credit_matrix = get_credit_matrix(custom_matrix_parameters, transaction_type)
            logger_data = {"message": "got credit matrix, regular", "application": application.id}
            if credit_matrix:
                logger_data["credit_matrix"] = credit_matrix.id
            logger.info(logger_data)

        if credit_matrix is not None:
            logger.info({"message": "got credit matrix, found", "credit_matrix": credit_matrix.id})
            credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
                credit_matrix=credit_matrix
            ).last()
            credit_model_result = get_credit_model_result(application)
            pgood = (
                getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
            )

            limit_adjustment_factor = _get_limit_adjustment_factor(pgood)

            # credit limit calculation logic
            credit_limit_result = calculate_credit_limit(
                credit_matrix_product_line, affordability_value, limit_adjustment_factor
            )

            log_data = {
                'simple_limit': credit_limit_result['simple_limit'],
                'reduced_limit': credit_limit_result['reduced_limit'],
                'limit_adjustment_factor': credit_limit_result['limit_adjustment_factor'],
                'max_limit (pre-matrix)': credit_limit_result['simple_limit_rounded'],
                'set_limit (pre-matrix)': credit_limit_result['reduced_limit_rounded'],
            }

            reason = "130 Credit Limit Generation"

            from juloserver.entry_limit.services import EntryLevelLimitProcess

            entry_limit_process = EntryLevelLimitProcess(application.id, application=application)
            entry_limit = entry_limit_process.run_entry_level_limit_eligible()

            if not eligible_el:
                if entry_limit and not revive_semi_good:
                    credit_limit_result['max_limit'] = entry_limit.entry_level_limit
                    credit_limit_result['set_limit'] = entry_limit.entry_level_limit
                    reason = CreditLimitGenerationReason.ENTRY_LEVEL_LIMIT

            if eligible_goldfish and not entry_limit:
                from juloserver.moengage.services.use_cases import (
                    send_user_attributes_to_moengage_for_goldfish,
                )

                application_tag_tracking_task.delay(
                    application.id, None, None, None, 'is_goldfish', 1
                )
                send_user_attributes_to_moengage_for_goldfish.delay(application.id, True)

            # check turbo limit here
            from juloserver.streamlined_communication.services import customer_have_upgrade_case

            if (
                customer_have_upgrade_case(application.customer, application)
                and not revive_semi_good
            ):
                turbo_application = Application.objects.get_or_none(
                    customer=application.customer,
                    application_status_id=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
                )
                credit_limit_turbo = CreditLimitGeneration.objects.filter(
                    application_id=turbo_application.id
                ).last()
                credit_limit_upgrade = credit_limit_turbo.set_limit

                if credit_limit_result['set_limit'] > credit_limit_turbo.set_limit:
                    credit_limit_upgrade = credit_limit_result['set_limit']

                credit_limit_result['max_limit'] = credit_limit_upgrade
                credit_limit_result['set_limit'] = credit_limit_upgrade
                reason = "130 Credit Limit Generation Turbo Upgrade"

            if bank_statement_success and not revive_semi_good:
                bank_statement_submit = BankStatementSubmit.objects.filter(
                    application_id=application.id
                ).last()
                bank_statement_submit_balances = BankStatementSubmitBalance.objects.filter(
                    bank_statement_submit=bank_statement_submit
                )
                average_values = bank_statement_submit_balances.aggregate(
                    avg_eom_balance=Avg('eom_balance'),
                    avg_average_eod_balance=Avg('average_eod_balance'),
                )
                avg_eom_balance = average_values['avg_eom_balance']
                avg_average_eod_balance = average_values['avg_average_eod_balance']
                balance = max(avg_eom_balance, avg_average_eod_balance)
                leverage_bank_statement_setting = ExperimentSetting.objects.filter(
                    is_active=True, code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT
                ).last()
                max_limit = 5000000
                min_rejection_limit = 150000
                balance_multiplier = 1.5
                if leverage_bank_statement_setting:
                    max_limit = leverage_bank_statement_setting.criteria['max_limit']
                    min_rejection_limit = leverage_bank_statement_setting.criteria[
                        'credit_limit_threshold'
                    ]
                    balance_multiplier = leverage_bank_statement_setting.criteria[
                        'credit_limit_constant'
                    ]
                given_limit = math.floor(balance * balance_multiplier / 50000) * 50000
                if given_limit < min_rejection_limit:
                    logger.info(
                        {
                            "application_id": application.id,
                            "message": "Generate credit limit, given_limit < min_rejection_limit",
                        }
                    )
                    return 0, 0
                elif given_limit > max_limit:
                    given_limit = max_limit
                credit_limit_result['max_limit'] = max_limit
                credit_limit_result['set_limit'] = given_limit

            if not eligible_el:
                if (
                    (revive_good_fdc or check_good_fdc_bypass(application))
                    and not revive_semi_good
                ):
                    credit_limit_result['max_limit'] = 3000000
                    credit_limit_result['set_limit'] = 3000000

                if check_good_fdc(application):
                    limit = 3000000

                    if credit_limit_result['max_limit'] >= limit:
                        limit = credit_limit_result['max_limit']

                    credit_limit_result['set_limit'] = limit
                    credit_limit_result['max_limit'] = limit

                if check_click_pass(application):
                    credit_limit_result['set_limit'] = 1500000
                    credit_limit_result['max_limit'] = 1500000

            if is_offline_activation_low_pgood(application):
                setting = ExperimentSetting.objects.get_or_none(
                    code="offline_activation_referral_code"
                )
                if setting:
                    limit = setting.criteria.get('minimum_limit')
                    credit_limit_result['set_limit'] = limit
                    credit_limit_result['max_limit'] = limit

            log_data = {
                'simple_limit': credit_limit_result['simple_limit'],
                'reduced_limit': credit_limit_result['reduced_limit'],
                'limit_adjustment_factor': credit_limit_result['limit_adjustment_factor'],
                'max_limit (pre-matrix)': credit_limit_result['simple_limit_rounded'],
                'set_limit (pre-matrix)': credit_limit_result['reduced_limit_rounded'],
            }

            # store generated credit limit and values
            store_credit_limit_generated(
                application,
                None,
                credit_matrix,
                affordability_history,
                credit_limit_result['max_limit'],
                credit_limit_result['set_limit'],
                json.dumps(log_data),
                reason,
            )

            logger.info(
                {
                    "application_id": application.id,
                    "message": "Generate credit limit, found",
                    "max_limit": credit_limit_result['max_limit'],
                    "set_limit": credit_limit_result['set_limit'],
                }
            )
            return credit_limit_result['max_limit'], credit_limit_result['set_limit']

    logger.info({"application_id": application.id, "message": "Generate credit limit, last 0"})
    return 0, 0


def calculate_credit_limit(
    credit_matrix_product_line, affordability_value, limit_adjustment_factor
):
    max_duration = credit_matrix_product_line.max_duration
    interest_rate = credit_matrix_product_line.interest
    max_loan_amount = credit_matrix_product_line.max_loan_amount

    simple_limit = int(
        py2round(
            old_div((affordability_value * max_duration), (1 + (max_duration * interest_rate)))
        )
    )
    reduced_limit = int(py2round(simple_limit * limit_adjustment_factor))

    simple_limit_rounded = (
        round_down_nearest(simple_limit, 1000000)
        if simple_limit > 5000000
        else round_down_nearest(simple_limit, 500000)
    )
    reduced_limit_rounded = (
        round_down_nearest(reduced_limit, 1000000)
        if reduced_limit > 5000000
        else round_down_nearest(reduced_limit, 500000)
    )

    try:
        credit_limit_rounding_value = FeatureSetting.objects.cache(timeout=60 * 60 * 24).get(
            is_active=True,
            feature_name=FeatureNameConst.CREDIT_LIMIT_ROUNDING_DOWN_VALUE,
        )
    except FeatureSetting.objects.model.DoesNotExist:
        credit_limit_rounding_value = None

    max_limit = min(simple_limit_rounded, max_loan_amount)
    set_limit = min(reduced_limit_rounded, max_loan_amount)
    if set_limit < 500000 and credit_limit_rounding_value:
        round_value = int(credit_limit_rounding_value.parameters['rounding_down_value'])
        if set_limit > round_value:
            set_limit = round_value

    credit_limit_result = {
        'simple_limit': simple_limit,
        'reduced_limit': reduced_limit,
        'simple_limit_rounded': simple_limit_rounded,
        'reduced_limit_rounded': reduced_limit_rounded,
        'max_limit': max_limit,
        'set_limit': set_limit,
        'limit_adjustment_factor': limit_adjustment_factor,
    }

    return credit_limit_result


def store_credit_limit_generated(
    application,
    account,
    credit_matrix,
    affordability_history,
    max_limit,
    set_limit,
    log_data,
    reason,
):
    CreditLimitGeneration.objects.create(
        application=application,
        account=account,
        credit_matrix=credit_matrix,
        affordability_history=affordability_history,
        max_limit=max_limit,
        set_limit=set_limit,
        log=log_data,
        reason=reason,
    )


def store_related_data_for_generate_credit_limit(application, max_limit, set_limit):
    from juloserver.julo.formulas import determine_first_due_dates_by_payday

    with transaction.atomic():
        today = timezone.localtime(timezone.now())
        if application.is_julover():
            cycle_day = JuloverConst.DEFAULT_CYCLE_PAYDAY
        else:
            first_due_date = determine_first_due_dates_by_payday(
                application.payday,
                today,
                application.product_line_code,
            )
            cycle_day = first_due_date.day

        last_affordability = AffordabilityHistory.objects.filter(application=application).last()
        last_credit_score = CreditScore.objects.filter(application=application).last()
        account_lookup = AccountLookup.objects.filter(workflow=application.workflow).last()
        account = Account.objects.create(
            customer=application.customer,
            status_id=AccountConstant.STATUS_CODE.inactive,
            account_lookup=account_lookup,
            cycle_day=cycle_day,
        )
        AccountLimit.objects.create(
            account=account,
            max_limit=max_limit,
            set_limit=set_limit,
            latest_affordability_history=last_affordability,
            latest_credit_score=last_credit_score,
        )
        customer_limit = CustomerLimit.objects.filter(customer=application.customer).last()
        if not customer_limit:
            CustomerLimit.objects.create(customer=application.customer, max_limit=max_limit)
        application.update_safely(account=account)


def get_credit_matrix_parameters(application):
    if application.is_julover():
        return {
            'min_threshold__lte': AccountConstant.PGOOD_CUTOFF,
            'max_threshold__gte': AccountConstant.PGOOD_CUTOFF,
            'credit_matrix_type': get_credit_matrix_type(application),
            'is_salaried': True,
            'is_premium_area': True,
        }

    credit_score = CreditScore.objects.filter(application=application).last()
    if credit_score is None:
        return None

    credit_model_result = get_credit_model_result(application)
    if credit_model_result is None:
        return None

    is_experiment = False
    probability_fpd = (
        getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
    )
    is_salaried = get_salaried(application.job_type)
    is_proven = get_is_proven()
    is_premium_area = is_inside_premium_area(application)
    is_fdc = credit_model_result.has_fdc
    if still_in_experiment('ExperimentCreditMatrix', application):
        if is_experiment_application(application.id, 'ExperimentCreditMatrix'):
            if credit_score.score:
                cm_version = (
                    CreditMatrix.objects.exclude(version__isnull=True).values('version').last()
                )
                experiment_cm = CreditMatrix.objects.filter(
                    score=credit_score.score,
                    credit_matrix_type=CreditMatrixType.JULO1_LIMIT_EXP,
                    version=cm_version['version'],
                    score_tag=credit_score.score_tag,
                    is_premium_area=is_premium_area,
                    is_salaried=is_salaried,
                    is_fdc=is_fdc,
                )
                if experiment_cm:
                    is_experiment = True

    """
    Partnership Custom credit matrix for product leadgen
    only for application x130
    """
    partnership_cm_credit_matrix = None
    if (
        application.is_partnership_app()
        and application.status == ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
    ):
        config = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PARTNERSHIP_LEADGEN_CONFIG_CREDIT_MATRIX,
            is_active=True,
        ).last()
        if config and config.parameters:
            partner_config = config.parameters.get('partners', {}).get(application.partner.name)
            if partner_config and partner_config.get('is_active'):
                partnership_cm_credit_matrix = partner_config.get('credit_matrix_type')

    credit_matrix_type = None
    if partnership_cm_credit_matrix:
        # Partnership
        credit_matrix_type = partnership_cm_credit_matrix
        ApplicationNote.objects.create(
            note_text="CreditLimitGeneration using credit matrix type julo1_leadgen",
            application_id=application.id,
            application_history_id=None,
        )
    else:
        # J1
        credit_matrix_type = get_credit_matrix_type(application, is_proven, is_experiment)

    credit_matrix_parameters = dict(
        min_threshold__lte=probability_fpd,
        max_threshold__gte=probability_fpd,
        credit_matrix_type=credit_matrix_type,
        is_salaried=is_salaried,
        is_premium_area=is_premium_area,
        is_fdc=is_fdc,
    )
    if credit_matrix_parameters:
        return credit_matrix_parameters
    return None


def get_credit_matrix(parameters, transaction_type, parameter: Q = None):
    credit_matrix_ids = CurrentCreditMatrix.objects.filter(
        transaction_type=transaction_type
    ).values('credit_matrix_id')
    query_set = CreditMatrix.objects.filter(
        id__in=credit_matrix_ids,
        version__isnull=False,
        transaction_type=transaction_type,
    ).filter(**parameters)

    # Since the parameter is not filled, and we want to add some filter in credit matrix.
    # we prevent regular query (without parameter) to get credit matrix that have parameter on it.
    if parameter is None:
        query_set = query_set.filter(Q(parameter__isnull=True) | Q(parameter=''))
    else:
        query_set = query_set.filter(parameter)

    credit_matrix = query_set.order_by('-version', '-max_threshold').first()

    return credit_matrix


def get_credit_matrix_type(application, is_proven=False, is_experiment=False):
    from juloserver.entry_limit.services import is_entry_level_type
    from juloserver.application_flow.services import (
        eligible_entry_level,
        is_entry_level_swapin,
    )

    if application.is_julo_one_ios():
        return CreditMatrixType.JULO_ONE_IOS

    # Julover
    if application.is_julover():
        return CreditMatrixType.JULOVER

    if application.is_julo_starter():
        return CreditMatrixType.JULO_STARTER

    if (
        is_entry_level_type(application)
        or eligible_entry_level(application.id)
        or is_entry_level_swapin(application)
    ):
        return CreditMatrixType.JULO1_ENTRY_LEVEL
    if is_proven:
        return CreditMatrixType.JULO1_PROVEN
    else:
        is_repeated_mtl = is_repeated_mtl_customer(application)
        if is_repeated_mtl:
            return CreditMatrixType.JULO1_REPEAT_MTL

    # JULO1 Limit Experiment
    if is_experiment:
        return CreditMatrixType.JULO1_LIMIT_EXP
    # Default JULO1
    return CreditMatrixType.JULO1


def is_repeated_mtl_customer(application):
    if application.product_line_code not in ProductLineCodes.mtl():
        return False

    repeat_time = (
        Loan.objects.get_queryset()
        .paid_off()
        .filter(
            customer=application.customer,
            application__product_line__product_line_code__in=ProductLineCodes.mtl(),
        )
        .count()
    )
    return True if repeat_time > 0 else False


def get_credit_model_result(application):
    credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'

    # this will be the validation for application that forced to filled the partner
    # (context) this will cover application with partner referral code or partner onelink
    if application.is_force_filled_partner_app():
        credit_model_result = PdCreditModelResult.objects.filter(
            application_id=application.id, credit_score_type=credit_score_type
        ).last()
        if credit_model_result:
            logger.info(
                {
                    'action': 'partnership_onelink_or_referral_code_get_credit_model_result',
                    'application_id': application.id,
                    'partner_id': application.partner_id,
                    'message': 'getting j1 credit model result',
                }
            )
            return credit_model_result

        credit_model_result = PdWebModelResult.objects.filter(application_id=application.id).last()
        logger.info(
            {
                'action': 'partnership_onelink_or_referral_code_get_credit_model_result',
                'application_id': application.id,
                'partner_id': application.partner_id,
                'message': 'getting webapp credit model result',
            }
        )
        return credit_model_result

    if not application.is_web_app() and not application.is_partnership_app():
        credit_model_result = PdCreditModelResult.objects.filter(
            application_id=application.id, credit_score_type=credit_score_type
        ).last()

        return credit_model_result

    # web app
    credit_model_result = PdWebModelResult.objects.filter(application_id=application.id).last()

    return credit_model_result


def store_account_property(application, set_limit):
    from juloserver.entry_limit.services import is_entry_level_type

    is_proven = get_is_proven()
    credit_model_result = get_credit_model_result(application)
    if not application.is_grab():
        pgood = getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
        p0 = credit_model_result.probability_fpd
    else:
        pgood = 0.0
        p0 = 0.0

    input_params = dict(
        account=application.account,
        pgood=pgood,
        p0=p0,
        is_salaried=get_salaried(application.job_type),
        is_proven=is_proven,
        is_premium_area=is_inside_premium_area(application),
        proven_threshold=get_proven_threshold(set_limit),
        voice_recording=get_voice_recording(is_proven),
        concurrency=True,
        is_entry_level=is_entry_level_type(application),
    )

    account_property = AccountProperty.objects.get_or_none(account=application.account)
    if not account_property:
        account_property = AccountProperty.objects.create(**input_params)
    else:
        if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
            return

        account_property.update_safely(**input_params)

    # create history
    store_account_property_history(input_params, account_property)


def store_account_property_history(input_params, account_property=None, account_property_old=None):
    bulk_create_data = []
    for key, value in list(input_params.items()):
        if key == "account":
            continue
        data = AccountPropertyHistory(
            account_property=account_property,
            field_name=key,
            value_old="" if account_property_old is None else account_property_old[key],
            value_new=value,
        )

        bulk_create_data.append(data)

    AccountPropertyHistory.objects.bulk_create(bulk_create_data)


def get_salaried(job_type):
    get_job_type = JobType.objects.get_or_none(job_type=job_type)
    if not get_job_type:
        return False
    return get_job_type.is_salaried


def is_inside_premium_area(application):
    auto_data_check = AutoDataCheck.objects.filter(
        application_id=application.id, data_to_check='inside_premium_area'
    ).last()
    if not auto_data_check:
        return False

    return auto_data_check.is_okay


def get_is_proven():
    return AccountConstant.DEFAULT_IS_PROVEN


def get_proven_threshold(set_limit):
    proven_threshold = max(
        (set_limit * AccountConstant.PROVEN_THRESHOLD_CALCULATION_PERCENTAGE),
        AccountConstant.PROVEN_THRESHOLD_CALCULATION_LIMIT,
    )
    return proven_threshold


def get_voice_recording(is_proven=False):
    if is_proven:
        return False
    return True


def get_transaction_type(credit_matrix_id=None):
    if credit_matrix_id:
        current_credtit_matrix = CurrentCreditMatrix.objects.filter(
            credit_matrix_id=credit_matrix_id
        ).last()
        if current_credtit_matrix:
            return current_credtit_matrix.transaction_type
    return TransactionType.DEFUALT_TRANSACTION_TYPE


def check_bypass_pgood_for_credit_matrix(application, account_property):
    is_shopee_active = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.SHOPEE_WHITELIST_SCORING, is_active=True
    )
    if not is_shopee_active:
        return account_property.pgood

    sw = ShopeeWhitelist(application=application)
    pgood_default = AccountConstant.PGOOD_BYPASS_CREDIT_MATRIX
    good_fdc_bypass_fs = is_shopee_active.parameters.get('good_fdc_bypass', {}).get('is_active')
    submitted_bank_bypass_fs = is_shopee_active.parameters.get(
        'submitted_bank_statement_bypass', {}
    ).get('is_active')

    if account_property.pgood < pgood_default:
        if (
            sw.has_success_tags
            or (good_fdc_bypass_fs and has_good_fdc_el_tag(application))
            or (submitted_bank_bypass_fs and check_success_submitted_bank_statement(application))
        ):
            account_property.pgood = pgood_default

    return account_property.pgood


def get_credit_matrix_parameters_from_account_property(application, account_property):
    if not account_property:
        return None
    credit_matrix_type = get_credit_matrix_type(application, account_property.is_proven)

    pgood = check_bypass_pgood_for_credit_matrix(application, account_property)

    credit_matrix_parameters = dict(
        min_threshold__lte=pgood,
        max_threshold__gte=pgood,
        credit_matrix_type=credit_matrix_type,
        is_salaried=account_property.is_salaried,
        is_premium_area=account_property.is_premium_area,
    )
    if credit_matrix_parameters:
        return credit_matrix_parameters
    return None


def get_is_concurrency(application):
    return application.customer.loan_set.filter(loan_status=LoanStatusCodes.PAID_OFF).exists()


# need to called in transaction atomic
def update_available_limit(loan):
    from juloserver.balance_consolidation.services import ConsolidationVerificationStatusService
    from juloserver.early_limit_release.services import calculate_loan_amount_for_early_limit
    from juloserver.early_limit_release.services import update_or_create_release_tracking

    change_limit_amount = get_change_limit_amount(loan)
    account = loan.account
    account_limit = AccountLimit.objects.select_for_update().get(account=account)

    if loan.status in AccountConstant.LIMIT_INCREASING_LOAN_STATUSES:
        if account.account_lookup.name == 'DANA' and loan.status == LoanStatusCodes.PAID_OFF:
            return

        # This part of code is handled by partnership team
        # for merchant financing product
        if (
            account.account_lookup.name == PartnershipAccountLookup.MERCHANT_FINANCING
            and loan.status == LoanStatusCodes.PAID_OFF
        ):
            partner_name = (
                PartnerLoanRequest.objects.filter(loan=loan)
                .values_list('partner__name', flat=True)
                .first()
            )
            if partner_name:
                mf_limit_replenishment_fs = PartnershipFeatureSetting.objects.filter(
                    feature_name=PartnershipFeatureNameConst.MERCHANT_FINANCING_LIMIT_REPLENISHMENT,
                    is_active=True,
                ).first()
                if mf_limit_replenishment_fs and mf_limit_replenishment_fs.parameters.get(
                    partner_name
                ):
                    return

        # recalculate the change_limit_amount for early limit release
        change_limit_amount = calculate_loan_amount_for_early_limit(loan, change_limit_amount)

        new_available_limit = account_limit.available_limit + change_limit_amount
        new_used_limit = account_limit.used_limit - change_limit_amount

        if loan.status == LoanStatusCodes.PAID_OFF and change_limit_amount > 0:
            update_or_create_release_tracking(
                loan.id,
                account.id,
                change_limit_amount,
                tracking_type=ReleaseTrackingType.LAST_RELEASE,
            )

    elif loan.status in AccountConstant.LIMIT_DECREASING_LOAN_STATUSES:
        new_available_limit = account_limit.available_limit - change_limit_amount
        new_used_limit = account_limit.used_limit + change_limit_amount
    else:
        return
    account_limit.update_safely(available_limit=new_available_limit, used_limit=new_used_limit)

    # handle limit for balance consolidation
    if loan.is_balance_consolidation and loan.status in LoanStatusCodes.J1_failed_loan_status():
        consolidation_service = ConsolidationVerificationStatusService(
            loan.balanceconsolidationverification, account
        )
        verification = consolidation_service.consolidation_verification
        amount_changed = verification.account_limit_histories['upgrade']['amount_changed']
        consolidation_service.handle_after_status_approved(amount_changed, is_upgrade=False)


@contextmanager
def record_account_limit_history(application, field, old_values):
    credit_score = CreditScore.objects.filter(application=application).last()
    affordability_history = AffordabilityHistory.objects.filter(application=application).last()
    account_limit_history = AccountLimitHistory()
    account_limit_history.field_name = field
    account_limit_history.value_old = old_values
    account_limit_history.affordability_history = affordability_history
    account_limit_history.credit_score = credit_score
    try:
        yield account_limit_history
    finally:
        account_limit_history.save()


def update_related_data_for_generate_credit_limit(application, max_limit, set_limit):
    with transaction.atomic():
        last_affordability = AffordabilityHistory.objects.filter(application=application).last()
        last_credit_score = CreditScore.objects.filter(application=application).last()
        account = application.customer.account_set.last()
        account_limit = account.accountlimit_set.last()
        account_limit.update_safely(
            max_limit=max_limit,
            set_limit=set_limit,
            latest_affordability_history=last_affordability,
            latest_credit_score=last_credit_score,
        )
        customer_limit = application.customer.customerlimit
        customer_limit.update_safely(max_limit=max_limit)
        application.update_safely(account=account)


def get_change_limit_amount(loan):
    change_limit_amount = loan.loan_amount
    if hasattr(loan, 'paymentdeposit'):
        change_limit_amount = int(loan.loan_amount * RENTEE_RESIDUAL_PERCENTAGE)

    return change_limit_amount


def update_credit_limit_with_clcs(application):
    """
    Recalculate user's credit limit when their clcs/b-score is updated
    Lock, see if their CLCS prime score has been updated, if yes --
    Add a new row in credit_limit_generation & update account limit
    -- returns (old_set_limit, new_set_limit)
    """
    from juloserver.loan.services.loan_related import (
        get_credit_matrix_and_credit_matrix_product_line,
    )

    def check_for_new_clcs_score():
        last_credit_generation = CreditLimitGeneration.objects.filter(
            application=application
        ).last()

        credit_generated_date = timezone.localtime(last_credit_generation.cdate).date()

        lastest_clcs_row = PdClcsPrimeResult.objects.filter(
            customer_id=customer_id,
            partition_date__gt=credit_generated_date,
        ).last()

        return lastest_clcs_row

    def entry_level_is_true(account):
        account_property = get_account_property_by_account(account)
        if account_property:
            return account_property.is_entry_level
        else:  # if somehow property doesn't exist
            return True

    account = application.account
    customer_id = application.customer_id
    calculation_result = None

    feature_setting = FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.CFS,
    ).last()

    # check some logic before continue
    if (
        not feature_setting
        or not feature_setting.parameters.get('is_active_limit_recalculation', False)
        or not application.eligible_for_cfs
        or entry_level_is_true(account)
        or not check_for_new_clcs_score()
    ):
        return calculation_result

    with transaction.atomic():
        account_limit = AccountLimit.objects.select_for_update().filter(account=account).last()

        lastest_clcs_row = check_for_new_clcs_score()
        if not lastest_clcs_row:
            return calculation_result

        if account_limit.used_limit != 0:
            return calculation_result

        # Get parameters for calculation:
        # -- affordability
        affordability_history = AffordabilityHistory.objects.filter(application=application).last()
        affordability_value = affordability_history.affordability_value

        # -- credit matrix product line
        credit_matrix_result = get_credit_matrix_and_credit_matrix_product_line(
            application, is_self_bank_account=True
        )
        if not credit_matrix_result:
            return calculation_result
        credit_matrix, credit_matrix_product_line = credit_matrix_result

        # -- limit adjustment factor, decided from clcs score
        pgood = lastest_clcs_row.clcs_prime_score
        if pgood >= AccountConstant.PGOOD_CUTOFF:
            limit_adjustment_factor = (
                AccountConstant.CREDIT_LIMIT_ADJUSTMENT_FACTOR_GTE_PGOOD_CUTOFF
            )
        else:
            limit_adjustment_factor = AccountConstant.CREDIT_LIMIT_ADJUSTMENT_FACTOR

        # recalculation
        result = calculate_credit_limit(
            credit_matrix_product_line, affordability_value, limit_adjustment_factor
        )

        log_data = {
            'simple_limit': result['simple_limit'],
            'reduced_limit': result['reduced_limit'],
            'limit_adjustment_factor': result['limit_adjustment_factor'],
            'max_limit (pre-matrix)': result['simple_limit_rounded'],
            'set_limit (pre-matrix)': result['reduced_limit_rounded'],
        }

        reason = CreditLimitGenerationReason.RECALCULATION_WITH_CLCS

        available_limit = result['set_limit'] - account_limit.used_limit
        old_set_limit = account_limit.set_limit
        store_credit_limit_generated(
            application=application,
            account=account,
            credit_matrix=credit_matrix,
            affordability_history=affordability_history,
            max_limit=result['max_limit'],
            set_limit=result['set_limit'],
            log_data=log_data,
            reason=reason,
        )
        account_limit.update_safely(
            max_limit=result['max_limit'],
            set_limit=result['set_limit'],
            available_limit=available_limit,
        )

        calculation_result = old_set_limit, result['set_limit']

    return calculation_result


def is_using_turbo_limit(application):
    turbo_application = Application.objects.get_or_none(
        customer=application.customer,
        application_status_id=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
    )

    if not turbo_application:
        return False

    credit_limit_turbo = CreditLimitGeneration.objects.filter(
        application_id=turbo_application.id
    ).last()

    credit_limit_j1 = CreditLimitGeneration.objects.filter(application_id=application.id).last()

    return credit_limit_j1.set_limit <= credit_limit_turbo.set_limit


def update_account_limit(change_limit_amount: int, account_id: int) -> None:
    account_limit = AccountLimit.objects.select_for_update().filter(account_id=account_id).last()
    new_available_limit = account_limit.available_limit + change_limit_amount
    new_used_limit = account_limit.used_limit - change_limit_amount
    account_limit.update_safely(available_limit=new_available_limit, used_limit=new_used_limit)


def update_account_max_limit_pre_matrix_with_cfs(application, affordability_history):
    with transaction.atomic():
        account = application.account
        if not account:
            return

        latest_credit_limit = CreditLimitGeneration.objects.filter(application=application).last()
        log_data = json.loads(latest_credit_limit.log)

        # Get parameters for calculation:
        # -- Affordability
        affordability_value = affordability_history.affordability_value

        # -- Credit matrix product line
        credit_matrix = latest_credit_limit.credit_matrix
        credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
            credit_matrix=credit_matrix
        ).last()

        # -- Limit adjustment factor
        limit_adjustment_factor = log_data.get('limit_adjustment_factor', 1.0)

        # New max limit and set limit (pre-matrix) calculation
        credit_limit_result = calculate_credit_limit(
            credit_matrix_product_line, affordability_value, limit_adjustment_factor
        )

        logger.info(
            {
                'action': 'calculate_new_credit_limit_result_from_cfs',
                'params': {
                    'account_id': account.id,
                    **credit_limit_result,
                },
            }
        )

        old_max_limit_pre_matrix = log_data.get('max_limit (pre-matrix)')
        new_max_limit_pre_matrix = credit_limit_result['simple_limit_rounded']
        new_set_limit_pre_matrix = credit_limit_result['reduced_limit_rounded']

        if not old_max_limit_pre_matrix or old_max_limit_pre_matrix < new_max_limit_pre_matrix:
            log_data['max_limit (pre-matrix)'] = new_max_limit_pre_matrix
            log_data['set_limit (pre-matrix)'] = new_set_limit_pre_matrix

            # Store max limit and set limit (pre-matrix)
            store_credit_limit_generated(
                application=latest_credit_limit.application,
                account=latest_credit_limit.account,
                credit_matrix=latest_credit_limit.credit_matrix,
                affordability_history=affordability_history,
                max_limit=latest_credit_limit.max_limit,
                set_limit=latest_credit_limit.set_limit,
                log_data=json.dumps(log_data),
                reason=CreditLimitGenerationReason.UPDATE_MONTHLY_INCOME,
            )


def get_triple_pgood_limit(application: Application, max_limit, set_limit):
    """
    Make customer that have good triple pgood get bigger limit.
    Triple pgood calculation inside ana, here we only check the calculation result
    and implement it in the generate credit limit.
    """
    from juloserver.ana_api.models import EligibleCheck
    from juloserver.entry_limit.models import EntryLevelLimitHistory

    logger.info(
        {
            "application_id": application.id,
            "message": "get_triple_pgood_limit: hit function",
            "data": {"max_limit": max_limit, "set_limit": set_limit},
        }
    )

    # Check for entry limit
    has_entry_level = EntryLevelLimitHistory.objects.filter(application_id=application.id).exists()
    if has_entry_level:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_triple_pgood_limit: has entry level",
            }
        )
        return max_limit, set_limit

    eligible_check = EligibleCheck.objects.filter(
        application_id=application.id, check_name="eligible_limit_increase"
    ).last()

    if not eligible_check:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_triple_pgood_limit: null eligible_limit_increase",
            }
        )
        return max_limit, set_limit

    if not eligible_check.is_okay:
        logger.info(
            {"application_id": application.id, "message": "get_triple_pgood_limit: not okay"}
        )
        return max_limit, set_limit

    parameter = eligible_check.parameter
    if not parameter or "limit_gain" not in parameter:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_triple_pgood_limit: no param or limit gain",
            }
        )
        return max_limit, set_limit

    limit_gain = parameter["limit_gain"]

    matrix = (
        (True, True, (0.95, 1.01), 16_000_000, 16_000_000),
        (True, True, (0.90, 0.95), 14_000_000, 14_000_000),
        (True, True, (0.8, 0.82), 4_000_000, 4_000_000),
        (True, False, (0.95, 1.01), 14_000_000, 14_000_000),
        (True, False, (0.8, 0.82), 4_000_000, 4_000_000),
    )

    is_salaried = get_salaried(application.job_type)
    is_premium_area = is_inside_premium_area(application)
    pgood = get_credit_pgood(application)

    final_max_limit = max_limit
    final_set_limit = set_limit
    in_matrix = False
    for row in matrix:
        if (
            not in_matrix
            and is_salaried == row[0]
            and is_premium_area == row[1]
            and (row[2][0] <= pgood < row[2][1])
            and set_limit >= row[3]
        ):
            base_limit = row[4]
            final_max_limit = final_set_limit = base_limit + limit_gain
            in_matrix = True
            logger.info(
                {
                    "application_id": application.id,
                    "message": "get_triple_pgood_limit: eligible",
                    "data": {
                        "is_salaried": row[0],
                        "is_premium_area": row[1],
                        "heimdall": pgood,
                        "heimdall range": row[2],
                        "set_limit": set_limit,
                        "set_limit_threshold": row[3],
                        "final_limit": final_set_limit,
                    },
                }
            )

    if not in_matrix:
        final_max_limit = final_set_limit = set_limit + limit_gain

    credit_limit_generation = CreditLimitGeneration.objects.filter(
        application_id=application.id
    ).last()
    if credit_limit_generation:
        log_data = json.loads(credit_limit_generation.log)
        max_limit_pre_matrix = int(log_data['max_limit (pre-matrix)'])
        if final_set_limit > max_limit_pre_matrix:
            logger.info(
                {
                    "application_id": application.id,
                    "message": "get_triple_pgood_limit: final_limit over max_limit (pre-matrix)",
                    "final_set_limit": final_set_limit,
                    "max_limit_pre_matrix": max_limit_pre_matrix,
                }
            )
            final_set_limit = max_limit_pre_matrix

    ApplicationTagTracking(application).tracking("is_limit_increase", 1, certain=True)

    return final_max_limit, final_set_limit


def get_orion_fdc_limit_adjustment(application: Application, max_limit, set_limit):
    from juloserver.ana_api.models import PdCreditEarlyModelResult
    from juloserver.fdc.constants import FDCStatus, FDCLoanStatus
    from juloserver.application_flow.tasks import application_tag_tracking_task

    logger.info(
        {
            "application_id": application.id,
            "message": "get_orion_fdc_limit_adjustment: hit function",
            "data": {"max_limit": max_limit, "set_limit": set_limit},
        }
    )

    orion_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ORION_FDC_LIMIT_GENERATION,
    ).last()

    if not orion_limit_setting or not orion_limit_setting.is_active:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_orion_fdc_limit_adjustment: no feature setting or inactive",
                "data": {"max_limit": max_limit, "set_limit": set_limit},
            }
        )
        return max_limit, set_limit

    if (
        application.partner
        and not application.is_grab()
        and not application.is_qoala()
    ):
        max_limit, set_limit = 4000000, 4000000
        logger.info(
            {
                "application_id": application.id,
                "message": "get_orion_fdc_limit_adjustment: web app application",
                "data": {"max_limit": max_limit, "set_limit": set_limit},
            }
        )
        return max_limit, set_limit

    if not application.is_julo_one() or application.partner:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_orion_fdc_limit_adjustment: not j1 application",
                "data": {"max_limit": max_limit, "set_limit": set_limit},
            }
        )
        return max_limit, set_limit

    fdc_inquiry = FDCInquiry.objects.filter(
        application_id=application.id, status__iexact=FDCStatus.FOUND,
    ).last()

    if not fdc_inquiry:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_orion_fdc_limit_adjustment: non fdc",
                "data": {"max_limit": max_limit, "set_limit": set_limit},
            }
        )
        return max_limit, set_limit

    has_active_dpd15_loan = FDCInquiryLoan.objects.filter(
        fdc_inquiry_id=fdc_inquiry.id,
        status_pinjaman=FDCLoanStatus.OUTSTANDING,
        dpd_terakhir__gte=15
    ).exists()

    if has_active_dpd15_loan:
        max_limit, set_limit = 500000, 500000
        application_tag_tracking_task.delay(
            application.id, None, None, None, 'dpd15_true', 1
        )
        logger.info(
            {
                "application_id": application.id,
                "message": "get_orion_fdc_limit_adjustment: dpd15_true",
                "data": {"max_limit": max_limit, "set_limit": set_limit},
            }
        )
    else:
        # get orion score
        orion = PdCreditEarlyModelResult.objects.filter(
            application_id=application.id
        ).last()

        if not orion:
            max_limit, set_limit = 500000, 500000
            application_tag_tracking_task.delay(
                application.id, None, None, None, 'orion_null', 1
            )
            logger.info(
                {
                    "application_id": application.id,
                    "message": "get_orion_fdc_limit_adjustment: orion_null",
                    "data": {"max_limit": max_limit, "set_limit": set_limit},
                }
            )
        else:
            orion_matrix = (
                ((0.95, 1.01), max_limit, set_limit, '1st_highest_orion'),
                ((0.90, 0.95), 1_000_000, 1_000_000, '2nd_highest_orion'),
                ((0.70, 0.90), 500_000, 500_000, '3rd_highest_orion'),
            )
            for row in orion_matrix:
                if (row[0][0] <= orion.pgood < row[0][1]):
                    max_limit = row[1]
                    set_limit = row[2]
                    application_tag_tracking_task.delay(
                        application.id, None, None, None, row[3], 1
                    )

                    logger.info(
                        {
                            "application_id": application.id,
                            "message": "get_orion_fdc_limit_adjustment: has orion",
                            "data": {
                                "orion": orion.pgood,
                                "heimdall range": row[1],
                                "set_limit": set_limit,
                                "max_limit": max_limit,
                            },
                        }
                    )

    return max_limit, set_limit


def get_credit_pgood(application):
    return PdCreditModelResult.objects.filter(application_id=application.id).last().pgood


def get_non_fdc_job_check_fail_limit(application: Application, max_limit, set_limit):
    from juloserver.ana_api.models import EligibleCheck

    logger.info(
        {
            "application_id": application.id,
            "message": "get_non_fdc_job_check_fail_limit function initiated",
        }
    )

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.HIGH_RISK, is_active=True
    ).last()
    if not setting:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_non_fdc_job_check_fail_limit: high_risk setting not found",
            }
        )
        return max_limit, set_limit

    try:
        threshold = setting.parameters["cap_limit"]
    except KeyError:
        logger.info(
            {
                "application_id": application.id,
                "message": "get_non_fdc_job_check_fail_limit: cap limit key not found",
            }
        )
        return max_limit, set_limit

    has_eligible_check = EligibleCheck.objects.filter(
        application_id=application.id, check_name="non_fdc_job_check_fail", is_okay=True
    ).last()

    if has_eligible_check:
        if max_limit < threshold or set_limit < threshold:
            logger.info(
                {
                    "application_id": application.id,
                    "message": "get_non_fdc_job_check_fail_limit: limit below threshold",
                }
            )
            return max_limit, set_limit

        logger.info(
            {
                "application_id": application.id,
                "message": "get_non_fdc_job_check_fail_limit: limit in threshold",
            }
        )
        return threshold, threshold

    logger.info(
        {
            "application_id": application.id,
            "message": "get_non_fdc_job_check_fail_limit: final logic",
        }
    )
    return max_limit, set_limit

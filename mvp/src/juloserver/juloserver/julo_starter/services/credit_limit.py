import json

from juloserver.apiv2.models import PdCreditModelResult
from juloserver.julo_starter.exceptions import PDCreditModelNotFound, SettingNotFound
from django.db import transaction
from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.julo.models import (
    AffordabilityHistory,
    FeatureSetting,
    FeatureNameConst,
    ExperimentSetting,
)
from juloserver.account.utils import round_down_nearest
from juloserver.account.services.credit_limit import store_credit_limit_generated
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo_starter.exceptions import JuloStarterException
from juloserver.application_flow.services import eligible_to_offline_activation_flow
from juloserver.julolog.julolog import JuloLog

juloLogger = JuloLog()


def calculate_credit_limit(affordability_value, max_limit):
    limit_rounded = (
        max_limit
        if affordability_value > max_limit
        else round_down_nearest(affordability_value, 100000)
    )
    return limit_rounded


def generate_credit_limit(application, setting, is_active_partial_limit=None):
    if is_active_partial_limit is None:
        from juloserver.julo_starter.services.flow_dv_check import is_active_partial_limit as iapl

        is_active_partial_limit = iapl()

    affordability_history = AffordabilityHistory.objects.filter(application=application).last()
    affordability_value = affordability_history.affordability_value

    credit_model = PdCreditModelResult.objects.filter(application_id=application.id).last()

    pgood = credit_model.pgood

    if pgood >= float(setting.parameters['high']['bottom_threshold']):
        bin = 'high'
    elif pgood >= float(setting.parameters['mid']['bottom_threshold']):
        bin = 'mid'
    elif pgood >= float(setting.parameters['low']['bottom_threshold']):
        bin = 'low'
    else:
        raise JuloStarterException("Illegal credit limit generation, pgood under lowest threshold.")

    credit_limit_result = calculate_credit_limit(
        affordability_value, setting.parameters[bin]['max_limit']
    )

    if credit_limit_result < setting.parameters[bin]['min_limit']:
        credit_limit_result = setting.parameters[bin]['min_limit']

    if is_active_partial_limit:
        credit_limit = setting.parameters[bin]['min_limit']
        reason = "109 Jstarter partial limit"

        if eligible_to_offline_activation_flow(application):
            exp_setting = ExperimentSetting.objects.get_or_none(
                code="offline_activation_referral_code"
            )
            if exp_setting:
                credit_limit = exp_setting.criteria.get('minimum_limit')

        if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
            credit_limit = credit_limit_result
            reason = "190 Jstarter partial to full limit"
    else:
        reason = "190 Jstarter full limit"
        credit_limit = credit_limit_result

    log_data = {
        'affordability_value': affordability_value,
        'set_limit': credit_limit,
        'full_limit': credit_limit_result,
        'max_duration': setting.parameters[bin]['max_duration'],
    }

    # store generated credit limit and values
    store_credit_limit_generated(
        application,
        None,
        None,
        affordability_history,
        credit_limit,
        credit_limit,
        json.dumps(log_data),
        reason,
    )

    return credit_limit


def activate_credit_limit(account, application_id):
    with transaction.atomic():
        account.update_safely(status_id=AccountConstant.STATUS_CODE.active)
        account_limit = AccountLimit.objects.filter(account=account).last()
        if not account_limit:
            juloLogger.warning(
                {
                    "msg": "JStarter Account Limit Not Found",
                    "application_id": application_id,
                }
            )
            return
        available_limit = account_limit.set_limit - account_limit.used_limit
        account_limit.update_safely(available_limit=available_limit)


def get_lowest_threshold_credit_score(application_id):
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SPHINX_THRESHOLD, is_active=True
    ).last()
    if setting is None:
        juloLogger.warning(
            {
                "msg": "handle_julo_starter_income_check, setting not found",
                "application_id": application_id,
            }
        )
        return

    return float(setting.parameters['low']['bottom_threshold'])


def check_is_good_score(application, credit_model=None):
    from juloserver.julo_starter.services.mocking_services import mock_determine_pgood

    if credit_model is None:
        credit_model = PdCreditModelResult.objects.filter(application_id=application.id).last()

    if credit_model is None:
        juloLogger.warning(
            {
                "msg": "Credit model not found",
                "application_id": application.id,
            }
        )
        raise PDCreditModelNotFound(
            'Pd credit model not found|' 'application={}'.format(application.id)
        )

    lowest_threshold = get_lowest_threshold_credit_score(application.id)
    if not lowest_threshold:
        raise SettingNotFound('Sphinx threshold setting not found')

    # Based on feature setting and for testing env only
    pgood = mock_determine_pgood(application, credit_model.pgood)

    return pgood >= lowest_threshold

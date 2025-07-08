from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo_starter.exceptions import JuloStarterException

logger = JuloLog()
sentry = get_julo_sentry_client()


def _validate_parameters():
    key_full_dv = 'full_dv'
    key_partial_limit = 'partial_limit'
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER, is_active=True
    ).last()
    if not setting:
        error_msg = "Not found {}".format(FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER)
        logger.error({"message": error_msg})
        raise JuloStarterException(error_msg)
    if not setting.parameters:
        error_msg = "Parameter is empty"
        logger.error(
            {"message": error_msg, "feature_setting": FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER}
        )
        raise JuloStarterException(error_msg)
    param = setting.parameters
    if key_full_dv not in param or key_partial_limit not in param:
        error_msg = "Parameter is invalid"
        logger.error(
            {
                "message": error_msg,
                "setting": str(param),
                "feature_setting": FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            }
        )
        raise JuloStarterException(error_msg)
    is_valid_for_param = are_different(param[key_full_dv], param[key_partial_limit])
    if not is_valid_for_param:
        error_msg = "Parameter is not correct"
        logger.error(
            {
                "message": error_msg,
                "setting": str(param),
                "feature_setting": FeatureNameConst.CONFIG_FLOW_LIMIT_JSTARTER,
            }
        )
        raise JuloStarterException(error_msg)
    return param


def are_different(full_dv, partial_limit):
    if full_dv == 'enabled' and partial_limit == 'disabled':
        return True
    elif full_dv == 'disabled' and partial_limit == 'enabled':
        return True
    else:
        return False


@sentry.capture_exceptions
def is_active_partial_limit():
    """
    To check flow active:
    Full DV or Partial Limit
    Based on setting in Feature Setting

    This function will return:
    : True -> If Partial Limit is enabled
    : False -> if Partial Limit is disabled and will use flow Full DV
    """

    param = _validate_parameters()

    return True if param["partial_limit"] == 'enabled' else False


@sentry.capture_exceptions
def is_active_full_dv():
    """
    To check flow active:
    Full DV or Partial Limit
    Based on setting in Feature Setting

    This function will return:
    : True -> If Partial Limit is enabled
    : False -> if Partial Limit is disabled and will use flow Full DV
    """

    param = _validate_parameters()

    return True if param["full_dv"] == 'enabled' else False

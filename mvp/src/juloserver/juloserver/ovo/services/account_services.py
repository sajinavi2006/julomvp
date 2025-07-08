from juloserver.julo.models import FeatureSetting
from juloserver.ovo.constants import OvoConst
from juloserver.julo.constants import FeatureNameConst


def is_show_ovo_payment_method(account):
    whitelist_ovo_feature_setting = FeatureSetting.objects.filter(
        feature_name=OvoConst.WHITELIST_OVO, is_active=True
    ).last()

    if not whitelist_ovo_feature_setting:
        return True

    application = account.last_application
    if application.id in whitelist_ovo_feature_setting.parameters["applications"]:
        return True

    return False


def is_ovo_tokenization_whitelist_feature_active(account):
    whitelist_ovo_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.OVO_TOKENIZATION_WHITELIST, is_active=True
    ).last()

    if not whitelist_ovo_feature_setting:
        return True

    application = account.last_application
    if application.id in whitelist_ovo_feature_setting.parameters["application_id"]:
        return True

    return False


def is_show_ovo_tokenization(application_id):
    ovo_tokenization_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.OVO_TOKENIZATION, is_active=True
    )

    ovo_tokenization_whitelist_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.OVO_TOKENIZATION_WHITELIST, is_active=True
    )

    if ovo_tokenization_feature_setting:
        if ovo_tokenization_whitelist_setting:
            if application_id in ovo_tokenization_whitelist_setting.parameters['application_id']:
                return True
            return False
        return True
    return False

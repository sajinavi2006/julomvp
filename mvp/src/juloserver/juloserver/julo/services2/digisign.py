from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import MobileFeatureSetting


def is_digisign_feature_active(application=None):
    feature_name = 'digisign_mode'
    partner = (PartnerConstant.AXIATA_PARTNER, PartnerConstant.PEDE_PARTNER)
    if application:
        if application.partner and application.partner.name in partner:
            feature_name = 'partner_digisign_mode'

    return MobileFeatureSetting.objects.filter(
        feature_name=feature_name,
        is_active=True
    ).exists()


def is_digisign_web_browser(application=None):
    partner = (PartnerConstant.AXIATA_PARTNER, PartnerConstant.PEDE_PARTNER)
    return application.partner and application.partner.name in partner

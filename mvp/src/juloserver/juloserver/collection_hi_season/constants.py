from juloserver.loan_refinancing.constants import CovidRefinancingConst


class CampaignStatus(object):
    DRAFT = 'draft'
    PAUSE = 'pause'
    ACTIVE = 'active'
    FINISHED = 'finished'


class CampaignCommunicationPlatform(object):
    EMAIL = 'email'
    PN = 'pn'
    INAPP = 'inapp_notification'


class CampaignBanner(object):
    EMAIL = 'email_banner'
    PN = 'pn_banner'
    INAPP = 'inapp_banner'
    ON_CLICK = 'onclick_banner'


class CampaignCardProperty(object):
    BANNER_IMAGE = 'banner_image'


EXCLUDE_PENDING_REFINANCING_STATUS = {
    CovidRefinancingConst.STATUSES.offer_generated,
    CovidRefinancingConst.STATUSES.offer_selected,
    CovidRefinancingConst.STATUSES.approved,
    CovidRefinancingConst.STATUSES.activated,
}

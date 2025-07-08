from factory.django import DjangoModelFactory
from factory import SubFactory

from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import CustomerFactory, RefereeMappingFactory
from juloserver.referral.constants import (
    FeatureNameConst,
    ReferralBenefitConst,
    ReferralLevelConst,
    ReferralPersonTypeConst,
    MAPPING_COUNT_START_DATE
)
from juloserver.referral.models import (
    ReferralBenefit,
    ReferralLevel,
    ReferralBenefitHistory,
)


class ReferralBenefitFactory(DjangoModelFactory):
    class Meta(object):
        model = ReferralBenefit

    benefit_type = ReferralBenefitConst.CASHBACK
    referrer_benefit = 50000
    referee_benefit = 20000
    min_disburse_amount = 450000
    is_active = True


class ReferralLevelFactory(DjangoModelFactory):
    class Meta(object):
        model = ReferralLevel

    benefit_type = ReferralLevelConst.CASHBACK
    referrer_level_benefit = 20000
    min_referees = 5
    level = 'SUPER'
    is_active = True


class ReferralLevelBenefitFeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = FeatureNameConst.REFERRAL_LEVEL_BENEFIT_CONFIG
    category = 'referral'
    description = 'referral level benefit config'
    is_active = True
    parameters = [
        {
            "level": "Basic",
            "color": "#404040",
            "icon": "http://drive.google.com/uc?id=1UnPJ5mnbnMoNlfeoe-4ZgAGqfsHVijvh",
            "referee_required": {
                "label": "Ajak teman",
                "value": "Mulai dari {referee} teman"
            },
            "min_transaction": {
                "label": "Min. transaksi {min_amount_thres}",
                "value": "Cashback {benefit_amount}"
            },
            "has_bonus": {
                "label": "Kesempatan menangin hadiah utama",
                "value": "false",
            },
            "referee_benefit": {
                "label": "Temanmu Min. transaksi {min_amount_thres}",
                "value": "Temanmu dapat cashback {referee_cashback}",
            },
        },
        {
            "level": "Super",
            "color": "#F09537",
            "icon": "http://drive.google.com/uc?id=1X5YWWO2eBd3-KC2xhO4aBoxRTMEudso4",
            "referee_required": {
                "label": 'Ajak teman',
                "value": "{referee} teman atau lebih",
            },
            "min_transaction": {
                "label": "Min. transaksi {min_amount_thres}",
                "value": "Cashback {benefit_amount}",
            },
            "has_bonus": {
                "label": "Kesempatan menangin hadiah utama",
                "value": "true",
            },
            "referee_benefit": {
                "label": "Temanmu Min. transaksi {min_amount_thres}",
                "value": "Temanmu dapat cashback {referee_cashback}",
            },
        }
    ]


class ReferralBenefitHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = ReferralBenefitHistory

    referee_mapping = SubFactory(RefereeMappingFactory)
    customer = SubFactory(CustomerFactory)
    referral_person_type = ReferralPersonTypeConst.REFERRER
    benefit_unit = ReferralBenefitConst.CASHBACK
    amount = 100000


class ReferralBenefitFeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = FeatureNameConst.REFERRAL_BENEFIT_LOGIC
    is_active = True
    parameters = {
        'count_start_date': MAPPING_COUNT_START_DATE
    }

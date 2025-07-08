from builtins import object
from enum import Enum


class CootekAIRobocall(object):
    SIP_LINE = 'JULOAPI_CALLER_LINE'
    REDIS_COOTEK_TOKEN_REDIS_KEY = 'cootek_api_token_authentication'
    MAX_RETRY_COUNT = 5
    UNIT_RUPIAH = 'Rupiah'
    PLATFORM_JULO = 'JULO'
    PLATFORM_DANA = 'DANA'
    NOT_DELETE_INTELIX_QUEUE_INTENTION = (
        'B', 'D', 'E', 'H', 'I', '--',
        'F', 'G',
    )
    # intention to send to our dialer
    DPD_0 = ('B', 'E', 'F', 'G', 'H', 'I', '--')


class CriteriaChoices(object):
    REFINANCING_PENDING = 'Refinancing_Pending'
    LATE_DPD_EXPERIMENT = 'Late_DPD_Experiment'
    UNCONNECTED_LATE_DPD = 'Unconnected_Late_dpd'
    ALL = (
        (REFINANCING_PENDING, 'Refinancing Pending (4)'),
        (LATE_DPD_EXPERIMENT, 'Late DPD Experiment'),
        (UNCONNECTED_LATE_DPD, 'Unconnected Late DPD'),
    )
    LATE_FEE_EARLIER_EXPERIMENT = 'late_fee_earlier_experiment'
    CASHBACK_NEW_SCHEME = 'cashback_new_scheme'


class DpdConditionChoices(object):
    EXACTLY = 'Exactly'
    RANGE = 'Range'
    LESS = 'Less'
    ALL = (
        (EXACTLY, 'Exactly on this dpd'),
        (RANGE, 'Dpd range'),
        (LESS, 'Less than this dpd')
    )


class LoanIdExperiment(object):
    GROUP_1 = 'L00-L33'
    GROUP_2 = 'L34-L66'
    GROUP_3 = 'L67-L99'


class CootekProductLineCodeName(object):
    J1 = 'J1'
    MTL = 'mtl'
    STL = 'stl'
    DANA = 'dana'
    JTURBO = 'JTurbo'

    COOTEK_CONFIGURATION_PRODUCT_LINE = (
        (None, '---------'),
        (MTL, MTL),
        (STL, STL),
        (J1, J1),
        (DANA, DANA),
        (JTURBO, JTURBO)
    )

    @classmethod
    def partner_eligible_for_cootek(cls):
        return {
            cls.DANA, "bukalapak_paylater"
        }


class JuloGoldFilter(Enum):
    EXCLUDE = "exclude"
    ONLY = "only"

    @classmethod
    def as_options(cls, with_none=False):
        options = [
            (cls.EXCLUDE.value, 'Exclude JULO Gold'),
            (cls.ONLY.value, 'Execute Only JULO Gold'),
        ]

        if with_none:
            options = [(None, 'None')] + options

        return options

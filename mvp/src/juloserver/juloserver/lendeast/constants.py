from builtins import object

from juloserver.julo.statuses import (
    LoanStatusCodes,
    ApplicationStatusCodes,
)
from juloserver.julo.product_lines import ProductLineCodes


class LendEastConst(object):
    PARTNER_NAME = "lendeast"
    LIMIT_B3_PERCENT = 10


class LoanAcceptanceCriteriaConst(object):
    LENDER_NAMES = ['jtp']
    OTHER_LENDER_NAMES = ['jh']
    APPLICATION_STATUS = ApplicationStatusCodes.LOC_APPROVED

    LOAN_STATUSES = [
        LoanStatusCodes.LOAN_1DPD,
        LoanStatusCodes.LOAN_5DPD,
        LoanStatusCodes.LOAN_30DPD,
        LoanStatusCodes.LOAN_60DPD,
        LoanStatusCodes.CURRENT
    ]

    J1_PRODUCT_LINE_CODES = [
        ProductLineCodes.J1,
    ]

    AXIATA_PRODUCT_LINE_CODES = [
        ProductLineCodes.AXIATA1,
        ProductLineCodes.AXIATA2
    ]

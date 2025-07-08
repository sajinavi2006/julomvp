from dataclasses import dataclass
from typing import List, Dict

from juloserver.julo.models import Loan


@dataclass
class LoanTransactionDetailData:
    loan: Loan
    admin_fee: int
    provision_fee_rate: float
    dd_premium: int
    insurance_premium: int
    digisign_fee: int
    total_registration_fee: int
    tax_fee: int
    monthly_interest_rate: float
    tax_on_fields: List[str]
    promo_applied: Dict[str, any]

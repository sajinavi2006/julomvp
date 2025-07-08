from dataclasses import dataclass

from juloserver.loan.models import LoanErrorLog


@dataclass
class LoanErrorLogData:
    identifier: str
    identifier_type: str
    error_code: str
    http_status_code: int
    error_detail: str
    api_url: str


def log_loan_error(data: LoanErrorLogData) -> None:
    """
    Log loan error into logging db
    """
    LoanErrorLog.objects.create(
        **data.__dict__,
    )

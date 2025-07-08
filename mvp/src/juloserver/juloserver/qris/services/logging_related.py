from juloserver.loan.services.logging_related import log_loan_error, LoanErrorLogData
from juloserver.qris.services.feature_settings import QrisErrorLogSetting


def log_qris_error(error: LoanErrorLogData):
    """
    Log knowns error for qris to logging DB
    """
    fs = QrisErrorLogSetting()
    if fs.is_active:
        log_loan_error(error)

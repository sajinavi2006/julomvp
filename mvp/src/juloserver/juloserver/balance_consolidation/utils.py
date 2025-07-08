import os
import datetime

from juloserver.balance_consolidation.constants import (
    BalanceConsolidationValidation,
    FileTypeUpload
)


def is_valid_file(filename):
    _, file_extension = os.path.splitext(filename)
    return file_extension in FileTypeUpload.valid_file_types()


def check_valid_loan_amount(loan_principal_amount, loan_outstanding_amount):
    min_loan_outstanding_amount = BalanceConsolidationValidation.MIN_LOAN_OUTSTANDING_AMOUNT
    max_loan_outstanding_amount = BalanceConsolidationValidation.MAX_LOAN_OUTSTANDING_AMOUNT
    min_loan_principal_amount = BalanceConsolidationValidation.MIN_LOAN_PRINCIPAL_AMOUNT
    max_loan_principal_amount = BalanceConsolidationValidation.MAX_LOAN_PRINCIPAL_AMOUNT

    valid_outstanding_amount = min_loan_outstanding_amount <= loan_outstanding_amount <= max_loan_outstanding_amount
    valid_principal_amount = min_loan_principal_amount <= loan_principal_amount <= max_loan_principal_amount
    return valid_outstanding_amount and valid_principal_amount


def check_valid_loan_date(loan_disbursement_date, loan_due_date):
    if not (
        loan_disbursement_date <= loan_due_date
    ) or not (loan_disbursement_date <= datetime.date.today()):
        return False
    return True

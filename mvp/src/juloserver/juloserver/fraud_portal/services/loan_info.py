import pytz
from django.db import connections

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.fraud_portal.models.models import LoanInfo
from juloserver.julo.constants import JULO_ANALYTICS_DB
from juloserver.julo.models import (
    Application,
    Loan,
    StatusLookup,
    Payment,
    FDCRiskyHistory,
)
from juloserver.payment_point.models import TransactionMethod
from juloserver.pii_vault.constants import PiiSource

jakarta_tz = pytz.timezone('Asia/Jakarta')


def get_loan_info(application_ids: list) -> list:
    loan_info_list = []

    for application_id in application_ids:
        application = Application.objects.get(pk=application_id)

        fpgw = get_fpgw(application)
        fdc_data_history = get_fdc_data_history(application)
        diabolical = get_diabolical(application)
        loan_information = get_loan_information(application)

        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application], ['fullname']
        )[0]
        loan_info = LoanInfo(
            application_id=application.id,
            application_fullname=detokenized_application.fullname,
            fpgw=fpgw,
            fdc_data_history=fdc_data_history,
            diabolical=diabolical,
            loan_information=loan_information,
        )
        loan_info_list.append(loan_info.to_dict())

    return loan_info_list


def get_fpgw(application: Application) -> str:
    """
    Calculates and retrieves the FPGW First Payment (Past) Grace, are loans that have their first
    payment not paid before or during grace period.

    Args:
        application (Application): Application object to retrieve customer_id.

    Returns:
        str: The number of fogw, or None if no such loans exist.
    """
    # TODO: will get from table that provided by data team later
    return None


def get_fdc_data_history(application: Application) -> bool:
    """
    To determine whether application has fdc risky or not.

    Args:
        application (Application): The application for which to retrieve FDC risk status.

    Returns:
        bool: The FDC risk status for the application. If no FDC risk data history is found,
        returns None.
    """
    fdc_data_history = FDCRiskyHistory.objects.filter(application_id=application.id).last()
    if not fdc_data_history:
        return None
    return fdc_data_history.is_fdc_risky


def get_diabolical(application: Application) -> str:
    """
    To determine whether application is diabolical or not.

    Args:
        application (Application): The application for to retrieve application_id.

    Returns:
        str: diabolical status of application between diabolical 5 and 40. If no
        diabolical return No
    """
    diabolocal_msg = "No"

    application_id = application.id

    with connections[JULO_ANALYTICS_DB].cursor() as cursor:
        cursor.execute(
            """SELECT
                dl.fpd5diablo, dl.fpd40diablo
            FROM
                ana.diabolical_list_fraud_portal dl
            WHERE
                dl.application_id= %s
            ORDER BY
                cdate desc
            LIMIT 1""",
            [application_id],
        )
        result = cursor.fetchone()

    if not result:
        return diabolocal_msg

    is_diabolical_5, is_diabolical_40 = result
    if is_diabolical_5 and is_diabolical_40:
        diabolocal_msg = "Yes (Diabolical 5 and 40)"
    elif is_diabolical_5:
        diabolocal_msg = "Yes (Diabolical 5)"
    elif is_diabolical_40:
        diabolocal_msg = "Yes (Diabolical 40)"

    return diabolocal_msg


def get_loan_information(application: Application) -> list:
    """
    Retrieves detailed information about loans associated with the given application.

    Args:
        application (Application): Application object to retrieve loan information.

    Returns:
        list: A list of dictionaries, each containing information about a loan.
    """
    loan_information_list = []
    customer = application.customer
    if not customer:
        return loan_information_list
    customer_id = customer.id
    loans = Loan.objects.filter(customer_id=customer_id)

    for loan in loans:
        loan_status = str(StatusLookup.objects.get(status_code=loan.status))
        transaction_method_name = ''
        if loan.transaction_method:
            transaction_method = TransactionMethod.objects.filter(
                pk=loan.transaction_method.id
            ).last()
            if transaction_method:
                transaction_method_name = transaction_method.fe_display_name
        disbursed_to = "{0} - {1} ({2})".format(
            application.bank_name, application.name_in_bank, application.bank_account_number
        )
        loan_date = loan.cdate.astimezone(jakarta_tz).strftime('%Y-%m-%d')
        repayment_history = get_repayment_history(loan)

        loan_information = {
            "loan_id": loan.id,
            "loan_amount": loan.loan_amount,
            "loan_status": loan_status,
            "transaction_method": transaction_method_name,
            "disbursed_to": disbursed_to,
            "loan_date": loan_date,
            "repayment_history": repayment_history,
        }
        loan_information_list.append(loan_information)

    return loan_information_list


def get_repayment_history(loan: Loan) -> list:
    """
    Retrieves payment history for a given loan.

    Args:
        loan (Loan): The loan for which to retrieve payment history.

    Returns:
        list: A list of dictionaries, each containing information about a payment associated with
        the loan.
    """
    repayment_history_list = []
    payments = Payment.objects.filter(loan=loan)

    for payment in payments:
        payment_status = str(StatusLookup.objects.get(status_code=payment.status))
        repayment_history = {
            "payment_id": payment.id,
            "payment_status": payment_status,
            "principle_amount": payment.installment_principal,
            "payment_amount": payment.due_amount,
            "paid_amount": payment.paid_amount,
        }
        repayment_history_list.append(repayment_history)

    return repayment_history_list

import math
import json

from dateutil.relativedelta import relativedelta

from django.db.models import Count, Sum

from babel.dates import format_date

from juloserver.account.services.credit_limit import get_salaried

from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)

from juloserver.julo.utils import (
    get_customer_age,
    get_marital_status_in_english,
    get_gender_in_english,
    get_last_education_in_english,
    get_monthly_income_band,
)

from juloserver.julo.models import (
    Loan,
    PaymentEvent,
    PaymentHistory,
    FeatureSetting,
    Device,
)

from juloserver.lendeast.models import (
    LendeastDataMonthly
)


from juloserver.lendeast.constants import (
    LoanAcceptanceCriteriaConst,
    LendEastConst,
)

from juloserver.lendeast.exceptions import (
    LendEastException,
)

from juloserver.account.services.credit_limit import get_credit_model_result

from .models import LendeastReportMonthly

REDIS_KEY_DEFAULT = "LENDEAST_DATA"
LENDEAST_CONF_NAME = "lendeast_config"


def get_lendeast_loan_eligiblity(current_month_year):
    minimum_total_osp = get_minimum_osp()
    last_month_year = current_month_year - relativedelta(months=+1)
    last_month_data_qs = LendeastDataMonthly.objects.filter(
        data_date=last_month_year,
        loan__loan_status__lte=LoanStatusCodes.LOAN_180DPD,
        loan__payment__is_restructured=False
    ).annotate(
        outstanding_amount=Sum('loan__payment__installment_principal')
        - Sum('loan__payment__paid_principal')
    ).values_list('outstanding_amount', 'loan_id')

    loan_qs = Loan.objects.filter(
        product__product_line__in=LoanAcceptanceCriteriaConst.J1_PRODUCT_LINE_CODES,
        account__application__application_status_id=LoanAcceptanceCriteriaConst.APPLICATION_STATUS,
        account__application__partner__isnull=True,
        payment__is_restructured=False
    ).order_by('pk').annotate(
        outstanding_amount=Sum('payment__installment_principal') - Sum('payment__paid_principal')
    ).values_list('outstanding_amount', 'pk')

    loan_axiata_qs = Loan.objects.filter(
        product__product_line__in=LoanAcceptanceCriteriaConst.AXIATA_PRODUCT_LINE_CODES,
    ).order_by('pk').annotate(
        outstanding_amount=Sum('payment__installment_principal') - Sum('payment__paid_principal')
    ).values_list('outstanding_amount', 'pk')

    loan_jtp_qs = loan_qs.filter(
        lender__lender_name__in=LoanAcceptanceCriteriaConst.LENDER_NAMES,
    )

    loan_other_qs = loan_qs.filter(
        lender__lender_name__in=LoanAcceptanceCriteriaConst.OTHER_LENDER_NAMES,
    )

    total_osp = {'total': 0}
    loan_valid_ids = []
    summary_data = {}
    for loan_status in LoanAcceptanceCriteriaConst.LOAN_STATUSES:
        summary_data[loan_status] = 0

    def calculate_outstanding(loans):
        for outstanding_amount, loan_id in loans.iterator():

            if not outstanding_amount:
                continue

            total_osp['total'] += outstanding_amount
            summary_data[loan_status] += outstanding_amount
            loan_valid_ids.append(loan_id)

            if total_osp['total'] >= minimum_total_osp:
                last_month_loan_ids = list(last_month_data_qs.values_list('loan_id', flat=True))
                all_loan_ids = list(set(last_month_loan_ids + loan_valid_ids))
                return all_loan_ids, total_osp['total'], summary_data

            if loan_status == LoanStatusCodes.LOAN_60DPD:
                b3_percent = summary_data[loan_status] * 100 / minimum_total_osp
                if b3_percent > LendEastConst.LIMIT_B3_PERCENT:
                    break
        return False

    all_loan_data = [loan_jtp_qs, loan_other_qs, loan_axiata_qs]

    for loan_status in LoanAcceptanceCriteriaConst.LOAN_STATUSES:
        loans = last_month_data_qs.filter(loan__loan_status=loan_status)
        result = calculate_outstanding(loans)
        if result:
            return result

    for loan_data in all_loan_data:
        for loan_status in LoanAcceptanceCriteriaConst.LOAN_STATUSES:
            loans = loan_data.filter(
                loan_status=loan_status
            ).exclude(
                pk__in=loan_valid_ids
            )
            result = calculate_outstanding(loans)
            if result:
                return result

    raise LendEastException(
        'Not enough loan OSP, total: %d, minimum: %d' % (
            total_osp['total'], minimum_total_osp)
    )


def construct_loan_detail_data(loan):
    lender = loan.lender
    customer = loan.customer
    account = loan.account
    application = account.last_application if account else loan.application

    dob = customer.dob or application.dob
    device_model = Device.objects.filter(customer_id=customer.id).last()
    credit_model_result = get_credit_model_result(application)
    product = loan.product
    credit_rating = 0
    if credit_model_result:
        credit_rating = credit_model_result.pgood or credit_model_result.probability_fpd

    payment_events = PaymentEvent.objects.filter(
        event_type__in=["waive_interest", "waive_principal"], payment__loan=loan
    )
    waived_amount = {"waive_interest": 0, "waive_principal": 0}
    for payment_event in payment_events:
        waived_amount[payment_event.event_type] += payment_event.event_payment
    loan_histories = Loan.objects.filter(
        customer=customer, loan_status__gte=LoanStatusCodes.CURRENT
    )
    payment_histories = PaymentHistory.objects.filter(
        loan=loan, payment_new_status_code__gte=PaymentStatusCodes.PAYMENT_1DPD
    ).values('loan', 'payment').annotate(
        dcount=Count('loan', 'payment')
    )
    return {
        "ownerId": lender.id,
        "loanOriginationCountry": "Indonesia",
        "loanOriginationChannel": "App",
        "localCurrency": "IDR",
        "ownerName": lender.lender_name,
        "loanId": loan.loan_xid,
        "borrowersId": customer.customer_xid,
        "borrowersAge": get_customer_age(dob),
        "borrowersSex": get_gender_in_english(application.gender),
        "borrowersLocation": application.full_address,
        "borrowersMaritalStatus": get_marital_status_in_english(application.marital_status),
        "borrowersEducation": get_last_education_in_english(application.last_education),
        "borrowersEmploymentStatus": get_salaried(application.job_type),
        "borrowersIncome": application.monthly_income,
        "borrowersExpenses": application.monthly_expenses,
        "borrowerhistoricalLoanApplication": len(loan_histories),
        "borrowerPriorDeliquency": len(payment_histories),
        "borrowerMobile": device_model.device_model_name if device_model else "",
        "borrowerMobileContacts": 0,
        "borrowerMobileAppList": 0,
        "borrowersInternalCreditrating": credit_rating,
        "borrowerPurchaseItem": 0,
        "borrowerPurchasePrice": 0,
        "borrowerMonthlyIncomeBand": get_monthly_income_band(application.monthly_income),
        "loanProduct": "Revolving Loan",
        "loanPurpose": loan.loan_purpose,
        "loanDisbursementDate": loan.fund_transfer_ts,
        "loanTerm": loan.loan_duration,
        "loanStatus": loan.loan_status.status,
        "loanAPR": product.interest_rate,
        "loanGrossInterestRate": product.monthly_interest_rate,
        "loanOriginationAmount": loan.loan_amount,
        "loanProcessingFee": loan.loan_amount - loan.loan_disbursement_amount,
        "loanOriginationDisbursementAmount ": loan.loan_disbursement_amount,
        "loanOriginationMonth ": format_date(loan.cdate, "MMMM"),
        "loanPrincipalWaived": waived_amount["waive_principal"],
        "loanInterestWaived": waived_amount["waive_interest"],
        "loanDayPastDue": "30"
    }


def construct_schedule_data(loan):
    payments = loan.payment_set.filter(is_restructured=False).order_by('pk')
    data = {
        "loanSchedulePrincipalPayment": [],
        "loanScheduleInterestPayment": [],
        "loanScheduleFeesPayment": [],
        "loanPaymentSchedule": "Monthly Installments",
        "loanRepaymentDueDates": [],
        "loanRepaymentPaids": [],
        "loanIncrPrincipalReceived": [],
        "loanIncrInterestReceived": [],
        "loanIncrFeesReceived": []
    }
    payment_received = {"principal": 0, "interest": 0, "late_fee": 0}
    payment_outstanding = {"principal": 0, "interest": 0, "late_fee": 0}
    for payment in payments:
        data["loanSchedulePrincipalPayment"].append(payment.installment_principal)
        data["loanScheduleInterestPayment"].append(payment.installment_interest)
        data["loanScheduleFeesPayment"].append(payment.late_fee_amount)
        data["loanRepaymentDueDates"].append(payment.due_date)
        for key, value in payment_received.items():
            payment_received[key] = value + getattr(payment, "paid_{}".format(key))
            payment_outstanding[key] = value + getattr(payment, "remaining_{}".format(key))

        data["loanRepaymentPaids"].append(payment.paid_date)
        data["loanIncrPrincipalReceived"].append(payment.paid_principal)
        data["loanIncrInterestReceived"].append(payment.paid_interest)
        data["loanIncrFeesReceived"].append(payment.paid_late_fee)

    data.update({
        "loanPrincipalOutstanding": payment_outstanding["principal"],
        "loanInterestOutstanding": payment_outstanding["interest"],
        "loanPrincipalReceived": payment_received["principal"],
        "loanActualPrincipalReceived": payment_received["principal"],
        "loanActualInterestReceived": payment_received["interest"],
        "loanActualFeesReceived": payment_received["late_fee"],
    })
    return data


def get_data_by_month(month_year, offset):
    limit = get_page_size()
    result = LendeastDataMonthly.objects.filter(
        data_date=month_year
    ).order_by('pk').values_list('loan_data', flat=True)[(offset - 1) * limit: offset * limit]

    return list(result)


def set_data_by_month(data, month_year):
    bulk_data = []
    for loan_id, loan_data in data.items():
        bulk_data.append(LendeastDataMonthly(
            loan_id=loan_id,
            data_date=month_year,
            loan_status=loan_data['loanStatus'],
            loan_data=json.loads(json.dumps(loan_data, default=str))
        ))

    LendeastDataMonthly.objects.bulk_create(bulk_data)


def get_minimum_osp():
    lendeast_conf = FeatureSetting.objects.get(
        is_active=True, feature_name=LENDEAST_CONF_NAME)
    return int(lendeast_conf.parameters.get('minimum_osp'))


def get_page_size():
    lendeast_conf = FeatureSetting.objects.get(
        is_active=True, feature_name=LENDEAST_CONF_NAME)
    return int(lendeast_conf.parameters.get('page_size'))


def construct_general_response_data(status_code, status_message, statement_month, page, data):
    lender_report = LendeastReportMonthly.objects.filter(
        statement_month=statement_month
    ).last()

    outstanding_amount = 0
    total_loan = 0
    page_str = ""

    if lender_report and data:
        limit = get_page_size()
        total_page = math.ceil(lender_report.total_loan / limit)
        outstanding_amount = lender_report.outstanding_amount
        total_loan = lender_report.total_loan
        page_str = "{}/{}".format(page, total_page)

    return {
        "statusCode": status_code,
        "statusMessage": status_message,
        "statementMonth": statement_month,
        "totalOutstanding": outstanding_amount,
        "totalLoan": total_loan,
        "page": page_str,
        "data": data,
    }

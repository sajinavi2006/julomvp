from __future__ import division
from builtins import str
from builtins import range
import os
import math
import logging
import json
from django.utils import timezone
from django.db import transaction
from past.utils import old_div
from django.conf import settings
from dateutil.relativedelta import relativedelta
from juloserver.julo.models import (
    Application,
    FDCActiveLoanChecking,
    FDCInquiry
)
from juloserver.julo.exceptions import JuloException
from rest_framework import status as http_status_codes

from juloserver.julo.formulas import (
    round_rupiah,
    determine_first_due_dates_by_payday,
    round_rupiah_grab
)
from juloserver.julo.models import (
    Loan,
    StatusLookup,
    Payment,
    CreditMatrixProductLine
)
from juloserver.julocore.python2.utils import py2round
from juloserver.grab.services.bank_account_related import grab_get_self_bank_account_destination
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.account.models import AccountProperty, AccountTransaction
from juloserver.loan.constants import (
    LoanStatusChangeReason,
    FDCUpdateTypes
)
from juloserver.loan.services.loan_related import (
    get_transaction_type,
    get_info_active_loan_from_platforms
)
from juloserver.account.services.credit_limit import (
    get_credit_matrix,
    get_credit_matrix_parameters_from_account_property
)
from juloserver.account.constants import PaymentFrequencyType
from juloserver.grab.models import GrabPaymentTransaction, GrabAPILog
from juloserver.grab.clients.paths import GrabPaths
from juloserver.account_payment.models import AccountPayment
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from ..models import GrabLoanInquiry, GrabLoanData, GrabPaymentData
from ..exceptions import GrabLogicException
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.grab.constants import (GRAB_ACCOUNT_LOOKUP_NAME,
                                       GRAB_AUTH_API_MAPPING)
from juloserver.grab.tasks import trigger_application_creation_grab_api
from juloserver.julo.constants import WorkflowConst
from juloserver.grab.services.fdc import get_fdc_inquiry_data

logger = logging.getLogger(__name__)
grab_auth_api_error_codes = set(list(GRAB_AUTH_API_MAPPING.keys()))


def generate_loan_payment_grab(application, account, loan_requested, loan_purpose, credit_matrix):
    with transaction.atomic():
        today_date = timezone.localtime(timezone.now()).date()
        oldest_loan = Loan.objects.filter(account=account).first()
        due_date = today_date + relativedelta(days=3)
        while True:
            if due_date.weekday() not in [5, 6]:
                break
            due_date = due_date + relativedelta(days=1)

        first_payment_date = get_due_date_based_on_holiday(due_date)
        principal_rest, interest_rest, installment_rest = compute_payment_installment_grab(
            loan_requested['loan_amount'],
            loan_requested['loan_duration_request'],
            loan_requested['interest_rate_monthly'])

        # principal_first, interest_first, installment_first = \
        #     compute_first_payment_installment_grab(
        #         loan_requested['loan_amount'],
        #         loan_requested['loan_duration_request'],
        #         loan_requested['interest_rate_monthly'],
        #     )

        bank_account_destination = grab_get_self_bank_account_destination(application.customer)
        if bank_account_destination:
            bank_account_destination = bank_account_destination.last()
            name_bank_validation_id = bank_account_destination.name_bank_validation_id

        loan = Loan.objects.create(
            customer=application.customer,
            loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE),
            product=loan_requested['product'],
            loan_amount=loan_requested['loan_amount'],
            loan_duration=loan_requested['loan_duration_request'],
            first_installment_amount=installment_rest,
            installment_amount=installment_rest,
            bank_account_destination=bank_account_destination,
            name_bank_validation_id=name_bank_validation_id,
            account=application.account,
            loan_purpose=loan_purpose,
            credit_matrix=credit_matrix
        )
        loan.cycle_day = first_payment_date.day
        loan.loan_disbursement_amount = loan.loan_amount - loan_requested['admin_fee']
        loan.set_sphp_expiration_date()
        loan.sphp_sent_ts = timezone.localtime(timezone.now())
        # set payment method for Loan
        # customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
        # if customer_has_vas:
        #     primary_payment_method = customer_has_vas.filter(is_primary=True).last()
        #     if primary_payment_method:
        #         loan.julo_bank_name = primary_payment_method.payment_method_name
        #         loan.julo_bank_account_number = primary_payment_method.virtual_account
        loan.save()

        grab_loan_inquiry = loan_requested['grab_loan_inquiry']

        grab_loan_data = GrabLoanData.objects.filter(grab_loan_inquiry=grab_loan_inquiry,
                                                     loan_id__isnull=True).last()
        if not grab_loan_data:
            raise GrabLogicException('Grab Loan Data Does not exist')
        grab_loan_data.loan = loan
        grab_loan_data.save()

        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for payment_number in range(loan.loan_duration):
            if account.account_lookup.payment_frequency == PaymentFrequencyType.DAILY:
                if payment_number == 0:
                    principal, interest, installment = \
                        principal_rest, interest_rest, installment_rest
                elif payment_number == int(loan.loan_duration) - 1:
                    principal, interest, installment = compute_final_payment_principal_grab(
                        loan_requested['loan_amount'],
                        loan_requested['loan_duration_request'],
                        loan_requested['interest_rate_monthly'],
                        principal_rest,
                        interest_rest
                    )
                else:
                    principal, interest, installment = principal_rest, interest_rest, installment_rest
                due_date = first_payment_date + relativedelta(days=payment_number)
                payment = Payment.objects.create(
                    loan=loan,
                    payment_status=payment_status,
                    payment_number=payment_number + 1,
                    due_date=due_date,
                    due_amount=installment,
                    installment_principal=principal,
                    installment_interest=interest)

                logger.info({
                    'action': 'generate_payment_grab',
                    'application': application.id,
                    'loan': loan,
                    'payment_number': payment_number,
                    'payment_amount': payment.due_amount,
                    'due_date': due_date,
                    'payment_status': payment.payment_status.status,
                    'status': 'payment_created'
                })
        return loan


def compute_first_payment_installment_grab(loan_amount, loan_duration, monthly_interest_rate):
    days_in_month = 30.0
    daily_interest_rate = float(monthly_interest_rate) / days_in_month
    principal = int(math.floor(float(loan_amount) / float(loan_duration)))
    adjusted_interest = float(loan_amount) * daily_interest_rate / float(loan_duration)
    # adjusted_interest = int(math.floor((float(delta_days) / days_in_month) * basic_interest))

    installment_amount = round_rupiah(principal + adjusted_interest)
    derived_adjusted_interest = installment_amount - principal

    return principal, derived_adjusted_interest, installment_amount


def compute_payment_installment_grab(loan_amount, loan_duration_days, monthly_interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    days_in_month = 30.0
    daily_interest_rate = float(monthly_interest_rate) / days_in_month
    principal = round_rupiah_grab(py2round(float(loan_amount) / loan_duration_days))
    installment_amount = int(
        math.ceil((float(loan_amount) / loan_duration_days) + (old_div(daily_interest_rate, 100) *
                                                               float(loan_amount)))
    )
    derived_interest = installment_amount - principal

    return principal, derived_interest, installment_amount


def compute_final_payment_principal_grab(
        loan_amount, loan_duration_days, monthly_interest_rate,
        installment_principal, derived_interest):
    """
    Computes installment, principal and interest for final payment
    """

    days_in_month = 30.0
    daily_interest_rate = float(monthly_interest_rate) / days_in_month
    total_principal = installment_principal * loan_duration_days
    pending_amount = loan_amount - total_principal
    final_instalment_principal = installment_principal + pending_amount
    total_interest = int(
        math.ceil((old_div(daily_interest_rate, 100) *
                  float(loan_amount)) * loan_duration_days)
    )
    interest_difference = total_interest - (derived_interest * loan_duration_days)
    final_instalment_interest = derived_interest + interest_difference
    final_installment_amount = final_instalment_interest + final_instalment_principal

    return final_instalment_principal, final_instalment_interest, final_installment_amount


def get_loan_amount_by_transaction_type(loan_amount, origination_fee_percentage, is_withdraw_funds):
    decrease_amount = loan_amount
    if not is_withdraw_funds:
        decrease_amount = int(round(old_div(loan_amount, (1 - origination_fee_percentage))))
    return decrease_amount


def get_credit_matrix_and_credit_matrix_product_line_grab(application, is_self_bank_account=True):
    customer = application.customer
    account = application.account
    transaction_type = get_transaction_type(is_self_bank_account)

    account_property = AccountProperty.objects.filter(account=account).last()
    if not account_property:
        return None, None

    credit_matrix_params = get_credit_matrix_parameters_from_account_property(
        application, account_property)
    if not credit_matrix_params:
        return None, None

    credit_matrix = get_credit_matrix(credit_matrix_params, transaction_type)

    credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
        credit_matrix=credit_matrix, product=application.product_line
    ).last()

    return credit_matrix, credit_matrix_product_line


def grab_loan_disbursement_success(loan):
    loan.refresh_from_db()
    loan.set_fund_transfer_time()
    loan.save()

    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.CURRENT,
        change_reason=LoanStatusChangeReason.ACTIVATED
    )

    payments = loan.payment_set.normal().not_paid_active()\
        .order_by('payment_number')
    status_code = StatusLookup.objects.get_or_none(
        status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
    for payment in payments:
        account_payment = AccountPayment.objects.get_or_none(
            account=loan.account, due_date=payment.due_date
        )
        if not account_payment:
            account_payment = AccountPayment.objects.create(
                account=loan.account,
                due_date=payment.due_date,
                late_fee_amount=0,
                status=status_code,
            )
        else:
            status = account_payment.status.status_code
            if status >= PaymentStatusCodes.PAID_ON_TIME:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'New payment added'
                }
                account_payment.change_status(PaymentStatusCodes.PAYMENT_NOT_DUE)
                account_payment.save(update_fields=['status'])
                account_payment.create_account_payment_status_history(history_data)

        account_payment.due_amount += payment.due_amount
        account_payment.principal_amount += payment.installment_principal
        account_payment.interest_amount += payment.installment_interest
        account_payment.save(update_fields=[
                'due_amount', 'principal_amount', 'interest_amount'])
        payment.update_safely(account_payment=account_payment)

    transaction_amount = loan.loan_amount * -1
    AccountTransaction.objects.create(
        account=loan.account,
        payback_transaction=None,
        disbursement_id=loan.disbursement_id,
        transaction_date=loan.fund_transfer_ts,
        transaction_amount=transaction_amount,
        transaction_type='disbursement',
        towards_principal=transaction_amount,
        towards_interest=0,
        towards_latefee=0,
    )


def get_due_date_based_on_holiday(date):
    json_file = 'public_holiday.json'
    file = os.path.join(settings.BASE_DIR, 'juloserver', 'julo', 'helpers',
                        json_file)
    filepath = os.path.abspath(file)

    with open(filepath, 'r') as f:
        restricted_dates = json.loads(f.read())
    while True:
        if str(date) not in restricted_dates:
            break
        date = date + relativedelta(days=1)
    return date


def process_grab_loan_signature_upload_success(loan):
    loan.sphp_accepted_ts = timezone.localtime(timezone.now())
    loan.save(update_fields=['sphp_accepted_ts', 'udate'])
    loan.refresh_from_db()
    accept_julo_sphp(loan, "JULO")


def update_grab_transaction_id(payment, txn_id, payment_amount):
    if not payment.loan.account:
        return
    account = payment.loan.account
    if not account.account_lookup.name == GRAB_ACCOUNT_LOOKUP_NAME:
        return

    GrabPaymentTransaction.objects.create(
        transaction_id=txn_id,
        payment=payment,
        payment_amount=payment_amount,
        loan=payment.loan
    )


def update_payments_for_resumed_loan(loan, resume_date, halt_date):
    payments = Payment.objects.filter(loan=loan).not_paid_active().only('id').order_by(
        'payment_number')

    days_diff = (resume_date - halt_date).days

    status_code = StatusLookup.objects.get_or_none(
        status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
    fields_to_check = [
        'due_date',
        'due_amount',
        'late_fee_amount',
        'paid_amount',
        'installment_interest',
        'installment_principal',
        'paid_interest',
        'paid_principal'
    ]
    payment_ids = payments.values_list('id', flat=True)
    with transaction.atomic():
        loan_count = Loan.objects.filter(
            account=loan.account,
            loan_status__in={
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.LOAN_1DPD,
                LoanStatusCodes.LOAN_5DPD,
                LoanStatusCodes.LOAN_30DPD,
                LoanStatusCodes.LOAN_60DPD,
                LoanStatusCodes.LOAN_90DPD,
                LoanStatusCodes.LOAN_120DPD,
                LoanStatusCodes.LOAN_150DPD,
                LoanStatusCodes.LOAN_180DPD,
                LoanStatusCodes.HALT
            }
        ).count()

        with transaction.atomic():
            payments = Payment.objects.select_related(
                'account_payment', 'account_payment__status').filter(
                id__in=payment_ids)
            for payment in payments.iterator():
                account_payment = payment.account_payment
                payment_flag = True
                for field_to_check in fields_to_check:
                    field_to_check_acc = field_to_check
                    if field_to_check == 'installment_interest':
                        field_to_check_acc = 'interest_amount'
                    elif field_to_check == 'installment_principal':
                        field_to_check_acc = 'principal_amount'
                    if getattr(payment.account_payment, field_to_check_acc) != getattr(payment, field_to_check):
                        payment_flag = False
                        break

                due_date = payment.due_date + relativedelta(days=days_diff)
                payment.update_safely(due_date=due_date)

                if payment_flag and loan_count <= 1:
                    payment_due_date = payment.due_date
                    account_payment.update_safely(due_date=payment_due_date)
                    continue

                due_date_account_payment = AccountPayment.objects.get_or_none(
                    account=loan.account, due_date=payment.due_date
                )

                if due_date_account_payment != account_payment:
                    fields_to_update = dict()
                    fields_to_update['due_amount'] = account_payment.due_amount - payment.due_amount
                    fields_to_update['principal_amount'] = \
                        account_payment.principal_amount - payment.installment_principal
                    fields_to_update['interest_amount'] = \
                        account_payment.interest_amount - payment.installment_interest
                    fields_to_update['paid_amount'] = \
                        account_payment.paid_amount - payment.paid_amount
                    fields_to_update['paid_principal'] = \
                        account_payment.paid_principal - payment.paid_principal
                    fields_to_update['paid_interest'] = \
                        account_payment.paid_interest - payment.paid_interest
                    fields_to_update['paid_late_fee'] = \
                        account_payment.paid_late_fee - payment.paid_late_fee
                    account_payment.update_safely(**fields_to_update)

                    if account_payment.due_amount == 0:
                        status = account_payment.status.status_code
                        if status < PaymentStatusCodes.PAID_ON_TIME:
                            history_data = {
                                'status_old': account_payment.status,
                                'change_reason': 'Payment updated on Loan Resume'
                            }
                            account_payment.change_status(PaymentStatusCodes.PAID_ON_TIME)
                            account_payment.save(update_fields=['status'])
                            account_payment.create_account_payment_status_history(history_data)

                if not due_date_account_payment:
                    due_date_account_payment = AccountPayment.objects.create(
                        account=loan.account,
                        due_date=payment.due_date,
                        late_fee_amount=0,
                        status=status_code,
                        paid_amount=0,
                        paid_principal=0,
                        paid_interest=0,
                        paid_late_fee=0
                    )
                else:
                    status = due_date_account_payment.status.status_code
                    if status >= PaymentStatusCodes.PAID_ON_TIME:
                        history_data = {
                            'status_old': due_date_account_payment.status,
                            'change_reason': 'New payment added'
                        }
                        due_date_account_payment.change_status(PaymentStatusCodes.PAYMENT_NOT_DUE)
                        due_date_account_payment.save(update_fields=['status'])
                        due_date_account_payment.create_account_payment_status_history(history_data)

                fields_to_update = dict()
                fields_to_update['due_amount'] = due_date_account_payment.due_amount + payment.due_amount
                fields_to_update['principal_amount'] = \
                    due_date_account_payment.principal_amount + payment.installment_principal
                fields_to_update['interest_amount'] = \
                    due_date_account_payment.interest_amount + payment.installment_interest
                fields_to_update['paid_amount'] = \
                    due_date_account_payment.paid_amount + payment.paid_amount
                fields_to_update['paid_principal'] = \
                    due_date_account_payment.paid_principal + payment.paid_principal
                fields_to_update['paid_interest'] = \
                    due_date_account_payment.paid_interest + payment.paid_interest
                fields_to_update['paid_late_fee'] = \
                    due_date_account_payment.paid_late_fee + payment.paid_late_fee
                due_date_account_payment.update_safely(**fields_to_update)
                payment.update_safely(account_payment=due_date_account_payment)


def check_grab_auth_success(loan_id):
    loan = Loan.objects.get_or_none(id=loan_id)
    if not loan:
        return False
    if loan.account.account_lookup.workflow.name != WorkflowConst.GRAB:
        return False
    return GrabAPILog.objects.filter(
        loan_id=loan.id,
        query_params__contains=GrabPaths.LOAN_CREATION,
        http_status_code=http_status_codes.HTTP_200_OK
    ).exists()


def get_change_reason_and_loan_status_change_mapping_grab(error_code):
    """
        To be used at 210 status for Grab Loans.
        This error code input is the error code we get from
        Loan creation API(auth API) for grab
    """
    if type(error_code) == str:
        error_code = int(error_code)
    if not error_code:
        raise GrabLogicException("Invalid Error Code")
    if int(error_code) not in grab_auth_api_error_codes:
        error_code = 'default'
    status_to_be_changed, change_reason = GRAB_AUTH_API_MAPPING.get(error_code)
    return status_to_be_changed, change_reason


def get_fdc_active_loan_check(customer_id):
    fdc_active_loan_checking, is_created = FDCActiveLoanChecking.objects.get_or_create(
        customer_id=customer_id
    )
    if not is_created:
        fdc_active_loan_checking.last_access_date = timezone.localtime(timezone.now()).date()
        fdc_active_loan_checking.save()

    return fdc_active_loan_checking


def is_user_have_active_loans(customer_id):
    if Loan.objects.filter(
        customer_id=customer_id,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
    ).exclude(loan_status_id=LoanStatusCodes.LOAN_INVALIDATED).exists():
        return True

    return False


def is_below_allowed_platforms_limit(number_of_allowed_platforms, fdc_inquiry,
                                     fdc_active_loan_checking):
    nearest_due_date, count_other_platforms, _ = get_info_active_loan_from_platforms(
        fdc_inquiry_id=fdc_inquiry.id
    )
    fdc_active_loan_checking.last_updated_time = timezone.now()
    fdc_active_loan_checking.nearest_due_date = nearest_due_date
    fdc_active_loan_checking.number_of_other_platforms = count_other_platforms
    fdc_active_loan_checking.save()

    if count_other_platforms < number_of_allowed_platforms:
        return True

    return False


def is_dax_eligible_other_active_platforms(
    application_id,
    fdc_data_outdated_threshold_days,
    number_of_allowed_platforms,
    is_grab=False
):
    result = {
        'is_eligible': False,
        'is_out_date': False,
        'is_pending': False,
        'is_fdc_exists': False
    }

    application = Application.objects.get_or_none(id=application_id)
    if not application:
        raise JuloException('Application id = {} not found.'.format(application_id))

    customer_id = application.customer_id
    fdc_active_loan_checking = get_fdc_active_loan_check(customer_id=customer_id)

    if is_user_have_active_loans(customer_id=customer_id):
        result.update({"is_eligible": True, 'is_fdc_exists': True})
        return result

    fdc_inquiry_dict = get_fdc_inquiry_data(
        application_id=application_id, day_diff=fdc_data_outdated_threshold_days
    )
    fdc_inquiry = fdc_inquiry_dict.get("fdc_inquiry")
    is_out_date = fdc_inquiry_dict.get("is_out_date")
    is_pending = fdc_inquiry_dict.get("is_pending")
    result.update({
        "is_out_date": is_out_date,
        "is_pending": is_pending,
        "is_fdc_exists": True if fdc_inquiry else False
    })

    if not fdc_inquiry:
        # return True to continue the loan to x210, cronjob will update the status before go to x211
        result.update({"is_eligible": False if is_grab else True})
        return result

    is_eligible = is_below_allowed_platforms_limit(
        number_of_allowed_platforms=number_of_allowed_platforms,
        fdc_inquiry=fdc_inquiry,
        fdc_active_loan_checking=fdc_active_loan_checking
    )
    result.update({"is_eligible": is_eligible})
    return result


def create_fdc_inquiry(customer, params):
    fdc_inquiry = FDCInquiry.objects.create(
        nik=customer.nik, customer_id=customer.pk, application_id=params['application_id']
    )
    fdc_inquiry_data = {'id': fdc_inquiry.pk, 'nik': customer.nik}
    return fdc_inquiry, fdc_inquiry_data


def execute_fdc_inquiry_other_active_loans_from_platforms_task_grab(
    fdc_inquiry_data, customer, update_type, params
):
    from juloserver.loan.tasks.lender_related import (
        fdc_inquiry_other_active_loans_from_platforms_task,
    )

    fdc_inquiry_other_active_loans_from_platforms_task.apply_async(
        (fdc_inquiry_data, customer.pk, update_type, params),
        queue="grab_global_queue"
    )


def create_fdc_inquiry_and_execute_check_active_loans_for_grab(
    customer,
    params,
    update_type=FDCUpdateTypes.
    AFTER_LOAN_STATUS_x211
):
    fdc_inquiry, fdc_inquiry_data = create_fdc_inquiry(customer, params)

    params['fdc_inquiry_id'] = fdc_inquiry.pk
    execute_fdc_inquiry_other_active_loans_from_platforms_task_grab(
        fdc_inquiry_data=fdc_inquiry_data,
        customer=customer,
        update_type=update_type,
        params=params
    )


def get_loan_repayment_amount(loan_amount, loan_duration_days, monthly_interest_rate):
    days_in_month = 30.0
    daily_interest_rate = float(monthly_interest_rate) / days_in_month
    repayment_amount = int(math.ceil(loan_amount +
                                     ((old_div(daily_interest_rate, 100) * float(loan_amount)) * loan_duration_days)))

    return repayment_amount

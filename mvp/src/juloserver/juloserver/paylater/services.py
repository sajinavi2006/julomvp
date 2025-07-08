from builtins import str
from builtins import object
import logging
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.db import transaction, models
from juloserver.julo.models import (Customer,
                                    StatusLookup,
                                    CreditScore,
                                    Application,
                                    PartnerBankAccount,
                                    FeatureSetting,
                                    )
from juloserver.julo.exceptions import JuloException
from juloserver.julo.utils import display_rupiah
from juloserver.julo.statuses import (LoanStatusCodes,
                                      PaymentStatusCodes,
                                      JuloOneCodes)
from juloserver.disbursement.models import BcaTransactionRecord as Btr
from juloserver.paylater.utils import get_interest_rate
from .models import (AccountCreditLimit,
                     LoanOne,
                     PaymentSchedule,
                     TransactionRefundDetail,
                     TransactionOne,
                     Statement,
                     StatementHistory,
                     AccountCreditHistory,
                     DisbursementSummary,
                     BukalapakWhitelist,
                     StatementEvent,
                     StatementNote,
                     InitialCreditLimit,
                     TransactionPaymentDetail
                     )
from .constants import StatementEventConst, LineTransactionType
from juloserver.paylater.utils import get_late_fee_rules
from juloserver.disbursement.services import trigger_disburse
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.disbursement.constants import (NameBankValidationStatus,
                                               XfersDisbursementStep,
                                               DisbursementVendors)
from juloserver.apiv2.models import (PdBukalapakModelResult,
                                     PdBukalapakUnsupervisedModelResult,
                                     AutoDataCheck)
from .constants import PaylaterCreditMatrix, PaylaterConst
from juloserver.julo.constants import ScoreTag
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from babel.numbers import parse_number

from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services import process_application_status_change
from juloserver.disbursement.tasks import application_bulk_disbursement_tasks

from juloserver.followthemoney.models import LenderTransactionMapping

logger = logging.getLogger(__name__)


def calculate_limit(probabilty, cluster):
    initialcreditlimit = InitialCreditLimit.objects.filter(
        score_first__lte=probabilty, score_last__gt=probabilty, cluster_type=cluster
    ).order_by('-score_first').first()

    if not initialcreditlimit:
        initialcreditlimit = InitialCreditLimit.objects.filter(
            score_first=None, score_last=None, cluster_type=cluster
        ).first()

    if not initialcreditlimit:
        initialcreditlimit = InitialCreditLimit.objects.get_or_none(cluster_type='Default')

    return initialcreditlimit.initial_credit_limit

def calculate_score(email, probabilty, cluster):
    whitelisted_customer = BukalapakWhitelist.objects.filter(email__iexact=email).last()
    threshold = PaylaterCreditMatrix.A_THRESHOLD
    good_cluster = (PaylaterCreditMatrix.MVP_CLUSTER, PaylaterCreditMatrix.POTENTIAL_MVP_CLUSTER)

    limit = calculate_limit(probabilty, cluster)

    if not whitelisted_customer:
        return 'C', 0

    if whitelisted_customer.group == "experiment":
        return 'A', limit

    if probabilty >= threshold and cluster in good_cluster:
        return 'A', limit
    else:
        return 'C', 0

def get_paylater_credit_score(application_id):
    #import in each function because circular import
    from .tasks import call_bukalapak_endpoint
    credit_score = CreditScore.objects.get_or_none(application_id=application_id)
    if credit_score:
        return credit_score

    credit_model_result = PdBukalapakModelResult.objects.filter(
        application_id=application_id).last()
    if not credit_model_result:
        return None

    cluster_model_result = PdBukalapakUnsupervisedModelResult.objects.filter(
        application_id=application_id).last()
    if not cluster_model_result:
        return None

    failed_checks = AutoDataCheck.objects.filter(
        application_id=application_id, is_okay=False)
    first_failed_check = None
    failed_checks = failed_checks.values_list('data_to_check', flat=True)
    if failed_checks:
        check_order = PaylaterConst.BINARY_CHECK
        for check in check_order:
            if check in failed_checks:
                first_failed_check = check
                break

        if first_failed_check:
            score = 'C'
            score_tag = ScoreTag.C_FAILED_BINARY
            limit = 0
    application = Application.objects.get_or_none(pk=application_id)
    if not first_failed_check:
        score, limit = calculate_score(application.customer.email,
                                       credit_model_result.probability_fpd,
                                       cluster_model_result.cluster_type)
        score_tag = ScoreTag.C_LOW_CREDIT_SCORE if score == 'C' else 'good_score'

    line = application.customer.customercreditlimit
    try:
        with transaction.atomic():
            credit_score = CreditScore.objects.create(
                application_id=application_id,
                score=score,
                products_str=PaylaterConst.PARTNER_NAME,
                message=score_tag,
                score_tag=score_tag,
                failed_checks=list(failed_checks)
            )

            update_data = dict(
                credit_score=credit_score,
                customer_credit_limit=limit,
            )

            if credit_score.score == 'C':
                update_data.update(dict(
                    customer_credit_active_date=timezone.localtime(timezone.now()),
                    customer_credit_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                ))
                call_bukalapak_endpoint.delay(application.id)
            else:
                sms_activation_scheduler(application_id)

            line.update_safely(**update_data)
    except Exception as e:
        logger.error({
            'task': 'get_paylater_credit_score',
            'app_id': application_id,
            'errors': str(e)
        })
        raise Exception(e)

    return credit_score

def generate_new_statement(invoice):
    today = timezone.localtime(timezone.now()).date()
    if today.day >= 28:
        due_date = today + relativedelta(day=28, months=1)
    else:
        due_date = today + relativedelta(day=28)
    not_due_status = StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_NOT_DUE)
    paid_refund = StatusLookup.objects.get(pk=PaymentStatusCodes.PAID_REFUND)

    # generate subscription_fee/ interest fee
    # get statement with interest_fee at this period
    last_statement = Statement.objects.filter(
        customer_credit_limit=invoice.customer_credit_limit,
        account_credit_limit=invoice.account_credit_limit,
        statement_due_date=due_date, statement_interest_amount__gt=0).exclude(
        statement_status=paid_refund
    )

    interest_amount = 0
    if not last_statement:
        credit_limit = invoice.account_credit_limit.account_credit_limit
        interest_rate = get_interest_rate(invoice.account_credit_limit.id)
        interest_amount = credit_limit * interest_rate

    last_statement = Statement.objects.create(
        customer_credit_limit=invoice.customer_credit_limit,
        account_credit_limit=invoice.account_credit_limit,
        statement_due_date=due_date,
        statement_due_amount=interest_amount,
        statement_interest_amount=interest_amount,
        statement_principal_amount=0,
        statement_transaction_fee_amount=0,
        statement_status=not_due_status)

    generate_statement_history(last_statement, PaymentStatusCodes.PAYMENT_NOT_DUE, "created_by_API")
    return last_statement


def generate_loan_one_and_payment(transaction_id):
    transaction_one = TransactionOne.objects.get(pk=transaction_id)
    invoice = transaction_one.invoice
    customer = transaction_one.customer_credit_limit.customer
    partner = transaction_one.account_credit_limit.partner
    statement = transaction_one.statement
    loan_one = LoanOne.objects.create(
        transaction=transaction_one,
        loan_amount=transaction_one.transaction_amount,
        loan_duration=1,
        installment_amount=transaction_one.transaction_amount,
        customer=customer,
        loan_one_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
        partner=partner)

    payment_schedule = PaymentSchedule.objects.create(
        loan_one=loan_one,
        due_date=statement.statement_due_date,
        due_amount=transaction_one.transaction_amount,
        interest_amount=0,
        principal_amount=transaction_one.disbursement_amount,
        transaction_fee_amount=invoice.transaction_fee_amount,
        status=StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_NOT_DUE),
        statement=statement)


def update_loan_one_and_payment(transaction_obj, paid_date):
    try:
        with transaction.atomic():
            if transaction_obj.transaction_type == 'debit':
                loan_one = transaction_obj.loanone
                loan_one.change_status(LoanStatusCodes.PAID_OFF)
                loan_one.save()

                payment_schedules = loan_one.paymentschedule_set.all()
                grace_period = payment_schedules.statement.statement_due_date + relativedelta(day=6, months=1)
                grace_period_timedelta = grace_period - payment_schedules.statement.statement_due_date
                grace_period_days = grace_period_timedelta.days

                for payment_schedule in payment_schedules:
                    late_days = payment_schedule.statement.paid_late_days
                    if late_days <= 0:
                        payment_schedule_status = PaymentStatusCodes.PAID_ON_TIME
                    elif late_days < grace_period_days:
                        payment_schedule_status = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
                    else:
                        payment_schedule_status = PaymentStatusCodes.PAID_LATE

                    payment_schedule.status = payment_schedule_status
                    payment_schedule.paid_date = paid_date
                    payment_schedule.paid_interest = payment_schedule.interest_amount
                    payment_schedule.paid_principal = payment_schedule.principal_amount
                    payment_schedule.paid_late_fee = payment_schedule.late_fee_amount
                    payment_schedule.paid_transaction_fee = payment_schedule.transaction_fee_amount
                    payment_schedule.paid_amount = payment_schedule.due_amount

                    payment_schedule.save()
    except Exception as e:
        logger.error({
            'action_view': 'update_loan_one_and_payment',
            'data': transaction_obj,
            'errors': str(e)
        })
        JuloException(e)
        pass


def generate_refund_detail(transaction_obj):
    # create refund detail
    invoice_trans = TransactionOne.objects.prefetch_related(
        'loanone', 'loanone__paymentschedule_set',
        'statement').filter(
        invoice=transaction_obj.invoice,
        transaction_description='invoice').last()

    refund_detail = TransactionRefundDetail.objects.create(
        invoice=transaction_obj.invoice,
        invoice_detail=transaction_obj.invoice_detail,
        loan_one=invoice_trans.loanone,
        transaction=transaction_obj,
        refund_amount=transaction_obj.transaction_amount
    )

    return refund_detail


def generate_statement_history(statement_obj, status_new, change_reason=None):
    status_old = statement_obj.statement_status.status_code

    StatementHistory.objects.create(
        statement=statement_obj,
        status_old=status_old,
        status_new=status_new,
        change_reason=change_reason
    )


def generate_accountcredit_history(accountcredit_obj, status_new, change_reason=None):
    status_old = accountcredit_obj.account_credit_status.status_code

    AccountCreditHistory.objects.create(
        account_credit=accountcredit_obj,
        status_old=status_old,
        status_new=status_new,
        change_reason=change_reason
    )

@transaction.atomic()
def update_late_fee_amount(statement_id):
    statement = Statement.objects.get_or_none(id=statement_id)
    account_credit = statement.account_credit_limit
    statement_old_status = statement.statement_status

    if statement.statement_late_fee_amount >= statement.statement_principal_amount:
        logger.warning({
            'warning': 'late fee applied maximum times',
            'late_fee_applied': statement.statement_late_fee_applied,
            'statement_id': statement.id,
        })
        return

    today = date.today()
    grace_period = statement.statement_due_date + relativedelta(day=6, months=1)
    late_fee = get_late_fee_rules(account_credit.account_credit_limit)

    if grace_period <= today:
        late_fee_before = statement.statement_late_fee_amount
        statement.statement_late_fee_amount += late_fee
        if statement.statement_late_fee_amount >= statement.statement_principal_amount:
            statement.statement_late_fee_amount = statement.statement_principal_amount

        late_fee_got = statement.statement_late_fee_amount - late_fee_before
        statement.statement_late_fee_applied += 1
        statement.statement_due_amount += late_fee_got

        if late_fee_got > 0:
            # include deleted late fee to transaction one
            transaction_type = LineTransactionType.TYPE_LATEFEE['type']
            transaction_desc = LineTransactionType.TYPE_LATEFEE['name']
            include_to_transaction_one(statement, late_fee_got, transaction_type, transaction_desc)

    statement.update_status_based_on_due_date()
    if statement.statement_status != statement_old_status:
        generate_statement_history(statement, statement.statement_status.status_code, "late_fee scheduler")

    statement.save()


def process_bank_validation(partner, method):
    bank_account = PartnerBankAccount.objects.get(partner=partner)

    # prepare data to validate
    data_to_validate = {'name_bank_validation_id': bank_account.name_bank_validation_id,
                        'bank_name': bank_account.bank_name,
                        'account_number': bank_account.bank_account_number,
                        'name_in_bank': bank_account.name_in_bank,
                        'mobile_phone': str(bank_account.phone_number),
                        'application': None
                        }
    if method == 'Bca':
        method = 'Xfers'

    validation = trigger_name_in_bank_validation(data_to_validate, method)

    # assign validation_id to partner bank account
    validation_id = validation.get_id()
    bank_account.name_bank_validation_id = validation_id
    bank_account.save(update_fields=['name_bank_validation_id'])
    validation.validate()
    validation_data = validation.get_data()

    if validation.is_success():
        note = 'Name in Bank Validation Success via %s' % (validation_data['method'])
        return validation_id, note

    elif validation.is_failed():
        note = 'Name in Bank Validation Failed via %s' % (validation_data['method'])
        return None, note


def process_bulk_disbursement(summary_id, method, user):
    disbursement_summary = DisbursementSummary.objects.get_or_none(id=summary_id)

    # Set default value
    partner = disbursement_summary.partner
    type_data_to_disburse = "loan_one"
    disburse_target = partner.name

    # retry disbursement
    if disbursement_summary.disbursement and disbursement_summary.disbursement.disburse_status == "FAILED":
        disbursement_ = disbursement_summary.disbursement

        disbursement_.retry_times += 1
        disbursement_.save(update_fields=['retry_times', 'udate'])
        disbursement_.refresh_from_db()
        if disbursement_.method == 'Bca':
            btr = Btr.objects.filter(reference_id=disbursement_.external_id).last()
            if btr:
                btr.reference_id += str(disbursement_.retry_times)
                btr.save()

    if not disbursement_summary.disbursement:
        if disbursement_summary.product_line_id in ProductLineCodes.bulk_disbursement():
            applications = Application.objects.filter(pk__in=disbursement_summary.transaction_ids)
            application = applications.last()
            partner = application.partner if application else None
            type_data_to_disburse = "bulk"
            disburse_target = "customer"

        if not partner:
            return {
                "status": "failed",
                "message": "failed partner",
                "reason": "Application has no Partner"
            }

        bank_validation_id, msg = process_bank_validation(partner, method)
        if not bank_validation_id:
            return {
                "status": "failed",
                "message": "failed disbursement",
                "reason": msg
            }

        data_to_disburse = {
            'disbursement_id': None,
            'name_bank_validation_id': bank_validation_id,
            'amount': disbursement_summary.transaction_amount,
            'external_id': disbursement_summary.disburse_xid,
            'type': type_data_to_disburse,
        }

    else:
        data_to_disburse = {
            'disbursement_id': disbursement_summary.disbursement_id,
            'name_bank_validation_id': disbursement_summary.disbursement.name_bank_validation_id
        }

    disbursement = trigger_disburse(data_to_disburse, method=method)
    disbursement_obj = disbursement.disbursement

    # update data disbursement summary & transaction one
    disbursement_summary.disbursement = disbursement_obj
    disbursement_summary.disburse_by = user
    disbursement_summary.save(update_fields=['disbursement', 'disburse_by'])

    if disbursement_summary.product_line_id not in ProductLineCodes.bulk_disbursement():
        transactions = TransactionOne.objects.filter(id__in=disbursement_summary.transaction_ids)
        transactions.update(disbursement=disbursement_obj)

    # do disbursement process
    disbursement.disburse()
    disbursement_data = disbursement.get_data()

    # check disbursement status
    # default disbursement.is_pending() == True
    status = "success"
    message = "Pending"
    next_status = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL

    if disbursement.is_success():
        message = "Successful"

    if disbursement.is_failed():
        message = "Failed"
        next_status = ApplicationStatusCodes.FUND_DISBURSAL_FAILED

    reason = 'Disbursement %s to %s Bank %s account number %s via %s' % (
        message, disburse_target, disbursement_data['bank_info']['bank_code'],
        disbursement_data['bank_info']['account_number'],
        disbursement_data['method'])

    if method == "Bca" and disbursement.get_type() == 'bulk':
        application_bulk_disbursement_tasks.delay(disbursement.get_id(), next_status, reason)

    return {
        "status": status,
        "message": "Disbursement {}".format(message),
        "reason": reason
    }


def activate_paylater(customer):
    # import in each function because circular import
    from .tasks import call_bukalapak_endpoint
    credit_limit = customer.customercreditlimit
    application = customer.application_set.filter(
            partner__name=PaylaterConst.PARTNER_NAME).last()

    credit_limit.update_safely(
        customer_credit_active_date=timezone.localtime(timezone.now()),
        customer_credit_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
    )

    call_bukalapak_endpoint.delay(application.id)


def sms_activation_scheduler(application_id):
    #import in each function because circular import
    from .tasks import sms_activation_paylater
    application = Application.objects.get_or_none(pk=application_id)
    scheduler = FeatureSetting.objects.get(feature_name=FeatureNameConst.SMS_ACTIVATION_PAYLATER)
    if scheduler.is_active == True:
        sms_activation_paylater.delay(application.customer.id)
    elif scheduler.is_active == False:
        activate_paylater(application.customer)


def process_rules_delete_latefee(statement, invoice_creation_date):
    grace_period_date = statement.statement_due_date + relativedelta(day=6, months=1)
    account_credit_limit = statement.account_credit_limit

    initial_late_fee = get_late_fee_rules(account_credit_limit.account_credit_limit)
    today = date.today()

    if invoice_creation_date != today:
        if invoice_creation_date >= grace_period_date:
            deltadate = invoice_creation_date - grace_period_date
            deltadays = deltadate.days + 1
            real_late_fee = deltadays * initial_late_fee

            deleted_late_fee = statement.statement_late_fee_amount - real_late_fee
            updated_statement_due_amount = statement.statement_due_amount - deleted_late_fee
            updated_statement_late_fee_amount = real_late_fee

            statement.update_safely(statement_due_amount=updated_statement_due_amount,
                                    statement_late_fee_amount=updated_statement_late_fee_amount)
            # create statement event
            event_date = timezone.localtime(timezone.now()).date()
            StatementEvent.objects.create(statement=statement,
                                          event_amount=deleted_late_fee,
                                          event_date=event_date,
                                          event_due_amount=updated_statement_due_amount,
                                          can_reverse=False,
                                          event_type=StatementEventConst.WAIVE_LATE_FEE)

        else:
            statement.statement_due_amount -= statement.statement_late_fee_amount
            deleted_late_fee = statement.statement_late_fee_amount
            statement.statement_late_fee_amount = 0
            statement.save(update_fields=['statement_late_fee_amount', 'statement_due_amount'])

        # include deleted late fee to transaction one
        transaction_type = LineTransactionType.TYPE_LATEFEE_VOID['type']
        transaction_desc = LineTransactionType.TYPE_LATEFEE_VOID['name']
        include_to_transaction_one(statement, deleted_late_fee, transaction_type, transaction_desc)


def process_suspend_account(account_credit_limit, late_days, grace_period_days):
    feature = FeatureSetting.objects.get(feature_name=FeatureNameConst.SUSPEND_ACCOUNT_PAYLATER)

    if feature.is_active:
        suspend_delay_days = grace_period_days + (feature.parameters.get('suspend_delay', 1) - 1)

        suspend_status = StatusLookup.objects.get(pk=JuloOneCodes.TERMINATED)

        if late_days >= suspend_delay_days:
            account_credit_limit.update_safely(
                account_credit_status=suspend_status
            )

            generate_accountcredit_history(account_credit_limit, JuloOneCodes.TERMINATED, "created_by_API")

            return True

    return False


def include_to_transaction_one(statement, amount, transaction_type, transaction_desc):
    """
    service for include additional transaction to transaction one
    exc: late_fee, late_fee_void, waive_late_fee, waive_late_fee_void
    """
    credit_limit = statement.customer_credit_limit
    account_credit_limit = statement.account_credit_limit
    today = timezone.now().date()

    TransactionOne.objects.create(
        customer_credit_limit=credit_limit,
        account_credit_limit=account_credit_limit,
        statement=statement,
        transaction_type=transaction_type,
        transaction_date=today,
        transaction_amount=amount,
        transaction_description=transaction_desc,
        transaction_status='paid')


class StatementEventServices(object):
    def get_dropdown_event(self, user_groups):
        dropdown = []

        if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2A in user_groups or\
           JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2B in user_groups or\
           JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3A in user_groups or\
           JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3B in user_groups or\
           JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_4 in user_groups or\
           JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_5 in user_groups or\
           JuloUserRoles.COLLECTION_SUPERVISOR in user_groups:
            dropdown = [{
                'value': 'waive_late_fee',
                'desc': 'Waive Late Fee'
            }]

        return dropdown

    def process_waive_late_fee(self, statement, data, agent):
        result = False
        statement_paid_status = (
            PaymentStatusCodes.PAID_ON_TIME,
            PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
            PaymentStatusCodes.PAID_LATE,
        )

        if statement.statement_status.status_code in statement_paid_status:
            return result

        event_type = StatementEventConst.WAIVE_LATE_FEE
        if 'waive_late_fee_amount_parsed' in data:
            waive_late_fee_amount = data['waive_late_fee_amount_parsed']
            event_type = data['event_type']
        else:
            waive_late_fee_amount = parse_number(data['waive_late_fee_amount'], locale='id_ID')


        if statement.statement_late_fee_amount < waive_late_fee_amount:
            return result

        event_date = timezone.localtime(timezone.now()).date()
        note = '[Add Event Waive Late Fee]\n\
                amount: {},\n\
                date: {},\n\
                note: {}.'.format(display_rupiah(waive_late_fee_amount),
                                  event_date.strftime('%m-%d-%Y'),
                                  data['note'])

        try:
            with transaction.atomic():
                statement_due_amount_before = statement.statement_due_amount
                statement_late_fee_amount_before = statement.statement_late_fee_amount
                updated_due_amount = statement_due_amount_before - waive_late_fee_amount
                updated_late_fee_amount = statement_late_fee_amount_before - waive_late_fee_amount

                statement.update_safely(statement_due_amount=updated_due_amount,
                                        statement_late_fee_amount=updated_late_fee_amount)

                # create statement event
                StatementEvent.objects.create(statement=statement,
                                              event_amount=waive_late_fee_amount,
                                              event_due_amount=statement_due_amount_before,
                                              event_date=event_date,
                                              event_type=event_type)
                # create statement note
                StatementNote.objects.create(
                    note_text=note,
                    statement=statement)

                logger.info({
                    'method': 'process_statement_event_type_waive_late_fee',
                    'status': 'success',
                    'statement_id': statement.id,
                    'waive_late_fee_amount': waive_late_fee_amount,
                    'event_date': event_date,
                    'due_amount_now': updated_due_amount
                })

                # include waive late fee to transaction one
                transaction_type = LineTransactionType.TYPE_WAIVE_LATEFEE['type']
                transaction_desc = LineTransactionType.TYPE_WAIVE_LATEFEE['name']
                include_to_transaction_one(statement, waive_late_fee_amount, transaction_type, transaction_desc)

                result = True
        except Exception as e:
            logger.info({
                'method': 'process_statement_event_type_waive_late_fee',
                'error': str(e),
                'status': 'failed',
                'statement_id': statement.id,
                'waive_late_fee_amount': waive_late_fee_amount,
                'event_date': event_date,
                'due_amount_before': statement_due_amount_before
            })

            raise Exception(e)

        return result

    def process_waive_interest_fee(self, statement, data):
        result = False
        statement_paid_status = (
            PaymentStatusCodes.PAID_ON_TIME,
            PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
            PaymentStatusCodes.PAID_LATE,
        )

        if statement.statement_status.status_code in statement_paid_status:
            return result

        event_type = data['event_type']
        interest_amount = data['interest_amount']

        if statement.statement_interest_amount < interest_amount:
            return result

        event_date = timezone.localtime(timezone.now()).date()
        note = '[Add Event Waive subscription Fee]\n\
                amount: {},\n\
                date: {},\n\
                note: {}.'.format(display_rupiah(interest_amount),
                                  event_date.strftime('%m-%d-%Y'),
                                  data['note'])

        try:
            with transaction.atomic():
                statement_due_amount_before = statement.statement_due_amount
                statement_interest_amount_before = statement.statement_interest_amount
                updated_subscription_amount = statement_interest_amount_before - interest_amount
                updated_due_amount = statement_due_amount_before - interest_amount

                statement.update_safely(statement_interest_amount=updated_subscription_amount,
                                        statement_due_amount=updated_due_amount)

                # create statement event
                StatementEvent.objects.create(statement=statement,
                                              event_amount=interest_amount,
                                              event_due_amount=statement_interest_amount_before,
                                              event_date=event_date,
                                              event_type=event_type)
                # create statement note
                StatementNote.objects.create(
                    note_text=note,
                    statement=statement)

                logger.info({
                    'method': 'process_statement_event_type_waive_late_fee',
                    'status': 'success',
                    'statement_id': statement.id,
                    'subscription_fee_amount': interest_amount,
                    'event_date': event_date,
                    'due_amount_now': updated_subscription_amount
                })

                result = True
        except Exception as e:
            logger.info({
                'method': 'process_statement_event_type_waive_late_fee',
                'error': str(e),
                'status': 'failed',
                'statement_id': statement.id,
                'waive_subscription_amount': interest_amount,
                'event_date': event_date,
                'due_amount_before': statement_due_amount_before
            })

            raise Exception(e)

        return result

    def create_reversal_statement_event(self, statement_event):
        logger.info({
            'action': 'reverse_statement_event',
            'statement_event': statement_event.id
        })

        statement_event.update_safely(can_reverse=False)
        StatementEvent.objects.create(statement=statement_event.statement,
                                      event_amount=statement_event.event_amount * -1,
                                      event_due_amount=statement_event.event_due_amount,
                                      event_date=statement_event.event_date,
                                      event_type='{}_void'.format(statement_event.event_type),
                                      can_reverse=False)

    def reverse_waive_late_fee(self, statement_event, note):
        result = False
        statement = statement_event.statement
        template_note = '[Reversal Event Waive Late Fee]\n\
                amount: {},\n\
                date: {},\n\
                note: {}.'.format(display_rupiah(statement_event.event_amount),
                                  statement_event.event_date.strftime("%d-%m-%Y"), note)
        try:
            with transaction.atomic():
                late_fee_after_campaign = 0
                late_fee_applied = statement.statement_late_fee_applied
                if statement_event.event_type in [StatementEventConst.WAIVE_LATE_FEE_GROUP_2,
                                                  StatementEventConst.WAIVE_LATE_FEE_GROUP_1]:
                    account_credit = statement.account_credit_limit
                    late_fee_after_campaign = 15 * get_late_fee_rules(account_credit.account_credit_limit)
                    late_fee_applied += 15
                reverse_due_amount = statement.statement_due_amount + statement_event.event_amount +\
                                     late_fee_after_campaign
                reverse_late_fee_amount = statement.statement_late_fee_amount + statement_event.event_amount +\
                                          late_fee_after_campaign
                statement.update_safely(statement_late_fee_amount=reverse_late_fee_amount,
                                        statement_due_amount=reverse_due_amount,
                                        statement_late_fee_applied=late_fee_applied)

                self.create_reversal_statement_event(statement_event)

                StatementNote.objects.create(
                    note_text=template_note,
                    statement=statement)

                # include reverse waive late fee to transaction one
                transaction_type = LineTransactionType.TYPE_WAIVE_LATEFEE_VOID['type']
                transaction_desc = LineTransactionType.TYPE_WAIVE_LATEFEE_VOID['name']
                include_to_transaction_one(statement, reverse_late_fee_amount, transaction_type, transaction_desc)

                result = True
        except Exception as e:
            logger.info({
                'method': 'reverse_waive_late_fee_error',
                'statement_event': statement_event.id,
                'message': str(e)
            })

        return result

    def reverse_waive_interest_fee(self, statement_event, note):
        result = False
        statement = statement_event.statement
        template_note = '[Reversal Event Waive Interest Fee]\n\
                amount: {},\n\
                date: {},\n\
                note: {}.'.format(display_rupiah(statement_event.event_amount),
                                  statement_event.event_date.strftime("%d-%m-%Y"), note)
        try:
            with transaction.atomic():
                reverse_due_amount = statement.statement_due_amount + statement_event.event_amount
                reverse_interest_amount = statement.statement_interest_amount + statement_event.event_amount
                statement.update_safely(statement_interest_amount=reverse_interest_amount,
                                        statement_due_amount=reverse_due_amount)
                self.create_reversal_statement_event(statement_event)

                StatementNote.objects.create(
                    note_text=template_note,
                    statement=statement)
                result = True
        except Exception as e:
            logger.info({
                'method': 'reverse_waive_interest_fee_error',
                'statement_event': statement_event.id,
                'message': str(e)
            })

        return result


def process_payment_for_bl_statement(
        statement, paid_amount, note, payment_method=None,
        payment_receipt=None, paid_date=None):
    if not paid_date:
        paid_date = timezone.now().date()

    status_active = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
    account_status_exclude = StatusLookup.objects.get(pk=JuloOneCodes.INACTIVE)
    credit_limit = statement.customer_credit_limit

    if credit_limit.customer_credit_status != status_active:
        return False

    account_credit_limit = credit_limit.accountcreditlimit_set.filter(
        partner__name=PaylaterConst.PARTNER_NAME,
        ).exclude(account_credit_status=account_status_exclude).last()

    if not account_credit_limit:
        return False

    # create transaction
    transaction_obj = TransactionOne.objects.create(
        customer_credit_limit=credit_limit,
        account_credit_limit=account_credit_limit,
        statement=statement,
        transaction_type='credit',
        transaction_date=paid_date,
        transaction_amount=paid_amount,
        transaction_description=LineTransactionType.TYPE_PAYMENT['name'],
        transaction_status='paid')

    # create payment detail
    TransactionPaymentDetail.objects.create(
        transaction=transaction_obj,
        payment_method_type='virtual_account',
        payment_method_name=payment_method.payment_method_name,
        payment_account_number=payment_method.virtual_account,
        payment_amount=paid_amount,
        payment_date=paid_date,
        payment_ref=payment_receipt  # Cek untuk payment_ref dari faspay
    )
    # execute signal after save transaction

    statement_transaction = TransactionOne.objects.filter(
        statement=statement).exclude(transaction_description='payment')

    # update date loanone and paymentschedule
    for transaction_obj in statement_transaction:
        update_loan_one_and_payment(transaction_obj, paid_date)

    return True

from builtins import range

from app_status.models import ApplicationLocked, ApplicationLockedMaster
from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from payment_status.models import PaymentLocked, PaymentLockedMaster

from juloserver.disbursement.services import (
    get_disbursement_process_by_id,
    get_name_bank_validation,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    ApplicationNote,
    CollectionAgentAssignment,
    CustomerAppAction,
    Loan,
    LoanStatusCodes,
    Payment,
    PaymentEvent,
    PaymentStatusCodes,
    StatusLookup,
)
from juloserver.julo.services import (
    ApplicationHistoryUpdated,
    get_grace_period_days,
    get_julo_pn_client,
    process_application_status_change,
    record_disbursement_transaction,
)
from juloserver.julo.statuses import ApplicationStatusCodes, StatusManager
from juloserver.julo.workflows2.handlers import execute_action


def force_change_status(application_id, new_status_code, note, agent):
    """
    force change_status to certain status not in the path
    usually agent request because of wrong chnage status
    """
    application = Application.objects.get(pk=application_id)
    old_status_code = application.status
    new_status_code = new_status_code
    note = '{} - requested by: agent: {}'.format(note, agent)
    status_object = StatusManager.get_or_none(new_status_code)
    changed = False
    message = ''
    if not status_object:
        return changed, 'invalid status'

    change_reason = 'Backend Script'
    if len(status_object.change_reasons) >= 1:
        change_reason = status_object.change_reasons[0]

    is_experiment = False

    try:
        with ApplicationHistoryUpdated(
            application, change_reason=change_reason, is_experiment=is_experiment
        ) as updated:
            workflow = application.workflow
            processed = execute_action(
                application, old_status_code, new_status_code, change_reason, note, workflow, 'pre'
            )
            if processed:
                application.change_status(new_status_code)
                application.save()

        execute_action(
            application, old_status_code, new_status_code, change_reason, note, workflow, 'post'
        )
        execute_action(
            application,
            old_status_code,
            new_status_code,
            change_reason,
            note,
            workflow,
            'async_task',
        )
        execute_action(
            application, old_status_code, new_status_code, change_reason, note, workflow, 'after'
        )
        status_change = updated.status_change
        ApplicationNote.objects.create(
            note_text=note, application_id=application.id, application_history_id=status_change.id
        )
        changed = True
        message = '{} successfully change status to {}'.format(application_id, status_change)
    except Exception as e:
        changed = False
        message = e.__str__()

    return changed, message


def force_change_status_no_handler(application_id, new_status_code, note, agent):
    """
    force change_status to certain status not in the path
    usually agent request because of wrong chnage status
    """
    application = Application.objects.get(pk=application_id)
    # old_status_code = application.status
    new_status_code = new_status_code
    note = '{} - requested by: agent: {}'.format(note, agent)
    status_object = StatusManager.get_or_none(new_status_code)
    changed = False
    message = ''
    if not status_object:
        return changed, 'invalid status'

    change_reason = 'Backend Script'
    if len(status_object.change_reasons) >= 1:
        change_reason = status_object.change_reasons[0]

    is_experiment = False

    try:
        with ApplicationHistoryUpdated(
            application, change_reason=change_reason, is_experiment=is_experiment
        ) as updated:
            application.change_status(new_status_code)
            application.save()

        status_change = updated.status_change
        ApplicationNote.objects.create(
            note_text=note, application_id=application.id, application_history_id=status_change.id
        )
        changed = True
        message = '{} successfully change status to {}'.format(application_id, status_change)
    except Exception as e:
        changed = False
        message = e.__str__()

    return changed, message


def customer_rescrape_action(customer, action):

    existing_entry = CustomerAppAction.objects.filter(
        customer=customer, action=action, is_completed=False
    ).last()
    if existing_entry:
        return False, 'customer already in rescrape state'

    CustomerAppAction.objects.create(customer=customer, action=action, is_completed=False)
    try:
        pn_client = get_julo_pn_client()
        pn_client.alert_rescrape(
            customer.device_set.last().gcm_reg_id, customer.application_set.last().id
        )
    except Exception:
        return True, 'successfully set rescrape action to {} but failed send pn'.format(
            customer.email
        )
    return True, 'successfully set rescrape action to {}'.format(customer.email)


def bulk_activate_loan_manual_disburse(app_ids, method):
    application_ids = set(app_ids)
    applications = Application.objects.filter(id__in=application_ids)
    application_ids_found = list(applications.values_list('id', flat=True))
    application_ids.difference(set(application_ids_found))
    loan_not_found = []
    already_180 = []
    disbursement_errors = []
    failed_activate = []
    success = []
    for application in applications:
        if not hasattr(application, 'loan'):
            loan_not_found.append(application.id)
            continue

        if application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            already_180.append(application.id)
            continue

        loan = application.loan
        # update disbursement status so that finance agent can get valid data from metabase
        try:
            disbursement = get_disbursement_process_by_id(loan.disbursement_id)
            update_fields = ['disburse_status', 'reason']
            values = ['COMPLETED', 'Manual Disbursement {}'.format(method)]
            disbursement.update_fields(update_fields, values)
        except Exception:
            disbursement_errors.append(application.id)

        if loan.partner and loan.partner.is_active_lender:
            record_disbursement_transaction(loan)

        bank_info = get_name_bank_validation(loan.name_bank_validation_id)
        new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        change_reason = 'Fund disbursal successful'
        note = (
            'Disbursement successful to %s Bank %s \
                account number %s atas Nama %s via %s'
            % (
                application.email,
                bank_info['bank_code'],
                bank_info['account_number'],
                bank_info['validated_name'],
                method,
            )
        )
        try:
            process_application_status_change(application.id, new_status_code, change_reason, note)
            success.append(application.id)
        except Exception:
            failed_activate.append(application.id)

    result = dict(
        loan_not_found=loan_not_found,
        already_180=already_180,
        error_disbursement_set_completed=disbursement_errors,
        failed_activate=failed_activate,
        success=success,
    )
    return result


def coll_reassign_agent(datas):
    failed_loan_assignment = []
    success = []
    for data in datas:
        loan = Loan.objects.get_or_none(pk=data['loan_id'])
        if not loan:
            failed_loan_assignment.append("%s - loan does not exist" % data['loan_id'])
            continue
        new_agent = User.objects.get(username=data['new_user_name'])
        current_agent = User.objects.get(username=data['old_user_name'])
        agent_assignment_type = data['type']
        current_agent_assignments = CollectionAgentAssignment.objects.filter(
            agent=current_agent, loan=loan, type=agent_assignment_type, unassign_time__isnull=True
        ).order_by('id')
        if not current_agent_assignments:
            failed_loan_assignment.append("%s - no agent assignment on loan" % loan.id)
            continue
        try:
            with transaction.atomic():
                today = timezone.localtime(timezone.now())
                current_agent_assignment = current_agent_assignments.last()
                current_agent_assignment.unassign_time = today
                current_agent_assignment.save()
                CollectionAgentAssignment.objects.create(
                    loan=loan,
                    payment=current_agent_assignment.payment,
                    agent=new_agent,
                    type=agent_assignment_type,
                    assign_time=today,
                )
                success.append(loan.id)
        except JuloException:
            failed_loan_assignment.append("%s - failed assignment loan" % loan.id)

    return success, failed_loan_assignment


def unlocked_app(app_id, user_obj):
    app_locked_master = ApplicationLockedMaster.objects.get_or_none(application_id=app_id)

    with transaction.atomic():
        if app_locked_master:
            app_locked = ApplicationLocked.objects.filter(
                application_id=app_id, user_lock=user_obj, locked=True
            ).last()

            if app_locked:
                app_locked.locked = False
                app_locked.user_unlock = user_obj
                app_locked.save()
                # delete master locked
                app_locked_master.delete()
                return True
    return False


def unlocked_payment(payment_id, user):
    payment_locked_master = PaymentLockedMaster.objects.get_or_none(payment_id=payment_id)

    with transaction.atomic():
        if payment_locked_master:
            payment_locked = PaymentLocked.objects.filter(
                payment_id=payment_id, user_lock=user, locked=True
            ).last()

            if payment_locked:
                payment_locked.locked = False
                payment_locked.user_unlock = user
                payment_locked.save()
                # delete master locked
                payment_locked_master.delete()
                return True
    return False


def waive_refinancing(payment):
    today = timezone.now().date()
    if not payment.due_amount:
        return True
    pe = PaymentEvent.objects.create(
        payment=payment,
        event_payment=payment.due_amount,
        event_due_amount=payment.due_amount,
        event_date=today,
        event_type='waive-refinancing',
        payment_receipt=None,
        payment_method=None,
    )
    payment.due_amount -= pe.event_payment
    payment.save()
    payment.change_status(PaymentStatusCodes.PAID_ON_TIME)
    payment.ptp_date = None
    payment.save()
    loan = payment.loan
    loan.update_status()
    loan.save()
    return True


def process_payment_discount(amount, payment_id):
    today = timezone.now().date()
    try:
        payment = Payment.objects.get(pk=payment_id)
    except ObjectDoesNotExist:
        return False, 'payment not found'
    if amount > payment.due_amount:
        return False, 'amount applied more than due amount'
    PaymentEvent.objects.create(
        payment=payment,
        event_payment=amount,
        event_due_amount=payment.due_amount,
        event_date=today,
        event_type='discount_loan',
        payment_receipt=None,
        payment_method=None,
        can_reverse=False,
    )
    payment.due_amount -= amount
    payment.save()
    payment.refresh_from_db()
    loan = payment.loan
    if payment.due_amount == 0:
        if payment.paid_late_days <= 0:
            payment.change_status(StatusLookup.PAID_ON_TIME_CODE)
            payment.save()
            loan.update_status()
            loan.save()
        elif 0 < payment.paid_late_days <= get_grace_period_days(payment):
            payment.change_status(StatusLookup.PAID_WITHIN_GRACE_PERIOD_CODE)
            payment.save()
            loan.update_status()
            loan.save()
        else:
            payment.change_status(StatusLookup.PAID_LATE_CODE)
            payment.save()
            loan.update_status()
            loan.save()

    return True, 'payment discount success'


def process_change_name_ktp(app_id, name):
    with transaction.atomic():
        application = Application.objects.get_or_none(pk=app_id)
        if application is None:
            raise JuloException("application ID %s is not found" % app_id)

        application.update_safely(fullname=name)
        customer = application.customer
        customer.update_safely(fullname=name)
        return


def payment_restructure(
    loan_id,
    starting_payment_number,
    principal,
    interest,
    late_fee,
    payment_count_to_restructure,
    due_date,
):
    """
    Restructure customer's loan to help them pay back their loan. Requested by
    collections agents in Slack #coll-swat
    """
    with transaction.atomic():
        loan = Loan.objects.get_or_none(pk=loan_id)
        if not loan:
            raise JuloException("Loan ID %s is not found" % loan_id)

        now = timezone.localtime(timezone.now())

        loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.RENEGOTIATED)
        new_loan_duration = payment_count_to_restructure + starting_payment_number - 1
        new_installment_amount = principal + interest
        loan.update_safely(
            loan_duration=new_loan_duration,
            cycle_day_change_date=now,
            cycle_day=due_date.day,
            installment_amount=new_installment_amount,
            loan_status=loan_status,
        )

        # This only works assuming there is an more total payments and will fail
        # if the restructure is done to more expensive less frequent payments
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for payment_num in range(
            starting_payment_number, starting_payment_number + payment_count_to_restructure
        ):

            payment = Payment.objects.get_or_none(loan_id=loan_id, payment_number=payment_num)

            if payment:

                original_principal = payment.installment_principal
                original_interest = payment.installment_interest
                original_late_fee = payment.late_fee_amount

                # Update existing payment
                new_due_amount = principal + interest + late_fee - payment.paid_amount
                late_fee_applied = 1 if late_fee > 0 else 0
                payment.update_safely(
                    due_date=due_date,
                    due_amount=new_due_amount,
                    installment_principal=principal,
                    installment_interest=interest,
                    late_fee_amount=late_fee,
                    payment_status=payment_status,
                    ptp_date=None,
                    uncalled_date=None,
                    is_ptp_robocall_active=None,
                    is_robocall_active=False,
                    is_collection_called=False,
                    reminder_call_date=None,
                    is_reminder_called=False,
                    is_whatsapp=False,
                    is_whatsapp_blasted=False,
                    ptp_robocall_template=None,
                    ptp_robocall_phone_number=None,
                    is_success_robocall=None,
                    is_restructured=True,
                    ptp_amount=0,
                    late_fee_applied=late_fee_applied,
                )

                # Create a payment event
                original_due_amount = original_principal + original_interest + original_late_fee
                discount = original_due_amount - new_due_amount
                PaymentEvent.objects.create(
                    payment=payment,
                    event_payment=discount,
                    event_due_amount=new_due_amount,
                    event_date=now.date(),
                    event_type='discount - restructuring',
                    payment_receipt=None,
                    payment_method=None,
                    can_reverse=False,
                )
            else:
                new_due_amount = principal + interest + late_fee
                Payment.objects.create(
                    payment_number=payment_num,
                    due_date=due_date,
                    loan_id=loan_id,
                    due_amount=new_due_amount,
                    installment_principal=principal,
                    installment_interest=interest,
                    late_fee_amount=late_fee,
                    payment_status=payment_status,
                    is_restructured=True,
                )

            due_date += relativedelta(months=+1)

        return loan

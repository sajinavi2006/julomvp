from builtins import str
from typing import Dict
import logging

from celery import task
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.disbursement.services.ayoconnect import AyoconnectService
from juloserver.disbursement.exceptions import (
    DisbursementServiceError,
    XenditExperimentError,
    XfersCallbackError,
    AyoconnectCallbackError,
    AyoconnectServiceError
)
from juloserver.disbursement.models import (
    Disbursement,
)
from juloserver.disbursement.services.bca import BcaService, BcaConst
from juloserver.disbursement.services import (
    get_disbursement_process,
    get_service,
    is_vendor_experiment_possible,
    get_ecommerce_disbursement_experiment_method,
    get_disbursement_by_obj,
    create_disbursement_history_ayoconnect,
    get_disbursement_process_by_transaction_id,
)
from juloserver.disbursement.services.gopay import GopayService
from juloserver.disbursement.services.xfers import XfersConst
from juloserver.disbursement.services.daily_disbursement_limit import (
    process_daily_disbursement_limit_whitelist
)
from juloserver.followthemoney.constants import LenderReversalTransactionConst
from juloserver.followthemoney.models import LenderCurrent, LenderReversalTransaction
from juloserver.followthemoney.services import (
    check_lender_reversal_step_needed,
    create_lender_reversal_trx_history,
    update_lender_balance_current_for_disbursement,
    withdraw_to_lender_for_reversal_transaction,
)
from juloserver.followthemoney.tasks import create_lender_transaction_for_reversal_payment
from juloserver.julo.exceptions import JuloException
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    CashbackTransferTransaction,
    Loan,
    Application,
    FeatureSetting,
    BcaTransactionRecord,
    LoanDisburseInvoices,
    Document,
)
from juloserver.julo.services import (
    process_application_status_change,
    record_bulk_disbursement_transaction,
    record_disbursement_transaction,

)
from juloserver.julo.services2 import get_cashback_redemption_service
from juloserver.julo.services2.cashback import (
    CashbackRedemptionService,
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
)
from juloserver.disbursement.constants import (
    DisbursementVendors,
    DisbursementStatus,
    XfersDisbursementStep,
    GopayAlertDefault,
    AyoconnectConst,
    AyoconnectErrorCodes,
    AyoconnectErrorReason,
    DailyDisbursementLimitWhitelistConst,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.disbursement.services.bulk_disbursement import application_bulk_disbursement
from juloserver.julo.utils import display_rupiah
from juloserver.loan.services.lender_related import (
    julo_one_loan_disbursement_failed,
    julo_one_loan_disbursement_success,
    ayoconnect_loan_disbursement_success,
    ayoconnect_loan_disbursement_failed,
)
from juloserver.monitors.notifications import (send_slack_bot_message, send_message_normal_format,
                                               get_slack_bot_client)
from juloserver.paylater.models import DisbursementSummary
from juloserver.payment_point.constants import TransactionMethodCode
from django.conf import settings

from juloserver.portal.core.templatetags.unit import format_rupiahs
from juloserver.grab.models import (
    PaymentGatewayCustomerData,
    PaymentGatewayApiLog,
    PaymentGatewayApiLogArchival,
    PaymentGatewayLogIdentifier,
    PaymentGatewayTransaction
)
from datetime import (
    timedelta,
    datetime
)
from juloserver.julo.product_lines import ProductLineCodes
logger = logging.getLogger(__name__)

grab_graveyard_statuses = {
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,  # 106
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,  # 136
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,  # 139
    ApplicationStatusCodes.APPLICATION_DENIED,  # 135
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,  # 137
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,  # 111
    ApplicationStatusCodes.OFFER_EXPIRED,  # 143
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,  # 171
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD  # 133
}


@task(queue='loan_high')
@transaction.atomic
def check_disbursement_via_bca_subtask(statement):
    """sub task"""

    try:
        disbursement = get_disbursement_process(statement['disburse_id'])
    except DisbursementServiceError:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        return

    disbursement.update_status(statement)
    disbursement_id = disbursement.get_id()
    disbursement_data = disbursement.get_data()
    if disbursement.is_success():
        if disbursement.get_type() == 'loan':
            loan = Loan.objects.filter(disbursement_id=disbursement_id)\
                               .order_by('cdate').last()
            application = loan.application
            if loan.lender and loan.lender.is_active_lender:
                record_disbursement_transaction(loan)
            # process change status to 180
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])
            process_application_status_change(application.id,
                                              new_status_code,
                                              change_reason,
                                              note)
        elif disbursement.get_type() == 'cashback':
            cashback_transfer = CashbackTransferTransaction.objects.filter(
                transfer_id=disbursement_id).order_by('cdate').last()
            if cashback_transfer:
                cashback_service = CashbackRedemptionService()
                cashback_service.action_cashback_transfer_finish(
                    cashback_transfer, is_success=True)


@task(queue="loan_high")
def check_disbursement_via_bca():
    pending_disbursements = Disbursement.objects.checking_statuses_bca_disbursement()
    pending_disburse_ids = pending_disbursements.values_list('disburse_id', flat=True)
    today = timezone.now().date()
    yesterday = today - relativedelta(days=1)
    bca_service = BcaService()
    logger.info({
        'action': 'check_disbursement_via_bca',
        'pending_disbursements': pending_disburse_ids,
        'date': 'today',
    })

    statements = bca_service.get_statements(yesterday.__str__(),
                                            today.__str__())

    for statement in statements:
        if 'JULO-Disburse' in statement['Trailer'] or\
                'JC' in statement['Trailer'] or\
                'JULO-Paylater' in statement['Trailer']:
            description = statement['Trailer'].split(',')
            disburse_id = description[1].strip()
            statement['disburse_id'] = disburse_id
            if disburse_id in pending_disburse_ids:
                check_disbursement_via_bca_subtask.delay(statement)


@task(queue="loan_high")
def auto_retry_disbursement_via_bca():
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BCA_DISBURSEMENT_AUTO_RETRY,
        category="disbursement",
        is_active=True).first()

    if not feature:
        logger.info({'task': 'auto_retry_disbursement_via_bca',
                     'status': 'feature inactive'})
        return

    params = feature.parameters
    current_time = timezone.now()
    today = current_time.date()
    yesterday = today - relativedelta(days=1)
    app_status = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
    delay_hours = current_time - relativedelta(hours=params['delay_in_hours'])

    bca_service = get_service(DisbursementVendors.BCA)
    statements = bca_service.get_statements(yesterday.__str__(),
                                            today.__str__())

    if statements:
        succeeded_disburse_ids = bca_service.filter_disburse_id_from_statements(statements)
        disburse_failed_applications = Application.objects.filter(application_status_id=app_status)
        for application in disburse_failed_applications:
            changed_to_181 = application.applicationhistory_set.filter(
                status_new=app_status).last()
            if not changed_to_181 or changed_to_181.cdate >= delay_hours:
                logger.info({'task': 'auto_retry_disbursement_via_bca',
                             'application_id': application.id,
                             'status': 'wait for next schedule'})
                continue

            disbursement = Disbursement.objects.get_or_none(
                pk=application.loan.disbursement_id, method=DisbursementVendors.BCA,
                disburse_status=DisbursementStatus.FAILED)
            if not disbursement:
                logger.info({'task': 'auto_retry_disbursement_via_bca',
                             'application_id': application.id,
                             'status': 'disbursement not found'})
                continue

            if disbursement.disburse_id in succeeded_disburse_ids:
                bca_transaction = BcaTransactionRecord.objects\
                    .filter(reference_id=disbursement.external_id).order_by('id').last()
                bca_transaction.status = 'Success'
                bca_transaction.error_code = None
                bca_transaction.save()

                new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                change_reason = 'Fund disbursal successful'
                note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                    application.email, disbursement.name_bank_validation.bank_code,
                    disbursement.name_bank_validation.account_number,
                    disbursement.name_bank_validation.method)

                logger.info({'task': 'auto_retry_disbursement_via_bca',
                             'application_id': application.id,
                             'status': 'disbursement completed based on check_bca_statement'})
            else:
                if disbursement.retry_times >= params['max_retries']:
                    new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_ONGOING
                    change_reason = BcaConst.RETRY_EXCEEDED_CHANGE_REASON
                    note = 'Disbursement via BCA retry attempt is exceeded please disburse manually'

                    logger.info({'task': 'auto_retry_disbursement_via_bca',
                                 'application_id': application.id,
                                 'status': 'max_retries exceeded sent it to status 177'})
                else:
                    disbursement.retry_times += 1
                    disbursement.save(update_fields=['retry_times', 'udate'])
                    new_status_code = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
                    change_reason = BcaConst.RETRY_CHANGE_REASON
                    note = 'Disbursement via BCA retry attempt %s' % str(disbursement.retry_times)

                    logger.info({'task': 'auto_retry_disbursement_via_bca',
                                 'application_id': application.id,
                                 'status': 'retrying disburse sent it back to status 170'})

            process_application_status_change(application.id, new_status_code, change_reason, note)


@task(queue="loan_high")
def application_bulk_disbursement_tasks(disbursement_id, new_status_code, note):
    application_bulk_disbursement(disbursement_id, new_status_code, note)


@task(queue="loan_high")
def bca_pending_status_check_in_170():
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BCA_PENDING_STATUS_CHECK_IN_170,
        category="disbursement",
        is_active=True).first()

    if not feature:
        logger.info({'task': 'bca_pending_status_check_in_170',
                     'status': 'feature inactive'})
        return

    params = feature.parameters
    current_time = timezone.now()
    today = current_time.date()
    yesterday = today - relativedelta(days=1)
    app_status = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
    bca_service = get_service(DisbursementVendors.BCA)
    statements = bca_service.get_statements(yesterday.__str__(),
                                            today.__str__())
    if statements:
        succeeded_disburse_ids = bca_service.filter_disburse_id_from_statements(statements)
        stuck_applications = Application.objects.filter(application_status_id=app_status)
        for application in stuck_applications:
            disbursement = Disbursement.objects.get_or_none(
                pk=application.loan.disbursement_id, method=DisbursementVendors.BCA)
            if not disbursement:
                logger.info({'task': 'bca_pending_status_check_in_170',
                             'application_id': application.id,
                             'status': 'disbursement not found'})
                continue
            # change status if success to 180
            if disbursement.disburse_id in succeeded_disburse_ids:
                new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                    application.email, disbursement.name_bank_validation.bank_code,
                    disbursement.name_bank_validation.account_number,
                    disbursement.name_bank_validation.method)
                process_application_status_change(application.id,
                                                  new_status_code,
                                                  'Fund disbursal successful',
                                                  note)
                # change status disburse to completed because disburse_id in succeeded_disburse_ids
                disbursement.disburse_status = DisbursementStatus.COMPLETED
                disbursement.save(update_fields=['disburse_status', 'udate'])
                logger.info({'task': 'bca_pending_status_check_in_170',
                             'application_id': application.id,
                             'status': 'success to 180'})
            else:
                if disbursement.retry_times == params['max_retries']:
                    new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
                    note = 'Failed Change status to 180 after 6 times retires'
                    process_application_status_change(application.id,
                                                      new_status_code,
                                                      'Fund disbursal failed after {} times'.format(
                                                          params['max_retries']
                                                      ),
                                                      note)
                    disbursement.disburse_status = DisbursementStatus.FAILED
                    disbursement.reason = note
                    disbursement.save(update_fields=['disburse_status', 'reason', 'udate'])
                    logger.info({'task': 'bca_pending_status_check_in_170',
                                 'application_id': application.id,
                                 'status': 'failed send to 181'})
                else:
                    disbursement.retry_times += 1
                    disbursement.save(update_fields=['retry_times', 'udate'])
                    logger.info({'task': 'bca_pending_status_check_in_170',
                                 'application_id': application.id,
                                 'status': 'retry'})


@task(queue="loan_high")
def xfers_second_step_disbursement_task(disburse_id):
    logger.info({'task': 'xfers_second_step_disbursement_task',
                 'disburse_id': disburse_id,
                 'status': 'initiated'})
    disbursement = get_disbursement_process(disburse_id)
    disbursement.disburse()


@task(queue="loan_high")
def process_xendit_callback(disburse_id, xendit_response):
    # perform checks before the main logic
    disburse_process = get_disbursement_process(disburse_id)
    disbursement_id = disburse_process.get_id()

    loan = Loan.objects.filter(disbursement_id=disbursement_id).last()

    # ------- for now we raise error if it's not ecommerce
    if not is_vendor_experiment_possible(loan):
        raise XenditExperimentError('Loan is not possible for vendor experiment')
    # -------

    # then only proceed if PENDING
    if disburse_process.is_pending():
        disburse_process.update_status(data=xendit_response)
        if disburse_process.is_success():
            # if there is concurency,
            # an expected exception will be raised in this function
            # "Can't change Loan Status from abc to abc"
            julo_one_loan_disbursement_success(loan)

            if loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)

            lender = loan.lender
            if lender and lender.lender_name in LenderCurrent.escrow_lender_list():
                update_lender_balance_current_for_disbursement(loan.id)
        else:
            julo_one_loan_disbursement_failed(loan)


@task(queue='loan_normal')
def process_callback_from_xfers(data, current_step, is_reversal_payment):
    new_status = data.get("status")
    if current_step:
        current_step = int(current_step)

    disburse_id = data.get('idempotency_id')
    # ---
    if is_reversal_payment:
        if current_step == LenderReversalTransactionConst.FIRST_STEP:
            ext_ref_id = data.get('order_id')
            if not ext_ref_id:
                ext_ref_id = data.get('idempotency_id')
        else:
            ext_ref_id = data.get('idempotency_id')

        lender_reversal_id = int(str(ext_ref_id.split('_')[-1])[:-1])
        lender_reversal_trx = LenderReversalTransaction.objects.\
            get_or_none(pk=lender_reversal_id)
        if not lender_reversal_trx:
            raise XfersCallbackError("lender id not found {}".format(lender_reversal_id))

        if (current_step == lender_reversal_trx.step
                and lender_reversal_trx.status == LenderReversalTransactionConst.PENDING
                and new_status in XfersConst.CALLBACK_STATUS):

            if current_step == LenderReversalTransactionConst.FIRST_STEP:
                history_data = {
                    'id': lender_reversal_trx.id,
                    'amount': lender_reversal_trx.amount,
                    'method': 'Xfers',
                    'order_id': ext_ref_id,
                    'reason': data.get('failure_reason'),
                    'status': new_status,
                    'step': current_step
                }
                create_lender_reversal_trx_history(history_data)
                if new_status == XfersConst.STATUS_COMPLETED:

                    create_lender_transaction_for_reversal_payment.delay(
                        lender_reversal_trx.source_lender_id,
                        lender_reversal_trx.amount * -1,
                        lender_reversal_trx.voided_payment_event.payment.id,
                        lender_reversal_trx.voided_payment_event,
                        different_lender=True,
                        deduct=True,
                    )

                    if check_lender_reversal_step_needed(lender_reversal_trx) ==\
                            LenderReversalTransactionConst.INTER_LENDER_TRX_STEP:
                        withdraw_to_lender_for_reversal_transaction(lender_reversal_trx)
                    else:
                        lender_reversal_trx.update_safely(status=new_status)
                else:
                    lender_reversal_trx.update_safely(status=new_status)
                return

            else:
                history_data = {
                    'id': lender_reversal_trx.id,
                    'amount': lender_reversal_trx.amount,
                    'method': 'Xfers',
                    'idempotency_id': ext_ref_id,
                    'reason': data.get('failure_reason'),
                    'status': new_status,
                    'step': current_step
                }
                create_lender_reversal_trx_history(history_data)
                if new_status == XfersConst.STATUS_COMPLETED:
                    create_lender_transaction_for_reversal_payment.delay(
                        lender_reversal_trx.destination_lender_id,
                        lender_reversal_trx.amount,
                        lender_reversal_trx.voided_payment_event.payment.id,
                        lender_reversal_trx.voided_payment_event.correct_payment_event,
                        different_lender=True,
                    )
                lender_reversal_trx.update_safely(status=new_status)
                return
        else:
            raise XfersCallbackError("Wrong step of Xfers")

    disbursement = get_disbursement_process(disburse_id)
    if not disbursement.is_valid_method(DisbursementVendors.XFERS):
        raise XfersCallbackError(
            "disbursement method xfers is not valid method for disbursement {}".format(disburse_id)
        )

    # ----------NEW MONEY FLOW---------------------
    # make sure has no duplicate callback
    if not (current_step == disbursement.disbursement.step
            and disbursement.is_pending()
            and new_status in XfersConst.CALLBACK_STATUS):
        raise XfersCallbackError("Wrong step of Xfers")

    disbursement.update_status(data)
    disbursement_id = disbursement.get_id()

    # bulk disbursement checker
    if disbursement.get_type() == 'bulk':
        disbursement_summary = DisbursementSummary.objects\
            .filter(disbursement_id=disbursement_id).last()
        loan = None
    else:
        disbursement_summary = None
        loan = Loan.objects.filter(disbursement_id=disbursement_id).order_by('cdate').last()

    # handle callback from jtp to jtf
    if current_step == XfersDisbursementStep.FIRST_STEP and disbursement.is_success():
        try:
            loan_id = None
            if loan:
                loan_id = loan.id
            update_lender_balance_current_for_disbursement(loan_id, disbursement_summary)
        except JuloException:
            sentry_client = get_julo_sentry_client()
            sentry_client.capture_exceptions()

        if (
            loan
            and loan.transaction_method_id in TransactionMethodCode.single_step_disbursement()
            and not loan.is_xfers_ewallet_transaction
        ):
            return
        # continue to disburse from jtf to customer

        # xendit experiment --
        if (
            loan and is_vendor_experiment_possible(loan)
            and get_ecommerce_disbursement_experiment_method(loan) == DisbursementVendors.XENDIT
        ):
            # change method for step 2:
            disbursement.change_method_for_xendit_step_two()
        # -- xendit experiment

        xfers_second_step_disbursement_task.delay(disburse_id)

        return
    # -------------------------------------------------

    # query cashbacktransfer object
    if disbursement.get_type() == 'cashback':
        # call cashback service to update cashback
        cashback_service = get_cashback_redemption_service()
        cashback_service.update_transfer_cashback_xfers(disbursement)
        return

    if disbursement.get_type() == 'loan_one':
        send_to = 'bukalapak'

    elif disbursement.get_type() == 'bulk':
        applications = Application.objects.filter(pk__in=disbursement_summary.transaction_ids)
        application = applications.last()
        send_to = application.partner.name

    else:
        # check if loan are from partner laku6
        if not loan:
            invoices = LoanDisburseInvoices.objects.filter(disbursement_id=disbursement_id)\
                .order_by('cdate').last()
            loan = invoices.loan

        application = loan.application
        if not application:
            application = loan.get_application
        send_to = application.email

    disbursement_data = disbursement.get_data()

    isnt_old_flow = [
        application.is_julo_one,
        application.is_grab,
        application.is_axiata_flow,
        application.is_julover,
        application.is_merchant_flow,
        application.is_julo_starter,
        application.is_mf_web_app_flow,
        application.is_julo_one_ios,
    ]
    if loan and application and any(flow() for flow in isnt_old_flow):
        if disbursement.is_success():
            if loan.status == LoanStatusCodes.CURRENT:
                return
            elif loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)
            lender = loan.lender
            if lender and lender.lender_name in LenderCurrent.escrow_lender_list():
                update_lender_balance_current_for_disbursement(loan.id)

            julo_one_loan_disbursement_success(loan)

        elif disbursement.is_failed():
            julo_one_loan_disbursement_failed(loan)
        return

    # prevent multiple callback
    if disbursement.is_success():
        if loan:
            if loan.application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                return

            elif loan.lender and loan.lender.is_active_lender:
                record_disbursement_transaction(loan)

        else:
            if disbursement.get_type() == 'bulk':
                lender = disbursement_summary.partner.user.lendercurrent
                if lender and lender.is_active_lender:
                    record_bulk_disbursement_transaction(disbursement_summary)

    if disbursement.is_failed() or disbursement.is_success():
        if disbursement.is_success():
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s \
                    account number %s atas Nama %s via %s' % (
                send_to,
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])

        elif disbursement.is_failed():
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            change_reason = 'Fund disbursal failed'
            note = 'Disbursement failed to %s Bank %s \
                    account number %s atas Nama %s via %s' % (
                send_to,
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])

        if disbursement.get_type() == 'bulk':
            application_bulk_disbursement_tasks.delay(disbursement_id, new_status_code, note)

        elif disbursement.get_type() not in ('loan_one', 'bulk'):
            # process change status to 180 / 181
            process_application_status_change(
                application.id,
                new_status_code,
                change_reason,
                note,
            )


@task(queue='loan_high')
def process_callback_from_ayoconnect(data):
    logger.info({
        "task": "process_callback_from_ayoconnect",
        "status": "starting_process",
        "data": data
    })
    details = data.get('details')
    a_correlation_id = details.get("A-Correlation-ID")
    payment_gateway_transaction = PaymentGatewayTransaction.objects.filter(
        correlation_id=a_correlation_id
    ).last()
    disbursement_obj = Disbursement.objects.filter(
        id=payment_gateway_transaction.disbursement_id,
        method=DisbursementVendors.AYOCONNECT
    ).last()
    is_status_missing = False
    new_status = None
    if 'status' in details:
        new_status = int(details.get("status"))
    else:
        is_status_missing = True
    loan = Loan.objects.filter(disbursement_id=disbursement_obj.id).last()
    if not loan:
        raise AyoconnectCallbackError(
            "Loan not Found for DisbursementID: {}".format(disbursement_obj.id))

    if loan.loan_status.status_code == LoanStatusCodes.CURRENT:
        raise AyoconnectCallbackError(
            "Loan already reach {} for DisbursementID: {}".format(
                LoanStatusCodes.CURRENT, disbursement_obj.id)
        )

    disbursement = get_disbursement_by_obj(disbursement_obj)
    if not disbursement.is_valid_method(DisbursementVendors.AYOCONNECT):
        raise AyoconnectCallbackError(
            "disbursement method xfers is not valid method for disbursementID {}".format(
                disbursement_obj.id))

    if not (disbursement.is_pending()
            and (is_status_missing or new_status in AyoconnectConst.DISBURSEMENT_STATUS)):
        logger.info({
            "task": "process_callback_from_ayoconnect",
            "disbursement_pending": disbursement.is_pending(),
            "new_status": new_status,
            "disbursement_id": disbursement_obj.id
        })
        return
    logger.info(
        {
            "task": "process_callback_from_ayoconnect",
            "status": "triggering update disbursement",
            "data": data
        }
    )
    disbursement.update_status(data)
    disbursement_id = disbursement.get_id()
    # bulk disbursement checker
    loan = Loan.objects.filter(disbursement_id=disbursement_id).order_by('cdate').last()
    if not loan:
        raise AyoconnectCallbackError(
            "Loan Not Found for disbursement_id: {}".format(disbursement_id))
    application = loan.application
    if not application:
        application = loan.get_application

    isnt_old_flow = [
        application.is_grab
    ]
    if loan and (
        application and any(flow() for flow in isnt_old_flow)
        or loan.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]
    ):
        if disbursement.is_success():
            logger.info({
                "task": "process_callback_from_ayoconnect",
                "status": "disbursement_success",
                "data": data
            })
            if loan.status == LoanStatusCodes.CURRENT:
                logger.info({
                    "task": "process_callback_from_ayoconnect",
                    "message": "loan already have status 220",
                })
                return
            elif loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)
            lender = loan.lender
            if lender and lender.lender_name in LenderCurrent.escrow_lender_list():
                update_lender_balance_current_for_disbursement(loan.id)

            ayoconnect_loan_disbursement_success(loan)

        elif disbursement.is_failed():
            logger.info({
                "task": "process_callback_from_ayoconnect",
                "status": "disbursement_failed",
                "data": data
            })
            if not is_status_missing:
                ayoconnect_loan_disbursement_failed(loan)
            else:
                send_payment_gateway_vendor_api_alert_slack.delay(
                    uri_path='/api/integration/v1/callbacks/ayoconnect/disbursement/',
                    err_message="Status Missing in response",
                    payload=data
                )
                ayoconnect_loan_disbursement_failed(loan, force_failed=True)
        logger.info({
            "task": "process_callback_from_ayoconnect",
            "status": "processed disbursement",
        })
        return
    logger.info({
        "task": "process_callback_from_ayoconnect",
        "status": "exiting",
    })


@task(queue='loan_low')
def check_gopay_balance_threshold():
    gopay_alert_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GOPAY_BALANCE_ALERT, is_active=True
    ).last()
    if not gopay_alert_fs:
        return

    gopay = GopayService()
    current_balance = gopay.get_balance()

    parameters = gopay_alert_fs.parameters
    channel = parameters.get('channel', GopayAlertDefault.CHANNEL)
    threshold = parameters.get('threshold', GopayAlertDefault.THRESHOLD)
    message = parameters.get('message', GopayAlertDefault.MESSAGE).format(
        current_balance=display_rupiah(current_balance), threshold=display_rupiah(threshold)
    )

    if current_balance <= float(threshold):
        send_slack_bot_message(channel, message)


@task(queue='loan_normal')
def process_callback_from_xfers_partner(data, current_step, is_reversal_payment):
    logger.info({
        'task': 'process_callback_from_xfers_partner',
        'data': data,
        'current_step': current_step,
        'is_reversal_payment': is_reversal_payment,
    })
    process_callback_from_xfers(data, current_step, is_reversal_payment)


@task(name="send_payment_gateway_vendor_api_alert_slack", queue="loan_high")
def send_payment_gateway_vendor_api_alert_slack(uri_path=None,
                                                slack_channel="#payment_gateway_vendor_api_alert",
                                                msg_header="Payment Gateway Vendor Alert",
                                                req_header=None,
                                                query_param=None,
                                                err_message=None,
                                                payload=None,
                                                msg_type=1):
    """
    msg_type :
        1 : full message type
        2: only env, params and err_message
        3: only env
    """
    payment_gateway_alert_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PAYMENT_GATEWAY_ALERT,
        is_active=True
    )
    if not payment_gateway_alert_feature_setting:
        return
    parameters = payment_gateway_alert_feature_setting.parameters
    env = settings.ENVIRONMENT.lower()
    key = "slack_alert_{}".format(env)
    if key not in parameters or not parameters.get(key):
        return

    upper_env = settings.ENVIRONMENT.upper()
    msg_header = "\n\n*{}*".format(msg_header)
    msg = ("\n\tENV : {}\n\tURL : {}\n\t"
           "Headers : {}\n\tQuery Param : {}\n\t"
           "Payload : {}\n\tError Message : {}\n\n"
           ).format(upper_env, uri_path, req_header, query_param, payload, err_message)
    if msg_type == 2:
        msg = "\n\tENV : {}\n\tPayload : {}\n\tError Message : {}\n\n".format(upper_env, payload,
                                                                              err_message)
    elif msg_type == 3:
        msg = "\n\tENV : {}\n\n".format(upper_env)
    send_message_normal_format(msg_header + msg, slack_channel)


@task(name='check_payment_gateway_vendor_balance', queue='loan_high')
def check_payment_gateway_vendor_balance():
    """
    scheduler to check merchant balance and sent slack notification if its below 1 Bio Rupiah
    """
    limit_balance = AyoconnectConst.PERMISSIBLE_BALANCE_LIMIT
    payment_gateway_alert_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PAYMENT_GATEWAY_ALERT,
        is_active=True
    )
    if not payment_gateway_alert_feature_setting:
        logger.info({
            "action": "check_payment_gateway_vendor_balance",
            "message": "payment_gateway_alert_feature_setting doesn't exist or inactivated"
        })
        return

    parameters = payment_gateway_alert_feature_setting.parameters
    env = settings.ENVIRONMENT.lower()
    key = "slack_alert_{}".format(env)
    if not parameters.get(key):
        logger.info({
            "action": "check_payment_gateway_vendor_balance",
            "message": "payment_gateway_alert_feature_setting {} inactivated".format(env)
        })
        return

    if parameters:
        limit_balance = payment_gateway_alert_feature_setting.parameters.get(
            "min_balance_ayoconnect", AyoconnectConst.PERMISSIBLE_BALANCE_LIMIT)
    balance_type, status, balance = AyoconnectService().check_balance(
        limit_balance
    )
    formatted_limit_balance = "{:,}".format(limit_balance).replace(',', '.')

    if balance_type == DisbursementStatus.INSUFICIENT_BALANCE:
        env = settings.ENVIRONMENT.upper()
        now_date = timezone.localtime(timezone.now()).date()
        now_time = timezone.localtime(timezone.now()).time()
        timestamp = now_date.strftime("%Y-%m-%d ") + now_time.strftime("%H:%M:%S")
        message = ("<@U04DPEV14SF> <@U01TRU8U3PG> <@U058M4QBVU4> <@UEBRK95J9> "
                   "Ayoconnect balance is below {} Rupiah\n```Timestamp: {}"
                   "\nCurrent Balance: {}\nENV:{}```".format(formatted_limit_balance,
                                                             timestamp,
                                                             format_rupiahs(balance, 'no'), env)
                   )

        get_slack_bot_client().api_call(
            "chat.postMessage",
            channel="grabmodal-finance",
            text=message
        )


@task(queue='loan_high')
def verify_ayoconnect_loan_disbursement_status(data):
    """
        data passed should be like eg:
         data = {
                'application_id': 44324324324,
                'pg_customer_data_id': 44,
                'payment_gateway_transaction_id': 3,
                'disbursement_id': 5
            }
    """
    loan = Loan.objects.filter(disbursement_id=data['disbursement_id']).last()
    application = Application.objects.get_or_none(pk=data['application_id'])
    disbursement_obj = Disbursement.objects.get_or_none(pk=data['disbursement_id'])
    pg_customer_data = PaymentGatewayCustomerData.objects.get(pk=data['pg_customer_data_id'])
    pg_transaction_data = PaymentGatewayTransaction.objects.get(
        pk=data['payment_gateway_transaction_id'])
    a_correlation_id = pg_transaction_data.correlation_id
    try:
        _, response = AyoconnectService().check_disburse_status(
            application.id, pg_customer_data, a_correlation_id, disbursement_obj
        )
    except AyoconnectServiceError as err:
        logger.info(
            {
                'task': 'verify_ayoconnect_loan_disbursement_status',
                'loan_id': loan.id,
                'disbursement_id': data['disbursement_id'],
                'err_message': err,
            }
        )
        return

    if response and response.get("code") == 412 and response.get("errors"):
        response_error = response.get("errors")
        if isinstance(response_error, list) and response_error[0].get(
                "code") == AyoconnectErrorCodes.TRANSACTION_NOT_FOUND:
            err_message = AyoconnectErrorReason.ERROR_TRANSACTION_NOT_FOUND
            logger.info(
                {
                    'task': 'verify_ayoconnect_loan_disbursement_status',
                    'loan_id': loan.id,
                    'disbursement_id': data['disbursement_id'],
                    'err_message': err_message,
                    'response': str(response)
                }
            )
            pg_transaction_data.update_safely(status=DisbursementStatus.FAILED, reason=err_message)
            update_fields = ['disburse_status', 'reason']
            disbursement_obj.disburse_status = DisbursementStatus.FAILED
            disbursement_obj.reason = err_message
            disbursement_obj.save(update_fields=update_fields)
            disbursement_obj.create_history('update_status', update_fields)
            create_disbursement_history_ayoconnect(disbursement_obj)
            ayoconnect_loan_disbursement_failed(loan)


@task(name='check_disbursement_status_schedule', queue='loan_high')
def check_disbursement_status_schedule():
    """
    scheduler to check disbursement status periodically
    """
    disbursements = Disbursement.objects.filter(
        cdate__lte=timezone.localtime(timezone.now() - timedelta(hours=3)),
        method=DisbursementVendors.AYOCONNECT,
        disburse_status=DisbursementStatus.PENDING,
    ).exclude(reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE)
    if disbursements:
        for disbursement in disbursements.iterator():
            loan = Loan.objects.filter(disbursement_id=disbursement.id).last()
            if not loan:
                logger.info({'task': 'check_disbursement_status_schedule',
                             'disbursement_id': disbursement.id,
                             'status': 'loan not found'})
                continue

            # Skip check disbursement status for J1 & JTurbo loan
            if loan.is_j1_or_jturbo_loan():
                logger.info({'task': 'check_disbursement_status_schedule',
                             'loan_id': loan.id,
                             'status': 'skip J1 & JTurbo'})
                continue

            application = loan.application
            if not application:
                application = loan.get_application

            pg_customer_data = PaymentGatewayCustomerData.objects.filter(
                customer_id=loan.customer.id).last()
            if not pg_customer_data:
                logger.info({'task': 'check_disbursement_status_schedule',
                             'loan_id': loan.id,
                             'status': 'pg_customer_data not found'})
                continue

            payment_gateway_transaction = PaymentGatewayTransaction.objects.filter(
                disbursement_id=disbursement.id
            ).last()
            if not payment_gateway_transaction:
                logger.info({'task': 'check_disbursement_status_schedule',
                             'loan_id': loan.id,
                             'status': 'payment_gateway_transaction not found'})
                continue
            data = {
                'application_id': application.id,
                'pg_customer_data_id': pg_customer_data.id,
                'payment_gateway_transaction_id': payment_gateway_transaction.id,
                'disbursement_id': disbursement.id
            }

            verify_ayoconnect_loan_disbursement_status.delay(data)


def remove_duplicate_archive_log(logs_will_be_archived):
    mapping_log = {}
    for log in logs_will_be_archived:
        mapping_log.update({log.id: log})

    logs_id_already_archived = set(PaymentGatewayApiLogArchival.objects.
                                   filter(id__in=mapping_log.keys()).
                                   values_list('id', flat=True))

    result = []
    for key, value in mapping_log.items():
        if key not in logs_id_already_archived:
            result.append(value)
    return result


@task(queue="grab_global_queue")
def payment_gateway_api_log_archival_task():
    logger.info({
        "action": "payment_gateway_api_log_archival_task",
        "message": "start triggering payment_gateway_api_log_archival_task"
    })

    batch_size = 100
    older_than_days = 30
    today = datetime.today()
    one_month_ago = today - timedelta(days=older_than_days)
    one_month_ago = one_month_ago.replace(hour=0, minute=0, second=0, microsecond=0)
    logs_archived = 0

    logs_will_be_archived = []
    logs_id_will_be_deleted = []
    for log in PaymentGatewayApiLog.objects.filter(cdate__lt=one_month_ago).iterator():
        logs_will_be_archived.append(log)
        logs_id_will_be_deleted.append(log.id)
        logs_archived += 1

        if len(logs_will_be_archived) >= batch_size:
            logs_will_be_archived = remove_duplicate_archive_log(
                logs_will_be_archived=logs_will_be_archived
            )
            with transaction.atomic():
                PaymentGatewayApiLogArchival.objects.bulk_create(logs_will_be_archived)
                PaymentGatewayLogIdentifier.objects.filter(
                    payment_gateway_api_log_id__in=logs_id_will_be_deleted).delete()
                PaymentGatewayApiLog.objects.filter(id__in=logs_id_will_be_deleted).delete()
                logs_will_be_archived = []
                logs_id_will_be_deleted = []

    if logs_will_be_archived:
        logs_will_be_archived = remove_duplicate_archive_log(
            logs_will_be_archived=logs_will_be_archived
        )
        with transaction.atomic():
            PaymentGatewayApiLogArchival.objects.bulk_create(logs_will_be_archived)
            PaymentGatewayLogIdentifier.objects.filter(
                payment_gateway_api_log_id__in=logs_id_will_be_deleted).delete()
            PaymentGatewayApiLog.objects.filter(id__in=logs_id_will_be_deleted).delete()

    logger.info({
        "action": "payment_gateway_api_log_archival_task",
        "message": "finish triggering payment_gateway_api_log_archival_task"
    })

    msg = "[Payment Gateway API logs archived] success archived {} logs".format(logs_archived)
    send_payment_gateway_vendor_api_alert_slack.delay(
        msg_header=msg,
        msg_type=3
    )
    return logs_archived


@task(queue='loan_high')
def process_disbursement_payment_gateway(disbursement_data):
    transaction_id = disbursement_data['transaction_id']
    disbursement = get_disbursement_process_by_transaction_id(transaction_id)
    disbursement.update_status(disbursement_data)
    disbursement_id = disbursement.get_id()

    loan = Loan.objects.filter(disbursement_id=disbursement_id).order_by('cdate').last()
    application = loan.application
    if not application:
        application = loan.get_application

    current_flow = [
        application.is_julo_one,
        application.is_grab,
        application.is_axiata_flow,
        application.is_julover,
        application.is_merchant_flow,
        application.is_julo_starter,
        application.is_mf_web_app_flow,
        application.is_julo_one_ios,
    ]
    if loan and application and any(flow() for flow in current_flow):
        if disbursement.is_success():
            if loan.status == LoanStatusCodes.CURRENT:
                return
            elif loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)
            lender = loan.lender
            if lender and lender.lender_name in LenderCurrent.escrow_lender_list():
                update_lender_balance_current_for_disbursement(loan.id)
            julo_one_loan_disbursement_success(loan)
        elif disbursement.is_failed():
            julo_one_loan_disbursement_failed(loan, payment_gateway_failed=True)

    return


@task(queue="channeling_loan_normal")
def process_daily_disbursement_limit_whitelist_task(
    user_id: int, document_id: int, form_data: Dict[str, str]
):
    def _send_logger(**kwargs):
        logger_data = {
            'action': 'disbursement.tasks.process_daily_disbursement_limit_whitelist_task',
            'user': user_id,
            **kwargs,
        }
        logger.info(logger_data)

    _send_logger(message='start execute daily disbursement whitelist file')
    url = form_data['url_field']
    if document_id:
        document = Document.objects.get_or_none(
            pk=document_id, document_type=DailyDisbursementLimitWhitelistConst.DOCUMENT_TYPE
        )
        if document:
            url = document.document_url

    if not url:
        _send_logger(message='data not provide', document=document_id, form_data=form_data)
        return

    process_daily_disbursement_limit_whitelist(url=url, user_id=user_id)

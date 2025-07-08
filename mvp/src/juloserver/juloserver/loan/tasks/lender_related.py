import logging
import math

from celery import task
from django.db import transaction, connection
from django.utils import timezone
from datetime import timedelta, time
from dateutil.relativedelta import relativedelta
from rest_framework import status
from django.db.utils import ProgrammingError

from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo.services import record_disbursement_transaction
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import (
    Loan,
    SepulsaTransaction,
    FeatureSetting,
    FDCInquiry,
    Customer,
)
from juloserver.followthemoney.models import (
    LenderApproval,
    LenderApprovalTransactionMethod,
    LenderBalanceCurrent,
)
from juloserver.disbursement.models import Disbursement
from juloserver.disbursement.services.xfers import XfersConst, XfersService
from juloserver.disbursement.constants import (
    DisbursementVendors,
    AyoconnectConst,
    DisbursementStatus,
    AyoconnectErrorCodes,
    AyoconnectErrorReason,
    AyoconnectFailoverXfersConst,
)
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.grab.clients.clients import GrabClient
from juloserver.grab.models import GrabLoanData
from juloserver.loan.exceptions import LenderException
from juloserver.partnership.models import PartnershipTransaction

from juloserver.payment_point.clients import get_julo_sepulsa_loan_client
from juloserver.ecommerce.juloshop_service import (
    juloshop_disbursement_process,
    get_juloshop_transaction_by_loan,
)

from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.julo.clients import get_voice_client_v2_for_loan, get_julo_sentry_client
from juloserver.julo.constants import (
    ReminderTypeConst,
    VendorConst,
    VoiceTypeStatus,
    FeatureNameConst,
)
from juloserver.julo.models import (
    VendorDataHistory,
    VoiceCallRecord,
)
from juloserver.account.models import Account
from juloserver.account.services.account_related import get_account_property_by_account
from juloserver.streamlined_communication.utils import payment_reminder_execution_time_limit

from juloserver.julo.utils import format_nexmo_voice_phone_number
from juloserver.disbursement.services import AyoconnectService
from juloserver.loan import utils as loan_utils
from django.db.models import F, ExpressionWrapper, Value, DateTimeField
from django.db.models.functions import Coalesce
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.loan.constants import FDCUpdateTypes
from juloserver.payment_point.services.ewallet_related import xfers_ewallet_disbursement_process
from juloserver.partnership.services.services import get_parameters_fs_partner_other_active_platform

logger = logging.getLogger(__name__)


@task(queue="loan_high")
def julo_one_disbursement_trigger_task(loan_id, new_payment_gateway=False):
    from ..services.lender_related import (
        julo_one_disbursement_process,
        payment_point_disbursement_process,
        credit_card_disbursement_process,
    )
    from ..services.lender_related import qris_disbursement_process
    from juloserver.julo_financing.services.crm_services import julo_financing_disbursement_process
    from juloserver.partnership.tasks import proceed_cashin_confirmation_linkaja_task

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'julo_one_disbursement_trigger_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan_id,
            }
        )

    lender_balance = LenderBalanceCurrent.objects.get_or_none(lender_id=loan.lender_id)
    if lender_balance and lender_balance.available_balance < loan.loan_amount:
        base_log_data = {
            'action': 'juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task',
            'message': 'Lender {} has insufficient balance'.format(loan.lender.lender_name),
            'lender_id': loan.lender_id,
        }

        sentry_client = get_julo_sentry_client()
        sentry_client.captureMessage(base_log_data)

        logger.info(
            {
                **base_log_data,
                'loan_id': loan_id,
            }
        )
        return

    # check for 212 and AYC
    disbursement = Disbursement.objects.filter(
        pk=loan.disbursement_id,
        method__in=(DisbursementVendors.AYOCONNECT, DisbursementVendors.PG),
    ).exists()
    # only check j1 and jturbo, and fund disbursal ongoing
    if (
        loan.status == LoanStatusCodes.FUND_DISBURSAL_ONGOING
        and disbursement
        and loan.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]
    ):
        julo_one_disbursement_process(loan, new_payment_gateway=new_payment_gateway)
        return

    can_disburse_statuses = [
        LoanStatusCodes.LENDER_APPROVAL,
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
    ]
    if loan.status in can_disburse_statuses:
        if loan.is_qris_product:
            qris_disbursement_process(loan)
            return

        if loan.is_credit_card_product:
            credit_card_disbursement_process(loan)
            return

        if loan.is_ecommerce_product and get_juloshop_transaction_by_loan(loan):
            juloshop_disbursement_process(loan)
            return

        if loan.is_ewallet_product and loan.is_xfers_ewallet_transaction:
            xfers_ewallet_disbursement_process(loan)
            return

        if loan.is_jfinancing_product:
            julo_financing_disbursement_process(loan)
            return

        if loan.is_axiata_loan():
            new_status_code = LoanStatusCodes.FUND_DISBURSAL_ONGOING
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=new_status_code,
                change_by_id=loan.application.customer.user_id,
                change_reason="Axiata process to 212",
            )
            return

        sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
        if not sepulsa_transaction:
            partnership_transaction = (
                PartnershipTransaction.objects.filter(loan=loan).only('id').order_by('-id').first()
            )
            if partnership_transaction:
                proceed_cashin_confirmation_linkaja_task.delay(loan.id)
            else:
                julo_one_disbursement_process(loan, new_payment_gateway=new_payment_gateway)
        elif sepulsa_transaction:
            payment_point_disbursement_process(sepulsa_transaction)


@task(queue="loan_high")
def grab_disbursement_trigger_task(loan_id, retry_times=0):
    from ..services.lender_related import (
        julo_one_disbursement_process,
        payment_point_disbursement_process,
        is_grab_lender_balance_sufficient,
    )
    from juloserver.grab.services.loan_related import check_grab_auth_success

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'julo_one_disbursement_trigger_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan_id,
            }
        )

    sufficient_balance, message = is_grab_lender_balance_sufficient(loan)
    if not sufficient_balance:
        raise JuloException(
            {
                'action': 'juloserver.loan.tasks.lender_related.grab_disbursement_trigger_task',
                'message': message,
                'loan_id': loan_id,
            }
        )

    is_auth_called = check_grab_auth_success(loan.id)
    if not is_auth_called:
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.LENDER_REJECT,
            change_reason="Auth Redundency Check 1 - Failure",
        )
        raise JuloException(
            {
                'action': 'juloserver.loan.tasks.lender_related.grab_disbursement_trigger_task',
                'message': "Attempting Disbursement before Auth Success",
                'loan_id': loan_id,
            }
        )
    can_disburse_statuses = [LoanStatusCodes.LENDER_APPROVAL, LoanStatusCodes.FUND_DISBURSAL_FAILED]
    if loan.status in can_disburse_statuses:
        sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
        if not sepulsa_transaction:
            julo_one_disbursement_process(loan, grab=True)
        elif sepulsa_transaction:
            payment_point_disbursement_process(sepulsa_transaction)


@task(queue="loan_high")
def julo_one_lender_auto_approval_task(loan_id):
    from juloserver.loan.services.lender_related import (
        is_application_whitelist_manual_approval_feature,
    )

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'julo_one_lender_auto_approval_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan.id,
            }
        )

    today = timezone.localtime(timezone.now())
    lender_approval = LenderApproval.objects.get_or_none(partner=loan.partner)

    if lender_approval:
        in_range = False
        if lender_approval.end_date:
            in_range = lender_approval.start_date <= today <= lender_approval.end_date

        auto_approve = lender_approval.is_auto

        if loan.is_axiata_loan():
            application = loan.application
        else:
            application = loan.get_application

        if is_application_whitelist_manual_approval_feature(application.id):
            auto_approve = False

        in_endless = today >= lender_approval.start_date and lender_approval.is_endless
        if auto_approve and (in_range or in_endless):
            if lender_approval.delay:
                gaps = relativedelta(
                    hours=lender_approval.delay.hour,
                    minutes=lender_approval.delay.minute,
                    seconds=lender_approval.delay.second,
                )

                transaction_method_approval = LenderApprovalTransactionMethod.objects.filter(
                    lender_approval=lender_approval, transaction_method=loan.transaction_method
                ).last()
                if transaction_method_approval:
                    gaps = relativedelta(
                        hours=transaction_method_approval.delay.hour,
                        minutes=transaction_method_approval.delay.minute,
                        seconds=transaction_method_approval.delay.second,
                    )

                julo_one_generate_auto_lender_agreement_document_task.delay(loan.id)
                julo_one_disbursement_trigger_task.apply_async(
                    (loan.id, True), eta=timezone.localtime(timezone.now()) + gaps
                )
            else:
                if auto_approve:
                    lender_approval.update_safely(is_auto=False)
        else:
            if auto_approve and today >= lender_approval.start_date:
                lender_approval.update_safely(is_auto=False)


@task(name="grab_lender_auto_approval_task", queue="loan_high")
def grab_lender_auto_approval_task(loan_id, retry_times=0):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'julo_one_lender_auto_approval_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan.id,
            }
        )

    today = timezone.localtime(timezone.now())
    lender_approval = LenderApproval.objects.get_or_none(partner=loan.partner)

    if lender_approval:
        julo_one_generate_auto_lender_agreement_document_task.delay(loan.id)
        in_range = False
        if lender_approval.end_date:
            in_range = lender_approval.start_date <= today <= lender_approval.end_date

        in_endless = today >= lender_approval.start_date and lender_approval.is_endless
        if lender_approval.is_auto and (in_range or in_endless):
            if lender_approval.delay:
                gaps = relativedelta(
                    hours=lender_approval.delay.hour,
                    minutes=lender_approval.delay.minute,
                    seconds=lender_approval.delay.second,
                )
                grab_disbursement_trigger_task.apply_async(
                    (loan.id,), eta=timezone.localtime(timezone.now()) + gaps
                )
            else:
                if lender_approval.is_auto:
                    lender_approval.update_safely(is_auto=False)
        else:
            if lender_approval.is_auto and today >= lender_approval.start_date:
                lender_approval.update_safely(is_auto=False)


@task(queue="loan_high")
def loan_lender_approval_process_task(loan_id, is_success_digisign=None, lender_ids=None):
    from ..services.lender_related import julo_one_lender_auto_matchmaking
    from juloserver.loan.tasks.sphp import upload_sphp_to_oss

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise LenderException(
            {
                'action': 'loan_lender_approval_process',
                'message': 'Loan ID not found!!',
                'loan_id': loan.id,
            }
        )
    if not loan.lender_id:
        lender = julo_one_lender_auto_matchmaking(loan, lender_ids=lender_ids)
        if not lender:
            logger.error({
                'action': 'loan_lender_approval_process',
                'message': 'no lender available for this loan!!',
                'loan_id': loan.id,
            })
            return False

        # this only for handle FTM
        partner = lender.user.partner
        loan.partner = partner
        loan.lender = lender
        loan.save()

    if loan.account:
        application = loan.get_application
        is_not_merchant_financing_product = True
        if application.partner and application.partner.is_csv_upload_applicable:
            is_not_merchant_financing_product = False

        if not application.is_merchant_flow() and is_not_merchant_financing_product:
            if not is_success_digisign:
                upload_sphp_to_oss(loan.id)

        if loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
            grab_lender_auto_approval_task.apply_async((loan.id,))
        elif not application.is_axiata_flow():
            julo_one_lender_auto_approval_task.delay(loan.id)
    else:
        if loan.is_axiata_loan():
            upload_sphp_to_oss(loan.id)
            julo_one_lender_auto_approval_task.delay(loan.id)


@task(queue="loan_high")
def loan_disbursement_retry_task(loan_id, max_retries):
    from juloserver.loan.services.lender_related import julo_one_loan_disbursement_failed
    from juloserver.loan.services.lender_related import julo_one_loan_disbursement_success

    logger.info(
        {
            'task': 'loan_disbursement_retry_task',
            'loan_id': loan_id,
            'max_retries': max_retries,
            'status': 'start loan_disbursement_retry_task',
        }
    )

    loan = Loan.objects.get(pk=loan_id)
    if not loan:
        logger.info(
            {'task': 'loan_disbursement_retry_task', 'loan_id': loan_id, 'status': 'loan not found'}
        )
        return

    disbursement_id = loan.disbursement_id
    disbursement_obj = Disbursement.objects.filter(pk=disbursement_id).last()
    method = disbursement_obj.method
    if method == DisbursementVendors.PG:
        return

    if method == DisbursementVendors.AYOCONNECT:
        ayoconnect_loan_disbursement_retry.delay(loan_id, max_retries)
        return

    disbursement = Disbursement.objects.get_or_none(
        pk=loan.disbursement_id,
        method=DisbursementVendors.XFERS,
        disburse_status=XfersConst().MAP_STATUS[XfersConst().STATUS_FAILED],
    )
    if not disbursement:
        logger.info(
            {
                'task': 'loan_disbursement_retry_task',
                'loan_id': loan_id,
                'status': 'disbursement method is not xfers or status not failed',
            }
        )
        return

    is_retrying, response = XfersService().check_disburse_status(disbursement)
    if is_retrying:
        with transaction.atomic():
            if disbursement.retry_times >= max_retries:
                julo_one_loan_disbursement_failed(loan, force_failed=True)
                logger.info(
                    {
                        'task': 'loan_disbursement_retry_task',
                        'loan_id': loan_id,
                        'status': 'max_retries exceeded sent it to status 218',
                        'response': response,
                    }
                )
            else:
                disbursement.retry_times += 1
                disbursement.save(update_fields=['retry_times', 'udate'])
                julo_one_disbursement_trigger_task(loan.id, True)

                logger.info(
                    {
                        'task': 'loan_disbursement_retry_task',
                        'loan_id': loan_id,
                        'status': 'retrying disburse',
                        'response': response,
                    }
                )
    else:
        if response['status'] == XfersConst().STATUS_COMPLETED:
            if loan.partner and loan.partner.is_active_lender:
                record_disbursement_transaction(loan)
            julo_one_loan_disbursement_success(loan)

            logger.info(
                {
                    'task': 'loan_disbursement_retry_task',
                    'loan_id': loan_id,
                    'status': 'disbursement completed based on check_disburse_status',
                    'response': response,
                }
            )


@task(queue="loan_high")
def ayoconnect_loan_disbursement_retry(loan_id, max_retries):
    from juloserver.loan.services.lender_related import (
        ayoconnect_loan_disbursement_failed,
        switch_disbursement_to_xfers,
        is_disbursement_stuck_less_than_threshold,
        handle_ayoconnect_beneficiary_errors_on_disbursement,
    )
    from juloserver.disbursement.tasks import send_payment_gateway_vendor_api_alert_slack

    logger.info(
        {
            'task': 'ayoconnect_loan_disbursement_retry',
            'loan_id': loan_id,
            'message': 'start ayoconnect disbursement retry task',
        }
    )

    loan = Loan.objects.get(pk=loan_id)
    if not loan:
        logger.info(
            {
                'task': 'ayoconnect_loan_disbursement_retry',
                'loan_id': loan_id,
                'status': 'loan not found',
            }
        )
        return

    disbursement = Disbursement.objects.get_or_none(
        pk=loan.disbursement_id,
        method=DisbursementVendors.AYOCONNECT,
        disburse_status=DisbursementStatus.FAILED,
    )
    if not disbursement:
        logger.info(
            {
                'task': 'ayoconnect_loan_disbursement_retry',
                'loan_id': loan_id,
                'status': 'disbursement method is not ayoconnect or status not failed',
            }
        )
        return

    if loan.status not in {
        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
    }:
        logger.info(
            {
                'task': 'ayoconnect_loan_disbursement_retry',
                'loan_id': loan_id,
                'status': "can't retry loan status not failed or ongoing",
            }
        )
        return

    if loan.is_j1_or_jturbo_loan():
        # error code already saved in disbursement.reason for both API & callback
        if disbursement.reason not in AyoconnectErrorCodes.all_existing_error_codes():
            # keep loan stuck when error code is not in the handled list
            return

        with transaction.atomic():
            if not is_disbursement_stuck_less_than_threshold(disbursement.cdate):
                # more than 1 day passed, cancel and dont switch to xfers regardless retry count
                update_loan_status_and_loan_history(
                    loan_id=loan_id,
                    new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
                )
                return

            is_switch_to_xfers = (
                disbursement.reason in AyoconnectErrorCodes.force_switch_to_xfers_error_codes()
                or disbursement.retry_times >= max_retries
            )
            if is_switch_to_xfers:
                # if Loan is AYC E-wallet => Mark failed if reach max retry
                if loan.transaction_method_id == TransactionMethodCode.DOMPET_DIGITAL.code:
                    update_loan_status_and_loan_history(
                        loan_id=loan_id,
                        new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
                    )
                    return

                switch_disbursement_to_xfers(
                    disbursement=disbursement,
                    lender_name=loan.lender.lender_name,
                    reason=AyoconnectFailoverXfersConst.J1_FORCE_SWITCH_MAPPING.get(
                        disbursement.reason, AyoconnectFailoverXfersConst.MAX_RETRIES_EXCEEDED
                    ),
                )
            else:
                handle_ayoconnect_beneficiary_errors_on_disbursement(
                    loan=loan, disbursement_reason=disbursement.reason
                )

                disbursement.retry_times += 1
                disbursement.save(update_fields=['retry_times'])

            julo_one_disbursement_trigger_task(loan_id)
        return

    with transaction.atomic():
        grab_disbursement_retry_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRAB_DISBURSEMENT_RETRY, is_active=True
        ).exists()
        if (
            disbursement.retry_times >= max_retries
            or not grab_disbursement_retry_feature_setting
            or disbursement.reason == AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE
        ):
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER, is_active=True
            ).last()
            if feature_setting:
                from juloserver.loan.services.lender_related import julo_one_disbursement_process

                logger.info(
                    {
                        'task': 'ayoconnect_loan_disbursement_retry',
                        'loan_id': loan_id,
                        'status': 'failover ayoconnect to xfer',
                        'disbursement_id': disbursement.id,
                        'disburse_status': disbursement.disburse_status,
                        'retry_times': disbursement.retry_times,
                    }
                )
                disbursement.retry_times += 1
                disbursement.save(update_fields=['retry_times', 'udate'])
                julo_one_disbursement_process(loan)
            else:
                ayoconnect_loan_disbursement_failed(loan, force_failed=True)
                logger.info(
                    {
                        'task': 'ayoconnect_loan_disbursement_retry',
                        'loan_id': loan_id,
                        'status': 'max_retries exceeded sent it to status 213',
                        'disbursement_id': disbursement.id,
                        'disburse_status': disbursement.disburse_status,
                        'retry_times': disbursement.retry_times,
                    }
                )

                send_payment_gateway_vendor_api_alert_slack.delay(
                    err_message="max retry exceeded for disbursement_id {}, updating to 213".format(
                        disbursement.id
                    ),
                    msg_type=2,
                )
        else:
            disbursement.retry_times += 1
            disbursement.save(update_fields=['retry_times', 'udate'])
            julo_one_disbursement_trigger_task(loan.id)

            logger.info(
                {
                    'task': 'ayoconnect_loan_disbursement_retry',
                    'loan_id': loan_id,
                    'status': 'retrying disburse',
                    'retry_times': disbursement.retry_times,
                }
            )


@task(queue="loan_high")
def loan_payment_point_disbursement_retry_task(loan_id, max_retries):
    from juloserver.loan.services.lender_related import julo_one_loan_disbursement_failed
    from juloserver.loan.services.lender_related import julo_one_loan_disbursement_success

    loan = Loan.objects.get(pk=loan_id)
    if not loan:
        logger.info(
            {
                'task': 'loan_payment_point_disbursement_retry_task',
                'loan_id': loan_id,
                'status': 'loan not found',
            }
        )
        return
    sepulsa_transaction = SepulsaTransaction.objects.filter(
        loan=loan, transaction_status='failed'
    ).last()
    if not sepulsa_transaction:
        logger.info(
            {
                'task': 'loan_payment_point_disbursement_retry_task',
                'loan_id': loan_id,
                'status': 'sepulsa_transaction not found',
            }
        )
        return
    julo_sepulsa_client = get_julo_sepulsa_loan_client()
    # check transaction_code before getting transaction detail to avoid raising exception with None
    # When transaction_code is not None
    # the flow continute retrying 3 times as our expectation if it failed
    response = None
    if sepulsa_transaction.transaction_code:
        response = julo_sepulsa_client.get_transaction_detail(sepulsa_transaction)
        if (
            'response_code' in response
            and response["response_code"] == SepulsaResponseCodes.SUCCESS
        ):
            julo_one_loan_disbursement_success(loan)
            logger.info(
                {
                    'task': 'loan_payment_point_disbursement_retry_task',
                    'loan_id': loan_id,
                    'status': 'disbursement completed based on check_disburse_status',
                    'response': response,
                }
            )
            return
    with transaction.atomic():
        if sepulsa_transaction.retry_times >= max_retries:
            julo_one_loan_disbursement_failed(loan, force_failed=True)
            logger.info(
                {
                    'task': 'loan_payment_point_disbursement_retry_task',
                    'loan_id': loan_id,
                    'status': 'max_retries exceeded sent it to status 218',
                }
            )
        else:
            sepulsa_transaction.retry_times += 1
            sepulsa_transaction.save(update_fields=['retry_times', 'udate'])
            julo_one_disbursement_trigger_task(loan.id)

            logger.info(
                {
                    'task': 'loan_payment_point_disbursement_retry_task',
                    'loan_id': loan_id,
                    'status': 'retrying disburse',
                    'response': response,
                }
            )


@task(name="grab_lender_manual_approval_task")
def grab_lender_manual_approval_task(loan_id, retry_times=0):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'julo_one_lender_auto_approval_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan.id,
            }
        )

    lender_approval = LenderApproval.objects.get_or_none(partner=loan.partner)

    if lender_approval:
        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
        txn_id = grab_loan_data.auth_transaction_id if grab_loan_data else None
        try:
            response = GrabClient.submit_loan_creation(
                loan_id=loan.id, customer_id=loan.customer.id, txn_id=txn_id
            )
        except AttributeError as ae:
            if 'document_url' in str(ae):
                if retry_times > 3:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.GRAB_AUTH_FAILED,
                        change_reason="Grab API Failure Limit reached",
                    )
                    return
                grab_lender_manual_approval_task.apply_async(
                    (loan.id, retry_times + 1),
                    eta=timezone.localtime(timezone.now()) + relativedelta(hours=1),
                )
                return
            raise
        if response.status_code not in [status.HTTP_200_OK, status.HTTP_201_CREATED]:
            logger.error("GRAB submit_loan_creation API Failed for loan id {}".format(loan.id))
            if response.status_code >= 500:
                if retry_times > 3:
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.GRAB_AUTH_FAILED,
                        change_reason="Grab API Failure Limit reached",
                    )
                    return

                grab_lender_manual_approval_task.apply_async(
                    (loan.id, retry_times + 1),
                    eta=timezone.localtime(timezone.now()) + relativedelta(minutes=2),
                )
                return

            elif response.status_code >= 400 and response.status_code < 500:
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=LoanStatusCodes.LENDER_REJECT,
                    change_reason="Grab API Failure",
                )
                return

        grab_disbursement_trigger_task.delay(loan.id)


@task(name="julo_one_generate_auto_lender_agreement_document_task")
def julo_one_generate_auto_lender_agreement_document_task(loan_id):
    from ..services.lender_related import julo_one_generate_auto_lender_agreement_document

    julo_one_generate_auto_lender_agreement_document(loan_id)


@task(queue="loan_robocall", rate_limit='10/s')
@payment_reminder_execution_time_limit
@transaction.atomic
def send_promo_code_robocall_subtask(
    customer_id: int,
    phone_number: str,
    gender: str,
    full_name: str,
    loan_info_dict: dict,
    template_text: str,
    list_phone_numbers: list,
    template_code: str,
):
    from juloserver.loan.services.robocall import rotate_phone_number_application

    if gender.lower() == 'pria':
        title = 'Bapak'
    elif gender.lower() == 'wanita':
        title = 'Ibu'
    else:
        title = 'Bapak/Ibu'

    ncco_dict = [
        {
            'action': 'talk',
            'voiceName': 'Damayanti',
            'text': template_text.format(title=title, customer_name=full_name, **loan_info_dict),
        },
    ]

    # rotate phone number by application
    account = Account.objects.filter(customer_id=customer_id).last()
    application = account.get_active_application()
    if not application:
        application = account.application_set.last()

    call_from = rotate_phone_number_application(application, list_phone_numbers)

    # record data
    voice_call_record = VoiceCallRecord.objects.create(
        template_code=template_code,
        event_type=VoiceTypeStatus.APP_CAMPAIGN,
        voice_identifier=None,
        application=application,
    )
    VendorDataHistory.objects.create(
        vendor=VendorConst.NEXMO,
        template_code=template_code,
        customer_id=customer_id,
        reminder_type=ReminderTypeConst.ROBOCALL_TYPE_REMINDER,
    )

    # start blast
    logger.info(
        {
            'message': 'Triggering_voice_call_loan',
            'action': 'send_promo_code_robocall',
            'voice_call_record_id': voice_call_record.id,
            'customer_id': customer_id,
            'call_from': call_from,
        }
    )
    voice_client = get_voice_client_v2_for_loan()
    phone_number = format_nexmo_voice_phone_number(phone_number)
    response = voice_client.create_call(
        phone_number=phone_number,
        application_id=customer_id,
        ncco_dict=ncco_dict,
        call_from=call_from,
        capture_sentry=False,
    )

    # update data after blasting
    if response.get('conversation_uuid'):
        voice_call_record.update_safely(
            refresh=False,
            status=response['status'],
            direction=response['direction'],
            uuid=response['uuid'],
            conversation_uuid=response['conversation_uuid'],
        )
    else:
        voice_call_record.update_safely(
            refresh=False,
            status=response.get('status'),
        )

    logger.info(
        {
            'message': 'voice_call_triggered_for_loan',
            'action': 'send_promo_code_robocall',
            'voice_call_record_id': voice_call_record.id,
            'response': response,
        }
    )

    return response


@task(queue="loan_robocall")
def send_promo_code_robocall_task(path: str, template_code: str, wib_hour: int):
    from juloserver.loan.services.robocall import send_promo_code_robocall

    send_promo_code_robocall(path=path, template_code=template_code, wib_hour=wib_hour)


def retry_disbursement_stuck_212(disbursement_obj):
    from juloserver.disbursement.services import (
        get_disbursement_by_obj,
        AyoconnectDisbursementProcess,
    )

    disbursement = get_disbursement_by_obj(disbursement=disbursement_obj)
    disbursement.disburse()
    disbursement.get_data()

    is_ayoconnect_disbursement_process = isinstance(disbursement, AyoconnectDisbursementProcess)
    is_failed = disbursement.is_failed()

    return is_ayoconnect_disbursement_process, is_failed


def retry_ayoconnect_stuck_212_disbursement(loan_obj: Loan, disbursement_obj: Disbursement):
    '''retry disbursement process for ayoconnect that stuck at 212'''
    from juloserver.loan.services.lender_related import (
        julo_one_loan_disbursement_failed,
        ayoconnect_loan_disbursement_failed,
    )

    is_ayoconnect_disbursement_process, is_failed = retry_disbursement_stuck_212(disbursement_obj)
    if is_failed:
        if is_ayoconnect_disbursement_process:
            ayoconnect_loan_disbursement_failed(loan_obj)
        else:
            julo_one_loan_disbursement_failed(loan_obj)


def retry_disbursement_worker(cursor, query, loan_fields, disbursement_fields) -> dict:
    '''
    fetch multiple loan & disbursement data from db based on the query,
    then do disbursement by calling `retry_ayoconnect_stuck_212_disbursement` func
    '''
    result = {'row_count': 0, 'last_id': 0, 'loans_id': [], 'disbursements_id': []}

    try:
        cursor.execute(query)
    except ProgrammingError as err:
        logger.error({"action": "retry_disbursement_worker", "error": str(err)})
        return result

    for row in cursor.fetchall():
        n_loan_fields = len(loan_fields)
        loan_obj = loan_utils.parse_loan(row[:n_loan_fields], loan_fields)
        disbursement_obj = loan_utils.parse_disbursement(row[n_loan_fields:], disbursement_fields)

        if not loan_obj or not disbursement_obj:
            return result

        retry_ayoconnect_stuck_212_disbursement(
            loan_obj=loan_obj, disbursement_obj=disbursement_obj
        )
        result['last_id'] = disbursement_obj.id
        result['row_count'] += 1
        result['loans_id'].append(loan_obj.id)
        result['disbursements_id'].append(disbursement_obj.id)

    return result


@task(queue="loan_high")
def retry_ayoconnect_loan_stuck_at_212_task():
    '''retrying ayoconnect's loan that stuck at 212 because of lender balance is not sufficient'''
    batch_size = 50
    last_id = 0
    n_loan = 0
    loans_id = []
    disbursements_id = []

    logger.info(
        {
            "action": "retry_loan_stuck_at_212_task",
            "message": "start triggering retry_loan_stuck_at_212_task",
        }
    )

    # checking ayoconnect balance, if it's insufficient, just return it
    _, is_ayoconnect_have_sufficient_balance, _ = AyoconnectService().check_balance(
        AyoconnectConst.PERMISSIBLE_BALANCE_LIMIT
    )
    if not is_ayoconnect_have_sufficient_balance:
        logger.info(
            {
                "action": "retry_loan_stuck_at_212_task",
                "message": "{} retry_loan_stuck_at_212_task canceled".format(
                    AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE
                ),
            }
        )
        return {'n_loan': n_loan, 'loans_id': loans_id, 'disbursements_id': disbursements_id}

    loan_fields = loan_utils.get_table_fields(Loan._meta.db_table)
    disbursement_fields = loan_utils.get_table_fields(Disbursement._meta.db_table)

    with connection.cursor() as cursor:
        while True:
            row_count = 0
            query = loan_utils.generate_query_for_get_loan_and_disbursement(
                batch_size=batch_size,
                last_id=last_id,
                loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                disburse_status=DisbursementStatus.PENDING,
                disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
                method=DisbursementVendors.AYOCONNECT,
            )

            if query:
                result = retry_disbursement_worker(
                    cursor=cursor,
                    query=query,
                    loan_fields=loan_fields,
                    disbursement_fields=disbursement_fields,
                )
                last_id = result.get('last_id')
                row_count = result.get('row_count')
                loans_id += result.get('loans_id')
                disbursements_id += result.get('disbursements_id')

            n_loan += row_count
            if row_count == 0:
                break

    logger.info(
        {
            "action": "retry_loan_stuck_at_212_task",
            "message": "finish triggering retry_loan_stuck_at_212_task, {} loans".format(n_loan),
        }
    )
    return {'n_loan': n_loan, 'loans_id': loans_id, 'disbursements_id': disbursements_id}


@task(queue="loan_high")
def reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task():
    from juloserver.loan.services.lender_related import (
        reassign_lender_or_expire_loan_x211_in_first_time,
        reassign_lender_or_expire_loan_x211_in_next_retry,
    )

    ftm_configuration = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FTM_CONFIGURATION, category="followthemoney", is_active=True
    )
    if not ftm_configuration:
        return

    expired_loan_lenders = ftm_configuration.parameters.get('expired_loan_for_lenders')
    if not expired_loan_lenders:
        return

    time_now = timezone.now()
    loans = Loan.objects.annotate(
        expired_in=ExpressionWrapper(
            Coalesce(F('partner__lenderapproval__expired_in'), Value(time(0, 0))),
            output_field=DateTimeField(),
        )
    ).filter(
        loan_status_id=LoanStatusCodes.LENDER_APPROVAL,
        partner__lenderapproval__is_auto=False,
        lender__lender_name__in=expired_loan_lenders,
        partner__lenderapproval__expired_start_time__lte=timezone.localtime(timezone.now()).time(),
        partner__lenderapproval__expired_end_time__gte=timezone.localtime(timezone.now()).time(),
    )
    reassign_lender_or_expire_loan_x211_in_first_time(loans, time_now)
    reassign_lender_or_expire_loan_x211_in_next_retry(loans, time_now)

    logger.info(
        {
            "action": "reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task",
        }
    )


@task(queue='loan_high')
def fdc_inquiry_other_active_loans_from_platforms_task(
    fdc_inquiry_data: dict,
    customer_id: int,
    type_update: str,
    params: dict,
    retry_count=0,
):
    """
    FDC inquiry check other active loans from platforms
    params:: fdc_inquiry_data: {id: fdc_inquiry.pk, nik: customer.nik}
    params:: customer_id: customer.pk
    params:: type_update: it's from FDCUpdateTypes.
    params:: params: params for handing update data
    params:: retry_count: number of retry times
    """
    from juloserver.loan.services.loan_related import (
        handle_update_after_fdc_inquiry_success,
        handle_update_after_fdc_inquiry_failed_completely,
    )

    name_function_logger = "fdc_inquiry_other_active_loans_from_platforms_task"

    try:
        logger.info(
            {
                "function": name_function_logger,
                "action": "call get_and_save_fdc_data",
                "fdc_inquiry_data": fdc_inquiry_data,
                "retry_count": retry_count,
            }
        )
        get_and_save_fdc_data(fdc_inquiry_data, 1, False)
        handle_update_after_fdc_inquiry_success(type_update, customer_id, params)
        if type_update == FDCUpdateTypes.GRAB_SUBMIT_LOAN:
            return True

        return

    except FDCServerUnavailableException:
        logger.error(
            {
                "action": name_function_logger,
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        if type_update == FDCUpdateTypes.GRAB_SUBMIT_LOAN:
            return False
    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        logger.info(
            {
                "action": name_function_logger,
                "error": str(e),
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        if type_update == FDCUpdateTypes.GRAB_SUBMIT_LOAN:
            return False

    # retry step
    fdc_api_config = params['fdc_inquiry_api_config']
    max_retries = fdc_api_config['max_retries']
    if retry_count >= max_retries:
        logger.info(
            {
                "action": name_function_logger,
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        handle_update_after_fdc_inquiry_failed_completely(type_update, customer_id, params)
        return

    # retry_count * seconds after one time
    countdown = int(fdc_api_config['retry_interval_seconds']) * retry_count
    retry_count += 1
    logger.info(
        {
            "action": name_function_logger,
            "data": fdc_inquiry_data,
            "extra_data": "retry_count={}|count_down={}".format(retry_count, countdown),
        }
    )

    if type_update in {FDCUpdateTypes.GRAB_STUCK_150, FDCUpdateTypes.GRAB_DAILY_CHECKER}:
        fdc_inquiry_other_active_loans_from_platforms_task.apply_async(
            (fdc_inquiry_data, customer_id, type_update, params, retry_count,),
            countdown=countdown,
            queue='grab_global_queue'
        )
    else:
        fdc_inquiry_other_active_loans_from_platforms_task.apply_async(
            (fdc_inquiry_data, customer_id, type_update, params, retry_count,), countdown=countdown
        )


@task(queue='loan_high')
def process_loan_fdc_other_active_loan_from_platforms_task(
    loan_id, is_mf_partner_max_3_platform_check=False
):
    from juloserver.loan.services.loan_related import (
        get_parameters_fs_check_other_active_platforms_using_fdc,
        check_eligible_and_out_date_other_platforms,
        handle_reject_loan_for_active_loan_from_platform,
        create_fdc_inquiry_and_execute_check_active_loans,
    )

    logger.info(
        {
            "action": 'process_loan_status_fdc_active_loans_from_platforms',
            "loan_id": loan_id,
        }
    )
    loan = Loan.objects.get_or_none(pk=loan_id)
    customer = loan.customer
    application = customer.account.get_active_application()

    parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
    if is_mf_partner_max_3_platform_check:
        parameters = get_parameters_fs_partner_other_active_platform()
    if not parameters:
        # if we turn off fs => process loan as normal
        loan_lender_approval_process_task.delay(loan.pk)
        return

    outdated_threshold_days = parameters['fdc_data_outdated_threshold_days']
    number_allowed_platforms = parameters['number_of_allowed_platforms']

    is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
        customer.pk, application.pk, outdated_threshold_days, number_allowed_platforms
    )

    if is_out_date:
        params = dict(
            application_id=application.pk,
            loan_id=loan_id,
            fdc_data_outdated_threshold_days=outdated_threshold_days,
            number_of_allowed_platforms=number_allowed_platforms,
            fdc_inquiry_api_config=parameters['fdc_inquiry_api_config'],
        )
        create_fdc_inquiry_and_execute_check_active_loans(customer, params)
    elif is_eligible:
        loan_lender_approval_process_task.delay(loan.pk)
    else:
        handle_reject_loan_for_active_loan_from_platform(loan_id, customer.id)


@task(queue='loan_normal')
def fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
    customer_id: int, fs_params: dict, type_update=FDCUpdateTypes.DAILY_CHECKER
):
    logger.info(
        {
            "action": 'fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask',
            "loan_id": customer_id,
        }
    )
    customer = Customer.objects.get(pk=customer_id)
    application = customer.account.get_active_application()

    if not application:
        logger.error(
            {
                "action": 'fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask',
                "error": "Application not found",
                "customer_id": customer_id,
            }
        )
        return

    c_score_bypass = fs_params.get('c_score_bypass', {})
    if c_score_bypass and c_score_bypass.get('is_active', False):
        account_property = get_account_property_by_account(application.account)
        pgood = c_score_bypass.get('pgood_gte', 0)
        bypass_fdc_checking = account_property and account_property.pgood >= pgood
        if bypass_fdc_checking:
            return

    fdc_inquiry = FDCInquiry.objects.create(
        nik=customer.nik, customer_id=customer.pk, application_id=application.pk
    )
    params = dict(
        application_id=application.pk,
        fdc_inquiry_api_config=fs_params['fdc_inquiry_api_config'],
        number_of_allowed_platforms=fs_params['number_of_allowed_platforms'],
        fdc_inquiry_id=fdc_inquiry.pk,
    )
    fdc_inquiry_data = {'id': fdc_inquiry.pk, 'nik': customer.nik}
    fdc_inquiry_other_active_loans_from_platforms_task(
        fdc_inquiry_data, customer.pk, type_update, params
    )


@task(queue='loan_normal')
def fdc_inquiry_for_active_loan_from_platform_daily_checker_task():
    from juloserver.loan.services.loan_related import (
        get_parameters_fs_check_other_active_platforms_using_fdc,
        get_fdc_loan_active_checking_for_daily_checker,
    )

    parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
    if not parameters:
        return

    current_time = timezone.now()
    config = parameters['daily_checker_config']
    applied_product_lines = config.get('applied_product_lines', None)
    # we set the RPS to lowest (3 RPS)
    rps_throttling = config.get('rps_throttling', 3)
    customer_ids = get_fdc_loan_active_checking_for_daily_checker(
        parameters,
        current_time,
        applied_product_lines,
    )

    delay = math.ceil(1000 / rps_throttling)
    eta_time = timezone.localtime(current_time)
    for customer_id in customer_ids.iterator():
        eta_time += timedelta(milliseconds=delay)
        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask.apply_async(
            (
                customer_id,
                parameters,
            ),
            eta=eta_time,
        )

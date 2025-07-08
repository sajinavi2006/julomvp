import json
import logging
from typing import Dict, Any, List
from bulk_update.helper import bulk_update

from juloserver.channeling_loan.clients import (
    get_fama_sftp_client,
    get_permata_sftp_client,
    get_smf_channeling_api_client,
    get_dbs_sftp_client,
)
from juloserver.channeling_loan.constants.fama_constant import FAMAAutoApprovalConst
from juloserver.channeling_loan.services.bni_services import BNIDisbursementServices

from juloserver.julo.models import (
    Loan,
    PaymentEvent,
    Document,
    FeatureSetting,
)
from celery import task
from datetime import timedelta, datetime
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.channeling_loan.models import (
    ChannelingPaymentEvent,
    ChannelingLoanApprovalFile,
    ARSwitchHistory,
)
from juloserver.channeling_loan.services.general_services import (
    get_general_channeling_ineligible_conditions,
    loan_risk_acceptance_criteria_check,
    update_loan_lender,
    get_channeling_eligibility_status,
    generate_channeling_loan_status,
    get_selected_channeling_type,
    recalculate_channeling_payment_interest,
    initiate_channeling_loan_status,
    is_channeling_lender_dashboard_active,
    get_channeling_loan_status,
    update_channeling_loan_status,
    get_fama_channeling_admin_fee,
    encrypt_data_and_upload_to_sftp_server,
    chunks,
    send_notification_to_slack,
    filter_loan_adjusted_rate,
    download_latest_file_from_sftp_server,
    download_latest_fama_approval_file_from_sftp_server,
    decrypt_data,
    convert_fama_approval_content_from_txt_to_csv,
    mark_approval_file_processed,
    upload_approval_file_to_oss_and_create_document,
    calculate_old_lender_balance,
    calculate_new_lender_balance,
    approve_loan_for_channeling,
    filter_field_channeling,
    get_channeling_loan_configuration,
    is_block_regenerate_document_ars_config_active,
    process_loan_for_channeling,
    # record_channeling_tenure_cap,  # will update when tenure cap release
)
from juloserver.channeling_loan.services.loan_tagging_services import (
    execute_repayment_process_service,
    update_lender_osp_balance,
    get_outstanding_withdraw_amount,
    loan_tagging_process,
    daily_checker_loan_tagging,
    daily_checker_loan_tagging_clone_table,
    release_loan_tagging_dpd_90,
    execute_replenishment_loan_payment_by_user_process,
    execute_replenishment_matchmaking,
    get_loan_tagging_feature_setting_lenders,
    clone_ana_table,
    delete_temporary_dpd_table,
)
from juloserver.channeling_loan.services.bss_services import (
    send_loan_for_channeling_to_bss,
    check_disburse_transaction,
    is_holdout_users_from_bss_channeling,
    check_transfer_out_status,
    get_bss_refno,
)
from juloserver.channeling_loan.services.smf_services import (
    generate_smf_disbursement_file,
    generate_smf_zip_file,
    generate_smf_receipt_and_invoice,
    construct_smf_api_disbursement_data,
    construct_smf_api_check_transaction_data,
    check_loan_validation_for_smf,
    validate_smf_document_data,
)
from juloserver.channeling_loan.services.support_services import (
    retroload_address,
    FAMAApprovalFileServices,
)
from juloserver.channeling_loan.services.task_services import (
    construct_channeling_url_reader,
    send_consolidated_error_msg,
)
from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderBucket,
    LenderTransactionType,
    LoanLenderHistory,
)
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.channeling_loan.constants import (
    ChannelingConst,
    ChannelingStatusConst,
    ChannelingLenderLoanLedgerConst,
    GeneralIneligible,
    ChannelingActionTypeConst,
    PermataChannelingConst,
    ChannelingLoanApprovalFileConst,
    FAMAChannelingConst,
    ARSwitchingConst,
    FeatureNameConst,
)
from juloserver.channeling_loan.constants.smf_constants import (
    SMFChannelingConst,
)

from juloserver.channeling_loan.utils import replace_gpg_encrypted_file_name
from juloserver.channeling_loan.models import (
    LenderLoanLedger,
    LenderOspAccount,
    LenderLoanLedgerHistory,
    ChannelingLoanPayment,
    ChannelingLoanStatus,
    ChannelingLoanWriteOff,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.channeling_loan.constants.dbs_constants import DBSChannelingConst
from juloserver.sdk.services import xls_to_dict

from juloserver.channeling_loan.services.general_services import (
    check_loan_and_approve_channeling,
    convert_dbs_approval_content_from_txt_to_csv,
)
from juloserver.channeling_loan.services.fama_services import reassign_lender_fama_rejected_loans

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue="loan_low")
def send_loan_for_channeling_task(loan_id, lender_list=None, is_prefund=False):
    return_value = False
    loan = Loan.objects.select_related('customer').filter(pk=loan_id).last()

    if (
        loan.loan_status.status_code == LoanStatusCodes.CURRENT
        and loan.lender.is_pre_fund_channeling_flow
    ):
        logger.info(
            {
                'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                'loan_id': loan_id,
                'message': "prevent double hit",
            }
        )
        return return_value

    ineligible_conditions = get_general_channeling_ineligible_conditions(loan)
    for condition, is_met in ineligible_conditions.items():
        if is_met():
            message = condition.message
            logger.info({
                'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                'loan_id': loan_id,
                'message': message,
            })
            if loan:
                initiate_channeling_loan_status(loan, ChannelingConst.GENERAL, message)
            return return_value

    # to move to get_general_channeling_ineligible_conditions()
    if is_holdout_users_from_bss_channeling(loan.application_id2):
        message = "Exclude holdout users from bss channeling"
        logger.info({
            'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
            'loan_id': loan_id,
            'message': message,
        })
        initiate_channeling_loan_status(loan, ChannelingConst.GENERAL, message)
        return return_value

    now = timezone.localtime(timezone.now())
    channeling_type_list, channeling_loan_config = get_selected_channeling_type(
        loan, now, lender_list
    )
    if not channeling_type_list:
        message = GeneralIneligible.CHANNELING_TARGET_MISSING.message
        logger.info({
            'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
            'loan_id': loan_id,
            'message': message,
        })
        initiate_channeling_loan_status(loan, ChannelingConst.GENERAL, message)
        return return_value

    channeling_type_list = filter_loan_adjusted_rate(
        loan,
        channeling_type_list,
        channeling_loan_config,
    )
    if not channeling_type_list:
        message = GeneralIneligible.LOAN_ADJUSTED_RATE.message
        initiate_channeling_loan_status(loan, ChannelingConst.GENERAL, message)
        return return_value

    for channeling_type in channeling_type_list:
        channeling_eligibility_status = get_channeling_eligibility_status(
            loan, channeling_type, channeling_loan_config[channeling_type]
        )
        if not channeling_eligibility_status:
            message = "application not eligible"
            logger.info({
                'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                'loan_id': loan_id,
                'channeling_type': channeling_type,
                'message': message,
            })
            initiate_channeling_loan_status(loan, channeling_type, message)
            continue

        error = filter_field_channeling(loan.get_application, channeling_type)
        if error:
            logger.info(
                {
                    'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                    'loan_id': loan_id,
                    'channeling_type': channeling_type,
                    'message': error,
                }
            )
            initiate_channeling_loan_status(loan, channeling_type, error)
            continue

        loan.refresh_from_db()
        criteria_check_result, reason = loan_risk_acceptance_criteria_check(
            loan, channeling_type, channeling_loan_config[channeling_type]
        )
        if not criteria_check_result:
            logger.info({
                'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                'loan_id': loan_id,
                'channeling_type': channeling_type,
                'message': "not pass criteria",
                'reason': reason,
                'version': channeling_loan_config[channeling_type]['force_update']['VERSION'],
            })
            initiate_channeling_loan_status(loan, channeling_type, reason)
            continue

        channeling_interest_amount = 0
        if not is_prefund:
            new_interests = recalculate_channeling_payment_interest(
                loan, channeling_type, channeling_loan_config[channeling_type]
            )
            if not new_interests:
                message = "cannot generate new interest"
                logger.info(
                    {
                        'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                        'loan_id': loan_id,
                        'channeling_type': channeling_type,
                        'message': message,
                        'version': channeling_loan_config[channeling_type]['force_update'][
                            'VERSION'
                        ],
                    }
                )
                initiate_channeling_loan_status(loan, channeling_type, message)
                continue
            channeling_interest_amount = sum(new_interests.values())

        channeling_loan_status = generate_channeling_loan_status(
            initiate_channeling_loan_status(loan, channeling_type, ""),
            channeling_eligibility_status,
            channeling_interest_amount,
            channeling_loan_config[channeling_type],
            is_prefund=is_prefund,
        )
        if not channeling_loan_status:
            message = "cannot generate new channeling_loan status"
            logger.info({
                'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                'loan_id': loan_id,
                'channeling_type': channeling_type,
                'message': message,
                'version': channeling_loan_config[channeling_type]['force_update']['VERSION'],
            })
            initiate_channeling_loan_status(loan, channeling_type, message)
            continue

        # If BSS lender dashboard not enabled, send data to BSS
        if not is_channeling_lender_dashboard_active(channeling_type):
            channeling_type_config = (
                channeling_loan_config[channeling_type]
                .get("general", {})
                .get("CHANNELING_TYPE", ChannelingConst.API_CHANNELING_TYPE)
            )
            if channeling_type_config != ChannelingConst.MANUAL_CHANNELING_TYPE:
                if channeling_type == ChannelingConst.BSS:
                    send_loan_for_channeling_to_bss_task(
                        loan_ids=[loan.id],
                        channeling_loan_config=channeling_loan_config[channeling_type],
                        channeling_type=channeling_type,
                    )
                elif (
                    channeling_type == ChannelingConst.DBS
                    and loan.status in (LoanStatusCodes.LENDER_APPROVAL, LoanStatusCodes.CURRENT)
                ):
                    send_loans_for_channeling_to_dbs_task(loan_ids=[loan.id])

        if channeling_loan_status:
            if channeling_type == ChannelingConst.FAMA and not is_prefund:
                # update admin fee here if fama only
                channeling_loan_status.update_safely(
                    admin_fee=get_fama_channeling_admin_fee(
                        channeling_loan_status, channeling_loan_config[channeling_type]
                    )
                )

            return_value = True
            # implement dati address map
            application = loan.get_application
            if not application.channelingloanaddress_set.exists():
                retroload_address(
                    limit=1,
                    batch_size=25,
                    query_filter={'id': application.id},
                    key=channeling_type,
                )
            break

    return return_value


@task(queue="channeling_loan_normal")
def send_loan_for_channeling_to_bss_task(loan_ids, channeling_loan_config, channeling_type):
    if channeling_type != ChannelingConst.BSS:
        return

    select_related = ["account", "lender"]
    loans = Loan.objects.filter(id__in=loan_ids).select_related(*select_related)
    for loan in loans:
        status, message, retry_interval = send_loan_for_channeling_to_bss(
            loan, channeling_loan_config
        )
        logger.info(
            {
                'action': 'channeling_loan.tasks.send_loan_for_channeling_task',
                'status': status,
                'message': message,
                'retry_interval': retry_interval,
                'loan_id': loan.id,
            }
        )
        if status == ChannelingStatusConst.SUCCESS:
            check_transfer_out_status_task.delay(loan.id, channeling_type, 1)

        if status == ChannelingStatusConst.RETRY:
            eta_time = timezone.localtime(timezone.now()) + timedelta(minutes=retry_interval)
            check_disburse_transaction_task.apply_async((loan.id, channeling_type, 1), eta=eta_time)


@task(queue="channeling_loan_normal")
def retroload_all_application_address_task():
    _, application_ids = retroload_address(
        limit=1000,
        query_filter={
            "product_line_id": ProductLineCodes.J1,
            "cdate__lte": ChannelingConst.DEFAULT_TIMESTAMP
        },
        key="J1"
    )
    logger.info({
        'action': 'juloserver.channeling_loan.tasks.retroload_all_application_address_task',
        'application_ids': application_ids
    })


@task(queue="channeling_loan_normal")
def update_loan_lender_task(
    loan_id, new_lender_name, purpose, reason, lender_obj=None, username=None
):
    def _send_logger(**kwargs):
        logger_data = {
            'action': 'juloserver.channeling_loan.tasks.update_loan_lender_task',
            'loan_id': loan_id,
            'user': username,
            **kwargs,
        }
        logger.info(logger_data)

    _send_logger(message='start update_loan_lender_task')

    loan = Loan.objects.get(pk=loan_id)
    if not loan:
        _send_logger(message='Loan not found')
        return

    if lender_obj is None:
        lender_obj = LenderCurrent.objects.get(lender_name=new_lender_name)

    with transaction.atomic():
        old_lender, channeling_loan_history = update_loan_lender(
            loan, lender_obj, purpose, reason, is_channeling=True
        )

        if old_lender.is_pre_fund_channeling_flow:
            amount = loan.loan_amount
            transaction_type = LenderTransactionType.objects.get_or_none(
                transaction_type=LenderTransactionTypeConst.CHANNELING_PREFUND_REJECT
            )

            # Bring amount back to old lender
            calculate_old_lender_balance(
                loan.id, amount, old_lender, channeling_loan_history, transaction_type)

            # Deduct target lender balance
            calculate_new_lender_balance(
                loan.id, amount, lender_obj, channeling_loan_history, transaction_type)

    regenerate_summary_and_skrtp_agreement_for_ar_switching.delay(loan_id)

    lender_loan_ledger = LenderLoanLedger.objects.get_or_none(
        loan=loan,
        tag_type__in=[
            ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG
        ]
    )
    loan.refresh_from_db()
    if lender_loan_ledger and loan.lender == lender_obj:
        # check lender_loan_ledger exist and lender already updated
        lenders = get_loan_tagging_feature_setting_lenders()
        lenders = lenders.get(lender_loan_ledger.lender_osp_account.lender_account_name)
        if lender_obj.lender_name not in lenders:
            release_lender_loan_ledger_by_lender_task.delay(lender_loan_ledger.id)

    _send_logger(message='end update_loan_lender_task')


@task(queue="loan_low")
def insert_loan_write_off(loan_ids, channeling_type, document_id, reason, user_id):
    # loan_id is already validated before, no need to revalidate again
    channeling_loan_write_off = []
    for loan_id in loan_ids:
        channeling_loan_write_off.append(
            ChannelingLoanWriteOff(
                loan_id=loan_id,
                is_write_off=True,
                channeling_type=channeling_type,
                document_id=document_id,
                reason=reason,
                user_id=user_id,
            )
        )
    ChannelingLoanWriteOff.objects.bulk_create(channeling_loan_write_off)


@task(queue="loan_low")
def update_loan_write_off(
    channeling_loan_write_off_ids, channeling_type, document_id, reason, user_id
):
    # update if row already exist but is_write_off is False
    now = timezone.localtime(timezone.now())
    channeling_loan_write_offs = ChannelingLoanWriteOff.objects.filter(
        id__in=channeling_loan_write_off_ids
    )
    for channeling_loan_write_off in channeling_loan_write_offs:
        channeling_loan_write_off.udate = now
        channeling_loan_write_off.is_write_off = True
        channeling_loan_write_off.reason = reason
        channeling_loan_write_off.user_id = user_id
        channeling_loan_write_off.channeling_type = channeling_type
        channeling_loan_write_off.document_id = document_id

    bulk_update(
        channeling_loan_write_offs,
        update_fields=[
            'is_write_off',
            'udate',
            'reason',
            'user_id',
            'channeling_type',
            'document_id',
        ],
    )


@task(queue="channeling_loan_normal")
def release_lender_loan_ledger_by_lender_task(
    lender_loan_ledger_id
):
    lender_loan_ledger = LenderLoanLedger.objects.get_or_none(
        id=lender_loan_ledger_id,
        tag_type__in=[
            ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG
        ]
    )

    if not lender_loan_ledger:
        logger.error(
            {
                "action": "juloserver.channeling_loan.tasks.release_lender_loan_ledger_by_lender",
                "lender_loan_ledger_id": lender_loan_ledger_id,
                "message": "Lender Loan Ledger not found",
            }
        )
        return

    logger.info({
        'action': 'juloserver.channeling_loan.tasks.release_lender_loan_ledger_by_lender',
        'loan_id': lender_loan_ledger.loan_id,
        'lender_loan_ledger': lender_loan_ledger.id,
    })

    with transaction.atomic():
        lender_loan_ledger.tag_type = ChannelingLenderLoanLedgerConst.RELEASED_BY_LENDER
        lender_loan_ledger.save()
        # insert history
        LenderLoanLedgerHistory.objects.create(
            lender_loan_ledger=lender_loan_ledger,
            field_name='tag_type',
            old_value=lender_loan_ledger.tag_type,
            new_value=ChannelingLenderLoanLedgerConst.RELEASED_BY_LENDER,
        )
        if lender_loan_ledger.osp_amount > 0:
            # reduce balance and record history
            lender_osp_account = LenderOspAccount.objects.select_for_update().filter(
                pk=lender_loan_ledger.lender_osp_account_id
            ).last()
            total_loan_lender = 0
            total_loan_julo = 0
            if lender_loan_ledger.is_fund_by_julo:
                total_loan_julo = lender_loan_ledger.osp_amount
            else:
                total_loan_lender = lender_loan_ledger.osp_amount

            # Insert History
            update_lender_osp_balance(
                lender_osp_account,
                lender_osp_account.balance_amount,
                lender_osp_account.fund_by_lender - total_loan_lender,
                lender_osp_account.fund_by_julo - total_loan_julo,
                reason='released_by_lender',
            )
            # Update Balance
            lender_osp_account.update_safely(
                fund_by_lender=lender_osp_account.fund_by_lender - total_loan_lender,
                fund_by_julo=lender_osp_account.fund_by_julo - total_loan_julo,
                total_outstanding_principal=(
                    lender_osp_account.fund_by_lender
                    + lender_osp_account.fund_by_julo
                    - total_loan_lender
                    - total_loan_julo
                ),
            )


@task(queue="channeling_loan_normal")
def process_ar_switching_task(username, document_id, form_data, reason):
    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_ar_switching_task',
            'user': username,
            'reason': reason,
            **kwargs
        }
        logger.info(logger_data)

    _send_logger(message='start execute ar switching')
    url = form_data['url_field']
    if document_id:
        document = Document.objects.get_or_none(pk=document_id)
        if document:
            url = document.document_url

    if not url:
        _send_logger(message='data not provide', document=document_id, form_data=form_data)
        return

    reader = construct_channeling_url_reader(url)
    if reader.empty:
        _send_logger(
            message='data not provide', document=document_id, form_data=form_data, reader=reader,
            url=url
        )
        return

    batches = reason.split('batch:')
    slack_messages = ""
    lender_list = LenderCurrent.objects.values('lender_name', 'id')
    lender_map = {}
    for lender in lender_list:
        lender_map[lender['lender_name']] = lender['id']
    target_lender_name = form_data['lender_name']
    default_message = 'Switch failed on row *{}* due to *{}* from *{}* \n'.format(
        '{}', '{}', batches[1]
    )

    failed_count = 0
    row_count, _ = reader.shape

    ARSwitchHistory.objects.create(
        username=username,
        batch=reason,
        new_lender=target_lender_name,
        status=ARSwitchingConst.IN_PROGRESS_AR_SWITCH_STATUS,
    )

    for idx, row in reader.iterrows():
        message = default_message.format(idx + 1, '{}')
        pass_field_validation = True
        for field in ['loan_id', 'lender_name']:
            if field not in row:
                failed_count += 1
                slack_messages += message.format("{} not provided".format(field))
                pass_field_validation = False
        if not pass_field_validation:
            continue

        lender_id = lender_map.get(row['lender_name'])
        if not lender_id:
            failed_count += 1
            slack_messages += message.format("invalid lender name {}".format(row['lender_name']))
            continue

        if target_lender_name == row['lender_name']:
            failed_count += 1
            slack_messages += message.format(
                "current lender name in the file is the same with the lender name target"
            )
            continue

        loan = Loan.objects.get_or_none(pk=row['loan_id'])
        if not loan:
            failed_count += 1
            slack_messages += message.format("invalid loan id {}".format(row['loan_id']))
            continue

        if loan.lender_id != lender_id:
            failed_count += 1
            slack_messages += message.format(
                "invalid lender name not match with loan id {}".format(row['loan_id'])
            )
            continue

        update_loan_lender_task.delay(
            row['loan_id'], target_lender_name, "AR switching", reason, None, username
        )

    _send_logger(message='end execute ar switching')

    if slack_messages:
        send_notification_to_slack(
            slack_messages, settings.AR_SWITCHING_FAILED_SLACK_NOTIFICATION_CHANNEL
        )

    send_consolidated_error_msg(reason, row_count, failed_count)

    ARSwitchHistory.objects.create(
        username=username,
        batch=reason,
        new_lender=target_lender_name,
        status=ARSwitchingConst.FINISHED_AR_SWITCH_STATUS,
    )

    return True


@task(queue="loan_low")
def process_loan_write_off_task(
    username, document_id, form_data, reason, channeling_type, user_id=None
):
    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_loan_write_off_task',
            'user': username,
            'reason': reason,
            **kwargs,
        }
        logger.info(logger_data)

    _send_logger(message='start execute loan write off')
    url = form_data['url_field']
    if document_id:
        document = Document.objects.get_or_none(pk=document_id)
        if document:
            url = document.document_url

    if not url:
        _send_logger(message='data not provide', document=document_id, form_data=form_data)
        return

    reader = construct_channeling_url_reader(url)
    if reader.empty:
        _send_logger(
            message='data not provide',
            document=document_id,
            form_data=form_data,
            reader=reader,
            url=url,
        )
        return

    batches = reason.split('batch:')
    slack_messages = ""
    default_message = 'Write off Failed on row *{}* due to *{}* from *{}* \n'.format(
        '{}', '{}', batches[1]
    )
    batch_insert_loan_write_off = []
    batch_update_channeling_loan_write_off = []
    for idx, row in reader.iterrows():
        message = default_message.format(idx + 1, '{}')
        loan_xid = int(str(row['rek_loan'])[6:])
        if not loan_xid:
            slack_messages += message.format("loan_xid not provided")
            continue

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            slack_messages += message.format("loan_xid {} not found".format(loan_xid))
            continue

        channeling_loan_status = ChannelingLoanStatus.objects.filter(
            loan_id=loan.id,
            channeling_type=channeling_type,
            channeling_status=ChannelingStatusConst.SUCCESS,
        ).exists()

        if not channeling_loan_status:
            slack_messages += message.format(
                "Success channeling BSS with loan_id {} not found".format(loan.id)
            )
            continue

        channeling_write_off = ChannelingLoanWriteOff.objects.filter(loan_id=loan.id).last()
        if not channeling_write_off:
            batch_insert_loan_write_off.append(loan.id)
        elif not channeling_write_off.is_write_off:
            # use channeling_loan_write_off id instead loan_id
            batch_update_channeling_loan_write_off.append(channeling_write_off.id)

    for loan_ids in chunks(batch_insert_loan_write_off, 100):
        insert_loan_write_off.delay(loan_ids, channeling_type, document_id, reason, user_id)

    for channeling_loan_write_off_ids in chunks(batch_update_channeling_loan_write_off, 100):
        update_loan_write_off.delay(
            channeling_loan_write_off_ids, channeling_type, document_id, reason, user_id
        )

    if slack_messages:
        send_notification_to_slack(
            slack_messages, settings.LOAN_WRITE_OFF_FAILED_SLACK_NOTIFICATION_CHANNEL
        )

    return


@task(queue="channeling_loan_high")
def process_lender_switch_task(username, document_id, form_data, reason, channeling_type):
    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_lender_switch_task',
            'user': username,
            'reason': reason,
            **kwargs,
        }
        logger.info(logger_data)

    _send_logger(message='start execute lender switch')
    url = form_data['url_field']
    if document_id:
        document = Document.objects.get_or_none(pk=document_id)
        if document:
            url = document.document_url

    if not url:
        _send_logger(message='data not provide', document=document_id, form_data=form_data)
        return

    reader = construct_channeling_url_reader(url)
    if reader.empty:
        _send_logger(
            message='data not provide',
            document=document_id,
            form_data=form_data,
            reader=reader,
            url=url,
        )
        return

    batches = reason.split('batch:')
    slack_messages = ""
    default_message = 'Lender Switch Failed on row *{}* due to *{}* from *{}* \n'.format(
        '{}', '{}', batches[1]
    )
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    target_lender_name = (channeling_loan_config.get('general', {})).get('LENDER_NAME', None)
    for idx, row in reader.iterrows():
        message = default_message.format(idx + 1, '{}')
        loan_xid = int(str(row['Refno'])[6:])
        if not loan_xid:
            slack_messages += message.format("loan_xid not provided")
            continue

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            slack_messages += message.format("loan_xid {} not found".format(loan_xid))
            continue

        channeling_loan_status = ChannelingLoanStatus.objects.filter(
            channeling_type=channeling_type,
            channeling_status=ChannelingStatusConst.PROCESS,
            loan_id=loan.pk,
        ).last()
        if not channeling_loan_status:
            slack_messages += message.format(
                "{} channeling_loan_status {} not found or the status is not on PROCESS".format(
                    channeling_type, loan.pk
                )
            )
            continue

        status = str(row['Status'])
        if status.upper() == "OK":
            # switch to BSS
            update_loan_lender_task.delay(
                loan.pk, target_lender_name, "Lender switch", "approval", None, username
            )
            approve_loan_for_channeling(
                loan=loan,
                channeling_type=channeling_type,
                approval_status='y',
                channeling_loan_config=channeling_loan_config,
            )
        else:
            approve_loan_for_channeling(
                loan=loan,
                channeling_type=channeling_type,
                approval_status='n',
                channeling_loan_config=channeling_loan_config,
            )

    if slack_messages:
        send_notification_to_slack(slack_messages, settings.SYNC_FAILED_SLACK_NOTIFICATION_CHANNEL)

    return


@task(queue="channeling_loan_normal")
def check_disburse_transaction_task(loan_id, channeling_type, retry_count):
    if channeling_type != ChannelingConst.BSS:
        logger.info({
            'action': 'channeling_loan.tasks.check_disburse_transaction_task',
            'loan_id': loan_id,
            'channeling_type': channeling_type,
            'message': "only available for BSS",
        })
        return

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            'action': 'channeling_loan.tasks.check_disburse_transaction_task',
            'loan_id': loan_id,
            'channeling_type': channeling_type,
            'message': "Loan not found",
        })
        return

    status, message, retry_interval = check_disburse_transaction(loan, retry_count)
    logger.info({
        'action': 'check_disburse_transaction_task',
        'status': status,
        'message': message,
        'retry_interval': retry_interval,
    })
    if status == ChannelingStatusConst.SUCCESS:
        check_transfer_out_status_task.delay(loan_id, channeling_type, 1)

    if status == ChannelingStatusConst.RETRY:
        eta_time = timezone.localtime(timezone.now()) + timedelta(minutes=retry_interval)
        check_disburse_transaction_task.apply_async(
            (loan.id, channeling_type, retry_count + 1), eta=eta_time
        )


@task(queue="channeling_loan_normal")
def check_transfer_out_status_task(loan_id, channeling_type, retry_count):
    if channeling_type != ChannelingConst.BSS:
        logger.info({
            'action': 'channeling_loan.tasks.check_transfer_out_status_task',
            'loan_id': loan_id,
            'channeling_type': channeling_type,
            'message': "only available for BSS",
        })
        return

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info({
            'action': 'channeling_loan.tasks.check_transfer_out_status_task',
            'loan_id': loan_id,
            'channeling_type': channeling_type,
            'message': "Loan not found",
        })
        return

    status, message, retry_interval = check_transfer_out_status(loan, retry_count)
    logger.info({
        'action': 'check_transfer_out_status_task',
        'status': status,
        'message': message,
        'retry_interval': retry_interval,
    })
    if status == ChannelingStatusConst.FAILED:
        send_notification_to_slack(
            (
                "BSS Disbursement Transfer Out failed, please check detail below.\n"
                "BSS Refno : %s\n"
                "%s\n"
                "Please follow up to BSS Team. Thank you"
            )
            % (get_bss_refno(loan), message),
            settings.BSS_SLACK_NOTIFICATION_CHANNEL,
        )

    if status == ChannelingStatusConst.RETRY:
        eta_time = timezone.localtime(timezone.now()) + timedelta(minutes=retry_interval)
        check_transfer_out_status_task.apply_async(
            (loan.id, channeling_type, retry_count + 1), eta=eta_time
        )


@task(queue="loan_low")
def reconciliation_channeling_loan_task():
    from juloserver.channeling_loan.services.views_services import construct_fama_reconciliation

    construct_fama_reconciliation(current_ts=timezone.localtime(timezone.now()) - timedelta(days=1))


@task(queue="channeling_loan_high")
def populate_fama_loan_after_cutoff():
    logger.info(
        {
            "action": "populate_fama_loan_after_cutoff",
            "message": "Start populating FAMA loans",
        }
    )
    # avoid circular import since view service also calling tasks.
    from juloserver.channeling_loan.services.views_services import (
        update_admin_fee_fama,
        construct_fama_response,
    )

    channeling_type = ChannelingConst.FAMA
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    if not channeling_loan_config:
        return

    cutoff_config = channeling_loan_config['cutoff']
    current_ts = timezone.localtime(timezone.now())
    cutoff_ts = current_ts.replace(**cutoff_config["CUTOFF_TIME"])

    # calculate cutoff time
    if not cutoff_config['is_active']:
        return

    if not cutoff_config['CHANNEL_AFTER_CUTOFF']:
        return

    day_name = current_ts.strftime("%A")
    if day_name in cutoff_config["INACTIVE_DAY"]:
        return

    if current_ts.date() in (
        datetime.strptime(x, '%Y/%m/%d').date() for x in cutoff_config['INACTIVE_DATE']
    ):
        return

    # recalculate only previous day loan, for today loan can use as it is
    processed_channeling_loan_statuses = ChannelingLoanStatus.objects.filter(
        channeling_type=channeling_type,
        cdate__lte=cutoff_ts,
        cdate__gte=current_ts.date() - timedelta(days=1),
        channeling_status=ChannelingStatusConst.PENDING,
    )

    if processed_channeling_loan_statuses:
        update_admin_fee_fama(
            processed_channeling_loan_statuses, current_ts, channeling_loan_config
        )
        logger.info(
            {
                "action": "populate_fama_loan_after_cutoff",
                "total": len(processed_channeling_loan_statuses),
                "message": "Update admin fee done",
            }
        )

    # send all PENDING data before cutoff
    _filter = {
        "channeling_type": channeling_type,
        "channeling_eligibility_status__channeling_type": channeling_type,
        "channeling_eligibility_status__eligibility_status": ChannelingStatusConst.ELIGIBLE,
        "channeling_status": ChannelingStatusConst.PENDING,
        "cdate__lte": cutoff_ts,
        "cdate__gte": current_ts.date() - timedelta(days=1),
    }

    # send fama data
    construct_fama_response(current_ts, _filter, None, True)
    logger.info(
        {
            "action": "populate_fama_loan_after_cutoff",
            "message": "Populate FAMA loans done",
        }
    )


@task(queue="channeling_loan_high")
def construct_fama_response_tasks(current_ts, _filter, user_id, upload):
    # avoid circular import since view service also calling tasks.
    from juloserver.channeling_loan.services.views_services import (
        construct_fama_response,
    )

    construct_fama_response(current_ts, _filter, user_id, upload)


@task(queue="loan_low")
def process_channeling_repayment_task(payment_event_ids):
    """insert data to channeling_payment_event on payment event made"""
    logger.info(
        {
            'method': 'process_channeling_repayment_task',
            'message': 'function executed',
            'payment_event_ids': payment_event_ids,
        }
    )
    if not payment_event_ids:
        logger.info(
            {
                'method': 'process_channeling_repayment_task',
                'message': 'payment_event_ids not found',
                'payment_event_ids': payment_event_ids,
            }
        )
        return

    all_channeling_configuration = get_channeling_loan_configuration()
    if not all_channeling_configuration:
        logger.info(
            {
                'method': 'process_channeling_repayment_task',
                'message': 'channeling config not found',
                'payment_event_ids': payment_event_ids,
            }
        )
        return

    lender_names = {}
    for channeling_type, channeling_loan_config in all_channeling_configuration.items():
        lender_name = (channeling_loan_config.get('general', {})).get('LENDER_NAME', None)
        if lender_name:
            lender_names[lender_name] = channeling_type
    if not lender_names:
        logger.info(
            {
                'method': 'process_channeling_repayment_task',
                'message': 'channeling_lenders not found',
                'payment_event_ids': payment_event_ids,
            }
        )
        return

    channeling_payment_events = []
    updated_channeling_loan_payments = []
    installment_types = ('interest', 'principal')

    """
    this query below and channeling type filter will validate duplicate channeling loan payment

    e.g.: user created two loan in a day and both of them channeled to FAMA, but one was rejected
    channeling loan status for FAMA loan became stuck in process
    afterwards, it was manually switched and channeled to another lender
    this will create new channeling loan payment and channeling loan status
    """
    payment_events = (
        PaymentEvent.objects.prefetch_related(
            'payment__channelingloanpayment_set', 'payment__channelingpaymentevent_set'
        )
        .select_related('payment__loan__lender')
        .filter(
            id__in=payment_event_ids,
            payment__loan__lender__lender_name__in=list(lender_names.keys()),
            channelingpaymentevent__isnull=True,
        )
    )

    for payment_event in payment_events:
        payment = payment_event.payment
        lender_name = payment.loan.lender.lender_name

        if lender_name not in lender_names:
            logger.info(
                {
                    'method': 'process_channeling_repayment_task',
                    'message': 'invalid lender_name',
                    'lender_name': lender_name,
                    'expected_lender_names': str(list(lender_names.keys())),
                }
            )
            continue

        channeling_type = lender_names.get(lender_name)
        channeling_payment = payment.channelingloanpayment_set.filter(
            channeling_type=channeling_type
        ).last()

        if not channeling_payment:
            logger.info(
                {
                    'method': 'process_channeling_repayment_task',
                    'message': 'channeling loan payment not found',
                    'loan_id': payment.loan.id,
                    'payment_event_id': payment_event.id,
                }
            )
            continue

        installments = {
            "interest": channeling_payment.interest_amount,
            "principal": channeling_payment.principal_amount,
            "due_amount": channeling_payment.interest_amount + channeling_payment.principal_amount,
        }

        channeling_payment_event = payment.channelingpaymentevent_set.last()
        if channeling_payment_event:
            installments = {
                "interest": channeling_payment_event.outstanding_interest,
                "principal": channeling_payment_event.outstanding_principal,
                "due_amount": channeling_payment_event.outstanding_amount,
            }

        event_payment = payment_event.event_payment
        data = {'total': 0, 'due_amount': installments['due_amount']}
        for installment_type in installment_types:
            if installment_type not in data:
                data[installment_type] = 0
            if event_payment > 0 and installments[installment_type] > 0:
                if installments[installment_type] <= event_payment:
                    data[installment_type] = installments[installment_type]
                    event_payment -= installments[installment_type]
                else:
                    data[installment_type] = event_payment
                    event_payment = 0
                data['total'] += data[installment_type]

        paid_interest = data['interest']
        paid_principal = data['principal']
        total = data['total']
        outstanding_amount = installments['due_amount'] - data['total']
        outstanding_principal = installments['principal'] - data['principal']
        outstanding_interest = installments['interest'] - data['interest']
        if (
            payment.due_amount == 0
            and channeling_payment.channeling_type == ChannelingConst.PERMATA
        ):
            # force all channelingloanpayment is paid when user paid all loan
            paid_interest = installments['interest']
            paid_principal = installments['principal']
            total = installments['due_amount']
            outstanding_amount = 0
            outstanding_principal = 0
            outstanding_interest = 0

        adjusted_principal = 0
        adjusted_interest = 0
        last_payment_event = payment.paymentevent_set.last()
        if (
            payment_event == last_payment_event
            and payment.status >= PaymentStatusCodes.PAID_ON_TIME
            and payment.paid_amount < channeling_payment.due_amount
        ):
            adjusted_principal = outstanding_principal
            adjusted_interest = outstanding_interest
            outstanding_amount = 0
            outstanding_principal = 0
            outstanding_interest = 0

        channeling_payment_events.append(
            ChannelingPaymentEvent(
                payment_event=payment_event,
                payment=payment,
                installment_amount=installments['due_amount'],
                payment_amount=total,
                paid_interest=paid_interest,
                paid_principal=paid_principal,
                outstanding_amount=outstanding_amount,
                outstanding_principal=outstanding_principal,
                outstanding_interest=outstanding_interest,
                adjusted_principal=adjusted_principal,
                adjusted_interest=adjusted_interest,
            )
        )

        channeling_payment.udate = timezone.localtime(timezone.now())
        channeling_payment.paid_interest += paid_interest
        channeling_payment.paid_principal += paid_principal
        # due_amount is reduced by the total amount paid in this payment event
        channeling_payment.due_amount -= total
        updated_channeling_loan_payments.append(channeling_payment)

    ChannelingPaymentEvent.objects.bulk_create(channeling_payment_events)

    if updated_channeling_loan_payments:
        bulk_update(
            updated_channeling_loan_payments,
            update_fields=['udate', 'paid_interest', 'paid_principal', 'due_amount'],
        )

    return True


@task(queue="loan_low")
def process_upload_loan_write_off_file(
    username, form_data, reason, document_id, file_path, channeling_type, user_id=None
):
    from juloserver.julo.tasks import upload_document

    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_upload_loan_write_off_file',
            'user': username,
            'reason': reason,
            'document_id': document_id,
            'file_path': file_path,
            'form_data': form_data,
            **kwargs,
        }
        logger.info(logger_data)

    upload_document(document_id, file_path, is_write_off=True)
    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        _send_logger(message='document not found')
        return

    if not document.document_url:
        _send_logger(message='document_url not found')
        return

    process_loan_write_off_task.delay(
        username, document_id, form_data, reason, channeling_type, user_id
    )


@task(queue="channeling_loan_high")
def process_upload_lender_switch_file(
    username, form_data, reason, document_id, file_path, channeling_type
):
    from juloserver.julo.tasks import upload_document

    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_upload_lender_switch_file',
            'user': username,
            'reason': reason,
            'document_id': document_id,
            'file_path': file_path,
            'form_data': form_data,
            **kwargs,
        }
        logger.info(logger_data)

    upload_document(document_id, file_path, is_channeling=True)
    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        _send_logger(message='document not found')
        return

    if not document.document_url:
        _send_logger(message='document_url not found')
        return

    process_lender_switch_task.delay(username, document_id, form_data, reason, channeling_type)


@task(queue="loan_low")
def execute_repayment_process(lender_osp_account, balance_amount):
    execute_repayment_process_service(lender_osp_account.id, balance_amount)


@task(queue="loan_low")
def execute_withdraw_batch_process(lender_osp_account_id):
    # create the lender osp transaction, and find tagged loan
    try:
        with transaction.atomic():
            lender_osp_account = LenderOspAccount.objects.get_or_none(
                pk=lender_osp_account_id
            )
            if not lender_osp_account:
                raise Exception('lender_osp_account with id {} not found'.format(
                    lender_osp_account_id
                ))

            tagged_loan, total_loan_lender, total_loan_julo = loan_tagging_process(
                lender_osp_account_id
            )
            if not tagged_loan:
                logger.error(
                    {
                        "action": "juloserver.channeling_loan.tasks.execute_withdraw_batch_process",
                        "lender_osp_account_id": lender_osp_account_id,
                        "message": "Lender withdraw batch already fulfilled",
                    }
                )
                return

            lenderloanledgers = []
            total_tagged_loan = 0
            for loan_id, loan in tagged_loan.items():
                lenderloanledgers.append(
                    LenderLoanLedger(
                        lender_osp_account_id=lender_osp_account_id,
                        application_id=loan["application_id"],
                        loan_xid=loan["loan_xid"],
                        loan_id=loan_id,
                        osp_amount=loan["amount"],
                        tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
                        notes=loan["notes"],
                        is_fund_by_julo=loan["is_fund_by_julo"],
                    )
                )
                total_tagged_loan += loan["amount"]

            # insert loan tagging
            LenderLoanLedger.objects.bulk_create(
                lenderloanledgers,
                batch_size=ChannelingLenderLoanLedgerConst.BATCH_SIZE
            )

            # Update history
            update_lender_osp_balance(
                lender_osp_account,
                lender_osp_account.balance_amount,
                lender_osp_account.fund_by_lender + total_loan_lender,
                lender_osp_account.fund_by_julo + total_loan_julo,
                reason='initial_tag',
            )

            # update balance
            total_loan = total_loan_lender + total_loan_julo
            lender_osp_account.update_safely(
                fund_by_lender=lender_osp_account.fund_by_lender + total_loan_lender,
                fund_by_julo=lender_osp_account.fund_by_julo + total_loan_julo,
                total_outstanding_principal=(
                    lender_osp_account.total_outstanding_principal + total_loan
                )
            )

        _, need_to_fund_lender, need_to_fund_julo = get_outstanding_withdraw_amount(
            lender_osp_account
        )
        if need_to_fund_lender > 0 or need_to_fund_julo > 0:
            logger.info(
                {
                    "action": "juloserver.channeling_loan.tasks.execute_withdraw_batch_process",
                    "lender_osp_account": lender_osp_account_id,
                    "message": "process completed, withdraw batch {} still not fulfiled".format(
                        lender_osp_account
                    ),
                }
            )
    except Exception as error:
        logger.error(
            {
                "action": "juloserver.channeling_loan.tasks.execute_withdraw_batch_process",
                "lender_osp_account": lender_osp_account_id,
                "message": str(error),
            }
        )

    return True


@task(queue="channeling_loan_normal")
def process_upload_ar_switching_file(username, form_data, reason, document_id, file_path):
    from juloserver.julo.tasks import upload_document

    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_upload_ar_switching_file',
            'user': username,
            'reason': reason,
            'document_id': document_id,
            'file_path': file_path,
            'form_data': form_data,
            **kwargs,
        }
        logger.info(logger_data)

    upload_document(document_id, file_path, is_switching=True)
    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        _send_logger(message='document not found')
        return

    if not document.document_url:
        _send_logger(message='document_url not found')
        return

    process_ar_switching_task.delay(username, document_id, form_data, reason)


@task(queue="loan_low")
def daily_checker_loan_tagging_task():
    # release paid off and replenish loan
    try:
        daily_checker_loan_tagging()
    except Exception as error:
        logger.error({
            "action": "juloserver.channeling_loan.tasks.daily_checker_loan_tagging_task",
            "message": str(error),
        })


@task(queue="loan_low")
def daily_checker_loan_tagging_clone_task():
    # clone table and release dpd 90
    try:
        daily_checker_loan_tagging_clone_table()
    except Exception as error:
        logger.error({
            "action": "juloserver.channeling_loan.tasks.daily_checker_loan_tagging_clone_task",
            "message": str(error),
        })


@task(queue="loan_low")
def release_loan_tagging_dpd_90_task():
    release_loan_tagging_dpd_90()


@task(queue="loan_low")
def execute_replenishment_loan_payment_by_user_process_task():
    execute_replenishment_loan_payment_by_user_process()


@task(queue="loan_low")
def execute_replenishment_matchmaking_task():
    execute_replenishment_matchmaking()


@task(queue="loan_low")
def execute_clone_ana_table():
    clone_ana_table()


@task(queue="loan_low")
def execute_delete_temporary_dpd_table():
    delete_temporary_dpd_table()


@task(queue="channeling_loan_normal")
def manual_hit_channeling_loan(loan_id):
    from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement

    log_data = {
        'action': 'channeling_loan.tasks.manual_hit_channeling_loan',
        'loan_id': loan_id,
    }
    loan = Loan.objects.get(pk=loan_id)
    if not loan:
        log_data['reason'] = 'loan not found'
        logger.info(log_data)
        return

    account = loan.account
    if not account:
        log_data['reason'] = 'account not found'
        logger.info(log_data)
        return

    application = account.get_active_application()
    if not application:
        log_data['reason'] = 'application not found'
        logger.info(log_data)
        return

    if not application.channelingloanaddress_set.exists():
        result, _ = retroload_address(
            limit=1, batch_size=25, query_filter={'id': application.id}, key="manual-BSS"
        )

        if result.get('400', 0) or result.get('404', 0):
            log_data['reason'] = 'skip value'
            log_data['result'] = result
            return

    if loan.payment_set.filter(paid_amount__gt=0).exists():
        log_data['reason'] = 'has paid payment'
        logger.info(log_data)
        return

    now = timezone.localtime(timezone.now())
    sphp_sent_ts = loan.sphp_sent_ts
    fund_transfer_ts = loan.fund_transfer_ts
    last_education = application.last_education

    loan.update_safely(sphp_sent_ts=now, fund_transfer_ts=now)
    application.update_safely(last_education='Diploma')

    log_data['reason'] = (sphp_sent_ts, loan.sphp_sent_ts, fund_transfer_ts, last_education)
    logger.info(log_data)

    # delete channeling payments
    payments = loan.payment_set.order_by('payment_number')
    ChannelingLoanPayment.objects.filter(payment__in=payments, channeling_type='BSS').delete()

    send_loan_for_channeling_task(loan_id)

    # generate document
    channeling_loan_status = (
        ChannelingLoanStatus.objects.filter(loan_id=loan_id)
        .values('id', 'cdate', 'loan_id', 'channeling_status', 'reason')
        .last()
    )
    log_data['reason'] = channeling_loan_status
    logger.info(log_data)
    if channeling_loan_status['reason'] == 'Success from partner':
        generate_julo_one_loan_agreement(loan.id, is_new_generate=True)

    # Update the old values
    loan.update_safely(sphp_sent_ts=sphp_sent_ts, fund_transfer_ts=fund_transfer_ts)
    application.update_safely(last_education=last_education)

    log_data['reason'] = (
        loan.sphp_sent_ts,
        loan.fund_transfer_ts,
    )
    logger.info(log_data)

    return


@task(queue="channeling_loan_high")
def encrypt_data_and_upload_to_fama_sftp_server(content: str, filename: str) -> None:
    return encrypt_data_and_upload_to_sftp_server(
        gpg_recipient=settings.FAMA_GPG_ENCRYPT_RECIPIENT,
        gpg_key_data=settings.FAMA_GPG_ENCRYPT_KEY_DATA,
        sftp_client=get_fama_sftp_client(),
        content=content,
        filename=filename,
    )


@task(queue="channeling_loan_high")
def encrypt_data_and_upload_to_permata_sftp_server(content: str, filename: str) -> None:
    return encrypt_data_and_upload_to_sftp_server(
        gpg_recipient=settings.PERMATA_GPG_ENCRYPT_RECIPIENT,
        gpg_key_data=settings.PERMATA_GPG_ENCRYPT_KEY_DATA,
        sftp_client=get_permata_sftp_client(),
        content=content,
        filename="{}/{}".format(settings.PERMATA_SFTP_UPLOAD_DIRECTORY, filename),
    )


@task(queue="channeling_loan_high")
def encrypt_data_and_upload_to_dbs_sftp_server(content: str, filename: str) -> None:
    return encrypt_data_and_upload_to_sftp_server(
        gpg_recipient=settings.DBS_GPG_ENCRYPT_RECIPIENT,
        gpg_key_data=settings.DBS_GPG_ENCRYPT_KEY_DATA,
        sftp_client=get_dbs_sftp_client(),
        content=content,
        filename=filename,
    )


@task(queue="channeling_loan_normal")
def regenerate_summary_and_skrtp_agreement_for_ar_switching(loan_id: int) -> None:
    from juloserver.followthemoney.tasks import (
        assign_lenderbucket_xid_to_lendersignature,
        generate_summary_lender_loan_agreement,
        generate_julo_one_loan_agreement,
    )

    if is_block_regenerate_document_ars_config_active():
        logger.info(
            {
                'action_view': 'juloserver.channeling_loan.tasks.'
                'regenerate_summary_and_skrtp_agreement_for_ar_switching',
                'data': {'loan_id': loan_id},
                'message': "blocked from regenerate document due to ar switching",
            }
        )
        return

    loan = Loan.objects.get(pk=loan_id)

    # Generate new P3PTI
    lender_bucket = LenderBucket.objects.create(
        partner_id=loan.lender.user.partner.pk,
        total_approved=1,
        total_rejected=0,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids={"approved": [loan.id], "rejected": []},
        is_disbursed=True,
        is_active=True,
        action_time=timezone.localtime(timezone.now()),
        action_name='Disbursed',
    )
    assign_lenderbucket_xid_to_lendersignature(
        [loan.id], lender_bucket.lender_bucket_xid, is_loan=True
    )

    # P3PTI document
    execute_after_transaction_safely(
        lambda: generate_summary_lender_loan_agreement.apply_async(
            kwargs={
                'lender_bucket_id': lender_bucket.id,
                'is_new_generate': True,
                'is_for_ar_switching': True,
            },
            queue='channeling_loan_low',
        )
    )

    # Generate new SKRTP
    execute_after_transaction_safely(
        lambda: generate_julo_one_loan_agreement.apply_async(
            kwargs={
                'loan_id': loan.id,
                'is_new_generate': True,
                'is_for_ar_switching': True,
            },
            queue='channeling_loan_low',
        )
    )


@task(queue="channeling_loan_high")
def send_loan_prefund_flow_task(loan_id):
    return_value = False
    loan = Loan.objects.get_or_none(pk=loan_id)

    if (
        loan.loan_status.status_code == LoanStatusCodes.CURRENT
        and not loan.lender.is_pre_fund_channeling_flow
    ):
        logger.info(
            {
                'action': 'channeling_loan.tasks.send_loan_prefund_flow_task',
                'loan_id': loan_id,
                'message': "prevent double hit",
            }
        )
        return return_value

    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.PREFUND)
    if not channeling_loan_status:
        logger.info(
            {
                'action': 'channeling_loan.tasks.send_loan_prefund_flow_task',
                'loan_id': loan_id,
                'message': "no prefund status found",
            }
        )
        return return_value

    channeling_type = channeling_loan_status.channeling_type
    new_interests = recalculate_channeling_payment_interest(loan, channeling_type, None)
    if not new_interests:
        message = "cannot generate new interest"
        logger.info(
            {
                'action': 'channeling_loan.tasks.send_loan_prefund_flow_task',
                'loan_id': loan_id,
                'channeling_type': channeling_type,
                'message': message,
            }
        )
        update_channeling_loan_status(
            channeling_loan_status_id=channeling_loan_status.id,
            new_status=ChannelingStatusConst.FAILED,
            change_reason=message,
        )
        return return_value

    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    admin_fee = channeling_loan_status.admin_fee
    if channeling_type == ChannelingConst.FAMA:
        # update admin fee here if fama only
        admin_fee = get_fama_channeling_admin_fee(channeling_loan_status, channeling_loan_config)

    channeling_loan_status.update_safely(
        channeling_interest_amount=sum(new_interests.values()),
        admin_fee=admin_fee
    )
    update_channeling_loan_status(
        channeling_loan_status_id=channeling_loan_status.id,
        new_status=ChannelingStatusConst.PENDING,
    )

    if channeling_type == ChannelingConst.SMF:
        channeling_loan_type = channeling_loan_config.get('general', {}).get(
            'CHANNELING_TYPE', ''
        )
        if channeling_loan_type == ChannelingConst.MANUAL_CHANNELING_TYPE:
            generate_smf_receipt_and_invoice_task.delay(loan_id)
        elif channeling_loan_type == ChannelingConst.API_CHANNELING_TYPE:
            send_loan_for_channeling_to_smf_task.delay(loan_id)

    return True


@task(queue="loan_low")
def cancel_loan_prefund_flow_task(loan_id):
    return_value = False
    loan = Loan.objects.get_or_none(pk=loan_id)
    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.PREFUND)
    if not channeling_loan_status:
        logger.info(
            {
                'action': 'channeling_loan.tasks.cancel_loan_prefund_flow_task',
                'loan_id': loan_id,
                'message': "no prefund status found",
            }
        )
        return return_value

    update_channeling_loan_status(
        channeling_loan_status_id=channeling_loan_status.id,
        new_status=ChannelingStatusConst.FAILED,
        change_reason="Canceled loan",
    )
    return True


@task(queue="channeling_loan_high")
def process_fama_approval_response(
    file_type: str, approval_file_id: int, retry_time: int = 0
) -> None:
    from juloserver.channeling_loan.services.fama_services import FAMARepaymentApprovalServices

    encrypted_filename, encrypted_data = download_latest_fama_approval_file_from_sftp_server(
        file_type=file_type
    )
    # check no file found
    if encrypted_filename is None:
        return mark_approval_file_processed(approval_file_id=approval_file_id)

    txt_content = decrypt_data(
        filename=encrypted_filename,
        content=encrypted_data,
        passphrase=settings.FAMA_GPG_DECRYPT_PASSPHRASE,
        gpg_recipient=settings.FAMA_GPG_DECRYPT_RECIPIENT,
        gpg_key_data=settings.FAMA_GPG_DECRYPT_KEY_DATA,
    )
    # check if decryption failed
    if txt_content is None:
        return mark_approval_file_processed(approval_file_id=approval_file_id)

    filename = replace_gpg_encrypted_file_name(encrypted_file_name=encrypted_filename)
    content = txt_content
    if file_type == ChannelingActionTypeConst.DISBURSEMENT:
        filename = replace_gpg_encrypted_file_name(
            encrypted_file_name=encrypted_filename, new_file_extension='csv'
        )
        content = convert_fama_approval_content_from_txt_to_csv(content=txt_content)
    elif file_type == ChannelingActionTypeConst.REPAYMENT:
        is_success = FAMARepaymentApprovalServices().store_data_and_notify_slack(
            approval_file_id=approval_file_id, filename=filename, txt_content=txt_content
        )
        if not is_success:
            if retry_time < FAMAChannelingConst.MAX_GET_NEW_REPAYMENT_APPROVAL_TIMES:
                process_fama_approval_response.apply_async(
                    kwargs={
                        'file_type': ChannelingActionTypeConst.REPAYMENT,
                        'approval_file_id': approval_file_id,
                        'retry_time': retry_time + 1,
                    },
                    countdown=FAMAChannelingConst.COUNTDOWN_RETRY_IN_SECONDS,
                )
            else:
                FAMARepaymentApprovalServices.send_exceed_max_retry_slack_notification()

    document_id = upload_approval_file_to_oss_and_create_document(
        channeling_type=ChannelingConst.FAMA,
        file_type=file_type,
        filename=filename,
        approval_file_id=approval_file_id,
        content=content,
    )

    return mark_approval_file_processed(approval_file_id=approval_file_id, document_id=document_id)


@task(queue="channeling_loan_high")
def process_dbs_approval_response(file_type: str, approval_file_id: int):

    encrypted_filename, encrypted_data = download_latest_file_from_sftp_server(
        sftp_client=get_dbs_sftp_client(),
        remote_path=DBSChannelingConst.APPROVAL_REMOTE_PATH_PER_FILE_TYPE.get(file_type),
    )

    # check no file found
    if encrypted_filename is None:
        return mark_approval_file_processed(approval_file_id=approval_file_id)

    txt_content = decrypt_data(
        filename=encrypted_filename,
        content=encrypted_data,
        passphrase=settings.DBS_GPG_DECRYPT_PASSPHRASE,
        gpg_recipient=settings.DBS_GPG_DECRYPT_RECIPIENT,
        gpg_key_data=settings.DBS_GPG_DECRYPT_KEY_DATA,
    )

    # check if decryption failed
    if txt_content is None:
        return mark_approval_file_processed(approval_file_id=approval_file_id)

    if file_type == ChannelingActionTypeConst.DISBURSEMENT:
        filename = replace_gpg_encrypted_file_name(
            encrypted_file_name=encrypted_filename, new_file_extension='csv'
        )
        content = convert_dbs_approval_content_from_txt_to_csv(content=txt_content)
    else:
        filename = replace_gpg_encrypted_file_name(encrypted_file_name=encrypted_filename)
        content = txt_content

    document_id = upload_approval_file_to_oss_and_create_document(
        channeling_type=ChannelingConst.DBS,
        file_type=file_type,
        filename=filename,
        approval_file_id=approval_file_id,
        content=content,
    )

    return mark_approval_file_processed(approval_file_id=approval_file_id, document_id=document_id)


@task(queue="channeling_loan_high")
def fama_auto_approval_loans(retry_counter=0, encrypted_filenames=None):
    action = "channeling_loan.tasks.fama_auto_approval_loans"
    current_date = timezone.localtime(timezone.now()).date().strftime("%Y%m%d")
    lender = LenderCurrent.objects.get_or_none(lender_name=ChannelingConst.LENDER_FAMA)

    base_logger_data = {
        "action": action,
        "current_date": current_date,
        "lender": lender,
        "retry_counter": retry_counter,
    }

    logger.info({**base_logger_data, "message": "Start FAMA auto approval"})

    results, results_msg, processed_encrypted_filenames = [], [], []

    disbursement_request_docs_count = Document.objects.filter(
        filename__icontains=current_date,
        document_type=ChannelingLoanApprovalFileConst.DOCUMENT_TYPE,
        document_source=lender.id,
    ).count()

    approval_files = FAMAApprovalFileServices().download_multi_fama_approval_file_from_sftp_server(
        file_type=ChannelingActionTypeConst.DISBURSEMENT,
        number_of_latest_file=disbursement_request_docs_count,
    )

    today_approval_file_count = 0
    for encrypted_filename, encrypted_data in approval_files:
        if not encrypted_filename:
            logger.error(
                {
                    **base_logger_data,
                    "message": "encrypted_filename is empty",
                }
            )

            return

        if encrypted_filenames and encrypted_filename in encrypted_filenames:
            continue

        if current_date not in encrypted_filename:
            continue

        today_approval_file_count += 1

    if today_approval_file_count > 0:
        (
            results,
            results_msg,
            processed_encrypted_filenames,
        ) = FAMAApprovalFileServices().execute_upload_fama_disbursement_approval_files(
            today_approval_file_count
        )

    if retry_counter == FAMAAutoApprovalConst.MAX_RETRY:
        logger.info(
            {
                **base_logger_data,
                "message": "reached max retry",
            }
        )
        send_notification_to_slack(
            "{} FAMA approval files still incomplete, please check and do manual approval".format(
                current_date
            ),
            settings.FAMA_SLACK_NOTIFICATION_CHANNEL,
        )
        return

    processed_encrypted_filenames_count = 0
    if encrypted_filenames:
        processed_encrypted_filenames_count = len(encrypted_filenames)

    if (
        today_approval_file_count
        != disbursement_request_docs_count - processed_encrypted_filenames_count
    ):
        retry_counter += 1

        logger.info(
            {
                **base_logger_data,
                "message": str(retry_counter) + " retry due to incomplete approval files",
            }
        )

        fama_auto_approval_loans.apply_async(
            (
                retry_counter,
                processed_encrypted_filenames,
            ),
            countdown=60 * 60,
        )

    if results:
        reassign_lender_fama_rejected_loans(results)

    if results_msg:
        send_notification_to_slack(
            "```%s```" % json.dumps(results_msg, indent=2),
            settings.FAMA_SLACK_NOTIFICATION_CHANNEL,
        )

    logger.info({**base_logger_data, "results": results, "message": "Finish FAMA auto approval"})


@task(queue="channeling_loan_high")
def process_permata_approval_response(file_type: str, approval_file_id: int):
    from juloserver.channeling_loan.services.permata_services import (
        construct_permata_disbursement_approval_file,
        construct_permata_single_approval_file,
    )

    filename = None
    content = None

    if file_type == PermataChannelingConst.FILE_TYPE_DISBURSEMENT:
        filename, content = construct_permata_disbursement_approval_file()
    elif file_type == PermataChannelingConst.FILE_TYPE_REPAYMENT:
        filename, content = construct_permata_single_approval_file(
            filename_prefix=PermataChannelingConst.REPAYMENT_FILENAME_PREFIX,
        )
    elif file_type == PermataChannelingConst.FILE_TYPE_EARLY_PAYOFF:
        filename, content = construct_permata_single_approval_file(
            filename_prefix=PermataChannelingConst.EARLY_PAYOFF_FILENAME_PREFIX,
        )

    if filename is None:
        return mark_approval_file_processed(approval_file_id=approval_file_id)

    document_id = upload_approval_file_to_oss_and_create_document(
        channeling_type=ChannelingConst.PERMATA,
        file_type=file_type,
        filename=filename,
        approval_file_id=approval_file_id,
        content=content,
    )

    return mark_approval_file_processed(approval_file_id=approval_file_id, document_id=document_id)


@task(queue="channeling_loan_high")
def process_upload_smf_disbursement_file_task(_filter, document_id, user_id):
    from juloserver.julo.tasks import upload_document

    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_upload_smf_disbursement_file_task',
            'user': user_id,
            'document_id': document_id,
            'filter': _filter,
            **kwargs
        }
        logger.info(logger_data)

    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        _send_logger(message='document not found')
        return

    file_path, loan_ids = generate_smf_disbursement_file(
        document.filename, _filter
    )
    upload_document(document.id, file_path, is_channeling=True)
    document.refresh_from_db()

    if not document.document_url:
        _send_logger(message='document_url not found')
        return

    send_notification_to_slack(
        (
            "Here's your SMF disbursement link file\n %s \nthis link expiry time only 2 minutes.\n"
            "if the link is already expired, please ask engineer to manually "
            "download it with document_id %s"
        )
        % (document.document_url, document.id),
        settings.SMF_SLACK_NOTIFICATION_CHANNEL,
    )
    zip_file = Document.objects.create(
        document_source=user_id,
        document_type="smf_zip",
        filename=document.filename.replace('.xls', '.zip'),
    )
    process_upload_smf_zip_file_task.delay(loan_ids, zip_file.id, user_id)


@task(queue="channeling_loan_high")
def process_upload_smf_zip_file_task(loan_ids, document_id, user_id):
    from juloserver.julo.tasks import upload_document

    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.tasks.process_upload_smf_zip_file_task',
            'user': user_id,
            'document_id': document_id,
            'loan_ids': loan_ids,
        }
        logger.info(logger_data)

    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        _send_logger(message='document not found')
        return

    file_path = generate_smf_zip_file(document.filename, loan_ids)
    upload_document(document.id, file_path, is_channeling=True)
    document.refresh_from_db()

    if not document.document_url:
        _send_logger(message='document_url not found')
        return

    send_notification_to_slack(
        (
            "Here's your SMF zip link file\n %s \nthis link expiry time only 2 minutes.\n"
            "if the link is already expired, please ask engineer to manually "
            "download it with document_id %s"
        )
        % (document.document_url, document.id),
        settings.SMF_SLACK_NOTIFICATION_CHANNEL,
    )


@task(queue="channeling_loan_high")
def generate_smf_receipt_and_invoice_task(loan_id):
    from juloserver.julo.tasks import upload_document

    loan = Loan.objects.get_or_none(
        pk=loan_id, lender__lender_name=SMFChannelingConst.LENDER_NAME,
    )
    if not loan:
        logger.info(
            {
                "task": "channeling_loan.tasks.generate_smf_receipt_and_invoice_task",
                "respon_data": "loan not found with related ID",
                "loan_id": loan_id
            }
        )
        return

    for document_type in ['invoice', 'receipt']:
        exist_doc = Document.objects.filter(
            document_source=loan.id,
            document_type='smf_%s' % (document_type)
        ).exists()
        if not exist_doc:
            document_id, local_path = generate_smf_receipt_and_invoice(loan, document_type)
            upload_document(document_id, local_path, is_channeling=True)


@task(queue="loan_low")
def approve_loan_for_channeling_task(
    loan_id: int,
    channeling_type: str,
    approval_status: str,
    channeling_loan_config: Dict[str, Any] = None,
):
    approve_loan_for_channeling(
        loan=Loan.objects.filter(pk=loan_id).last(),  # handle loan not found inside the function
        channeling_type=channeling_type,
        approval_status=approval_status,
        channeling_loan_config=channeling_loan_config,
    )


@task(queue="loan_low")
def send_loan_for_channeling_to_bni_task() -> None:
    return BNIDisbursementServices().send_loan_for_channeling_to_bni()


@task(queue="loan_low")
def send_recap_loan_for_channeling_to_bni_task() -> None:
    return BNIDisbursementServices().send_recap_loan_for_channeling_to_bni()


@task(queue="channeling_loan_high")
def construct_bss_response_tasks(current_ts, _filter, user_id):
    from juloserver.channeling_loan.services.views_services import (
        construct_bss_response,
    )

    logger.info(
        {
            'action': 'channeling_loan.tasks.construct_bss_response_tasks',
            'message': 'start construct_bss_response | user_id :{}'.format(user_id),
        }
    )
    construct_bss_response(current_ts, _filter, user_id)


@task(queue="channeling_loan_high")
def proceed_sync_channeling(url, file, channeling_type):
    field1 = "Application_XID"
    field2 = "disetujui"
    field3 = "reason"
    if url:
        reader = construct_channeling_url_reader(url)
        if reader.empty:
            return
        data = reader.iterrows()
    if file:
        try:
            excel_datas = xls_to_dict(file)
            data = enumerate(excel_datas["csv"])
            field1 = field1.lower()
        except Exception as error:
            logger.info(
                {
                    'action': 'channeling_loan.tasks.proceed_sync_channeling',
                    'file': file.name,
                    'message': error,
                }
            )
            return error
    nok_counter = 0
    ok_counter = 0
    logs = ''
    for idx, row in data:
        for field in [field1, field2]:
            if field not in row:
                nok_counter += 1
                logs += "nok"
        loan_xid = row[field1]
        approved = row[field2]
        reason = row.get(field3, "")

        error = check_loan_and_approve_channeling(loan_xid, approved, channeling_type, reason)
        if error:
            nok_counter += 1
            logs += error
            continue
        ok_counter += 1
    if nok_counter:
        logger.info(
            {
                'action': 'channeling_loan.tasks.proceed_sync_channeling',
                'message': "have errors, sending the list to the Slack channel : {}".format(
                    settings.SYNC_FAILED_SLACK_NOTIFICATION_CHANNEL
                ),
                'channeling_type': channeling_type,
            }
        )
        send_notification_to_slack(logs, settings.SYNC_FAILED_SLACK_NOTIFICATION_CHANNEL)
    logger.info(
        {
            'action': 'channeling_loan.tasks.proceed_sync_channeling',
            'message': "Completed, sending notification to Slack channel : {} | "
            "Total Loans Success {} | "
            "Total Loans Invalid {}".format(
                settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL, ok_counter, nok_counter
            ),
            'channeling_type': channeling_type,
        }
    )
    send_notification_to_slack(
        'Upload successful', settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL
    )
    return


@task(queue="channeling_loan_normal")
def store_fama_repayment_approval_data_task():
    file_type = ChannelingActionTypeConst.REPAYMENT
    approval_file = ChannelingLoanApprovalFile.objects.create(
        channeling_type=ChannelingConst.FAMA, file_type=file_type
    )
    process_fama_approval_response(file_type=file_type, approval_file_id=approval_file.id)


@task(queue="channeling_loan_high")
def notify_channeling_loan_cancel_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.SUCCESS)
    if not channeling_loan_status:
        logger.info(
            {
                'action': 'channeling_loan.tasks.notify_channeling_loan_cancel_task',
                'loan_id': loan_id,
                'message': "no success status found",
            }
        )
        return

    loan_history = loan.loanhistory_set.last()
    message = (
        "Loan status code change, please check detail below.\n"
        "Loan ID : {}\n"
        "Lender : {}\n"
        "Status Code : {} to {}\n"
        "\n"
        "Please follow up this, Thank you"
    ).format(
        loan.id, loan.lender.lender_name, loan_history.status_old, loan_history.status_new
    )
    send_notification_to_slack(
        message, settings.NOTIFY_WHEN_LOAN_CANCEL_SLACK_NOTIFICATION_CHANNEL
    )


@task(queue="channeling_loan_normal")
def send_loan_for_channeling_to_smf_task(loan_id, channeling_status=None, retry_count=1):
    def _log_and_return(message):
        logger.info({
            'action': 'channeling_loan.tasks.send_loan_for_channeling_to_smf_task',
            'loan_id': loan_id,
            'message': message
        })
        return

    if not channeling_status:
        channeling_status = ChannelingStatusConst.PENDING

    loan, message = check_loan_validation_for_smf(loan_id)
    if not loan:
        return _log_and_return(message)

    channeling_loan_status = get_channeling_loan_status(loan, channeling_status)
    if not channeling_loan_status:
        return _log_and_return("Pending channeling not found")

    generate_smf_receipt_and_invoice_task(loan_id)

    document_validation = validate_smf_document_data(loan)
    if not all(document_validation.values()):
        if retry_count == 3:
            return _log_and_return(("Exceed maximum cap", document_validation, retry_count))

        eta_time = timezone.localtime(timezone.now()) + timedelta(minutes=5)
        send_loan_for_channeling_to_smf_task.apply_async(
            (loan.id, channeling_status, retry_count + 1), eta=eta_time
        )
        return _log_and_return(("Document not complete", document_validation, retry_count))

    status, result = get_smf_channeling_api_client().disburse(
        construct_smf_api_disbursement_data(loan), loan
    )

    change_reason = result.get('error', '')
    if status == SMFChannelingConst.OK_STATUS:
        change_reason = result.get('responseDescription', '')
        if result['responseCode'] == SMFChannelingConst.ONPROGRESS_STATUS_CODE:
            channeling_proccess_status, message = process_loan_for_channeling(loan)
            if channeling_proccess_status == ChannelingStatusConst.SUCCESS:
                return _log_and_return((channeling_proccess_status, message))

    update_channeling_loan_status(
        channeling_loan_status.id, ChannelingStatusConst.FAILED,
        change_reason=change_reason
    )
    return _log_and_return(change_reason)


@task(queue="channeling_loan_high")
def check_smf_process_disbursement_task(current_ts=None, days=2):
    if not current_ts:
        current_ts = timezone.localtime(timezone.now())

    logger.info({
        'action': 'channeling_loan.tasks.check_smf_process_disbursement_task',
        'current_ts': current_ts,
        'days': days,
        'message': 'start execute function'
    })

    all_process_channeling_loan_status = ChannelingLoanStatus.objects.filter(
        channeling_type=ChannelingConst.SMF,
        cdate__gte=current_ts.date() - timedelta(days=days),
        channeling_status=ChannelingStatusConst.PROCESS,
    )
    for channeling_loan_status in all_process_channeling_loan_status:
        check_smf_disburse_transaction_task.delay(channeling_loan_status.loan_id)

    logger.info({
        'action': 'channeling_loan.tasks.check_smf_process_disbursement_task',
        'current_ts': current_ts,
        'days': days,
        'total_process': len(all_process_channeling_loan_status),
        'message': 'end execute function'
    })


@task(queue="channeling_loan_normal")
def check_smf_disburse_transaction_task(loan_id, retry_count=0):
    def _log_and_return(message):
        logger.info({
            'action': 'channeling_loan.tasks.check_smf_disburse_transaction_task',
            'loan_id': loan_id,
            'retry_count': retry_count,
            'message': message
        })
        return

    loan, message = check_loan_validation_for_smf(loan_id)
    if not loan:
        return _log_and_return(message)

    retry_channeling_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SMF_CHANNELING_RETRY
    ).last()
    if not retry_channeling_feature:
        return _log_and_return("Unconfigurize retry feature")

    if retry_count > retry_channeling_feature.parameters["max_retry_count"]:
        return _log_and_return("Retry limit reach")

    status, result = get_smf_channeling_api_client().check_transaction(
        construct_smf_api_check_transaction_data(loan), loan
    )

    interval = retry_channeling_feature.parameters["minutes"]
    change_reason = result.get('error', '')
    response_code = result.get('responseCode', '')
    approval_status = 'y' if response_code == SMFChannelingConst.SUCCESS_STATUS_CODE else 'n'

    if status == SMFChannelingConst.OK_STATUS:
        change_reason = result.get('responseDescription', '')
        if result['responseCode'] == SMFChannelingConst.ONPROGRESS_STATUS_CODE:
            eta_time = timezone.localtime(timezone.now()) + timedelta(minutes=interval)
            check_smf_disburse_transaction_task.apply_async(
                (loan.id, retry_count + 1), eta=eta_time
            )
            return _log_and_return(change_reason)

    approve_loan_for_channeling(
        loan=loan, channeling_type=ChannelingConst.SMF, approval_status=approval_status,
    )

    return _log_and_return(change_reason)


@task(queue="channeling_loan_low")
def send_loans_for_channeling_to_dbs_task(loan_ids: List[int]):
    from juloserver.channeling_loan.services.dbs_services import DBSDisbursementServices
    from juloserver.loan.tasks.lender_related import loan_lender_approval_process_task

    loans = Loan.objects.filter(id__in=loan_ids)
    for loan in loans:
        status, message = DBSDisbursementServices().send_loan_for_channeling_to_dbs(loan=loan)
        logger.info(
            {
                'action': 'channeling_loan.tasks.send_loans_for_channeling_to_dbs_task',
                'loan_id': loan.id,
                'status': status,
                'message': message,
            }
        )

        if status == ChannelingStatusConst.FAILED:
            if loan.status == LoanStatusCodes.LENDER_APPROVAL:
                lender_id = loan.lender_id
                LoanLenderHistory.objects.create(loan=loan, lender_id=lender_id)
                loan.update_safely(lender=None)
                loan_lender_approval_process_task.delay(loan.id, lender_ids=[lender_id])


@task(queue="channeling_loan_high")
def record_channeling_tenure_cap_after_220_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    lender = loan.lender
    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.SUCCESS)

    base_logger_data = {
        "action": "channeling_loan.tasks.record_channeling_tenure_cap_after_220_task",
        "current_date": timezone.localtime(timezone.now()),
        "loan_id": loan_id,
        "channeling_loan_status": channeling_loan_status,
    }

    logger.info(
        {**base_logger_data, "message": "Start record_channeling_tenure_cap_after_220_task"}
    )

    if lender.lender_name != ChannelingConst.LENDER_DBS:
        logger.info({**base_logger_data, "message": "Non DBS lender"})
        return

    if not lender.is_pre_fund_channeling_flow:
        logger.info({**base_logger_data, "message": "Non DBS lender pre-fund"})
        return

    # will update when tenure cap release
    # record_channeling_tenure_cap(
    #     loan.loan_duration,
    #     loan.loan_amount,
    #     ChannelingConst.DBS,
    # )

    logger.info({**base_logger_data, "message": "End record_channeling_tenure_cap_after_220"})

import json
from datetime import datetime
from django.contrib.auth.models import User

from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.julo.models import (SkiptraceResultChoice, Skiptrace, SkiptraceHistory)
from juloserver.julo.services import ptp_create
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.minisquad.constants import (DialerTaskType, DialerTaskStatus, GenesysResultChoiceMapping)
from juloserver.minisquad.models import DialerTask
from juloserver.minisquad.services2.intelix import (update_intelix_callback, construct_status_and_status_group)
from juloserver.minisquad.tasks import trigger_insert_col_history
from juloserver.minisquad.tasks2 import create_failed_call_results


def store_genesys_call_result_to_skiptracehistory(genesys_call_result):
    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.MANUAL_UPLOAD_GENESYS_CALL_RESULTS,
        error=''
    )
    account_id = genesys_call_result.get('ACCOUNT_ID', False)
    account_payment_id = genesys_call_result.get('ACCOUNT_PAYMENT_ID', False)
    skiptrace_callback_time = genesys_call_result.get('CALLBACK_TIME') \
        if genesys_call_result.get('CALLBACK_TIME') else None

    skiptrace_notes = genesys_call_result.get('NOTES', '')
    skiptrace_agent_name = genesys_call_result.get('AGENT_NAME')
    start_time = datetime.strptime(genesys_call_result.get('START_TS'), '%Y-%m-%d %H:%M:%S')
    end_time = datetime.strptime(genesys_call_result.get('END_TS'), '%Y-%m-%d %H:%M:%S')
    non_payment_reason = None if 'NON_PAYMENT_REASON' not in genesys_call_result else \
        genesys_call_result.get('NON_PAYMENT_REASON')

    spoke_with = genesys_call_result.get('SPOKE_WITH')
    call_id = genesys_call_result.get('CALL_ID', None)
    account_payment_status_id = None
    account_payment = None
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        error_msg = 'Not found account for account_id - {} call_id {}'.format(
            account_id, call_id
        )
        create_failed_call_results(
            dict(
                dialer_task=dialer_task,
                error=error_msg,
                call_result=json.dumps(genesys_call_result)
            )
        )
        update_intelix_callback(
            error_msg, DialerTaskStatus.FAILURE, dialer_task
        )
        return False, error_msg

    account_payment = account.accountpayment_set.get_or_none(id=account_payment_id)

    if not account_payment:
        error_msg = 'Not found account_payment for account {} ' \
                    'with account_payment id - {} call_id {}'.format(account_id,
                                                                     account_payment_id, call_id)
        create_failed_call_results(
            dict(
                dialer_task=dialer_task,
                error=error_msg,
                call_result=json.dumps(genesys_call_result)
            )
        )
        update_intelix_callback(
            error_msg, DialerTaskStatus.FAILURE, dialer_task
        )
        return False, error_msg

    application = account.customer.application_set.last()
    customer = account.customer
    account_payment_status_id = account_payment.status_id

    skiptrace_phone = genesys_call_result.get('PHONE_NUMBER', False)
    agent_user = User.objects.filter(username=skiptrace_agent_name).last()
    if agent_user is None:
        error_msg = 'Invalid agent details - {} call_id {}'.format(
            skiptrace_agent_name, call_id
        )
        create_failed_call_results(
            dict(
                dialer_task=dialer_task,
                error=error_msg,
                call_result=json.dumps(genesys_call_result)
            )
        )
        update_intelix_callback(
            error_msg, DialerTaskStatus.FAILURE, dialer_task
        )
        return False, error_msg

    call_status = genesys_call_result.get('CALL_STATUS')
    skip_result_choice = SkiptraceResultChoice.objects.filter(
        name__iexact=call_status
    ).last()
    if not skip_result_choice:
        julo_skiptrace_result_choice = None \
            if call_status not in GenesysResultChoiceMapping.MAPPING_STATUS \
            else GenesysResultChoiceMapping.MAPPING_STATUS[call_status]

        skip_result_choice = SkiptraceResultChoice.objects.filter(
            name__iexact=julo_skiptrace_result_choice).last()
        if not skip_result_choice:
            error_msg = 'Invalid skip_result_choice with value {} call_id'.format(
                call_status, call_id
            )
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=error_msg,
                    call_result=json.dumps(genesys_call_result)
                )
            )
            update_intelix_callback(
                error_msg, DialerTaskStatus.FAILURE, dialer_task
            )
            return False, error_msg

    skiptrace_obj = Skiptrace.objects.filter(
        phone_number=format_e164_indo_phone_number(skiptrace_phone),
        customer_id=customer.id).last()

    if not skiptrace_obj:
        skiptrace_obj = Skiptrace.objects.create(
            phone_number=format_e164_indo_phone_number(skiptrace_phone),
            customer_id=customer.id
        )

    skiptrace_id = skiptrace_obj.id
    ptp_notes = ''
    if 'PTP_AMOUNT' in genesys_call_result and 'PTP_DATE' in genesys_call_result:
        ptp_amount = genesys_call_result.get('PTP_AMOUNT')
        ptp_date = genesys_call_result.get('PTP_DATE')
        if ptp_amount and ptp_date:
            ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
            account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
            ptp_create(account_payment, ptp_date, ptp_amount, agent_user, True)

    skiptrace_result_id = skip_result_choice.id

    status_group, status = construct_status_and_status_group(skip_result_choice.name)
    if skiptrace_notes:
        call_note = {
            "contact_source": skiptrace_obj.contact_source,
            "phone_number": str(skiptrace_obj.phone_number),
            "call_result": status,
            "spoke_with": spoke_with,
            "non_payment_reason": non_payment_reason or ''
        }
        AccountPaymentNote.objects.create(
            note_text='{};{}'.format(ptp_notes, skiptrace_notes),
            account_payment=account_payment,
            added_by=agent_user,
            extra_data={
                'call_note': call_note
            }
        )

    SkiptraceHistory.objects.create(
        start_ts=start_time, end_ts=end_time, application_id=application.id,
        agent_name=agent_user.username, call_result_id=skiptrace_result_id,
        agent_id=agent_user.id, skiptrace_id=skiptrace_id, notes=skiptrace_notes,
        callback_time=skiptrace_callback_time, application_status=application.status,
        non_payment_reason=non_payment_reason, spoke_with=spoke_with,
        status_group=status_group, status=status,
        account_id=account_id,
        account_payment_id=account_payment_id,
        account_payment_status_id=account_payment_status_id, source='Genesys',
        unique_call_id=call_id
    )

    if agent_user:
        trigger_insert_col_history(
            account_payment.id, agent_user.id, skip_result_choice.id, True)

    error_msg = 'Details updated for account - {} call_id {}'.format(
        account.id, call_id)

    update_intelix_callback(
        error_msg, DialerTaskStatus.SUCCESS, dialer_task
    )
    return True, 'Success insert to skiptracehistory'

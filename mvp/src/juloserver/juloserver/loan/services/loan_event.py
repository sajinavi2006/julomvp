import math

from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.services2 import get_appsflyer_service
from juloserver.account.services.account_related import get_account_property_by_account
from juloserver.julo.workflows2.tasks import appsflyer_update_status_task
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.google_analytics.constants import GAEvent
from juloserver.ana_api.models import PdApplicationFraudModelResult


def send_loan_status_changed_to_ga_appsflyer_event(
    application, loan, old_status_code, new_status_code
):
    """
    Send loan status changed to GA and Appsflyer
    Only send when new_status_code > old_status_code
        and old_status_code is [x220, x250]
    """
    if (
        new_status_code in [LoanStatusCodes.CURRENT, LoanStatusCodes.PAID_OFF]
        and old_status_code < new_status_code
    ):
        # trigger status changes events  to appflyer and GA
        # extra_params : can pass any extra key value pair with events
        extra_params = (
            {'credit_limit_balance': loan.loan_disbursement_amount}
            if new_status_code == LoanStatusCodes.CURRENT
            else {}
        )
        appsflyer_service = get_appsflyer_service()
        appsflyer_service.info_j1_loan_status(loan, new_status_code, extra_params)

        loan_status_ga_event = getattr(GAEvent, 'X' + str(new_status_code))
        send_event_to_ga_task_async.apply_async(
            kwargs={
                'customer_id': loan.customer.id,
                'event': loan_status_ga_event,
                'extra_params': extra_params,
            }
        )

        ftc_repeat_x220_events = handle_x220_ga_event(loan, new_status_code)
        for loan_suffix_event in ftc_repeat_x220_events:
            if loan_suffix_event == '_mycroft90':
                continue
            send_event_to_ga_task_async.apply_async(
                kwargs={
                    'customer_id': loan.customer.id,
                    'event': loan_status_ga_event + loan_suffix_event,
                    'extra_params': extra_params,
                }
            )

            appsflyer_update_status_task.delay(
                application.id,
                str(new_status_code) + loan_suffix_event,
                extra_params=extra_params,
            )

        x220_ftc_pct_events = combine_x220_ftc_pct_mycroft_event(ftc_repeat_x220_events)
        for x220_ftc_pct_event in x220_ftc_pct_events:
            send_event_to_ga_task_async.apply_async(
                kwargs={
                    'customer_id': loan.customer.id,
                    'event': x220_ftc_pct_event,
                    'extra_params': extra_params,
                }
            )

            appsflyer_update_status_task.delay(
                application.id,
                x220_ftc_pct_event,
                extra_params=extra_params,
            )


def handle_x220_ga_event(loan, new_status_code):
    event_suffix_list = []

    if new_status_code != LoanStatusCodes.CURRENT:
        return event_suffix_list

    application = loan.get_application

    if not application.is_julo_one_or_starter():
        return event_suffix_list

    # handle ftc or repeat event
    if loan.is_first_time_220:
        loan_ftc_or_repeat_event = '_ftc'
    else:
        loan_ftc_or_repeat_event = '_repeat'

    event_suffix_list.append(loan_ftc_or_repeat_event)

    pct_values = [('_pct80', 8), ('_pct90', 9)]
    account_property = get_account_property_by_account(loan.account)
    if not account_property:
        return event_suffix_list

    has_pct_event = False
    pgood = account_property.pgood
    for pct_score_str, pct_score_num in pct_values:
        if math.floor(pgood * 10) == pct_score_num:
            event_suffix_list.append(pct_score_str)
            has_pct_event = True
            break

    if has_pct_event:
        pct_mycroft_values = [('_mycroft90', 9)]
        pd_fraud = PdApplicationFraudModelResult.objects.filter(
            customer_id=loan.customer_id
        ).last()
        if pd_fraud:
            mycroft_pgood = pd_fraud.pgood
            for pct_score_str, pct_score_num in pct_mycroft_values:
                if math.floor(mycroft_pgood * 10) == pct_score_num:
                    event_suffix_list.append(pct_score_str)
                    break

    return event_suffix_list


def combine_x220_ftc_pct_mycroft_event(event_suffix_list):
    base_path = 'x_220'

    if '_pct80' in event_suffix_list:
        pct = '_pct80'
    elif '_pct90' in event_suffix_list:
        pct = '_pct90'
    else:
        return []  # No pct, return empty list

    result = []
    if '_ftc' in event_suffix_list:
        result.append("{base_path}_ftc{pct}".format(base_path=base_path, pct=pct))

    if '_mycroft90' in event_suffix_list:
        result.append("{base_path}{pct}_mycroft90".format(base_path=base_path, pct=pct))
        if '_ftc' in event_suffix_list:
            result.append("{base_path}_ftc{pct}_mycroft90".format(base_path=base_path, pct=pct))

    return result

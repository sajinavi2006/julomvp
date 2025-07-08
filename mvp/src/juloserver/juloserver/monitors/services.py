import logging

from ..julo.clients import get_julo_sentry_client
from . import checks
from .notifications import notify_data_integrity_checks_completed
from django.conf import settings


logger = logging.getLogger(__name__)


def check_data_integrity():

    check_functions = [
        'check_late_fee_applied',
        'check_paid_amount_is_correct',
        'check_doku_referred_customers_are_properly_linked',
        'check_resubmission_requested_images',
        'check_doku_payment_are_processed',
        'check_no_unprocessed_doku_payments',
        'check_skiptrace_data_generated',
        'check_assigned_loans_to_vas',
        'check_inaccurate_product_line',
        'check_application_checklist',
        'check_agent_in_loan',
        'check_inaccurate_collateral_partner',
        'check_unsent_application_collateral_partner',
        'check_application_in_110_has_images',
        'check_application_in_105_has_images',
        'check_va_by_loan',
        'check_faspay_transaction_id',
        'check_faspay_status_code',
        'check_kyc_application'
    ]

    for check_function in check_functions:
        try:
            getattr(checks, check_function)()
        except:
            julo_sentry_client = get_julo_sentry_client()
            julo_sentry_client.captureException()
    notify_data_integrity_checks_completed(check_functions)


def check_data_integrity_hourly():

    check_functions = [
        'check_pending_disbursements',
        'check_xendit_balance'
    ]

    for check_function in check_functions:
        try:
            getattr(checks, check_function)()
        except:
            julo_sentry_client = get_julo_sentry_client()
            julo_sentry_client.captureException()


def get_channel_name_slack_for_payment_problem():
    # default set as staging, take care of if local trying to test
    channel_name = '#staging_payment_problem'
    if settings.ENVIRONMENT == 'prod':
        channel_name = '#payment_problem'
        return channel_name
    elif settings.ENVIRONMENT == 'uat':
        channel_name = '#uat_payment_problem'
        return channel_name

    return channel_name

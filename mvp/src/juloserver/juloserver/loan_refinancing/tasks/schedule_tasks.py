import logging

from celery import task
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequestCampaign,
    LoanRefinancingRequest,
    LoanRefinancingOffer,
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst, Campaign
from django.utils import timezone
from juloserver.integapiv1.tasks import update_va_bni_transaction
from django.db import transaction
from django.utils import timezone, dateparse
from juloserver.account.models import Account
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.loan_refinancing.services.notification_related import CovidLoanRefinancingEmail
from juloserver.account.constants import AccountConstant
import os
import pandas as pd

logger = logging.getLogger(__name__)


@task(queue="collection_normal")
def set_expired_refinancing_request():
    """cron job to make expired for loan refinancing request"""
    # get list of request in some status
    from ..services.loan_related import get_refinancing_request_expired_possibility
    refinancing_request_ids = get_refinancing_request_expired_possibility()

    logger.info({
        'action': 'set_expired_refinancing_request',
        'data': {'refinancing_request_ids': refinancing_request_ids}
        })

    for request_id in refinancing_request_ids:
        set_expired_refinancing_request_subtask.delay(request_id)


@task(queue="collection_normal")
def set_expired_refinancing_request_subtask(loan_refinancing_request_id):
    """subtask to prevent memory leak in python"""
    from ..services.loan_related import (get_loan_refinancing_request_by_id,
                                         is_proactive_link_expired,
                                         expire_loan_refinancing_request)
    logger.info({
        'action': 'set_expired_refinancing_request_subtask',
        'data': {'loan_refinancing_request_id': loan_refinancing_request_id}
        })
    loan_refinancing_request = get_loan_refinancing_request_by_id(loan_refinancing_request_id)
    if not loan_refinancing_request:
        logger.error({
            'action': 'set_expired_refinancing_request_subtask',
            'data': {'loan_refinancing_request_id': loan_refinancing_request_id},
            'error': 'Loan Refinancing not found'
            })
        return False

    # check expired or not which is_proactive_link_expired
    if is_proactive_link_expired(loan_refinancing_request):
        # update status to Expired (in transaction)
        expire_loan_refinancing_request(loan_refinancing_request)
    else:
        logger.warn({
            'action': 'set_expired_refinancing_request_subtask',
            'data': {'loan_refinancing_request_id': loan_refinancing_request_id},
            'msg': 'refinancing request has not been expired yet'
            })
        return False
    return True


@task(queue="collection_normal")
def set_expired_refinancing_request_from_requested_status_with_campaign():
    """
    cron job to make expired for loan refinancing request with status on requested
    with campign
    """
    # get loan refinancing status on requested status

    refinancing_request_ids = LoanRefinancingRequestCampaign.objects.filter(
        loan_refinancing_request__status=CovidRefinancingConst.STATUSES.requested,
        expired_at__lt=timezone.now().date()
    ).values_list('loan_refinancing_request', flat=True)

    logger.info({
        'action': 'set_expired_refinancing_request_from_requested_status_with_campaign',
        'data': {'refinancing_request_ids': refinancing_request_ids}
    })

    if refinancing_request_ids:
        LoanRefinancingRequest.objects.filter(
            pk__in=refinancing_request_ids
        ).update(
            expire_in_days=0,
            status=CovidRefinancingConst.STATUSES.expired)

        loan_refinancing_requests = LoanRefinancingRequest.objects.filter(
            pk__in=refinancing_request_ids
        )
        for loan_refinancing_request in loan_refinancing_requests:
            update_va_bni_transaction.delay(
                loan_refinancing_request.account.id,
                'change_following_process_status_to_expired',
            )


@task(queue="dialer_call_results_queue")
def blast_email_sos_refinancing(path):
    fn_name = 'blast_email_sos_refinancing'
    logger.info({
        'action': fn_name,
        'info': 'task begin',
    })

    if not os.path.exists(path):
        logger.error({
            'action': fn_name,
            'info': "there's no file at {}".format(path),
        })
        get_julo_sentry_client().captureException()
        return

    # read data with pandas, and drop the duplicate account
    df = pd.read_csv(path)
    df = df.drop_duplicates(subset='account_id')

    for _, refinancing_data in df.iterrows():
        blast_email_sos_refinancing_subtask.delay(refinancing_data)

    logger.info({
        'action': fn_name,
        'info': 'All data sent to Async task',
    })


@task(queue="dialer_call_results_queue")
def blast_email_sos_refinancing_subtask(refinancing_data):
    from juloserver.loan_refinancing.services.offer_related import (
        change_exist_refinancing_status_to_expired,
        create_loan_refinancing_request_sos,
    )
    from juloserver.account_payment.services.account_payment_related import \
        update_checkout_experience_status_to_cancel

    fn_name = 'blast_email_sos_refinancing_subtask'
    logger.info({
        'action': fn_name,
        'info': 'task begin',
        'account_id': refinancing_data['account_id']
    })
    errors = {
        'email_sent': False,
    }
    loan_refinancing_request = None
    try:
        with transaction.atomic():
            account = Account.objects.get(id=refinancing_data['account_id'])
            change_exist_refinancing_status_to_expired(account)
            # update checkout to cancel
            update_checkout_experience_status_to_cancel(account.id)

            expire_in_days = (dateparse.parse_date(
                refinancing_data['expired_at']) - timezone.localtime(timezone.now()).date()).days
            loan_refinancing_request = create_loan_refinancing_request_sos(
                refinancing_data['account_id'], expire_in_days)
    except Exception as error:
        logger.error({
            'action': fn_name,
            'info': "there's issue during creating loan refinancing request",
            'message': str(error),
            'account_id': refinancing_data['account_id']
        })
        errors['reason'] = str(error)
        get_julo_sentry_client().captureException()
    finally:
        if not errors.get('reason'):
            status = 'Success'
            extra_data = None
        else:
            status = 'Failed'
            extra_data = errors
            loan_refinancing_request = None

        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.create(
            loan_refinancing_request=loan_refinancing_request,
            account_id=refinancing_data['account_id'],
            campaign_name=Campaign.R1_SOS_REFINANCING_23,
            expired_at=refinancing_data['expired_at'],
            status=status,
            extra_data=extra_data
        )

    try:
        if not errors.get('reason'):
            # send email
            loan_refinancing_email = CovidLoanRefinancingEmail(loan_refinancing_request)
            loan_refinancing_email.send_offer_sos_refinancing_email()
            errors['email_sent'] = True
    except Exception as error:
        logger.error({
            'action': fn_name,
            'info': "there's issue during sending email sos refinancing",
            'message': str(error),
            'account_id': refinancing_data['account_id']
        })
        get_julo_sentry_client().captureException()
        errors['reason'] = str(error)
        loan_ref_req_campaign.update_safely(
            extra_data=errors
        )

    if not errors.get('reason'):
        logger.error({
            'action': fn_name,
            'info': "Loan refinancing request created",
            'account_id': refinancing_data['account_id']
        })


@task(queue="dialer_call_results_queue")
def activation_sos_refinancing(path):
    fn_name = 'activation_sos_refinancing'
    logger.info({
        'action': fn_name,
        'info': 'task begin',
    })

    if not os.path.exists(path):
        logger.error({
            'action': fn_name,
            'info': "there's no file at {}".format(path),
        })
        get_julo_sentry_client().captureException()
        return

    # read data with pandas, and drop the duplicate account
    df = pd.read_csv(path)
    df = df.drop_duplicates(subset='account_id')

    for _, refinancing_data in df.iterrows():
        activation_sos_refinancing_subtask.delay(refinancing_data)

    logger.info({
        'action': fn_name,
        'info': 'All data sent to Async task',
    })


@task(queue="dialer_call_results_queue")
def activation_sos_refinancing_subtask(refinancing_data):
    from juloserver.refinancing.services import J1LoanRefinancing
    from juloserver.account.services.account_related import process_change_account_status
    from juloserver.julo.models import EmailHistory

    fn_name = 'activation_sos_refinancing_subtask'
    logger.info({
        'action': fn_name,
        'info': 'task begin',
        'account_id': refinancing_data['account_id']
    })

    try:
        with transaction.atomic():
            loan_refinancing_campaign = LoanRefinancingRequestCampaign.objects.select_related(
                'loan_refinancing_request'
            ).filter(
                campaign_name=Campaign.R1_SOS_REFINANCING_23,
                loan_refinancing_request__status=CovidRefinancingConst.STATUSES.approved,
                account=refinancing_data['account_id']
            ).last()
            if not loan_refinancing_campaign:
                logger.warning({
                    'action': fn_name,
                    'info': "there's no data on loan refinancing request campaign",
                    'account_id': refinancing_data['account_id']
                })
                return

            loan_refinancing_request = loan_refinancing_campaign.loan_refinancing_request
            if not loan_refinancing_request:
                logger.warning({
                    'action': fn_name,
                    'info': "there's no data on loan refinancing request",
                    'account_id': refinancing_data['account_id']
                })
                return

            customer = loan_refinancing_request.account.customer
            if EmailHistory.objects.filter(
                customer_id=customer.id,
                template_code='sos_email_refinancing_r1_30/08/23',
                status__in=['click', 'clicked']).exists():
                logger.info({
                    'action': fn_name,
                    'info': "customer rejected the offer, triggered by click button",
                    'account_id': refinancing_data['account_id']
                })
                LoanRefinancingRequest.objects.filter(
                    pk=loan_refinancing_request.id).last().update_safely(
                    expire_in_days=0,
                    status=CovidRefinancingConst.STATUSES.expired,
                    udate=timezone.localtime(timezone.now())
                )
                return

            account = Account.objects.get(pk=refinancing_data['account_id'])
            account_payment = account.get_oldest_unpaid_account_payment()
            j1_loan_refinancing = J1LoanRefinancing(
                account_payment, loan_refinancing_request)
            if not j1_loan_refinancing.activate():
                raise Exception('Failed to activate SOS refinancing')
            process_change_account_status(
                account, AccountConstant.STATUS_CODE.suspended, 'SOS refinancing')
    except Exception as error:
        logger.error({
            'action': fn_name,
            'info': 'Error during activate SOS refinancing',
            'account_id': refinancing_data['account_id'],
            'message': str(error)
        })
        get_julo_sentry_client().captureException()
        return

    logger.info({
        'action': fn_name,
        'info': 'SOS refinancing successfully created',
        'account_id': refinancing_data['account_id'],
    })

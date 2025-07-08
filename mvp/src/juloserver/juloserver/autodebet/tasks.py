import logging
import semver
import time
from datetime import timedelta, datetime
from typing import (
    Optional,
)

from celery import task, chain
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.conf import settings

from juloserver.account.models import (
    Account,
    ExperimentGroup,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.autodebet.clients import (
    get_bca_autodebet_client,
    get_bri_autodebet_client,
    get_bni_autodebet_client,
    get_dana_autodebet_client,
    get_mandiri_autodebet_client,
)
from juloserver.autodebet.constants import (
    VendorConst,
    AutodebetStatuses,
    AutodebetVendorConst,
    AutodebetDeductionSourceConst,
    FeatureNameConst,
    BRITransactionStatus,
    REACTIVATION_VERSION_VENDOR,
    AutodebetBNIPaymentResultStatusConst,
    SWEEPING_SAFE_INTERVAL,
    AutodebetDANAPaymentResultStatusConst,
    AutodebetDANATransactionStatusCodeCons,
    AutodebetOVOPaymentResultStatusConst,
    DanaErrorCode,
    AutodebetDanaResponseCodeConst,
    AutodebetOVOResponseCodeConst,
    AutodebetOVOTransactionStatusCodeCons,
    AutodebetMandiriPaymentResultStatusConst,
)
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBenefit,
    AutodebetAPILog,
    AutodebetBRITransaction,
    AutodebetBniTransaction,
    AutodebetDanaTransaction,
    AutodebetOvoTransaction,
    AutodebetPaymentOffer,
    AutodebetSuspendLog,
    AutodebetMandiriTransaction,
    AutodebetMandiriAccount,
    GopayAutodebetSubscriptionRetry,
)
from juloserver.autodebet.services.account_services import (
    is_account_eligible_for_fund_collection,
    is_account_eligible_for_fund_collection_experiment,
    is_autodebet_feature_active,
    is_autodebet_bri_feature_active,
    is_autodebet_gopay_feature_active,
    is_autodebet_feature_disable,
    is_autodebet_mandiri_feature_active,
    is_autodebet_bni_feature_active,
    is_idfy_autodebet_valid,
    is_autodebet_dana_feature_active,
    is_autodebet_ovo_feature_active,
    is_experiment_group_autodebet,
    get_autodebet_experiment_setting,
    get_autodebet_dpd_deduction,
)

from juloserver.autodebet.services.task_services import (
    create_debit_payment_process_bri,
    get_active_autodebet_account,
    get_active_autodebet_gopay_account,
    process_fund_collection,
    process_autodebet_benefit_waiver,
    retry_autodebet_bri_validation,
    determine_best_deduction_day,
    get_autodebet_inquiry_feature_configuration,
    inquiry_account_registration,
    create_subscription_payment_process_gopay,
    get_gopay_wallet_customer_balance,
    update_gopay_wallet_customer_balance,
    get_autodebet_payment_method,
    create_debit_payment_process_dana,
    create_debit_payment_process_ovo,
    create_debit_payment_process_mandiriv2,
)
from juloserver.autodebet.services.authorization_services import (
    check_gopay_wallet_token_valid,
    update_gopay_wallet_token,
    update_autodebet_bri_transaction_failed,
    update_autodebet_bni_transaction_failed,
)
from juloserver.autodebet.utils import convert_bytes_to_dict_or_string
from juloserver.julo.models import (
    Customer,
    FeatureSetting,
    PaybackTransaction,
    CustomerAppAction,
    Device,
)

from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_julo_pn_client,
    get_doku_snap_ovo_client,
)
from juloserver.monitors.notifications import get_slack_bot_client, send_slack_bot_message
from juloserver.moengage.services.use_cases_ext2 import send_event_autodebet_payment_method_disabled

from juloserver.autodebet.services.mandiri_services import (
    get_channel_name_slack_autodebet_mandiri_deduction,
    inquiry_transaction_statusv2,
)
from juloserver.autodebet.services.task_services import get_due_amount_for_gopay_autodebet_deduction

from juloserver.payback.models import GopayAutodebetTransaction
from juloserver.payback.constants import GopayAccountStatusConst
from juloserver.payback.client import get_gopay_client
from juloserver.payback.exceptions import GopayError
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.autodebet.services.bni_services import create_debit_payment_process_bni
from juloserver.autodebet.services.bni_services import process_bni_autodebet_repayment
from juloserver.autodebet.services.autodebet_services import suspend_autodebet_insufficient_balance
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.moengage.tasks import (
    update_moengage_for_payment_received_task,
    send_event_autodebit_failed_deduction_task,
)
from juloserver.autodebet.services.benefit_services import is_eligible_to_get_benefit, give_benefit
from juloserver.julo.utils import execute_after_transaction_safely, have_pn_device
from juloserver.autodebet.services.account_services import get_existing_autodebet_account
from juloserver.julo.services2 import get_redis_client
from juloserver.autodebet.constants import RedisKey
from juloserver.ovo.models import OvoWalletAccount
from juloserver.ovo.constants import OvoWalletAccountStatusConst


logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


@task(queue='repayment_low')
def inquiry_account_registration_task(autodebet_account_id, retry_count=0):
    autodebet_inquiry_config = get_autodebet_inquiry_feature_configuration(retry_count)
    if not autodebet_inquiry_config:
        return

    gaps = timedelta(minutes=autodebet_inquiry_config['delay_in_minutes'])

    status, error_message = inquiry_account_registration(autodebet_account_id, retry_count)
    logger.info({
        'action': 'inquiry_account_registration_task',
        'autodebet_account_id': autodebet_account_id,
        'retry_count': retry_count,
        'status': status,
        'message': error_message,
    })
    if status == "03":
        inquiry_account_registration_task.apply_async(
            (autodebet_account_id, retry_count + 1, ),
            eta=timezone.localtime(timezone.now()) + gaps
        )
    return


@task(queue='repayment_high')
def collect_autodebet_account_collections_task():
    is_bca_autodebet_active = is_autodebet_feature_active()
    is_bri_autodebet_active = is_autodebet_bri_feature_active()
    is_mandiri_autodebet_active = is_autodebet_mandiri_feature_active()
    is_bni_autodebet_active = is_autodebet_bni_feature_active()

    autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY,
        is_active=True
    )
    autodebet_deduction_parameters = None
    if autodebet_deduction_feature_setting:
        autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters
    vendors = []

    if (
        not is_bca_autodebet_active
        and not is_bri_autodebet_active
        and not is_mandiri_autodebet_active
        and not is_bni_autodebet_active
    ):
        return

    is_bca_autodebet_disable = is_autodebet_feature_disable(VendorConst.BCA)
    is_bri_autodebet_disable = is_autodebet_feature_disable(VendorConst.BRI)
    is_mandiri_autodebet_disable = is_autodebet_feature_disable(VendorConst.MANDIRI)
    is_bni_autodebet_disable = is_autodebet_feature_disable(VendorConst.BNI)

    if is_bri_autodebet_active and not is_bri_autodebet_disable:
        vendors.append('BRI')

    if is_bca_autodebet_active and not is_bca_autodebet_disable:
        vendors.append('BCA')

    if is_mandiri_autodebet_active and not is_mandiri_autodebet_disable:
        vendors.append('MANDIRI')

    if is_bni_autodebet_active and not is_bni_autodebet_disable:
        vendors.append('BNI')

    today_date = timezone.localtime(timezone.now()).date()

    for autodebet_account in get_active_autodebet_account(vendors):
        account = autodebet_account.account
        account_payment = account.accountpayment_set.not_paid_active().filter(
            due_date=today_date).order_by('due_date').last()
        account_payment_this_month = AccountPayment.objects.filter(
            due_date__month=today_date.month,
            due_date__year=today_date.year,
            account=account
        ).last()
        vendor = autodebet_account.vendor
        deduction_cycle_day = determine_best_deduction_day(account)

        if vendor in AutodebetVendorConst.LIST:
            # temporary
            if vendor != AutodebetVendorConst.MANDIRI:
                if autodebet_deduction_parameters:
                    if autodebet_deduction_parameters[vendor]['deduction_day_type']\
                            == AutodebetDeductionSourceConst.FOLLOW_PAYDAY:
                        account_payment = None
                        if not deduction_cycle_day:
                            sentry.captureMessage(
                                'deduction_cycle_day with account_id: {} is None'.format(
                                    account.id))
                            logger.info({
                                'action': 'collect_autodebet_account_collections_task',
                                'account_id': account.id,
                                'message': 'deduction_cycle_day is none',
                            })
                            continue
                        if account_payment_this_month:
                            if today_date.day == deduction_cycle_day:
                                if (datetime.strptime(
                                        autodebet_deduction_parameters[vendor]['last_update'],
                                        '%Y-%m-%d').date() < account_payment_this_month.due_date):
                                    account_payment = account.accountpayment_set.not_paid_active()\
                                        .order_by('due_date').last()

        if not account_payment:
            logger.info({
                'action': 'collect_autodebet_account_collections_task',
                'account_id': account.id,
                'message': "unpaid account payment not found",
            })
            continue

        if autodebet_deduction_parameters:
            if autodebet_deduction_parameters[vendor]['deduction_day_type'] \
                    == AutodebetDeductionSourceConst.FOLLOW_DUE_DATE:
                if (datetime.strptime(autodebet_deduction_parameters[vendor]['last_update'],
                                      '%Y-%m-%d').date()
                        >= datetime(today_date.year, today_date.month, deduction_cycle_day).date()):
                    continue

        if vendor == AutodebetVendorConst.BCA:
            if autodebet_deduction_parameters:
                if autodebet_deduction_parameters[vendor]['deduction_day_type']\
                        == AutodebetDeductionSourceConst.FOLLOW_PAYDAY:
                    if not is_account_eligible_for_fund_collection_experiment(
                            autodebet_account, today_date):
                        logger.info({
                            'action': 'is_account_eligible_for_fund_collection',
                            'account_payment': account_payment.id,
                            'message': 'Exclude fund collection for users that have due date = '
                                    'registered date'})
                        continue

        if vendor in [
            AutodebetVendorConst.BCA,
            AutodebetVendorConst.MANDIRI,
            AutodebetVendorConst.BNI,
        ]:
            if not is_account_eligible_for_fund_collection(account_payment):
                logger.info({
                    'action': 'is_account_eligible_for_fund_collection',
                    'account_payment': account_payment.id,
                    'message': 'Exclude fund collection for users that have due date = '
                            'registered date'})
                continue

        filter_ = {"due_date__lte": today_date}
        if autodebet_deduction_parameters:
            if autodebet_deduction_parameters[vendor]['deduction_day_type'] \
                    == AutodebetDeductionSourceConst.FOLLOW_PAYDAY:
                filter_ = {
                    "due_date__month__lte": today_date.month,
                    "due_date__year__lte": today_date.year
                }
        if account_payment:
            filter_["due_date__lte"] = account_payment.due_date

        account_payment_ids = account.accountpayment_set.not_paid_active()\
            .filter(**filter_).order_by('due_date').values_list('id', flat=True)

        if not account_payment_ids:
            logger.info({
                'action': 'collect_autodebet_account_collections_task',
                'account_id': account.id,
                'message': "account payment not found",
            })
            continue

        if vendor == AutodebetVendorConst.BRI:
            bri_autodebet_client = get_bri_autodebet_client(account)
            response, error = bri_autodebet_client.get_payment_method(
                autodebet_account.payment_method_id
            )
            if error:
                sentry.captureMessage(
                    'Failed to get BRI payment method for autodebet account {}: {}'.format(
                        autodebet_account.id, error
                    )
                )
                continue
            if response is None:
                sentry.captureMessage(
                    'BRI Autodebet Empty Response - Autodebet Account ID: {}'.format(
                        autodebet_account.id
                    )
                )
                continue
            if response['status'] in ['INACTIVE', 'EXPIRED', 'FAILED']:
                logger.info(
                    {
                        'action': 'BRI autodebet bad status before deduction',
                        'account_id': account.id,
                        'autodebet_account_id': autodebet_account.id,
                        'payment_method_id': autodebet_account.payment_method_id,
                        'status': response['status'],
                    }
                )
                autodebet_account.update_safely(
                    is_use_autodebet=False,
                    is_deleted_autodebet=True,
                    deleted_success_ts=timezone.localtime(timezone.now()),
                    status=AutodebetStatuses.REVOKED,
                    deleted_failed_reason=response['status'],
                )
                julo_pn_client = get_julo_pn_client()
                device = Device.objects.filter(customer_id=account.customer_id).last()
                if not have_pn_device(device):
                    logger.warning(
                        {
                            "action": "collect_autodebet_account_collections_task",
                            "error": "not pn device",
                            "customer_id": account.customer_id,
                            "device_id": device.id,
                        }
                    )
                    continue
                julo_pn_client.pn_bri_bad_status_before_deduction(device.gcm_reg_id)
                continue

        if len(account_payment_ids) > 0:
            autodebet_fund_collection_task.delay(
                account_payment_ids,
                autodebet_account.vendor,
                account
            )


@task(queue='repayment_high')
def autodebet_fund_collection_task(account_payment_ids, vendor, account=None):
    account_payments = AccountPayment.objects.filter(
        pk__in=account_payment_ids
    ).order_by('due_date')
    if not account_payments:
        logger.info({
            'action': 'autodebet_fund_collection_task',
            'account_payment_ids': account_payment_ids,
            'message': "account payments not found",
        })
        return

    today_date = timezone.localtime(timezone.now()).date()
    is_account_payment_due_today = False if account_payments.last().due_date != today_date\
        else True
    autodebet_deduction_parameters = None
    autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY,
        is_active=True
    )

    if autodebet_deduction_feature_setting:
        autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters

    if vendor in AutodebetVendorConst.LIST:
        # temporary
        if vendor != 'MANDIRI':
            if autodebet_deduction_parameters:
                if autodebet_deduction_parameters[vendor]['deduction_day_type']\
                        == AutodebetDeductionSourceConst.FOLLOW_PAYDAY:
                    deduction_cycle_day = determine_best_deduction_day(account)

                    is_account_payment_due_today = True

                    if deduction_cycle_day != today_date.day:
                        is_account_payment_due_today = False

    if not is_account_payment_due_today:
        logger.info({
            'action': 'autodebet_fund_collection_task',
            'account_payment_ids': account_payment_ids,
            'message': "no account payments due today",
        })
        return

    message = 'success'
    if vendor == AutodebetVendorConst.BRI:
        account_payment_id = create_debit_payment_process_bri(account_payments)
        if account_payment_id:
            call_retry_mechanism_task.delay(account_payment_id, account_payment_ids)
    elif vendor == AutodebetVendorConst.BCA:
        fs = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.DELAY_AUTODEBET_BCA_DEDUCTION, is_active=True
        )
        if fs:
            delay_in_seconds = fs.parameters.get('delay_in_seconds', 5)
            slice_autodebet_fund_collection_task_bca.delay(
                account_payment_ids, vendor, delay_in_seconds
            )
        else:
            slice_autodebet_fund_collection_task(account_payment_ids, vendor)
    elif vendor == AutodebetVendorConst.MANDIRI:
        create_debit_payment_process_mandiriv2(account_payments)
    elif vendor == AutodebetVendorConst.BNI:
        create_debit_payment_process_bni(account_payments)
    else:
        message = process_fund_collection(account_payments, vendor)
        if message == 'Saldo tidak cukup' and len(account_payments) > 1:
            slice_autodebet_fund_collection_task.delay(account_payment_ids, vendor)

    logger.info({
        'action': 'juloserver.autodebet.tasks.autodebet_fund_collection_task',
        'account_payment_ids': account_payment_ids,
        'vendor': vendor,
        'message': message
    })


@task(queue='repayment_high')
def slice_autodebet_fund_collection_task(account_payment_ids, vendor):
    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.slice_autodebet_fund_collection_task_initial',
            'account_payment_ids': account_payment_ids,
            'vendor': vendor,
        }
    )
    if not account_payment_ids:
        logger.info({
            'action': 'slice_autodebet_fund_collection_task',
            'account_payment_ids': account_payment_ids,
            'message': "account payments not found",
        })
        return

    for account_payment_id in account_payment_ids:
        account_payment = AccountPayment.objects.filter(pk=account_payment_id)
        if not account_payment:
            continue
        message = process_fund_collection(account_payment, vendor)

        logger.info({
            'action': 'juloserver.autodebet.tasks.slice_autodebet_fund_collection_task',
            'account_payment_id': account_payment_id,
            'account_payment_ids': account_payment_ids,
            'vendor': vendor,
            'message': message
        })

        if message:
            break


@task(queue='autodebet_bca')
def slice_autodebet_fund_collection_task_bca(account_payment_ids, vendor, delay_in_seconds):
    redis_client = get_redis_client()
    key = RedisKey.AUTODEBET_FUND_COLLECTION_TASK_BCA_COUNTER
    counter = redis_client.get(key)
    if counter:
        counter = int(counter) + delay_in_seconds
        redis_client.set(key, counter, timedelta(hours=1))
    else:
        counter = 0
        redis_client.set(key, counter, timedelta(hours=1))
    slice_autodebet_fund_collection_task.apply_async(
        (account_payment_ids, vendor),
        countdown=counter,
        queue='autodebet_bca',
    )


@task(queue='repayment_high')
def autodebet_benefit_waiver_task(account_id):
    account = Account.objects.get(pk=account_id)
    if not account:
        logger.info({
            'action': 'autodebet_benefit_waiver_task',
            'account_id': account_id,
            'message': "account not found",
        })
        return
    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment:
        logger.info({
            'action': 'autodebet_benefit_waiver_task',
            'account_id': account_id,
            'message': "account payment not found",
        })
        return

    process_autodebet_benefit_waiver(account_payment)


@task(queue='repayment_low')
def scheduled_pending_revocation_sweeper():
    # right now only implemented for BCA
    vendor = VendorConst.BCA
    pending_revocation_autodebets = AutodebetAccount.objects.filter(
        vendor=vendor,
        is_use_autodebet=False,
        deleted_request_ts__isnull=False,
        status=AutodebetStatuses.PENDING_REVOCATION,).only('id')
    for pending_revocation_autodebet in pending_revocation_autodebets:
        logger.info({
            'action': 'juloserver.autodebet.tasks.scheduled_pending_revocation_sweeper',
            'autodebet_account_id': pending_revocation_autodebet.id,
            'message': "start function"
        })
        scheduled_pending_revocation_sweeper_subtask.delay(pending_revocation_autodebet.id)


@task(queue='repayment_low')
def scheduled_pending_revocation_sweeper_subtask(pending_autodebet_id):
    autodebet_account = AutodebetAccount.objects.get(pk=pending_autodebet_id)
    account = autodebet_account.account
    application = account.last_application
    customer_id_merchant = str(application.application_xid)
    bca_autodebet_client = get_bca_autodebet_client(account)
    data, error_message = bca_autodebet_client.send_request(
        "get", "/account-authorization/inquiry/%s" % customer_id_merchant, {},
        extra_headers={"customer_id_merchant": customer_id_merchant}
    )
    request_id = autodebet_account.request_id
    active = None
    if data and 'skpr_active' in data:
        active = next(
            (skpr for skpr in data['skpr_active'] if skpr['skpr_id'] == request_id[1:]), None)
        if active:
            _, error_message_delete = bca_autodebet_client.send_request(
                "delete", "/account-authorization/customer/%s/account-number/%s" %
                (customer_id_merchant, autodebet_account.db_account_no), {})
            if error_message_delete:
                logger.info({
                    'action': 'juloserver.autodebet.tasks.\
                        scheduled_pending_revocation_sweeper_subtask.send_request',
                    'autodebet_account_id': pending_autodebet_id,
                    'message': error_message_delete
                })
    logger.info({
        'action': 'juloserver.autodebet.tasks.scheduled_pending_revocation_sweeper_subtask',
        'autodebet_account_id': pending_autodebet_id,
        'active': active,
        'message': error_message
    })
    if error_message == 'Data pelanggan tidak ditemukan' or not active:
        autodebet_account.update_safely(
            deleted_success_ts=timezone.localtime(timezone.now()),
            is_deleted_autodebet=True,
            is_use_autodebet=False,
            status=AutodebetStatuses.REVOKED
        )


@task(queue='repayment_low')
def scheduled_inquiry_account_registration():
    # right now only implemented for BCA
    vendor = VendorConst.BCA

    # prevent race condition with realtime retry mechanism
    an_hour_before = timezone.localtime(timezone.now()) - timedelta(hours=1)

    pending_autodebets = AutodebetAccount.objects.filter(
        cdate__lte=an_hour_before,
        vendor=vendor,
        is_use_autodebet=False,
        registration_ts__isnull=False,
        failed_ts__isnull=True).only('id', 'retry_count')

    for pending_autodebet in pending_autodebets:
        scheduled_inquiry_account_registration_subtask(
            pending_autodebet.id,
            pending_autodebet.retry_count
        )


@task(queue='repayment_low')
def scheduled_inquiry_account_registration_subtask(pending_autodebet_id, retry_count):
    inquiry_account_registration(pending_autodebet_id, retry_count)


@task(queue='repayment_high')
def call_retry_mechanism_task(account_payment_id, account_payment_ids):
    if account_payment_id not in account_payment_ids:
        return

    account_payment = AccountPayment.objects.get(pk=account_payment_id)
    retry_count = account_payment.autodebet_retry_count

    is_valid, countdown_seconds = retry_autodebet_bri_validation(retry_count)

    if not is_valid:
        return

    create_debit_payment_process_task.apply_async(
        (account_payment_ids,),
        countdown=countdown_seconds, queue='normal', routing_key='normal'
    )


@task(queue='repayment_high')
def create_debit_payment_process_task(account_payment_ids):
    account_payments = AccountPayment.objects.filter(
        pk__in=account_payment_ids).order_by('due_date')
    account_payment_id = create_debit_payment_process_bri(account_payments)
    if not account_payment_id:
        return

    account_payment = AccountPayment.objects.get(pk=account_payment_id)
    account_payment.autodebet_retry_count += 1
    account_payment.save()
    call_retry_mechanism_task.delay(account_payment_id, account_payment_ids)


@task(queue='repayment_high')
def collect_gopay_autodebet_account_collections_task():
    slack_bot_client = get_slack_bot_client()
    slack_messages = "Create subscription started"
    if settings.ENVIRONMENT != 'prod':
        slack_messages = (
            "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_messages
        )
    slack_bot_client.api_call(
        "chat.postMessage", channel="#gopay-autodebit-alert", text=slack_messages
    )

    if not is_autodebet_gopay_feature_active():
        return

    today_date = timezone.localtime(timezone.now()).date()
    dpd_start, dpd_end = get_autodebet_dpd_deduction(vendor=AutodebetVendorConst.GOPAY)
    start_date = today_date - timedelta(days=dpd_end)
    end_date = today_date - timedelta(days=dpd_start)

    for autodebet_account in get_active_autodebet_gopay_account():
        try:
            account = autodebet_account.account
            account_payment = (
                account.accountpayment_set.not_paid_active()
                .filter(due_date__lte=end_date, due_date__gte=start_date)
                .order_by('due_date')
                .last()
            )
            logger.info(
                {
                    "action": "juloserver.autodebet.tasks."
                    "collect_gopay_autodebet_account_collections_task",
                    "autodebet_account_id": autodebet_account.id,
                    "account_payment_id": account_payment.id if account_payment else "",
                }
            )
            if account_payment:
                create_subscription_payment_process_gopay(account_payment)
        except Exception as e:
            account = autodebet_account.account
            account_payment = (
                account.accountpayment_set.not_paid_active()
                .filter(due_date__lte=end_date, due_date__gte=start_date)
                .order_by('due_date')
                .last()
            )
            if account_payment:
                GopayAutodebetSubscriptionRetry.objects.create(
                    account_payment_id=account_payment.id, error=str(e)
                )
            logger.error(
                {
                    "action": "juloserver.autodebet.tasks."
                    "collect_gopay_autodebet_account_collections_task",
                    "error": str(e),
                    "autodebet_account_id": autodebet_account.id,
                }
            )
            sentry.captureException()
            continue


@task(queue='repayment_high')
def send_slack_notify_autodebet_gopay_failed_subscription_and_deduction(
        account_id, account_payment_id, error_message, subscription_id=None):
    account = Account.objects.filter(pk=account_id).last()
    application_id = account.last_application.id
    slack_messages = "Application ID - {app_id}\n" \
        "Account Payment ID - {acc_payment_id}\n" \
        "Subscription ID - {sub_id}\n" \
        "Reason - {error_msg}".format(
            app_id=str(application_id),
            acc_payment_id=account_payment_id,
            sub_id=subscription_id,
            error_msg=str(error_message),
        )
    if settings.ENVIRONMENT != 'prod':
        slack_messages = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + \
            slack_messages

    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage", channel="#gopay-autodebit-alert", text=slack_messages
    )


@task(queue='repayment_low')
def send_pn_autodebet_insufficient_balance_turn_off(customer_id, vendor):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        logger.warning({
            "action": "juloserver.autodebet.services.task_services"
                      ".send_pn_adbca_insufficient_balance_turn_off",
            "message": "customer not found",
            "customer_id": customer_id
        })
        return
    julo_pn_client = get_julo_pn_client()

    julo_pn_client.pn_autodebet_insufficient_balance_turn_off(customer, vendor)


@task(queue='repayment_high')
def send_pn_autodebet_payment_method_disabled(
        feature_name, event_type, start_date_time, end_date_time):
    vendor = feature_name.split('_')[-1].upper()
    logger.info({
        "action": "juloserver.autodebet.task.send_pn_autodebet_payment_method_disabled",
        "message": 'autodebet disable pn begin'
    })
    for autodebet_account in get_active_autodebet_account([vendor]):
        customer = autodebet_account.account.customer
        if not customer:
            logger.warning({
                "action": "juloserver.autodebet.services.task"
                          ".send_pn_autodebet_disable_turned_on",
                "message": "customer not found",
                "account_id": autodebet_account.account.id
            })
            continue
        send_event_autodebet_payment_method_disabled(
            customer,
            vendor,
            event_type,
            start_date_time,
            end_date_time
        )


@task(queue='repayment_high')
def collect_and_update_gopay_autodebet_account_subscription_task():
    if not is_autodebet_gopay_feature_active():
        return

    if is_autodebet_feature_disable(VendorConst.GOPAY):
        logger.info({
            "action": "juloserver.autodebet.task"
                      ".collect_and_update_gopay_autodebet_account_subscription_task",
            "message": 'gopay autodebet disabled is turned on'
        })
        return

    today_date = timezone.localtime(timezone.now()).date()
    gopay_autodebet_transactions = GopayAutodebetTransaction.objects.filter(
        is_active=True,
        cdate__date=today_date - timedelta(days=1),
        status=None
    )

    if gopay_autodebet_transactions:
        for gopay_autodebet_transaction in gopay_autodebet_transactions.iterator():
            account_payment = gopay_autodebet_transaction.account_payment
            is_autodebet_active = AutodebetAccount.objects.filter(
                is_use_autodebet=True,
                vendor=AutodebetVendorConst.GOPAY,
                account=account_payment.account
            ).exists()

            if not is_autodebet_active:
                continue

            gopay_account_link = gopay_autodebet_transaction.gopay_account
            if not gopay_account_link or \
                    gopay_account_link.status != GopayAccountStatusConst.ENABLED:
                logger.warning(
                    {
                        'action': 'juloserver.autodebet.task'
                                  '.collect_and_update_gopay_autodebet_account_subscription_task',
                        'account_id': account_payment.account.id,
                        'error': 'Account GoPay Anda belum terhubung/tidak terdaftar',
                    }
                )
                continue

            result = check_gopay_wallet_token_valid(account_payment.account)
            if not result:
                logger.error(
                    {
                        'action': 'juloserver.autodebet.task'
                                  '.collect_and_update_gopay_autodebet_account_subscription_task',
                        'account_id': account_payment.account.id,
                        'error': 'GopayAccountLinkStatus not found',
                    }
                )
                continue

            is_valid = result[0]
            token = result[1]
            if not is_valid:
                update_gopay_wallet_token(account_payment.account, token)

            # Fetch and update subscripiton due_amount based on customer balance
            customer_balance = get_gopay_wallet_customer_balance(gopay_account_link.pay_account_id)
            if customer_balance is None:
                logger.error(
                    {
                        'action': 'juloserver.autodebet.task'
                                  '.collect_and_update_gopay_autodebet_account_subscription_task',
                        'account_id': account_payment.account.id,
                        'error': 'Gopay wallet customer balance not found',
                    }
                )
                continue
            update_gopay_wallet_customer_balance(account_payment.account, customer_balance)

            amount = gopay_autodebet_transaction.amount

            if account_payment.dpd > 0:
                if customer_balance < 10000:
                    continue

            if customer_balance > 1 and amount > customer_balance:
                amount = customer_balance

            now = timezone.localtime(timezone.now()) + timedelta(minutes=5)
            next_execution_at = now.strftime("%Y-%m-%d %H:%M:%S %z")

            request_data = {
                'name': gopay_autodebet_transaction.name,
                'amount': amount,
                'currency': 'IDR',
                'token': token,
                'schedule': {
                    'next_execution_at': next_execution_at
                }
            }

            gopay_client = get_gopay_client()
            try:
                gopay_client.update_subscription_gopay_autodebet(
                    gopay_autodebet_transaction,
                    request_data
                )
            except GopayError as error:
                logger.error(
                    {
                        'action': 'juloserver.autodebet.tasks'
                                  '.collect_and_update_gopay_autodebet_account_subscription_task',
                        'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id,
                        'error': error,
                    }
                )
                continue

            logger.info(
                {
                    'action': 'juloserver.autodebet.tasks'
                              '.collect_and_update_gopay_autodebet_account_subscription_task',
                    'gopay_autodebet_transaction_id': gopay_autodebet_transaction.id,
                    'request_data': request_data,
                    'message': 'updating the subscription amount based on customer balance',
                }
            )


@task(queue='repayment_high')
def send_pn_gopay_autodebet_partial_repayment(customer_id, paid_amount):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        logger.warning({
            "action": "juloserver.autodebet.services.tasks"
                      ".send_pn_gopay_autodebet_partial_repayment",
            "message": "customer not found",
            "customer_id": customer_id
        })
        return
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_gopay_autodebet_partial_repayment(customer, paid_amount)


@task(queue='repayment_high')
def change_benefit_value(cashback_value):
    autodebet_benefit_values = AutodebetBenefit.objects.values_list('id', flat=True)
    batch_size = 100

    for start in range(0, len(autodebet_benefit_values), batch_size):
        end = start + batch_size
        benefit_ids = autodebet_benefit_values[start:end]
        AutodebetBenefit.objects.filter(id__in=benefit_ids, benefit_type='cashback').update(
            benefit_value=cashback_value
        )


@task(queue='repayment_high')
def collect_mandiri_autodebet_account_maximum_limit_collections_task():
    if not is_autodebet_mandiri_feature_active():
        return

    if is_autodebet_feature_disable(VendorConst.MANDIRI):
        logger.info({
            "action": "juloserver.autodebet.tasks"
                      ".collect_mandiri_autodebet_account_maximum_limit_collections_task",
            "message": "autodebet mandiri is been disabled",
        })
        return

    mandiri_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = mandiri_max_limit_setting.parameters.get('maximum_amount')
    deduction_dpd_list = mandiri_max_limit_setting.parameters.get('deduction_dpd')
    if not maximum_amount or not deduction_dpd_list:
        logger.warning({
            "action": "juloserver.autodebet.tasks"
                      ".collect_mandiri_autodebet_account_maximum_limit_collections_task",
            "message": "maximum_amount or deduction_dpd not found",
        })
        return
    today_date = timezone.localtime(timezone.now()).date()
    for autodebet_account in get_active_autodebet_account([VendorConst.MANDIRI]):
        if autodebet_account.activation_ts \
                and today_date == timezone.localtime(autodebet_account.activation_ts).date():
            logger.info({
                'action': 'is_account_eligible_for_fund_collection',
                'autodebet_account': autodebet_account.id,
                'message': 'Exclude fund collection for users that have due date = '
                        'registered date'})
            continue
        account = autodebet_account.account
        for dpd in deduction_dpd_list:
            due_date = today_date - timedelta(days=dpd)
            is_account_payment = account.accountpayment_set.not_paid_active()\
                .filter(due_date=due_date).exists()

            if is_account_payment:
                filter_ = {
                    "due_date__lte": due_date,
                }
                account_payments = account.accountpayment_set.not_paid_active()\
                    .filter(**filter_).order_by('due_date')
                due_amount = 0
                for account_payment in account_payments.iterator():
                    if today_date.day != account_payment.due_date.day:
                        due_amount += account_payment.due_amount

                if due_amount > maximum_amount:
                    create_debit_payment_process_mandiriv2(account_payments)


@task(queue='repayment_low')
def send_slack_alert_mandiri_purchase_notification(
    error_message: str,
    original_partner_reference_no: Optional[str] = None,
    account_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    application_id: Optional[int] = None,
) -> None:
    slack_message = "Application ID - {application_id}\n" \
                    "Account ID - {account_id}\n" \
                    "Account Payment ID - {account_payment_id}\n" \
                    "Original Partner Reference No - {original_partner_reference_no}\n" \
                    "Reason - {error_msg}". \
        format(
            application_id=str(application_id),
            account_id=str(account_id),
            account_payment_id=account_payment_id,
            original_partner_reference_no=original_partner_reference_no,
            error_msg=str(error_message),
        )
    channel_name = get_channel_name_slack_autodebet_mandiri_deduction()
    get_slack_bot_client().api_call(
        "chat.postMessage", channel=channel_name, text=slack_message
    )


@task(queue='repayment_low')
def store_autodebet_api_log(
    request_data: bytes,
    response_data: bytes,
    http_status_code: int,
    url: str,
    vendor: str,
    account_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    AutodebetAPILog.objects.create(
        vendor=vendor,
        http_status_code=http_status_code,
        request_type=url.upper(),
        request=convert_bytes_to_dict_or_string(request_data),
        response=convert_bytes_to_dict_or_string(response_data),
        account_id=account_id,
        account_payment_id=account_payment_id,
        error_message=error_message,
    )


@task(queue='repayment_low')
def scheduled_pending_registration_sweeper_mandiri():
    vendor = VendorConst.MANDIRI
    current_ts = timezone.localtime(timezone.now())
    pending_registration_autodebets = AutodebetAccount.objects.filter(
        vendor=vendor,
        is_use_autodebet=False,
        status=AutodebetStatuses.PENDING_REGISTRATION
    )

    for pending_registration_autodebet in pending_registration_autodebets:
        logger.info({
            'action': 'juloserver.autodebet.tasks.'
                      'scheduled_pending_registration_sweeper_mandiri',
            'autodebet_account_id': pending_registration_autodebet.id,
            'message': "start function"
        })
        pending_registration_autodebet.update_safely(
            failed_ts=current_ts,
            failed_reason="Force failed by JULO system",
            is_deleted_autodebet=True,
            status=AutodebetStatuses.FAILED_REGISTRATION,
        )


@task(queue='repayment_low')
def scheduled_pending_registration_sweeper_bni():
    vendor = VendorConst.BNI
    current_ts = timezone.localtime(timezone.now())
    safe_window_time = timezone.localtime(
        timezone.now() - timedelta(seconds=SWEEPING_SAFE_INTERVAL)
    )
    pending_registration_autodebets = AutodebetAccount.objects.filter(
        vendor=vendor,
        is_use_autodebet=False,
        status=AutodebetStatuses.PENDING_REGISTRATION,
        cdate__lte=safe_window_time,
    )

    for pending_registration_autodebet in pending_registration_autodebets:
        logger.info(
            {
                'action': 'juloserver.autodebet.tasks.'
                'scheduled_pending_registration_sweeper_bni',
                'autodebet_account_id': pending_registration_autodebet.id,
                'message': "start function",
            }
        )
        pending_registration_autodebet.update_safely(
            failed_ts=current_ts,
            failed_reason="Force failed by JULO system",
            is_deleted_autodebet=True,
            status=AutodebetStatuses.FAILED_REGISTRATION,
        )


@task(queue='repayment_normal')
def update_gopay_autodebet_account_subscription(account_id):
    logger.info(
        {
            'action': 'juloserver.autodebet.services.task_services.'
            'update_gopay_autodebet_account_subscription',
            'message': 'update gopay autodebet subscription {} account'.format(account_id),
        }
    )
    account = Account.objects.get(id=account_id)
    if not account:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'update_gopay_autodebet_account_subscription',
                'account_id': account.id,
                'error': 'No account found for this {} account'.format(account_id),
            }
        )
        return

    gopay_autodebet_transaction = GopayAutodebetTransaction.objects.filter(
        customer=account.customer).last()

    if not gopay_autodebet_transaction:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'update_gopay_autodebet_account_subscription',
                'account_id': account.id,
                'error': 'No subscription found for this {} account'.format(account.id),
            }
        )
        return

    if not gopay_autodebet_transaction.is_active:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'update_gopay_autodebet_account_subscription',
                'account_id': account.id,
                'error': 'subscription is not active',
            }
        )
        return

    due_amount = get_due_amount_for_gopay_autodebet_deduction(account)
    gopay_client = get_gopay_client()
    if not due_amount:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'update_gopay_autodebet_account_subscription',
                'account_id': account.id,
                'error': 'No payment due today for this {} account'.format(account.id),
            }
        )
        res_data = gopay_client.disable_subscription_gopay_autodebet(gopay_autodebet_transaction)
        if res_data['status_message'] == "Subscription is updated.":
            gopay_autodebet_transaction.update_safely(is_active=False)
        return

    if due_amount == gopay_autodebet_transaction.amount:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'update_gopay_autodebet_account_subscription',
                'account_id': account.id,
                'error': 'No changes in the due_amount for this'
                ' subscription_id: {}'.format(gopay_autodebet_transaction.subscription_id),
            }
        )
        return

    req_data = {
        "name": gopay_autodebet_transaction.name,
        "amount": str(due_amount),
        "currency": "IDR",
        "token": gopay_autodebet_transaction.gopay_account.token
    }

    res_data = gopay_client.update_subscription_gopay_autodebet(
        gopay_autodebet_transaction,
        req_data
    )

    if res_data['status_message'] == "Subscription is updated.":
        gopay_autodebet_transaction.update_safely(amount=due_amount)


@task(queue='repayment_high')
def inquiry_payment_autodebet_bri_scheduler():
    inquiry_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY, is_active=True
    )

    if not inquiry_fs:
        return

    # 840(minutes) is 10:00 to 00:00
    limit = int(840 / inquiry_fs.parameters[AutodebetVendorConst.BRI]['minutes'])
    for multiplier in range(limit):
        inquiry_payment_autodebet_bri.apply_async(
            countdown=(
                (multiplier * inquiry_fs.parameters[AutodebetVendorConst.BRI]['minutes']) * 60
            )
        )
    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.inquiry_payment_autodebet_bri_scheduler',
            'limit': limit,
            'message': "start parent task",
        }
    )


@task(queue='repayment_high')
def inquiry_payment_autodebet_bri():
    autodebet_bri_transactions = AutodebetBRITransaction.objects.filter(
        status=BRITransactionStatus.CALLBACK_PENDING
    )

    for autodebet_bri_transaction in autodebet_bri_transactions.iterator():
        bri_autodebet_client = get_bri_autodebet_client(
            autodebet_bri_transaction.autodebet_account.account
        )
        bri_transaction_id = autodebet_bri_transaction.bri_transaction_id
        payback_transaction = PaybackTransaction.objects.get_or_none(
            transaction_id=bri_transaction_id, is_processed=True
        )

        with transaction.atomic():
            if payback_transaction:
                autodebet_bri_transaction.update_safely(
                    status=BRITransactionStatus.SUCCESS,
                    updated_ts=timezone.localtime(timezone.now()),
                )
                continue

            result, error = bri_autodebet_client.inquiry_bri_transaction(bri_transaction_id)

            if error:
                if 'status' not in result:
                    update_autodebet_bri_transaction_failed(
                        result['error_code'], autodebet_bri_transaction
                    )
                logger.error(
                    {
                        'action': 'juloserver.autodebet.tasks.inquiry_payment_autodebet_bri',
                        'error': error,
                        'autodebet_bri_transaction_id': autodebet_bri_transaction.id,
                    }
                )
                continue

            if result['status'] == BRITransactionStatus.COMPLETED:
                error = process_fund_collection(
                    autodebet_bri_transaction.account_payment,
                    AutodebetVendorConst.BRI,
                    result['amount'],
                    bri_transaction_id,
                )
                if error:
                    continue

                autodebet_bri_transaction.update_safely(
                    status=BRITransactionStatus.SUCCESS,
                    updated_ts=timezone.localtime(timezone.now()),
                )
            elif result['status'] == BRITransactionStatus.PENDING:
                continue
            else:
                update_autodebet_bri_transaction_failed(
                    result['failure_code'], autodebet_bri_transaction
                )

    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.inquiry_payment_autodebet_bri',
            'message': "start child task",
        }
    )


@task(queue='repayment_low')
def reactivate_autodebet_validation(app_version, customer_id):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        logger.warning(
            {
                "action": "juloserver.action_log.autodebet.tasks"
                ".reactivate_autodebet_validation",
                "message": "customer not found",
                "customer_id": customer_id,
            }
        )
        return

    account = customer.account_set.last()
    autodebet_account = (
        AutodebetAccount.objects.filter(
            account=account,
            is_use_autodebet=True,
        )
        .order_by('cdate')
        .last()
    )

    if not autodebet_account:
        logger.warning(
            {
                "action": "juloserver.action_log.autodebet.tasks"
                ".reactivate_autodebet_validation",
                "message": "cannot detect reactivation vendor",
                "customer_id": customer_id,
            }
        )
        return

    vendor = autodebet_account.vendor
    minimum_version = REACTIVATION_VERSION_VENDOR.get(vendor)

    if minimum_version and semver.match(app_version, "<%s" % minimum_version):
        existing_customer_app_action = CustomerAppAction.objects.filter(
            customer_id=customer.id, action='warning_upgrade', is_completed=False
        )
        if not existing_customer_app_action.exists():
            CustomerAppAction.objects.create(
                customer_id=customer.id, action='warning_upgrade', is_completed=False
            )

        device_query = customer.device_set.all()
        gcm_reg_id = device_query.order_by('cdate').values_list('gcm_reg_id', flat=True).last()

        julo_pn_client = get_julo_pn_client()
        julo_pn_client.unable_reactivate_autodebet(gcm_reg_id)


@task(queue='repayment_high')
def collect_bni_autodebet_account_maximum_limit_collections_task():
    if not is_autodebet_bni_feature_active():
        return

    if is_autodebet_feature_disable(VendorConst.BNI):
        logger.info(
            {
                "action": "juloserver.autodebet.tasks"
                ".collect_bni_autodebet_account_maximum_limit_collections_task",
                "message": "autodebet bni is been disabled",
            }
        )
        return

    bni_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BNI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = bni_max_limit_setting.parameters.get('maximum_amount')
    deduction_dpd_list = bni_max_limit_setting.parameters.get('deduction_dpd')
    if not maximum_amount or not deduction_dpd_list:
        logger.warning(
            {
                "action": "juloserver.autodebet.tasks"
                ".collect_bni_autodebet_account_maximum_limit_collections_task",
                "message": "maximum_amount or deduction_dpd not found",
            }
        )
        return
    today_date = timezone.localtime(timezone.now()).date()
    for autodebet_account in get_active_autodebet_account([VendorConst.BNI]):
        if (
            autodebet_account.activation_ts
            and today_date == timezone.localtime(autodebet_account.activation_ts).date()
        ):
            logger.info(
                {
                    'action': 'is_account_eligible_for_fund_collection',
                    'autodebet_account': autodebet_account.id,
                    'message': 'Exclude fund collection for users that have due date = '
                    'registered date',
                }
            )
            continue
        account = autodebet_account.account
        for dpd in deduction_dpd_list:
            due_date = today_date - timedelta(days=dpd)
            is_account_payment = (
                account.accountpayment_set.not_paid_active().filter(due_date=due_date).exists()
            )

            if is_account_payment:
                filter_ = {
                    "due_date__lte": due_date,
                }
                account_payments = (
                    account.accountpayment_set.not_paid_active()
                    .filter(**filter_)
                    .order_by('due_date')
                )
                due_amount = 0
                for account_payment in account_payments.iterator():
                    if today_date.day != account_payment.due_date.day:
                        due_amount += account_payment.due_amount

                if due_amount > maximum_amount:
                    create_debit_payment_process_bni(account_payments)


@task(queue='repayment_high')
def send_slack_notify_autodebet_bni_failed_deduction(
    account_id, account_payment_id, external_id, error_message
):
    account = Account.objects.filter(pk=account_id).last()
    application_id = account.last_application.id
    slack_messages = (
        "Application ID - {app_id}\n"
        "Account Payment ID - {acc_payment_id}\n"
        "External ID - {sub_id}\n"
        "Reason - {error_msg}".format(
            app_id=str(application_id),
            acc_payment_id=account_payment_id,
            sub_id=external_id,
            error_msg=str(error_message),
        )
    )
    if settings.ENVIRONMENT != 'prod':
        slack_messages = (
            "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_messages
        )

    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage", channel="#bni-autodebet-alert", text=slack_messages
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_bni_scheduler():
    inquiry_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY, is_active=True
    )

    if not inquiry_fs:
        return

    # 840(minutes) is 10:00 to 00:00
    interval_minutes = inquiry_fs.parameters[AutodebetVendorConst.BNI]['minutes']
    limit = int(840 / interval_minutes)
    for multiplier in range(limit):
        reinquiry_payment_autodebet_bni.apply_async(
            countdown=((multiplier * interval_minutes) * 60)
        )
    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_bni_scheduler',
            'limit': limit,
            'message': "start parent task",
        }
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_bni():
    autodebet_bni_transactions = AutodebetBniTransaction.objects.filter(
        status=AutodebetBNIPaymentResultStatusConst.PROCESSING
    )

    for autodebet_bni_transaction in autodebet_bni_transactions.iterator():
        with transaction.atomic():
            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=autodebet_bni_transaction.x_external_id,
                is_processed=True,
            )
            if payback_transaction.exists():
                autodebet_bni_transaction.update_safely(
                    status=AutodebetBNIPaymentResultStatusConst.SUCCESS,
                )
                continue

            account = autodebet_bni_transaction.autodebet_bni_account.autodebet_account.account
            bni_autodebet_client = get_bni_autodebet_client(
                autodebet_bni_transaction.autodebet_bni_account.autodebet_account.account
            )

            result, error = bni_autodebet_client.inquiry_autodebet_status(
                autodebet_bni_transaction.x_external_id
            )
            if error:
                logger.error(
                    {
                        'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_bni',
                        'error': error,
                        'autodebet_bri_transaction_id': autodebet_bni_transaction.id,
                    }
                )
                continue

            payment_result = result.get('additionalInfo', {}).get('paymentResult')
            if not payment_result:
                continue
            payment_result = payment_result.lower()

            if payment_result == AutodebetBNIPaymentResultStatusConst.SUCCESS:
                today = timezone.localtime(timezone.now())
                vendor = AutodebetVendorConst.BNI
                payback_transaction, _ = PaybackTransaction.objects.get_or_create(
                    customer=account.customer,
                    payback_service='autodebet',
                    status_desc='Autodebet {}'.format(vendor),
                    transaction_id=autodebet_bni_transaction.x_external_id,
                    amount=autodebet_bni_transaction.amount,
                    account=account,
                    payment_method=get_autodebet_payment_method(
                        account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
                    ),
                    defaults={"is_processed": False, "transaction_date": today},
                )
                if payback_transaction.is_processed:
                    continue
                process_bni_autodebet_repayment(
                    payback_transaction, autodebet_bni_transaction, today
                )
            elif payment_result == AutodebetBNIPaymentResultStatusConst.FAILED:
                update_autodebet_bni_transaction_failed(payment_result, autodebet_bni_transaction)
            else:
                continue

    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.inquiry_payment_autodebet_bri',
            'message': "start child task",
        }
    )


@task(queue='repayment_low')
def suspend_autodebet_mandiri_insufficient_balance(autodebet_account_id):
    autodebet_account = AutodebetAccount.objects.filter(pk=autodebet_account_id).last()
    suspend_autodebet_insufficient_balance(autodebet_account, autodebet_account.vendor)


@task(queue='repayment_low')
def send_pn_idfy_unfinished_autodebet_activation(customer_id, vendor):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        logger.warning(
            {
                "action": "juloserver.autodebet.services.tasks"
                ".send_pn_idfy_unfinished_autodebet_activation",
                "message": "customer not found",
                "customer_id": customer_id,
            }
        )
        return

    account = Account.objects.get_or_none(customer=customer)
    if not account:
        logger.warning(
            {
                "action": "juloserver.autodebet.services.tasks"
                ".send_pn_idfy_unfinished_autodebet_activation",
                "message": "account not found",
                "customer_id": customer_id,
            }
        )
        return

    # CANCEL PN IF IDFY AUTODEBET NOT VALID
    if not is_idfy_autodebet_valid(account):
        return

    # SEND PN
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_idfy_unfinished_autodebet_activation(customer, vendor)

    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.send_pn_idfy_unfinished_autodebet_activation',
            'customer_id': customer_id,
            'vendor': vendor,
            'message': "send pn to customer",
        }
    )


@task(queue='repayment_high')
def collect_dana_autodebet_account_collection_task():
    if not is_autodebet_dana_feature_active():
        return

    if is_autodebet_feature_disable(VendorConst.DANA):
        logger.info(
            {
                "action": "juloserver.autodebet.tasks"
                ".collect_dana_autodebet_account_collection_task",
                "message": "autodebet dana has been disabled",
            }
        )
        return

    # Calculate deduction date inclusion
    today_date = timezone.localtime(timezone.now()).date()
    dpd_start, dpd_end = get_autodebet_dpd_deduction(vendor=AutodebetVendorConst.DANA)
    start_date = today_date - timedelta(days=dpd_end)  # plus minus defined by dpd_end
    end_date = today_date - timedelta(days=dpd_start)  # plus minus defined by dpd_start

    for autodebet_account in get_active_autodebet_account([AutodebetVendorConst.DANA]):
        account = autodebet_account.account
        account_payment = (
            account.accountpayment_set.not_paid_active()
            .filter(due_date__lte=end_date, due_date__gte=start_date)
            .order_by("due_date")
            .last()
        )

        if not account_payment:
            continue

        account_payment_ids = (
            account.accountpayment_set.not_paid_active()
            .filter(due_date__lte=account_payment.due_date)
            .order_by('due_date')
            .values_list('id', flat=True)
        )

        if account_payment_ids:
            create_debit_payment_process_dana(account_payment_ids, account)

        logger.info(
            {
                'action': 'juloserver.autodebet.tasks.'
                'collect_dana_autodebet_account_collection_task',
                'message': "Collect DANA autodebet due account payment",
                'autodebet_account': autodebet_account.id,
                'account_payment_ids': account_payment_ids,
            }
        )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_dana_scheduler():
    inquiry_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY, is_active=True
    )

    if not inquiry_fs:
        return

    # 840(minutes) is 10:00 to 00:00
    interval_minutes = inquiry_fs.parameters[AutodebetVendorConst.DANA]['minutes']
    limit = int(840 / interval_minutes)
    for multiplier in range(limit):
        reinquiry_payment_autodebet_dana.apply_async(
            countdown=((multiplier * interval_minutes) * 60)
        )
    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_dana_scheduler',
            'limit': limit,
            'message': "start parent task",
        }
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_dana():
    autodebet_dana_transactions = AutodebetDanaTransaction.objects.filter(
        status=AutodebetDANAPaymentResultStatusConst.PENDING,
    )

    for autodebet_dana_transaction in autodebet_dana_transactions.iterator():
        with transaction.atomic():
            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=autodebet_dana_transaction.original_partner_reference_no,
                is_processed=True,
            )

            if payback_transaction.exists():
                autodebet_dana_transaction.update_safely(
                    status=AutodebetDANAPaymentResultStatusConst.SUCCESS,
                )
                continue

            account_payment = autodebet_dana_transaction.account_payment
            account = account_payment.account
            customer = account.customer
            customer_xid = customer.customer_xid
            if not customer_xid:
                customer_xid = customer.generated_customer_xid
            dana_client = get_dana_autodebet_client(
                account=account,
                account_payment=account_payment,
            )
            response, error = dana_client.inquiry_autodebet_status(
                customer_xid,
                autodebet_dana_transaction.original_partner_reference_no,
                autodebet_dana_transaction.original_reference_no,
            )

            response_code = response.get('responseCode', '')
            if error and response_code != AutodebetDanaResponseCodeConst.TRANSACTION_NOT_FOUND:
                logger.error(
                    {
                        'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_dana',
                        'error': error,
                        'autodebet_dana_transaction_id': autodebet_dana_transaction.id,
                    }
                )
                continue

            vendor = AutodebetVendorConst.DANA
            latestTransactionStatus = response.get('latestTransactionStatus', '')
            amount = int(float(response.get('amount', {}).get('value', '0')))
            if latestTransactionStatus == AutodebetDANATransactionStatusCodeCons.SUCCESS:
                today = timezone.localtime(timezone.now())
                payback_transaction, _ = PaybackTransaction.objects.get_or_create(
                    customer=customer,
                    payback_service='autodebet',
                    status_desc='Autodebet {}'.format(vendor),
                    transaction_id=autodebet_dana_transaction.original_partner_reference_no,
                    amount=amount,
                    account=account,
                    payment_method=get_autodebet_payment_method(
                        account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
                    ),
                    defaults={"is_processed": False, "transaction_date": today},
                )
                if payback_transaction.is_processed:
                    continue

                j1_refinancing_activation(
                    payback_transaction, account_payment, payback_transaction.transaction_date
                )
                process_j1_waiver_before_payment(
                    account_payment, amount, payback_transaction.transaction_date
                )
                account_trx = process_repayment_trx(
                    payback_transaction,
                    note='payment with autodebet {} amount {}'.format(vendor, amount),
                )
                autodebet_dana_transaction.update_safely(
                    status=AutodebetDANAPaymentResultStatusConst.SUCCESS,
                    paid_amount=amount,
                    status_desc=None,
                )

                # GIVE BENEFIT
                benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
                if (
                    benefit
                    and not autodebet_dana_transaction.is_partial
                    and autodebet_dana_transaction.is_eligible_benefit
                ):
                    if is_eligible_to_get_benefit(account):
                        give_benefit(benefit, account, account_payment)

                execute_after_transaction_safely(
                    lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
                )
            elif (
                latestTransactionStatus
                in (
                    AutodebetDANATransactionStatusCodeCons.CANCELLED,
                    AutodebetDANATransactionStatusCodeCons.NOT_FOUND,
                )
                or response_code == AutodebetDanaResponseCodeConst.TRANSACTION_NOT_FOUND
            ):
                send_event_autodebit_failed_deduction_task.delay(
                    account_payment.id, customer.id, vendor
                )
                autodebet_dana_transaction.update_safely(
                    status=AutodebetDANAPaymentResultStatusConst.FAILED,
                )

                if autodebet_dana_transaction.status_desc == DanaErrorCode.INSUFFICIENT_FUND:
                    autodebet_account = account.autodebetaccount_set.filter(
                        is_use_autodebet=True
                    ).last()
                    suspend_autodebet_insufficient_balance(autodebet_account, VendorConst.DANA)

            logger.info(
                {
                    'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_dana',
                    'autodebet_dana_transaction_id': autodebet_dana_transaction.id,
                    'latest_transaction_status': latestTransactionStatus,
                }
            )

    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_dana',
            'message': "end child task",
        }
    )


@task(queue='repayment_low')
def send_slack_alert_dana_failed_subscription_and_deduction(
    error_message: str,
    account_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    application_id: Optional[int] = None,
    original_partner_reference_no: Optional[str] = None,
) -> None:
    slack_messages = (
        "Application ID - {application_id}\n"
        "Account ID - {account_id}\n"
        "Account Payment ID - {account_payment_id}\n"
        "Original Partner Reference No - {original_partner_reference_no}\n"
        "Reason - {error_msg}".format(
            application_id=str(application_id),
            account_id=str(account_id),
            account_payment_id=account_payment_id,
            original_partner_reference_no=original_partner_reference_no,
            error_msg=str(error_message),
        )
    )

    if settings.ENVIRONMENT != 'prod':
        slack_messages = (
            "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_messages
        )

    send_slack_bot_message(channel="#dana-autodebit-alert", message=slack_messages)


@task(queue='repayment_low')
def send_slack_alert_ovo_failed_subscription_and_deduction_linking(
    error_message: str,
    topic: str = "",
    account_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    is_autodebet: Optional[bool] = None,
) -> None:
    slack_messages = (
        "{topic}\n"
        "Account ID - {account_id}\n"
        "Account Payment ID - {account_payment_id}\n"
        "Reason - {error_msg}".format(
            topic=topic,
            account_id=str(account_id),
            account_payment_id=account_payment_id,
            error_msg=str(error_message),
        )
    )

    if settings.ENVIRONMENT != 'prod':
        slack_messages = (
            "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_messages
        )

    slack_channel = "#ovolinking_alert" if not is_autodebet else "#ovo-autodebit-alert"
    send_slack_bot_message(channel=slack_channel, message=slack_messages)


@task(queue='repayment_high')
def collect_ovo_autodebet_account_collection_subtask(account_payment_ids, account):
    create_debit_payment_process_ovo(account_payment_ids, account)


@task(queue='repayment_high')
def collect_ovo_autodebet_account_collection_task():
    if not is_autodebet_ovo_feature_active():
        return

    if is_autodebet_feature_disable(VendorConst.OVO):
        logger.info(
            {
                "action": "juloserver.autodebet.tasks"
                ".collect_ovo_autodebet_account_collection_task",
                "message": "autodebet OVO has been disabled",
            }
        )
        return

    today_date = timezone.localtime(timezone.now()).date()

    for autodebet_account in get_active_autodebet_account([AutodebetVendorConst.OVO]):
        dpd_start, dpd_end = get_autodebet_dpd_deduction(vendor=AutodebetVendorConst.OVO)
        start_date = today_date - timedelta(days=dpd_end)  # plus minus defined by dpd_end
        end_date = today_date - timedelta(days=dpd_start)  # plus minus defined by dpd_start
        account = autodebet_account.account
        account_payment = (
            account.accountpayment_set.not_paid_active()
            .filter(due_date__lte=end_date, due_date__gte=start_date)
            .order_by("due_date")
            .last()
        )

        if not account_payment:
            continue

        account_payment_ids = (
            account.accountpayment_set.not_paid_active()
            .filter(due_date__lte=account_payment.due_date)
            .order_by('due_date')
            .values_list('id', flat=True)
        )

        if account_payment_ids:
            collect_ovo_autodebet_account_collection_subtask.delay(account_payment_ids, account)

        logger.info(
            {
                'action': 'juloserver.autodebet.tasks.'
                'collect_ovo_autodebet_account_collection_task',
                'message': "Collect OVO autodebet due account payment",
                'autodebet_account': autodebet_account.id,
                'account_payment_ids': account_payment_ids,
            }
        )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_ovo_scheduler():
    inquiry_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY, is_active=True
    )

    if not inquiry_fs:
        return

    # 840(minutes) is 10:00 to 00:00
    interval_minutes = inquiry_fs.parameters[AutodebetVendorConst.OVO]['minutes']
    limit = int(840 / interval_minutes)
    for multiplier in range(limit):
        reinquiry_payment_autodebet_ovo.apply_async(
            countdown=((multiplier * interval_minutes) * 60)
        )
    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo_scheduler',
            'limit': limit,
            'message': "start parent task",
        }
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_ovo():
    end_dt = timezone.localtime(timezone.now()) - timedelta(hours=1)
    autodebet_ovo_transactions = AutodebetOvoTransaction.objects.filter(
        status=AutodebetOVOPaymentResultStatusConst.PENDING,
        cdate__lte=end_dt,
        original_partner_reference_no__isnull=False,
    )

    for autodebet_ovo_transaction in autodebet_ovo_transactions.iterator():
        reinquiry_payment_autodebet_ovo_subtask.delay(
            autodebet_ovo_transaction.original_partner_reference_no
        )

    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo',
            'message': "end child task",
        }
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_ovo_subtask(original_partner_reference_no):
    autodebet_ovo_transaction = AutodebetOvoTransaction.objects.filter(
        status=AutodebetOVOPaymentResultStatusConst.PENDING,
        original_partner_reference_no=original_partner_reference_no,
    ).first()

    with transaction.atomic(), transaction.atomic(using='repayment_db'):
        payback_transaction = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                transaction_id=autodebet_ovo_transaction.original_partner_reference_no,
            )
            .last()
        )

        if not payback_transaction:
            return

        if payback_transaction.is_processed is True:
            with transaction.atomic(using='repayment_db'):
                autodebet_ovo_transaction.update_safely(
                    status=AutodebetOVOPaymentResultStatusConst.SUCCESS,
                )
                return

        account_payment = AccountPayment.objects.get_or_none(
            pk=autodebet_ovo_transaction.account_payment_id,
        )
        account = account_payment.account
        customer = account.customer
        customer_xid = customer.customer_xid
        if not customer_xid:
            customer_xid = customer.generated_customer_xid

        ovo_wallet_account = OvoWalletAccount.objects.filter(
            account_id=account.id, status=OvoWalletAccountStatusConst.ENABLED
        ).last()
        if not ovo_wallet_account:
            return

        doku_client = get_doku_snap_ovo_client(
            ovo_wallet_account=ovo_wallet_account,
            account=account,
            account_payment=account_payment,
            is_autodebet=True,
        )
        response, error = doku_client.ovo_inquiry_payment(
            autodebet_ovo_transaction.original_partner_reference_no,
            autodebet_ovo_transaction.amount,
            autodebet_ovo_transaction.original_reference_no,
        )

        response_code = response.get('responseCode', '')
        if error and response_code != AutodebetOVOResponseCodeConst.TRANSACTION_NOT_FOUND:
            logger.error(
                {
                    'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo',
                    'error': error,
                    'autodebet_ovo_transaction_id': autodebet_ovo_transaction.id,
                }
            )
            return

        vendor = AutodebetVendorConst.OVO
        latestTransactionStatus = response.get('latestTransactionStatus', '')
        amount = int(float(response.get('transAmount', {}).get('value', '0')))
        if latestTransactionStatus == AutodebetOVOTransactionStatusCodeCons.SUCCESS:
            j1_refinancing_activation(
                payback_transaction, account_payment, payback_transaction.transaction_date
            )
            process_j1_waiver_before_payment(
                account_payment, amount, payback_transaction.transaction_date
            )
            account_trx = process_repayment_trx(
                payback_transaction,
                note='payment with autodebet {} amount {}'.format(vendor, amount),
            )

            with transaction.atomic(using='repayment_db'):
                autodebet_ovo_transaction.update_safely(
                    status=AutodebetOVOPaymentResultStatusConst.SUCCESS,
                    paid_amount=amount,
                    status_desc=None,
                )

            # GIVE BENEFIT
            benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
            if (
                benefit
                and not autodebet_ovo_transaction.is_partial
                and autodebet_ovo_transaction.is_eligible_benefit
            ):
                if is_eligible_to_get_benefit(account):
                    give_benefit(benefit, account, account_payment)

            execute_after_transaction_safely(
                lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
            )
        elif latestTransactionStatus in (
            AutodebetOVOTransactionStatusCodeCons.CANCELLED,
            AutodebetOVOTransactionStatusCodeCons.FAILED,
            AutodebetOVOTransactionStatusCodeCons.NOT_FOUND,
        ) or response_code in (
            AutodebetOVOResponseCodeConst.TRANSACTION_NOT_FOUND,
            AutodebetOVOResponseCodeConst.FAILED_INSUFFICIENT_FUND,
        ):
            send_event_autodebit_failed_deduction_task.delay(
                account_payment.id, customer.id, vendor
            )
            with transaction.atomic(using='repayment_db'):
                autodebet_ovo_transaction.update_safely(
                    status=AutodebetOVOPaymentResultStatusConst.FAILED,
                )
            if (
                response.get('originalResponseCode', '')
                == AutodebetOVOResponseCodeConst.FAILED_INSUFFICIENT_FUND
            ):
                autodebet_account = get_existing_autodebet_account(
                    account, AutodebetVendorConst.OVO
                )
                suspend_autodebet_insufficient_balance(autodebet_account, AutodebetVendorConst.OVO)
        else:
            logger.error(
                {
                    'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo',
                    'autodebet_ovo_transaction_id': autodebet_ovo_transaction.id,
                    'latest_transaction_status': latestTransactionStatus,
                    'response': response,
                    'error': error,
                }
            )
            raise Exception('Unknown transaction status')

        logger.info(
            {
                'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo',
                'autodebet_ovo_transaction_id': autodebet_ovo_transaction.id,
                'latest_transaction_status': latestTransactionStatus,
            }
        )


@task(queue='repayment_low')
def send_slack_alert_ovo_failed_subscription_and_deduction(
    error_message: str,
    account_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    application_id: Optional[int] = None,
    original_partner_reference_no: Optional[str] = None,
) -> None:
    slack_messages = (
        "Application ID - {application_id}\n"
        "Account ID - {account_id}\n"
        "Account Payment ID - {account_payment_id}\n"
        "Original Partner Reference No - {original_partner_reference_no}\n"
        "Reason - {error_msg}".format(
            application_id=str(application_id),
            account_id=str(account_id),
            account_payment_id=account_payment_id,
            original_partner_reference_no=original_partner_reference_no,
            error_msg=str(error_message),
        )
    )

    if settings.ENVIRONMENT != 'prod':
        slack_messages = (
            "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper()) + slack_messages
        )

    send_slack_bot_message(channel="#ovo-autodebit-alert", message=slack_messages)


@task(queue='repayment_high')
def reinquiry_payment_autodebet_mandiri_scheduler():
    inquiry_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBET_RE_INQUIRY, is_active=True
    )

    if not inquiry_fs:
        return

    # 840(minutes) is 10:00 to 00:00
    interval_minutes = inquiry_fs.parameters[AutodebetVendorConst.MANDIRI]['minutes']
    limit = int(840 / interval_minutes)
    for multiplier in range(limit):
        reinquiry_payment_autodebet_mandiri.apply_async(
            countdown=((multiplier * interval_minutes) * 60)
        )
    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_mandiri_scheduler',
            'limit': limit,
            'message': "start parent task",
        }
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_mandiri():
    now = timezone.now()
    start_dt = timezone.localtime(now) - timedelta(days=7)
    end_dt = timezone.localtime(now) - timedelta(hours=1)
    autodebet_mandiri_transactions = AutodebetMandiriTransaction.objects.filter(
        status=AutodebetMandiriPaymentResultStatusConst.PENDING,
        cdate__range=(start_dt, end_dt),
        original_partner_reference_no__isnull=False,
    ).order_by('cdate')

    chain_tasks = []
    for autodebet_mandiri_transaction in autodebet_mandiri_transactions.iterator():
        chain_tasks.append(
            reinquiry_payment_autodebet_mandiri_subtask.si(
                autodebet_mandiri_transaction.original_partner_reference_no
            )
        )
    chain(chain_tasks).apply_async()

    logger.info(
        {
            'action': 'juloserver.autodebet.tasks.reinquiry_payment_autodebet_ovo',
            'message': "end child task",
        }
    )


@task(queue='repayment_high')
def reinquiry_payment_autodebet_mandiri_subtask(original_partner_reference_no):
    inquiry_transaction_statusv2(original_partner_reference_no)


@task(queue='repayment_low')
def update_autodebet_payment_offer(account_id: int):
    account = Account.objects.get(pk=account_id)
    existing_autodebet_account = get_existing_autodebet_account(account)

    if not existing_autodebet_account:
        now = timezone.localtime(timezone.now())
        paybact_trx_count = PaybackTransaction.objects.filter(
            Q(account=account)
            & Q(transaction_date__year=now.year)
            & Q(transaction_date__month=now.month)
            & Q(is_processed=True)
        ).count()

        if paybact_trx_count == 1:
            with transaction.atomic(using="repayment_db"):
                payment_offer = (
                    AutodebetPaymentOffer.objects.select_for_update()
                    .filter(account_id=account.id)
                    .first()
                )

                if not payment_offer:
                    AutodebetPaymentOffer.objects.create(
                        account_id=account.id, counter=0, is_should_show=True
                    )
                else:
                    payment_offer.counter += 1
                    if payment_offer.counter % 3 == 0:
                        payment_offer.is_should_show = True

                    payment_offer.save()


@task(queue='repayment_normal')
def store_autodebet_streamline_experiment(account_ids):
    experiment_setting = get_autodebet_experiment_setting()
    if not experiment_setting:
        return

    experiment_groups = []
    for account_id in account_ids:
        account = Account.objects.get(pk=account_id)
        group = None
        if account:
            group = "control"
            if is_experiment_group_autodebet(account):
                group = "experiment"

            existing_group = ExperimentGroup.objects.filter(
                account_id=account_id,
                experiment_setting_id=experiment_setting.id,
            )
            if not existing_group.exists():
                experiment_groups.append(
                    ExperimentGroup(
                        account_id=account_id,
                        experiment_setting_id=experiment_setting.id,
                        group=group,
                    )
                )

    ExperimentGroup.objects.bulk_create(experiment_groups, batch_size=1000)


@task(queue='repayment_normal')
def suspend_autodebet_deactivated_account_task(account_id, account_status):
    autodebet_account = AutodebetAccount.objects.filter(
        account_id=account_id,
        status__in=[AutodebetStatuses.REGISTERED, AutodebetStatuses.PENDING_REGISTRATION],
        is_use_autodebet=True,
        is_suspended=False,
    ).last()

    if autodebet_account:
        autodebet_account.is_suspended = True
        autodebet_account.save()
        AutodebetSuspendLog.objects.create(
            autodebet_account=autodebet_account,
            account_id=int(account_id),
            reason="turned off due to account is no longer valid (account status {})".format(
                account_status
            ),
        )


def create_debit_payment_process_mandiri_chainv2(account_payments):
    chain_tasks = []
    for idx, account_payment in enumerate(account_payments.iterator()):
        if idx == 0:
            chain_tasks.append(
                create_debit_payment_process_mandiri_subchainv2.s(True, account_payment.id),
            )
        else:
            chain_tasks.append(
                create_debit_payment_process_mandiri_subchainv2.s(account_payment.id),
            )

    chain(chain_tasks).apply_async()


@task(queue='repayment_high')
def create_debit_payment_process_mandiri_subchainv2(
    is_success_previous_payment, account_payment_id
) -> bool:
    if is_success_previous_payment is False:
        logger.warning(
            {
                "task": "juloserver.autodebet.tasks."
                "create_debit_payment_process_mandiri_chainv2",
                "message": "payment process was stop by previous payment",
                "account_payment_id": account_payment_id,
            }
        )
        return False

    account_payment = AccountPayment.objects.get(pk=account_payment_id)
    account = account_payment.account
    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account__account=account,
    ).last()
    if not autodebet_mandiri_account or not autodebet_mandiri_account.bank_card_token:
        logger.warning(
            {
                "task": "juloserver.autodebet.tasks."
                "create_debit_payment_process_mandiri_chainv2",
                "message": "autodebet_mandiri_account or bank card token not found",
                "account_id": account.id,
                "account_payment_id": account_payment_id,
            }
        )
        return False

    mandiri_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = mandiri_max_limit_setting.parameters.get('maximum_amount')

    today_date = timezone.localtime(timezone.now()).date()
    total_amount_deducted = (
        AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=autodebet_mandiri_account,
            status__in=(
                AutodebetMandiriPaymentResultStatusConst.SUCCESS,
                AutodebetMandiriPaymentResultStatusConst.PENDING,
            ),
            cdate__date=today_date,
        ).aggregate(amount_sum=Sum("amount"))["amount_sum"]
        or 0
    )
    remaining_amount = maximum_amount - total_amount_deducted
    due_amount = account_payment.due_amount

    if due_amount > remaining_amount:
        due_amount = remaining_amount

    if due_amount <= 0:
        logger.error(
            {
                'action': 'juloserver.autodebet.tasks.'
                'create_debit_payment_process_mandiri_chainv2',
                'account_id': account.id,
                'account_payment_id': account_payment.id,
                'error': "Due amount must be greater than zero",
            }
        )
        return False

    customer = account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    autodebet_mandiri_client = get_mandiri_autodebet_client(account, account_payment)
    purchase_id = autodebet_mandiri_client.generate_external_id(customer_xid)

    response, error_message = autodebet_mandiri_client.create_payment_purchase_submit(
        purchase_id,
        autodebet_mandiri_account.bank_card_token,
        due_amount,
        VendorConst.AUTODEBET_MANDIRI_PURCHASE_PRODUCT_TYPE,
        customer_xid,
    )
    if error_message:
        logger.error(
            {
                "task": "juloserver.autodebet.tasks."
                "create_debit_payment_process_mandiri_chainv2",
                "account_id": account.id,
                'account_payment_id': account_payment.id,
                "error": error_message,
            }
        )
        return True

    if response['responseCode'] == '2025400':
        AutodebetMandiriTransaction.objects.create(
            autodebet_mandiri_account=autodebet_mandiri_account,
            amount=due_amount,
            account_payment=account_payment,
            original_partner_reference_no=purchase_id,
            status=AutodebetMandiriPaymentResultStatusConst.PENDING,
        )

    time.sleep(1.5)

    return True


@task(queue='repayment_high')
def gopay_autodebet_subscription_retry():
    gopay_subscription_retry = GopayAutodebetSubscriptionRetry.objects.filter(
        cdate__date=timezone.localtime(timezone.now()).date(), is_retried=False
    )

    for subscription_retry in gopay_subscription_retry:
        try:
            account_payment = AccountPayment.objects.get_or_none(
                pk=subscription_retry.account_payment_id
            )
            if account_payment:
                create_subscription_payment_process_gopay(account_payment)
                subscription_retry.is_retried = True
                subscription_retry.save()
        except Exception as e:
            logger.error(
                {
                    "action": "juloserver.autodebet.tasks.gopay_autodebet_subscription_retry",
                    "error": str(e),
                    "account_payment_id": subscription_retry.account_payment_id,
                }
            )
            sentry.captureException()
            continue

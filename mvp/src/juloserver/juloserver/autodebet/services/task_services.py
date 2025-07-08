import ast
import calendar
import copy
from builtins import str
import uuid

import pytz
import math
import logging
import time

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from datetime import datetime, timedelta
from babel.dates import format_date
from typing import List

from juloserver.account_payment.models import AccountPayment
from juloserver.autodebet.clients import (
    get_bca_autodebet_client,
    get_bca_fund_collection_client,
    get_bri_autodebet_client,
    get_mandiri_autodebet_client,
    get_dana_autodebet_client,
)
from juloserver.autodebet.exceptions import AutodebetException
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBenefit,
    AutodebetAPILog,
    AutodebetMandiriAccount,
    AutodebetMandiriTransaction,
    AutodebetDanaTransaction,
    AutodebetOvoTransaction,
)
from juloserver.autodebet.constants import (
    FeatureNameConst,
    AutodebetStatuses,
    AutodebetVendorConst,
    VendorConst,
    BRIErrorCode,
    AutodebetDeductionSourceConst,
    AutodebetDANAPaymentResultStatusConst,
    AutodebetDanaResponseCodeConst,
    DanaErrorCode,
    MINIMUM_BALANCE_AUTODEBET_DANA_DEDUCTION_DPD,
    MINIMUM_BALANCE_AUTODEBET_OVO_DEDUCTION_DPD,
    AutodebetOVOPaymentResultStatusConst,
    AutodebetOVOResponseCodeConst,
    OVOErrorCode,
    AutodebetMandiriPaymentResultStatusConst,
)
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    send_pn_autodebet_activated_payday,
    get_deduction_day,
    get_autodebet_dpd_deduction,
    is_autodebet_mandiri_feature_active,
    is_autodebet_feature_disable,
    is_account_eligible_for_fund_collection,
)
from juloserver.autodebet.services.authorization_services import (
    init_autodebet_bri_transaction,
    update_autodebet_bri_transaction_failed,
    update_autodebet_bri_transaction_first_step,
    check_gopay_wallet_token_valid,
    update_gopay_wallet_token,
)
from juloserver.autodebet.services.benefit_services import (
    update_autodebet_benefit_vendor,
    store_autodebet_benefit_control,
    get_benefit_waiver_amount,
    is_eligible_to_get_benefit,
    give_benefit,
    set_default_autodebet_benefit_control,
)
from juloserver.dana_linking.constants import DanaWalletAccountStatusConst
from juloserver.dana_linking.models import DanaWalletAccount
from juloserver.dana_linking.services import get_dana_balance_amount

from juloserver.ovo.constants import (
    OvoWalletAccountStatusConst,
    AUTODEBET_MINIMUM_AMOUNT_PAYMENT,
    AUTODEBET_MAXIMUM_AMOUNT_PAYMENT,
)
from juloserver.ovo.models import OvoWalletAccount
from juloserver.ovo.services.ovo_tokenization_services import get_ovo_wallet_balance

from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_julo_pn_client,
    get_doku_snap_ovo_client
)

from juloserver.julo.models import (
    FeatureSetting,
    PaybackTransaction,
    PaymentMethod,
    Device,
)
from juloserver.account.models import (
    AccountTransaction,
    Account,
)

from juloserver.account_payment.services.payment_flow import (
    process_repayment_trx,
    get_and_update_latest_loan_status,
)
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import (
    process_j1_waiver_before_payment,
    j1_paid_waiver,
)

from juloserver.monitors.notifications import notify_payment_failure_with_severity_alert
from juloserver.moengage.tasks import (
    update_moengage_for_payment_received_task,
    send_event_autodebit_failed_deduction_task,
    send_event_autodebet_bri_expiration_handler_task,
)
from juloserver.monitors.services import get_channel_name_slack_for_payment_problem

from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.payback.models import (
    GopayAccountLinkStatus,
    GopayAutodebetTransaction,
    GopayCustomerBalance,
)
from juloserver.payback.client import get_gopay_client
from juloserver.payback.constants import (
    GopayAccountStatusConst,
    GopayAccountStatusMessageConst,
)
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.autodebet.services.autodebet_services import suspend_autodebet_insufficient_balance
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.pii_vault.constants import PiiSource

sentry = get_julo_sentry_client()

logger = logging.getLogger(__name__)


def get_active_autodebet_account(vendors):
    return AutodebetAccount.objects.filter(
        vendor__in=vendors,
        is_use_autodebet=True,
        is_deleted_autodebet=False,
        is_suspended=False,
    )


def get_active_autodebet_bri_account():
    return AutodebetAccount.objects.filter(
        vendor=AutodebetVendorConst.BRI,
        is_use_autodebet=True,
        is_deleted_autodebet=False,
    )


def get_active_autodebet_gopay_account():
    return AutodebetAccount.objects.filter(
        vendor=AutodebetVendorConst.GOPAY,
        is_use_autodebet=True,
        is_deleted_autodebet=False,
        is_suspended=False,
    )


def get_autodebet_inquiry_feature_configuration(retry_count=0):
    autodebet_inquiry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_AUTODEBET_BCA_INQUIRY, is_active=True
    ).last()
    if not autodebet_inquiry_feature:
        return

    configuration = autodebet_inquiry_feature.parameters
    if retry_count > configuration['limit']:
        return

    return configuration


def update_account_payment_xid(account_payment, retry_count=0):
    try:
        account_payment.update_safely(
            account_payment_xid=str(time.time()).replace('.', '')[:14]
        )
    except IntegrityError:
        if retry_count < 12:
            account_payment = update_account_payment_xid(
                account_payment, retry_count + 1
            )
        else:
            get_julo_sentry_client().captureException()
    finally:
        return account_payment


def inquiry_account_registration(autodebet_account_id, retry_count):
    # importing here, because of circular import
    julo_pn_client = get_julo_pn_client()
    autodebet_account = AutodebetAccount.objects.get_or_none(
        pk=autodebet_account_id,
        activation_ts__isnull=True,
        failed_ts__isnull=True,
        deleted_success_ts__isnull=True,
        deleted_failed_ts__isnull=True,
        is_deleted_autodebet=False,
    )
    if not autodebet_account:
        return "98", "Autodebet account doesn't exist"

    account = autodebet_account.account
    application = account.last_application
    customer_id_merchant = str(application.application_xid)
    bca_autodebet_client = get_bca_autodebet_client(account)
    data, error_message = bca_autodebet_client.send_request(
        "get", "/account-authorization/inquiry/%s" % customer_id_merchant, {},
        extra_headers={"customer_id_merchant": customer_id_merchant}
    )

    if error_message:
        return "99", error_message

    request_id = autodebet_account.request_id
    if len(data['skpr_active']) == 1:
        account_id = autodebet_account.account_id
        active_skpr = data['skpr_active'][0]
        active_autodebet_account = AutodebetAccount.objects.filter(
            account_id=account_id, request_id='A' + active_skpr['skpr_id']
        ).last()
        if not active_autodebet_account:
            return "02", "Autodebet account not found"

        if active_autodebet_account != autodebet_account:
            AutodebetAccount.objects.filter(account_id=account_id).update(
                status='failed_registration',
                deleted_failed_reason=None,
                is_deleted_autodebet=True,
            )
            autodebet_account = active_autodebet_account
        autodebet_account.update_safely(
            is_use_autodebet=True,
            is_deleted_autodebet=False,
            failed_ts=None,
            failed_reason=None,
            activation_ts=active_skpr['active_date'],
            db_account_no=active_skpr['db_account_no'],
            status=AutodebetStatuses.REGISTERED,
        )

        set_default_autodebet_benefit_control(account, AutodebetVendorConst.BCA)
        get_autodebet_payment_method(
            account, autodebet_account.vendor,
            AutodebetVendorConst.PAYMENT_METHOD[autodebet_account.vendor])
        device = Device.objects.filter(customer_id=account.customer_id).last()
        julo_pn_client.pn_autodebet_activated(account, device.gcm_reg_id)
        send_pn_autodebet_activated_payday(account, AutodebetVendorConst.BCA)
        if not account.autodebetaccount_set.filter(status='revoked').exists():
            update_autodebet_benefit_vendor(account, autodebet_account.vendor)
        return "01", "Autodebet account activate"

    pending = next(
        (skpr for skpr in data['skpr_pending'] if skpr['request_id'] == request_id), None
    )
    if pending and pending['status'] == "03":
        autodebet_account.update_safely(
            retry_count=retry_count
        )

        # this logic to handle anomaly where the user still not process the registration
        # on their side (mBCA)
        threshold_in_hour = 2
        current_ts = timezone.localtime(timezone.now())
        registration_ts = timezone.localtime(autodebet_account.registration_ts)
        delta_hour = divmod((current_ts - registration_ts).seconds, 3600)[0]
        expired_registration = delta_hour >= threshold_in_hour
        if expired_registration:
            autodebet_account.update_safely(
                failed_ts=timezone.localtime(timezone.now()),
                failed_reason='registration expired (over than 2 hour)',
                is_use_autodebet=False,
                is_deleted_autodebet=False,
                status=AutodebetStatuses.FAILED_REGISTRATION
            )
            logger.warning({
                "action": "autodebet.services.task_services.inquiry_account_registration",
                "current_ts": timezone.localtime(timezone.now())
            })
            return "02", "Autodebet account abandoned (expired)"

        return "03", "Autodebet account still on process"

    if pending and pending['status'] == "02":
        autodebet_account.update_safely(
            is_use_autodebet=False,
            failed_ts=pending['failed_date'],
        )
        return "02", "Autodebet account reject"

    return "97", "Undefined condition"


def process_fund_collection(account_payments, vendor, amount=0, bri_transaction_id=None):
    is_split_payment = False
    if vendor == AutodebetVendorConst.BCA:
        autodebet_feature = FeatureNameConst.AUTODEBET_BCA
        account_payment = account_payments.order_by('due_date').first()
        due_amount = 0
        for account_payment in account_payments.iterator():
            due_amount += account_payment.due_amount
    elif vendor == AutodebetVendorConst.BRI:
        autodebet_feature = FeatureNameConst.AUTODEBET_BRI
        account_payment = account_payments
        due_amount = amount
        # handle if split payment
        due_amount_after_benefit = account_payment.due_amount - get_benefit_waiver_amount(
            account_payment)
        if due_amount_after_benefit >= VendorConst.MAX_DUE_AMOUNT_BRI_AUTODEBET:
            is_split_payment = True
    else:
        logger.error({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection',
            'account_payments': account_payments,
            'error': 'Autodebet vendor not found',
        })
        return 'Autodebet vendor not found'

    autodebet_feature_setting = FeatureSetting.objects.filter(
        feature_name=autodebet_feature, is_active=True
    ).last()

    if not autodebet_feature_setting:
        logger.error({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection',
            'error': "Autodebet {} feature not active".format(vendor),
        })
        return "Autodebet {} feature not active".format(vendor)

    account = account_payment.account
    existing_benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)

    if vendor == VendorConst.BCA:
        if is_eligible_to_get_benefit(account):
            due_amount -= get_benefit_waiver_amount(account_payment)

    data_constructor = {
        AutodebetVendorConst.BCA: construct_fund_collection_data(account_payment, due_amount),
        AutodebetVendorConst.BRI: construct_fund_collection_bri_data(account_payment, due_amount,
                                                                     bri_transaction_id)
    }

    data = data_constructor[vendor]

    if not data:
        logger.error({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection',
            'account': account.id,
            'data': data,
            'error': "Data missmatch",
        })
        return "Account don't have active autodebet account"

    error_message = ''

    try:
        amount = float(data['Amount'])
        autodebet_api_log_id = ''
        if vendor == AutodebetVendorConst.BCA:
            bca_autodebet_client = get_bca_fund_collection_client(account)
            # based on API documentation, it's only allow spesific account number for testing
            force_success_fund_collection = FeatureSetting.objects.filter(
                feature_name="force_success_fund_collection", is_active=True
            ).last()
            if force_success_fund_collection:
                data["DebitedAccount"] = settings.BCA_FUND_COLLECTION_DEBITED_ACCOUNT
                data["CreditedAccount"] = settings.BCA_FUND_COLLECTION_CREDITED_ACCOUNT

            extra_headers = {
                "ChannelID": bca_autodebet_client.channel_id,
                "CredentialID": bca_autodebet_client.corporate_id.zfill(10),
            }
            data, error_message, autodebet_api_log_id = bca_autodebet_client.send_request(
                "post", "/fund-collection", data, extra_headers=extra_headers,
                account_payment=account_payment, is_need_api_log=True
            )

            if error_message:
                if error_message == 'Saldo tidak cukup':
                    autodebet_account = get_existing_autodebet_account(
                        account, VendorConst.BCA
                    )
                    suspend_autodebet_insufficient_balance(
                        autodebet_account,
                        autodebet_account.vendor
                    )

                send_event_autodebit_failed_deduction_task.delay(
                    account_payment.id,
                    account.customer.id,
                    vendor
                )
                return error_message

        local_timezone = pytz.timezone('Asia/Jakarta')
        transaction_date = local_timezone.localize(
            datetime.strptime(data['TransactionDate'], '%Y-%m-%d'))

        with transaction.atomic():
            if existing_benefit:
                if is_eligible_to_get_benefit(account, is_split_payment):
                    give_benefit(existing_benefit, account, account_payment)

            transaction_id = data['TransactionID']
            payback_transaction = PaybackTransaction.objects.create(
                is_processed=False,
                customer=account.customer,
                payback_service='autodebet',
                status_desc='Autodebet {}'.format(vendor),
                transaction_id=transaction_id,
                transaction_date=transaction_date,
                amount=amount,
                account=account_payment.account,
                payment_method=get_autodebet_payment_method(
                    account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor])
            )
            j1_refinancing_activation(
                payback_transaction, account_payment, payback_transaction.transaction_date)
            process_j1_waiver_before_payment(
                account_payment, amount, payback_transaction.transaction_date)
            account_trx = process_repayment_trx(
                payback_transaction, note='payment with autodebet {} amount {}'.format(
                    vendor, amount)
            )
        if account_trx:
            if vendor == AutodebetVendorConst.BCA:
                autodebet_api_log = AutodebetAPILog.objects.get(pk=autodebet_api_log_id)
            else:
                autodebet_api_log = AutodebetAPILog.objects.filter(
                    account_payment_id=account_payment.id
                ).last()

            if autodebet_api_log:
                autodebet_api_log.update_safely(account_transaction_id=account_trx.id)
            execute_after_transaction_safely(
                lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
            )

    except Exception as e:
        get_julo_sentry_client().captureException()
        msg = "payment with autodebet {} amount {} account_payment id {} failed due to {}".format(
            vendor, amount, account_payment.id, str(e)
        )
        logger.info({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection',
            'account_payment': account_payment,
            'error': str(e),
        })
        channel_name = get_channel_name_slack_for_payment_problem()
        notify_payment_failure_with_severity_alert(msg, "#FF0000", channel_name)
        raise

    return None


def construct_fund_collection_data(account_payment, due_amount):
    account = account_payment.account
    existing_autodebet_account = AutodebetAccount.objects.filter(
        vendor="BCA",
        account=account,
        is_deleted_autodebet=False,
        is_use_autodebet=True,
    ).last()
    if not existing_autodebet_account:
        return None

    application = account.last_application
    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.APPLICATION, application, application.customer.customer_xid, ['email']
    )
    current_ts = timezone.localtime(timezone.now())
    formatted_date = current_ts.strftime('%Y-%m-%d')
    formatted_remark = "bulan %s" % format_date(current_ts, "MMM yyyy", locale='id')
    if not account_payment.account_payment_xid:
        account_payment = update_account_payment_xid(account_payment)
        if not account_payment.account_payment_xid:
            return None

    return {
        "TransactionID": str(time.time()).replace('.', '')[:16],
        "ReferenceNumber": account_payment.account_payment_xid,
        "RequestType": "NB",
        "DebitedAccount": existing_autodebet_account.db_account_no,
        "Amount": format(due_amount, '.2f'),
        "Currency": "IDR",
        "CreditedAccount": settings.BCA_AUTODEBET_ACCOUNT_NUMBER,
        "EffectiveDate": formatted_date,
        "TransactionDate": formatted_date,
        "Remark1": "cicilan JULO",
        "Remark2": formatted_remark,
        "Email": detokenized_application.email,
    }


def construct_fund_collection_bri_data(account_payment, due_amount, bri_transaction_id):
    account = account_payment.account
    existing_autodebet_account = AutodebetAccount.objects.filter(
        vendor=AutodebetVendorConst.BRI,
        account=account,
        is_deleted_autodebet=False,
        is_use_autodebet=True,
    ).last()

    if not existing_autodebet_account:
        return None

    customer = account.customer
    current_ts = timezone.localtime(timezone.now())
    formatted_date = current_ts.strftime('%Y-%m-%d')
    formatted_remark = "bulan %s" % format_date(current_ts, "MMM yyyy", locale='id')
    detokenized_application = detokenize_sync_primary_object_model(
        PiiSource.CUSTOMER, customer, customer.customer_xid, ['email']
    )
    return {
        "TransactionID": bri_transaction_id,
        "ReferenceNumber": account_payment.account_payment_xid,
        "RequestType": "NB",
        "DebitedAccount": existing_autodebet_account.linked_account_id,
        "Amount": format(due_amount, '.2f'),
        "Currency": "IDR",
        "EffectiveDate": formatted_date,
        "TransactionDate": formatted_date,
        "Remark1": "cicilan JULO",
        "Remark2": formatted_remark,
        "Email": detokenized_application.email,
    }


def process_autodebet_benefit_waiver(account_payment):
    existing_benefit = (
        AutodebetBenefit.objects.filter(
            account_id=account_payment.account.id,
            is_benefit_used=False,
        )
        .exclude(
            benefit_type="cashback",
        )
        .last()
    )

    if not existing_benefit or not existing_benefit.benefit_type:
        return None

    benefit_types = existing_benefit.benefit_type.split("_")
    if benefit_types[0] == "waive":
        waiver_type = benefit_types[1]
        try:
            benefit_value = ast.literal_eval(existing_benefit.benefit_value)
            if type(benefit_value) != dict:
                benefit_value['percentage'] = 0
        except SyntaxError:
            benefit_value = dict(percentage=0, max=0)
        waiver_percentage = float(benefit_value['percentage']) / float(100)
        remaining_amount = getattr(account_payment, "remaining_%s" % waiver_type)

        if remaining_amount == 0:
            return

        waiver_amount = math.ceil(float(waiver_percentage) * float(remaining_amount))
        waiver_max_amount = benefit_value['max']
        if waiver_amount >= waiver_max_amount:
            waiver_amount = waiver_max_amount
        loan_statuses_list = []
        status, _ = j1_paid_waiver(
            waiver_type,
            account_payment,
            waiver_amount,
            "Autodebet Waive Benefit",
            loan_statuses_list,
            is_autodebet_waive=True,
        )
        get_and_update_latest_loan_status(loan_statuses_list)
        if status:
            account = account_payment.account
            transaction_date = timezone.localtime(timezone.now()).date()
            account_trx = AccountTransaction.objects.filter(
                account=account,
                payback_transaction=None,
                transaction_date=transaction_date,
                transaction_amount=waiver_amount,
                transaction_type='waive_%s' % waiver_type,
            ).last()
            existing_benefit = {
                'type': existing_benefit.benefit_type,
                'value': benefit_value
            }
            for payment_event in account_trx.paymentevent_set.all():
                store_autodebet_benefit_control(account, account_payment, payment_event.payment.id,
                                                existing_benefit, payment_event.event_payment)
        return


def process_fund_collection_bri(account_payment):
    autodebet_bri_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BRI, is_active=True
    ).last()
    if not autodebet_bri_feature_setting:
        return {}, "Autodebet BRI feature not active"

    due_amount = account_payment.due_amount
    account = account_payment.account
    data = construct_fund_collection_bri_data(account_payment, due_amount)

    try:
        amount = float(data['Amount'])

        local_timezone = pytz.timezone('Asia/Jakarta')
        transaction_date = local_timezone.localize(
            datetime.strptime(data['TransactionDate'], '%Y-%m-%d'))
        account_trx = None
        with transaction.atomic():
            transaction_id = 'autodebet-bri-%s-%s' % (data['TransactionID'],
                                                      data['ReferenceNumber'])
            payback_transaction = PaybackTransaction.objects.create(
                is_processed=False,
                customer=account.customer,
                payback_service='autodebet',
                status_desc='Autodebet BRI',
                transaction_id=transaction_id,
                transaction_date=transaction_date,
                amount=amount,
                account=account_payment.account,
                payment_method=None
            )
            j1_refinancing_activation(
                payback_transaction, account_payment, payback_transaction.transaction_date)
            process_j1_waiver_before_payment(
                account_payment, amount, payback_transaction.transaction_date)
            account_trx = process_repayment_trx(
                payback_transaction, note='payment with autodebet BRI amount %s' % amount
            )
        if account_trx:
            execute_after_transaction_safely(
                lambda: update_moengage_for_payment_received_task.delay(account_trx.id)
            )

    except Exception as e:
        get_julo_sentry_client().captureException()
        msg = "payment with autodebet BRI amount {} account_payment id {} failed due to {}".format(
            amount, account_payment.id, str(e)
        )
        logger.info({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection_bri',
            'account_payment': account_payment,
            'error': str(e),
        })
        channel_name = get_channel_name_slack_for_payment_problem()
        notify_payment_failure_with_severity_alert(msg, "#FF0000", channel_name)
        raise

    return data, None


def get_autodebet_payment_method(account, vendor, bank_code):
    customer = account.customer
    detokenized_customer = detokenize_sync_primary_object_model(
        PiiSource.CUSTOMER, customer, customer.customer_xid, ['phone']
    )
    payment_method_code = "999%s" % bank_code
    payment_method, _ = PaymentMethod.objects.get_or_create(
        payment_method_code=payment_method_code,
        payment_method_name="Autodebet %s" % vendor,
        bank_code=bank_code,
        customer=customer,
        is_shown=False,
        is_primary=False,
        virtual_account="%s%s" % (payment_method_code, detokenized_customer.phone),
    )

    return payment_method


def retry_autodebet_bri_validation(retry_count):
    autodebet_retry_bri_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_AUTODEBET_BRI, is_active=True).first()

    if not autodebet_retry_bri_feature:
        logger.warning({
            "action": "autodebet_retry_bri_feature",
            "error": "autodebet_retry_bri_feature is not active"
        })
        return False, None

    params = autodebet_retry_bri_feature.parameters
    retry_interval_minutes = params['minutes']
    max_retries = params['max_retry_count']

    if retry_interval_minutes == 0:
        logger.warning({
            "action": "autodebet_retry_bri_feature",
            "error": "Parameter retry_interval_minutes: {} can not be zero value".format(
                retry_interval_minutes)
        })
        return False, None

    if not isinstance(retry_interval_minutes, int):
        logger.warning({
            "action": "autodebet_retry_bri_feature",
            "error": "Parameter retry_interval_minutes should integer"
        })
        return False, None

    if not isinstance(max_retries, int):
        logger.warning({
            "action": "autodebet_retry_bri_feature",
            "error": "Parameter max_retries should integer"
        })
        return False, None

    if max_retries <= 0:
        logger.warning({
            "action": "autodebet_retry_bri_feature",
            "error": "Parameter max_retries should greater than zero"
        })
        return False, None

    countdown_seconds = retry_interval_minutes * 60

    if retry_count >= max_retries:
        logger.warning({
            "action": "autodebet_retry_bri",
            "message": "Autodebet retry BRI has exceeded the maximum limit"
        })
        return False, None

    logger.info({
        'action': 'autodebet_retry_bri_failure_status',
        'retry_count': retry_count,
        'count_down': countdown_seconds
    })

    return True, countdown_seconds


def create_debit_payment_process_bri(account_payments):
    from juloserver.autodebet.services.autodebet_services import (
        suspend_autodebet_insufficient_balance,
    )

    account_payment = account_payments.order_by('due_date').first()
    due_amount = account_payment.due_amount
    autodebet_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BRI, is_active=True
    ).last()
    minimum_autodebet_amount = autodebet_feature_setting.parameters['minimum_amount']

    if due_amount < minimum_autodebet_amount:
        logger.error({
            'action': 'juloserver.autodebet.services.task_services.process_fund_collection',
            'account_payments': account_payments,
            'error': "Due amount less than minimun amount",
        })
        raise AutodebetException("Due amount less than minimun amount")

    is_split = False
    if due_amount >= VendorConst.MAX_DUE_AMOUNT_BRI_AUTODEBET:
        due_amount = VendorConst.AMOUNT_DEDUCTION_BRI_AUTODEBET
        is_split = True

    if is_eligible_to_get_benefit(account_payment.account, is_split):
        due_amount -= get_benefit_waiver_amount(account_payment)

    account = account_payment.account
    autodebet_account = get_existing_autodebet_account(account, AutodebetVendorConst.BRI)

    transaction_id = str(uuid.uuid4())
    payment_method_id = autodebet_account.payment_method_id

    bri_transaction = init_autodebet_bri_transaction(
        transaction_id, autodebet_account, account_payment, due_amount)

    bri_autodebet_client = get_bri_autodebet_client(account)
    result, error = bri_autodebet_client.create_direct_debit_payment(
        transaction_id, payment_method_id, due_amount, False, account_payment)

    if error:
        update_autodebet_bri_transaction_failed(error, bri_transaction)
        if result['error_code'] == BRIErrorCode.INSUFFICIENT_BALANCE:
            suspend_autodebet_insufficient_balance(autodebet_account, VendorConst.BRI)
            return account_payment.id
        elif result['error_code'] == BRIErrorCode.INVALID_PAYMENT_METHOD_ERROR:
            autodebet_account.update_safely(
                deleted_request_ts=timezone.localtime(timezone.now()),
                deleted_success_ts=timezone.localtime(timezone.now()),
                is_deleted_autodebet=True,
                is_use_autodebet=False,
                is_force_unbind=True,
                status=AutodebetStatuses.REVOKED
            )
            send_event_autodebet_bri_expiration_handler_task.delay(
                account_payment.id, account.customer.id
            )
        raise AutodebetException("Could not create debit payment")

    update_autodebet_bri_transaction_first_step(result, bri_transaction)


def determine_best_deduction_day(account, raise_error=True):
    today_date = timezone.localtime(timezone.now()).date()
    day = get_deduction_day(account, raise_error)

    # To check and compare the last day of the month with deduction day
    last_day_of_the_month = calendar.monthrange(
        today_date.year, today_date.month)[1]

    if day >= last_day_of_the_month:
        day = last_day_of_the_month

    return day


def get_due_amount_for_gopay_autodebet_deduction(account):
    dpd_start, dpd_end = get_autodebet_dpd_deduction(vendor=AutodebetVendorConst.GOPAY)
    subscription_due_date = timezone.localtime(timezone.now()).date() - timedelta(days=dpd_start)
    account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')
    if not account_payments:
        return None

    due_amount = 0
    for account_payment in account_payments.iterator():
        if account_payment.due_date <= subscription_due_date:
            due_amount += account_payment.due_amount

    return due_amount


def create_subscription_payment_process_gopay(account_payment):
    account = account_payment.account
    gopay_account_link = GopayAccountLinkStatus.objects.filter(
        account=account, status=GopayAccountStatusConst.ENABLED).last()
    autodebet_gopay_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_GOPAY
    ).last()

    if not gopay_account_link:
        logger.error(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_subscription_payment_process_gopay',
                'error': 'Account GoPay Anda belum terhubung/tidak terdaftar',
                'data': {'account_id': account.id}
            }
        )
        return

    now = timezone.localtime(timezone.now())

    gopay_autodebet_transaction = GopayAutodebetTransaction.objects.filter(
        gopay_account=gopay_account_link,
        cdate__range=[now.date(), now], is_active=True,
    ).last()

    if gopay_autodebet_transaction:
        logger.error(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_subscription_payment_process_gopay',
                'error': 'subscription sudah dibuat dihari ini',
                'data': {'account_id': account.id}
            }
        )
        return

    result = check_gopay_wallet_token_valid(account)
    if not result:
        logger.error(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_subscription_payment_process_gopay',
                'account_id': account.id,
                'error': 'GopayAccountLinkStatus not found',
            }
        )
        return
    is_valid = result[0]
    token = result[1]

    if not is_valid:
        update_gopay_wallet_token(account, token)

    due_amount = get_due_amount_for_gopay_autodebet_deduction(account)
    if not due_amount:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_subscription_payment_process_gopay',
                'account_id': account.id,
                'error': 'No payment due today for this {} account'.format(account.id),
            }
        )
        return

    if due_amount <= 0:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'update_gopay_autodebet_account_subscription',
                'account_id': account.id,
                'error': 'subscription.amount must be between 0.01 - 99999999999.00',
            }
        )
        return

    customer = account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid
    name = str(customer_xid) + str(time.time()).replace('.', '')[:8]

    start_time = (
        timezone.localtime(timezone.now() + timedelta(days=1))
        .replace(hour=17, minute=0, second=0)
        .strftime("%Y-%m-%d %H:%M:%S %z")
    )

    retry_schedule = autodebet_gopay_feature_setting.parameters['retry_schedule']

    req_data = {
        "name": name,
        "amount": str(due_amount),
        "currency": "IDR",
        "payment_type": "gopay",
        "token": token,
        "schedule": {
            "interval": 1,
            "interval_unit": "month",
            "max_interval": 1,
            "start_time": start_time,
        },
        "retry_schedule": retry_schedule,
        "gopay": {
            "account_id": gopay_account_link.pay_account_id
        }
    }

    gopay_client = get_gopay_client()
    res_data = gopay_client.create_subscription_gopay_autodebet(
        gopay_account_link.pay_account_id,
        account_payment,
        req_data
    )

    if 'id' not in res_data:
        logger.error(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_subscription_payment_process_gopay',
                'account_id': account.id,
                'error': res_data,
            }
        )
        return

    GopayAutodebetTransaction.objects.create(
        subscription_id=res_data['id'],
        name=name,
        gopay_account=gopay_account_link,
        amount=due_amount,
        customer=customer,
        is_active=True,
        account_payment=account_payment,
        is_partial=False
    )


def disable_gopay_autodebet_account_subscription_if_change_in_due_date(account_payment):
    gopay_autodebet_transaction = GopayAutodebetTransaction.objects.filter(
        account_payment=account_payment).last()

    if not gopay_autodebet_transaction:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'disable_gopay_autodebet_account_subscription_if_change_in_due_date',
                'account_id': account_payment.account.id,
                'error': 'No subscription found for this {} account'.format(
                    account_payment.account.id)
            }
        )
        return

    if not gopay_autodebet_transaction.is_active:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'disable_gopay_autodebet_account_subscription_if_change_in_due_date',
                'account_id': account_payment.account.id,
                'error': 'subscription is already inactive',
            }
        )
        return

    gopay_client = get_gopay_client()
    res_data = gopay_client.disable_subscription_gopay_autodebet(gopay_autodebet_transaction)
    if res_data['status_message'] == "Subscription is updated.":
        gopay_autodebet_transaction.update_safely(is_active=False)


def get_gopay_wallet_customer_balance(pay_account_id):
    gopay_client = get_gopay_client()
    response = gopay_client.get_pay_account(pay_account_id, True)

    if response['account_status'] != GopayAccountStatusConst.ENABLED:
        logger.error({
            'action': 'juloserver.autodebet.services.task_services'
                      'get_gopay_wallet_customer_balance',
            'message': GopayAccountStatusMessageConst.status[response['account_status']],
        })
        return None

    gopay_wallet = next((item for item in response['metadata']['payment_options']
                         if item['name'] == 'GOPAY_WALLET'), None)
    if not gopay_wallet:
        logger.warning(
            {
                'action': 'juloserver.autodebet.services.task_services'
                          '.get_gopay_wallet_customer_balance',
                'pay_account_id': pay_account_id,
                'error': 'Gopay wallet not provided',
                'data': response
            }
        )
        return None

    return int(float(gopay_wallet['balance']['value']))


def update_gopay_wallet_customer_balance(account, balance):
    gopay_customer_balance = GopayCustomerBalance.objects.filter(
        account=account
    ).last()

    if not gopay_customer_balance:
        logger.warning(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                          'update_gopay_wallet_customer_balance',
                'account_id': account.id,
                'error': 'GopayCustomerBalance not found',
            }
        )
        return

    if gopay_customer_balance.balance != balance:
        gopay_customer_balance.update_safely(balance=balance)


def create_debit_payment_process_mandiriv2(account_payments):
    account_payment = account_payments.order_by('due_date').first()
    account = account_payment.account
    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account__account=account,
    ).last()
    if not autodebet_mandiri_account or not autodebet_mandiri_account.bank_card_token:
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                "create_debit_payment_process_mandiri",
                "message": "autodebet_mandiri_account or bank card token not found",
                "account_id": account.id,
            }
        )
        return

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
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_debit_payment_process_mandiriv2',
                'account_id': account.id,
                'account_payment_id': account_payment.id,
                'error': "Due amount must be greater than zero",
            }
        )
        return

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
                "task": "juloserver.autodebet.services.mandiri_services."
                "create_debit_payment_process_mandiriv2",
                "account_id": account.id,
                'account_payment_id': account_payment.id,
                "error": error_message,
            }
        )
        return

    if response['responseCode'] == '2025400':
        AutodebetMandiriTransaction.objects.create(
            autodebet_mandiri_account=autodebet_mandiri_account,
            amount=due_amount,
            account_payment=account_payment,
            original_partner_reference_no=purchase_id,
            status=AutodebetMandiriPaymentResultStatusConst.PENDING,
        )


def check_and_create_debit_payment_process_after_callback_mandiriv2(account):
    is_mandiri_autodebet_active = is_autodebet_mandiri_feature_active()

    autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY, is_active=True
    )
    if not is_mandiri_autodebet_active:
        logger.error(
            {
                "action": "juloserver.autodebet.services.mandiri_services."
                "check_and_create_debit_payment_process_after_callback_mandiriv2",
                "account_id": account.id,
                "message": "autodebet mandiri is inactive",
            }
        )
        return

    autodebet_deduction_parameters = None
    if autodebet_deduction_feature_setting:
        autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters

    is_mandiri_autodebet_disable = is_autodebet_feature_disable(VendorConst.MANDIRI)
    if is_mandiri_autodebet_disable:
        logger.error(
            {
                "action": "juloserver.autodebet.services.mandiri_services."
                "check_and_create_debit_payment_process_after_callback_mandiriv2",
                "account_id": account.id,
                "message": "autodebet mandiri feature is disabled",
            }
        )
        return

    today_date = timezone.localtime(timezone.now()).date()
    autodebet_account = AutodebetAccount.objects.filter(
        vendor=AutodebetVendorConst.MANDIRI,
        account=account,
        is_deleted_autodebet=False,
        is_use_autodebet=True,
        is_suspended=False,
    ).last()
    if not autodebet_account:
        logger.error(
            {
                "action": "juloserver.autodebet.services.mandiri_services."
                "check_and_create_debit_payment_process_after_callback_mandiriv2",
                "account_id": account.id,
                "message": "autodebet acount is not found",
            }
        )
        return

    mandiri_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    deduction_dpd_list = mandiri_max_limit_setting.parameters.get('deduction_dpd', [])

    due_dates = [today_date - timedelta(days=dpd) for dpd in deduction_dpd_list]
    due_dates.append(today_date)

    account_payment = (
        account.accountpayment_set.not_paid_active()
        .filter(due_date__in=due_dates)
        .order_by("due_date")
        .last()
    )
    vendor = autodebet_account.vendor
    deduction_cycle_day = determine_best_deduction_day(account)

    if not account_payment:
        logger.error(
            {
                "action": "juloserver.autodebet.services.mandiri_services."
                "check_and_create_debit_payment_process_after_callback_mandiriv2",
                "account_id": account.id,
                "message": "unpaid account payment not found",
            }
        )
        return

    if autodebet_deduction_parameters:
        if (
            autodebet_deduction_parameters[vendor]["deduction_day_type"]
            == AutodebetDeductionSourceConst.FOLLOW_DUE_DATE
        ):
            if (
                datetime.strptime(
                    autodebet_deduction_parameters[vendor]["last_update"], "%Y-%m-%d"
                ).date()
                >= datetime(today_date.year, today_date.month, deduction_cycle_day).date()
            ):
                return

    if not is_account_eligible_for_fund_collection(account_payment):
        logger.error(
            {
                "action": "juloserver.autodebet.services.mandiri_services."
                "check_and_create_debit_payment_process_after_callback_mandiriv2",
                "account_id": account.id,
                "account_payment": account_payment.id,
                "message": "Exclude fund collection for users that have due date = "
                "registered date",
            }
        )
        return

    filter_ = {"due_date__lte": max(due_dates)}
    if autodebet_deduction_parameters:
        if (
            autodebet_deduction_parameters[vendor]["deduction_day_type"]
            == AutodebetDeductionSourceConst.FOLLOW_PAYDAY
        ):
            filter_ = {
                "due_date__month__lte": today_date.month,
                "due_date__year__lte": today_date.year,
            }
    if account_payment:
        filter_["pk__lte"] = account_payment.id

    account_payments = (
        account.accountpayment_set.not_paid_active().filter(**filter_).order_by("due_date")
    )

    if not account_payments:
        logger.info(
            {
                "action": "juloserver.autodebet.services.mandiri_services."
                "check_and_create_debit_payment_process_after_callback_mandiriv2",
                "account_id": account.id,
                "message": "account payment not found",
            }
        )
        return

    create_debit_payment_process_mandiriv2(account_payments)


def create_debit_payment_process_mandiri(account_payments):
    from juloserver.autodebet.services.mandiri_services import inquiry_transaction_status

    account_payment = account_payments.order_by('due_date').first()
    account = account_payment.account
    autodebet_mandiri_account = AutodebetMandiriAccount.objects.filter(
        autodebet_account__account=account,
    ).last()
    if not autodebet_mandiri_account or not autodebet_mandiri_account.bank_card_token:
        logger.warning(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                        "create_debit_payment_process_mandiri",
                "message": "autodebet_mandiri_account or bank card token not found",
                "account_id": account.id,
            }
        )
        return

    due_amount = 0
    for account_payment in account_payments.iterator():
        due_amount += account_payment.due_amount
    if due_amount <= 0:
        logger.info(
            {
                'action': 'juloserver.autodebet.services.task_services.'
                'create_debit_payment_process_mandiri',
                'account_id': account.id,
                'error': "Due amount must be greater than zero",
            }
        )
        return

    mandiri_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = mandiri_max_limit_setting.parameters.get('maximum_amount')
    if due_amount > maximum_amount:
        due_amount = maximum_amount

    is_need_retry = inquiry_transaction_status(
        autodebet_mandiri_account,
        due_amount,
        account_payment
    )
    if not is_need_retry:
        return

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
        customer_xid
    )
    if error_message:
        logger.error(
            {
                "task": "juloserver.autodebet.services.mandiri_services."
                        "create_debit_payment_process_mandiri",
                "error": error_message,
                "account_id": account.id,
            }
        )
        return

    if response['responseCode'] == '2025400':
        AutodebetMandiriTransaction.objects.create(
            autodebet_mandiri_account=autodebet_mandiri_account,
            amount=due_amount,
            account_payment=account_payment,
            original_partner_reference_no=purchase_id
        )
    return


def is_autodebet_deduction_feature_setting_active():
    autodebet_deduction_parameters = None
    autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY, is_active=True
    )
    if autodebet_deduction_feature_setting:
        autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters
    return autodebet_deduction_parameters


def create_debit_payment_process_ovo(account_payment_ids: List[int], account: Account):
    ovo_wallet_account = OvoWalletAccount.objects.filter(
        account_id=account.id, status=OvoWalletAccountStatusConst.ENABLED
    ).last()
    if not ovo_wallet_account:
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_ovo",
                "account_id": account.id,
                "error": "OVO wallet not found",
            }
        )
        return

    balance_amount, error_message = get_ovo_wallet_balance(ovo_wallet_account, True)
    if error_message:
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_ovo",
                "account_id": account.id,
                "error": error_message,
            }
        )
        return

    if balance_amount and balance_amount < AUTODEBET_MINIMUM_AMOUNT_PAYMENT:
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_ovo",
                "account_id": account.id,
                "error": "Balance is less than {}".format(AUTODEBET_MINIMUM_AMOUNT_PAYMENT),
            }
        )
        return

    customer = account.customer
    customer_xid = customer.customer_xid
    is_partial = False

    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids).order_by(
        'due_date'
    )
    due_amount = sum(account_payment.due_amount for account_payment in account_payments.iterator())
    due_amount_original = copy.deepcopy(due_amount)

    if due_amount > balance_amount:
        due_amount = balance_amount
        is_partial = True

    if balance_amount == 0:
        due_amount = due_amount_original

    if ovo_wallet_account.max_limit_payment and due_amount > ovo_wallet_account.max_limit_payment:
        due_amount = ovo_wallet_account.max_limit_payment
        is_partial = True

    if due_amount <= 0:
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_ovo",
                "account_id": account.id,
                "error": "Due amount must be greater than zero",
            }
        )
        return

    last_account_payment = account_payments.last()
    today_date = timezone.localtime(timezone.now()).date()
    if (
        last_account_payment.due_date != today_date
        and balance_amount < MINIMUM_BALANCE_AUTODEBET_OVO_DEDUCTION_DPD
    ):
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_dana",
                "account_id": account.id,
                "message": "Non dpd 0 deduction skipped due to balance is lower than minimum",
            }
        )
        return

    # PREVENT CASHBACK FOR LATE PAYMENTS
    is_eligible_benefit = True
    if last_account_payment.due_date < today_date:
        is_eligible_benefit = False

    status = AutodebetOVOPaymentResultStatusConst.PENDING
    status_desc = None
    account_payment = account_payments.first()
    doku_client = get_doku_snap_ovo_client(
        ovo_wallet_account, account=account, account_payment=account_payment, is_autodebet=True
    )
    partner_reference_no = doku_client.generate_reference_no()
    body = {
        "payment_type": "RECURRING",
        "partner_reference_number": partner_reference_no,
        "amount": due_amount,
        "success_url": "https://www.julo.com/ovo-tokenization/payment/success",
        "failed_url": "https://www.julo.com/ovo-tokenization/payment/failed",
    }

    with transaction.atomic(), transaction.atomic(using="repayment_db"):
        ovo_transaction = AutodebetOvoTransaction.objects.create(
            ovo_wallet_account=ovo_wallet_account,
            original_partner_reference_no=partner_reference_no,
            amount=due_amount,
            account_payment_id=account_payment.id,
            is_partial=is_partial,
            status=status,
            status_desc=status_desc,
            is_eligible_benefit=is_eligible_benefit,
        )

        vendor = AutodebetVendorConst.OVO
        PaybackTransaction.objects.create(
            customer=account.customer,
            payback_service='autodebet',
            status_desc='Autodebet {}'.format(vendor),
            transaction_id=partner_reference_no,
            amount=due_amount,
            account=account,
            payment_method=get_autodebet_payment_method(
                account, vendor, AutodebetVendorConst.PAYMENT_METHOD[vendor]
            ),
            is_processed=False,
            transaction_date=timezone.localtime(timezone.now()),
        )

    response_data, error_message = doku_client.payment(body)
    if error_message:
        if response_data['responseCode'] == AutodebetOVOResponseCodeConst.FAILED_INSUFFICIENT_FUND:
            status_desc = OVOErrorCode.INSUFFICIENT_FUND
        elif (
            response_data['responseCode']
            == AutodebetOVOResponseCodeConst.EXCEEDS_TRANSACTION_AMOUNT_LIMIT
        ):
            ovo_wallet_account.update_safely(
                max_limit_payment=AUTODEBET_MAXIMUM_AMOUNT_PAYMENT,
            )
        else:
            status_desc = error_message

    ovo_transaction.update_safely(
        original_reference_no=response_data.get("referenceNo", None),
        status_desc=status_desc,
    )

    if error_message:
        logger.error(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_ovo",
                "error": error_message,
                "account_id": account.id,
            }
        )


def create_debit_payment_process_dana(account_payment_ids, account):
    dana_wallet_account = DanaWalletAccount.objects.filter(
        account=account,
    ).last()
    customer = dana_wallet_account.account.customer
    customer_xid = customer.customer_xid
    device = customer.device_set.last()
    oldest_account_payment = (
        account.accountpayment_set.not_paid_active().order_by('due_date').first()
    )
    balance_amount = get_dana_balance_amount(
        dana_wallet_account, device.android_id, customer_xid, True, account, oldest_account_payment
    )
    dana_wallet_account = DanaWalletAccount.objects.filter(
        account=account, status=DanaWalletAccountStatusConst.ENABLED
    ).last()
    is_partial = False

    if not dana_wallet_account:
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_dana",
                "account_id": account.id,
                "error": "Dana wallet not found",
            }
        )
        return

    if balance_amount is None:
        balance_amount = dana_wallet_account.balance

    if balance_amount is None:
        balance_amount = 0

    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids).order_by(
        'due_date'
    )

    due_amount = sum(account_payment.due_amount for account_payment in account_payments.iterator())
    due_amount_original = copy.deepcopy(due_amount)

    last_account_payment = account_payments.last()
    today_date = timezone.localtime(timezone.now()).date()
    if (
        last_account_payment.due_date != today_date
        and balance_amount < MINIMUM_BALANCE_AUTODEBET_DANA_DEDUCTION_DPD
    ):
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_dana",
                "account_id": account.id,
                "message": "Non dpd 0 deduction skipped due to balance is lower than minimum",
            }
        )
        return

    # PREVENT CASHBACK FOR LATE PAYMENTS
    is_eligible_benefit = True
    if last_account_payment.due_date < today_date:
        is_eligible_benefit = False

    if due_amount > balance_amount:
        due_amount = balance_amount
        is_partial = True

    if balance_amount == 0:
        due_amount = due_amount_original

    if due_amount <= 0:
        logger.info(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_dana",
                "account_id": account.id,
                "error": "Due amount must be greater than zero",
            }
        )
        return

    status_desc = None
    if balance_amount == 0:
        status_desc = DanaErrorCode.INSUFFICIENT_FUND

    account_payment = account_payments.first()
    account_payment_xid = account_payment.account_payment_xid

    if not account_payment_xid:
        account_payment.update_safely(account_payment_xid=str(time.time()).replace('.', '')[:14])
        account_payment_xid = account_payment.account_payment_xid

    dana_linking_autodebet_client = get_dana_autodebet_client(
        account=account,
        account_payment=account_payment,
    )

    status = AutodebetDANAPaymentResultStatusConst.PENDING
    partner_reference_no = dana_linking_autodebet_client._generate_partner_reference_no(
        account_payment_xid
    )
    dana_transaction = AutodebetDanaTransaction.objects.create(
        dana_wallet_account=dana_wallet_account,
        original_partner_reference_no=partner_reference_no,
        amount=due_amount_original,
        account_payment=account_payment,
        is_partial=is_partial,
        status=status,
        status_desc=status_desc,
        is_eligible_benefit=is_eligible_benefit,
    )

    response_data, error_message = dana_linking_autodebet_client.direct_debit_autodebet(
        dana_wallet_account.access_token,
        device.android_id,
        customer_xid,
        partner_reference_no,
        due_amount,
        account_payment.due_date,
    )
    if response_data['responseCode'] == AutodebetDanaResponseCodeConst.FAILED_INSUFFICIENT_FUND:
        status_desc = DanaErrorCode.INSUFFICIENT_FUND
        # no need to handle right now
        # callback will be sent after 3 hours, there will be no racing condition

    dana_transaction.update_safely(
        original_reference_no=response_data.get("referenceNo", None),
        status_desc=status_desc,
    )

    if error_message:
        logger.error(
            {
                "action": "juloserver.autodebet.services.task_services."
                "create_debit_payment_process_dana",
                "error": error_message,
                "account_id": account.id,
            }
        )

import csv
import json
import logging
import typing
from builtins import str
from datetime import time, datetime

import semver
from cacheops import cached_as
from dateutil.relativedelta import relativedelta
from django.db import transaction, connection, connections
from django.db.models import Sum
from django.utils import timezone

from juloserver.account.constants import (
    AccountConstant,
    AccountStatus430CardColorDpd,
    LDDEReasonConst,
    AccountChangeReason,
)
from juloserver.account.constants import FeatureNameConst as AccountFeatureNameConst
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountProperty,
    AccountStatusHistory,
    ExperimentGroup,
    AccountCycleDayHistory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.collection_vendor.constant import Bucket5Threshold
from juloserver.customer_module.services.customer_related import (
    update_cashback_balance_status,
)
from juloserver.fraud_security.constants import FraudFlagType
from juloserver.fraud_security.models import FraudFlag
from juloserver.google_analytics.constants import GAEvent
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    FeatureSetting,
    Loan,
    MobileFeatureSetting,
    SkiptraceHistory,
    CashbackCounterHistory,
    EmailHistory,
)
from juloserver.julo.services import update_is_proven_bad_customers
from juloserver.julo.services2 import get_appsflyer_service
from juloserver.julo.services2.experiment import get_experiment_setting_by_code
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.minisquad.constants import FeatureNameConst as MinisquadFeatureNameConst
from juloserver.julo.clients import get_julo_email_client
from typing import Dict, Any
from juloserver.face_recognition.tasks import store_fraud_face_task

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def process_change_account_status(
    account: Account,
    new_status_code: int,
    change_reason: typing.Optional[str] = None,
    manual_change: bool = False,
) -> typing.Optional[AccountStatusHistory]:
    """
    Update the account status code and store the account status history.
    For every status code changes, we sent the user attribute to ME.

    Args:
        account (Account): The account object.
        new_status_code (int): The new status code.
        change_reason (str): The change reason. Default is None.
        manual_change (bool): Force the account status to move without checking
                              the protected status.

    Returns:
        AccountStatusHistory: Return None if the account status doesn't change.
            Return AccountStatusHistory object if account status changes.
    """
    from juloserver.moengage.tasks import async_update_moengage_for_account_status_change
    from juloserver.autodebet.tasks import suspend_autodebet_deactivated_account_task

    with transaction.atomic():
        old_status_code = account.status_id
        logger_data = {
            'action': 'account.services.account_related.process_change_account_status',
            'account_id': str(account.id),
            'old_status_code': old_status_code,
            'new_status_code': new_status_code,
        }
        if old_status_code == AccountConstant.STATUS_CODE.sold_off:
            logger.info(
                {
                    'message': 'account is selloff account status cannot be moved',
                    **logger_data,
                }
            )
            return

        if old_status_code == new_status_code and change_reason == "refinancing cool off period":
            logger.info(
                {
                    'message': 'update account status history called but seem status not changed',
                    **logger_data,
                }
            )
            return

        if not manual_change and old_status_code in AccountConstant.FRAUD_REJECT_STATUS:
            logger.info(
                {
                    'message': 'terminated or suspended account status cannot be moved',
                    **logger_data,
                }
            )
            return
        account.update_safely(status_id=new_status_code)
        account_status_history_fields = {
            'account': account,
            'status_old_id': old_status_code,
            'status_new_id': new_status_code,
            'change_reason': change_reason,
        }
        if change_reason in ["refinancing cool off period", "R4 cool off period"]:
            account_status_history_fields['is_reactivable'] = True
        account_status_history = AccountStatusHistory.objects.create(
            **account_status_history_fields
        )

        if (
            new_status_code == AccountConstant.STATUS_CODE.suspended
            and change_reason == AccountChangeReason.EXCEED_DPD_THRESHOLD
        ):
            # since we keep status code on 430,
            # no need to trigger code below (moengage)
            logger.info(
                {
                    'message': 'update account status history created',
                    **logger_data,
                }
            )
            return

        if new_status_code in [
            AccountConstant.STATUS_CODE.active,
            AccountConstant.STATUS_CODE.active_in_grace,
            AccountConstant.STATUS_CODE.suspended,
        ]:
            # appsflyer event trigger loan status change
            appsflyer_service = get_appsflyer_service()
            appsflyer_service.info_account_status(account, new_status_code)

            app_instance_id = account.customer.app_instance_id
            if app_instance_id:
                execute_after_transaction_safely(
                    lambda: send_event_to_ga_task_async.apply_async(
                        kwargs={
                            'customer_id': account.customer_id,
                            'event': getattr(GAEvent, 'X' + str(new_status_code)),
                        }
                    )
                )

        if new_status_code == AccountConstant.STATUS_CODE.fraud_reported:
            application = account.last_application
            store_fraud_face_task.delay(
                application.id,
                application.customer_id,
                change_reason,
            )

        if new_status_code >= AccountConstant.STATUS_CODE.deactivated:
            execute_after_transaction_safely(
                lambda: suspend_autodebet_deactivated_account_task.apply_async(
                    kwargs={
                        'account_id': account.id,
                        'account_status': new_status_code,
                    }
                )
            )

        execute_after_transaction_safely(
            lambda: async_update_moengage_for_account_status_change.delay(account_status_history.id)
        )

        return account_status_history


def bad_payment_message(account_status_code, label=None):
    if not account_status_code:
        return None

    bad_payment_setting = MobileFeatureSetting.objects.filter(
        feature_name="bad_payment_message_setting", is_active=True
    ).last()
    if not bad_payment_setting:
        return None

    if not label:
        label = str(account_status_code)
    bad_payment_content = bad_payment_setting.parameters.get(label)

    if not bad_payment_content:
        return None

    return dict(
        title=bad_payment_content['title'],
        content=bad_payment_content['content'],
        button_text=bad_payment_content['button_text'],
        button_action=bad_payment_content['button_action'],
    )


def update_account_status_based_on_account_payment(account_payment, reason_override=''):
    account = account_payment.account
    new_status_code = account_payment.get_status_based_on_due_date()
    previous_account_status_code = account.status_id
    # this if for prevent
    # account bring back to active in grace if have more then 1 account payment
    if previous_account_status_code != AccountConstant.STATUS_CODE.suspended:
        new_account_status_code = None
        new_account_reason = ''
        if new_status_code == PaymentStatusCodes.PAYMENT_1DPD:
            # change status into 421
            new_account_status_code = AccountConstant.STATUS_CODE.active_in_grace
            new_account_reason = 'reach DPD+1 to +4 '
            update_is_proven_bad_customers(account)
        elif (
            PaymentStatusCodes.PAYMENT_5DPD <= new_status_code <= PaymentStatusCodes.PAYMENT_180DPD
        ):
            # change status into 430
            new_account_status_code = AccountConstant.STATUS_CODE.suspended
            new_account_reason = 'reach DPD + 5 ++ '

        if reason_override:
            new_account_reason = reason_override

        if new_account_status_code:
            process_change_account_status(account, new_account_status_code, new_account_reason)
            update_cashback_balance_status(account.customer)


def update_account_app_version(account, app_version):
    if not app_version:
        app_version = '5.0.0'
    if not account:
        return
    is_new_app_version = True
    if account.app_version:
        is_new_app_version = semver.match(app_version, ">%s" % account.app_version)

    if is_new_app_version:
        account.update_safely(app_version=app_version)


def get_dpd_and_lock_colour_by_account(account):
    if not account:
        return None, None

    setting = MobileFeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name=AccountFeatureNameConst.ACCOUNT_STATUS_X430_COLOR,
    )
    if not setting:
        return None, None

    if account.status_id != AccountConstant.STATUS_CODE.suspended:
        return None, None

    dpd = account.dpd
    parameters = setting.parameters
    if 5 <= dpd <= 10:
        return (
            parameters['dpd_color'][AccountStatus430CardColorDpd.FIVE_TO_TEN],
            parameters['lock_color'][AccountStatus430CardColorDpd.FIVE_TO_TEN],
        )
    if dpd >= 11:
        return (
            parameters['dpd_color'][AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN],
            parameters['lock_color'][AccountStatus430CardColorDpd.MORE_THAN_EQUAL_ELEVEN],
        )

    return None, None


def is_bucket_5_feature_threshold_forever():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EVER_ENTERED_B5_J1_EXPIRED_CONFIGURATION, is_active=True
    ).last()

    if not feature_setting:
        return False

    parameter = feature_setting.parameters
    valid_days_threshold = parameter['entered_b5_valid_for']
    if valid_days_threshold == 'forever':
        return True

    return False


def update_ever_entered_b5_account_level_base_on_account_payment(account_payment):
    account = account_payment.account
    oldest_account_payment = account.get_oldest_unpaid_account_payment()
    last_loan = account.loan_set.order_by('cdate').last()
    if account_payment != oldest_account_payment:
        return

    if oldest_account_payment.dpd < Bucket5Threshold.DPD_REACH_BUCKET_5:
        return

    today = timezone.localtime(timezone.now())
    account_updated_fields = dict(ever_entered_B5=True)
    # will update the timestamp if the last loan ever entered B5 False
    # because will update the timestamp once it reach the dpd 91 and setting on
    # feature setting is not forever if forever then update every reach dpd 91
    if (
        is_bucket_5_feature_threshold_forever()
        or not account.ever_entered_B5
        or not last_loan.ever_entered_B5
    ):
        account_updated_fields["ever_entered_B5_timestamp"] = today

    account.update_safely(**account_updated_fields)
    # update all active loans
    account.loan_set.filter(
        loan_status__status_code__range=(LoanStatusCodes.CURRENT, LoanStatusCodes.RENEGOTIATED)
    ).update(ever_entered_B5=True)


def is_new_loan_part_of_bucket5(account):
    if not account:
        return False

    if not account.ever_entered_B5:
        return False

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EVER_ENTERED_B5_J1_EXPIRED_CONFIGURATION, is_active=True
    ).last()

    if not feature_setting:
        return False

    parameter = feature_setting.parameters
    valid_days_threshold = parameter['entered_b5_valid_for']
    if valid_days_threshold == 'forever':
        return True

    valid_days_threshold = int(parameter['entered_b5_valid_for'])
    today_date = timezone.localtime(timezone.now()).date()
    if account.ever_entered_B5_timestamp:
        ever_entered_b5_timestamp = timezone.localtime(account.ever_entered_B5_timestamp).date()
        expire_time_in_b5 = ever_entered_b5_timestamp + relativedelta(days=valid_days_threshold)
        if today_date <= expire_time_in_b5:
            return True

    return False


def is_account_limit_sufficient(loan_amount, account_id):
    account_limit = AccountLimit.objects.filter(account_id=account_id).last()
    if not account_limit:
        raise Exception("Account limit not found for account id {}".format(account_id))

    return account_limit.available_limit >= loan_amount


def get_loan_amount_dict_by_account_ids(account_ids):
    queryset = (
        Loan.objects.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lte=LoanStatusCodes.LOAN_180DPD,
            account_id__in=account_ids,
        )
        .values('account_id')
        .annotate(total_loan_amount=Sum('loan_amount'))
    )

    return {loan['account_id']: loan['total_loan_amount'] for loan in queryset.iterator()}


def get_latest_loan_dict_by_account_ids(account_ids, fields=None):
    queryset = (
        Loan.objects.filter(account_id__in=account_ids)
        .distinct('account_id')
        .order_by('account_id', '-cdate')
    )

    if fields:
        fields.append('account_id')
        queryset = queryset.only(*fields)

    return {loan.account_id: loan for loan in queryset.iterator()}


def get_latest_application_dict_by_account_ids(account_ids, fields=None, select_related=None):
    queryset = (
        Application.objects.filter(account_id__in=account_ids)
        .distinct('account_id')
        .order_by('account_id', '-cdate')
    )

    if fields:
        fields.append('account_id')
        queryset = queryset.only(*fields)

    if select_related:
        queryset = queryset.select_related(*select_related)

    return {application.account_id: application for application in queryset.iterator()}


def get_account_property_by_account(account):
    @cached_as(AccountProperty.objects.filter(account=account.id))
    def _get_account_property_by_account():
        account_property = (
            AccountProperty.objects.filter(account=account.id).select_related('account').last()
        )
        return account_property

    return _get_account_property_by_account()


def get_experiment_group_data(code, account_id):
    experiment_setting, experiment_group = None, None
    experiment_setting = get_experiment_setting_by_code(code)
    if not experiment_setting:
        return experiment_setting, experiment_group

    experiment_group = ExperimentGroup.objects.filter(
        experiment_setting=experiment_setting.id, account_id=account_id
    ).last()
    if not experiment_group:
        return experiment_setting, experiment_group

    return experiment_setting, experiment_group


def register_accounts_late_fee_experiment(path_file, experiment_setting):
    batch_size = 500
    chunk_size = 2500
    data_to_insert = []
    account_ids = set()
    with open(path_file, 'r') as csvfile:
        csv_rows = csv.DictReader(csvfile, delimiter=',')
        rows = [r for r in csv_rows]

    for row in rows:
        group = row['experiment_group'].lower()
        account_id = row['account_id']
        # handle duplicate data when data not yet inserted
        if account_id not in account_ids:
            if group not in ('control', 'experiment'):
                continue
            account = Account.objects.get_or_none(pk=account_id)
            if not account:
                continue
            if ExperimentGroup.objects.filter(
                experiment_setting=experiment_setting.id, account_id=account_id
            ).exists():
                continue
            data = {
                'account': account,
                'experiment_setting': experiment_setting,
                'group': group,
            }
            data_to_insert.append(ExperimentGroup(**data))
            account_ids.add(account_id)

        if len(data_to_insert) == chunk_size:
            ExperimentGroup.objects.bulk_create(data_to_insert, batch_size)
            data_to_insert = []
            account_ids = set()

    if data_to_insert:
        ExperimentGroup.objects.bulk_create(data_to_insert, batch_size)


def is_account_hardtoreach(account_id: int) -> bool:
    last_account_payment = AccountPayment.objects.filter(
        account=account_id, status__gte=PaymentStatusCodes.PAID_ON_TIME
    ).last()

    if not last_account_payment:
        return False

    if last_account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME:
        return False

    get_call_dates_sql = """
        SELECT start_ts::date as call_date
        FROM skiptrace_history
        WHERE account_id = %s
        GROUP BY 1
        ORDER BY 1 DESC
        LIMIT 3;
    """

    with connection.cursor() as cursor:
        cursor.execute(get_call_dates_sql, [account_id])
        get_few_call_dates = cursor.fetchall()

    if not get_few_call_dates:
        return False

    start_call_date = datetime.combine(get_few_call_dates[-1][0], time.min)
    end_call_date = datetime.combine(get_few_call_dates[0][0], time(23, 59, 59, 999999))

    contact_call_results = [
        'PTPR',
        'RPC',
        'RPC - Regular',
        'RPC - PTP',
        'RPC - HTP',
        'RPC - Broken Promise',
        'RPC - Call Back',
    ]

    if SkiptraceHistory.objects.filter(
        account_id=account_id,
        start_ts__range=(start_call_date, end_call_date),
        call_result__name__in=contact_call_results,
    ).exists():
        return False

    return True


def execute_query(cursor, query, parameters=None):
    cursor.execute(query, parameters)
    row = cursor.fetchone()
    return dict(zip([col[0] for col in cursor.description], row)) if row else {}


def get_fdc_data_from_bureau_db(application_id: int):
    fdc_data = {}
    try:
        with transaction.atomic(using='bureau_db'), connections['bureau_db'].cursor() as cursor:
            query = 'SELECT * FROM ana.calculate_cycle_day_fdc_v2(%s)'
            return execute_query(cursor, query, (application_id,))
    except Exception as e:
        sentry_client.captureException()
        logger.error({'action': 'get_fdc_data_from_bureau_db', 'errors': str(e)})

    return fdc_data


def calculate_cycle_day_from_ana(fdc_data: dict):
    data = {}
    if not fdc_data:
        return data
    try:
        application_id = fdc_data['application_id']
        dpd_max = fdc_data['dpd_max']
        tgl_jatuh_tempo_pinjaman = str(fdc_data['tgl_jatuh_tempo_pinjaman'])
        tgl_penyaluran_dana = str(fdc_data['tgl_penyaluran_dana'])

        with transaction.atomic(), connections['default'].cursor() as cursor:
            query = 'SELECT * FROM ana.calculate_cycle_day_v2(%s, %s, %s, %s)'
            return execute_query(
                cursor,
                query,
                (application_id, dpd_max, tgl_jatuh_tempo_pinjaman, tgl_penyaluran_dana),
            )
    except Exception as e:
        sentry_client.captureException()
        logger.error({'action': 'calculate_cycle_day_from_ana', 'errors': str(e)})

    return data


def get_data_from_ana_calculate_cycle_day(application_id: int):
    fdc_data = get_fdc_data_from_bureau_db(application_id)
    return calculate_cycle_day_from_ana(fdc_data)


def create_account_cycle_day_history(
    params: dict, account: Account, reason: str, old_cycle_day: int,
    application_id: int, auto_adjust_changes: dict = None
):
    """
    Create history, and update latest_flag when cycle_day changes
        ::params: get from get_data_from_ana_calculate_cycle_day(application_id)
        ::account: the account that we change cycle day
        ::reason: can be "LDDE v1", "LDDE v2", "Manual"
        ::old_cycle_day: the old cycle_day of the account
        ::application_id: application_id of the account
    """
    data = dict(
        account_id=account.pk,
        application_id=application_id,
        old_cycle_day=old_cycle_day,
        new_cycle_day=account.cycle_day,
        reason=reason,
        parameters=json.dumps(params, default=str),
        auto_adjust_changes=json.dumps(auto_adjust_changes or {}, default=str)
    )

    # end_date is the end of the previous cycle day
    AccountCycleDayHistory.objects.filter(account_id=account.pk, latest_flag=True).update(
        latest_flag=False, end_date=timezone.localtime(timezone.now()).date()
    )

    AccountCycleDayHistory.objects.create(**data)


def get_detail_cashback_counter_history(account_payment_id):
    cashback_history = CashbackCounterHistory.objects.filter(account_payment_id=account_payment_id)
    if not cashback_history.exists():
        return None

    cashback_history = cashback_history.filter(counter__gt=0)
    if not cashback_history.exists():
        return dict(streak_level=0, amount=0)

    total_of_cashback_earned = (
        cashback_history.select_related('payment').aggregate(
            total_cashback_earned=Sum('payment__cashback_earned')
        )['total_cashback_earned']
        or 0
    )
    last_cashback_history = cashback_history.values('counter', 'cashback_percentage').last()
    streak_bonus = int(last_cashback_history.get('cashback_percentage', 0) * 100)
    return dict(
        streak_level=last_cashback_history.get('counter', 0),
        streak_bonus=streak_bonus,
        amount=total_of_cashback_earned,
    )


def update_cashback_counter_account(account_payment, is_reversal=False, paid_date=None, counter=0):
    from juloserver.account.tasks.account_task import update_cashback_counter_account_task

    fn_name = 'update_cashback_counter_account'
    logger.info({'action': fn_name, 'message': 'function begin'})
    update_cashback_counter_account_task(account_payment.id, is_reversal, paid_date, counter)
    logger.info({'action': fn_name, 'message': 'function finish'})


def risky_change_phone_activity_check(loan, application):
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history

    if FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RISKY_CHANGE_PHONE_ACTIVITY_CHECK, is_active=True
    ).exists():
        if (
            application.is_julo_one_product()
            and application.status == ApplicationStatusCodes.LOC_APPROVED
            and not application.account.loan_set.exclude(id=loan.id).exists()
        ):
            if FraudFlag.objects.filter(
                fraud_type=FraudFlagType.CHANGE_PHONE_ACTIVITY, customer=loan.customer
            ).exists():
                with transaction.atomic():
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
                        change_reason="CPA detected before first transact",
                    )
                    process_change_account_status(
                        loan.account,
                        new_status_code=AccountConstant.STATUS_CODE.fraud_reported,
                        change_reason="CPA detected before first transact",
                    )
                return True
        return False
    return False


def get_user_timezone(postal_code):
    from juloserver.julo.constants import AddressPostalCodeConst

    selected_timezone_key = 'WIB'
    for timezone_key, postal_codes in AddressPostalCodeConst.INDONESIAN_TIMEZONE.items():
        if any(postal_code in postal_range for postal_range in postal_codes):
            selected_timezone_key = timezone_key
            break

    return AddressPostalCodeConst.PYTZ_TIME_ZONE_ID[selected_timezone_key]


def do_update_user_timezone(account):
    if not account:
        return
    # Example: Set the timezone to the current timezone.
    # You can modify this logic to determine the appropriate timezone
    # based on the user's location or any other criteria.
    application = account.last_application
    if not application:
        return

    if not application.address_kodepos:
        # set default value into WIB
        postal_code = '20111'
    else:
        postal_code = application.address_kodepos

    account.user_timezone = get_user_timezone(int(postal_code))
    account.save()


def update_cycle_day_history(
    account, reason, old_cycle_day, ana_cycle_day_data, application_id, auto_adjust_changes
):
    ldde_history = AccountCycleDayHistory.objects.get_or_none(
        account_id=account.pk,
        latest_flag=True,
    )
    ldde_history_reason = ldde_history.reason if ldde_history else LDDEReasonConst.LDDE_V1
    not_dup_old_cycle_day = ldde_history.old_cycle_day != old_cycle_day if ldde_history else True

    if (
        account.is_ldde
        and not_dup_old_cycle_day
        and (old_cycle_day != account.cycle_day or reason != ldde_history_reason)
    ):
        # if cycle date same but reason changed (v1 to v2), also create history
        create_account_cycle_day_history(
            ana_cycle_day_data, account, reason, old_cycle_day,
            application_id, auto_adjust_changes
        )


def is_account_permanent_risk_block(account, is_from_scheduler=False):
    block_permanent_feature = FeatureSetting.objects.filter(
        feature_name=MinisquadFeatureNameConst.PERMANENT_RISK_BLOCK_CUSTOMER_DISBURSEMENT,
        is_active=True,
    ).last()
    if not block_permanent_feature:
        return False
    block_permanent_dpd = block_permanent_feature.parameters.get('dpd_threshold', 90)
    account_payments_paid_off = account.accountpayment_set.filter(
        status_id__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
    )
    if not account_payments_paid_off:
        return False

    for account_payment in account_payments_paid_off.iterator():
        due_date = account_payment.due_date
        paid_date = account_payment.paid_date or None
        status_code = account_payment.status

        if not paid_date:
            account_payment_history = account_payment.accountpaymentstatushistory_set.filter(
                status_new=status_code
            ).last()
            if not account_payment_history:
                continue

            paid_date = account_payment_history.cdate.date()

        dpd_paid = paid_date - due_date
        if dpd_paid.days > block_permanent_dpd:
            return True

    return False


def trigger_send_email_suspension(account: Account) -> None:
    customer = account.customer
    try:
        julo_email_client = get_julo_email_client()
        application = account.last_application
        context = get_suspension_email_context(account)

        _, headers, subject, msg, _ = julo_email_client.email_notify_loan_suspension_j1(
            context, customer.email
        )
        template = "julo_risk_suspension_email_information.html"

        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=template,
        )

        logger.info(
            {
                "action": "trigger_send_email_suspension",
                "customer_id": customer.id,
                "template": template,
            }
        )

    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'trigger_send_email_suspension',
                'data': {'customer_id': customer.id},
                'response': "failed to send email",
                'error': e,
            }
        )


def get_suspension_email_context(account: Account) -> Dict[str, Any]:
    customer = account.customer
    context = {
        'fullname': customer.fullname,
    }
    return context


def trigger_send_email_reactivation(account_id: str) -> None:
    account = Account.objects.get_or_none(id=account_id)
    customer = account.customer
    template = "email_notify_back_to_420.html"
    from juloserver.graduation.services import is_customer_suspend

    is_suspend, lock_reason = is_customer_suspend(customer.id)
    try:
        if is_suspend:
            logger.info(
                {
                    "action": "trigger_send_email_reactivation",
                    "customer_id": customer.id,
                    "template": template,
                    "message": "suspended customer: {}".format(lock_reason),
                }
            )
            return
        julo_email_client = get_julo_email_client()
        application = account.last_application
        context = get_reactivation_email_context(account)

        (
            _,
            headers,
            subject,
            msg,
            _,
        ) = julo_email_client.email_notify_loan_reactivation_j1(context, customer.email)

        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=template,
        )

        logger.info(
            {
                "action": "trigger_send_email_reactivation",
                "customer_id": customer.id,
                "template": template,
            }
        )

    except Exception as e:
        sentry_client.captureException()
        logger.error(
            {
                'action': 'trigger_send_email_reactivation',
                'data': {'customer_id': customer.id},
                'response': "failed to send email",
                'error': e,
            }
        )


def get_reactivation_email_context(account: Account) -> Dict[str, Any]:
    customer = account.customer
    context = {
        'fullname': customer.fullname,
    }
    return context


def is_account_exceed_dpd_threshold(account: Account) -> bool:
    return (
        account.status_id == AccountConstant.STATUS_CODE.suspended
        and AccountStatusHistory.objects.filter(
            account=account, change_reason=AccountChangeReason.EXCEED_DPD_THRESHOLD
        ).exists()
    )

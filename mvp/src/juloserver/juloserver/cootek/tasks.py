from __future__ import absolute_import

import secrets
from builtins import str
import logging
from celery import task
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.utils import timezone
from datetime import datetime, timedelta

from juloserver.julo.models import (
    CootekRobocall,
    Customer,
    ExperimentSetting,
    FeatureSetting,
)
from juloserver.julo.constants import ExperimentConst, FeatureNameConst
from juloserver.cootek.services import (
    create_task_to_send_data_customer_to_cootek,
    get_details_task_from_cootek,
    change_field_from_previous_cootek_for_first_round_in_cootek,
    get_payment_details_cootek_for_centerix,
    get_today_data_with_specific_cootek_intention,
    update_cootek_data,
    upload_payment_details,
    get_payment_details_cootek_for_intelix,
    get_payment_details_for_intelix,
    process_upload_j1_jturbo_t0_to_intelix,
)
from juloserver.cootek.clients import get_julo_cootek_client
from .utils import convert_gender
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from ..julo.clients import get_julo_sentry_client
from juloserver.julo.utils import format_e164_indo_phone_number
from ..julo.exceptions import JuloException
from ..minisquad.clients import get_julo_intelix_client
from ..minisquad.constants import IntelixTeam, DialerTaskType, DialerTaskStatus, RedisKey
from ..minisquad.models import DialerTask
from juloserver.cootek.models import (
    CootekConfiguration,
    CootekRobot,
)
from ..minisquad.services2.intelix import (
    construct_data_for_intelix,
    create_history_dialer_task_event,
    record_intelix_log,
)
from juloserver.monitors.notifications import (
    send_slack_bot_message,
    send_message_normal_format,
)
from juloserver.cootek.constants import (
    CootekAIRobocall,
    LoanIdExperiment,
)
from juloserver.streamlined_communication.services import is_holiday
from juloserver.streamlined_communication.utils import payment_reminder_execution_time_limit
from juloserver.minisquad.constants import FeatureNameConst as MiniSquadFeatureSettingConst
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model

logger = logging.getLogger(__name__)


@task(queue='collection_high')
def get_token_authentication_from_cootek():
    cootek_client = get_julo_cootek_client()
    cootek_client.refresh_token()


@task(queue='collection_high')
def get_tasks_from_db_and_schedule_cootek():
    is_holiday_today = is_holiday()
    if is_holiday_today:
        logger.info({
            'action': 'get_tasks_from_db_and_schedule_cootek',
            'is_holiday': is_holiday_today,
            'message': 'Cootek configuration skipped due to holiday.'
        })
        return

    # update 'cootek_configuration.from_previous_cootek_result' column to 'False'
    change_field_from_previous_cootek_for_first_round_in_cootek()
    configuration = CootekConfiguration.objects.filter(
        is_active=True).order_by('task_type', 'time_to_start')
    now = timezone.localtime(timezone.now())

    for config in configuration:
        start_time = config.time_to_start
        if start_time is None:
            continue
        start_time = str(start_time)
        start_time = str(now.date()) + ' ' + start_time
        start_time = datetime.strptime(start_time, "%Y-%m-%d %X")
        time_to_prepare = start_time - timedelta(minutes=10)
        if config.time_to_prepare:
            time_to_prepare = datetime.strptime(
                str(now.date()) + ' ' + str(config.time_to_prepare), "%Y-%m-%d %X")
        time_to_query_result = start_time + timedelta(minutes=70)
        end_time = start_time + timedelta(hours=1)
        if config.time_to_end:
            end_time = datetime.strptime(
                str(now.date()) + ' ' + str(config.time_to_end), "%Y-%m-%d %X")
            time_to_query_result = end_time + timedelta(minutes=10)

        if config.is_unconnected_late_dpd:
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.COOTEK_LATE_DPD_SETTING,
                is_active=True
            ).last()
            if feature_setting:
                query_result_time = feature_setting.parameters[
                    config.unconnected_late_dpd_time]
                query_result_time = query_result_time + 10
                time_to_query_result = start_time + timedelta(minutes=query_result_time)

        logger.info({
            'action': 'get_tasks_from_db_and_schedule_cootek',
            'start_time': start_time,
            'end_time': end_time,
            'cootek_configuration_id': config.id,
            'cootek_configuration_name': config.strategy_name,
        })
        countdown_send_data = (time_to_prepare - now.replace(tzinfo=None)).total_seconds()
        countdown_get_data = (time_to_query_result - now.replace(tzinfo=None)).total_seconds()
        task_to_send_data_customer_to_cootek.apply_async((config.id, start_time, end_time,),
                                                         countdown=countdown_send_data)
        get_details_of_task_from_cootek.apply_async(
            kwargs={'cootek_record_id': config.id, 'start_time': start_time},
            countdown=countdown_get_data)


@task(queue='collection_high')
@payment_reminder_execution_time_limit
def task_to_send_data_customer_to_cootek(cootek_record_id, start_time, end_time=None):
    logger.info({
        'action': 'task_to_send_data_customer_to_cootek',
        'start_time': start_time,
        'end_time': end_time,
        'cootek_configuration_id': cootek_record_id,
        'time_execute': timezone.localtime(timezone.now()),
    })
    cootek_record = CootekConfiguration.objects.get(id=cootek_record_id)
    create_task_to_send_data_customer_to_cootek(cootek_record, start_time, end_time)
    slack_message = "*Tasktype - {}* - task_to_send_data_customer_to_cootek (cootek_config_id - {}, start_time - {})".format(
        str(cootek_record.task_type), str(cootek_record_id), str(start_time))
    send_slack_bot_message('alerts-comms-prod-cootek', slack_message)


@task(queue='collection_high')
def get_details_of_task_from_cootek(**kwargs):
    retries_time = get_details_of_task_from_cootek.request.retries
    cootek_record_id, start_time = kwargs.get('cootek_record_id'), kwargs.get('start_time')
    # this mock url is for testing purpose so we can set the timeout
    mock_url = kwargs.get('mock_url')
    if not cootek_record_id or not start_time:
        logger.error({
            'action': 'get_details_of_task_from_cootek',
            'time_execute': timezone.localtime(timezone.now()),
            'error_message': "cannot process task because cootek record id or start_time is null"
        })
        return
    logger.info({
        'action': 'get_details_of_task_from_cootek',
        'time_to_get': start_time,
        'cootek_configuration_id': cootek_record_id,
        'time_execute': timezone.localtime(timezone.now()),
        'retries_times': retries_time
    })
    cootek_record = CootekConfiguration.objects.get(id=cootek_record_id)
    try:
        get_details_task_from_cootek(
            cootek_record, start_time, retries_times=retries_time, mock_url=mock_url)
    except Exception as error:
        if retries_time >= \
                get_details_of_task_from_cootek.max_retries:
            # send message to slack alert
            header = "<!here>\n"
            setting_env = settings.ENVIRONMENT.upper()
            if setting_env != 'PROD':
                header = "<!here>\n Testing Purpose from {}\n".format(setting_env)

            message = "Error when try get call results for " \
                      "campaign {} from cootek with this error: {}".format(
                (cootek_record.task_type + '-' + str(cootek_record.time_to_start)), str(error))
            formated_message = "{} ```{}```".format(header, message)
            send_message_normal_format(formated_message, channel='#cootek-failure-call-results')
            get_julo_sentry_client().captureException()
            return
        raise get_details_of_task_from_cootek.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'cootek_record_id': cootek_record_id, 'start_time': start_time, 'mock_url': mock_url
            }
        )


@task(queue='collection_high')
def cancel_phone_call_for_payment_paid_off(cootek_robocall_id):
    fn_name = 'cancel_phone_call_for_payment_paid_off'
    logger.info(
        {
            'action': fn_name,
            'cootek_robocall_id': cootek_robocall_id,
            'message': 'task begin',
        }
    )

    account_payment_form_cootek = CootekRobocall.objects.filter(pk=cootek_robocall_id).last()
    if account_payment_form_cootek:
        cootek_robocall_detokenized = collection_detokenize_sync_object_model(
            PiiSource.COOTEK_ROBOCALL,
            account_payment_form_cootek,
            None,
            ['call_to'],
            PiiVaultDataType.KEY_VALUE,
        )
        task_id = account_payment_form_cootek.task_id
        call_to = cootek_robocall_detokenized.call_to
        cootek_client = get_julo_cootek_client()
        cootek_client.cancel_phone_call_for_payment_paid_off(task_id, call_to)
        logger.info(
            {
                'action': fn_name,
                'cootek_robocall_id': cootek_robocall_id,
                'message': 'task finish',
            }
        )
        return

    logger.warning(
        {
            'action': fn_name,
            'cootek_robocall_id': cootek_robocall_id,
            'message': "there's no data from cootek robocall",
        }
    )
    return


@task(queue='collection_high')
def upload_julo_t0_cootek_data_to_centerix():
    payments = get_payment_details_cootek_for_centerix(0)
    if len(payments) == 0:
        logger.error({
            "action": "upload_julo_t0_data_to_centerix",
            "error": "error upload t0 data to centerix because payment list not exist"
        })
        return

    response = upload_payment_details(payments, 'JULO_T0')

    logger.info({
        "action": "upload_julo_t0_data_to_centerix",
        "response": response
    })


@task(queue='collection_high')
def upload_julo_t0_cootek_data_to_intelix():
    from juloserver.minisquad.services2.dialer_related import is_eligible_sent_to_intelix

    if not is_eligible_sent_to_intelix(0):
        logger.info({
            "action": "upload_julo_t0_cootek_data_to_intelix",
            "info": "constuct and send data with other dialer system"
        })
        upload_jturbo_t0_cootek_data_to_intelix.delay()
        return

    logger.info({
        "action": "upload_julo_t0_cootek_data_to_intelix",
        "info": "task begin"
    })
    today = datetime.now().date()
    check_intelix_experiment = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today
    )
    if check_intelix_experiment:
        logger.info({
            'msg': 'Skip this job during intelix experiment',
            'action': __name__,
        })
        return
    feature_setting = FeatureSetting.objects.filter(
        feature_name=MiniSquadFeatureSettingConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
        is_active=True
    ).last()
    split_threshold = 500
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get(IntelixTeam.JULO_T0) or 500
    process_upload_j1_jturbo_t0_to_intelix(
        bucket_name=IntelixTeam.JULO_T0,
        dialer_type=DialerTaskType.UPLOAD_JULO_T0,
        function_str='upload_julo_t0_cootek_data_to_intelix',
        split_threshold=split_threshold,
        is_jturbo=False
    )


@task(queue='collection_high')
def upload_jturbo_t0_cootek_data_to_intelix():
    from juloserver.minisquad.services2.dialer_related import is_eligible_sent_to_intelix

    if not is_eligible_sent_to_intelix(0, is_jturbo=True):
        logger.info({
            "action": "upload_jturbo_t0_cootek_data_to_intelix",
            "info": "constuct and send data with other dialer system"
        })
        return

    logger.info({
        "action": "upload_jturbo_t0_cootek_data_to_intelix",
        "info": "task begin"
    })
    today = datetime.now().date()
    check_intelix_experiment = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today
    )
    if check_intelix_experiment:
        logger.info({
            'msg': 'Skip this job during intelix experiment',
            'action': __name__,
        })
        return
    feature_setting = FeatureSetting.objects.filter(
        feature_name=MiniSquadFeatureSettingConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
        is_active=True
    ).last()
    split_threshold = 500
    if feature_setting:
        feature_parameters = feature_setting.parameters
        split_threshold = feature_parameters.get(IntelixTeam.JTURBO_T0) or 500
    process_upload_j1_jturbo_t0_to_intelix(
        bucket_name=IntelixTeam.JTURBO_T0,
        dialer_type=DialerTaskType.UPLOAD_JTURBO_T0,
        function_str='upload_jturbo_t0_cootek_data_to_intelix',
        split_threshold=split_threshold,
        is_jturbo=True
    )


@task(queue='collection_high')
def upload_partial_cootek_data_to_intelix_t0_00_33():
    dpd, loan_ids = 0, LoanIdExperiment.GROUP_1
    payments = get_payment_details_cootek_for_intelix(dpd, loan_ids=loan_ids)

    if not payments:
        logger.error({
            "action": 'upload_partial_cootek_data_to_intelix',
            "error": "payment list not exist"
        })
        upload_partial_cootek_data_to_intelix_t0_34_66.delay()
        return

    upload_partial_cootek_data_to_intelix(dpd, loan_ids, payments)
    upload_partial_cootek_data_to_intelix_t0_34_66.delay()


@task(queue='collection_high')
def upload_partial_cootek_data_to_intelix_t0_34_66():
    dpd, loan_ids = 0, LoanIdExperiment.GROUP_2
    payments = get_payment_details_for_intelix(dpd, loan_ids)

    if not payments:
        logger.error({
            "action": 'upload_partial_cootek_data_to_intelix',
            "error": "payment list not exist"
        })
        upload_partial_cootek_data_to_intelix_t0_67_99.delay()
        return

    upload_partial_cootek_data_to_intelix(dpd, loan_ids, payments)
    upload_partial_cootek_data_to_intelix_t0_67_99.delay()


@task(queue='collection_high')
def upload_partial_cootek_data_to_intelix_t0_67_99():
    dpd, loan_ids = 0, LoanIdExperiment.GROUP_3
    payments = get_payment_details_cootek_for_intelix(dpd, loan_ids=loan_ids)

    if not payments:
        logger.error({
            "action": 'upload_partial_cootek_data_to_intelix',
            "error": "payment list not exist"
        })
        upload_partial_cootek_data_to_intelix_t0_67_99.delay()
        return

    upload_partial_cootek_data_to_intelix(dpd, loan_ids, payments)
    upload_partial_cootek_data_to_intelix_tminus1_67_90.delay()


@task(queue='collection_high')
def upload_partial_cootek_data_to_intelix_tminus1_67_90():
    dpd, loan_ids = -1, LoanIdExperiment.GROUP_3
    payments = get_payment_details_cootek_for_intelix(dpd, loan_ids=loan_ids)

    if not payments:
        logger.error({
            "action": 'upload_partial_cootek_data_to_intelix',
            "error": "payment list not exist"
        })
        upload_partial_cootek_data_to_intelix_t0_67_99.delay()
        return
    upload_partial_cootek_data_to_intelix(dpd, loan_ids, payments)
    upload_partial_cootek_data_to_intelix_tminus2_67_99.delay()


@task(queue='collection_high')
def upload_partial_cootek_data_to_intelix_tminus2_67_99():
    dpd, loan_ids = -2, LoanIdExperiment.GROUP_3
    payments = get_payment_details_cootek_for_intelix(dpd, loan_ids=loan_ids)

    if not payments:
        logger.error({
            "action": 'upload_partial_cootek_data_to_intelix',
            "error": "payment list not exist"
        })
        return

    upload_partial_cootek_data_to_intelix(dpd, loan_ids, payments)


@task(queue='collection_high')
def upload_partial_cootek_data_to_intelix(dpd, loan_ids, payments):
    today = datetime.now().date()
    check_intelix_experiment = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today
    )

    if not check_intelix_experiment:
        logger.info({
            'msg': 'The experiment is expired',
            'action': 'upload_partial_cootek_data_to_intelix',
        })
        return

    task_type = DialerTaskType.SHARED_BUCKET_T + str(dpd)
    dialer_task = DialerTask.objects.create(type=task_type)
    create_history_dialer_task_event(dict(dialer_task=dialer_task))

    create_history_dialer_task_event(dict(
        dialer_task=dialer_task,
        status=DialerTaskStatus.QUERIED,
        data_count=len(payments)
    ))

    data_to_send = construct_data_for_intelix(payments, [], IntelixTeam.SHARED_BUCKET)
    intelix_client = get_julo_intelix_client()
    response = intelix_client.upload_to_queue(data_to_send)

    if response['result'].lower() == 'success':
        record_intelix_log(payments, task_type, dialer_task)
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.SENT,
            data_count=response['rec_num']
        ))

    logger.info({
        "action": 'upload_partial_cootek_data_to_intelix',
        "response": response
    })


@task(queue='collection_high')
def trigger_experiment_cootek_config(disable=True):
    experiment_settings = CootekConfiguration.objects.filter(
        strategy_name__contains='EXPERIMENT', product='mtl')

    normal_settings = CootekConfiguration.objects.filter(
        product='mtl').exclude(strategy_name__contains='EXPERIMENT')

    if disable:
        experiment_settings.update(is_active=False)
        normal_settings.update(is_active=True)
    else:
        special_setting = CootekConfiguration.objects.filter(
            strategy_name__contains='EXPERIMENT',
            product='mtl',
            called_at=0,
            task_type__contains=LoanIdExperiment.GROUP_2
        )

        experiment_settings.update(is_active=True)
        special_setting.update(is_active=False)
        normal_settings.update(is_active=False)


@task(bind=True, queue='collection_cootek')
@payment_reminder_execution_time_limit
def process_call_customer_via_cootek(self, source: str, call_customer_request_data: dict):
    """
    Process call customer via cootek
    Args:
        self: Task instance
        source (str): Source of the request
        call_customer_request_data (dict): This data is validate_data from
                    juloserver.integapiv1.serializers.CallCustomerCootekRequestSerializer

    Returns:
        None
    """
    logger_data = {
        "action": "process_call_customer_via_cootek",
        "task_id": self.request.id,
    }

    task_type = call_customer_request_data['data']['task_type']
    cootek_robot = None
    is_created = False
    try:
        cootek_robot, is_created = CootekRobot.objects.get_or_create(
            robot_identifier=call_customer_request_data['data']['robot_id'],
            is_group_method=call_customer_request_data['data'].get('is_group_method', False),
            defaults={'robot_name': task_type},
        )
    except MultipleObjectsReturned:
        # Skip if there is duplicate row in the database this happens when concurrent task.
        get_julo_sentry_client().captureException()
        pass

    if is_created or cootek_robot is None:
        # Always get the first element to mitigate duplicate row in the database.
        # So that the latest created will not be used at all.
        cootek_robot = CootekRobot.objects.filter(
            robot_identifier=call_customer_request_data['data']['robot_id'],
            is_group_method=call_customer_request_data['data'].get('is_group_method', False),
        ).first()

    campaign_id = call_customer_request_data['campaign_data']['campaign_id']

    now = timezone.localtime(timezone.now())
    repeat_number = call_customer_request_data['data'].get('attempt', 3)
    start_time = call_customer_request_data['data']['start_time']
    start_at = now.replace(
        hour=start_time.hour, minute=start_time.minute, second=start_time.second, microsecond=0
    )
    end_time = call_customer_request_data['data']['end_time']
    end_at = now.replace(
        hour=end_time.hour, minute=end_time.minute, second=end_time.second, microsecond=0
    )

    task_name = "{}|{}|{}|{}".format(source, campaign_id, secrets.token_hex(8), task_type)
    if settings.ENVIRONMENT != 'prod':
        task_name = settings.ENVIRONMENT + "|" + task_name
    task_name = task_name[:63]  # Cootek limitation

    customer_request_data = call_customer_request_data['customers']
    task_details = []

    intention_list = call_customer_request_data['data'].get('intention_list', [])
    should_call_account_payment_ids = None
    if len(intention_list) != 0:
        should_call_account_payment_ids = get_today_data_with_specific_cootek_intention(
            intention_list,
            task_type,
            'account_payment_id',
            None,
        )

    account_payment_ids = [
        int(customer['current_account_payment_id']) for customer in customer_request_data
    ]
    if should_call_account_payment_ids is not None:
        account_payment_ids = list(set(account_payment_ids) & set(should_call_account_payment_ids))

    account_payments = list(
        AccountPayment.objects.filter(id__in=account_payment_ids, due_amount__gt=0)
        .only('id', 'account_id', 'due_amount', 'due_date', 'status_id')
        .all()
    )
    account_payment_map = {
        account_payment.id: account_payment for account_payment in account_payments
    }

    # Prefect customer data
    customer_ids = [int(customer['customer_id']) for customer in customer_request_data]
    customers = list(
        Customer.objects.filter(id__in=customer_ids)
        .only(
            'fullname',
            'phone',
            'gender',
            'product_line',
        )
        .all()
    )
    customer_map = {customer.id: customer for customer in customers}

    if len(account_payment_ids) == 0:
        logger_data['error'] = 'No account payment ids to process'
        logger.warning(logger_data)
        return

    # Populate data for cootek.
    insert_cootek_robocalls = []
    for customer_data in customer_request_data:
        try:
            account_payment_id = customer_data['current_account_payment_id']
            customer_id = customer_data['customer_id']

            account_payment = account_payment_map.get(int(account_payment_id))
            if not account_payment:
                continue

            customer = customer_map.get(int(customer_id))
            if not customer:
                continue

            due_amount = (
                customer_data.get('due_amount')
                if customer_data.get('due_amount') is not None
                else account_payment.due_amount
            )
            due_date = (
                customer_data.get('due_date')
                if customer_data.get('due_date') is not None
                else account_payment.due_date.strftime("%Y-%m-%d")
            )

            customer_phone = customer.phone
            customer_fullname = customer.fullname
            customer_gender = customer.gender

            loan_amount = customer_data.get('loan_amount')
            loan_date = customer_data.get('loan_date')
            if loan_amount is None or loan_date is None:
                loan = account_payment.payment_set.order_by('cdate').last().loan
                loan_amount = loan.loan_amount
                loan_date = loan.cdate.strftime("%Y-%m-%d")

            extra_a = customer_data.get('extraA')
            if extra_a is None:
                account = Account.objects.only('cashback_counter').get(
                    id=account_payment.account_id
                )
                extra_a = account.cashback_counter

            insert_cootek_robocall = CootekRobocall(
                campaign_or_strategy=task_name,
                product=customer.product_line.product_line_type if customer.product_line else None,
                arrears=due_amount,
                payment_status_code_id=account_payment.status_id,
                cootek_event_type=source,
                call_to=format_e164_indo_phone_number(customer_phone),
                round=repeat_number,
                called_at=account_payment.dpd,
                cootek_robot=cootek_robot,
                task_type=task_type,
                time_to_start=start_time,
                account_payment_id=account_payment_id,
                time_to_end=end_time,
            )
            insert_cootek_robocalls.append(insert_cootek_robocall)
            task_details.append(
                {
                    'Debtor': customer_fullname,
                    'Mobile': format_e164_indo_phone_number(customer_phone),
                    'DueDate': due_date,
                    'LoanDate': loan_date,
                    'LoanAmount': loan_amount,
                    'Arrears': due_amount,
                    'Unit': CootekAIRobocall.UNIT_RUPIAH,
                    'Platform': CootekAIRobocall.PLATFORM_JULO,
                    'Comments': account_payment_id,
                    'Gender': convert_gender(customer_gender),
                    'ExtraA': extra_a,
                }
            )
        except Exception as e:
            # SKip the customer data if there is an error.
            # Publish it to sentry and log the error.
            logger.exception(
                {
                    "message": "error when process customer data",
                    "error": str(e),
                    "customer_data": customer_data,
                }
            )
            get_julo_sentry_client().captureException()

    # Send customer data to Cootek
    cootek_client = get_julo_cootek_client()
    cootek_task_id = cootek_client.create_task(
        task_name=task_name,
        start_time=start_at,
        end_time=end_at,
        robot=cootek_robot,
        attempts=repeat_number,
        task_details=task_details,
    )

    if not cootek_task_id:
        logger_data['error'] = 'Failed to create task to cootek'
        logger.error(logger_data)
        raise Exception('Failed to create task to cootek')

    # Insert customer data to cootek_robocall table for delivery report later.
    logger_data['cootek_task_id'] = cootek_task_id
    logger.info(
        {
            "message": "success send data to cootek",
            "total_task_details": len(task_details),
            **logger_data,
        }
    )
    for robocall in insert_cootek_robocalls:
        robocall.task_id = cootek_task_id
    CootekRobocall.objects.bulk_create(insert_cootek_robocalls)

    logger.info(
        {
            "message": "success create cootek_robocall data",
            "total_row": len(insert_cootek_robocalls),
            **logger_data,
        }
    )

    # Schedule task to get the result from cootek
    download_delay_secs = (end_at - now + timedelta(minutes=10)).total_seconds()
    celery_task = download_cootek_call_report_by_task_id.apply_async(
        (cootek_task_id, task_name), countdown=download_delay_secs
    )

    logger.info(
        {
            "message": "success schedule download_cootek_call_report_by_task_id",
            "schedule_celery_task_id": celery_task.id,
            "task_name": task_name,
            "cootek_task_id": cootek_task_id,
            "download_delay_secs": download_delay_secs,
            **logger_data,
        }
    )
    return cootek_task_id


@task(queue="collection_cootek", bind=True, max_retries=3)
def download_cootek_call_report_by_task_id(self, task_id, task_name=None, mock_url=None):
    """
    This task supported for J1 only. Used for download call report from cootek.
    """
    retries_times = self.request.retries
    try:
        cootek_client = get_julo_cootek_client()
        task_details = cootek_client.get_task_details(
            task_id, retries_times=retries_times, mock_url=mock_url
        )

        update_cootek_data(task_details, None, is_julo_one_product=True)
    except JuloException as error:
        if retries_times >= self.max_retries:
            header = "<!here>\n"
            setting_env = settings.ENVIRONMENT.upper()
            if setting_env != 'PROD':
                header = "<!here>\n Testing Purpose from {}\n".format(setting_env)

            message = (
                "Error when try get call results for " "campaign {} from cootek with this error: {}"
            ).format(task_name, str(error))
            formated_message = "{} ```{}```".format(header, message)
            send_message_normal_format(formated_message, channel='#cootek-failure-call-results')
            raise error

        raise self.retry(
            countdown=300,
            exc=error,
            kwargs={task_name, task_id, mock_url},
        )

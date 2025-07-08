import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import (
    transaction,
    OperationalError,
)
from django.forms import model_to_dict
from django.utils import timezone
from django.db.models import F

from juloserver.moengage.services.use_cases import \
    send_event_moengage_for_rpc_sales_ops
from juloserver.sales_ops.constants import (
    SalesOpsSettingConst,
)
from juloserver.sales_ops.exceptions import (
    NotValidSalesOpsAutodialerOption,
)
from juloserver.sales_ops.models import (
    SalesOpsLineup,
    SalesOpsAgentAssignment,
    SalesOpsAutodialerSession,
    SalesOpsAutodialerActivity,
)
from juloserver.sales_ops.services import (
    sales_ops_services,
)
from juloserver.loan.constants import TimeZoneName
from juloserver.julo.constants import AddressPostalCodeConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic


logger = logging.getLogger(__name__)


@dataclass
class AutodialerDelaySetting:
    rpc_delay_hour: \
        int = SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR  # flake8: noqa 701
    rpc_assignment_delay_hour: \
        int = SalesOpsSettingConst.DEFAULT_AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR  # flake8: noqa 701
    non_rpc_delay_hour: \
        int = SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR  # flake8: noqa 701
    non_rpc_final_delay_hour: \
        int = SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR  # flake8: noqa 701
    non_rpc_final_attempt_count: \
        int = SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT  # flake8: noqa 701


def is_sales_ops_autodialer_option(option_value):
    """
    option_value must have prefix "sales_ops:", for e.x:
    - sales_ops:bucket
    - sales_ops:queue
    """
    values = str(option_value).split(':')
    if len(values) >= 1 and values[0].lower() == 'sales_ops':
        return True

    return False


def get_sales_ops_autodialer_option(option_value):
    if not is_sales_ops_autodialer_option(option_value):
        raise NotValidSalesOpsAutodialerOption(f'Not a valid sales ops option: {option_value}.')

    values = str(option_value).lower().split(':')
    if len(values) > 1 and len(values[1]) > 0:
        return values[1]
    return None


def assign_agent_to_lineup(agent, lineup):
    logger_data = {
        'module': 'sales_ops',
        'action': 'assign_agent_to_lineup',
        'lineup_id': lineup.id,
        'agent_id': agent.id,
    }
    try:
        with db_transactions_atomic(DbConnectionAlias.utilization()):
            lineup = SalesOpsLineup.objects.select_for_update(
                nowait=True
            ).get(pk=lineup.id)

            last_agent_assignment_id = lineup.latest_agent_assignment_id
            last_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
                pk=last_agent_assignment_id
            )

            # Return the assignment if:
            # - No last_agent_assignment
            # - the last_agent_assignment is_active
            if not last_agent_assignment or not last_agent_assignment.is_active:
                agent_assignment = SalesOpsAgentAssignment.objects.create(
                    agent_id=agent.id,
                    agent_name=agent.user.username,
                    lineup_id=lineup.id,
                    is_active=True,
                    assignment_date=timezone.localtime(timezone.now()),
                )
                lineup.update_safely(latest_agent_assignment_id=agent_assignment.id)
                logger.info({
                    **logger_data,
                    'message': 'Assignment to SalesOpsLineup successful.',
                    'last_agent_assignment': model_to_dict(agent_assignment),
                })
                return agent_assignment

            logger.info(
                {
                    **logger_data,
                    'message': 'Fail to assign an agent to SalesOpsLineup.',
                    'lineup': lineup,
                    'last_agent_assignment_id': lineup.latest_agent_assignment_id,
                }
            )
            return None
    except OperationalError as e:
        logger.exception({
            **logger_data,
            'message': 'Fail to select_for_update a SalesOpsLineup for autodialer',
            'error': str(e),
        })
        return None


def get_active_assignment(agent):
    return (
        SalesOpsAgentAssignment.objects.filter(is_active=True, agent_id=agent.id)
        .order_by('cdate')
        .last()
    )


def get_autodialer_session(lineup_id):
    return SalesOpsAutodialerSession.objects.get_or_none(lineup_id=lineup_id)


def get_or_create_autodialer_session(lineup_id, **data):
    autodialer_session = get_autodialer_session(lineup_id)
    if autodialer_session:
        return autodialer_session

    data['lineup_id'] = lineup_id
    return SalesOpsAutodialerSession.objects.create(**data)


def get_agent_assignment(agent, lineup_id):
    filter_kwargs = {
        'is_active': True,
        'lineup_id': lineup_id,
        'agent_id': agent.id,
    }
    return SalesOpsAgentAssignment.objects.get_or_none(**filter_kwargs)


def create_autodialer_activity(autodialer_session, agent_assignment, action, **data):
    data.update(
        autodialer_session_id=autodialer_session.id,
        agent_id=agent_assignment.agent_id,
        action=action,
        agent_assignment_id=agent_assignment.id,
    )
    return SalesOpsAutodialerActivity.objects.create(**data)


def generate_autodialer_next_ts(agent_assignment):
    delay_setting = sales_ops_services.SalesOpsSetting.get_autodialer_delay_setting()
    now = timezone.localtime(timezone.now())
    if agent_assignment.is_rpc:
        return now + timedelta(hours=delay_setting.rpc_delay_hour)
    else:
        if agent_assignment.non_rpc_attempt >= delay_setting.non_rpc_final_attempt_count:
            return now + timedelta(hours=delay_setting.non_rpc_final_delay_hour)
        return now + timedelta(hours=delay_setting.non_rpc_delay_hour)


def stop_autodialer_session(autodialer_session, agent_assignment):
    """
    - If failed, increase the failed attempt
    - Generate the next_turn timestamp based on the rules and update the sesions.
    - Update SalesOpsAgentAssignment (is_rpc) based on `is_failed`
    """
    latest_autodialer_activity = SalesOpsAutodialerActivity.objects.get_latest_activity(
        autodialer_session.id, agent_assignment.id
    )
    prev_agent_assignment = SalesOpsAgentAssignment.objects.get_previous_assignment(
        agent_assignment
    )
    now = timezone.localtime(timezone.now())
    assignment_data = {
        'is_active': False,
        'completed_date': now,
        'non_rpc_attempt': 0,
    }
    session_data = {
        'total_count': autodialer_session.total_count + 1
    }
    if prev_agent_assignment:
        assignment_data.update(non_rpc_attempt=prev_agent_assignment.non_rpc_attempt)
    is_rpc = latest_autodialer_activity and latest_autodialer_activity.is_success()
    if latest_autodialer_activity:
        if latest_autodialer_activity.is_success():
            assignment_data.update(is_rpc=True, non_rpc_attempt=0)
        else:
            session_data.update(failed_count=autodialer_session.failed_count + 1)
            assignment_data.update(
                is_rpc=False, non_rpc_attempt=assignment_data.get('non_rpc_attempt') + 1
            )
    else:
        session_data.update(total_count=autodialer_session.total_count)
        assignment_data.update(completed_date=None)

    # Update the agent_assignment
    agent_assignment.update_safely(**assignment_data)
    if agent_assignment.is_rpc:
        send_event_moengage_for_rpc_sales_ops.delay(agent_assignment.id)

    # Update latest_agent_assignment
    # if the agent close the call (no activity), then cancel the assignment
    sales_ops_lineup = SalesOpsLineup.objects.get(id=agent_assignment.lineup_id)
    if not assignment_data['completed_date']:
        sales_ops_lineup.update_safely(latest_agent_assignment_id=prev_agent_assignment.id)
    else:
        if latest_autodialer_activity.is_success():
            sales_ops_lineup.update_safely(
                latest_agent_assignment_id=agent_assignment.id,
                latest_rpc_agent_assignment_id=agent_assignment.id,
                udate=now
            )
        else:
            sales_ops_lineup.update_safely(
                latest_agent_assignment_id=agent_assignment.id, udate=now
            )
    if is_rpc:
        sales_ops_lineup.update_safely(rpc_count=F("rpc_count") + 1)

    # Update the autodialer_session
    session_data.update(next_session_ts=generate_autodialer_next_ts(agent_assignment))
    autodialer_session.update_safely(**session_data)


def create_agent_assignment_by_skiptrace_result(lineup, agent, is_rpc):
    now = timezone.localtime(timezone.now())
    data_create = {
        'agent_id': agent.id,
        'agent_name': agent.user.username,
        'lineup_id': lineup.id,
        'is_active': False,
        'assignment_date': now,
        'completed_date': now,
        'is_rpc': is_rpc
    }
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        agent_assignment = SalesOpsAgentAssignment.objects.create(**data_create)
        if is_rpc:
            lineup.update_safely(
                latest_agent_assignment_id=agent_assignment.id,
                latest_rpc_agent_assignment_id=agent_assignment.id,
            )
        else:
            lineup.update_safely(latest_agent_assignment_id=agent_assignment.id)
    return agent_assignment


def get_customer_timezone(postcode):
    if not postcode:
        return TimeZoneName.WIT

    postcode = int(postcode)
    if postcode in AddressPostalCodeConst.WIT_POSTALCODE:
        return TimeZoneName.WIT
    if postcode in AddressPostalCodeConst.WITA_POSTALCODE:
        return TimeZoneName.WITA
    if postcode in AddressPostalCodeConst.WIB_POSTALCODE:
        return TimeZoneName.WIB
    return TimeZoneName.WIT


def get_autodialer_end_call_hour():
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.SALES_OPS, is_active=True)
    return fs.parameters.get(
        SalesOpsSettingConst.AUTODIAL_END_CALL_HOUR,
        SalesOpsSettingConst.DEFAULT_AUTODIAL_END_CALL_HOUR
    )


def check_autodialer_due_calling_time(lineup_id):
    end_call_hour = get_autodialer_end_call_hour()

    lineup = SalesOpsLineup.objects.get(pk=lineup_id)
    application = lineup.latest_application
    postcode = application and application.address_kodepos
    tz = get_customer_timezone(postcode)
    now = timezone.localtime(timezone.now())
    end_calling_time = timezone.localtime(timezone.now()).replace(
        hour=end_call_hour, minute=0, second=0
    )

    # default for WIB
    tz_hour_adjustment = 0

    # WITA: WIB - 1 hour
    if tz == TimeZoneName.WITA:
        tz_hour_adjustment = -1
    # WIT: WIB - 2 hours
    elif tz == TimeZoneName.WIT:
        tz_hour_adjustment = -2

    return now < end_calling_time + timedelta(hours=tz_hour_adjustment)

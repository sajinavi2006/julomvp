import io
import os
import csv
import logging
import urllib.request
from datetime import datetime

from django.core.files.base import ContentFile
from django.utils import timezone
from django.conf import settings
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
    UploadAsyncStateType
)
from juloserver.julo.models import UploadAsyncState, FeatureSetting, Agent
from juloserver.julo.utils import put_public_file_to_oss
from juloserver.sales_ops.constants import VendorRPCConst
from juloserver.sales_ops.exceptions import (
    MissingCSVHeaderException,
    InvalidBooleanValueException,
    InvalidDatetimeValueException,
    InvalidDigitValueException,
    MissingFeatureSettingVendorRPCException,
    InvalidSalesOpsPDSPromoCode,
)
from juloserver.sales_ops.constants import (
    UploadSalesOpsVendorRPC,
    SalesOpsPDSConst,
)
from juloserver.sales_ops.models import (
    SalesOpsLineup,
    SalesOpsVendorAgentMapping,
    SalesOpsAgentAssignment
)
from juloserver.sales_ops.utils import convert_string_to_datetime
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.moengage.services.use_cases import \
    send_event_moengage_for_rpc_sales_ops_pds
from juloserver.promo.models import PromoCode
from juloserver.promo.constants import PromoCodeTypeConst


logger = logging.getLogger(__name__)

CSV_HEADER = [
    'account_id', 'vendor_id', 'user_extension', 'completed_date', 'is_rpc', 'result upload'
]


def check_vendor_rpc_csv_format(csv_list):
    headers = list(csv_list[0].keys()) if len(csv_list) else []
    fs = get_fs_for_sales_ops_vendor_rpc()
    if not fs:
        raise MissingFeatureSettingVendorRPCException

    params = fs.parameters
    if not _is_have_vendor_rpc_csv_headers(headers, params['csv_headers']):
        raise MissingCSVHeaderException

    for val_dict in csv_list:
        if not _isdigit_values(val_dict, params['digit_fields']):
            raise InvalidDigitValueException

        if not _is_all_date_values(val_dict, params['date_fields'], params['datetime_format']):
            raise InvalidDatetimeValueException

        if not _is_all_boolean_values(val_dict, params['boolean_fields']):
            raise InvalidBooleanValueException

    return True


def check_promo_code_for_sales_ops_pds():
    now = timezone.localtime(timezone.now())
    fs = get_fs_for_promo_code_pds()
    if not fs:
        return

    promo_code_id = fs.parameters.get("promo_code_id")
    if promo_code_id:
        promo_code = PromoCode.objects.filter(
            pk=promo_code_id,
            type=PromoCodeTypeConst.LOAN,
            is_active=True,
            start_date__lte=now,
            end_date__gte=now
        ).last()

        if promo_code:
            return promo_code

    raise InvalidSalesOpsPDSPromoCode


def _is_have_vendor_rpc_csv_headers(headers, default_headers):
    return set(headers) == set(default_headers)


def _isdigit_values(val_dict, key_fields):
    return all([val_dict[field].isdigit() for field in key_fields])


def _is_all_date_values(val_dict, key_fields, datetime_format):
    for field in key_fields:
        try:
            datetime.strptime(val_dict[field], datetime_format)
        except Exception:
            return False

    return True


def _is_all_boolean_values(val_dict, key_fields):
    return all([val_dict[field].upper() in ['TRUE', 'FALSE'] for field in key_fields])


def get_fs_for_sales_ops_vendor_rpc():
    return FeatureSetting.objects.filter(
        feature_name=VendorRPCConst.FS_NAME,
        is_active=True,
        category='sales_ops'
    ).last()


def get_fs_for_promo_code_pds():
    return FeatureSetting.objects.filter(
        feature_name=SalesOpsPDSConst.PromoCode.FS_NAME,
        is_active=True,
        category=SalesOpsPDSConst.PromoCode.CATEGORY
    ).last()


def save_vendor_rpc_csv(csv_file, agent):
    from juloserver.sales_ops.tasks import update_rpc_from_vendor_task
    upload_async_state = UploadAsyncState.objects.create(
        task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        task_status=UploadAsyncStateStatus.WAITING,
        agent=agent,
        service='oss',
        url='',
    )

    upload_vendor_rpc_csv_to_oss(upload_async_state, csv_file)
    update_rpc_from_vendor_task.delay(upload_async_state.id)


def upload_vendor_rpc_csv_to_oss(upload_async_state, csv_file):
    """Upload CSV file to OSS and update upload_async_state URL"""
    file_name, extension = os.path.splitext(csv_file.name)

    dest_name = "vendor_rpc/{}/{}{}".format(
        upload_async_state.id,
        file_name,
        extension
    )

    if hasattr(csv_file, 'seek'):
        csv_file.seek(0)

    put_public_file_to_oss(settings.OSS_MEDIA_BUCKET, csv_file, dest_name)
    upload_async_state.update_safely(url=dest_name)


def update_rpc_from_vendor(upload_async_state):
    csv_file = read_csv_file(upload_async_state.download_url)
    fs = get_fs_for_sales_ops_vendor_rpc()
    date_format = fs.parameters['datetime_format'] if fs else VendorRPCConst.DEFAULT_DATETIME_FORMAT

    is_success_all = True
    now = timezone.localtime(timezone.now())
    csv_buffer = io.StringIO()
    write = csv.writer(csv_buffer)
    write.writerow(CSV_HEADER)

    for row in csv_file:
        try:
            completed_date = convert_string_to_datetime(row['completed_date'], date_format)
        except Exception:
            is_success_all = False
            write_csv_result(write, row, UploadSalesOpsVendorRPC.INVALID_FORMAT_COMPLETED_DATE)
            continue

        if completed_date > now:
            is_success_all = False
            write_csv_result(write, row, UploadSalesOpsVendorRPC.INVALID_COMPLETED_DATE)
            continue

        lineup = get_sales_ops_lineup_by_account_id(row['account_id'])
        if not lineup:
            is_success_all = False
            write_csv_result(write, row, UploadSalesOpsVendorRPC.LINEUP_DOES_NOT_EXISTED)
            continue

        agent = Agent.objects.get_or_none(user_extension=row['user_extension'])
        if not agent:
            write_csv_result(write, row, UploadSalesOpsVendorRPC.AGENT_DOES_NOT_EXISTED)
            is_success_all = False
            continue

        vendor_agent_mapping = get_sales_ops_vendor_agent_mapping(agent.id, row['vendor_id'])
        if not vendor_agent_mapping:
            write_csv_result(write, row, UploadSalesOpsVendorRPC.VENDOR_AGENT_DOES_NOT_EXISTED)
            is_success_all = False
            continue

        ret_val = stored_rpc_sales_ops_agent_assignment(
            row, lineup, vendor_agent_mapping, now, completed_date
        )
        if isinstance(ret_val, SalesOpsAgentAssignment):
            write_csv_result(write, row, UploadSalesOpsVendorRPC.SUCCESS)
            if ret_val.is_rpc:
                promo_code_pds_fs = get_fs_for_promo_code_pds()
                if not promo_code_pds_fs:
                    continue
                promo_code_id = promo_code_pds_fs.parameters['promo_code_id']

                send_event_moengage_for_rpc_sales_ops_pds.delay(
                    agent_assignment_id=ret_val.id,
                    promo_code_id=promo_code_id
                )
        else:
            write_csv_result(write, row, ret_val)
            is_success_all = False

    # Upload result CSV (overwrite original file)
    csv_content = ContentFile(csv_buffer.getvalue().encode('utf-8'))
    csv_content.name = os.path.basename(upload_async_state.url)  # Set name explicitly
    upload_vendor_rpc_csv_to_oss(upload_async_state, csv_content)

    return is_success_all


def read_csv_file(upload_file):
    f = urllib.request.urlopen(upload_file)
    f = f.read().decode('utf-8').splitlines()
    reader = csv.DictReader(f, delimiter=',')
    return reader


def get_sales_ops_lineup_by_account_id(account_id):
    return SalesOpsLineup.objects.get_or_none(account_id=account_id, is_active=True)


def get_sales_ops_vendor_agent_mapping(agent_id, vendor_id):
    return SalesOpsVendorAgentMapping.objects.get_or_none(
        agent_id=agent_id, vendor_id=vendor_id, is_active=True
    )


def stored_rpc_sales_ops_agent_assignment(row, lineup, vendor_agent_mapping, now, completed_date):
    try:
        is_rpc = row['is_rpc'].strip().lower() == 'true'
        agent_assignment = create_salesops_agent_assignment(
            lineup, vendor_agent_mapping, now, is_rpc, completed_date
        )
        return agent_assignment
    except Exception as err_msg:
        logger.error({
            'action': 'stored_rpc_sales_ops_agent_assignment',
            'error': str(err_msg)
        })
        return err_msg


def write_csv_result(write, row, result):
    write.writerow([
        row['account_id'], row['vendor_id'], row['user_extension'], row['completed_date'],
        row['is_rpc'], result
    ])


def is_latest_rpc_agent_assignment(sales_ops_lineup, new_rpc_agent_assignment):
    old_rpc_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
        pk=sales_ops_lineup.latest_rpc_agent_assignment_id
    )
    return (
        not old_rpc_agent_assignment or
        not old_rpc_agent_assignment.completed_date or
        old_rpc_agent_assignment.completed_date <= new_rpc_agent_assignment.completed_date
    )


def is_latest_agent_assignment(sales_ops_lineup, new_agent_assignment):
    old_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
        pk=sales_ops_lineup.latest_agent_assignment_id
    )
    return (
        not old_agent_assignment or
        not old_agent_assignment.completed_date or
        old_agent_assignment.completed_date <= new_agent_assignment.completed_date
    )


def create_salesops_agent_assignment(lineup, vendor_agent_mapping, now, is_rpc, completed_date):
    agent_id = vendor_agent_mapping.agent_id
    agent = Agent.objects.get(pk=agent_id)
    if is_rpc:
        agent_assignment = create_salesops_rpc_agent_assignment(lineup, agent, now, completed_date)
    else:
        agent_assignment = create_salesops_non_rpc_agent_assignment(
            lineup, agent, now, completed_date
        )
    return agent_assignment


def construct_agent_assignment_data(lineup, agent, now, is_rpc, completed_date):
    agent_assignment_data = {
        'agent_id': 0,
        'agent_name': '',
        'lineup_id': lineup.id,
        'is_active': False,
        'assignment_date': now,
        'completed_date': completed_date,
        'is_rpc': is_rpc
    }
    if agent:
        agent_assignment_data.update({
            'agent_id': agent.id,
            'agent_name': agent.user.username
        })

    return agent_assignment_data


def create_salesops_rpc_agent_assignment(lineup, agent, now, completed_date):
    """
        Create RPC agent assignment
        Update latest agent assignment and RPC latest agent assignment of lineup
    """
    data_create = {
        **construct_agent_assignment_data(lineup, agent, now, True, completed_date),
        **{'non_rpc_attempt': 0}
    }
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        lineup = SalesOpsLineup.objects.select_for_update().get(pk=lineup.id)
        new_agent_assignment = SalesOpsAgentAssignment.objects.create(**data_create)
        update_data = {
            'is_active': False,
            'rpc_count': lineup.rpc_count + 1
        }
        if is_latest_agent_assignment(lineup, new_agent_assignment):
            update_data['latest_agent_assignment_id'] = new_agent_assignment.id
        if is_latest_rpc_agent_assignment(lineup, new_agent_assignment):
            update_data['latest_rpc_agent_assignment_id'] = new_agent_assignment.id
        lineup.update_safely(**update_data)
    return new_agent_assignment


def create_salesops_non_rpc_agent_assignment(lineup, agent, now, completed_date):
    """
        Create non RPC agent assignment
        Update latest agent assignment of lineup
        - If new agent assignment is latest:
            + Update non_rpc_attempt = lineup.latest_agent_assignment.non_rpc_attempt + 1
            + Assign new agent assignment to lineup
        - If new non RPC agent assignment is not latest:
            + Increase lineup.latest_agent_assignment.non_rpc_attempt to 1
    """
    latest_agent_assignment_id = lineup.latest_agent_assignment_id
    latest_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
        pk=latest_agent_assignment_id
    )
    non_rpc_attempt = latest_agent_assignment and latest_agent_assignment.non_rpc_attempt or 0
    data_create = {
        **construct_agent_assignment_data(lineup, agent, now, False, completed_date),
        **{'non_rpc_attempt': 1}
    }
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        lineup = SalesOpsLineup.objects.select_for_update().get(pk=lineup.id)
        new_agent_assignment = SalesOpsAgentAssignment.objects.create(**data_create)
        update_data = {
            'is_active': True
        }
        if is_latest_agent_assignment(lineup, new_agent_assignment):
            update_data['latest_agent_assignment_id'] = new_agent_assignment.id
            new_agent_assignment.update_safely(non_rpc_attempt=non_rpc_attempt + 1)
        elif not latest_agent_assignment.is_rpc:
            latest_agent_assignment.update_safely(non_rpc_attempt=non_rpc_attempt + 1)
        lineup.update_safely(**update_data)
    return new_agent_assignment

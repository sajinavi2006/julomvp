from juloserver.julo.models import FeatureSetting
from juloserver.sales_ops_pds.constants import (
    FeatureNameConst,
    SalesOpsPDSTaskName,
    SalesOpsPDSDownloadConst,
)


def get_sales_ops_pds_fs():
    sales_ops_pds_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_PDS,
        is_active=True
    ).last()
    return sales_ops_pds_fs


def check_create_task_fs() -> bool:
    sales_ops_pds_fs = get_sales_ops_pds_fs()
    if not sales_ops_pds_fs:
        return False

    parameters = getattr(sales_ops_pds_fs, 'parameters', {})
    return parameters.get(SalesOpsPDSTaskName.CREATE_TASK, False)


def check_download_call_result_fs() -> bool:
    sales_ops_pds_fs = get_sales_ops_pds_fs()
    if not sales_ops_pds_fs:
        return False

    parameters = getattr(sales_ops_pds_fs, 'parameters', {})
    return parameters.get(SalesOpsPDSTaskName.DOWNLOAD_CALL_RESULT, False)


def check_download_recording_file_fs() -> bool:
    sales_ops_pds_fs = get_sales_ops_pds_fs()
    if not sales_ops_pds_fs:
        return False

    parameters = getattr(sales_ops_pds_fs, 'parameters', {})
    return parameters.get(SalesOpsPDSTaskName.DOWNLOAD_RECORDING_FILE, False)


def get_sales_ops_pds_strategy_setting_fs_params() -> dict:
    strategy_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_AI_RUDDER_TASKS_STRATEGY_CONFIG,
        is_active=True
    ).last()
    return strategy_setting and getattr(strategy_setting, 'parameters', {}) or {}


def get_download_limit_fs_params() -> int:
    sales_ops_pds_fs = get_sales_ops_pds_fs()
    if not sales_ops_pds_fs:
        return 0

    parameters = getattr(sales_ops_pds_fs, 'parameters', {})
    return parameters.get(
        SalesOpsPDSTaskName.DOWNLOAD_LIMIT, SalesOpsPDSDownloadConst.DEFAULT_DOWNLOAD_LIMIT
    )


def get_format_call_result_fs_params() -> dict:
    call_result_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SALES_OPS_CALL_RESULT_FORMAT,
        is_active=True
    ).last()
    return call_result_fs and getattr(call_result_fs, 'parameters', {}) or {}

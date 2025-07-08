import base64
import csv
import os
from datetime import datetime, date, time, timedelta
from typing import List, Tuple, Optional
from requests import (
    ConnectionError,
    HTTPError,
    Timeout,
)

from django.conf import settings
from django.utils import timezone

from juloserver.julo.exceptions import JuloException
from juloserver.julo.utils import get_file_from_oss
from juloserver.minisquad.constants import AiRudder

from juloserver.sales_ops_pds.services.general_services import (
    get_sales_ops_pds_strategy_setting_fs_params
)
from juloserver.sales_ops_pds.serializers import SalesOpsLineupAIRudderDataSerializer
from juloserver.sales_ops_pds.tasks import (
    create_sales_ops_pds_task_subtask,
    send_create_task_request_to_airudder,
)
from juloserver.sales_ops.utils import chunker
from juloserver.sales_ops_pds.models import (
    AIRudderAgentGroupMapping,
    AIRudderDialerTaskGroup,
    AIRudderDialerTaskUpload,
    SalesOpsLineupAIRudderData,
)
from juloserver.sales_ops_pds.constants import (
    SalesOpsPDSConst,
    SalesOpsPDSUploadConst,
    SalesOpsPDSDataStoreType,
)
from juloserver.sales_ops_pds.serializers import AIRudderPDSConfigSerializer
from juloserver.sales_ops_pds.clients.sales_ops_airudder_pds import (
    get_sales_ops_airudder_pds_client,
    GeneralAIRudderPDSClient,
)
from juloserver.sales_ops_pds.services.store_data_services import StoreSalesOpsPDSUploadData


class SalesOpsPDSUploadTask:
    @staticmethod
    def get_sales_ops_task_strategy_config() -> dict:
        params = get_sales_ops_pds_strategy_setting_fs_params()
        strategy_config = dict()
        strategy_config["start_time"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.START_TIME,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.START_TIME
        )
        strategy_config["end_time"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.AUTO_END_TIME,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.AUTO_END_TIME
        )
        strategy_config["rest_times"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.REST_TIMES,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.REST_TIMES
        )
        strategy_config["autoSlotFactor"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.AUTO_SLOT_FACTOR,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.AUTO_SLOT_FACTOR
        )
        strategy_config["ringLimit"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.RING_LIMIT,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.RING_LIMIT
        )
        strategy_config["maxLostRate"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.MAX_LOST_RATE,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.MAX_LOST_RATE
        )
        strategy_config["dialingMode"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.DIALING_MODE,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.DIALING_MODE
        )
        strategy_config["dialingOrder"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.DIALING_ORDER,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.DIALING_ORDER
        )
        strategy_config["acwTime"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.ACW_TIME,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.ACW_TIME
        )
        strategy_config["repeatTimes"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.REPEAT_TIMES,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.REPEAT_TIMES
        )
        strategy_config["bulkCallInterval"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.BULK_CALL_INTERVAL,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.BULK_CALL_INTERVAL
        )
        strategy_config["voiceCheck"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.VOICEMAIL_CHECK,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.VOICEMAIL_CHECK
        )
        strategy_config["voiceCheckDuration"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.VOICEMAIL_CHECK_DURATION,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.VOICEMAIL_CHECK_DURATION
        )
        strategy_config["voiceHandle"] = params.get(
            SalesOpsPDSConst.SalesOpsPDSSetting.VOICEMAIL_HANDLE,
            SalesOpsPDSConst.SalesOpsPDSSettingDefault.VOICEMAIL_HANDLE
        )
        return strategy_config

    def get_airudder_task_strategy_config(
        self, group_mapping: AIRudderAgentGroupMapping
    ) -> dict:
        strategy_config = self.get_sales_ops_task_strategy_config()
        strategy_config["groupName"] = group_mapping.agent_group_name
        return strategy_config

    def init_create_sales_ops_pds_task(self):
        agent_group_mappings = AIRudderAgentGroupMapping.objects.filter(is_active=True)
        for agent_group_mapping in agent_group_mappings:
            self.create_sales_ops_pds_task_per_group(agent_group_mapping)

    def create_sales_ops_pds_task_per_group(
        self, agent_group_mapping: AIRudderAgentGroupMapping
    ):
        bucket_code = agent_group_mapping.bucket_code
        customer_type = agent_group_mapping.customer_type

        account_ids = list(
            SalesOpsLineupAIRudderData.objects
            .filter(bucket_code=bucket_code, customer_type=customer_type)
            .values_list("account_id", flat=True)
        )

        if not account_ids:
            return

        dialer_task_group = AIRudderDialerTaskGroup.objects.create(
            bucket_code=bucket_code,
            customer_type=customer_type,
            agent_group_mapping=agent_group_mapping,
            total=len(account_ids)
        )

        batch_number = 1
        for sub_account_ids in chunker(account_ids, SalesOpsPDSUploadConst.UPLOAD_BATCH_SIZE):
            create_sales_ops_pds_task_subtask.delay(
                dialer_task_group_id=dialer_task_group.id,
                sub_account_ids=sub_account_ids,
                batch_number=batch_number
            )
            batch_number += 1

    def create_sales_ops_pds_task_per_group_per_batch(
        self, dialer_task_group_id: int, sub_account_ids: List[int], batch_number: int
    ):
        dialer_task_group = AIRudderDialerTaskGroup.objects.filter(
            pk=dialer_task_group_id
        ).last()
        if not dialer_task_group:
            raise JuloException(
                "Not found dialer task group ID {id}".format(id=dialer_task_group_id)
            )

        data = list(
            SalesOpsLineupAIRudderData.objects
            .filter(account_id__in=sub_account_ids)
            .order_by('-r_score', '-m_score', '-available_limit')
            .values()
        )
        serializer = SalesOpsLineupAIRudderDataSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        customized_data = serializer.data

        total_uploaded = len(customized_data)
        dialer_task_upload = AIRudderDialerTaskUpload.objects.create(
            dialer_task_group=dialer_task_group,
            total_uploaded=total_uploaded,
            batch_number=batch_number
        )
        StoreSalesOpsPDSUploadData(
            data=customized_data,
            store_type=SalesOpsPDSDataStoreType.UPLOAD_TO_AIRUDDER,
            dialer_task_upload_id=dialer_task_upload.id
        ).store_uploaded_data()

        send_create_task_request_to_airudder.delay(
            dialer_task_upload_id=dialer_task_upload.id
        )

    def load_data_from_oss_file(
        self, dialer_task_upload: AIRudderDialerTaskUpload
    ) -> List[dict]:
        upload_file_url = dialer_task_upload.upload_file_url
        if not upload_file_url:
            raise JuloException(
                "Not found upload url link for dialer task upload ID {id}".format(
                    id=dialer_task_upload.id
                )
            )
        file_obj = get_file_from_oss(settings.OSS_MEDIA_BUCKET, upload_file_url)
        file_content = file_obj.read().decode('utf-8')
        csv_reader = csv.DictReader(file_content.splitlines(), delimiter=',')
        return list(csv_reader)

    def record_uploaded_sales_ops_pds_data(
        self,
        dialer_task_upload: AIRudderDialerTaskUpload,
        total_successful: int,
        total_failed: int,
        task_id: str,
        error_uploaded_data: List[dict] = None
    ):
        dialer_task_upload.update_safely(
            total_successful=total_successful,
            total_failed=total_failed,
            task_id=task_id
        )
        if error_uploaded_data:
            StoreSalesOpsPDSUploadData(
                data=error_uploaded_data,
                store_type=SalesOpsPDSDataStoreType.UPLOAD_FAILED_TO_AIRUDDER,
                dialer_task_upload_id=dialer_task_upload.id
            ).store_failed_uploaded_data()


class AIRudderPDSUploadService:
    def __init__(
        self, bucket_code: str, customer_type: str, strategy_config: dict,
        customer_list: List[dict], batch_number: int, callback_url: str = None,
    ):
        self.bucket_code = bucket_code
        self.customer_type = customer_type
        self.strategy_config = self._validate_strategy_config(strategy_config)
        self.customer_list = self._validate_customer_list(customer_list)
        self.batch_number = batch_number
        self.callback_url = self._get_encode_callback_url(callback_url)

    @staticmethod
    def _validate_strategy_config(raw_strategy_config: dict) -> dict:
        if not raw_strategy_config:
            raise JuloException("Strategy configuration is empty")

        serializer = AIRudderPDSConfigSerializer(data=raw_strategy_config)
        serializer.is_valid(raise_exception=True)
        strategy_config = serializer.validated_data

        current_time = timezone.localtime(timezone.now())
        start_time = strategy_config.get('start_time')
        end_time = strategy_config.get('end_time')

        start_time = current_time.replace(hour=start_time.hour, minute=start_time.minute, second=0)
        end_time = current_time.replace(hour=end_time.hour, minute=end_time.minute, second=0)

        if start_time <= current_time:
            start_time = current_time.replace(second=0) + timedelta(minutes=2)

        if end_time <= start_time:
            raise ValueError("End time must be greater than start time")

        strategy_config['start_time'] = start_time
        strategy_config['end_time'] = end_time

        rest_times = strategy_config.get("rest_times", [])
        formated_rest_times = []
        for rest_time in rest_times:
            formated_rest_times.append(
                {
                    "start": rest_time[0].isoformat(),
                    "end": rest_time[1].isoformat(),
                }
            )
        strategy_config['restTimes'] = formated_rest_times
        if "rest_times" in strategy_config:
            del strategy_config["rest_times"]

        if int(strategy_config.get('autoSlotFactor', 0)) == 0:
            strategy_config['slotFactor'] = strategy_config.get('slotFactor', 2.5)

        return dict(strategy_config)

    @staticmethod
    def _validate_customer_list(customer_list: List[dict]) -> List[dict]:
        for customer in customer_list:
            for key, value in customer.items():
                if value is None:
                    customer[key] = ''
                elif (
                    isinstance(value, datetime) or
                    isinstance(value, date) or
                    isinstance(value, time)
                ):
                    customer[key] = value.isoformat()
                elif not isinstance(value, str):
                    customer[key] = str(value)
        return customer_list

    def _get_encode_callback_url(self, callback_url: str) -> str:
        if not callback_url:
            callback_url = SalesOpsPDSUploadConst.DUMMY_CALLBACK_URL
        return base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

    def get_airudder_client(self) -> GeneralAIRudderPDSClient:
        airudder_client = get_sales_ops_airudder_pds_client()
        return airudder_client

    def get_task_name(self) -> str:
        task_name = "{bucket_code}_{customer_type}_{timestamp}_p{batch_number}".format(
            bucket_code=self.bucket_code.title().replace("_", ""),
            customer_type=self.customer_type.title().replace("_", ""),
            timestamp=timezone.localtime(timezone.now()).strftime("%Y%m%d-%H%M"),
            batch_number=self.batch_number
        )

        setting_env = settings.ENVIRONMENT.upper()
        if setting_env != 'PROD':
            task_name = "{}_{}".format(setting_env, task_name)

        return task_name

    def create_task(self) -> Tuple[str, List[dict]]:
        fn_name = "AIRudderPDSUploadService.create_task"
        airudder_client = self.get_airudder_client()
        task_name = self.get_task_name()
        start_time = self.strategy_config.get('start_time')
        end_time = self.strategy_config.get('end_time')

        response = airudder_client.create_task(
            task_name=task_name,
            start_time=start_time,
            end_time=end_time,
            group_name=self.strategy_config["groupName"],
            list_contact_to_call=self.customer_list,
            call_back_url=self.callback_url,
            strategy_config=self.strategy_config,
            partner_name=AiRudder.SALES_OPS
        )

        response_body = response.get('body')
        if not response_body:
            raise JuloException(
                "{} not return correct response. Returned response {}".format(
                    fn_name, str(response)
                )
            )

        task_id = response_body.get("taskId")
        if not task_id:
            raise JuloException(
                "{} not return correct response. Returned response {}".format(
                    fn_name, str(response_body)
                )
            )

        error_customer_list = response_body.get("errorContactList", [])
        return task_id, error_customer_list


class AIRudderPDSUploadManager:
    class NeedRetryException(Exception):
        pass

    class NoNeedRetryException(Exception):
        pass

    def __init__(self, airudder_upload_service: AIRudderPDSUploadService):
        self.airudder_upload_service = airudder_upload_service

    def create_task(self) -> Optional[Tuple[str, List[dict]]]:
        try:
            task_id, error_uploaded_data = self.airudder_upload_service.create_task()
        except (ConnectionError, Timeout) as error:
            raise self.NeedRetryException("Need to retry") from error
        except HTTPError as error:
            http_resp = error.response
            if not http_resp:
                raise self.NeedRetryException("Need to retry") from error

            if http_resp.status_code == 429 or http_resp.status_code >= 500:
                raise self.NeedRetryException("Need to retry") from error

            raise error

        return task_id, error_uploaded_data

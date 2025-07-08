import math
from datetime import datetime
from dateutil import parser
from typing import List
from requests import (
    ConnectionError,
    HTTPError,
    Timeout,
)

from django.utils import timezone

from juloserver.julo.models import Agent
from juloserver.julo.exceptions import JuloException
from juloserver.sales_ops.models import SalesOpsLineup
from juloserver.sales_ops.services.vendor_rpc_services import (
    create_salesops_rpc_agent_assignment,
    create_salesops_non_rpc_agent_assignment,
)
from juloserver.sales_ops_pds.tasks import (
    send_get_total_request_to_airudder,
    send_get_call_list_request_to_airudder
)
from juloserver.sales_ops_pds.models import (
    AIRudderDialerTaskUpload,
    AIRudderDialerTaskDownload,
)
from juloserver.sales_ops_pds.services.general_services import get_download_limit_fs_params
from juloserver.sales_ops_pds.constants import SalesOpsPDSDownloadConst
from juloserver.sales_ops_pds.clients.sales_ops_airudder_pds import (
    get_sales_ops_airudder_pds_client,
    GeneralAIRudderPDSClient
)


class SalesOpsPDSDownloadTask:
    def init_download_sales_ops_pds_call_result(self):
        now = timezone.localtime(timezone.now())
        dialer_task_upload_ids = (
            AIRudderDialerTaskUpload.objects
            .filter(cdate__date=now.date(), task_id__isnull=False)
            .values_list("pk", flat=True)
        )

        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        for dialer_task_upload_id in dialer_task_upload_ids:
            send_get_total_request_to_airudder.delay(
                dialer_task_upload_id=dialer_task_upload_id,
                start_time=start_time,
                end_time=end_time
            )

    def init_download_call_result_per_task(
        self,
        dialer_task_upload: AIRudderDialerTaskUpload,
        total_downloaded: int,
        start_time: datetime,
        end_time: datetime
    ):
        time_range = self.get_time_range(start_time=start_time, end_time=end_time)
        limit = get_download_limit_fs_params()
        num_of_page = math.ceil(total_downloaded / limit)

        for page_num in range(num_of_page):
            dialer_task_download = AIRudderDialerTaskDownload.objects.create(
                dialer_task_upload=dialer_task_upload,
                total_downloaded=total_downloaded,
                time_range=time_range,
                limit=limit,
                offset=page_num*limit
            )
            send_get_call_list_request_to_airudder.delay(
                dialer_task_download_id=dialer_task_download.id,
                start_time=start_time,
                end_time=end_time
            )

    def capture_call_result_data_to_sales_ops(self, call_list: List[dict]):
        for call_result in call_list:
            self.create_sales_ops_agent_assignment(call_result)

    def get_time_range(self, start_time: datetime, end_time: datetime) -> str:
        return "{start_time}_{end_time}".format(
            start_time=start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_time=end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def create_sales_ops_agent_assignment(self, call_result: dict):
        account_id = call_result["customerInfo"]['account_id']
        agent_name = call_result['agentName']
        completed_date = parser.isoparse(call_result["endtime"])

        lineup = SalesOpsLineup.objects.filter(account_id=account_id).last()
        if not lineup:
            return

        agent = Agent.objects.filter(user__username=agent_name).last()
        now = timezone.localtime(timezone.now())
        is_rpc = self.map_airudder_call_status_to_rpc(call_result)

        if is_rpc:
            create_salesops_rpc_agent_assignment(
                lineup, agent, now, completed_date
            )
        else:
            create_salesops_non_rpc_agent_assignment(
                lineup, agent, now, completed_date
            )

    def map_airudder_call_status_to_rpc(self, call_result: dict) -> bool:
        call_result_type = call_result['callResultType']
        call_result_levels = {
            result_level["title"].replace(" ", "_").lower(): result_level["value"]
            for result_level in call_result["customizeResults"]
        }
        level_1 = call_result_levels['level_1']
        level_2 = call_result_levels['level_2']

        is_rpc = all([
            call_result_type in SalesOpsPDSDownloadConst.IS_RPC_CALL_RESULT_TYPES,
            level_1 == SalesOpsPDSDownloadConst.IS_RPC_LEVEL_1,
            level_2 == SalesOpsPDSDownloadConst.IS_RPC_LEVEL_2
        ])
        return is_rpc


class AIRudderPDSDownloadService:
    def __init__(self, task_id: str, start_time: datetime, end_time: datetime):
        self.task_id = task_id
        self.start_time = start_time
        self.end_time = end_time

    def get_airudder_client(self) -> GeneralAIRudderPDSClient:
        airudder_client = get_sales_ops_airudder_pds_client()
        return airudder_client

    def get_total(self) -> int:
        fn_name = "AIRudderPDSDownloadService.get_call_list"
        airudder_client = self.get_airudder_client()

        response = airudder_client.query_task_detail(
            task_id=self.task_id,
            start_time=self.start_time,
            end_time=self.end_time,
            limit=1,
            offset=0,
        )

        response_body = response.get('body')
        if not response_body:
            raise JuloException(
                "{} not return correct response. Returned response {}".format(
                    fn_name, str(response)
                )
            )

        total = response_body.get('total')
        if total is None:
            raise JuloException(
                "{} not return correct response. Returned response {}".format(
                    fn_name, str(response)
                )
            )
        return total

    def get_call_list(self, offset: int, limit: int) -> List[dict]:
        fn_name = "AIRudderPDSDownloadService.get_call_list"
        airudder_client = self.get_airudder_client()

        response = airudder_client.query_task_detail(
            task_id=self.task_id,
            start_time=self.start_time,
            end_time=self.end_time,
            limit=limit,
            offset=offset,
            need_customer_info=True
        )

        response_body = response.get('body')
        if not response_body:
            raise JuloException(
                "{} not return correct response. Returned response {}".format(
                    fn_name, str(response)
                )
            )

        call_list = response_body.get('list')
        if not call_list:
            raise JuloException(
                "{} not return correct response. Returned response {}".format(
                    fn_name, str(response_body)
                )
            )
        return call_list


class AIRudderPDSDownloadManager:
    class NeedRetryException(Exception):
        pass

    class NoNeedRetryException(Exception):
        pass

    def __init__(self, airudder_download_service: AIRudderPDSDownloadService):
        self.airudder_download_service = airudder_download_service

    def get_total(self) -> int:
        try:
            total = self.airudder_download_service.get_total()
        except (ConnectionError, Timeout) as error:
            raise self.NeedRetryException("Need to retry") from error
        except HTTPError as error:
            http_resp = error.response
            if not http_resp:
                raise self.NeedRetryException("Need to retry") from error

            if http_resp.status_code == 429 or http_resp.status_code >= 500:
                raise self.NeedRetryException("Need to retry") from error

            raise error

        return total

    def get_call_list(self, offset: int, limit: int) -> List[dict]:
        try:
            call_list = self.airudder_download_service.get_call_list(offset, limit)
        except (ConnectionError, Timeout) as error:
            raise self.NeedRetryException("Need to retry") from error
        except HTTPError as error:
            http_resp = error.response
            if not http_resp:
                raise self.NeedRetryException("Need to retry") from error

            if http_resp.status_code == 429 or http_resp.status_code >= 500:
                raise self.NeedRetryException("Need to retry") from error

            raise error

        return call_list

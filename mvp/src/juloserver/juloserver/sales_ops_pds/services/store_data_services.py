import csv
import os
import logging
from typing import Optional
from requests import (
    HTTPError,
    ConnectionError,
    Timeout,
)
from typing import List

from django.conf import settings
from django.utils import timezone

from juloserver.fdc.files import TempDir

from juloserver.julo.exceptions import JuloException
from juloserver.julo.utils import upload_file_to_oss
from juloserver.julocore.utils import download_file

from juloserver.sales_ops_pds.models import (
    AIRudderDialerTaskUpload,
    AIRudderDialerTaskDownload,
    AIRudderVendorRecordingDetail
)
from juloserver.sales_ops_pds.tasks import process_recording_file_task
from juloserver.julo.models import Agent
from juloserver.sales_ops_pds.services.general_services import (
    get_format_call_result_fs_params
)
from juloserver.sales_ops_pds.constants import SalesOpsPDSConst
from juloserver.sales_ops_pds.serializers import AIRudderCallResultSerializer

logger = logging.getLogger(__name__)


class StoreSalesOpsPDSDataBase:
    def __init__(self, data: List[dict], store_type: str):
        self.data = data
        self.store_type = store_type

    def _validate_store_data(self):
        if not self.data:
            raise JuloException("Empty data")

    def create_csv_file_and_upload_to_oss(self, file_name: str, remote_filepath: str):
        with TempDir(dir="/media") as tempdir:
            dir_path = tempdir.path
            local_filepath = os.path.join(dir_path, file_name)

            with open(local_filepath, "w") as csv_file:
                headers = list(self.data[0].keys())
                writer = csv.DictWriter(csv_file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(self.data)

            upload_file_to_oss(
                bucket_name=settings.OSS_MEDIA_BUCKET,
                local_filepath=local_filepath,
                remote_filepath=remote_filepath
            )


class StoreSalesOpsPDSUploadData(StoreSalesOpsPDSDataBase):
    def __init__(self, data: List[dict], store_type: str, dialer_task_upload_id: int):
        super().__init__(data, store_type)
        self.dialer_task_upload_id = dialer_task_upload_id
        self._dialer_task_upload = self.get_dialer_task_upload()

    def get_dialer_task_upload(self) -> AIRudderDialerTaskUpload:
        if not self.dialer_task_upload_id:
            return

        dialer_task_upload = AIRudderDialerTaskUpload.objects.filter(
            pk=self.dialer_task_upload_id
        ).last()
        if not dialer_task_upload:
            raise JuloException(
                "Not found dialer task upload ID {id}".format(id=self.dialer_task_upload_id)
            )

        return dialer_task_upload

    def get_upload_file_name(self) -> str:
        dialer_task_group = self._dialer_task_upload.dialer_task_group
        file_name = "{bucket}_{type}_{timestamp}_p{batch_number}.csv".format(
            bucket=dialer_task_group.bucket_code.title().replace("_", ""),
            type=dialer_task_group.customer_type.title().replace("_", ""),
            timestamp=timezone.localtime(timezone.now()).strftime("%Y%m%d-%H%M"),
            batch_number=str(self._dialer_task_upload.batch_number)
        )
        return file_name

    def get_upload_remote_filepath(self, file_name: str) -> str:
        remoth_path = "{sub_app}/{sub_folder}/{date}/{file_name}".format(
            sub_app=SalesOpsPDSConst.SUB_APP,
            sub_folder=self.store_type,
            date=timezone.localtime(timezone.now()).strftime("%Y%m%d"),
            file_name=file_name
        )
        return remoth_path

    def store_data(self) -> str:
        self._validate_store_data()
        file_name = self.get_upload_file_name()
        remote_filepath = self.get_upload_remote_filepath(file_name)
        self.create_csv_file_and_upload_to_oss(
            file_name=file_name, remote_filepath=remote_filepath
        )
        return remote_filepath

    def store_uploaded_data(self):
        remote_filepath = self.store_data()
        self._dialer_task_upload.update_safely(upload_file_url=remote_filepath)

    def store_failed_uploaded_data(self):
        remote_filepath = self.store_data()
        self._dialer_task_upload.update_safely(result_file_url=remote_filepath)


class StoreSalesOpsPDSDownloadData(StoreSalesOpsPDSDataBase):
    def __init__(self, data: List[dict], store_type: str, dialer_task_download_id: int):
        super().__init__(data, store_type)
        self.dialer_task_download_id = dialer_task_download_id
        self._dialer_task_download = self.get_dialer_task_download()
        self.formatted_fields = get_format_call_result_fs_params()

    def get_dialer_task_download(self) -> AIRudderDialerTaskDownload:
        if not self.dialer_task_download_id:
            return

        dialer_task_download = AIRudderDialerTaskDownload.objects.filter(
            pk=self.dialer_task_download_id
        ).last()
        if not dialer_task_download:
            raise JuloException(
                "Not found dialer task download ID {id}".format(
                    id=self.dialer_task_download_id
                )
            )

        return dialer_task_download

    def get_download_file_name(self) -> str:
        dialer_task_upload = self._dialer_task_download.dialer_task_upload
        dialer_task_group = dialer_task_upload.dialer_task_group
        file_name = "{bucket}_{type}_{time_range}_o{offset}_l{limit}.csv".format(
            bucket=dialer_task_group.bucket_code.title().replace("_", ""),
            type=dialer_task_group.customer_type.title().replace("_", ""),
            time_range=self._dialer_task_download.time_range,
            offset=self._dialer_task_download.offset,
            limit=self._dialer_task_download.limit
        )
        return file_name

    def get_download_remote_filepath(self, file_name: str) -> str:
        remoth_path = "{sub_app}/{sub_folder}/{date}/{file_name}".format(
            sub_app=SalesOpsPDSConst.SUB_APP,
            sub_folder=self.store_type,
            date=timezone.localtime(timezone.now()).strftime("%Y%m%d"),
            file_name=file_name
        )
        return remoth_path

    def store_data(self) -> str:
        file_name = self.get_download_file_name()
        remote_filepath = self.get_download_remote_filepath(file_name)
        self.create_csv_file_and_upload_to_oss(
            file_name=file_name, remote_filepath=remote_filepath
        )
        return remote_filepath

    def normalize_download_file(self):
        if self.formatted_fields:
            self.normalize_data_with_configured_format()
        else:
            self.normalize_data_with_default_format()

    def normalize_data_with_default_format(self):
        serializer = AIRudderCallResultSerializer(data=self.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.data = serializer.validated_data

    def normalize_data_with_configured_format(self):
        self.data = list(
            map(lambda line: self.normalize_line(line), self.data)
        )

    def normalize_line(self, line: dict):
        formatted_line = dict()
        for field, value in self.formatted_fields.items():
            if field == "customerInfo":
                formatted_line.update({
                    sub_value: line[field].get(sub_field, "")
                    for sub_field, sub_value in value.items()
                })
            elif field == "customizeResults" and value == True:
                formatted_line.update({
                    result["title"]: result["value"]
                    for result in line["customizeResults"]
                })
            else:
                formatted_line.update({value: line.get(field, "")})
        return formatted_line

    def store_downloaded_data(self):
        self.normalize_download_file()
        remote_filepath = self.store_data()
        self._dialer_task_download.update_safely(download_file_url=remote_filepath)


class StoreSalesOpsPDSRecordingFile:
    def get_upload_remote_filepath(self, local_filepath: str) -> str:
        file_name = self.get_upload_filename(local_filepath)
        remote_path = "{sub_app}/{sub_folder}/{date}/{file_name}".format(
            sub_app=SalesOpsPDSConst.SUB_APP,
            sub_folder=SalesOpsPDSConst.RECORDING_FILE_SUB_FOLDER,
            date=timezone.localtime(timezone.now()).strftime("%Y%m%d"),
            file_name=file_name
        )
        return remote_path

    def get_upload_filename(self, filepath: str) -> str:
        return os.path.basename(filepath)

    def create_airudder_vendor_recording_detail(
        self,
        call_result: dict,
        remote_filepath: str,
        dialer_task_upload_id: int
    ) -> AIRudderVendorRecordingDetail:
        agent = Agent.objects.filter(
            user_extension__icontains=call_result['agentName']
        ).last()
        if not agent:
            raise JuloException("Agent not found")

        dialer_task_upload = AIRudderDialerTaskUpload.objects.filter(
            pk=dialer_task_upload_id
        ).last()

        bucket_code = dialer_task_upload.dialer_task_group.bucket_code

        airudder_vendor_recording_detail = AIRudderVendorRecordingDetail.objects.create(
            bucket_code=bucket_code,
            call_to=call_result['phoneNumber'],
            call_start=call_result['calltime'],
            call_end=call_result['endtime'],
            duration=call_result['talkDuration'],
            call_id=call_result['callid'],
            customer_id=call_result['customerInfo']['customer_id'],
            agent_id=agent.pk,
            recording_url=remote_filepath,
            dialer_task_upload=dialer_task_upload,
        )
        return airudder_vendor_recording_detail

    def retrieve_call_result_recordings(self, call_list: List[dict], dialer_task_upload_id: int):
        """
            Process recording files from call result CSV data:
            - Download recording file as a temp file.
            - Upload file to OSS.
        """
        for call_result in call_list:
            if call_result.get('reclink'):
                process_recording_file_task.delay(
                    call_result=call_result,
                    dialer_task_upload_id=dialer_task_upload_id
                )

    def fetch_recording_file(self, reclink: str) -> str:
        upload_filename = self.get_upload_filename(reclink)
        directory = os.path.join('media/', SalesOpsPDSConst.SUB_APP)
        os.makedirs(directory, exist_ok=True)
        try:
            local_filepath = download_file(url=reclink, dir=directory, filename=upload_filename)
        except Exception as e:
            raise e

        return local_filepath

    def store_and_upload_recording_file(
        self,
        call_result: dict,
        local_filepath: str,
        dialer_task_upload_id: int
    ):
        """
        Store recording file details in SalesOpsPDSTable and upload to OSS.

        Args:
            call_result (dict): Call result data.
            local_file_path (str): Path to the downloaded recording file.
        """
        remote_filepath = self.get_upload_remote_filepath(
            local_filepath=local_filepath,
        )
        upload_file_to_oss(
            bucket_name=settings.OSS_MEDIA_BUCKET,
            local_filepath=local_filepath,
            remote_filepath=remote_filepath
        )

        airudder_vendor_recording_detail = self.create_airudder_vendor_recording_detail(
            call_result=call_result,
            remote_filepath=remote_filepath,
            dialer_task_upload_id=dialer_task_upload_id)
        # Update URL in airudder_vendor_recording_detail
        airudder_vendor_recording_detail.update_safely(recording_url=remote_filepath)
        # Remove local file after uploading
        if os.path.exists(local_filepath):
            os.remove(local_filepath)


class SalesOpsPDSRecordingFileManager:
    class NeedRetryException(Exception):
        pass

    def __init__(self, sales_ops_pds_recording_file: StoreSalesOpsPDSRecordingFile):
        self.sales_ops_pds_recording_file = sales_ops_pds_recording_file

    def fetch_recording_file(self, reclink: str) -> Optional[str]:
        try:
            local_filepath = self.sales_ops_pds_recording_file.fetch_recording_file(reclink)
        except (ConnectionError, Timeout) as error:
            raise self.NeedRetryException("Need to retry") from error
        except HTTPError as error:
            http_resp = error.response
            if not http_resp:
                raise self.NeedRetryException("Need to retry") from error

            if http_resp.status_code == 429 or http_resp.status_code >= 500:
                raise self.NeedRetryException("Need to retry") from error

            raise error

        return local_filepath

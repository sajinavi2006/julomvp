from django.utils.functional import cached_property
import json
import logging
import typing
from dataclasses import asdict
from requests import Response
from juloserver.antifraud.models.fraud_db_models import MonnaiRequestLogData
from juloserver.antifraud.tasks import store_monnai_log
from juloserver.antifraud.constant.feature_setting import FeatureNameConst
from juloserver.julo.services2.feature_setting import FeatureSettingHelper


logger = logging.getLogger(__name__)


class MonnaiRequestLogService:
    def __init__(self, monnai_response_json: dict, application_id: int, packages: typing.List[str]):
        self.response: dict = monnai_response_json
        self.application_id: int = application_id
        self.log: MonnaiRequestLogData = MonnaiRequestLogData(
            packages=','.join(packages), application_id=application_id
        )
        self.is_device_details = 'DEVICE_DETAILS' in packages
        self.is_telco_maid = self.is_device_details or 'ADDRESS_VERIFICATION' in packages

    @cached_property
    def setting(self):
        return FeatureSettingHelper(FeatureNameConst.ANTIFRAUD_STORE_MONNAI_LOG)

    def parse_response_to_log(self):
        meta = self.response.get('meta', {}) or {}
        self.log.reference_id = meta.get('referenceId', '') or ''

        if not self.is_telco_maid:
            return

        self.log.raw_response = json.dumps(self.response.get('data', {}) or {})

        if not self.is_device_details:
            return

        data = ((self.response.get('data', {}) or {}).get('device', {}) or {}).get(
            'deviceRecords', []
        ) or []

        if not data:
            return

        if len(data) < 1:
            return

        data = data[0]

        device_details = data.get('deviceDetails', {}) or {}
        self.log.has_device_info = any(device_details.values())

        location = data.get('location', {}) or {}
        self.log.has_device_location = any(location.values())

    def as_dict(self):
        return asdict(self.log)

    def send(self):
        store_monnai_log.delay(self.as_dict())

    @staticmethod
    def get_monnai_log_svc(
        response: Response, application_id: int, packages: typing.List[str]
    ) -> typing.Type['MonnaiRequestLogService']:
        if response.status_code != 200 and response.status_code != 201:
            return None
        try:
            monnaisvc = MonnaiRequestLogService(
                monnai_response_json=response.json(),
                application_id=application_id,
                packages=packages,
            )
            if not monnaisvc.setting.is_active:
                return None

            monnaisvc.parse_response_to_log()
            return monnaisvc
        except Exception as e:
            logger.error(msg={'action': 'get_monnai_log_svc', 'error': str(e)}, exc_info=True)
            return None

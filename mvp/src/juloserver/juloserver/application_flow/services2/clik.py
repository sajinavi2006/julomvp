import os
import time

import requests
import urllib3

from juloserver.application_flow.models import ClikScoringResult
from juloserver.julo.models import Application, MobileFeatureSetting
from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julolog.julolog import JuloLog
from juloserver.cfs.services.core_services import get_pgood
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource

logger = JuloLog(__name__)


class CLIKError(Exception):
    pass


class CLIKClient:

    CLIK_ENDPOINT = os.getenv("CLIK_ENDPOINT")
    APPLICATION_TAG = "is_clik_pass"
    TAG_STATUS_FAILED = 0
    TAG_STATUS_SUCCESS = 1
    TYPE_SWAP_IN = 'swap_in'
    TYPE_SWAP_OUT = 'swap_out'
    TYPE_SHADOW_SCORE = 'shadow_score'
    TYPE_HOLDOUT = 'holdout'
    TYPE_CLIK_MODEL = 'clik_model'

    _GENDER_MAPPING = {'pria': 'L', 'wanita': 'P'}
    _optional_fields = ['birthplace', 'address', 'mobile_phone_1', 'zipcode']

    def __init__(self, application: Application):
        self.application = application
        self.request = None
        self.swap_in_setting = None
        self.swap_out_setting = None
        self.response = None

    def _update_tag(self, to):
        from juloserver.application_flow.services import ApplicationTagTracking

        tag_tracking = ApplicationTagTracking(application=self.application)
        tag_tracking.tracking(tag=self.APPLICATION_TAG, status=to, certain=True)

    def update_tag_to_success(self):
        """
        Assign tag to the application
        """
        logger.info(
            {
                "message": "CLIK updating status to success",
                "application_id": self.application.id,
            }
        )
        self._update_tag(to=self.TAG_STATUS_SUCCESS)

    def update_tag_to_failed(self):
        """
        Assign failed tag to the application
        """
        logger.info(
            {
                "message": "CLIK updating status to failed",
                "application_id": self.application.id,
            }
        )
        self._update_tag(to=self.TAG_STATUS_FAILED)

    def get_clik_setting(self):
        return MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.CLIK_INTEGRATION
        ).last()

    def get_payload(self, path="nae", sync=True):
        customer = self.application.customer

        if not self.application.application_xid:
            self.application.generate_xid()

        # detokenized before preparing payload
        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': customer.customer_xid,
                    'object': self.application,
                }
            ],
            force_get_local_data=True,
        )
        self.application = detokenized_applications[0]

        empty_optional_fields = []
        postal_code = self.application.address_kodepos
        if not postal_code:
            postal_code = "12345"
            empty_optional_fields.append('zipcode')

        address = self.application.address_street_num
        if not address:
            address = "data belum tersedia"
            empty_optional_fields.append('address')

        sub_district = self.application.address_kelurahan
        if not sub_district:
            sub_district = "data belum tersedia"

        district = self.application.address_kecamatan
        if not district:
            district = "data belum tersedia"

        city = self.application.address_kabupaten
        if not city:
            city = "9999"

        mobile_phone = self.application.mobile_phone_1
        if not mobile_phone:
            mobile_phone = "0812"
            empty_optional_fields.append('mobile_phone_1')

        birhtplace = self.application.birth_place
        if not birhtplace:
            birhtplace = 'data belum tersedia'
            empty_optional_fields.append('birthplace')

        gender = self._GENDER_MAPPING.get(
            str(self.application.gender).lower(), 'data belum tersedia'
        )

        data = {
            'Resident': '',
            'Gender': gender,
            'MarriageStatus': '',
            'EducationalStatus': '',
            'NameAsId': self.application.full_name_only,
            'FullName': self.application.full_name_only,
            'MothersName': customer.mother_maiden_name,
            'BirthDate': str(customer.dob),
            'BirthPlace': birhtplace,
            'Address': address,
            'SubDistrict': sub_district,
            'District': district,
            'City': city,
            'PostalCode': postal_code,
            'Country': 'ID',
            'IdentityType': '1',
            'IdentityNumber': self.application.ktp,
            'PhoneNumber': mobile_phone,
            'CellphoneNumber': mobile_phone,
            'EmailAddress': self.application.email,
            'OccupationCode': '',
            'Workplace': '',
            'EmployerSector': '',
            'WorkplaceAddress': '',
            'application_id': str(self.application.id),
        }
        if path == 'nae':
            data.update(
                {
                    'ApplicationAmount': '1000000',
                    'DueDate': '',
                    'OriginalAgreementNumber': '',
                    'OriginalAgreementDate': '',
                    'ProviderApplicationNo': str(self.application.application_xid),
                    'sync': sync,
                }
            )

        if empty_optional_fields:
            logger.info(
                {
                    'action': 'ClikClient | get_payload',
                    'message': 'Empty optional fields detected',
                    'empty_fields': empty_optional_fields,
                }
            )

        return data

    def get(self, path):
        url = '{}{}'.format(self.CLIK_ENDPOINT, path)

        response = requests.get(url)

        return response

    def post(self, path, headers, data):
        url = '{}{}'.format(self.CLIK_ENDPOINT, path)

        response = requests.post(url, json=data, headers=headers)

        return response

    def process_shadow_score(self):
        setting = self.get_clik_setting()

        if not setting or not setting.is_active:
            return

        if not setting.parameters['shadow_score']:
            return

        if setting.parameters['shadow_score']['is_active']:
            try:
                result = ClikScoringResult.objects.filter(application_id=self.application.id).last()
                if result and result.type == self.TYPE_CLIK_MODEL:
                    logger.info(
                        {
                            "action": "process_shadow_score",
                            "message": "passing shadow score because application is_clik_model",
                            "application_id": self.application.id,
                        }
                    )
                    return
                if not result:
                    new_enquiry = self.new_enquiry()
                    self.get_and_store_data_from_clik('nae', self.TYPE_SHADOW_SCORE)
            except (
                CLIKError,
                urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
            ) as e:
                logger.info(
                    {
                        'action': 'CLIK - Shadow Score Error',
                        'data': {'application_id': self.application.id, 'message': str(e)},
                    }
                )
                get_julo_sentry_client().captureException()
        return

    def process_swap_in(self):
        setting = self.get_clik_setting()

        if not setting or not setting.is_active:
            return False

        if not setting.parameters['swap_ins']:
            return False

        if setting.parameters['swap_ins']['is_active']:
            try:
                self.swap_in_setting = setting.parameters['swap_ins']
                result = ClikScoringResult.objects.filter(application_id=self.application.id).last()
                if result:
                    data = dict(
                        score_raw=result.score_raw,
                        total_overdue_amount=result.total_overdue_amount,
                    )
                    return self.eligible_pass_swap_in(data)
                else:
                    new_enquiry = self.new_enquiry()

                    if new_enquiry:
                        swap_in = self.swap_in()

                        return swap_in
            except (
                CLIKError,
                urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
            ) as e:
                logger.info(
                    {
                        'action': 'CLIK - Swap In Error',
                        'data': {'application_id': self.application.id, 'message': str(e)},
                    }
                )
                get_julo_sentry_client().captureException()
        return False

    def pass_swap_out(self):
        setting = self.get_clik_setting()

        if not setting or not setting.is_active:
            return True

        if not setting.parameters['swap_outs']:
            return True

        if setting.parameters['swap_outs']['is_active']:
            try:
                self.swap_out_setting = setting.parameters['swap_outs']

                clik_data = ClikScoringResult.objects.filter(application_id=self.application.id).last()
                if clik_data:
                    logger.info(
                        {
                            "action": "CLIK Swap Out: use existing data",
                            "application_id": self.application.id,
                        }
                    )

                    data = {
                        'total_overdue_amount': clik_data.total_overdue_amount,
                        'score_raw': clik_data.score_raw,
                        'reporting_providers_number': clik_data.reporting_providers_number,
                    }
                    return self.check_swap_out(data)
                else:
                    new_enquiry = self.new_enquiry()

                    if new_enquiry:
                        return self.swap_out('nae')

            except (
                CLIKError,
                urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
            ) as e:
                logger.info(
                    {
                        'action': 'CLIK - Swap Out Error',
                        'data': {'application_id': self.application.id, 'message': str(e)},
                    }
                )
                get_julo_sentry_client().captureException()
        return True

    def new_enquiry(self):
        try:
            headers = {"Content-Type": "application/json"}
            path = "nae"

            data = self.get_payload(path, True)

            logger.info(
                {
                    "action": "CLIK New Enquiry",
                    "application_id": self.application.id,
                    "data": data,
                }
            )
            response = self.post(path, headers, data)
            self.response = response

            if response.status_code != 200:
                raise CLIKError("Failed to get new enquiry from CLIK")
        except (
            CLIKError,
            urllib3.exceptions.ReadTimeoutError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
        ) as e:
            logger.info(
                {
                    "action": "CLIK New Enquiry",
                    "application_id": self.application.id,
                    "error": str(e),
                }
            )
            get_julo_sentry_client().captureException()
            return False

        return True

    def monitoring_enquiry(self):
        try:
            headers = {"Content-Type": "application/json"}
            path = "me"

            data = self.get_payload(path)

            logger.info(
                {
                    "action": "CLIK Monitoring Enquiry",
                    "application_id": self.application.id,
                    "data": data,
                }
            )
            response = self.post(path, headers, data)

            if response.status_code != 200:
                raise CLIKError("Failed to send monitoring enquiry to CLIK")
        except (
            CLIKError,
            urllib3.exceptions.ReadTimeoutError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
        ) as e:
            logger.info(
                {
                    "action": "CLIK Monitoring Enquiry",
                    "application_id": self.application.id,
                    "error": str(e),
                }
            )
            get_julo_sentry_client().captureException()
            return False

        return True

    def swap_in(self):
        logger.info(
            {
                "action": "CLIK Swap In",
                "application_id": self.application.id,
            }
        )

        data = self.get_and_store_data_from_clik('nae', self.TYPE_SWAP_IN)

        if not data:
            return False

        return self.eligible_pass_swap_in(data)

    def swap_out(self, enquiry_type):
        logger.info(
            {
                "action": "CLIK Swap Out",
                "application_id": self.application.id,
            }
        )

        data = self.get_and_store_data_from_clik(enquiry_type, self.TYPE_SWAP_OUT)

        if not data:
            return True

        return self.check_swap_out(data)

    def get_and_store_data_from_clik(self, enquiry_type, scoring_type):
        response = self.response
        if not response:
            path = (
                str(self.application.ktp)
                if enquiry_type == 'me'
                else str(self.application.application_xid)
            )
            path += '/all'
            logger.info(
                {
                    "action": "CLIK Get Data - " + enquiry_type,
                    "application_id": self.application.id,
                }
            )
            response = self.get(path)

        result = response.json()

        if response.status_code != 200:
            logger.info(
                {
                    "action": "CLIK Get Data - " + enquiry_type + "Failed",
                    "application_id": self.application.id,
                    "error": result['error'],
                }
            )
            return False

        application_id = self.application.id
        product_output_type = (
            'CB_ME_ProductOutput' if enquiry_type == 'me' else 'CB_NAE_ProductOutput'
        )
        enquiry_type = result['data']['enquiry_type']
        score_raw = result['data']['json_data']['Body']['MGResult']['ProductResponse'][
            product_output_type
        ]['CBScore']['CBSGlocal']['ScoreData']['ScoreRaw']
        score_range = result['data']['json_data']['Body']['MGResult']['ProductResponse'][
            product_output_type
        ]['CBScore']['CBSGlocal']['ScoreData']['ScoreRange']
        score_message_desc = result['data']['json_data']['Body']['MGResult']['ProductResponse'][
            product_output_type
        ]['CBScore']['CBSGlocal']['ScoreData']['ScoreMessage']['Description']
        total_overdue_amount = result['data']['json_data']['Body']['MGResult']['ProductResponse'][
            product_output_type
        ]['CreditReport']['ContractsHistory']['AggregatedData']['TotalOverdue']
        reporting_providers_number = result['data']['json_data']['Body']['MGResult'][
            'ProductResponse'
        ][product_output_type]['CreditReport']['ContractsHistory']['AggregatedData'][
            'ReportingProvidersNumber'
        ]

        data = dict(
            application_id=application_id,
            enquiry_type=enquiry_type,
            score_raw=score_raw,
            score_range=score_range,
            score_message_desc=score_message_desc,
            total_overdue_amount=total_overdue_amount,
            reporting_providers_number=reporting_providers_number,
            type=scoring_type,
        )

        self._store_response_to_table(data)
        logger.info(
            {
                "action": "CLIK store response to table",
                "application_id": self.application.id,
                "data": data,
            }
        )

        return data

    def _store_response_to_table(self, data):
        ClikScoringResult.objects.create(**data)

    def eligible_pass_swap_in(self, data):
        total_overdue_amount = data['total_overdue_amount'] if data['total_overdue_amount'] else 0
        score_raw = data['score_raw'] if data['score_raw'] else 0

        if int(total_overdue_amount) >= self.swap_in_setting['total_overdue']:
            return False

        if int(score_raw) < self.swap_in_setting['score_raw']:
            return False

        if get_pgood(self.application.id) < self.swap_in_setting['pgood']:
            return False

        self.update_tag_to_success()
        return True

    def check_swap_out(self, data):
        total_overdue_amount = data['total_overdue_amount'] if data['total_overdue_amount'] else 0
        score_raw = data['score_raw'] if data['score_raw'] else 0
        reporting_providers_number = (
            data['reporting_providers_number'] if data['reporting_providers_number'] else 0
        )

        if int(total_overdue_amount) < self.swap_out_setting['total_overdue']:
            return True

        if int(score_raw) >= self.swap_out_setting['score_raw']:
            return True

        if int(reporting_providers_number) >= self.swap_out_setting['reporting_providers']:
            return True

        return False

    def process_clik_model_on_submission(self):
        try:
            result = ClikScoringResult.objects.filter(application_id=self.application.id).last()
            if result:
                return True
            else:
                self.new_enquiry()
                self.get_and_store_data_from_clik('nae', self.TYPE_CLIK_MODEL)
                if self.response.status_code == 200:
                    return True
                return False
        except (
            CLIKError,
            urllib3.exceptions.ReadTimeoutError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
        ) as e:
            logger.info(
                {
                    'action': 'CLIK - Process Clik Model Error',
                    'data': {'application_id': self.application.id, 'message': str(e)},
                }
            )
            get_julo_sentry_client().captureException()
        return False

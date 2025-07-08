import requests
import urllib3

from juloserver.application_flow.models import ClikScoringResult
from juloserver.application_flow.services2.clik import CLIKClient, CLIKError
from juloserver.julo.models import Application
from juloserver.julo.utils import post_anaserver
from juloserver.julolog.julolog import JuloLog
from juloserver.partnership.constants import (
    PartnershipCLIKScoringStatus,
    PartnershipFlag,
    PartnershipClikModelResultStatus,
)
from juloserver.partnership.models import PartnershipFlowFlag, PartnershipClikModelResult

logger = JuloLog(__name__)


class PartnershipCLIKClient(CLIKClient):
    def __init__(self, application: Application):
        super().__init__(application=application)
        self.result = None  # ClickScoringResult
        self.clik_model_setting = None

    def get_partner_clik_setting(self):
        return PartnershipFlowFlag.objects.filter(
            partner=self.application.partner,
            name=PartnershipFlag.CLIK_INTEGRATION,
        ).last()

    def partnership_process_swap_in(self) -> str:
        fn_name = "PartnershipCLIKClient.partnership_process_swap_in()"
        setting = self.get_partner_clik_setting()

        if not setting:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Partner flow flag not found",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        self.swap_in_setting = setting.configs.get('swap_ins')
        if not self.swap_in_setting:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Click swap in setting not found",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        elif not self.swap_in_setting['is_active']:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Click swap in setting not active",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        else:
            try:
                result = ClikScoringResult.objects.filter(application_id=self.application.id).last()
                if result:
                    data = dict(
                        score_raw=result.score_raw,
                        total_overdue_amount=result.total_overdue_amount,
                    )

                    if self._is_empty_result(data=data):
                        return PartnershipCLIKScoringStatus.EMPTY_RESULT

                    is_okay_swap_in = self.leadgen_eligible_pass_swap_in(data)
                    if is_okay_swap_in:
                        return PartnershipCLIKScoringStatus.PASSED_SWAP_IN
                else:
                    new_enquiry = self.new_enquiry()

                    if new_enquiry:
                        data = self.get_and_store_data_from_clik('nae', self.TYPE_SWAP_IN)

                        if not data:
                            return PartnershipCLIKScoringStatus.FAILED_CLICK_SCORING

                        if self._is_empty_result(data=data):
                            return PartnershipCLIKScoringStatus.EMPTY_RESULT

                        is_okay_swap_in = self.leadgen_eligible_pass_swap_in(data)
                        if is_okay_swap_in:
                            return PartnershipCLIKScoringStatus.PASSED_SWAP_IN
            except (
                CLIKError,
                urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
            ) as e:
                logger.info(
                    {
                        'action': fn_name,
                        'message': 'CLIK - Swap In Error',
                        'application_id': self.application.id,
                        'error': str(e),
                    }
                )

        return PartnershipCLIKScoringStatus.FAILED_SWAP_IN

    def leadgen_eligible_pass_swap_in(self, data: dict) -> bool:
        score_raw = data['score_raw'] if data['score_raw'] else 0

        if int(score_raw) >= self.swap_in_setting['score_raw']:
            self.update_tag_to_success()
            return True

        return False

    def _is_empty_result(self, data: dict) -> bool:
        score_raw = data.get('score_raw')
        if score_raw is None or score_raw == "":
            return True

        return False

    def partnership_process_clik_model(self):
        fn_name = "PartnershipCLIKClient.partnership_process_clik_model()"
        setting = self.get_partner_clik_setting()

        if not setting:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Partner flow flag not found",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        self.clik_model_setting = setting.configs.get('clik_model')
        if not self.clik_model_setting:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Clik model setting not found",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        elif not self.clik_model_setting['is_active']:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Clik model setting not active",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        else:
            try:
                result = ClikScoringResult.objects.filter(
                    application_id=self.application.id, type='clik_model'
                ).last()

                if not result:
                    new_enquiry = self.new_enquiry()

                    if new_enquiry:
                        data = self.get_and_store_data_from_clik('nae', self.TYPE_CLIK_MODEL)

                        if not data:
                            return PartnershipCLIKScoringStatus.FAILED_CLICK_SCORING

                # Hit ANA to run CLIK model and generate CLIK pgood
                self.run_ana_partnership_clik_model()

                PartnershipClikModelResult.objects.create(
                    application_id=self.application.id,
                    status=PartnershipClikModelResultStatus.IN_PROGRESS,
                    pgood=float(0),
                )

                return PartnershipCLIKScoringStatus.PASSED_CLICK_SCORING

            except Exception as e:
                logger.info(
                    {
                        'action': fn_name,
                        'message': 'CLIK - clik_model Error',
                        'application_id': self.application.id,
                        'error': str(e),
                    }
                )

        return PartnershipCLIKScoringStatus.FAILED_CLICK_SCORING

    def run_ana_partnership_clik_model(self):
        fn_name = "PartnershipCLIKClient.run_ana_partnership_clik_model()"
        ana_data = {'application_id': self.application.id}
        url = '/api/amp/v1/clik/'

        try:
            response = post_anaserver(url, json=ana_data)
            logger.info(
                {
                    'action': fn_name,
                    'message': 'CLIK - ANA clik model response',
                    'application_id': self.application.id,
                    'response_status_code': response.status_code,
                }
            )

        except Exception as e:
            error_message = str(e)
            raise CLIKError(error_message)

    def leadgen_eligible_passed_clik_model(self):
        fn_name = "PartnershipCLIKClient.leadgen_eligible_passed_clik_model()"
        setting = self.get_partner_clik_setting()

        if not setting:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Partner flow flag not found",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        self.clik_model_setting = setting.configs.get('clik_model')
        if not self.clik_model_setting:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Clik model setting not found",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        elif not self.clik_model_setting['is_active']:
            logger.error(
                {
                    'action': fn_name,
                    'message': "Clik model setting not active",
                    'application_id': self.application.id,
                }
            )
            return PartnershipCLIKScoringStatus.FEATURE_NOT_ACTIVE

        else:
            try:
                # Process pgood threshold check
                result = PartnershipClikModelResult.objects.filter(
                    application_id=self.application.id
                ).last()
                if not result:
                    return PartnershipCLIKScoringStatus.EMPTY_RESULT

                # Check if clik flag status
                metadata = result.metadata
                clik_flag_matched = metadata.get('clik_flag_matched', False)
                if not clik_flag_matched:
                    return PartnershipCLIKScoringStatus.EMPTY_RESULT

                # Check if clik model pgood
                pgood = result.pgood
                if float(pgood) >= self.clik_model_setting['pgood']:
                    self.update_tag_to_success()
                    return PartnershipCLIKScoringStatus.PASSED_CLIK_MODEL

            except (
                CLIKError,
                urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
            ) as e:
                logger.info(
                    {
                        'action': fn_name,
                        'message': 'CLIK - clik_model threshold check Error',
                        'application_id': self.application.id,
                        'error': str(e),
                    }
                )

        return PartnershipCLIKScoringStatus.FAILED_CLIK_MODEL

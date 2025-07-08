import logging

from juloserver.julo.workflows import WorkflowAction

from juloserver.application_flow.tasks import application_tag_tracking_task
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.services import process_application_status_change

logger = logging.getLogger(__name__)


class JuloOneIOSWorkflowAction(WorkflowAction):
    def process_hsfbp(self):
        from juloserver.julo.services2.high_score import (
            do_high_score_full_bypass,
            feature_high_score_full_bypass,
        )

        eligible_hsfbp = feature_high_score_full_bypass(self.application)
        if eligible_hsfbp:
            do_hsfbp = do_high_score_full_bypass(self.application)

            if do_hsfbp:
                application_tag_tracking_task(
                    self.application.id, None, None, None, 'is_hsfbp', 1
                )
        else:
            new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            process_application_status_change(
                self.application.id, new_status_code, change_reason='regular flow DV'
            )

    def x124_bypass(self):
        new_status_code = ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
        process_application_status_change(
            self.application.id, new_status_code, change_reason='iOS bypass'
        )

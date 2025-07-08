from juloserver.julo.models import Workflow, Loan
from juloserver.julo.statuses import StatusManager
import logging
logger = logging.getLogger(__name__)

def get_allowed_loan_statuses(status_code, loan_id):
    list_result = []
    loan = Loan.objects.get_or_none(pk=loan_id)
    if loan:
        workflow = Workflow.objects.get(name='LegacyWorkflow')  # use the default one
        allowed_statuses = workflow.workflowstatuspath_set.filter(status_previous=int(status_code),
                                                                  agent_accessible=True, is_active=True)
        if allowed_statuses:
            for status in allowed_statuses:
                logger.info({
                    'status': 'path_found',
                    'path_status': status
                })
                next_status = StatusManager.get_or_none(status.status_next)
                if next_status:
                    list_result.append(next_status)
        else:
            logger.warn({
                'status': 'path_not_found',
                'status_code': status_code
            })
    else:
        logger.warn({
            'status': 'application_not_found',
        })
    return list_result
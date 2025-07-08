from celery.task import task

from juloserver.tokopedia.services.common_service import run_shadow_score_with_toko_score
from juloserver.julolog.julolog import JuloLog

logger = JuloLog(__name__)


@task(queue='application_normal')
def trigger_shadow_score_with_toko_score(application_id):

    logger.info(
        {
            'message': 'Tokoscore: Start execute trigger shadow score',
            'application_id': application_id,
        }
    )

    run_shadow_score_with_toko_score(application_id)

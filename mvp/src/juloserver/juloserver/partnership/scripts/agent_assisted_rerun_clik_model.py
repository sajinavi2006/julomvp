from juloserver.julo.utils import post_anaserver
from juloserver.partnership.constants import PartnershipClikModelResultStatus
from juloserver.partnership.models import PartnershipClikModelResult


def agent_assisted_rerun_clik_model():
    clik_model_results = PartnershipClikModelResult.objects.filter(
        status=PartnershipClikModelResultStatus.IN_PROGRESS
    ).all()

    for click_model in clik_model_results:
        ana_data = {'application_id': click_model.application_id}
        url = '/api/amp/v1/clik/'

        try:
            response = post_anaserver(url, json=ana_data)
            print(
                {
                    'message': 'CLIK - ANA clik model response',
                    'application_id': click_model.application_id,
                    'response_status_code': response.status_code,
                }
            )

        except Exception as e:
            print(
                {
                    'message': 'CLIK - ANA clik model response',
                    'application_id': click_model.application_id,
                    'error_message': str(e),
                }
            )

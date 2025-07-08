from django.conf import settings
from juloserver.julo.models import FeatureSetting, FeatureNameConst
from juloserver.julolog.julolog import JuloLog

logger = JuloLog(__name__)


def mock_determine_pgood(application, pgood_origin):

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.HEIMDALL_MOCK_RESPONSE_SET, is_active=True
    ).last()

    # make sure only testing purpose
    if settings.ENVIRONMENT == 'prod' or not feature_setting:
        logger.info(
            {
                'message': 'Heimdall without mocking response',
                'process': 'mocking_response',
                'application': application.id,
            }
        )
        return pgood_origin
    else:
        # do mocking response if setting is active
        # for testing purpose
        if feature_setting:
            return mock_get_response_heimdall(application, feature_setting, pgood_origin)


def mock_get_response_heimdall(application, feature_setting, pgood_origin):

    parameters = feature_setting.parameters
    products = parameters['products']

    if 'j-starter' in products and application.is_julo_starter():
        mock_response_set = parameters['response_values']['j-starter']
        logger.info(
            {
                'message': 'mocking response heimdall is running',
                'application': application.id,
                'pgood_origin': pgood_origin,
                'mock_response': str(mock_response_set),
            }
        )
        return mock_response_set['pgood']

    logger.info(
        {
            'message': 'Application is not JStarter',
            'process': 'mocking_response',
            'application': application.id,
            'pgood_origin': pgood_origin,
        }
    )
    return pgood_origin

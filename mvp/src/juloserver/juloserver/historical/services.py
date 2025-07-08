import logging
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import FeatureSetting
from juloserver.historical.models import BioSensorHistory
from juloserver.historical.constants import (
    BIO_SENSOR_ELEMENT_CREATE_QUANTITY, FeatureNameConst)

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def pre_capture_ggar_history():
    data = {
        'is_active': False,
        'config': {}
    }
    config = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.BIO_SENSOR_HISTORY, is_active=True)
    if not config:
        return data

    scrape_period = config.parameters.get('scrape_period') if config.parameters else None
    if not scrape_period:
        logger.warning('bio_senor_history_feature_has_no_value|data={}'.format(config.parameters))
        return data

    data.update(
        is_active=True,
        config={'scrape_period': scrape_period}
    )

    return data


def store_bio_sensor_history(bio_sensor_data, application):
    application_id = application.id
    histories = bio_sensor_data['histories']
    total_element_count = len(histories)
    current_element_count = 0
    elements = []
    for i in range(total_element_count):
        if current_element_count < BIO_SENSOR_ELEMENT_CREATE_QUANTITY:
            elements.append(BioSensorHistory(
                application_id=application_id,
                **histories[i]
            ))
            current_element_count += 1
            should_create = False
        else:
            should_create = True

        is_last_element = i == total_element_count-1
        if should_create or is_last_element:
            try:
                BioSensorHistory.objects.bulk_create(elements)
            except Exception as e:
                sentry_client.captureException()
            elements = []
            current_element_count = 0

    return True

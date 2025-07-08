from juloserver.julo.models import FeatureSetting
from juloserver.julo_starter.constants import NotificationSetJStarter
from juloserver.julo.services import get_julo_sentry_client
from juloserver.julolog.julolog import JuloLog
from juloserver.julo_starter.exceptions import JuloStarterException
from juloserver.julo.constants import FeatureNameConst

sentry = get_julo_sentry_client()
logger = JuloLog()


@sentry.capture_exceptions
def get_data_notification_second_check(template_code):
    """
    Get data by MobileFeatureSetting
    To get data title, body, and destination for Notification
    """

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE, is_active=True
    ).last()

    # run validation data
    validate_data_from_db(setting)

    try:
        parameters = setting.parameters
        data = parameters[template_code]

        return data
    except Exception as error:
        logger.error(str(error))
        raise JuloStarterException(str(error))


def validate_data_from_db(setting):

    if not setting:
        error_message = 'Not found feature setting {}'.format(
            FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE
        )
        logger.error(error_message)
        raise JuloStarterException(error_message)

    if not setting.parameters:
        error_message = 'Not found feature setting parameters{}'.format(
            FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE
        )
        logger.error(error_message)
        raise JuloStarterException(error_message)

    if NotificationSetJStarter.KEY_MESSAGE_OK not in setting.parameters:
        error_message = 'Not found feature setting {}'.format(
            NotificationSetJStarter.KEY_MESSAGE_OK
        )
        logger.error(error_message)
        raise JuloStarterException(error_message)

    if NotificationSetJStarter.KEY_MESSAGE_OFFER not in setting.parameters:
        error_message = 'Not found feature setting {}'.format(
            NotificationSetJStarter.KEY_MESSAGE_OFFER
        )
        logger.error(error_message)
        raise JuloStarterException(error_message)

    if NotificationSetJStarter.KEY_MESSAGE_REJECTED not in setting.parameters:
        error_message = 'Not found feature setting {}'.format(
            NotificationSetJStarter.KEY_MESSAGE_REJECTED
        )
        logger.error(error_message)
        raise JuloStarterException(error_message)

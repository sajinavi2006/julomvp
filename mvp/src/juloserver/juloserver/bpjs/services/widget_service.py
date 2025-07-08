from django.conf import settings
from juloserver.bpjs.exceptions import BrickBpjsException
from juloserver.julolog.julolog import JuloLog
from juloserver.bpjs.services.bpjs import Bpjs
from juloserver.julo.models import Application
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.bpjs.constants import BrickSetupClient
from juloserver.julo.clients import get_julo_sentry_client

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def get_widget_url(request, data):

    application_id = data['application_id']
    application = is_verified_data_for_widget(application_id)

    if not application:
        error_message = 'WidgetBrick: Invalid application data'
        logger.error(
            {
                'message': error_message,
                'application_id': application_id,
            }
        )
        raise BrickBpjsException(error_message)

    public_access_token = get_token_public(request, application)
    application_xid = application.application_xid

    if not public_access_token or not application_xid:
        error_message = 'WidgetBrick: public token or application_xid is empty'
        logger.error(
            {
                'message': error_message,
                'application_id': application_id,
            }
        )
        raise BrickBpjsException(error_message)

    widget_url = build_widget_url(
        access_token=public_access_token,
        application_xid=application_xid,
    )

    response = {'widget_url': widget_url}

    return response


def get_token_public(request, application):

    try:
        bpjs = Bpjs()
        bpjs.provider = bpjs.PROVIDER_BRICK
        bpjs.set_request(request)
        call_authenticate = bpjs.with_application(application).authenticate()
        public_access_token = call_authenticate["data"]["access_token"]

        return public_access_token
    except BrickBpjsException as error:
        logger.error(
            {
                'message': str(error),
                'application': application.id if application else None,
            }
        )
        return None


def is_verified_data_for_widget(application_id):

    application = Application.objects.filter(pk=application_id).last()
    if (
        not application.is_julo_one()
        or application.application_status_id != ApplicationStatusCodes.FORM_CREATED
    ):
        logger.error(
            {
                'message': 'WidgetBrick: Not allowed the application',
                'application_id': application_id,
            }
        )
        return None

    return application


def build_widget_url(access_token, application_xid):

    callback_endpoint = BrickSetupClient.JULO_PATH_CALLBACK.format(application_xid)
    fullpath_callback = '{0}{1}'.format(
        settings.BASE_URL,
        callback_endpoint,
    )
    widget_url = '{0}/v1/?accessToken={1}&redirect_url={2}'.format(
        BrickSetupClient.BRICK_WIDGET_BASE_URL,
        access_token,
        fullpath_callback,
    )

    logger.info(
        {
            'message': 'WidgetBrick: success generate the url',
            'widget_url': str(widget_url),
            'application_xid': application_xid,
        }
    )

    return widget_url

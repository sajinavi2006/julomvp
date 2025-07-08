from juloserver.julo_app_report.models import JuloAppReport
from django.db.utils import IntegrityError
from juloserver.julo_app_report.exceptions import JuloAppReportException
from juloserver.julo.clients import get_julo_sentry_client


sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def save_capture(data):
    """
    Save data to ops.julo_app_report
    """

    try:
        JuloAppReport.objects.create(**data)
    except IntegrityError as error:
        raise JuloAppReportException(str(error))

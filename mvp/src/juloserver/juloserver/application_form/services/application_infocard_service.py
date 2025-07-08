from datetime import datetime

from juloserver.julo.models import (
    Application,
    ApplicationInfoCardSession,
    ApplicationStatusCodes,
    Customer,
    FeatureNameConst,
    FeatureSetting,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.application_flow.constants import JuloOne135Related
from juloserver.application_form.constants import InfoCardMessageReapply
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes


logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def get_session_limit_infocard():
    """
    Get data session from Django Admin
    - Feature Setting
    """

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SESSION_LIMIT_FOR_INFOCARD,
    ).last()

    if not setting:
        error_message = 'Not found setting {}'.format(FeatureNameConst.SESSION_LIMIT_FOR_INFOCARD)
        logger.error({'message': error_message})
        raise JuloException(error_message)

    if not setting.is_active:
        error_message = 'Setting parameter {} is not active'.format(
            FeatureNameConst.SESSION_LIMIT_FOR_INFOCARD
        )
        logger.error({'message': error_message})
        raise JuloException(error_message)

    key_target = 'session_limit_daily'
    if setting.parameters and key_target not in setting.parameters:
        error_message = 'Not have value target {}'.format(key_target)
        logger.error({'message': error_message})
        raise JuloException(error_message)

    if not setting.parameters[key_target]:
        error_message = 'Invalid value from parameters {}'.format(key_target)
        logger.error({'message': error_message})
        raise JuloException(error_message)

    return setting.parameters[key_target]


def is_active_session_limit_infocard(application: Application, stream_lined_communication_id=None):

    session_limit = get_session_limit_infocard()
    existing_app = ApplicationInfoCardSession.objects.filter(application=application).last()
    is_active = False
    if not existing_app:
        is_active = True
        session_daily = 1
        logger.info(
            {
                'message': 'create application to application infocard session',
                'session_limit': session_limit,
                'application': application.id,
                'session_daily': session_daily,
            }
        )
        ApplicationInfoCardSession.objects.create(
            application=application,
            session_limit=session_limit,
            session_daily=session_daily,
            stream_lined_communication_id=stream_lined_communication_id,
        )
    else:
        today = datetime.now().date()
        session_daily = existing_app.session_daily
        if session_daily <= existing_app.session_limit:
            is_active = True
            session_daily = existing_app.session_daily + 1

        # check today need to update session
        if existing_app.udate.date() < today:
            logger.info(
                {
                    'message': 'update application to application infocard session',
                    'session_limit': session_limit,
                    'application': application.id,
                    'session_daily': session_daily,
                    'is_active': is_active,
                }
            )
            existing_app.update_safely(
                session_daily=session_daily,
                is_active=is_active,
                stream_lined_communication_id=stream_lined_communication_id,
            )
    return is_active


def message_info_card_for_reapply_duration(customer):

    last_application = Application.objects.filter(
        customer=customer,
        workflow__name=WorkflowConst.JULO_ONE,
        product_line=ProductLineCodes.J1,
    ).last()
    if not last_application:
        return None

    message = InfoCardMessageReapply.MESSAGE_FOR_REAPPLY + ' {}'
    if last_application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
        return message.format(InfoCardMessageReapply.TWO_WEEKS)

    if last_application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:

        application_history = last_application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.APPLICATION_DENIED
        ).last()

        if not application_history:
            logger.warning(
                {'message': 'application_history not found', 'application': last_application.id}
            )
            return None

        reason = application_history.change_reason.lower()
        last_application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.APPLICATION_DENIED
        ).last()

        three_months_reason = Customer.REAPPLY_THREE_MONTHS_REASON
        one_year_reason = Customer.REAPPLY_ONE_YEAR_REASON
        half_a_year_reason = Customer.REAPPLY_HALF_A_YEAR_REASON
        if last_application.is_julo_one():
            one_months_reason = JuloOne135Related.REAPPLY_AFTER_ONE_MONTHS_REASON_J1
            three_months_reason += JuloOne135Related.REAPPLY_AFTER_THREE_MONTHS_REASON_J1
            half_a_year_reason += JuloOne135Related.REAPPLY_AFTER_HALF_A_YEAR_REASON_J1
            one_year_reason += JuloOne135Related.REAPPLY_AFTER_ONE_YEAR_REASON_J1

            if any(word in reason for word in one_months_reason):
                return message.format(InfoCardMessageReapply.ONE_MONTH)

        if any(word in reason for word in half_a_year_reason):
            return message.format(InfoCardMessageReapply.THREE_MONTHS)

        if any(word in reason for word in three_months_reason):
            return message.format(InfoCardMessageReapply.THREE_MONTHS)

        if any(word in reason for word in one_year_reason):
            return message.format(InfoCardMessageReapply.ONE_YEAR)

        return None

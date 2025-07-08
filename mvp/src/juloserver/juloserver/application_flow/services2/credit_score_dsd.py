from django.core.exceptions import MultipleObjectsReturned
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.julo.models import (
    Application,
    CreditScore,
    CustomerAppAction,
    FDCInquiry,
    ApplicationHistory,
    CustomerFieldChange,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import post_anaserver

from juloserver.apiv2.views import EtlStatus
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.fdc.constants import FDCStatus
from juloserver.julolog.julolog import JuloLog
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.apiv3.services.dsd_service import stored_as_application_scrape_action
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.apiv3.exceptions import JuloDeviceScrapedException
from juloserver.julo.exceptions import JuloException
from juloserver.apiv3.constants import DeviceScrapedConst
from juloserver.application_flow.constants import ApplicationDsdMessageConst

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def hit_ana_server_without_dsd(application: Application):

    customer = application.customer
    url = DeviceScrapedConst.ANA_SERVER_DATA_MISSING_ENDPOINT
    json = {'application_id': application.id}

    try:
        incomplete_rescrape_action = CustomerAppAction.objects.get_or_none(
            customer=customer, action='rescrape', is_completed=False
        )
    except MultipleObjectsReturned:
        # checking total duplicate data, delete the duplicate data and leaving 1 data
        incomplete_rescrape_action = CustomerAppAction.objects.filter(
            customer=customer, action='rescrape', is_completed=False
        )
        total_data = len(incomplete_rescrape_action)
        if total_data > 1:
            for incomplete in range(1, total_data):
                incomplete_rescrape_action[incomplete].update_safely(is_completed=True)
        incomplete_rescrape_action = CustomerAppAction.objects.get_or_none(
            customer=customer, action='rescrape', is_completed=False
        )

    if incomplete_rescrape_action:
        incomplete_rescrape_action.mark_as_completed()
        incomplete_rescrape_action.save()

    # Stored the application scrape action
    stored_as_application_scrape_action(customer, application.id, url)
    try:
        response = post_anaserver(
            url=url,
            json=json,
        )
        logger.info(
            {
                'message': '[post_anaserver] Hit ana_server without dsd data',
                'endpoint': url,
                'response_status_code': response.status_code if response else None,
                'json': json,
            }
        )
        return response
    except JuloException as error:
        raise JuloDeviceScrapedException('Failed sent to ana server' + str(error))


def check_fdc_data(application, is_need_to_moved=False) -> (bool, str):

    application_id = application.id

    # Check have FDC data
    is_fdc_found_exists = FDCInquiry.objects.filter(
        application_id=application_id, status__iexact=FDCStatus.FOUND
    ).exists()
    if not is_fdc_found_exists:
        is_success = False
        if application.is_julo_one():
            if is_need_to_moved:
                is_success = process_application_status_change(
                    application_id,
                    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                    change_reason=JuloOneChangeReason.NO_DSD_NO_FDC_FOUND,
                )
                if is_success:
                    customer = application.customer

                    if customer.can_reapply:
                        CustomerFieldChange.objects.create(
                            customer=customer,
                            application=application,
                            field_name='can_reapply',
                            old_value=True,
                            new_value=False,
                        )
                        customer.update_safely(
                            can_reapply=False,
                        )

                    # record change can reapply date
                    can_reapply_date = timezone.localtime(timezone.now()) + relativedelta(days=90)
                    CustomerFieldChange.objects.create(
                        customer=customer,
                        application=application,
                        field_name='can_reapply_date',
                        old_value=customer.can_reapply_date,
                        new_value=can_reapply_date,
                    )
                    customer.update_safely(
                        can_reapply_date=can_reapply_date,
                    )

            logger.info(
                {
                    'message': '[action_process] Moving J1 application to x106 status',
                    'application_id': application_id,
                    'is_success_to_x106': is_success,
                    'is_need_to_moved': is_need_to_moved,
                }
            )

            return False, ApplicationDsdMessageConst.MSG_ALREADY_MOVE_STATUS

        logger.info(
            {
                'message': '[action_process] JTurbo not moving to x106 status',
                'application_id': application_id,
                'is_success_to_x106': is_success,
                'is_need_to_moved': is_need_to_moved,
            }
        )

        return False, ApplicationDsdMessageConst.MSG_ALREADY_MOVE_STATUS

    return True, None


def general_check_for_scoring(application, is_need_to_moved=True) -> (bool, str, str):

    application_id = application.id
    const = ApplicationDsdMessageConst

    application_history = ApplicationHistory.objects.filter(
        status_old=ApplicationStatusCodes.FORM_CREATED,
        status_new=ApplicationStatusCodes.FORM_PARTIAL,
        application=application,
    ).last()

    if (
        application.application_status_id != ApplicationStatusCodes.FORM_PARTIAL
        or not application_history
    ):
        logger.info(
            {
                'message': '[skip_process] application is not x105 status',
                'application_id': application_id,
                'application_status_id': application.application_status_id,
                'workflow_id': application.workflow_id,
            }
        )
        return False, const.FLAG_STATUS_IS_NOT_X105, const.MSG_NOT_IN_X105

    if not application.is_julo_one_or_starter():
        logger.info(
            {
                'message': '[skip_process] application not J1 or JTurbo',
                'application_id': application_id,
                'workflow_id': application.workflow_id,
            }
        )
        return False, const.FLAG_NOT_J1_JTURBO, const.MSG_NOT_J1_JTURBO

    # [Double_check] still have not credit score?
    is_score_exists = CreditScore.objects.filter(application_id=application_id).exists()
    if is_score_exists:
        logger.info(
            {
                'message': '[skip_process] application already have credit score',
                'application_id': application_id,
            }
        )
        return False, const.FLAG_AVAILABLE_CREDIT_SCORE, const.MSG_AVAILABLE_CREDIT_SCORE

    # [Double_check] still have not pgood?
    is_pgood_exists = PdCreditModelResult.objects.filter(application_id=application_id).exists()
    if is_pgood_exists:
        logger.info(
            {
                'message': '[skip_process] application already have pgood',
                'application_id': application_id,
            }
        )
        return False, const.FLAG_AVAILABLE_PGOOD_SCORE, const.MSG_AVAILABLE_PGOOD_SCORE

    etl_status = EtlStatus.objects.filter(application_id=application_id).last()
    if etl_status:
        if "dsd" in str(etl_status.executed_tasks):
            logger.info(
                {
                    'message': '[skip_process] application already have dsd status',
                    'application_id': application_id,
                    'etl_status_id': etl_status.id,
                }
            )
            return False, const.FLAG_AVAILABLE_ETL_STATUS, const.MSG_NEED_RAISE_TO_PRE

    # Check have customer_app_action data?
    now = timezone.localtime(timezone.now())
    customer = application.customer
    app_action = (
        CustomerAppAction.objects.values_list('is_completed', 'cdate')
        .filter(customer_id=customer.id, action='rescrape', cdate__gte=application.cdate)
        .last()
    )

    diff_minutes = (now - application_history.cdate).total_seconds() / 60
    if not app_action:
        if diff_minutes < 30:
            logger.info(
                {
                    'message': '[skip_process] nothing data in customer_app_action',
                    'application_id': application_id,
                    'customer_id': customer.id,
                }
            )
            return False, const.FLAG_WAIT_FEW_MINUTES, const.MSG_TO_WAIT_FEW_MINUTES

        # condition more than 30 minutes submit
        return False, const.FLAG_WAIT_FEW_MINUTES, const.MSG_X105_LESS_THAN_FEW_MINUTES

    # Check data customer_app_action less than 12 hours?
    is_completed, cdate = app_action
    difference_time_in_hours = (now - cdate).total_seconds() / 3600
    if not is_completed and difference_time_in_hours < 12:
        logger.info(
            {
                'message': '[skip_process] customer_app_action less than 12 hours',
                'is_completed': is_completed,
                'app_action': cdate,
                'customer_id': customer.id,
                'application_id': application_id,
                'difference_time_in_hours': difference_time_in_hours,
            }
        )
        return False, const.FLAG_WAIT_FEW_HOURS, const.MSG_TO_WAIT_FEW_HOURS

    # FDC Check
    result, message = check_fdc_data(application, is_need_to_moved)
    if not result:
        return False, const.FLAG_NOT_AVAILABLE_FDC, message

    return True, const.FLAG_SUCCESS_ALL_CHECK, None


def process_check_without_dsd_data(application_id) -> (bool, bool, str):

    logger.info(
        {
            'message': '[executed] process check without dsd data',
            'application_id': application_id,
        }
    )

    application = Application.objects.filter(pk=application_id).last()
    result, flag, message = general_check_for_scoring(application)
    logger.info(
        {
            'message': '[result] general check for scoring {}'.format(message),
            'flag': flag,
            'result': result,
            'application_id': application_id,
        }
    )
    is_call_ana_server = False
    if not result:
        return False, is_call_ana_server, flag

    # to handle condition need to hit ana server
    if result and flag == ApplicationDsdMessageConst.FLAG_SUCCESS_ALL_CHECK:
        # Hit pgood data
        is_call_ana_server = True
        hit_ana_server_without_dsd(application)

    return result, is_call_ana_server, flag

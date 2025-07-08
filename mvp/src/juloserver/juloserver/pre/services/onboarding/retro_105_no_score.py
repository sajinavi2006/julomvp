from juloserver.julo.models import Application, CreditScore, CustomerAppAction, FDCInquiry
from juloserver.apiv2.views import EtlStatus
from juloserver.julo.services import process_application_status_change
from django.core.exceptions import (
    MultipleObjectsReturned,
)
from datetime import datetime
import pytz
from juloserver.apiv3.exceptions import JuloDeviceScrapedException
from juloserver.julo.exceptions import JuloException
from juloserver.julo.utils import post_anaserver

from juloserver.apiv3.services.dsd_service import stored_as_application_scrape_action
from juloserver.pre.services.common import track_agent_retrofix
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.apiv2.models import PdCreditModelResult


def retro_105_no_score(app_id, actor_id):
    track_agent_retrofix('retro_105_no_score', app_id, {}, actor_id)

    # make sure it's eligible to hit ana without dsd
    _check_eligible_to_hit_ana_without_dsd(app_id)

    response = _hit_ana_without_dsd(app_id)
    return response


def _check_eligible_to_hit_ana_without_dsd(app_id):
    app = Application.objects.get(pk=app_id)
    # make sure status is 105
    if app.status != 105:
        raise Exception("this app status is not 105")

    # make sure it's j1/jturbo
    if app.product_line_id not in (1, 2) or app.partner_id:
        raise Exception("this app is not j1/jturbo")

    # make sure score is not generated yet
    is_score_exists = CreditScore.objects.filter(application_id=app_id).exists()
    if is_score_exists:
        raise Exception("score already exists")

    # make sure pgood is not generated
    is_pgood_exists = PdCreditModelResult.objects.filter(application_id=app_id).exists()
    if is_pgood_exists:
        raise Exception(
            "score not exists but pgood is exists. Please raise it to PRE and create escard !"
        )

    # make sure already have completed customer_app_action "rescrape" at least 1
    customer = app.customer
    caa = (
        CustomerAppAction.objects.values_list('is_completed', 'cdate')
        .filter(customer_id=customer.id, action='rescrape', cdate__gte=app.cdate)
        .last()
    )
    if not caa:
        raise Exception(
            "Ask customer to wait 30 minutes since x105 and ask them to logout and login again"
        )
    is_completed, cdate = caa
    if not is_completed and (datetime.now(tz=pytz.utc) - cdate).total_seconds() / 3600 < 12:
        raise Exception(
            "Wait 12 hours, then open this feature again, then submit with this app_id again"
        )

    # make sure dsd is not generated yet
    etl_status = EtlStatus.objects.filter(application_id=app_id).last()
    if etl_status:
        if "dsd" in str(etl_status.executed_tasks):
            raise Exception("Please raise this issue to PRE and create ESCard")

    is_fdc_found_exists = FDCInquiry.objects.filter(
        application_id=app_id, status__in=['found', 'Found']
    ).exists()
    if not is_fdc_found_exists:
        process_application_status_change(
            app_id,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            change_reason=JuloOneChangeReason.NO_DSD_NO_FDC_FOUND,
        )
        raise Exception("We cannot fix this application due to some conditions, so we move to x106")

    return True


def _hit_ana_without_dsd(app_id):
    app = Application.objects.get(pk=app_id)
    customer = app.customer
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
    stored_as_application_scrape_action(customer, app_id, "")
    final_json = {"application_id": app_id}
    # api/amp/v1/device-scraped-data-missing/
    new_endpoint_ana_scraping = "/api/amp/v1/device-scraped-data-missing/"
    try:
        response = post_anaserver(
            new_endpoint_ana_scraping,
            json=final_json,
        )
        return response
    except JuloException as error:
        raise JuloDeviceScrapedException('Failed sent to ana server' + str(error))

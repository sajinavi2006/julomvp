import html
from django.core.exceptions import (
    MultipleObjectsReturned,
)
from rest_framework.status import HTTP_200_OK

from juloserver.apiv3.constants import DeviceScrapedConst
from juloserver.julo.models import (
    Application,
    ApplicationScrapeAction,
    Customer,
    CustomerAppAction,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.exceptions import JuloException
from juloserver.apiv3.exceptions import JuloDeviceScrapedException
from juloserver.julo.utils import post_anaserver
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.ana_api.models import EtlRepeatStatus


logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@sentry.capture_exceptions
def run_and_check_customer_app_action(
    customer: Customer, application_id, url, json_forward, is_ios_device=False
):

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
        logger.info(
            {
                'message': 'Incomplete rescrape action and try to mark as completed',
                'process_name': DeviceScrapedConst.PROCESS_NAME,
                'application_id': application_id,
            },
        )
        incomplete_rescrape_action.mark_as_completed()
        incomplete_rescrape_action.save()

    # Stored the application scrape action
    stored_as_application_scrape_action(customer, application_id, url)

    # handle json forward if no have wifi_details
    json_forward = binding_wifi_data(json_forward, application_id)
    final_json = sanitize_payload_for_dsd(json_forward)

    # We change to post_anaserver from redirect_post_to_anaserver to get retry some status codes
    # And new method (json) to ana
    ana_endpoint = (
        DeviceScrapedConst.ANA_SERVER_ENDPOINT_FOR_IOS
        if is_ios_device
        else DeviceScrapedConst.ANA_SERVER_ENDPOINT
    )
    try:
        response = post_anaserver(
            ana_endpoint,
            json=final_json,
        )
        return response
    except JuloException as error:
        logger.error(
            {
                'message': str(error),
                'process_name': DeviceScrapedConst.PROCESS_NAME,
                'application_id': application_id,
            }
        )
        raise JuloDeviceScrapedException('Failed sent to ana server')


def stored_as_application_scrape_action(customer, application_id, url, scrape_type='dsd'):

    application = customer.application_set.get(pk=application_id)
    logger.info(
        {
            'message': 'Stored the application scrape action',
            'process_name': DeviceScrapedConst.PROCESS_NAME,
            'application_id': application,
        }
    )

    ApplicationScrapeAction.objects.create(
        application_id=application.id, url=url, scrape_type=scrape_type
    )

    return True


def get_structure_initiate_dsd(application_id):

    structure_initiate = {
        "status": 'initiated',
        "application_id": application_id,
        "data_type": 'dsd',
        "s3_url_report": None,
        "udate": None,
        "dsd_id": 0,
        "cdate": None,
        "s3_url_raw": None,
        "temp_dir": None,
        "error": None,
        "customer_id": None,
        "id": 1,
    }

    return structure_initiate


def binding_wifi_data(json_forward, application_id):
    """
    Add manually if request no available wifi_details
    """

    wifi_details = json_forward.get(DeviceScrapedConst.KEY_WIFI_DETAILS, None)
    if not wifi_details:
        logger.info(
            {
                'message': 'process embed the wifi_details',
                'process': DeviceScrapedConst.PROCESS_NAME,
                'application': application_id,
            }
        )
        embed_wifi_details = {DeviceScrapedConst.KEY_WIFI_DETAILS: []}
        json_forward.update(embed_wifi_details)

    return json_forward


@sentry.capture_exceptions
def sanitize_payload_for_dsd(data):

    if not data:
        return False

    try:
        for key in DeviceScrapedConst.KEYS_MAP_PARAM:
            is_data_list_type = False
            if key in (
                DeviceScrapedConst.KEY_APP_DETAILS,
                DeviceScrapedConst.KEY_WIFI_DETAILS,
            ):
                is_data_list_type = True

            # check and convert for all value
            check_and_convert(data.get(key), is_data_list_type=is_data_list_type)

        return data
    except Exception as error:
        logger.error(
            {
                'message': 'SanitizeDSDV3: {}'.format(str(error)),
                'data': str(data),
            }
        )
        raise JuloDeviceScrapedException(str(error))


def check_and_convert(data, is_data_list_type=False):

    if not data:
        return data

    if isinstance(data, int) or isinstance(data, str):
        return do_escape_for_html(data)

    for item in data:
        if is_data_list_type:
            temporary_dict = {}
            for item_child in item:
                temporary_dict.update({item_child: do_escape_for_html(item[item_child])})

            if temporary_dict:
                item.update(temporary_dict)
        else:
            data.update({item: do_escape_for_html(data[item])})

    return data


def do_escape_for_html(value):

    if not isinstance(value, str):
        return value

    return html.escape(value, False)


def proceed_request_clcs_dsd(request_body, customer, application_id, url):

    application = Application.objects.filter(pk=application_id).last()
    if not application:
        logger.error(
            {
                'message': '[DSD-CLCS] Application is not found',
                'application_id': application_id,
            }
        )
        return False, None

    customer_query = application.customer
    if customer.id != customer_query.id:
        logger.error(
            {
                'message': '[DSD-CLCS] Application is not valid',
                'application_id': application_id,
                'customer_id': customer.id,
                'customer_id_query': customer_query.id,
            }
        )
        return False, None

    # Stored data application scrape action
    stored_as_application_scrape_action(
        customer=customer,
        application_id=application_id,
        url=url,
        scrape_type='dsd-clcs',
    )

    etl_repeat_status = EtlRepeatStatus.objects.filter(application_id=application_id).last()
    etl_repeat_number = etl_repeat_status.repeat_number if etl_repeat_status else 0

    # Prepare forward body
    data = {
        'application_id': application_id,
        'customer_id': customer.id,
        'repeat_number': int(etl_repeat_number) + 1,
    }
    request_body.update(data)

    # Handle json forward if no have wifi_details
    request_body = binding_wifi_data(request_body, application_id)
    request_body = binding_phone_details_data(request_body, application_id)
    json = sanitize_payload_for_dsd(request_body)

    try:
        response = post_anaserver(
            DeviceScrapedConst.ANA_SERVER_ENDPOINT_CLCS,
            json=json,
        )

        if response.status_code != HTTP_200_OK:
            logger.error(
                {
                    'message': '[DSD-CLCS] Failed response from anaserver',
                    'application_id': application_id,
                    'response': str(response.content),
                }
            )

        return True, response
    except JuloException as error:
        logger.error(
            {
                'message': str(error),
                'process_name': DeviceScrapedConst.PROCESS_NAME_CLCS,
                'application_id': application_id,
            }
        )
        raise JuloDeviceScrapedException('Failed sent the data')


def binding_phone_details_data(json_forward, application_id):
    """
    Add manually if request no available wifi_details
    """

    phone_details = json_forward.get(DeviceScrapedConst.KEY_PHONE_DETAILS, None)
    if not phone_details:
        logger.info(
            {
                'message': 'process embed the phone_details',
                'process': DeviceScrapedConst.PROCESS_NAME_CLCS,
                'application': application_id,
            }
        )
        embed_data_request = {DeviceScrapedConst.KEY_PHONE_DETAILS: {}}
        json_forward.update(embed_data_request)

    return json_forward

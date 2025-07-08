from datetime import datetime, timedelta, date
from typing import Union

import pytz
from django.db import connection

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.apiv2.models import GAAppActivity
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.customer_module.constants import AppActionFlagConst
from juloserver.fraud_portal.models.models import ConnectionAndDevice
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    DeviceIpHistory,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julocore.cache_client import get_redis_cache
from juloserver.pii_vault.constants import PiiSource
from dateutil.relativedelta import relativedelta

cache = get_redis_cache()
CACHE_DURATION = 60 * 60  # 1 hour

jakarta_tz = pytz.timezone('Asia/Jakarta')


def get_connection_and_device(application_ids: list) -> list:
    connection_and_device_list = []

    for application_id in application_ids:
        application = Application.objects.get(id=application_id)

        uninstalled = get_uninstalled(application)
        application_risky_flag = get_application_risky_flag(application)

        today = date.today()
        six_months_ago_first_day = (today - relativedelta(months=6)).replace(day=1)

        overlap_connection_to_wifi = get_overlap_connection_to_wifi(
            application, today.isoformat(), six_months_ago_first_day.isoformat()
        )
        overlap_installed_apps = get_overlap_installed_apps(
            application, today.isoformat(), six_months_ago_first_day.isoformat()
        )

        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application], ['fullname']
        )[0]
        connection_and_device = ConnectionAndDevice(
            application_id=application.id,
            application_fullname=detokenized_application.fullname,
            uninstalled=uninstalled,
            application_risky_flag=application_risky_flag,
            overlap_connection_to_wifi=overlap_connection_to_wifi,
            overlap_installed_apps=overlap_installed_apps
        )
        connection_and_device_list.append(connection_and_device.to_dict())

    return connection_and_device_list


def get_uninstalled(application: Application) -> str:
    """
    Determines if app has been uninstalled or not by customer.

    Args:
        application (Application): Application object for retrieve customer_id.

    Returns:
        str: A message indicating whether the application has been uninstalled or not.
    """
    customer_id = application.customer.id
    latest_ga_app_activity = (
        GAAppActivity.objects.filter(customer_id=customer_id).order_by('event_date').last()
    )
    if not latest_ga_app_activity:
        return None
    event_name = latest_ga_app_activity.event_name
    result = "No"
    if event_name not in (
        AppActionFlagConst.INSTALLED_CRITERIA_EVENT_NAMES,
        AppActionFlagConst.INSTALLED,
    ):
        if event_name in (
            AppActionFlagConst.NOT_INSTALLED,
            AppActionFlagConst.NOT_INSTALLED_CRITERIA_EVENT_NAME,
            AppActionFlagConst.UNINSTALLED_AND_UNIDENTIFIED_APP,
        ):
            result = "Yes ({0})".format(
                latest_ga_app_activity.event_date.astimezone(jakarta_tz).strftime(
                    '%d-%m-%Y %H:%M:%S'
                )
            )
        else:
            result = "Unidentified"
    return result


def get_application_risky_flag(application: Application) -> dict:
    """
    Retrieves a dictionary of risk flags for the given application based on various risk checks.

    Args:
        application (Application): The application for which to retrieve risk flags.

    Returns:
        dict: A dictionary containing various risk flags. If no risk check data is found for the
        application, an empty dictionary is returned.
    """
    app_risky_check = ApplicationRiskyCheck.objects.get_or_none(application_id=application.id)
    if not app_risky_check:
        return {}
    application_risky_flag = {
        "is_rooted_device": app_risky_check.is_rooted_device,
        "is_address_device": app_risky_check.is_address_suspicious,
        "is_special_event": app_risky_check.is_special_event,
        "is_bpjs_name_suspicious": app_risky_check.is_bpjs_name_suspicious,
        "is_bpjs_nik_suspicious": app_risky_check.is_bpjs_nik_suspicious,
        "is_suspicious_camera_app": app_risky_check.is_sus_camera_app,
        "is_sus_ektp_generator_app": app_risky_check.is_sus_ektp_generator_app,
        "is_vpn_detected": app_risky_check.is_vpn_detected,
        "is_fh_detected": app_risky_check.is_fh_detected,
        "is_similar_face_suspicious": app_risky_check.is_similar_face_suspicious,
        "is_sus_app_detected": app_risky_check.is_sus_app_detected,
        "is_dukcapil_not_match": app_risky_check.is_dukcapil_not_match,
        "is_mycroft_holdout": app_risky_check.is_mycroft_holdout
    }
    return application_risky_flag


def get_overlap_connection_to_wifi(
    application: Application, start_date: str, end_date: str
) -> list:
    """
    Retrieves a list of Wi-Fi connections that have overlapping usage with other customers.

    Args:
        application (Application): Application object for retrieve application_id,
        customer_id, and device_id.

    Returns:
        list: A list of Wi-Fi connections that are used by other customers.
    """
    overlap_connection_list = []
    application_id = application.id
    customer_id = application.customer.id
    device_app = application.device
    if not device_app:
        return overlap_connection_list

    device_id = device_app.id

    CACHE_KEY = 'compare_pages_overlap_connections::{0}_{1}_{2}'.format(
        application_id,
        customer_id,
        device_id,
    )
    cache_data = cache.get(CACHE_KEY)
    if cache_data:
        return cache_data

    # Query for get data wifi customer
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                wifi_ssid,
                MAX(cdate) AS max_cdate
            FROM
                ana.sd_device_wifi_detail
            WHERE
                application_id = %s
                AND customer_id = %s
                AND device_id = %s
                AND cdate <= %s
                AND cdate >= %s
            GROUP BY
                wifi_ssid
            """,
            [application_id, customer_id, device_id, start_date, end_date],
        )
        results = cursor.fetchall()

    if not results:
        return overlap_connection_list

    ssid_cdate_dict = {}
    ssid_list = []
    for result in results:
        wifi_ssid, max_cdate = result
        ssid_cdate_dict[wifi_ssid] = max_cdate
        ssid_list.append(wifi_ssid)

    ssid_placeholder = ', '.join(['%s'] * len(ssid_list))

    # Query for get number of overlap from wifi customer
    with connection.cursor() as cursor:
        query = """
            SELECT
                wifi_ssid,
                COUNT(*) AS number_of_row
            FROM
            ana.sd_device_wifi_detail dwd
            WHERE
                dwd.wifi_ssid IN ({0})
                AND customer_id != %s
                AND cdate <= %s
                AND cdate >= %s
            GROUP BY
                wifi_ssid
            ORDER BY
                number_of_row DESC;""".format(
            ssid_placeholder
        )
        params = ssid_list + [customer_id] + [start_date] + [end_date]
        cursor.execute(query, params)
        results = cursor.fetchall()

    if not results:
        return overlap_connection_list

    for result in results:
        wifi_ssid, number_of_row = result
        wifi_cdate = ssid_cdate_dict[wifi_ssid]
        ip_address = get_wifi_ip_address(device_id, customer_id, wifi_cdate)
        overlap_connection = {
            "ip_address": ip_address,
            "ssid": wifi_ssid,
            "number_of_overlap": number_of_row
        }
        overlap_connection_list.append(overlap_connection)

    cache.set(CACHE_KEY, overlap_connection_list, CACHE_DURATION)
    return overlap_connection_list


def get_wifi_ip_address(device_id: int, customer_id: int, wifi_cdate: datetime) -> str:
    """
    Retrieves the most recent IP address for a specific device and customer based on the
    provided creation date.

    Args:
        device_id (int): The ID of the device whose IP address is to be retrieved.
        customer_id (int): The ID of the customer associated with the device.
        wifi_cdate (datetime): The creation date for filtering the IP address history.

    Returns:
        str: IP address if found, otherwise None.
    """
    start_datetime = wifi_cdate.replace(second=0, microsecond=0)
    end_datetime = start_datetime + timedelta(minutes=1)
    device_ip = DeviceIpHistory.objects.filter(
        device_id=device_id,
        customer_id=customer_id,
        cdate__gte=start_datetime,
        cdate__lt=end_datetime
    ).last()
    if not device_ip:
        return None
    return device_ip.ip_address


def get_overlap_installed_apps(application: Application, start_date: str, end_date: str) -> list:
    """
    Retrieves a list of apps that have overlapping installations with other customer.

    Args:
        application (Application): Application object for retrieve customer_id.

    Returns:
        list: A list of apps that are installed by other customers.
    """
    overlap_installed_apps_list = []

    customer_id = application.customer.id

    start_time, end_time = get_range_time_installed_app(application)
    if not start_time:
        return overlap_installed_apps_list

    CACHE_KEY = 'compare_pages_overlap_apps::{0}'.format(customer_id)
    cache_data = cache.get(CACHE_KEY)
    if cache_data:
        return cache_data

    # Query for get installed apps customer
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT
                app_name,
                app_package_name
            FROM
                ana.sd_device_app
            WHERE
                customer_id= %s
                AND install_time_milis>= %s
                AND install_time_milis<= %s
                AND cdate <= %s
                AND cdate >= %s
            """,
            [customer_id, start_time, end_time, start_date, end_date],
        )
        results = cursor.fetchall()
    if not results:
        return overlap_installed_apps_list
    app_names = []
    app_package_names = []
    for result in results:
        app_name, app_package_name = result
        app_names.append(app_name)
        app_package_names.append(app_package_name)

    name_placeholder = ', '.join(['%s'] * len(app_names))
    package_placeholder = ', '.join(['%s'] * len(app_package_names))

    # Query for get number of overlap installed apps
    with connection.cursor() as cursor:
        query = """
            SELECT
                app_name,
                app_package_name,
                COUNT(*) AS number_of_row
            FROM
            ana.sd_device_app da
            WHERE
                da.app_package_name IN ({0})
                AND da.app_name IN ({1})
                AND customer_id != %s
                AND cdate <= %s
                AND cdate >= %s
            GROUP BY
                app_name, app_package_name
            ORDER BY
                number_of_row DESC;""".format(
            package_placeholder, name_placeholder
        )
        params = app_package_names + app_names + [customer_id] + [start_date] + [end_date]
        cursor.execute(query, params)
        results = cursor.fetchall()
    if not results:
        return overlap_installed_apps_list

    for result in results:
        app_name, app_package_name, number_of_overlap = result
        overlap_app = {
            "app_name": app_name,
            "app_package_name": app_package_name,
            "number_of_overlap": number_of_overlap
        }
        overlap_installed_apps_list.append(overlap_app)
    cache.set(CACHE_KEY, overlap_installed_apps_list, CACHE_DURATION)
    return overlap_installed_apps_list


def get_range_time_installed_app(application: Application) -> Union[int, int]:
    """
    Retrieves the range of time (in milliseconds) for which an application with
    status FORM_PARTIAL (x105).

    Args:
        application (Application): Application object to retrieve the application history.

    Returns:
        tuple: A tuple containing the start time and end time in milliseconds since the epoch.
        If no history is found, returns (False, False).
    """
    app_history_105 = ApplicationHistory.objects.filter(
        application_id=application.id,
        status_new=ApplicationStatusCodes.FORM_PARTIAL
    ).last()
    if not app_history_105:
        return False, False
    app_history_105_cdate = app_history_105.cdate
    start_time = int(app_history_105_cdate.timestamp() * 1000)
    time_after_24_hours = app_history_105_cdate + timedelta(hours=24)
    end_time = int(time_after_24_hours.timestamp() * 1000)
    return start_time, end_time

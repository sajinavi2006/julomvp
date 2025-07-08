from juloserver.account.models import Account
from juloserver.julo.models import Customer, Application, AppVersion
from django.contrib.auth.models import User
from juloserver.application_flow.models import ApplicationPathTag
from juloserver.pre.services.common import track_agent_retrofix
import json


def _find_cust(identifier):
    app = None
    try:
        if isinstance(identifier, str):
            app = Application.objects.filter(email=identifier).last()
            if app:
                return app.customer
            app = Application.objects.filter(mobile_phone_1=identifier).last()
            if app:
                return app.customer
            app = Application.objects.filter(ktp=identifier).last()
            if app:
                return app.customer
        else:
            app = Application.objects.get_or_none(pk=identifier)
            if app:
                return app.customer
            cust = Customer.objects.get_or_none(pk=identifier)
            if cust:
                return cust
            acc = Account.objects.get_or_none(pk=identifier)
            if acc:
                return Application.objects.filter(account_id=acc.id).last().customer
            print("identifier tidak valid")
            return None
    except Application.MultipleObjectsReturned:
        print("banyak application yang menggunakan email/phone ini")
        return None
    return app


def _request_api(view=None, user_id=None, body=None, header={}, method="POST"):
    from django.http import HttpRequest

    request = HttpRequest()
    request.method = method
    user = User.objects.get(pk=user_id)
    request.user = user
    if method == "GET":
        for key, value in header.items():
            header_key = f'HTTP_{key.upper().replace("-", "_")}'
            request.META[header_key] = value
        response = view.get(request)
    elif method == 'POST':

        header['Content-Type'] = 'application/json'
        for key, value in header.items():
            header_key = f'HTTP_{key.upper().replace("-", "_")}'
            request.META[header_key] = value

        if body:
            request.body = json.dumps(body).encode('utf-8')
        response = view.post(request)

    return response


def _do_simulate_api(identifier, view, body, header, method):
    cust = _find_cust(identifier)
    auth_user_id = None
    if cust is not None:
        auth_user_id = cust.user_id
    response = _request_api(
        view=view, user_id=auth_user_id, body=body, header=header, method=method
    )
    result = {
        "status_code": response.status_code,
        "data": response.data,
    }
    return result


def _simulate_api(trigger_app):

    identifier = trigger_app["identifier"]
    view = trigger_app["view"]
    body = trigger_app["body"]
    header = trigger_app["header"]
    method = trigger_app["method"]
    # -- fix --
    response = _do_simulate_api(identifier, view, body, header, method)
    return response


def _get_credit_info_information(cust_id):
    # show credit-info
    from juloserver.customer_module.views import views_api_v3

    view = views_api_v3.CreditInfoView()
    req_data = {
        "identifier": cust_id,
        "view": view,
        'method': 'GET',
        "body": {},
        'header': {},
    }
    response = _simulate_api(req_data)

    if response['status_code'] != 200:
        raise Exception(
            "credit info status_code is not 200 ! but "
            + str(response['status_code'])
            + ". Please screenshot this and raise to PRE"
        )

    if not response['data']:
        raise Exception(
            "credit info response data is null. Please screenshot this and raise to PRE"
        )

    return response['data']


def _get_neo_banner_information(cust_id):
    app_version_obj = AppVersion.objects.filter(status='latest').last()
    last_app_version = app_version_obj.app_version

    # show neo banner
    from juloserver.streamlined_communication import views

    view = views.NeoBannerAndroidAPI()

    req_data = {
        "identifier": cust_id,
        "view": view,
        'method': 'GET',
        "body": {},
        'header': {"X_APP_VERSION": last_app_version},
    }
    response = _simulate_api(req_data)

    if response['status_code'] != 200:
        raise Exception(
            "neo banner status_code is not 200 ! but "
            + str(response['status_code'])
            + ". Please screenshot this and raise to PRE"
        )

    if not response['data']:
        raise Exception("neo banner response data is null. Please screenshot this and raise to PRE")

    return response


def _get_info_card(cust_id):
    # get info card
    from juloserver.streamlined_communication import views

    view = views.InfoCardAndroidAPI()
    req_data = {
        "identifier": cust_id,
        "view": view,
        'method': 'GET',
        "body": {},
        'header': {},
    }

    response = _simulate_api(req_data)

    if response['status_code'] != 200:
        raise Exception(
            "neo banner status_code is not 200 ! but "
            + str(response['status_code'])
            + ". Please screenshot this and raise to PRE"
        )

    if not response['data']:
        raise Exception("neo banner response data is null. Please screenshot this and raise to PRE")

    return response


def _get_path_tag(cust_id):
    last_app = Application.objects.filter(customer_id=cust_id).last()
    app_tags = ApplicationPathTag.objects.filter(application_id=last_app.id)
    tag_str = ""
    for app_tag in app_tags:
        temp_status = app_tag.application_path_tag_status
        temp_tag_str = (
            temp_status.application_tag
            + ":"
            + str(temp_status.status)
            + " ("
            + str(temp_status.id)
            + ")"
        )
        tag_str += temp_tag_str + ", "
    return tag_str


def _remove_newlines_from_dict(d):
    for key, value in d.items():
        if isinstance(value, dict):
            # Recursive call for nested dictionary
            _remove_newlines_from_dict(value)
        elif isinstance(value, list):
            # Recursive call for each dictionary in a list
            for item in value:
                if isinstance(item, dict):
                    _remove_newlines_from_dict(item)
        elif isinstance(value, str):
            # Replace newlines in string values
            d[key] = value.replace('\n', ' ')
    return d


def get_customer_information(cust_id, actor_id):
    last_app = Application.objects.filter(customer_id=cust_id).last()
    if last_app:
        track_agent_retrofix('get_customer_information', last_app.id, {}, actor_id)

    credit_info_json = _get_credit_info_information(cust_id)
    neo_banner_json = _get_neo_banner_information(cust_id)
    info_card_json = _get_info_card(cust_id)
    path_tags = _get_path_tag(cust_id)

    result = {
        "customer_id": cust_id,
        "credit_info": credit_info_json,
        "neo_banner": neo_banner_json,
        "info_card": info_card_json,
        "path_tags": path_tags,
    }

    if last_app:
        result['last_application_id'] = last_app.id

    cleaned_result = _remove_newlines_from_dict(result)

    return cleaned_result

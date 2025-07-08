from juloserver.julolog.julolog import JuloLog
from django.shortcuts import render
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.pre.serializers import (
    ChangePhoneInX137Serializer,
    SendLinkResetPinSerializer,
    ChangeApplicationDataSerializer,
    ForceChangeApplicationStatusSerializer,
    DeleteMtlCtlStlNullProductCustomerSerializer,
    Fix105NoCreditScoreSerializer,
    ShowCustomerInformationSerializer,
)
from juloserver.pre.services.onboarding.change_application_data import (
    conditional_change_application_data,
)
from juloserver.pre.services.onboarding.change_force import change_force
from juloserver.pre.services.onboarding.send_link_reset_pin import (
    send_link_reset_pin_manual,
)
from juloserver.julo.models import (
    Application,
    Customer,
)
from juloserver.julo.utils import format_valid_e164_indo_phone_number
from juloserver.pre.services.onboarding.delete_old_customer_with_new_logic import (
    new_delete_customer_based_on_api_logic,
)

from juloserver.pre.services.onboarding.retro_105_no_score import retro_105_no_score
from juloserver.pre.services.onboarding.show_customer_information import (
    get_customer_information,
)
import json


logger = JuloLog()


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.BO_GENERAL_CS])
def change_phone_in_x137(request):
    if request.POST:
        return change_phone_in_x137_post(request)

    template = 'pre/change_phone_in_x137.html'

    return render(request, template)


def change_phone_in_x137_post(request):
    template = 'pre/change_phone_in_x137.html'
    try:
        # get and validate request
        serializer = ChangePhoneInX137Serializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        app_id = data['application_id']
        phone = data['phone']
        app = Application.objects.get_or_none(pk=app_id)
        if app is None:
            context = {'type_message': 'failed', 'message': "app id is not found"}
            return render(request, template, context)

        last_app = Application.objects.filter(customer_id=app.customer_id).last()

        if app.status != 137:
            context = {'type_message': 'failed', 'message': "status is not in x137"}
            return render(request, template, context)

        if app.id != last_app.id:
            context = {
                'type_message': 'failed',
                'message': "app id is not the last app id of this customer (last app id is : "
                + str(last_app.id)
                + ")",
            }
            return render(request, template, context)

        format_valid_e164_indo_phone_number(phone)

        # run action
        params = [{"app_id": app_id, "data_changes": {"mobile_phone_1": phone}}]
        result = conditional_change_application_data(params, actor_id=request.user.id)

        # return response as html
        context = {'type_message': 'success', 'message': str(result)}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "change_phone_in_x137_post", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.BO_GENERAL_CS])
def send_link_reset_pin(request):
    if request.POST:
        return send_link_reset_pin_post(request)

    template = 'pre/send_link_reset_pin.html'

    return render(request, template)


def send_link_reset_pin_post(request):
    template = 'pre/send_link_reset_pin.html'
    try:
        # get and validate request
        serializer = SendLinkResetPinSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        nik = data['nik']

        cust = Customer.objects.filter(nik=nik).last()
        if cust is None:
            context = {'type_message': 'failed', 'message': "NIK is not found"}
            return render(request, template, context)

        # run action
        result = send_link_reset_pin_manual(cust.id, actor_id=request.user.id)

        # return response as html
        context = {'type_message': 'success', 'message': str(result)}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "send_link_reset_pin_post", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.AGENT_RETROFIX_HIGH_RISK_USER])
def change_application_data(request):
    if request.POST:
        return change_application_data_post(request)

    template = 'pre/change_application_data.html'

    return render(request, template)


def change_application_data_post(request):
    template = 'pre/change_application_data.html'
    try:
        # get and validate request
        serializer = ChangeApplicationDataSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        app_id = data['application_id']
        field_name = data['field_name']
        new_value = data['new_value']
        if new_value == "None":
            new_value = None

        app = Application.objects.get_or_none(pk=app_id)
        if app is None:
            context = {'type_message': 'failed', 'message': "app id is not found"}
            return render(request, template, context)

        # run action
        app_data = {"app_id": app_id, "data_changes": {}}
        app_data['data_changes'][field_name] = new_value
        params = [app_data]
        result = conditional_change_application_data(params, actor_id=request.user.id)

        # return response as html
        context = {'type_message': 'success', 'message': str(result)}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "change_application_data_post", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.AGENT_RETROFIX_HIGH_RISK_USER])
def force_change_application_status(request):
    if request.POST:
        return force_change_application_status_post(request)

    template = 'pre/force_change_application_status.html'

    return render(request, template)


def force_change_application_status_post(request):
    template = 'pre/force_change_application_status.html'
    try:
        # get and validate request
        serializer = ForceChangeApplicationStatusSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        app_id = data['application_id']
        status_new = data['status_new']
        reason = data['reason']
        app = Application.objects.get_or_none(pk=app_id)
        if app is None:
            context = {'type_message': 'failed', 'message': "app id is not found"}
            return render(request, template, context)

        # run action
        status_data = {"status": {"value": status_new, "reason": reason}}
        result = change_force(app_id, status_data, 1, actor_id=request.user.id)

        # return response as html
        context = {'type_message': 'success', 'message': str(result)}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "change_application_data_post", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.AGENT_RETROFIX_HIGH_RISK_USER])
def delete_mtl_ctl_stl_null_product_customer(request):
    if request.POST:
        return delete_mtl_ctl_stl_null_product_customer_post(request)

    template = 'pre/delete_mtl_ctl_stl_null_product_customer.html'

    return render(request, template)


def delete_mtl_ctl_stl_null_product_customer_post(request):
    template = 'pre/delete_mtl_ctl_stl_null_product_customer.html'
    try:
        # get and validate request
        serializer = DeleteMtlCtlStlNullProductCustomerSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cust_id = data['customer_id']
        cust = Customer.objects.get_or_none(pk=cust_id)
        if cust is None:
            context = {'type_message': 'failed', 'message': "cust id is not found"}
            return render(request, template, context)

        # run action
        result = new_delete_customer_based_on_api_logic(
            [{"cust_id": cust_id, "reason": "user requested delete"}], actor_id=request.user.id
        )

        # return response as html
        context = {'type_message': 'success', 'message': str(result)}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "delete_mtl_ctl_stl_null_product_customer", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.AGENT_RETROFIX_HIGH_RISK_USER])
def fix_105_no_credit_score(request):
    if request.POST:
        return fix_105_no_credit_score_post(request)

    template = 'pre/fix_105_no_credit_score.html'

    return render(request, template)


def fix_105_no_credit_score_post(request):
    template = 'pre/fix_105_no_credit_score.html'
    try:
        # get and validate request
        serializer = Fix105NoCreditScoreSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        app_id = data['application_id']
        app = Application.objects.get_or_none(pk=app_id)
        if app is None:
            context = {'type_message': 'failed', 'message': "app id is not found"}
            return render(request, template, context)

        # run action
        result = retro_105_no_score(app_id, actor_id=request.user.id)

        # return response as html
        context = {'type_message': 'success', 'message': str(result)}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "fix_105_no_credit_score", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.AGENT_RETROFIX_HIGH_RISK_USER])
def show_customer_information(request):
    if request.POST:
        return show_customer_information_post(request)

    template = 'pre/show_customer_information.html'

    return render(request, template)


def show_customer_information_post(request):
    template = 'pre/show_customer_information.html'
    try:
        # get and validate request
        serializer = ShowCustomerInformationSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cust_id = data['customer_id']
        cust = Customer.objects.get_or_none(pk=cust_id)
        if cust is None:
            context = {'type_message': 'failed', 'message': "cust id is not found"}
            return render(request, template, context)

        # run action
        result = get_customer_information(cust_id, actor_id=request.user.id)
        json_result = json.dumps(result)

        # return response as html
        context = {'type_message': 'success', 'message': json_result}

        return render(request, template, context)
    except KeyError as e:
        logger.info({"function": "show_customer_information", "error": str(e)})
        context = {'type_message': 'failed', 'message': "wrong input ! please check your input !"}
        return render(request, template, context)
    except Exception as e:
        context = {'type_message': 'failed', 'message': str.join(" ", str(e).splitlines())}
        return render(request, template, context)

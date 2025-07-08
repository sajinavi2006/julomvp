import json
from builtins import str

from django.http import HttpResponse, JsonResponse
from django.http.response import HttpResponseRedirect
from object import julo_login_required
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView

from juloserver.bpjs.constants import TongdunCodes
from juloserver.bpjs.models import BpjsTask, BpjsTaskEvent
from juloserver.bpjs.services import (
    create_or_update_bpjs_task_from_tongdun_callback,
    generate_bpjs_pdf,
)
from juloserver.bpjs.services.bpjs import Bpjs
from juloserver.bpjs.tasks import async_get_bpjs_data

# set decorator for login required
from juloserver.cfs.services.core_services import process_post_connect_bpjs_success
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Application, Customer
from juloserver.standardized_api_response.utils import general_error_response

# Create your views here.


class LoginUrlView(APIView):
    """
    Login url BPJS previous process with Tongdun Provider (Deprecated)
    And currently process has changed with Brick Provider.
    Refer to (for fixing the Old Apps Version):
    https://juloprojects.atlassian.net/browse/RUS1-871
    """

    permission_classes = []
    authentication_classes = []

    def get(self, request, customer_id, application_id, app_type):

        try:
            customer = Customer.objects.values("id").filter(pk=customer_id).last()
            if customer["id"] is None:
                error_msg = "Invalid customer_id: {}".format(customer_id)
                return general_error_response(error_msg)

            application = Application.objects.get_or_none(pk=application_id)
            if not application:
                error_msg = "Invalid application_id: {}".format(application_id)
                return general_error_response(error_msg)

            bpjs = Bpjs()
            bpjs.provider = bpjs.PROVIDER_BRICK
            bpjs.set_request(request)
            authenticate = bpjs.with_application(application).authenticate()
            bpjs.public_access_token = authenticate["data"]["access_token"]
            login_url = bpjs.get_full_widget_url()

            return HttpResponseRedirect(login_url)

        except Exception as error:
            error_message = str(error)
            return general_error_response(error_message)


class TongdunTaskCallbackView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        passback_params = request.POST.get("passback_params")
        if not passback_params:
            error_msg = "passback_params is empty"
            return Response(status=HTTP_200_OK, data={"message": error_msg, "code": 1})
        notify_data = request.POST.get("notify_data")
        if not notify_data:
            error_msg = "notify_data is empty"
            return Response(status=HTTP_200_OK, data={"message": error_msg, "code": 1})

        customer_id, application_id, data_source, page = passback_params.split("_")
        data = json.loads(notify_data)
        code = data["code"]
        bpjs_task = None
        if code not in [
            TongdunCodes.TONGDUN_TASK_SUBMIT_SUCCESS_CODE,
            TongdunCodes.TONGDUN_TASK_SUCCESS_CODE,
        ]:
            error_msg = "wrong code received"

            bpjs_task = BpjsTask.objects.filter(task_id=data["task_id"]).last()

            if bpjs_task:
                BpjsTaskEvent.objects.create(
                    status_code=data["code"],
                    message=data["message"],
                    bpjs_task=bpjs_task,
                )

                return Response(status=HTTP_200_OK, data={"message": error_msg, "code": code})

            error_msg = "Can not find bpjs task_id for task id : {} in bpjs_task table".format(
                data["task_id"]
            )

            return Response(status=HTTP_200_OK, data={"message": error_msg, "code": code})

        task_id = data["task_id"]
        if not task_id:
            error_msg = "No task_id received"
            return Response(status=HTTP_200_OK, data={"message": error_msg, "code": code})

        create_or_update_bpjs_task_from_tongdun_callback(
            data, customer_id, application_id, data_source
        )
        if code == TongdunCodes.TONGDUN_TASK_SUCCESS_CODE:
            process_post_connect_bpjs_success(application_id, customer_id, bpjs_task=bpjs_task)
            async_get_bpjs_data.apply_async((task_id, customer_id, application_id), countdown=10)

        return Response(status=HTTP_200_OK, data={"message": "success", "code": 0})


@julo_login_required
def bpjs_pdf_view(request, application_id):
    try:
        pdf = generate_bpjs_pdf(application_id)
        response = HttpResponse(pdf, content_type="application/pdf")
        filename = "BPJS_report_{}.pdf".format(application_id)
        response["Content-Disposition"] = 'attachment; filename="%s"' % filename
        return response

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        return JsonResponse(
            {
                "status": "failed",
                "message": "No BPJS report for application {}".format(application_id),
                "error_message": str(e),
            }
        )

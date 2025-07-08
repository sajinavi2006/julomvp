import logging
import urllib.parse

import pdfkit
from django.conf import settings
from django.template.loader import render_to_string

from juloserver.bpjs import get_anaserver_client
from juloserver.bpjs.constants import JuloRedirectUrls, TongdunCodes
from juloserver.bpjs.exceptions import JuloBpjsException
from juloserver.bpjs.models import BpjsTask, SdBpjsCompany, SdBpjsProfile

from .bpjs_interface import BpjsInterface

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = logging.getLogger(__name__)


class Tongdun(BpjsInterface):
    def __init__(self, application, referer=None, public_access_token=None, type_=None):
        super(Tongdun, self).__init__(application, referer, public_access_token, type_)

        self.provider = "tongdun"

    def detail(self, *args, **kwargs):
        tasks = BpjsTask.objects.filter(application_id=self.application.id)
        if "status" in kwargs and kwargs["status"] == "success":
            return tasks.filter(status_code=TongdunCodes.TONGDUN_TASK_SUCCESS_CODE).last()
        return tasks.last()

    @property
    def status(self):
        task = BpjsTask.objects.filter(application_id=self.application.id).last()

        if task.status_code == TongdunCodes.TONGDUN_TASK_SUBMIT_SUCCESS_CODE:
            return self.STATUS_ONGOING
        elif task.status_code == TongdunCodes.TONGDUN_TASK_SUCCESS_CODE:
            return self.STATUS_VERIFIED
        else:
            return self.STATUS_NOT_VERIFIED

    @property
    def companies(self):
        return SdBpjsCompany.objects.filter(sd_bpjs_profile=self.profiles.last())

    @property
    def has_company(self):
        return self.companies.exists()

    @property
    def profiles(self):
        return SdBpjsProfile.objects.filter(application_id=self.application.id)

    @property
    def has_profile(self) -> bool:
        return self.profiles.exists()

    @property
    def is_identity_match(self) -> bool:

        # For a note, Tongdun only has one profile for each application, so we just
        # take the last.

        # this is detokenization for ktp
        profile = self.profiles.last()
        detokenized_application = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': self.application.customer.customer_xid,
                    'object': self.application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenized_application[0]
        return profile.identity_number == application.ktp

    @property
    def is_scraped(self) -> bool:
        if not self.is_submitted:
            return False

        return self.has_company

    @property
    def is_submitted(self):
        return self.has_profile

    def generate_pdf(self):
        bpjs_task = BpjsTask.objects.filter(
            application_id=self.application.id,
            status_code=TongdunCodes.TONGDUN_TASK_SUCCESS_CODE,
        )
        if not bpjs_task:
            raise JuloBpjsException(
                "No tongdun task for application_id {}".format(self.application.id)
            )

        ana_server_client = get_anaserver_client()
        ana_bpjs_data = ana_server_client.get_bpjs_data(self.application.id)
        if not ana_bpjs_data["does_data_exist"]:
            raise JuloBpjsException(
                "No BPJS profile data for "
                "application_id {}".format(ana_bpjs_data["application_id"])
            )

        context = {
            "julo_image": settings.SPHP_STATIC_FILE_PATH + "scraoe-copy-3@3x.png",
            "application_id": self.application.id,
            "sd_bpjs_profile": ana_bpjs_data["sd_bpjs_profile"],
            "sd_bpjs_companies": ana_bpjs_data["sd_bpjs_companies"],
        }
        if not ana_bpjs_data["sd_bpjs_profile"] or not ana_bpjs_data["sd_bpjs_companies"]:
            raise JuloBpjsException("Either sd_bpjs_profile or sd_bpjs_companies is empty")

        template = render_to_string("tongdun_report.html", context=context)
        return pdfkit.from_string(template, False)

    def store_user_information(self, *args, **kwargs):
        from juloserver.bpjs import get_julo_tongdun_client

        task_id = kwargs["task_id"]
        tongdun_client = get_julo_tongdun_client()
        response = tongdun_client.get_bpjs_data(task_id, self.customer.id, self.application.id)

        ana_server_client = get_anaserver_client()
        return ana_server_client.send_bpjs_data(response, self.customer.id, self.application.id)

    def process_callback(self):
        pass

    def authenticate(self, *args, **kwargs):
        """Generate a login url for web view."""
        # customer_id = kwargs['customer_id']
        julo_redirect_url = JuloRedirectUrls.ANDROID_REDIRECT_URL
        return_page = "julo"
        if self.application_type == "app":
            box_token = settings.TONGDUN_BOX_TOKEN_ANDROID
            app_type = self.application_type
        else:
            box_token = settings.TONGDUN_BOX_TOKEN_WEB
            if len(self.application_type.split("_")) == 3:
                app_type, partner, return_page = self.application_type.split("_")
                julo_redirect_url = JuloRedirectUrls.BPJS_WEB_REDIRECT_URL + partner
            else:
                app_type = "web"

        data = {
            "box_token": box_token,
            "passback_params": str(self.customer.id)
            + "_"
            + str(self.application.id)
            + "_"
            + app_type
            + "_"
            + return_page,
            "cb": julo_redirect_url,
            "fix": 1,
        }
        encoded_data = urllib.parse.urlencode(data)
        login_url = "{}?{}".format(settings.TONGDUN_BPJS_LOGIN_URL, encoded_data)
        logger.info({"action": "tongdun.authenticate", "login_url": login_url})

        return login_url

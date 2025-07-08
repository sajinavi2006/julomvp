import logging

import pdfkit
from django.conf import settings
from django.template.loader import render_to_string

from juloserver.bpjs import get_brick_client
from juloserver.bpjs.exceptions import BrickBpjsException
from juloserver.bpjs.models import (
    BpjsUserAccess,
    SdBpjsCompanyScrape,
    SdBpjsPaymentScrape,
    SdBpjsProfileScrape,
)
from juloserver.bpjs.services.providers.bpjs_interface import BpjsInterface
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services2.encryption import AESCipher

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

sentry = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class Brick(BpjsInterface):
    def __init__(self, application, referer=None, public_access_token=None, type_=None):
        super(Brick, self).__init__(application, referer, public_access_token, type_)

        self.provider = "brick"
        self.profile = None
        self.profile_response = None
        self.company_response = None
        self.payment_response = None

        # Configure Brick client
        self.brick_client = get_brick_client()

    def detail(self, *args, **kwargs):
        return self.profiles.last()

    @property
    def has_company(self) -> bool:
        return self.companies.exists()

    @property
    def profiles(self):
        return SdBpjsProfileScrape.objects.filter(application_id=self.application.id)

    @property
    def companies(self):
        return SdBpjsCompanyScrape.objects.filter(profile=self.profiles.last())

    @property
    def status(self):
        has_user_access = BpjsUserAccess.objects.filter(application_id=self.application.id).exists()

        if has_user_access:
            return self.STATUS_VERIFIED

        return self.STATUS_NOT_VERIFIED

    @property
    def has_profile(self) -> bool:
        return self.profiles.exists()

    @property
    def is_submitted(self) -> bool:
        return self.has_profile

    @property
    def is_scraped(self) -> bool:
        if not self.is_submitted:
            return False

        return self.has_company

    @property
    def is_identity_match(self) -> bool:
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
        return str(profile.identity_number) == str(application.ktp)

    @sentry.capture_exceptions
    def authenticate(self):
        """
        Authenticate for get Public Access Token from server Brick.
        """

        client = self.brick_client.set_scraper_instance(self).get_auth_token()
        client_response = client.json()

        data_log = {
            "api_type": "POST",
            "http_status_code": str(client.status_code),
            "query_params": str(client.request.url),
            "request": "header: "
            + str(client.request.headers)
            + " body: "
            + str(client.request.body),
            "response": str(client_response),
            "error_message": None,
        }

        # check status code response 200 is OK
        if client.status_code != 200:
            error_message = "[Authenticate] Connect Brick Provider: [status_code {}]".format(
                str(client.status_code)
            )
            data_log["error_message"] = str(error_message)

            # save log to db
            self.log_api_call(**data_log)
            raise BrickBpjsException(error_message)

        # check response have key status and access token
        if "status" not in client_response or "access_token" not in client_response["data"]:
            error_message = "No target key in response"
            data_log["error_message"] = str(error_message)

            # save log to db
            self.log_api_call(**data_log)
            raise BrickBpjsException(error_message)

        # save log to db
        self.log_api_call(**data_log)
        return client_response

    def generate_pdf(self):
        """Generate pdf from stored data that successfully scraped."""

        if not self.has_profile:
            raise BrickBpjsException(
                "No BPJS profile data for application_id {}".format(self.application.id)
            )

        if not self.has_profile or not self.has_company:
            raise BrickBpjsException("Either profile or companies is empty")

        context = {
            "julo_image": settings.SPHP_STATIC_FILE_PATH + "scraoe-copy-3@3x.png",
            "application_id": self.application.id,
            "profile": self.compile_deep_structure(),
        }

        template = render_to_string("brick_report.html", context=context)
        return pdfkit.from_string(template, False)

    def compile_deep_structure(self):
        data = {}
        profile = self.profiles.last()
        for key, value in profile.__dict__.items():
            if (
                key
                in [
                    "real_name",
                    "identity_number",
                    "npwp_number",
                    "birthday",
                    "phone",
                    "address",
                    "gender",
                    "total_balance",
                    "type",
                ]
                and value is not None
            ):
                data[key] = value

        companies = []
        for company in profile.companies.all():
            _company = {}
            for key, value in company.__dict__.items():
                if (
                    key
                    in [
                        "company",
                        "current_salary",
                        "last_payment_date",
                        "employment_status",
                        "employment_month_duration",
                        "bpjs_card_number",
                    ]
                    and value is not None
                ):
                    _company[key] = value

            payments = []
            for payment in company.payments.all():
                _payment = {}
                for key, value in payment.__dict__.items():
                    if key in ["payment_amount", "payment_date"]:
                        _payment[key] = value

                payments.append(_payment)

            _company["payments"] = payments
            companies.append(_company)
        data["companies"] = companies

        return data

    @sentry.capture_exceptions
    def store_user_information(self, user_access_token):
        """
        For information user, and save data user to the table.
            - Save profile info = In Brick call with General Info
            - Save Company data = In Brick call with Employment Info
            - Save Salary data = In Brick call with Salary Info
        """

        try:
            self.brick_client.set_scraper_instance(self).set_user_access_token(user_access_token)

            self.profile_response = self.brick_client.get_income_profile()
            self.save_profile_info()

            self.company_response = self.brick_client.get_income_employment()
            self.save_company_data()

            self.payment_response = self.brick_client.get_income_salary()
            self.save_payment_data()

            return True
        except Exception as error:
            error_message = str(error)

            raise BrickBpjsException(error_message)

    def save_profile_info(self):
        """
        Save data profile user information with relation by application_id
        """
        Brick.verify_get_information(self.profile_response.json())
        data_profile = self.profile_response.json()["data"]
        if data_profile is None or data_profile == "":
            self.profile = SdBpjsProfileScrape.objects.create(application_id=self.application.id)
        else:
            self.profile = SdBpjsProfileScrape.objects.create(
                application_id=self.application.id,
                real_name=data_profile["name"],
                identity_number=data_profile["ktpNumber"],
                npwp_number=data_profile["npwpNumber"],
                birthday=data_profile["dob"],
                phone=data_profile["phoneNumber"],
                address=data_profile["address"],
                gender=data_profile["gender"],
                bpjs_cards=data_profile["bpjsCards"],
                total_balance=data_profile["totalBalance"],
                type=data_profile["type"],
                application_status_code=self.application.application_status_id,
            )

        return self.profile

    def save_company_data(self):
        """
        Save data company from brick user.
        """
        Brick.verify_get_information(self.company_response.json())
        data_company = self.company_response.json()["data"]
        if data_company is None:
            return
        try:
            for item in data_company:
                SdBpjsCompanyScrape.objects.create(
                    profile=self.profile,
                    company=item["companyName"],
                    current_salary=item["latestSalary"],
                    last_payment_date=item["latestPaymentDate"],
                    employment_status=item["status"],
                    employment_month_duration=item["workingMonth"],
                    bpjs_card_number=item["bpjsCardNumber"],
                    application_status_code=self.application.application_status_id,
                )

            return True
        except Exception as error:
            raise BrickBpjsException(str(error))

    def save_payment_data(self):
        """
        Save data salary from Brick Server.
        """
        Brick.verify_get_information(self.payment_response.json())
        data_payment = self.payment_response.json()["data"]
        if data_payment is None:
            return
        try:
            for item in data_payment:
                company_id = Brick.search_company_id(item["companyName"], item["bpjsCardNumber"])
                id_master_pk = SdBpjsCompanyScrape.objects.get(pk=company_id)
                SdBpjsPaymentScrape.objects.create(
                    company=id_master_pk,
                    payment_amount=item["salary"],
                    payment_date=item["monthName"],
                    application_status_code=self.application.application_status_id,
                )

            return True
        except Exception as error:
            raise BrickBpjsException(str(error))

    @staticmethod
    def verify_get_information(response):
        """
        Verify data response structure must correct.
        """

        if "data" not in response:
            error_message = "Not found key [data] in response."
            raise BrickBpjsException(error_message)

    @staticmethod
    def search_company_id(company_name, bpjs_card_number):
        """
        Search data company by Bpjs Card number & Company Name
        """

        sd_bpjs_company_id_master = (
            SdBpjsCompanyScrape.objects.values("id")
            .filter(bpjs_card_number=bpjs_card_number)
            .order_by("-id")[:1]
        )

        if sd_bpjs_company_id_master:
            return sd_bpjs_company_id_master[0]["id"]

        return None

    def process_callback(self):
        pass

    @sentry.capture_exceptions
    def get_full_widget_url(self):
        """
        Generate URL Brick for old version
        """

        try:
            if self.referer is None:
                error_message = "Error to get Host: " + str(self.referer)
                logger.error(
                    {
                        "message": error_message,
                        "method": str(__name__),
                        "action": "Generate URL callback Brick.",
                    }
                )
                raise BrickBpjsException(error_message)

            if settings.BRICK_WIDGET_BASE_URL is None:
                error_message = "BRICK_WIDGET_BASE_URL: {}".format(
                    str(settings.BRICK_WIDGET_BASE_URL)
                )
                logger.error(
                    {
                        "message": error_message,
                        "method": str(__name__),
                        "action": "Get environment data settings",
                    }
                )
                raise BrickBpjsException(error_message)

            if settings.BASE_URL is None:
                error_message = "[BRICK] BASE_URL: {}".format(str(settings.BRICK_WIDGET_BASE_URL))
                logger.error(
                    {
                        "message": error_message,
                        "method": str(__name__),
                        "action": "Get env Generate Full Widget Brick",
                    }
                )
                raise BrickBpjsException(error_message)

            if not self.public_access_token:
                error_message = "[BRICK] Public Access Token: {}".format(
                    str(settings.BRICK_WIDGET_BASE_URL)
                )
                logger.error(
                    {
                        "message": error_message,
                        "method": str(__name__),
                        "action": "Get env Generate Full Widget Brick",
                    }
                )
                raise BrickBpjsException(error_message)

            redirect_url = "{0}{1}{2}{3}".format(
                settings.BASE_URL,
                "/api/bpjs/v2/applications/",
                self.application.application_xid,
                "/brick-callback",
            )

            widget_url = "{}/v1/?accessToken={}&redirect_url={}".format(
                settings.BRICK_WIDGET_BASE_URL, self.public_access_token, redirect_url
            )

            return widget_url
        except Exception as error:
            error_message = str(error)
            logger.warning(
                {
                    "message": error_message,
                    "method": str(__name__),
                    "action": "Generate Url callback Brick.",
                }
            )
            raise BrickBpjsException(error_message)


def store_bpjs_from_brick(application_xid, user_access_credential, referrer):
    from juloserver.bpjs.services.bpjs import Bpjs
    from juloserver.julo.models import Application

    if not user_access_credential:
        logger.info(
            {
                "message": "User Access Token not found.",
                "method": str(__name__),
                "action": "[Celery] Brick Get Information",
            }
        )
        raise BrickBpjsException("[Celery] Brick Get Information - User Access Token not found.")

    application = Application.objects.get_or_none(application_xid=application_xid)
    if not application:
        error_message = "Application not found [application xid: " + str(application_xid) + "]"
        logger.info(
            {
                "message": error_message,
                "method": str(__name__),
                "action": "[Celery] Brick Get Information",
            }
        )
        raise BrickBpjsException(error_message)
    aes = AESCipher(settings.BRICK_SALT)

    user_access_token = aes.decrypt(user_access_credential)

    bpjs = Bpjs(application=application)
    bpjs.provider = bpjs.PROVIDER_BRICK
    bpjs.referer = referrer
    bpjs.store_user_information(user_access_token)

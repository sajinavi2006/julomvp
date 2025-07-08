import base64
from datetime import datetime
import json
from typing import Union

import jwt
import requests
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import RedirectView
from rest_framework.generics import RetrieveAPIView, UpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from rest_framework.views import APIView

from juloserver.antifraud.decorator.rate_limit import antifraud_rate_limit
from juloserver.antifraud.constant.feature_setting import AntiFraudRateLimit
from juloserver.apiv1.exceptions import ResourceNotFound
from juloserver.apiv1.serializers import ApplicationSerializer
from juloserver.apiv2.constants import ErrorCode, ErrorMessage
from juloserver.apiv2.utils import failure_template, success_template
from juloserver.application_flow.constants import JuloOneChangeReason, InstructionVerificationConst
from juloserver.application_flow.models import (
    BankStatementProviderLog,
    EmulatorCheck,
    EmulatorCheckIOS,
)
from juloserver.application_flow.serializers import (
    EmulatorCheckSafetyNetSerializer,
    GooglePlayIntegrityDecodeSerializer,
    GooglePlayIntegritySerializer,
    ReapplyJuloOneSerializer,
    SelfCorrectionTypoSerializer,
    SelfMotherCorrectionSerializer,
    SelfMotherTypoCorrectionSerializer,
    BankCorrectionSerializer,
    EmulatorCheckIOSSerializer,
)
from juloserver.application_flow.services import (
    create_julo1_application_with_serializer,
    fetch_application_image_url,
    format_pre_long_form_message,
    get_tutorial_bottom_sheet_content,
    process_emulator_detection,
    reject_application_by_google_play_integrity,
    store_application_to_experiment_table,
    verify_emulator_check_eligibility,
    get_instruction_verification_docs,
    decline_hsfbp_income_verification,
)
from juloserver.application_flow.tasks import (
    handle_google_play_integrity_decode_request_task,
)
from juloserver.application_form.services.application_service import (
    stored_application_to_upgrade_table,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Application,
    Customer,
    Device,
    Mantri,
    BankStatementSubmit,
    StatusLookup,
    Image,
)
from juloserver.julo.services import (
    link_to_partner_if_exists,
    process_application_status_change,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julolog.julolog import JuloLog
from juloserver.pin.services import does_user_have_pin
from juloserver.partnership.constants import HTTPStatusCode
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    not_found_response,
    success_response,
)
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.application_flow.authentication import (
    OnboardingInternalAuthentication,
    ApplicationPermission,
)
from juloserver.integapiv1.authentication import IsSourceAuthenticated
from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck

from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.application_flow.services2.bank_statement import (
    BankStatementClient,
    Perfios,
    PowerCred,
    LBSJWTAuthentication,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.application_form.services.mother_name_experiment_service import MotherNameValidation
from juloserver.application_form.constants import MotherMaidenNameConst

logger = JuloLog()
julo_sentry_client = get_julo_sentry_client()


class ApplicationReapplyJuloOne(APIView):
    model_class = Application
    serializer_class = ReapplyJuloOneSerializer

    def post(self, request):
        request_data = self.serializer_class(data=request.data)
        request_data.is_valid()
        customer = request.user.customer
        customer.update_safely(is_review_submitted=False)
        web_version = request.data.get('web_version')

        if request_data.data.get('mother_maiden_name', None):
            customer.mother_maiden_name = request_data.data['mother_maiden_name']
            customer.save()
        if not customer.can_reapply:
            logger.warning(
                {
                    'msg': 'creating application when can_reapply is false',
                    'customer_id': customer.id,
                }
            )
            return Response(
                failure_template(ErrorCode.CUSTOMER_REAPPLY, ErrorMessage.CUSTOMER_REAPPLY)
            )

        if not does_user_have_pin(request.user):
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'message': 'This customer is not available'}
            )

        # get device and app_version
        device = None
        if not web_version:
            device_id = int(request.data['device_id'])
            device = Device.objects.get_or_none(id=device_id, customer=customer)
            if device is None:
                raise ResourceNotFound(resource_id=device_id)

        # handle null app version
        app_version = request.data.get('app_version')
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        from juloserver.apiv2.services import get_latest_app_version

        if not app_version:
            app_version = get_latest_app_version()

        # get last application
        last_application = customer.application_set.regular_not_deletes().last()
        if not last_application:
            return Response(
                status=HTTP_404_NOT_FOUND, data={'message': 'customer has no application'}
            )

        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': last_application.customer.customer_xid,
                    'object': last_application,
                }
            ],
            force_get_local_data=True,
        )
        last_application = detokenized_applications[0]

        last_application_number = last_application.application_number
        if not last_application_number:
            last_application_number = 1
        application_number = last_application_number + 1

        data_to_save = {'application_number': application_number}

        # check duration
        today = timezone.now().date()
        date_apply = last_application.cdate.date()
        day_range = (today - date_apply).days
        fields = [
            'marketing_source',
            'is_own_phone',
            'mobile_phone_1',
            'fullname',
            'dob',
            'gender',
            'ktp',
            'email',
            'bbm_pin',
            'twitter_username',
            'instagram_username',
            'marital_status',
            'dependent',
            'spouse_name',
            'spouse_dob',
            'close_kin_name',
            'close_kin_mobile_phone',
            'close_kin_relationship',
            'birth_place',
            'kin_name',
            'kin_dob',
            'kin_gender',
            'kin_mobile_phone',
            'kin_relationship',
            'last_education',
            'college',
            'major',
            'graduation_year',
            'gpa',
            'vehicle_type_1',
            'vehicle_ownership_1',
            'bank_name',
            'bank_branch',
            'bank_account_number',
            'name_in_bank',
            'address_kabupaten',
            'address_kecamatan',
            'address_kelurahan',
            'address_kodepos',
            'address_provinsi',
            'address_street_num',
            'home_status',
            'occupied_since',
            'job_description',
            'job_function',
            'job_industry',
            'job_start',
            'job_type',
            'company_name',
            'company_phone_number',
            'payday',
        ]

        if day_range <= 30:
            fields += [
                'billing_office',
                'company_address',
                'employment_status',
                'has_other_income',
                'has_whatsapp_1',
                'has_whatsapp_2',
                'hrd_name',
                'income_1',
                'income_2',
                'income_3',
                'landlord_mobile_phone',
                'monthly_expenses',
                'monthly_housing_cost',
                'monthly_income',
                'mutation',
                'number_of_employees',
                'other_income_amount',
                'other_income_source',
                'position_employees',
                'spouse_has_whatsapp',
                'spouse_mobile_phone',
                'total_current_debt',
                'work_kodepos',
                'mantri_id',
            ]

        if last_application.mantri_id:
            fields += ['referral_code']

        for field in fields:
            data_to_save[field] = getattr(last_application, field)

        serializer = ApplicationSerializer(data=data_to_save)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():

                # prevent race condition when there are multiple request at the same time
                customer = Customer.objects.select_for_update().get(pk=customer.pk)
                if not customer.can_reapply:
                    logger.warning(
                        {
                            'msg': 'creating application when can_reapply is false',
                            'customer_id': customer.id,
                        }
                    )
                    return Response(
                        failure_template(ErrorCode.CUSTOMER_REAPPLY, ErrorMessage.CUSTOMER_REAPPLY)
                    )

                application = create_julo1_application_with_serializer(
                    serializer=serializer,
                    customer=last_application.customer,
                    device=device,
                    app_version=app_version,
                    web_version=web_version,
                    onboarding_id=last_application.onboarding_id,
                )

                store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

                stored_application_to_upgrade_table(application)

                # not populate the ktp and selfie pic, for security reason

                # images = Image.objects.filter(
                #     image_source=last_application.id,
                #     image_type__in=('ktp_self', 'selfie', 'crop_selfie')
                # )
                # for image in images:
                #     Image.objects.create(
                #         image_source=application.id,
                #         image_type=image.image_type,
                #         url=image.url,
                #         image_status=image.image_status,
                #         thumbnail_url=image.thumbnail_url,
                #         service=image.service,
                #     )

                logger.info(
                    {
                        'action': 'application reapply',
                        'status': 'form_created',
                        'application': application,
                        'customer': customer,
                        'device': application.device,
                    }
                )

                if day_range <= 30 and last_application.mantri_id:
                    # Set mantri id if referral code is a mantri id
                    referral_code = data_to_save['referral_code']
                    if referral_code:
                        referral_code = referral_code.replace(' ', '')
                        mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                        application.mantri = mantri_obj
                        application.save(update_fields=['mantri'])

                link_to_partner_if_exists(application)

                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_CREATED,
                    change_reason='customer_triggered',
                )

                # update reapply value after creating new application
                customer.can_reapply = False
                customer.save()

            create_application_checklist_async.delay(application.id)
            final_respone = serializer.data.copy()
            final_respone['mother_maiden_name'] = customer.mother_maiden_name

            return Response(success_template(final_respone))
        except Exception:
            julo_sentry_client.captureException()
            return Response(failure_template(ErrorCode.CUSTOMER_REAPPLY, ErrorMessage.GENERAL))


class PreLongFormSettingAPI(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        # data except guidancePopup is hardcoded
        data = {
            "openCv": {
                "is_active": True,
                "dark": {
                    "lower_bin": 2,
                    "numer_of_bin": 7,
                    "upper_limit": 5,
                    "lower_limit": 90,
                    "upper_bin": 6,
                },
                "number_of_tries": 2,
                "glare": {"threshold": 250, "percentage_limit": 0.9},
                "blur": {"threshold": 0},
            },
            "motherMaidenName": {"is_active": True},
            "birthPlaceRequired": {"is_active": True},
        }
        data.update(guidancePopup=format_pre_long_form_message())

        logger.info({"message": "Pre Longform setting", "data": data}, request=request)
        return success_response(data)


class GetApplicationImageURL(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        if 'image_id' not in request.GET:
            return general_error_response({'image_id': "This field is required"})
        image_id = int(request.GET.get('image_id'))
        image_url = fetch_application_image_url(request.user.customer, image_id)
        if not image_url:
            return general_error_response(
                {'error': 'No Images found with the given image_id for the customer'}
            )
        response = {'image_id': image_id, 'image_url': image_url}
        return success_response(response)


class SafetyNetViewEmulatorCheck(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = EmulatorCheckSafetyNetSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @antifraud_rate_limit(
        feature_name=AntiFraudRateLimit.EMULATOR_CHECK
    )
    def get(self, request):
        try:
            application_id = request.GET.get('application_id')
            if not application_id:
                return general_error_response("'application_id' is a required field")
            application = Application.objects.get_or_none(
                pk=application_id, customer=request.user.customer
            )
            if not application:
                return general_error_response(
                    'Application with application_id = %s is not found' % (str(application_id))
                )
            eligible_for_emulator_check = verify_emulator_check_eligibility(application)
            response = {
                "eligible_for_emulator_check": True if eligible_for_emulator_check else False,
                "application_id": application_id,
            }
            if eligible_for_emulator_check:
                response['request_timeout'] = eligible_for_emulator_check['timeout']
            return success_response(response)
        except Exception as exc:
            return general_error_response(str(exc))

    @antifraud_rate_limit(
        feature_name=AntiFraudRateLimit.EMULATOR_CHECK
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return general_error_response(serializer.errors)

            validated_data = serializer.validated_data
            application_id = validated_data.get('application_id')
            application = Application.objects.get_or_none(
                pk=application_id, customer=request.user.customer
            )
            if not application:
                return general_error_response(
                    'Application with application_id = %s is not found' % (str(application_id))
                )
            serializer.save()
            if not validated_data.get('is_request_timeout'):
                process_emulator_detection(serializer.data)
            return created_response(
                {
                    'data_saved': serializer.data,
                }
            )
        except Exception as exc:
            return general_error_response(str(exc))


class GooglePlayIntegrity(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GooglePlayIntegritySerializer

    def post(self, request, application_id):
        """The request is comes from the Google Play Integrity API itself.
        Its mean that the request is json object"""
        import copy

        try:

            application = Application.objects.get_or_none(
                pk=application_id, customer=request.user.customer
            )
            if not application:
                return general_error_response(
                    'Application with application_id = %s is not found' % (str(application_id))
                )

            data = copy.deepcopy(request.data)
            if (
                'error_message' in data
                and data['error_message'] is not None
                and data['error_message'] != ""
            ):
                stored_data = {
                    "error_msg": data['error_message'],
                }
            elif (
                "is_request_timeout" in request.data and request.data["is_request_timeout"] is True
            ):
                stored_data = {"error_msg": "Julo - Request timeout"}
            else:

                if "requestDetails" in data:

                    if "timestampMillis" in data['requestDetails']:
                        data["requestDetails"]["timestampMillis"] = timezone.localtime(
                            datetime.fromtimestamp(
                                int(data["requestDetails"]["timestampMillis"]) / 1000,
                            )
                        )
                    else:
                        data["requestDetails"]["timestampMillis"] = None
                else:
                    data["requestDetails"]["timestampMillis"] = None
                    data["requestDetails"]["nonce"] = None

                if "appIntegrity" in data:
                    if "certificateSha256Digest" not in data["appIntegrity"]:
                        data["appIntegrity"]["certificateSha256Digest"] = []
                    if "packageName" not in data["appIntegrity"]:
                        data["appIntegrity"]["packageName"] = None
                    if "appRecognitionVerdict" not in data["appIntegrity"]:
                        data["appIntegrity"]["appRecognitionVerdict"] = None
                else:
                    data["appIntegrity"]["certificateSha256Digest"] = []
                    data["appIntegrity"]["packageName"] = None
                    data["appIntegrity"]["appRecognitionVerdict"] = None

                if "deviceIntegrity" in data:
                    if "deviceRecognitionVerdict" not in data["deviceIntegrity"]:
                        data["deviceIntegrity"]["deviceRecognitionVerdict"] = None
                else:
                    data["deviceIntegrity"]["deviceRecognitionVerdict"] = None

                if "accountDetails" not in data:
                    data["accountDetails"]["appLicensingVerdict"] = None
                else:
                    if "appLicensingVerdict" not in data["accountDetails"]:
                        data["accountDetails"]["appLicensingVerdict"] = None

                certificateSha256Digest = ",".join(data["appIntegrity"]["certificateSha256Digest"])

                stored_data = {
                    "timestamp_ms": data["requestDetails"]["timestampMillis"],
                    "nonce": data["requestDetails"]["nonce"],
                    "apk_package_name": data["appIntegrity"]["packageName"],
                    "apk_certificate_digest_sha_256": f"[{certificateSha256Digest}]",
                    "app_recognition_verdict": data["appIntegrity"]["appRecognitionVerdict"],
                    "device_recognition_verdict": data["deviceIntegrity"][
                        "deviceRecognitionVerdict"
                    ],
                    "app_licensing_verdict": data["accountDetails"]["appLicensingVerdict"],
                    "original_response": request.data,
                }

            stored_data["application"] = application
            stored_data["service_provider"] = "GooglePlayIntegrity"
            emulator_check = EmulatorCheck.objects.create(**stored_data)

            # After we store data into the approripate table, next we do some logic if the
            # application has emulator detected then reject the application
            reject_application_by_google_play_integrity(emulator_check)

            serializer = self.serializer_class(emulator_check)

            return created_response(serializer.data['original_response'])
        except Exception as exc:
            return general_error_response(str(exc))


class GooglePlayIntegrityDecodeView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GooglePlayIntegrityDecodeSerializer

    def post(self, request, application_id):
        logging_data = {
            'method': 'google_play_integrity_deocode_view_check',
            'application_id': application_id,
            'response': 'success'
        }
        application = Application.objects.get_or_none(
            pk=application_id, customer=request.user.customer
        )
        if not application:
            logging_data['response'] = 'Invalid Application ID = %s' % (str(application_id))
            logger.info(logging_data)
            return general_error_response('Invalid Application ID = %s' % (str(application_id)))

        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            if application.is_jstarter:
                handle_google_play_integrity_decode_request_task(
                    application.id, serializer.validated_data
                )
            else:
                handle_google_play_integrity_decode_request_task.delay(
                    application.id, serializer.validated_data
                )
            logger.info(logging_data)
            return success_response()
        logging_data['response'] = str(serializer.errors)
        logger.error(logging_data)
        return general_error_response(serializer.errors)


class EmulatorCheckIOSView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = EmulatorCheckIOSSerializer

    def post(self, request, application_id):
        logging_data = {'method': 'emulator_check_ios', 'application_id': application_id}
        logger.info(logging_data)
        application = Application.objects.get_or_none(
            pk=application_id, customer=request.user.customer
        )
        if not application:
            response = 'Invalid Application ID'
            logging_data['response'] = response
            logger.warn(logging_data)
            return general_error_response(response)

        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            EmulatorCheckIOS.objects.create(
                application_id=application_id, **serializer.validated_data
            )
            return success_response("data stored successfully")

        logging_data['response'] = str(serializer.errors)
        logger.info(logging_data)
        return general_error_response(serializer.errors)


class TutorialBottomSheet(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
    }
    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        content = get_tutorial_bottom_sheet_content()
        if not content:
            return not_found_response('Not found!')

        return success_response(content)


class PowerCredCallback(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)
    authentication_classes = []
    http_method_names = ['post']

    def post(self, request):
        from juloserver.application_flow.services2.bank_statement import (
            BankStatementError,
            PowerCred,
        )

        try:
            PowerCred.callback(request.data)
        except (Exception, BankStatementError) as exc:
            julo_sentry_client.captureException()
            return general_error_response(str(exc))

        return success_response({'message': 'success'})


class PerfiosCallback(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)
    authentication_classes = []
    http_method_names = ['post']

    def post(self, request):
        from juloserver.application_flow.services2.bank_statement import (
            BankStatementError,
            Perfios,
        )

        try:
            Perfios.callback(request.data)
        except (Exception, BankStatementError) as exc:
            julo_sentry_client.captureException()
            return general_error_response(str(exc))

        return success_response({'message': 'success'})


class BankStatementUrl(StandardizedExceptionHandlerMixin, APIView):
    # for temporary fixing until all old LBS expiry token clear out completely
    # we still use AllowAny permission
    permission_classes = (AllowAny,)

    authentication_classes = [LBSJWTAuthentication]

    def get(self, request, application_id):
        """
        This endpoint used when bank statement loaded to get target link
        in the provided button, before button clicked.
        """
        application = Application.objects.get(pk=application_id)

        if request.user is None:
            if getattr(request, 'auth', None) == "expired":
                return general_error_response({"message": "Token has expired"})
            # todo: this used to handle existing user that still using expiry token.
            #  Remove after no message below shown up again in OpenSearch
            logger.error({"message": "BankStatementUrl no user."})
            pass
        elif request.user != application.customer.user:
            return general_error_response({"message": "Fail to authenticate user"})

        client = BankStatementClient(application=application)
        url = client.build_url_submission()
        return success_response({"url": url})


class BankStatement(StandardizedExceptionHandlerMixin, RedirectView):

    def get(self, request, *args, **kwargs):
        """
        This endpoint used when in bank statement page, the continue button
        clicked, which trigger to redirect to vendor site.
        """

        from django.utils.dateparse import parse_datetime

        lid = request.GET.get("lid")
        token = request.GET.get("token")

        if "?url_view_type=" in token:
            token = token.split("?url_view_type=")[0]

        logger.info(
            {
                "message": "Bank statement click processed",
                "data": {
                    "lid": lid,
                },
            }
        )

        # First get the information from passed lid
        data = BankStatementProviderLog.objects.get(pk=lid)
        if not data:
            logger.error(
                {"bank_statement_log_id": lid, "message": "Bank statement click: log not found"}
            )
            return render(request, 'lbs-400.html', status=400)

        # Secondly we try to validate the token
        payload = jwt.decode(token, BankStatementClient.JWT_KID, algorithms="HS256")
        if payload["application_id"] != data.application_id:
            logger.error(
                {
                    "bank_statement_log_id": lid,
                    "message": "Bank statement click: application not valid",
                }
            )

            return render(request, 'lbs-401.html', status=401)

        expired_at = parse_datetime(payload["expired_at"])
        now = timezone.localtime(timezone.now())
        if now > expired_at:
            logger.error(
                {"bank_statement_log_id": lid, "message": "Bank statement click: Token expired"}
            )
            return render(request, 'lbs-400.html', status=400)

        # Finally process to redirect
        application = Application.objects.get(pk=data.application_id)

        # Check if the bank statement is fraud
        submission = BankStatementSubmit.objects.filter(application_id=application.id).last()
        if submission is not None and submission.is_fraud:
            return render(request, 'lbs-400.html', status=400)

        provider = None
        log = json.loads(data.log.replace("'", "\"").replace(": None", ": null"))
        if data.provider == BankStatementClient.PERFIOS:
            self.url = log["redirectUrl"]
            provider = Perfios(application)
        elif data.provider == BankStatementClient.POWERCRED:
            provider = PowerCred(application)
            self.url = log["url"]

        if self.url and provider:
            logger.info(
                {
                    "message": "Bank statement click: try to move to x128",
                    "data": {
                        "lid": lid,
                    },
                }
            )
            if provider.is_eligible_to_move_to_128():
                provider.move_to_128()
                self._set_as_clicked(data)
            return super().get(request)

        logger.error({"bank_statement_log_id": lid, "message": "Bank statement provider not found"})
        return render(request, 'lbs-400.html', status=400)

    @staticmethod
    def _set_as_clicked(data):
        data.clicked_at = timezone.localtime(timezone.now())
        data.save()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def waiting_list_x155_upload(request: HttpRequest) -> Union[HttpResponse, HttpResponseRedirect]:
    import csv
    import re

    from django.shortcuts import render
    from django.core.urlresolvers import reverse
    from juloserver.application_flow.crm.forms import WaitlistUploadForm
    from django.contrib import messages

    upload_form = WaitlistUploadForm(request.POST, request.FILES)
    template_name = 'object/onboarding/waitlist_upload.html'
    url = reverse('bulk_upload:onboarding_waitlist_155')

    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            file_ = upload_form.cleaned_data['file_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            try:
                x155_status = StatusLookup.objects.filter(status_code=155).last()

                # Here we read csv file, check the status if x155 and move it to x120
                decoded_file = file_.read().decode('utf-8').splitlines()
                reader = csv.reader(decoded_file)

                application_ids = []

                # Process the CSV file
                for row in reader:
                    value = row[0]
                    if not bool(re.match(r'^\d+$', value)):
                        continue
                    application_ids.append(int(value))

                applications = Application.objects.filter(
                    id__in=application_ids, application_status=x155_status
                )
                for application in applications:
                    process_application_status_change(
                        application, ApplicationStatusCodes.DOCUMENTS_SUBMITTED, "waitlist is open"
                    )

                messages.success(request, "Success processing csv file")

            except Exception as e:
                messages.error(request, str(e))

    elif request.method == 'GET':
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


class DigitalSignatureData(StandardizedExceptionHandlerMixinV2, APIView):
    """
    This endpoint intended to hit only by internal only, especially for Kanban team
    to provide required data for Digital Signature.
    """

    http_method_names = ['get']
    permission_classes = (IsSourceAuthenticated,)
    authentication_classes = [OnboardingInternalAuthentication]

    def get(self, request, application_id, *args, **kwargs):
        application = (
            Application.objects.prefetch_related(
                "activelivenessdetection_set", "passivelivenessdetection", "dukcapilresponse_set"
            )
            .select_related("customer")
            .filter(id=application_id)
            .last()
        )
        if not application:
            return not_found_response("Application not found")

        active_liveness = application.activelivenessdetection_set.last()

        passive_liveness = None
        if hasattr(application, "passivelivenessdetection"):
            passive_liveness = application.passivelivenessdetection

        dukcapil_webservice = application.dukcapilresponse_set.last()
        dukcapil_fr = DukcapilFaceRecognitionCheck.objects.filter(
            application_id=application.id
        ).last()
        detokenized_dukcapil_frs = detokenize_for_model_object(
            PiiSource.DUKCAPIL_FACE_RECOGNITION_CHECK,
            [
                {
                    'object': dukcapil_fr,
                }
            ],
            force_get_local_data=True,
        )
        dukcapil_fr = detokenized_dukcapil_frs[0]

        images = Image.objects.filter(
            image_source=application.id, image_type__in=["selfie", "ktp_self"]
        )
        encoded_selfie = None
        encoded_ktp_self = None
        for image in images:
            url = image.image_url
            if url is None:
                continue
            response = requests.get(url)
            if response.status_code != 200:
                continue
            content = response.content
            encoded_image = base64.b64encode(content).decode("utf-8")

            if image.image_type.lower() == "selfie":
                encoded_selfie = f"data:image/png;base64,{encoded_image}"
            elif image.image_type.lower() == "ktp_self":
                encoded_ktp_self = f"data:image/png;base64,{encoded_image}"

        active_liveness_data = {}
        if active_liveness:
            active_liveness_data = {
                "status": active_liveness.status,
                "score": active_liveness.score,
                "error_code": active_liveness.error_code,
                "latency": active_liveness.latency,
                "sequence": active_liveness.sequence,
                "attempt": active_liveness.attempt,
                "api_version": active_liveness.api_version,
                "client_type": active_liveness.client_type,
                "detect_type": active_liveness.detect_type,
                "service_type": active_liveness.service_type,
            }

        passive_liveness_data = {}
        if passive_liveness:
            passive_liveness_data = {
                "status": passive_liveness.status,
                "score": passive_liveness.score,
                "error_code": passive_liveness.error_code,
                "latency": passive_liveness.latency,
                "api_version": passive_liveness.api_version,
                "attempt": passive_liveness.attempt,
                "client_type": passive_liveness.client_type,
                "service_type": passive_liveness.service_type,
            }

        dukcapil_webservice_data = {}
        if dukcapil_webservice:
            dukcapil_webservice_data = {
                "trx_id": dukcapil_webservice.trx_id,
                "ref_id": dukcapil_webservice.ref_id,
                "status": self._cast_string(dukcapil_webservice.status, int),
                "errors": dukcapil_webservice.errors,
                "message": dukcapil_webservice.message,
                "name": dukcapil_webservice.name,
                "birthdate": dukcapil_webservice.birthdate,
                "birthplace": dukcapil_webservice.birthplace,
                "address": dukcapil_webservice.address,
                "gender": dukcapil_webservice.gender,
                "marital_status": dukcapil_webservice.marital_status,
                "source": dukcapil_webservice.source,
                "address_kabupaten": dukcapil_webservice.address_kabupaten,
                "address_kecamatan": dukcapil_webservice.address_kecamatan,
                "address_kelurahan": dukcapil_webservice.address_kelurahan,
                "address_provinsi": dukcapil_webservice.address_provinsi,
                "address_street": dukcapil_webservice.address_street,
                "job_type": dukcapil_webservice.job_type,
            }

        dukcapil_fr_data = {}
        if dukcapil_fr:

            dukcapil_fr_data = {
                "transaction_id": dukcapil_fr.transaction_id,
                "transaction_source": dukcapil_fr.transaction_source,
                "client_customer_id": dukcapil_fr.client_customer_id,
                "nik": dukcapil_fr.nik,
                "threshold": dukcapil_fr.threshold,
                "template": dukcapil_fr.template,
                "type": dukcapil_fr.type,
                "position": dukcapil_fr.position,
                "response_code": self._cast_string(dukcapil_fr.response_code, int),
                "response_score": self._cast_string(dukcapil_fr.response_score, float),
                "quota_limiter": self._cast_string(dukcapil_fr.quota_limiter, int),
            }

        data = {
            "customer_xid": application.customer.customer_xid,
            "email": application.email,
            "mobile_phone": application.mobile_phone_1,
            "name": application.fullname,
            "dob": application.dob.strftime("%Y-%m-%d") if application.dob else None,
            "nik": application.ktp,
            "selfie": encoded_selfie,
            "ktp_photo": encoded_ktp_self,
            "liveness": {"active": active_liveness_data, "passive": passive_liveness_data},
            "dukcapil": {
                "webservice": dukcapil_webservice_data,
                "face_recognition": dukcapil_fr_data,
            },
        }

        return success_response(data)

    def _cast_string(self, input, data_type):
        if not input:
            return None

        try:
            return data_type(input)
        except ValueError:
            return None


class DigitalSignatureDukcapil(StandardizedExceptionHandlerMixinV2, APIView):
    """
    This endpoint intended to hit only by internal only, especially for Kanban team
    to trigger Dukcapil request.
    """

    http_method_names = ['post']
    permission_classes = (IsSourceAuthenticated,)
    authentication_classes = [OnboardingInternalAuthentication]

    def post(self, request, application_id, *args, **kwargs):
        from juloserver.personal_data_verification.tasks import face_recogniton, fetch_dukcapil_data

        application = Application.objects.filter(id=application_id).last()
        if not application:
            return not_found_response("Application not found")

        # try to hit dukcapil webservice first
        fetch_dukcapil_data.delay(application.id)

        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': application.customer.customer_xid,
                    'object': application,
                }
            ],
            force_get_local_data=True,
        )
        application = detokenized_applications[0]
        # try to hit dukcapil FR
        face_recogniton.delay(application.id, application.ktp)

        return success_response("Requesting Dukcapil data")


class SelfCorrectionTypoView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    serializer_class = SelfCorrectionTypoSerializer
    permission_classes = (ApplicationPermission,)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return success_response(response.data)

    def get_queryset(self):
        return Application.objects.all()

    def partial_update(self, request, *args, **kwargs):
        """Change application to x121 from x127"""

        application = self.get_object()
        self.check_object_permissions(request, application)
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        serializer = self.get_serializer(application)
        process_application_status_change(
            application,
            new_status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            change_reason=JuloOneChangeReason.CUSTOMER_TYPO_ACK,
        )
        return success_response(serializer.data)


class SelfMotherCorrectionView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    serializer_class = SelfMotherCorrectionSerializer
    permission_classes = (ApplicationPermission,)
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return success_response(response.data)

    def get_queryset(self):
        return Application.objects.all()

    def partial_update(self, request, *args, **kwargs):
        """Change application to x127 from x121"""

        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        application = self.get_object()
        self.check_object_permissions(request, application)
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        serializer = self.get_serializer(application, data=request.data, partial=True)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend(f"{field}: {error}" for error in errors)
                else:
                    error_messages.append(f"{field}: {errors}")
            return general_error_response(error_messages)

        mother_maiden_name = self.request.data.get('mother_maiden_name')
        mother_name_validation = MotherNameValidation(
            application_id=application.id,
            app_version=app_version,
            mother_maiden_name=mother_maiden_name,
        )
        if not mother_name_validation.run_validation():
            return general_error_response(MotherMaidenNameConst.ERROR_MESSAGE)

        customer = application.customer
        with transaction.atomic():
            customer.update_safely(mother_maiden_name=mother_maiden_name)
            process_application_status_change(
                application,
                new_status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                change_reason=JuloOneChangeReason.CUSTOMER_MOTHER_ACK,
            )

        return success_response(serializer.data)


class SelfMotherTypoCorrectionView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    serializer_class = SelfMotherTypoCorrectionSerializer
    permission_classes = (ApplicationPermission,)
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return success_response(response.data)

    def get_queryset(self):
        return Application.objects.all()

    def partial_update(self, request, *args, **kwargs):
        """Change application to x127 from x121"""

        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        application = self.get_object()
        customer = application.customer
        self.check_object_permissions(request, application)
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        serializer = self.get_serializer(application, data=request.data, partial=True)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend(f"{field}: {error}" for error in errors)
                else:
                    error_messages.append(f"{field}: {errors}")
            return general_error_response(error_messages)

        mother_maiden_name = self.request.data.get('mother_maiden_name')
        mother_name_validation = MotherNameValidation(
            application_id=application.id,
            app_version=app_version,
            mother_maiden_name=mother_maiden_name,
        )
        if not mother_name_validation.run_validation():
            return general_error_response(MotherMaidenNameConst.ERROR_MESSAGE)

        with transaction.atomic():
            customer.update_safely(mother_maiden_name=mother_maiden_name)
            process_application_status_change(
                application,
                new_status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                change_reason=JuloOneChangeReason.CUSTOMER_TYPO_MOTHER_ACK,
            )

        return success_response(serializer.data)


class BankCorrectionView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    serializer_class = SelfMotherCorrectionSerializer
    permission_classes = (ApplicationPermission,)

    def get(self, request):
        application_id = request.GET.get('application_id')
        if not application_id:
            return general_error_response("'application_id' is a required field")
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return general_error_response(
                'Application with application_id = %s is not found' % (str(application_id))
            )
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        response = {
            "mother_maiden_name": application.customer.mother_maiden_name,
            "application_id": application_id,
        }
        return success_response(response)

    def partial_update(self, request, *args, **kwargs):
        """Change application to x127 from x121"""

        application = self.get_object()
        customer = application.customer
        self.check_object_permissions(request, application)
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        serializer = self.get_serializer(customer)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend(f"{field}: {error}" for error in errors)
                else:
                    error_messages.append(f"{field}: {errors}")
            return general_error_response(error_messages)

        serializer.save()
        process_application_status_change(
            application,
            new_status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            change_reason=JuloOneChangeReason.CUSTOMER_MOTHER_ACK,
        )

        return success_response(serializer.data)


class SelfMotherTypoCorrectionView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    serializer_class = SelfMotherTypoCorrectionSerializer
    permission_classes = (ApplicationPermission,)


    def get(self, request):
        application_id = request.GET.get('application_id')
        if not application_id:
            return general_error_response("'application_id' is a required field")
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return general_error_response(
                'Application with application_id = %s is not found' % (str(application_id))
            )
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        response = {
            "mother_maiden_name": application.customer.mother_maiden_name,
            "fullname": application.fullname,
            "dob": application.dob,
            "birth_place": application.birth_place,
            "ktp": application.ktp,
            "application_id": application_id,
        }
        return success_response(response)

    def get_queryset(self):
        return Application.objects.all()

    def partial_update(self, request, *args, **kwargs):
        """Change application to x127 from x121"""

        application = self.get_object()
        customer = application.customer
        self.check_object_permissions(request, application)
        if application.status != ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL:
            return general_error_response("Application status not permitted.")

        serializer = self.get_serializer(application)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend(f"{field}: {error}" for error in errors)
                else:
                    error_messages.append(f"{field}: {errors}")
            return general_error_response(error_messages)
        serializer.save()

        with transaction.atomic():
            mother_maiden_name = serializer.data.get('mother_maiden_name', None)
            customer.update_safely(mother_maiden_name=mother_maiden_name)
            process_application_status_change(
                application,
                new_status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                change_reason=JuloOneChangeReason.CUSTOMER_TYPO_MOTHER_ACK,
            )

        return success_response(serializer.data)


class BankCorrectionView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    serializer_class = BankCorrectionSerializer
    permission_classes = (ApplicationPermission,)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return success_response(response.data)

    def get_queryset(self):
        return Application.objects.all()

    def partial_update(self, request, *args, **kwargs):
        application = self.get_object()
        self.check_object_permissions(request, application)
        if application.status != ApplicationStatusCodes.NAME_VALIDATE_FAILED:
            return general_error_response("Application status not permitted.")

        serializer = self.get_serializer(application, data=request.data, partial=True)
        if not serializer.is_valid():
            error_messages = []
            for field, errors in serializer.errors.items():
                if isinstance(errors, list):
                    error_messages.extend(f"{field}: {error}" for error in errors)
                else:
                    error_messages.append(f"{field}: {errors}")
            return general_error_response(error_messages)
        serializer.save()
        process_application_status_change(
            application,
            new_status_code=ApplicationStatusCodes.BANK_NAME_CORRECTED,
            change_reason='customer_triggered_bank_info_updated',
        )
        return success_response(serializer.data)


class InstructionVerificationDocs(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
    }

    def get(self, request, *args, **kwargs):

        user = self.request.user
        if self.request.query_params.get('type', None) not in (
            InstructionVerificationConst.PAYSLIP,
            InstructionVerificationConst.BANK_STATEMENT,
        ):
            logger.warning(
                {
                    'message': '[InstructionContent] Bad request in parameters',
                    'user_id': user.id,
                }
            )
            return general_error_response('Bad Request')

        type_param = self.request.query_params.get('type')
        content = get_instruction_verification_docs(type_param)
        if not content:
            logger.warning(
                {
                    'message': '[InstructionContent] Not found content instruction!',
                    'user_id': user.id,
                    'parameter': type_param,
                }
            )
            return not_found_response('Not found!')

        logger.info(
            {
                'message': '[InstructionContent] Success load content page',
                'user_id': user.id,
                'parameter': type_param,
            }
        )
        return success_response(content)


class DeclineHsfbpView(StandardizedExceptionHandlerMixinV2, RetrieveAPIView, UpdateAPIView):
    http_method_names = ["get", "patch"]
    lookup_field = "id"
    lookup_url_kwarg = 'application_id'
    permission_classes = (ApplicationPermission,)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return success_response(response.data)

    def get_queryset(self):
        return Application.objects.all()

    def partial_update(self, request, *args, **kwargs):
        application = self.get_object()
        self.check_object_permissions(request, application)

        success, message = decline_hsfbp_income_verification(application.id)
        if message:
            return general_error_response(message)
        return success_response()

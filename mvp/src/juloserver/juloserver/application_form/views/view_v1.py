import sys
import traceback

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotAuthenticated, AuthenticationFailed
from juloserver.application_flow.tasks import application_tag_tracking_task

from juloserver.application_form.serializers.idfy_serializer import (
    IDFyWebhookPayloadSerializer,
    IDFyChangeStatusSerializer,
)
from juloserver.julo.clients.idfy import (
    IDfyTimeout,
    IDfyProfileCreationError,
    IDfyApplicationNotAllowed,
    IDFyGeneralMessageError,
)
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_403_FORBIDDEN,
    HTTP_401_UNAUTHORIZED,
)
from rest_framework.views import APIView

from juloserver.apiv1.exceptions import ResourceNotFound
from juloserver.apiv2.constants import ErrorCode, ErrorMessage
from juloserver.apiv2.utils import failure_template, success_template
from juloserver.apiv2.views import process_application_status_change
from juloserver.apiv3.views import ApplicationUpdateV3
from juloserver.application_flow.services import (
    create_julo1_application_with_serializer,
    store_application_to_experiment_table,
)
from juloserver.application_form.serializers import (
    ApplicationSerializer,
    ReapplyApplicationSerializer,
    ReapplySerializer,
    RegionSerializer,
    AppProductPickerSerializer,
    JuloApplicationUpgradeSerializer,
    CancelApplicationSerializer,
    ReviveMTLRequestSerializer,
    EmergencyContactSerializer,
    KtpOCRResponseSerializer,
    ConfirmCustomerNIKSerializer,
    AgentAssistedWebTokenSerializer,
    ApplicationPhoneNumberRecordSerializer,
)
from juloserver.application_form.services import get_application_reapply_setting
from juloserver.application_form.services.julo_starter_service import cancel_application
from juloserver.application_form.constants import (
    JuloStarterAppCancelResponseCode,
    ApplicationReapplyFields,
    AgentAssistedSubmissionConst,
    MotherMaidenNameConst,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Application,
    Customer,
    Device,
    Mantri,
    Bank,
    MobileFeatureSetting,
)
from juloserver.julo.services import link_to_partner_if_exists
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.exceptions import ApplicationNotFound, ForbiddenError
from juloserver.julolog.julolog import JuloLog
from juloserver.pin.services import does_user_have_pin
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    general_error_response as new_general_error_response,
    not_found_response,
)
from juloserver.standardized_api_response.utils import (
    success_response,
    created_response,
    general_error_response,
    unauthorized_error_response,
    forbidden_error_response,
    request_timeout_response,
)
from juloserver.julo.services2.fraud_check import get_client_ip_from_request
from juloserver.application_form.exceptions import (
    JuloProductPickerException,
    JuloApplicationUpgrade,
)
from juloserver.application_form.services.product_picker_service import (
    proceed_select_product,
)
from juloserver.application_form.services.application_service import (
    upgrade_app_to_j1,
    stored_application_to_upgrade_table,
    create_idfy_profile,
    get_destination_page,
    get_bottomsheet,
    proceed_stored_data_mtl_application,
    determine_page_for_continue_or_video,
    is_have_approved_application,
    proceed_save_emergency_contacts,
    retrieve_application_consent_info,
    record_emergency_contact_consent,
    retrieve_ktp_ocr_result,
    confirm_customer_nik,
    validate_web_token,
    update_application_tnc,
    store_phone_number_application,
)
from juloserver.application_form.services.idfy_service import (
    process_response_from_idfy,
    get_scheduler_message_for_idfy,
)
from juloserver.application_form.services.common import parse_param
from juloserver.application_form.constants import (
    JuloStarterFormResponseCode,
    GeneralMessageResponseShortForm,
)
from juloserver.julo.constants import (
    OnboardingIdConst,
    MobileFeatureNameConst,
    IdentifierKeyHeaderAPI,
    WorkflowConst,
)

from juloserver.application_form.services.idfy_service import (
    proceed_the_status_response,
    get_ifdfy_record_result,
    get_idfy_instruction,
    process_change_status_idfy,
)
from juloserver.application_form.exceptions import IDFyException
from juloserver.pin.utils import transform_error_msg
from juloserver.application_form.decorators import verify_is_allowed_user
from juloserver.application_form.services.application_service import (
    is_user_offline_activation_booth,
    is_already_have_phone_record,
)
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.apiv4.serializers.application_serializers import AgentAssistedSubmissionSerializer
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_customer_agent_assisted,
)
from juloserver.application_form.tasks import trigger_generate_session_token_form
from juloserver.pin.decorators import parse_device_ios_user
from juloserver.application_form.services.mother_name_experiment_service import MotherNameValidation

logger = JuloLog(__name__)
julo_sentry_client = get_julo_sentry_client()


class ApplicationExceptionHanlder:
    def handle_exception(self, exc):
        """
        Handle any exception that occurs, by returning an appropriate response,
        or re-raising the error.
        """
        if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            # WWW-Authenticate header for 401 responses, else coerce to 403
            auth_header = self.get_authenticate_header(self.request)

            if auth_header:
                exc.auth_header = auth_header
            else:
                exc.status_code = HTTP_403_FORBIDDEN

        exception_handler = self.settings.EXCEPTION_HANDLER

        context = self.get_exception_handler_context()
        response = exception_handler(exc, context)

        if response is None:
            raise

        # customer error validation for company phone number
        if hasattr(response, 'data'):
            if isinstance(response.data, dict) and response.data.get('company_phone_number'):
                response.data['company_phone_number'] = [
                    """Maaf, nomor yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya"""
                ]

        response.exception = True
        return response


class ApplicationUpdate(ApplicationExceptionHanlder, ApplicationUpdateV3):
    serializer_class = ApplicationSerializer

    def check_job_and_company_phone(self):
        """Override parent method to check job and company phone."""
        data = self.request.data
        company_phone = self.request.data.get('company_phone_number', None)
        job_type = self.request.data.get('job_type', None)
        if not company_phone:
            return True, ''

        salaried = ['Pegawai swasta', 'Pegawai negeri']
        if job_type in salaried:
            related_phones = [
                data.get('mobile_phone_1'),
                data.get('mobile_phone_2'),
                data.get('kin_mobile_phone'),
                data.get('close_kin_mobile_phone'),
                data.get('spouse_mobile_phone'),
            ]
            if company_phone in related_phones:
                return False, 'Nomor telepon tidak boleh sama dengan nomor yang lain'

        return True, ''

    def update(self, request, *args, **kwargs):
        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        onboarding_id = request.data.get('onboarding_id')
        # check data onboarding_id is correct
        if onboarding_id and not self.check_allowed_onboarding(onboarding_id):
            return new_general_error_response(OnboardingIdConst.MSG_NOT_ALLOWED)

        if not self.check_liveness():
            return new_general_error_response(
                'Cek kembali halaman selfie dan ambil ulang foto kamu'
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get('mobile_phone_1') and not self.check_validated_otp(
            request.data.get('mobile_phone_1')
        ):
            logger.warning(
                {
                    "message": "Mismatch in mobile phone number",
                    "process": "check_validated_otp",
                    "data": str(serializer.validated_data),
                    "app_version": app_version,
                    "application": instance.id,
                }
            )
            return new_general_error_response(ErrorMessage.PHONE_NUMBER_MISMATCH)

        self.claim_customer(instance, request.data)
        is_valid_company_phone, check_company_phone_message = self.check_job_and_company_phone()
        if not is_valid_company_phone:
            error = APIException(format(str(check_company_phone_message)))
            error.status_code = 400
            raise error

        self.perform_update(serializer, app_version=app_version)

        return Response(serializer.data)

    @staticmethod
    def claim_customer(application, request_data):
        """
        When customer goes to change the apk, from old to new one, or from new to old one in the
        middle of registration it will make an trash data. So we must claim the trash data into
        new one.
        """

        from juloserver.application_form.services import ClaimError

        application_customer = application.customer

        try:
            from juloserver.application_form.services.claimer_service import (
                ClaimerService,
            )

            (ClaimerService(customer=application_customer)).claim_using(
                nik=request_data.get('ktp'), email=request_data.get('email')
            ).on_module(sys.modules[__name__])

        except ClaimError as e:
            message = e.message if hasattr(e, 'message') else e
            logger.info(
                {
                    'mark': 'ClaimError',
                    'application_id': application.id,
                    'customer_id': application_customer.id,
                    'message': message,
                }
            )


class RegionCheck(RetrieveAPIView):
    def get(self, request, *args, **kwargs):
        from juloserver.apiv3.models import SubDistrictLookup
        from juloserver.standardized_api_response.utils import success_response

        province = request.GET.get('province', '')
        city = request.GET.get('city', '')
        district = request.GET.get('district', '')
        sub_district = request.GET.get('sub-district', '')

        # First check from sub_district if the name is unique
        sub_district_cnt = SubDistrictLookup.objects.filter(
            sub_district__iexact=sub_district, is_active=True
        ).count()
        if sub_district_cnt == 1:
            sub_district = (
                SubDistrictLookup.objects.select_related('district__city__province')
                .filter(sub_district__iexact=sub_district, is_active=True)
                .first()
            )

            return success_response(
                RegionSerializer(
                    {
                        'province': sub_district.district.city.province.province,
                        'city': sub_district.district.city.city,
                        'district': sub_district.district.district,
                        'sub_district': sub_district.sub_district,
                        'zipcode': sub_district.zipcode,
                    }
                ).data
            )

        province_response = None
        city_response = None
        district_response = None
        sub_district_response = None
        zipcode_response = None

        from juloserver.apiv3.models import ProvinceLookup

        province_response = ProvinceLookup.objects.filter(
            province__iexact=province, is_active=True
        ).first()

        if province_response is not None:
            from juloserver.apiv3.models import CityLookup

            province_response = province_response.province
            city_response = CityLookup.objects.filter(city__iexact=city, is_active=True).first()

        if city_response is not None:
            from juloserver.apiv3.models import DistrictLookup

            city_response = city_response.city
            district_response = DistrictLookup.objects.filter(
                district__iexact=district, is_active=True
            ).first()

        if district_response is not None:
            district_response = district_response.district
            sub_district_response = SubDistrictLookup.objects.filter(
                sub_district__iexact=sub_district, is_active=True
            ).first()

        if sub_district_response is not None:
            zipcode_response = sub_district_response.zipcode
            sub_district_response = sub_district_response.sub_district

        return success_response(
            RegionSerializer(
                {
                    'province': province_response,
                    'city': city_response,
                    'district': district_response,
                    'sub_district': sub_district_response,
                    'zipcode': zipcode_response,
                }
            ).data
        )


class ApplicationPrecheckReapply(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        mfs = get_application_reapply_setting()

        parameters = {"ktp": False}

        if mfs:
            parameters = mfs.parameters['editable']

        data = {'editable': parameters}

        return success_response(data)

    def post(self, request):
        customer = request.user.customer
        mfs = get_application_reapply_setting()
        detokenized_customers = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenized_customers[0]

        parameters = {"ktp": False, "phone": False}

        if mfs:
            parameters = mfs.parameters['editable']

        if customer:
            parameters['phone'] = False if customer.phone else True

        data = {'editable': parameters}

        return success_response(data)


class ApplicationReapply(APIView):
    model_class = Application
    serializer_class = ReapplySerializer

    @parse_device_ios_user
    @verify_is_allowed_user
    def post(self, request, *args, **kwargs):
        request_data = self.serializer_class(data=request.data)
        request_data.is_valid()
        customer = request.user.customer

        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        ios_id = device_ios_user['ios_id'] if device_ios_user else None

        # prevent to hit this endpoint if have x190 status
        if is_have_approved_application(customer):
            logger.error(
                {
                    'message': 'Application already have x190, but do reapply',
                    'customer': customer.id,
                }
            )
            return new_general_error_response(ErrorMessage.GENERAL)

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

        last_application_number = last_application.application_number
        if not last_application_number:
            last_application_number = 1
        application_number = last_application_number + 1

        data_to_save = {'application_number': application_number}

        # check duration
        today = timezone.now().date()
        date_apply = last_application.cdate.date()
        day_range = (today - date_apply).days

        # detokenize data
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

        for field in ApplicationReapplyFields.JULO_ONE:
            data_to_save[field] = getattr(last_application, field)

        bank_name = data_to_save['bank_name']
        if not Bank.objects.regular_bank().filter(bank_name=bank_name).last():
            data_to_save['bank_name'] = None
            data_to_save['bank_account_number'] = None

        serializer = ReapplyApplicationSerializer(data=data_to_save)
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

                workflow_name = WorkflowConst.JULO_ONE if not ios_id else WorkflowConst.JULO_ONE_IOS
                application = create_julo1_application_with_serializer(
                    serializer=serializer,
                    customer=last_application.customer,
                    device=device,
                    app_version=app_version,
                    web_version=web_version,
                    onboarding_id=last_application.onboarding_id,
                    workflow_name=workflow_name,
                )

                if not application.onboarding_id and ios_id:
                    logger.info(
                        {
                            'message': 'Onboarding ID is null from latest application, '
                            'set to 3 OnboardingID',
                            'application_id': application.id,
                        }
                    )
                    application.update_safely(
                        onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID,
                    )

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

                        # condition for offline activation booth
                        is_user_offline_activation_booth(referral_code, application.id)

                        mantri_obj = Mantri.objects.get_or_none(code__iexact=referral_code)
                        application.mantri = mantri_obj
                        application.save(update_fields=['mantri'])

                link_to_partner_if_exists(application)
                store_application_to_experiment_table(application, 'ExperimentUwOverhaul')

                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_CREATED,
                    change_reason='customer_triggered',
                )

                # update reapply value after creating new application
                customer.can_reapply = False
                customer.save()

            create_application_checklist_async.delay(application.id)
            application.refresh_from_db()

            # init application upgrade
            stored_application_to_upgrade_table(application)

            # run experiment for mother maiden Name
            if not device_ios_user:
                mother_name_validation = MotherNameValidation(
                    application_id=application.id, app_version=app_version, mother_maiden_name=None
                )
                mother_name_validation.run()

            final_response = serializer.data.copy()
            final_response['onboarding_id'] = application.onboarding_id

            return Response(success_template(final_response))
        except Exception:
            julo_sentry_client.captureException()
            return Response(failure_template(ErrorCode.CUSTOMER_REAPPLY, ErrorMessage.GENERAL))


class ApplicationCancelation(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {'log_data': ['request', 'response']}
    serializer_class = CancelApplicationSerializer

    def post(self, request):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data
            result, data = cancel_application(customer, validated_data)
        except Exception as e:
            return general_error_response(str(e))

        if result == JuloStarterAppCancelResponseCode.APPLICATION_NOT_FOUND:
            return not_found_response(message=data)
        if result == JuloStarterFormResponseCode.APPLICATION_NOT_ALLOW:
            return forbidden_error_response(message=data)

        return success_response(data)


class ApplicationProductPicker(StandardizedExceptionHandlerMixinV2, APIView):
    # capture request and response as logging
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = AppProductPickerSerializer
    exclude_raise_error_sentry_in_status_code = {HTTP_401_UNAUTHORIZED}

    @verify_is_allowed_user
    def post(self, request):
        user = self.request.user
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        if 'customer_id' not in validated_data:
            validated_data['customer_id'] = user.customer.id

        if user.customer.id != validated_data['customer_id']:
            logger.warning(
                {
                    "message": "Not match between customer token and parameter",
                    "customer_token": user.customer.id,
                    "customer_param": validated_data['customer_id'],
                },
                request=request,
            )
            return unauthorized_error_response("Unauthorized request")

        app_version = request.META.get('HTTP_X_APP_VERSION')
        if not app_version:
            logger.error(
                {
                    "message": "App version is required",
                    "app_version": app_version,
                    "process": "product_picker",
                    "data": str(serializer.data),
                },
                request=request,
            )
            return general_error_response('Request invalid')

        validated_data['app_version'] = app_version
        validated_data['ip_address'] = get_client_ip_from_request(request)
        try:
            const = GeneralMessageResponseShortForm
            new_application, response = proceed_select_product(validated_data)

            if new_application:
                return created_response(response)
            else:
                if const.key_name_flag in response:
                    return general_error_response(response.get(const.key_name_message))

                return success_response(response)
        except JuloProductPickerException as error:
            error_msg = str(error)
            logger.error(
                {
                    "message": error_msg,
                    "customer": validated_data['customer_id'],
                    "action": "application_product_picker",
                },
                request=request,
            )
            return general_error_response(error_msg)

    def get(self, request):
        fs = MobileFeatureSetting.objects.filter(
            feature_name='dynamic_product_picker', is_active=True
        ).last()
        if not fs:
            return not_found_response("Feature setting not found.")

        return success_response(fs.parameters)


class ApplicationUpgrade(StandardizedExceptionHandlerMixinV2, APIView):
    # capture request and response as logging
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    @parse_param(serializer_class=JuloApplicationUpgradeSerializer)
    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        if not customer:
            return unauthorized_error_response('User not allowed')

        if str(customer.id) != str(kwargs['validated_data']['customer_id']):
            error_message = 'User not allowed'
            logger.warning({'message': error_message, 'customer': customer.id})
            return forbidden_error_response(error_message)

        try:
            kwargs['validated_data']['ip_address'] = get_client_ip_from_request(request)
            response = upgrade_app_to_j1(customer, kwargs['validated_data'])

            return created_response(response)
        except JuloApplicationUpgrade as error:
            return general_error_response(str(error))


class CreateProfileRequest(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        customer = request.user.customer

        if not customer:
            return unauthorized_error_response('User not allowed')

        try:
            url, profile_id = create_idfy_profile(customer)
        except IDfyProfileCreationError as e:
            logger.warning(
                "IDfyProfileCreationError on create_profile for : {} due to : {}".format(
                    customer, str(e)
                )
            )
            return general_error_response(str(e))
        except IDfyTimeout as e:
            logger.warning(
                "IDfyTimeout on create_profile for : {} due to : {}".format(customer, str(e))
            )
            return request_timeout_response(str(e))
        except IDfyApplicationNotAllowed as e:
            logger.warning(
                "Application for this customer not allowed for idfy : {} due to : {}".format(
                    customer, str(e)
                )
            )
            return forbidden_error_response(str(e))
        except IDFyGeneralMessageError as e:
            return general_error_response(str(e))
        except Exception as e:
            logger.warning(
                "Exception on create_profile for : {} due to : {}".format(customer, str(e))
            )
            return general_error_response(str(e))

        if url is None and profile_id is None:
            return unauthorized_error_response('Video call session expired')

        response_data = {
            "video_call_url": url,
            "profile_id": profile_id,
        }

        return success_response(response_data)


class ApplicationCallbackFromIDFy(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []

    # capture request and response as logging
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request, *args, **kwargs):
        data = request.data
        try:
            proceed_the_status_response(data)

        except IDFyException as error:
            logger.error(
                {
                    'message': str(error),
                    'data': str(data),
                },
                request=request,
            )

            return general_error_response(str(error))

        return success_response(data='successfully')


class ApplicationResultFromIDFy(StandardizedExceptionHandlerMixinV2, APIView):
    # capture request and response as logging
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request, application_id):
        try:
            data = get_ifdfy_record_result(request.user.customer.id, application_id)
        except ApplicationNotFound:
            return not_found_response("Application not found")
        except ForbiddenError:
            return forbidden_error_response("User not allowed!")

        return success_response(data=data)

    def post(self, request, application_id):
        serializer = IDFyChangeStatusSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error(
                {
                    'message': 'serializers error',
                    'data': str(serializer.errors),
                    'application': application_id,
                }
            )
            return general_error_response('Mohon maaf terjadi kesalahan')

        validated_data = serializer.validated_data
        validated_data['application_id'] = application_id
        customer = request.user.customer
        try:
            result, destination_page = process_change_status_idfy(customer.id, validated_data)
        except ApplicationNotFound:
            return not_found_response("Application not found")
        except ForbiddenError:
            return forbidden_error_response("User not allowed!")
        except IDFyException as error:
            return general_error_response(str(error))

        if not result:
            return general_error_response('Mohon maaf terjadi kesalahan')

        response = serializer.initial_data
        response['destination_page'] = (
            destination_page if destination_page else determine_page_for_continue_or_video(customer)
        )
        return success_response(data=serializer.initial_data)


class IdfyInstructionPage(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        content = get_idfy_instruction()
        if not content:
            return not_found_response('Not found!')

        return success_response(content)


class IDFySessionWebhookView(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []
    # Logging configuration
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def validate_request(self, payload):
        required_fields = ["profile_id", "reference_id", "status", "session_status"]
        for field in required_fields:
            if field not in payload:
                return False
        return True

    def post(self, request):
        serializer = IDFyWebhookPayloadSerializer(data=request.data)

        if not serializer.is_valid():
            return general_error_response("Invalid request")

        validated_data = serializer.validated_data

        response_bool = process_response_from_idfy(
            validated_data.get("profile_id"),
            validated_data.get("reference_id"),
            validated_data.get("status"),
            validated_data.get("session_status"),
        )
        if not response_bool:
            return general_error_response("Invalid request")

        return success_response(data="Success")


class ApplicationDestinationPage(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        """
        This endpoint to get direction customer go to Home or Product Picker
        """

        customer = request.user.customer
        page = get_destination_page(customer)
        if not page:
            general_error_response('Invalid request')

        response = {
            'destination_page': page,
        }
        return success_response(response)


class BottomSheetContents(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        user = request.user
        customer = user.customer if user else None

        if not customer:
            return unauthorized_error_response('User not allowed')

        fs = MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.BOTTOMSHEET_CONTENT_PRODUCT_PICKER, is_active=True
        ).last()
        if not fs:
            return not_found_response("No bottomsheet setting found.")

        response = get_bottomsheet(fs)

        return success_response(response)


class ApplicationFormMTL(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = ReviveMTLRequestSerializer

    def post(self, request):
        """
        This endpoint to accept data from WebForm with target MTL Customers
        """

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            logger.error({'message': 'serializers error', 'data': str(serializer.errors)})
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        validated_data = serializer.validated_data
        julo_mtl_form = request.data.get('julo_mtl_form', None)
        is_success, message = proceed_stored_data_mtl_application(validated_data, julo_mtl_form)
        if not is_success:
            return general_error_response(message)

        return success_response(data=serializer.initial_data)


class EmergencyContactForm(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = EmergencyContactSerializer

    def post(self, request):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            logger.error(
                {
                    'message': 'serializers error',
                    'data': str(serializer.errors),
                }
            )
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        validated_data = serializer.validated_data

        try:
            is_success, message, response_data = proceed_save_emergency_contacts(
                customer, validated_data
            )
        except Exception as e:
            return general_error_response(str(e))

        if not is_success:
            return general_error_response(message)
        return success_response(data=response_data)


class EmergencyContactConsentForm(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request, *args, **kwargs):
        code = request.GET.get('data', None)
        if not code:
            return general_error_response('No data provided')
        is_success, response = retrieve_application_consent_info(code)
        if not is_success:
            return general_error_response(response)

        return success_response(data=response)

    def post(self, request):
        application_xid = request.data.get('application_xid')
        consent_response = request.data.get('consent_response')
        if not application_xid:
            return general_error_response('No application info provided')
        is_success, response = record_emergency_contact_consent(application_xid, consent_response)
        if not is_success:
            return general_error_response(response)

        return success_response()


class RetrieveOCRResult(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request, application_id):
        user = request.user
        customer = user.customer if user else None
        if not customer:
            return unauthorized_error_response('User not allowed')
        is_success, ocr_result, message = retrieve_ktp_ocr_result(customer, application_id)
        if not is_success:
            return general_error_response(message)

        serializer = KtpOCRResponseSerializer(ocr_result)
        return success_response(serializer.data)


class ConfirmCustomerNIK(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    serializer_class = ConfirmCustomerNIKSerializer

    def post(self, request, application_id):
        user = request.user
        customer = user.customer if user else None
        if not customer:
            return unauthorized_error_response('User not allowed')

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            logger.error(
                {
                    'message': 'serializers error',
                    'data': str(serializer.errors),
                    'customer_id': customer.id,
                }
            )
            return general_error_response('NIK yang anda masukkan tidak valid')

        validated_data = serializer.validated_data
        is_success, message = confirm_customer_nik(customer, validated_data, application_id)

        if not is_success:
            return general_error_response(message)

        data = {
            'nik': validated_data['nik'],
        }

        return success_response(data)


class VideoCallAvailabilityView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request):
        user = request.user
        customer = user.customer if user else None

        if not customer:
            return unauthorized_error_response('User not allowed')

        dynamic_configuration = get_scheduler_message_for_idfy()
        response = {
            'is_available': dynamic_configuration['is_available'],
            'is_need_submit_phone_number': not is_already_have_phone_record(customer.id),
            'message': dynamic_configuration['message'],
            'title': dynamic_configuration['title'],
            'button_message': dynamic_configuration['button_message'],
        }

        return success_response(response)


class AgentAssistedApplicationUpdate(ApplicationUpdateV3):
    serializer_class = AgentAssistedSubmissionSerializer

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get_application_instance(self, application_id):
        return Application.objects.filter(id=application_id).last()

    def update(self, request, *args, **kwargs):
        user = request.user
        if not user or not user.groups.filter(name=JuloUserRoles.J1_AGENT_ASSISTED_100).exists():
            return unauthorized_error_response('Agent ini tidak diperbolehkan melakukan submission')

        instance = self.get_application_instance(kwargs.get('pk'))
        if not instance:
            return new_general_error_response('Aplikasi tidak ditemukan')
        if instance.application_status_id != ApplicationStatusCodes.FORM_CREATED:
            return new_general_error_response('Aplikasi harus di status x100')
        data = request.data

        onboarding_id = (
            data.get('onboarding_id') if data.get('onboarding_id') else instance.onboarding_id
        )
        if not onboarding_id or onboarding_id not in [OnboardingIdConst.LONGFORM_SHORTENED_ID]:
            return new_general_error_response(OnboardingIdConst.MSG_NOT_ALLOWED)

        is_longform_shortened = True
        detokenize_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': instance.customer.customer_xid,
                    'object': instance,
                }
            ],
            force_get_local_data=True,
        )
        instance = detokenize_applications[0]
        serializer = self.get_serializer(instance, data=data, partial=True)
        if not serializer.is_valid():

            logger.warning(
                {
                    "action": "agent_assisted_application_update",
                    "message": str(serializer.errors),
                    "process": "serializer check validation",
                    "data": str(request.data),
                    "application": instance.id,
                },
                request=request,
            )
            return new_general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True, strict_mode=True)[0]
            )

        if not self.check_liveness(instance) or not self.check_selfie_submission(instance):
            error_message = "Customer belum melakukan cek liveness atau foto selfie"
            logger.warning(
                {
                    "action": "agent_assisted_application_update",
                    "message": error_message,
                    "application": instance.id,
                },
                request=request,
            )
            return new_general_error_response(error_message)

        self.claim_customer(instance, request.data)
        if not self.check_job_and_company_phone():
            job_type = self.request.data.get('job_type', None)
            message = 'Jika pekerjaan ' + job_type + ', nomor telepon kantor tidak boleh GSM'
            error = APIException(format(str(message)))
            error.status_code = 400
            logger.warning(
                {
                    "action": "agent_assisted_application_update",
                    "message": str(message),
                    "process": "check_job_and_company_phone",
                    "data": str(serializer.validated_data),
                    "application": instance.id,
                    "is_upgrade": logger,
                },
                request=request,
            )
            return new_general_error_response(message)

        # set path tag
        application_tag_tracking_task(
            instance.id,
            None,
            None,
            None,
            AgentAssistedSubmissionConst.TAG_NAME,
            AgentAssistedSubmissionConst.SUCCESS_VALUE,
            traceback.format_stack(),
        )

        try:

            self.perform_update(
                serializer, longform_shortened=is_longform_shortened, customer=instance.customer
            )
        except Exception as err:
            logger.warning(
                {
                    "action": "agent_assisted_application_update",
                    "process": "check_job_and_company_phone",
                    "data": str(serializer.validated_data),
                    "application": instance.id,
                    "message": str(err),
                },
                request=request,
            )
            return new_general_error_response("Proses update gagal karena terjadi kesalahan")

        self._post_application_submit(serializer, instance.customer.id)
        self._trigger_process_for_tnc_application(instance.id)

        logger.info(
            {
                "action": "agent_assisted_application_update",
                "message": "Capture submission data after perform update",
                "process": "AFTER_PERFORM_UPDATE submission data",
                "data": str(serializer.data),
                "application": instance.id,
            },
            request=request,
        )

        return success_response(serializer.data)

    @staticmethod
    def _trigger_process_for_tnc_application(application_id):

        # Create session token
        trigger_generate_session_token_form.delay(application_id)

        # Trigger notification customer for tnc approval in 5 minutes
        send_user_attributes_to_moengage_for_customer_agent_assisted.apply_async(
            (application_id,), countdown=5 * 60
        )


class SalesOpsTermsAndConditionView(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = []
    authentication_classes = []
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    serializer_class = AgentAssistedWebTokenSerializer

    def get(self, request, *args, **kwargs):
        """
        Check if the user has accepted the terms and conditions
        """
        token = request.query_params.get('token')
        application_xid = request.query_params.get('application_xid')

        if not all([token, application_xid]):
            return new_general_error_response("Data tidak lengkap")

        application = Application.objects.filter(
            application_xid=application_xid,
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        ).first()

        if not application or not application.is_agent_assisted_submission():
            return new_general_error_response("Aplikasi salah")

        is_already_approved = application.is_term_accepted and application.is_verification_agreed
        if is_already_approved:
            logger.info(
                {
                    'message': 'User has not accepted the terms and conditions',
                    'action': 'SalesOpsTermsAndConditionView',
                    'application_xid': application_xid,
                }
            )

        is_token_valid, new_token = validate_web_token(application_xid, token)
        if not is_token_valid:
            return new_general_error_response(
                "Your token is not valid", data={'is_already_approved': None, 'token': new_token}
            )

        return success_response(data={'is_already_approved': is_already_approved, 'token': None})

    def post(self, request):
        """
        Validate and save the user's acceptance of the terms and conditions
        """
        message = 'Token tidak valid'

        data = request.data
        if not data.get('token') or not data.get('application_xid'):
            return new_general_error_response("Data tidak lengkap")

        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            logger.error(
                {
                    'message': 'serializers error',
                    'data': str(serializer.errors),
                    'application_xid': data.get('application_xid', None),
                }
            )
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        validated_data = serializer.validated_data
        is_token_valid, new_token = validate_web_token(
            validated_data.get('application_xid'), validated_data.get('token')
        )
        if is_token_valid:
            is_success, message = update_application_tnc(validated_data)
            if is_success:
                return success_response()

        return general_error_response(message)


class ApplicationPhoneNumberSubmitView(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = ApplicationPhoneNumberRecordSerializer

    def post(self, request):
        user = request.user
        customer_token = user.customer if user else None

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0]
            )

        validated_data = serializer.validated_data
        is_success, message = store_phone_number_application(validated_data, customer_token)
        if not is_success:
            return general_error_response(message)

        return success_response(message)


class MotherMaidenNameSettingView(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request, application_id):

        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        service_validation = MotherNameValidation(
            application_id=application_id,
            app_version=app_version,
            mother_maiden_name=None,
        )
        improper_names = service_validation.check_and_get_improper_names()

        response = {MotherMaidenNameConst.KEY_IMPROPER_NAMES: []}
        if not improper_names:
            return success_response(response)

        response[MotherMaidenNameConst.KEY_IMPROPER_NAMES] = improper_names
        return success_response(response)

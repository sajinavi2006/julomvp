from builtins import str
from copy import deepcopy

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.status import HTTP_200_OK

from django.template.loader import render_to_string
from juloserver.apiv4.serializers.application_serializers import ApplicationUpdateSerializerV4
from juloserver.apiv3.views import ApplicationUpdateV3, DeviceScrapedDataUploadV3
from juloserver.apiv3.constants import DeviceScrapedConst
from juloserver.apiv3.services.dsd_service import (
    run_and_check_customer_app_action,
    get_structure_initiate_dsd,
)
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.apiv2.constants import ErrorMessage
from juloserver.julolog.julolog import JuloLog
from juloserver.pin.utils import transform_error_msg
from juloserver.application_form.constants import (
    ApplicationJobSelectionOrder,
)
from juloserver.application_flow.services import ApplicationTagTracking
from juloserver.julo.constants import OnboardingIdConst
from juloserver.application_form.services.application_service import do_check_and_copy_data_approved
from juloserver.apiv4.services.application_service import is_passed_checking_email
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource
from juloserver.pin.decorators import parse_device_ios_user
from juloserver.application_form.constants import MotherMaidenNameConst
from juloserver.application_form.services.common import build_additional_message

julolog = JuloLog(__name__)


class TermsConditionAndPrivacyNotice(APIView):
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        """return terms condition and privacy notice"""
        terms_and_condition = render_to_string("terms_and_condition_v4.html")
        privacy_notice = render_to_string("privacy_notice_v4.html")
        response_data = {
            "terms_and_condition": terms_and_condition,
            "privacy_notice": privacy_notice,
        }
        return success_response(response_data)


class ApplicationUpdateV4(ApplicationUpdateV3):
    serializer_class = ApplicationUpdateSerializerV4

    def update(self, request, *args, **kwargs):

        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        # detokenize
        detokenized_applications = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [
                {
                    'customer_xid': instance.customer.customer_xid,
                    'object': instance,
                }
            ],
            force_get_local_data=True,
        )
        instance = detokenized_applications[0]

        request_data = request.data.copy()

        application_path_tag = request_data.get('application_path_tag')
        if application_path_tag and application_path_tag not in (
            ApplicationJobSelectionOrder.FIRST,
            ApplicationJobSelectionOrder.SECOND,
            ApplicationJobSelectionOrder.THIRD,
            ApplicationJobSelectionOrder.FOURTH,
            ApplicationJobSelectionOrder.FIFTH,
            ApplicationJobSelectionOrder.SIXTH,
            ApplicationJobSelectionOrder.SEVENTH,
            ApplicationJobSelectionOrder.EIGHTH,
        ):
            return general_error_response('application_path_tag is invalid')

        onboarding_id = request_data.get('onboarding_id')
        # check data onboarding_id is correct
        if onboarding_id and not self.check_allowed_onboarding(onboarding_id):
            return general_error_response(OnboardingIdConst.MSG_NOT_ALLOWED)

        # to define data from LFS (LongForm Shortened)
        is_upgrade = request_data.get('is_upgrade')
        if str(is_upgrade).lower() != 'true':
            error_message_general = 'Bad request'
            if 'latitude' not in request_data:
                julolog.error(
                    {'message': 'Bad request latitude is mandatory', 'application_id': instance.id},
                    request=request,
                )
                return general_error_response(error_message_general)

            if 'longitude' not in request_data:
                julolog.error(
                    {
                        'message': 'Bad request longitude is mandatory',
                        'application_id': instance.id,
                    },
                    request=request,
                )
                return general_error_response(error_message_general)

        # run process for upgrade flow check and copy
        do_check_and_copy_data_approved(
            target_application_id=instance.id,
            is_upgrade=is_upgrade,
        )

        if not self.check_liveness() or not self.check_selfie_submission():
            error_message = "Cek kembali halaman selfie dan ambil ulang foto kamu"
            julolog.warning(
                {"message": error_message, "application": instance.id, "app_version": app_version},
                request=request,
            )
            return general_error_response(error_message)

        mother_maiden_name = self.request.data.get('mother_maiden_name', None)
        if not self.is_validated_mother_maiden_name(
            application_id=instance.id,
            app_version=app_version,
            mother_maiden_name=mother_maiden_name,
        ):
            julolog.warning(
                {'message': '[MotherMaidenName] is not valid', 'application_id': instance.id}
            )
            additional_message = build_additional_message(
                app_version=app_version,
                title='Nama lengkap ibu kandung tidak sesuai',
                message=MotherMaidenNameConst.ERROR_MESSAGE,
                button_text='Perbaiki',
            )
            if additional_message:
                return general_error_response(
                    message=MotherMaidenNameConst.ERROR_MESSAGE, data=additional_message
                )

            return general_error_response(MotherMaidenNameConst.ERROR_MESSAGE)

        # mobile_phone_1 is immutable for julo360
        if instance.is_julo_360():
            request_data.pop('mobile_phone_1', None)

        is_longform_shortened = self.check_is_longform_shortened(request_data)
        serializer = self.get_serializer(instance, data=request_data, partial=partial)

        if not serializer.is_valid():
            julolog.warning(
                {
                    "message": str(serializer.errors),
                    "process": "serializer check validation",
                    "data": str(request_data),
                    "app_version": app_version,
                    "application": instance.id,
                    "is_upgrade": is_upgrade,
                },
                request=request,
            )
            serializer_errors = serializer.errors
            if isinstance(serializer_errors, dict) and serializer_errors.get(
                'company_phone_number'
            ):
                serializer_errors = deepcopy(serializer_errors)
                serializer_errors['company_phone_number'] = [
                    'Maaf, nomor telepon perusahaan yang kamu masukkan tidak valid. '
                    'Mohon masukkan nomor lainnya.'
                ]
            return general_error_response(
                transform_error_msg(serializer_errors, exclude_key=True)[0]
            )
        if (
            not instance.is_julo_360()
            and serializer.validated_data.get('mobile_phone_1')
            and not self.check_validated_otp(request_data.get('mobile_phone_1'))
        ):
            julolog.warning(
                {
                    "message": "Mismatch in mobile phone number",
                    "process": "check_validated_otp",
                    "data": str(serializer.validated_data),
                    "app_version": app_version,
                    "application": instance.id,
                    "is_upgrade": is_upgrade,
                }
            )
            return general_error_response(ErrorMessage.PHONE_NUMBER_MISMATCH)

        self.claim_customer(instance, request_data)

        # ---------
        # We disabled this validation to allow mobile phone number in company phone
        # Refer this ticket: https://juloprojects.atlassian.net/browse/RUS1-3403
        # ---------
        # if not self.check_job_and_company_phone():
        #     job_type = self.request.data.get('job_type', None)
        #     message = 'Jika pekerjaan ' + job_type + ', nomor telepon kantor tidak boleh GSM'
        #     error = APIException(format(str(message)))
        #     error.status_code = 400
        #     julolog.warning(
        #         {
        #             "message": str(message),
        #             "process": "check_job_and_company_phone",
        #             "data": str(serializer.validated_data),
        #             "app_version": app_version,
        #             "application": instance.id,
        #             "is_upgrade": is_upgrade,
        #         },
        #         request=request,
        #     )
        #     raise error

        email = serializer.validated_data.get('email')
        application = instance
        if not is_passed_checking_email(application, onboarding_id, email):
            julolog.warning(
                {
                    "message": "Email already registered",
                    "process": "is_exist_email_customer",
                    "data": str(serializer.validated_data),
                    "application": application.id,
                    "is_upgrade": is_upgrade,
                },
                request=request,
            )
            return general_error_response(
                'Email yang Anda masukkan telah terdaftar. Mohon gunakan email lain'
            )

        # check for upgrade payload should be correct
        message_upgrade, checker_is_upgrade = self.check_is_upgrade_application(
            serializer, is_upgrade
        )
        if not checker_is_upgrade:
            julolog.error(
                {
                    "message": message_upgrade,
                    "process": "check is upgrade application",
                    "data": str(request_data),
                    "app_version": app_version,
                    "application": instance.id,
                    "is_upgrade": is_upgrade,
                },
                request=request,
            )
            return general_error_response(message_upgrade)

        julolog.info(
            {
                "message": "[v4] Capture submission data before perform update",
                "process": "BEFORE_PERFORM_UPDATE submission data",
                "data": str(serializer.validated_data),
                "app_version": app_version,
                "application": instance.id,
                "is_upgrade": is_upgrade,
            },
            request=request,
        )

        self.perform_update(serializer, is_longform_shortened, app_version)

        # add application path tag for job order selection
        if application_path_tag:
            instance.refresh_from_db()
            tag_tracer = ApplicationTagTracking(instance, 100, 105)
            tag_tracer.adding_application_path_tag(application_path_tag, 0)

        # Trigger optional process after the application is updated.
        self._post_application_submit(serializer)

        return Response(serializer.data)


class DeviceScrapedDataUploadV4(DeviceScrapedDataUploadV3, APIView):
    """
    Endpoint for uploading DSD to anaserver for ios and android
    """

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        device_ios_user = kwargs.get('device_ios_user', {})
        if not device_ios_user.get('ios_id'):
            return super().post(request)  # Call V3 logic for non-iOS requests

        process_name = DeviceScrapedConst.PROCESS_NAME
        customer = request.user.customer

        # Validate application ID
        try:
            application_id = self.validate_application(request, customer, process_name)
        except ValidationError as error:
            return Response({"error": error.detail}, status=400)

        url = request.build_absolute_uri()
        json_forward = request.data
        response = run_and_check_customer_app_action(
            customer, application_id, url, json_forward, is_ios_device=True
        )

        if response.status_code != HTTP_200_OK:
            return general_error_response('Error occurred during iOS data upload.')

        structure_initiate = get_structure_initiate_dsd(application_id)  # V4-specific structure
        return success_response(data=structure_initiate)

    def validate_application(self, request, customer, process_name):
        """
        Validates the application ID for the V4 process.
        Raises ValidationError if validation fails.
        """
        if 'application_id' not in request.data:
            julolog.warning(
                {
                    'message': 'Application is required',
                    'process_name': process_name,
                },
                request=request,
            )
            raise ValidationError('Application is required')

        application_id = int(request.data['application_id'])
        if application_id == 0:
            application = customer.application_set.last()
            if application:
                application_id = application.id

        user_applications = customer.application_set.values_list('id', flat=True)
        if application_id not in user_applications:
            julolog.warning(
                {
                    'message': 'Invalid case: application not found',
                    'process_name': process_name,
                    'application_id': application_id,
                },
                request=request,
            )
            raise ValidationError('Application not found')

        julolog.info(
            {
                'message': 'Validated application ID',
                'application_id': application_id,
                'process_name': process_name,
            },
            request=request,
        )
        return application_id

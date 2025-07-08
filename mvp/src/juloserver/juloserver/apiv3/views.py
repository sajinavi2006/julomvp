"""
views.py
new api v3
"""

import csv
import logging

from builtins import str
from datetime import datetime
from copy import deepcopy

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import get_template
from rest_framework.exceptions import APIException
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from rest_framework.permissions import IsAuthenticated

from juloserver.apiv2.serializers import (
    AdditionalInfoSerializer,
)
from juloserver.apiv2.constants import ErrorMessage
from juloserver.apiv2.views import ApplicationUpdate
from juloserver.apiv3.serializers import (
    AppsflyerSerializer,
    ApplicationUpdateSerializerV3,
)
from juloserver.face_recognition.constants import ImageType
from juloserver.julo.models import (
    Bank,
    Customer,
    Device,
    DeviceGeolocation,
    FrontendView,
    Image,
    MobileFeatureSetting,
    OtpRequest,
    FaqFeature,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julolog.julolog import JuloLog
from juloserver.liveness_detection.constants import LivenessCheckStatus
from juloserver.liveness_detection.models import ActiveLivenessDetection
from juloserver.paylater.utils import general_error_response, success_response
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    general_error_response as new_general_error_response,
    not_found_response,
    success_response as new_success_response,
)
from juloserver.pin.utils import transform_error_msg

from .models import CityLookup, DistrictLookup, ProvinceLookup, SubDistrictLookup
from .serializers import (
    AddressInfoSerializer,
    DeviceGeolocationSerializer,
    SubDistrictLookupReqSerializer,
    SubDistrictLookupResSerializer,
)
from juloserver.fraud_score.tasks import handle_post_user_submit_application
from juloserver.julocore.decorators import silent_exception
from juloserver.julocore.utils import get_client_ip
from juloserver.application_form.constants import (
    ApplicationUpgradeConst,
    ApplicationJobSelectionOrder,
)
from juloserver.application_form.services.application_service import check_phone_number_is_used
from juloserver.application_form.models.idfy_models import IdfyVideoCall
from juloserver.application_flow.services import ApplicationTagTracking
from juloserver.otp.constants import SessionTokenAction, FeatureSettingName
from juloserver.apiv3.constants import DeviceScrapedConst
from juloserver.apiv3.services.dsd_service import (
    run_and_check_customer_app_action,
    get_structure_initiate_dsd,
    proceed_request_clcs_dsd,
)
from juloserver.account.models import Account
from juloserver.pii_vault.services import detokenize_value_lookup
from juloserver.pii_vault.constants import PIIType
from juloserver.account_payment.services.collection_related import get_cashback_claim_experiment
from juloserver.julo.constants import FaQSectionNameConst
from juloserver.application_form.constants import MotherMaidenNameConst

julolog = JuloLog(__name__)
LOGGER = logging.getLogger(__name__)


class AddressLookupView(StandardizedExceptionHandlerMixin, ViewSet):
    def _get_request_data(self):
        return self.request.data

    def get_provinces(self, request):
        provinces = (
            ProvinceLookup.objects.filter(is_active=True)
            .order_by('province')
            .values_list('province', flat=True)
        )
        return success_response(provinces)

    def get_cities(self, request):
        data = self._get_request_data()
        if 'province' not in data:
            return general_error_response('province is required')
        cities = (
            CityLookup.objects.filter(
                province__province__icontains=data['province'], is_active=True
            )
            .order_by('city')
            .values_list('city', flat=True)
        )
        return success_response(cities)

    def get_districts(self, request):
        data = self._get_request_data()
        if 'province' not in data:
            return general_error_response('province is required')
        if 'city' not in data:
            return general_error_response('city is required')
        district = (
            DistrictLookup.objects.filter(
                city__city__icontains=data['city'],
                city__province__province__icontains=data['province'],
                is_active=True,
            )
            .order_by('district')
            .values_list('district', flat=True)
        )
        return success_response(district)

    def get_subdistricts(self, request):
        data = self._get_request_data()
        serializer = SubDistrictLookupReqSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        subdistrict = SubDistrictLookup.objects.filter(
            district__district__icontains=data['district'],
            district__city__city__icontains=data['city'],
            district__city__province__province__icontains=data['province'],
            is_active=True,
        ).order_by('sub_district')
        return success_response(SubDistrictLookupResSerializer(subdistrict, many=True).data)

    def get_info(self, request):
        data = self._get_request_data()
        serializer = AddressInfoSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        subdistricts = SubDistrictLookup.objects.filter(zipcode=data['zipcode'], is_active=True)
        if len(subdistricts) > 1:
            filtered_subdistricts = subdistricts.filter(sub_district__icontains=data['subdistrict'])
            if filtered_subdistricts:
                subdistricts = filtered_subdistricts

        subdistrict = subdistricts.first()

        if subdistrict:
            res_data = {
                "province": subdistrict.district.city.province.province,
                "city": subdistrict.district.city.city,
                "district": subdistrict.district.district,
                "subDistrict": subdistrict.sub_district,
                "zipcode": subdistrict.zipcode,
            }

            return success_response(res_data)
        else:
            return general_error_response("Lokasi anda tidak ditemukan")


class AdditionalInfoView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        try:
            addtional_info = FrontendView.objects.all()
            addtional_info_data = AdditionalInfoSerializer(addtional_info, many=True).data
            info_data = {}
            for info in addtional_info_data:
                if info['label_code'] not in info_data:
                    info_data[info['label_code']] = {}
                info_data[info['label_code']] = {
                    'label_name': info['label_name'],
                    'label_value': info['label_value'],
                }
            return Response(info_data)
        except ValueError as e:
            error = APIException('{}: last update date should be valid'.format(str(e)))
            error.status_code = 400
            raise error


class AppsflyerView(RetrieveUpdateAPIView):
    """class to implement update appsflyer id"""

    serializer_class = AppsflyerSerializer

    def get_object(self):
        obj = get_object_or_404(Customer, user=self.request.user)

        julolog.info(message="Try get AppsflyerView", request=self.request)
        return obj


class DeviceGeolocationView(APIView):
    """class to implement store geolocation data"""

    def post(self, request):
        if 'location_file' not in request.data:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'message': "location_file field is required"}
            )
        if not isinstance(request.data['location_file'], InMemoryUploadedFile):
            return Response(status=HTTP_400_BAD_REQUEST, data={'message': "Wrong file format"})
        reader = csv.DictReader(
            request.data['location_file'].read().decode().splitlines(),
            fieldnames=("device_id", "latitude", "longitude", "timestamp"),
        )
        customer = Customer.objects.get_or_none(user=request.user)
        if not customer:
            return Response(status=HTTP_400_BAD_REQUEST, data={'message': "Invalid user"})

        valid_device = Device.objects.filter(customer=customer).values_list('pk', flat=True)
        valid_record = []

        if not valid_device:
            return Response(status=HTTP_400_BAD_REQUEST, data={'message': "Has no valid device"})

        for loc_line in reader:
            error_log = None
            serializer = DeviceGeolocationSerializer(data=loc_line)

            if not serializer.is_valid():
                error_log = serializer.errors
            elif serializer.data['device_id'] not in valid_device:
                error_log = "Invalid device id %s" % serializer.data['device_id']
            else:
                valid_record.append(DeviceGeolocation(**serializer.data))

            if error_log:
                LOGGER.error(
                    {
                        'action': 'check valid geolocation data',
                        'data': str(loc_line),
                        'message': error_log,
                    }
                )

        DeviceGeolocation.objects.bulk_create(valid_record)
        LOGGER.info(
            {
                'action': 'update geolocation data',
                'data': 'customer_id: %s' % customer.pk,
                'message': 'Done',
            }
        )
        return Response(status=HTTP_200_OK, data={'message': 'success data saved'})


class ServerTimeView(APIView):
    """return current time of server"""

    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        julolog.info(message="Server time OK {}".format(str(datetime.now())), request=request)
        return Response(status=HTTP_200_OK, data=datetime.now())


class HealthCheckView(APIView):
    """api for health check server"""

    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        return Response(status=HTTP_200_OK, data={'message': 'Server is healthy'})


class BankApi(APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def perform_authentication(self, request):
        web_mtl_form_param = request.query_params.get('web_mtl_form', '').lower() == 'true'
        if web_mtl_form_param:
            self.authentication_classes = []
            self.permission_classes = []
        super().perform_authentication(request)

    def get(self, request, product_line_code):
        if int(product_line_code) not in ProductLineCodes.all():
            julolog.warning(message="Product line code not found", request=request)
            return Response(status=HTTP_404_NOT_FOUND, data={'Not found': 'Product line code'})
        is_show_logo = request.query_params.get('is_show_logo')
        banks_list = Bank.objects.regular_bank()
        if is_show_logo:
            bank_list = banks_list.order_by('order_position', 'bank_name')
            result = []
            for bank in bank_list:
                bank_dict = dict(
                    id=bank.id,
                    bank_name=bank.bank_name,
                    bank_code=bank.bank_code,
                    min_account_number=bank.min_account_number,
                    swift_bank_code=bank.swift_bank_code,
                    xfers_bank_code=bank.xfers_bank_code,
                    xendit_bank_code=bank.xendit_bank_code,
                    cdate=bank.cdate,
                    udate=bank.udate,
                    bank_logo=bank.bank_logo,
                )
                result.append(bank_dict)
            return JsonResponse(result, safe=False)
        else:
            banks_list = list(banks_list.values())
            return JsonResponse(banks_list, safe=False)


def get_terms_privacy(_request):
    """return term and privacy in html code"""
    html_content = get_template("terms_and_privacy.html")
    html_render = html_content.render()
    julolog.info("Total length : {}".format(len(html_render)))
    return HttpResponse(html_render, content_type='text/plain')


class ApplicationUpdateV3(ApplicationUpdate):
    serializer_class = ApplicationUpdateSerializerV3

    def check_liveness(self, application=None):
        instance = application or self.get_object()
        application_id = instance.id
        # skip or IDFy customer
        is_idfy_record = IdfyVideoCall.objects.filter(application_id=application_id).exists()
        if is_idfy_record:
            logging.info(
                'skip check liveness for idfy application|application_id={}'.format(application_id)
            )
            return True

        active_liveness_detection = ActiveLivenessDetection.objects.filter(
            application_id=application_id
        ).last()
        if not active_liveness_detection or active_liveness_detection in (
            LivenessCheckStatus.STARTED,
            LivenessCheckStatus.INITIAL,
        ):
            LOGGER.warning(
                'j1_application_submit_without_liveness_detection|'
                'application_id={}'.format(application_id)
            )
            return False

        return True

    def check_selfie_submission(self, application=None):
        instance = application or self.get_object()
        application_id = instance.id
        face_image = Image.objects.filter(
            image_source=application_id, image_type=ImageType.SELFIE
        ).last()
        if not face_image:
            LOGGER.warning(
                'j1_application_submit_without_selfie_upload|'
                'application_id={}'.format(application_id)
            )
            return False

        return True

    def check_validated_otp(self, submitted_phone_number, application=None):
        instance = application or self.get_object()
        customer = instance.customer
        if not MobileFeatureSetting.objects.filter(
            feature_name=FeatureSettingName.COMPULSORY,
            is_active=True,
        ).exists():
            return True

        detokenize_value_lookup(submitted_phone_number, PIIType.CUSTOMER)
        otp_request = OtpRequest.objects.filter(
            phone_number=submitted_phone_number,
            is_used=True,
            action_type__in=(
                SessionTokenAction.VERIFY_PHONE_NUMBER,
                SessionTokenAction.PHONE_REGISTER,
            ),
        ).last()

        if not otp_request:
            return False

        if (
            otp_request.action_type == SessionTokenAction.VERIFY_PHONE_NUMBER
            and otp_request.customer_id != customer.id
        ):
            return False
        return True

    @staticmethod
    def check_is_longform_shortened(data):
        """
        Check is LongForm shortened with rule:
        In shortform no key
        "loan_purpose_desc", "home_status",
        Return True is LongForm Shortened
        Return False is LongForm
        """

        # This condition to skip check
        # If customer fill out form with Upgrade Form
        if 'is_upgrade' in data:
            # default is LFS
            return True

        default_dependent = [0, "0", None]
        special_field = "dependent"
        keys_in_longform = ["loan_purpose_desc", "home_status", "occupied_since", special_field]

        count_is_none = 0
        for key in keys_in_longform:
            # handle for data null or empty string
            if key in data and not data[key]:
                count_is_none += 1
            elif special_field in data and key == special_field:
                if data[special_field] in default_dependent:
                    count_is_none += 1

        if count_is_none == len(keys_in_longform):
            return True

        # default for return LongForm
        return False

    def is_validated_mother_maiden_name(self, application_id, app_version, mother_maiden_name):
        from juloserver.application_form.services.mother_name_experiment_service import (
            MotherNameValidation,
        )

        mother_name_validation = MotherNameValidation(
            application_id=application_id,
            app_version=app_version,
            mother_maiden_name=mother_maiden_name,
        )
        return mother_name_validation.run_validation()

    def update(self, request, *args, **kwargs):
        from juloserver.julo.constants import OnboardingIdConst
        from juloserver.application_form.services.application_service import (
            do_check_and_copy_data_approved,
        )

        app_version = None
        if request.META.get('HTTP_X_APP_VERSION'):
            app_version = request.META.get('HTTP_X_APP_VERSION')

        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        application_path_tag = request.data.get('application_path_tag')
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
            return new_general_error_response('application_path_tag is invalid')

        onboarding_id = request.data.get('onboarding_id')
        # check data onboarding_id is correct
        if onboarding_id and not self.check_allowed_onboarding(onboarding_id):
            return new_general_error_response(OnboardingIdConst.MSG_NOT_ALLOWED)

        # to define data from LFS (LongForm Shortened)
        is_upgrade = request.data.get('is_upgrade')

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
            return new_general_error_response(error_message)

        is_longform_shortened = self.check_is_longform_shortened(request.data)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            julolog.warning(
                {
                    "message": str(serializer.errors),
                    "process": "serializer check validation",
                    "data": str(request.data),
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
                    "Maaf, nomor telepon perusahaan yang kamu masukkan tidak "
                    "valid. Mohon masukkan nomor lainnya."
                ]
            return new_general_error_response(
                transform_error_msg(serializer_errors, exclude_key=True)[0]
            )
        if serializer.validated_data.get('mobile_phone_1') and not self.check_validated_otp(
            request.data.get('mobile_phone_1')
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
            return new_general_error_response(ErrorMessage.PHONE_NUMBER_MISMATCH)

        # serializer.is_valid(raise_exception=True)
        self.claim_customer(instance, request.data)
        if not self.check_job_and_company_phone():
            job_type = self.request.data.get('job_type', None)
            message = 'Jika pekerjaan ' + job_type + ', nomor telepon kantor tidak boleh GSM'
            error = APIException(format(str(message)))
            error.status_code = 400
            julolog.warning(
                {
                    "message": str(message),
                    "process": "check_job_and_company_phone",
                    "data": str(serializer.validated_data),
                    "app_version": app_version,
                    "application": instance.id,
                    "is_upgrade": is_upgrade,
                },
                request=request,
            )
            raise error

        mother_maiden_name = self.request.data.get('mother_maiden_name', None)
        if not self.is_validated_mother_maiden_name(
            application_id=instance.id,
            app_version=app_version,
            mother_maiden_name=mother_maiden_name,
        ):
            julolog.warning(
                {'message': '[MotherMaidenName] is not valid', 'application_id': instance.id}
            )
            return new_general_error_response(MotherMaidenNameConst.ERROR_MESSAGE)

        # check for upgrade payload should be correct
        message_upgrade, checker_is_upgrade = self.check_is_upgrade_application(
            serializer, is_upgrade
        )
        if not checker_is_upgrade:
            julolog.error(
                {
                    "message": message_upgrade,
                    "process": "check is upgrade application",
                    "data": str(request.data),
                    "app_version": app_version,
                    "application": instance.id,
                    "is_upgrade": is_upgrade,
                },
                request=request,
            )
            return new_general_error_response(message_upgrade)

        # capture log process before perform update
        julolog.info(
            {
                "message": "Capture submission data before perform update",
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

        # # capture log process after perform update
        # to make sure check all process result with data correct
        julolog.info(
            {
                "message": "Capture submission data after perform update",
                "process": "AFTER_PERFORM_UPDATE submission data",
                "data": str(serializer.data),
                "app_version": app_version,
                "application": instance.id,
                "is_upgrade": is_upgrade,
            },
            request=request,
        )

        return Response(serializer.data)

    @silent_exception
    def _post_application_submit(self, serializer, customer_id=None):
        """
        Trigger optional process after the application is updated.
        The initial purpose is to store SEON fingerprint to DB. This is an experiment process.
        After the experiment is done and the process is proven to be stable, this process should be
        async process.
        """
        application_id = serializer.instance.id
        ip_address = get_client_ip(self.request)
        customer_id = customer_id if customer_id else self.request.user.customer.id
        request_data = serializer.initial_data

        handle_post_user_submit_application.delay(
            customer_id=customer_id,
            application_id=application_id,
            ip_address=ip_address,
            request_data=request_data,
        )

    def check_is_upgrade_application(self, serializer, is_upgrade):
        """
        Check if payload is not correct when upgrade form
        """

        key_upgrade = None
        fields_to_upgrade = ApplicationUpgradeConst.FIELDS_UPGRADE_FORM
        fields_to_upgrade.sort()

        # sorting the keys
        keys = list(serializer.validated_data)
        keys.sort()

        if is_upgrade:
            # for handle boolean in form-data
            if str(is_upgrade).lower() == 'true':
                key_upgrade = True

        if keys == fields_to_upgrade:
            if not key_upgrade:
                # return error for invalid case
                return 'Mohon maaf terjadi kesalahan saat pengiriman data', False
            else:
                # check mandatory field
                field_have_allow_value = 'total_current_debt'
                total_current_debt = serializer.validated_data[field_have_allow_value]
                if not self.check_mandatory_field_upgrade(
                    serializer, field_have_allow_value
                ) or not self.check_mandatory_field_with_allow_value(total_current_debt):
                    return 'Invalid request', False

                application_id = serializer.instance.id
                phone_number = serializer.validated_data['mobile_phone_2']
                if not check_phone_number_is_used(application_id, phone_number):
                    return 'Mohon maaf, nomor HP yang dimasukkan sudah digunakan', False

        return None, True

    @staticmethod
    def check_mandatory_field_upgrade(serializer, field_have_allow_value):
        data = serializer.validated_data
        fields_mandatory = ApplicationUpgradeConst.MANDATORY_UPGRADE_FORM
        for field in fields_mandatory:
            if not data[field] and field != field_have_allow_value:
                return False
        return True

    @staticmethod
    def check_mandatory_field_with_allow_value(total_current_debt):
        if str(total_current_debt) == '0':
            return True

        if not total_current_debt:
            return False

        return True


class DeviceScrapedDataUploadV3(StandardizedExceptionHandlerMixinV2, APIView):
    """
    Endpoint for uploading DSD to anaserver and starting ETL
    This version will accept data as JSON.
    """

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):
        process_name = DeviceScrapedConst.PROCESS_NAME
        if 'application_id' not in request.data:
            julolog.warning(
                {
                    'message': 'Application is required',
                    'process_name': process_name,
                },
                request=request,
            )
            return new_general_error_response('Application is required')

        customer = request.user.customer
        application_id = int(request.data['application_id'])
        if application_id == 0:
            application = customer.application_set.last()
            if application:
                application_id = application.id

        # verify the data application
        user_applications = customer.application_set.values_list('id', flat=True)
        if application_id not in user_applications:
            julolog.warning(
                {
                    'message': 'Invalid case application not found',
                    'process_name': process_name,
                    'application_id': application_id,
                },
                request=request,
            )
            return not_found_response('Application not found')

        julolog.info(
            {
                'message': 'Passed get data customer by application',
                'application_id': application_id,
                'process_name': process_name,
            },
            request=request,
        )

        # run and check customer app action
        url = request.build_absolute_uri()
        response = None
        json_forward = request.data
        try:
            response = run_and_check_customer_app_action(
                customer,
                application_id,
                url,
                json_forward,
            )
        except Exception as error:
            julolog.error(
                {
                    'message': str(error),
                    'process_name': process_name,
                    'application_id': application_id,
                }
            )

        if response.status_code != HTTP_200_OK:
            return new_general_error_response('Terjadi kesalahan dalam pengiriman data.')

        # structure response
        structure_initiate = get_structure_initiate_dsd(application_id)

        julolog.info(
            {
                'message': 'Success process for device scraped data',
                'data': structure_initiate,
                'application_id': application_id,
            },
            request=request,
        )

        return new_success_response(data=structure_initiate)


class FAQFeatureView(StandardizedExceptionHandlerMixin, APIView):
    """
    Endpoint for getting FAQ data based on section_name
    """

    def get(self, request, *args, **kwargs):
        user = self.request.user
        customer = user.customer

        account = Account.objects.filter(customer=customer).values('cashback_counter').last()
        if not account:
            return not_found_response('Account not found')

        section_name = request.GET.get('section_name', '')
        if not section_name:
            return general_error_response('section_name is required')

        faq_data = FaqFeature.objects.filter(section_name=section_name, visible=True).order_by(
            'order_priority'
        )

        if not faq_data.exists():
            return not_found_response('FaQ {} not found'.format(section_name))

        faq_contents = [{'title': faq.title, 'content': faq.description} for faq in faq_data]

        # Dictionary to handle specific logic for different section names
        section_specific_logic = {
            FaQSectionNameConst.CASHBACK_NEW_SCHEME: self._handle_cashback_new_scheme,
        }

        if section_name in section_specific_logic:
            faq_contents.extend(section_specific_logic[section_name](customer.account))

        response_data = dict(
            streak_level=account['cashback_counter'],
            faq=faq_contents,
        )

        return success_response(response_data)

    def _handle_cashback_new_scheme(self, account):
        _, is_cashback_experiment = get_cashback_claim_experiment(account=account)
        if is_cashback_experiment:
            faq_experiment = FaqFeature.objects.filter(
                section_name=FaQSectionNameConst.CASHBACK_NEW_SCHEME_EXPERIMENT, visible=True
            ).order_by('order_priority')
            if faq_experiment:
                return [{'title': faq.title, 'content': faq.description} for faq in faq_experiment]
        return []


class DeviceScrapedDataUploadCLCSV3(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):

        if 'application_id' not in request.data:
            julolog.error(
                {'message': 'Bad Request application ID is required!', 'request': str(request.data)}
            )
            return new_general_error_response('Bad Request!')

        application_id = int(request.data['application_id'])
        customer = request.user.customer
        url = request.build_absolute_uri()
        request_body = request.data

        is_success, response = proceed_request_clcs_dsd(
            request_body=request_body,
            customer=customer,
            application_id=application_id,
            url=url,
        )

        if not is_success or response.status_code != HTTP_200_OK:
            return new_general_error_response('Failed send the data')

        return new_success_response('successfully')

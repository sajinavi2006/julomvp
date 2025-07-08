import os
import logging
from datetime import datetime, time

from bulk_update.helper import bulk_update
from django.conf import settings
from juloserver.julo.models import AuthUser as User
from django.db import transaction
from django.db.models import F
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponseNotAllowed, StreamingHttpResponse
from django.utils import timezone
from hashids import Hashids

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.status import (
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_403_FORBIDDEN,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_202_ACCEPTED,
    HTTP_415_UNSUPPORTED_MEDIA_TYPE,
)
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.viewsets import ViewSet
from rest_framework.decorators import parser_classes
from rest_framework.parsers import FormParser, MultiPartParser

from juloserver.dana.constants import DanaHashidsConstant
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    get_file_from_oss,
    get_oss_presigned_url_external,
)
from juloserver.merchant_financing.models import MerchantRiskAssessmentResult
from juloserver.merchant_financing.web_app.constants import (
    WebAppErrorMessage,
    MFWebAppUploadAsyncStateType,
    MFWebAppUploadStateTaskStatus,
    MFStandardMerchantStatus,
    MFStandardApplicationStatus,
    MFStandardApplicationType,
)
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.merchant_financing.api_response import (
    error_response as mf_error_response,
    success_response as mf_success_response,
)
from juloserver.merchant_financing.constants import (
    MFStandardRole,
    MFFeatureSetting,
    MFStandardRejectReason,
)
from juloserver.merchant_financing.web_app.serializers import (
    ApproveRejectSerializer,
    WebAppRegisterSerializer,
    WebAppLoginSerializer,
    RetriveNewAccessTokenSerializer,
    DashboardLoginSerializer,
    DistributorUploadSerializer,
    DistributorListSerializer,
    WebAppOTPRequestSerializer,
    WebAppOTPValidateSerializer,
    DocumentUploadSerializer,
    SubmitApplicationSerializer,
    SubmitPartnershipApplicationDataSerializer,
    ForgotPasswordSerializer,
    VerifyResetKeySerializer,
    ResetPasswordConfirmSerializer,
    LimitApprovalSerializer,
    LimitAdjustmentSerializer,
    DashboardLogin2Serializer,
    UploadDistributorDataV2Serializer,
    DistributorListV2Serializer,
    MerchantUploadCsvSerializer,
    MerchantDocumentUploadSerializer,
    ReSubmissionApplicationRequestSerializer,
    MerchantSubmitFileSerializer,
    ApplicationRiskAssessmentSerializer,
)
from juloserver.merchant_financing.web_app.tasks import (
    process_mf_web_app_merchant_upload_file_task,
    merchant_financing_std_move_status_131_async_process,
)
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.merchant_financing.decorators import (
    require_partner_agent_role,
    require_mf_api_v1,
    require_mf_api_v2,
    require_agent_role,
)
from juloserver.merchant_financing.web_app.security import (
    WebAppAuthentication,
    MFStandardAPIAuthentication,
)
from juloserver.merchant_financing.web_app.services import (
    create_partnership_user,
    validate_and_insert_distributor_data,
    web_app_send_sms_otp,
    web_app_verify_sms_otp,
    process_upload_file,
    check_image_upload,
    check_document_upload,
    process_reset_password_request,
    process_confirm_new_password_web_app,
    get_fdc_data_for_application,
    validate_and_insert_distributor_data_v2,
    upload_merchant_financing_onboarding_document,
    get_fdc_data_for_application_v2,
    mapping_merchant_financing_standard_status,
)
from juloserver.partnership.constants import (
    PartnershipTokenType,
    HTTPStatusCode,
    IMAGE_EXTENSION_FORMAT,
    IMAGE_TYPE,
    DOCUMENT_TYPE,
    DOCUMENT_EXTENSION_FORMAT,
    ErrorMessageConst,
    PartnershipHttpStatusCode,
    HTTPGeneralErrorMessage,
    PartnershipProductCategory,
    PartnershipImageStatus,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.tasks import partnership_application_status_change_async_process
from juloserver.merchant_financing.web_app.utils import (
    create_or_update_token,
    check_partner_name,
    error_response_web_app,
    generate_access_token,
    verify_access_token,
    inactivate_token,
    success_response_web_app,
    verify_token_is_active,
    check_partner_from_token,
    no_content_response_web_app,
    response_template_error,
)
from juloserver.partnership.models import (
    PartnershipDistributor,
    PartnershipCustomerData,
    PartnershipApplicationData,
    PartnerLoanRequest,
    PartnershipUser,
    PartnershipImage,
    PartnershipDocument,
    PartnershipFeatureSetting,
)
from juloserver.julo.models import (
    Customer,
    Image,
    Application,
    Document,
    FeatureSetting,
    Agent,
    UploadAsyncState,
    Partner,
    CreditScore,
)
from juloserver.apiv3.models import CityLookup, DistrictLookup, ProvinceLookup, SubDistrictLookup
from juloserver.apiv3.serializers import (
    AddressInfoSerializer,
    SubDistrictLookupReqSerializer,
    SubDistrictLookupResSerializer,
)
from juloserver.merchant_financing.web_portal.paginations import WebPortalPagination
from juloserver.apiv2.tasks import populate_zipcode
from juloserver.application_flow.services import suspicious_hotspot_app_fraud_check
from juloserver.julo.services import process_application_status_change
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.partnership.utils import (
    response_template,
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
    partnership_detokenize_sync_primary_object_model_in_bulk,
    partnership_detokenize_sync_kv_in_bulk,
)
from juloserver.partnership.exceptions import APIUnauthorizedError
from juloserver.merchant_financing.api_response import error_response
from juloserver.partnership.jwt_manager import JWTManager

from typing import Any

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class MFPartnerWebAppAPIView(StandardizedExceptionHandlerMixin, APIView):
    """ Customize APIView FOR MERCHANT FINANCING  WEB APP """
    permission_classes = []
    authentication_classes = [WebAppAuthentication]
    renderer_classes = [JSONRenderer]

    @csrf_exempt
    def dispatch(self, request, *args, **kwargs) -> Response:
        partner = self.kwargs.get('partner')
        if not partner:
            response = self.error_response(msg=WebAppErrorMessage.INVALID_REQUIRED_PARTNER_NAME)
            return response

        check_partner = check_partner_name(partner)
        if not check_partner:
            response = self.error_response(
                msg=WebAppErrorMessage.INVALID_PARTNER_NAME,
                status=HTTP_404_NOT_FOUND,
            )
            return response

        response = super().dispatch(request, *args, **kwargs)
        return response

    def error_response(self, msg: str, status=HTTP_400_BAD_REQUEST) -> Response:
        """ Customize error response for dispatch """
        response_dict = {
            'message': msg,
        }
        renderer = JSONRenderer()
        response = Response(status=status)
        rendered_content = renderer.render(
            response_dict,
            renderer_context={'charset': 'utf-8'}
        )
        response.content = rendered_content
        response.accepted_renderer = renderer.media_type
        response.accepted_media_type = renderer.media_type
        response.content_type = renderer.media_type
        response.renderer_context = {'request': self.request}
        response['Content-Type'] = renderer.media_type
        return response


class MFWebAppAPIView(StandardizedExceptionHandlerMixin, APIView):
    """ Customize APIView FOR General Partner MERCHANT FINANCING  WEB APP"""
    permission_classes = []
    authentication_classes = [WebAppAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, APIUnauthorizedError):
            error_response = response_template(
                message=exc.detail,
                status=exc.status_code,
            )
            return error_response

        if isinstance(exc, MethodNotAllowed):
            return HttpResponseNotAllowed(HTTPGeneralErrorMessage.HTTP_METHOD_NOT_ALLOWED)

        if isinstance(exc, Exception):

            # # For local dev directly raise the exception
            if settings.ENVIRONMENT and settings.ENVIRONMENT == 'dev':
                raise exc

            sentry_client.captureException()

            error_response = response_template(
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                status=HTTP_500_INTERNAL_SERVER_ERROR,
            )
            return error_response

        return super().handle_exception(exc)


class MFStandardAPIView(StandardizedExceptionHandlerMixin, APIView):
    """
    This API will using for Merchant Financing new standard API View
    """

    permission_classes = []
    authentication_classes = [MFStandardAPIAuthentication]

    def handle_exception(self, exc: Exception) -> Response:

        if isinstance(exc, APIUnauthorizedError):
            return mf_error_response(
                status=exc.status_code,
                message=exc.detail,
            )

        if isinstance(exc, MethodNotAllowed):
            return HttpResponseNotAllowed(HTTPGeneralErrorMessage.HTTP_METHOD_NOT_ALLOWED)

        # For local dev directly raise the exception
        if settings.ENVIRONMENT and settings.ENVIRONMENT == 'dev':
            raise exc

        sentry_client.captureException()
        response_err = mf_error_response(
            message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

        logger.exception(
            {
                'action': 'mf_standard_api_view',
                'error': str(exc),
            }
        )
        return response_err


class WebAppRegister(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = WebAppRegisterSerializer

    def post(self, request: Request, *args, **kwargs) -> Response:

        partner = self.kwargs.get('partner')

        if not partner:
            return error_response_web_app(message=WebAppErrorMessage.INVALID_REQUIRED_PARTNER_NAME)

        check_partner = check_partner_name(partner)

        if not check_partner:
            return error_response_web_app(message=WebAppErrorMessage.INVALID_PARTNER_NAME)

        serializer = self.serializer_class(data=request.data)

        data = {}

        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )

        with transaction.atomic():
            partnership_data_created = create_partnership_user(serializer.data, partner)

        access = create_or_update_token(
            partnership_data_created.user,
            partner,
            PartnershipTokenType.ACCESS_TOKEN
        )
        refresh = create_or_update_token(
            partnership_data_created.user,
            partner,
            PartnershipTokenType.REFRESH_TOKEN
        )
        data = {
            'access_token': access.token,
            'refresh_token': refresh.token,
            'application_xid': partnership_data_created.application_xid,
            'nik': partnership_data_created.nik,
            'email': partnership_data_created.email,
        }

        return success_response_web_app(data=data)


class LoginWebApp(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = WebAppLoginSerializer

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )

        access = create_or_update_token(
            serializer.validated_data['user'],
            serializer.validated_data['partner'],
            PartnershipTokenType.ACCESS_TOKEN
        )
        refresh = create_or_update_token(
            serializer.validated_data['user'],
            serializer.validated_data['partner'],
            PartnershipTokenType.REFRESH_TOKEN
        )
        data = {
            'access_token': access.token,
            'refresh_token': refresh.token,
            'partner': serializer.validated_data['partner'],
        }
        return success_response_web_app(data=data)


class RetriveNewAccessToken(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = RetriveNewAccessTokenSerializer

    def post(self, request: Request) -> Response:

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_app(
                message=WebAppErrorMessage.INVALID_FIELD_FORMAT,
                errors=serializer.errors
            )

        grant_type = serializer.validated_data['grant_type']
        refresh_token = serializer.validated_data['refresh_token']

        is_active_token = verify_token_is_active(
            refresh_token,
            PartnershipTokenType.REFRESH_TOKEN
        )

        if not is_active_token:
            return error_response_web_app(message=WebAppErrorMessage.INVALID_TOKEN)

        partner = check_partner_from_token(refresh_token)

        if grant_type and grant_type == PartnershipTokenType.REFRESH_TOKEN:
            # Process generate access_token from refresh_token
            access_token = generate_access_token(refresh_token, partner)
            if not access_token:
                return error_response_web_app(message=WebAppErrorMessage.INVALID_TOKEN)

            data = {
                'access_token': access_token,
            }

            return success_response_web_app(data=data)
        return error_response_web_app(message=WebAppErrorMessage.INVALID_TOKEN)


class Logout(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        access_token = verify_access_token(request.META.get('HTTP_AUTHORIZATION'))
        partner = check_partner_from_token(access_token)

        if not partner:
            logger.error(
                {"action": "MFWebAppAPIView", "error": WebAppErrorMessage.INVALID_PARTNER_NAME}
            )
            return Response(status=HTTP_204_NO_CONTENT)

        set_tokens_not_active = inactivate_token(
            access_token,
            partner
        )

        if not set_tokens_not_active:
            logger.error({"action": "MFWebAppAPIView", "error": WebAppErrorMessage.INVALID_TOKEN})
            return Response(status=HTTP_204_NO_CONTENT)

        return Response(status=HTTP_204_NO_CONTENT)


class ListApplications(MFPartnerWebAppAPIView):

    def post(self, request: Request, *args, **kwargs) -> Response:
        return success_response_web_app(data={'data': 'applications'})


class LoginDashboardWebApp(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = DashboardLoginSerializer

    def post(self, request: Request, *args, **kwargs) -> Response:
        # Check Partner name from paramater
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )

        username = serializer.validated_data['username']

        user = User.objects.filter(username=username).first()
        partnership_user = user.partnershipuser_set.first()
        get_user_group = list(user.groups.values('name'))
        list_group = []

        if not partnership_user:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND, message=WebAppErrorMessage.INVALID_ACCESS_PARTNER
            )

        # On this Login will be used for Axiata Flow
        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partnership_user.partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )
        partner = detokenize_partner.name

        feature_setting = FeatureSetting.objects.filter(
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            is_active=True,
        ).last()
        if feature_setting and feature_setting.parameters:
            allowed_partners = feature_setting.parameters.get('api_v1')
            if allowed_partners and partner not in allowed_partners:
                return error_response_web_app(
                    status=HTTP_403_FORBIDDEN, message=WebAppErrorMessage.ACCESS_NOT_ALLOWED
                )

        for group in get_user_group:
            list_group.append(group['name'])
        list_group.sort(reverse=True)

        access = create_or_update_token(
            user,
            partner,
            PartnershipTokenType.ACCESS_TOKEN
        )
        refresh = create_or_update_token(
            user,
            partner,
            PartnershipTokenType.REFRESH_TOKEN
        )
        data = {
            'name': user.username,
            'access_token': access.token,
            'refresh_token': refresh.token,
            'partner': list_group,
        }
        return success_response_web_app(data=data)


class WebAppDashboardUserProfile(MFWebAppAPIView):

    @require_mf_api_v1
    def get(self, request: Request) -> Response:

        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            # to handle if fail get data partnership_user
            return error_response_web_app(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )

        get_user_group = list(user.groups.values('name'))
        list_group = []

        for group in get_user_group:
            list_group.append(group['name'])
        list_group.sort(reverse=True)

        hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
        hash_user_id = hashids.encode(user.id)

        data = {
            'user_id': hash_user_id,
            'name': user.username,
            'partner': list_group,
        }
        msg = {
            'status': WebAppErrorMessage.SUCCESSFUL
        }
        return success_response_web_app(data=data, meta=msg)


class WebAppMerchantUserProfile(MFWebAppAPIView):

    def get(self, request: Request) -> Response:

        user = request.user_obj
        if not hasattr(user, 'customer'):
            return error_response_web_app(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )
        partnership_customer_data = user.customer.partnershipcustomerdata_set.last()
        application_data = partnership_customer_data.partnershipapplicationdata_set.annotate(
            application_status=F('application__application_status__status'),
            application_status_code=F('application__application_status'),
        ).values(
            'gender',
            'dob',
            'birth_place',
            'application_status',
            'application_status_code',
        ).last()

        # Detokenize partner
        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partnership_customer_data.partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )

        customer_xid = user.customer.customer_xid
        # Detokenize partnership customer data
        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            customer_xid,
            ['nik', 'email'],
        )

        data = {
            'application': {
                'label': application_data['application_status'],
                'status': application_data['application_status_code']
            },
            'nik': detokenize_partnership_customer_data.nik,
            'email': detokenize_partnership_customer_data.email,
            'partner': detokenize_partner.name,
        }

        # To get data if merchant user already submit the application and status LOC_APPROVED
        if application_data['application_status_code'] == ApplicationStatusCodes.LOC_APPROVED:
            # Detokenize partnership application data
            detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_APPLICATION_DATA,
                partnership_customer_data.partnershipapplicationdata_set.last(),
                customer_xid,
                ['fullname', 'mobile_phone_1'],
            )

            data["fullname"] = detokenize_partnership_application_data.fullname
            data["gender"] = application_data['gender']
            data["dob"] = application_data['dob']
            data["birth_place"] = application_data['birth_place']
            data["phone_number"] = detokenize_partnership_application_data.mobile_phone_1

        msg = {
            'status': WebAppErrorMessage.SUCCESSFUL
        }

        return success_response_web_app(
            data=data,
            meta=msg
        )


class WebviewAddressLookupView(StandardizedExceptionHandlerMixin, ViewSet):
    permission_classes = []
    authentication_classes = [WebAppAuthentication]
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get_provinces(self, request):
        provinces = (
            ProvinceLookup.objects.filter(is_active=True)
            .order_by('province')
            .values_list('province', flat=True)
        )
        return success_response_web_app(data=provinces)

    def get_cities(self, request):
        data = request.GET
        if 'province' not in data:
            return error_response_web_app(message='province is required')
        cities = (
            CityLookup.objects.filter(
                province__province__icontains=data['province'], is_active=True
            )
            .order_by('city')
            .values_list('city', flat=True)
        )
        return success_response_web_app(data=cities)

    def get_districts(self, request):
        data = request.GET
        if 'province' not in data:
            return error_response_web_app(message='province is required')
        if 'city' not in data:
            return error_response_web_app(message='city is required')
        district = (
            DistrictLookup.objects.filter(
                city__city__icontains=data['city'],
                city__province__province__icontains=data['province'],
                is_active=True,
            )
            .order_by('district')
            .values_list('district', flat=True)
        )
        return success_response_web_app(data=district)

    def get_subdistricts(self, request):
        serializer = SubDistrictLookupReqSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        subdistrict = SubDistrictLookup.objects.filter(
            district__district__icontains=data['district'],
            district__city__city__icontains=data['city'],
            district__city__province__province__icontains=data['province'],
            is_active=True,
        ).order_by('sub_district')
        return success_response_web_app(
            data=SubDistrictLookupResSerializer(subdistrict, many=True).data)

    def get_info(self, request):
        serializer = AddressInfoSerializer(data=request.GET)
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

            return success_response_web_app(data=res_data)
        else:
            return error_response_web_app(message="Lokasi anda tidak ditemukan")


class WebviewDropdownDataView(StandardizedExceptionHandlerMixin, ViewSet):
    permission_classes = []
    authentication_classes = [WebAppAuthentication]
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get_marital_statuses(self, request):
        marital_statuses = [x[0] for x in Application().MARITAL_STATUS_CHOICES]
        return success_response_web_app(data=marital_statuses)


class UploadDistributorData(MFWebAppAPIView):
    serializer_class = DistributorUploadSerializer

    @require_mf_api_v1
    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            # to handle if fail get data partnership_user
            return error_response_web_app(
                status=HTTP_401_UNAUTHORIZED,
                message=WebAppErrorMessage.INVALID_TOKEN,
            )
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            if serializer.errors.get('file'):
                return error_response_web_app(
                    message=serializer.errors.get('file')[0],
                )
            else:
                return error_response_web_app(
                    status=HTTP_500_INTERNAL_SERVER_ERROR,
                    message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
                )

        data_reader = serializer.validated_data['file']
        try:
            with transaction.atomic():
                response = validate_and_insert_distributor_data(data_reader, partnership_user)
                return response
        except Exception as error:
            logger.error({"action": "UploadDistributorData", "error": str(error)})
            return error_response_web_app(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
            )


class ListDistributorData(MFWebAppAPIView, ListAPIView):
    pagination_class = WebPortalPagination
    serializer_class = DistributorListSerializer

    @require_mf_api_v1
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            # to handle if fail get data partnership_user
            return error_response_web_app(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )
        distributors = (
            PartnershipDistributor.objects.filter(
                partner=partnership_user.partner,
                is_deleted=False,
            )
            .order_by('-cdate')
            .all()
        )
        # Detokenize partnership application data
        detokenize_distributors = partnership_detokenize_sync_kv_in_bulk(
            PiiSource.PARTNERSHIP_DISTRIBUTOR,
            distributors,
            ['distributor_bank_account_number'],
        )
        queryset = self.filter_queryset(distributors)
        try:
            page = self.paginate_queryset(queryset)
            datas = []
            for distributor in page:
                data_obj = {
                    'distributor_id': distributor.id,
                    'distributor_name': distributor.distributor_name,
                    'distributor_bank_account_number': getattr(
                        detokenize_distributors.get(distributor.id),
                        'distributor_bank_account_number',
                        '',
                    ),
                    'distributor_bank_account_name': distributor.distributor_bank_account_name,
                    'bank_code': distributor.bank_code,
                    'bank_name': distributor.bank_name,
                }

                datas.append(data_obj)
            return self.get_paginated_response(datas)
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=HTTP_404_NOT_FOUND)

            return error_response_web_app(message=str(e))


class WebAppOTPRequest(MFWebAppAPIView):
    serializer_class = WebAppOTPRequestSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message='Gagal Mengirim OTP',
                errors=serializer.errors
            )

        user = request.user_obj
        application = user.customer.application_set.last()

        try:
            send_otp = web_app_send_sms_otp(
                phone_number=serializer.data.get('phone_number'),
                application=application
            )
            otp_send_sms_status = send_otp.get('otp_content').get('otp_send_sms_status')
            otp_max_request_status = send_otp.get('otp_content').get('otp_max_request_status')
            if otp_max_request_status or not otp_send_sms_status:
                return response_template_error(
                    status=HTTP_429_TOO_MANY_REQUESTS,
                    meta={
                        'expired_time': send_otp.get('otp_content').get('expired_time'),
                    },
                    data={'resend_time': send_otp.get('otp_content').get('resend_time')},
                    errors={'otp': 'Permintaan kode OTP melebihi batas maksimum'},
                )

            return success_response_web_app(
                meta={
                    'expired_time': send_otp.get('otp_content').get('expired_time'),
                },
                data={
                    'resend_time': send_otp.get('otp_content').get('resend_time'),
                }
            )
        except Exception:
            sentry_client.captureException()
            return error_response_web_app(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message='Gagal Mengirim OTP, Silahkan mencoba kembali',
            )


class WebAppVerifyOtp(MFWebAppAPIView):
    serializer_class = WebAppOTPValidateSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )
        data = serializer.data
        try:
            verify_otp = web_app_verify_sms_otp(data)
            if not verify_otp.get('success'):
                msg = verify_otp['content']['message']
                return error_response_web_app(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors={'otp': [msg]},
                )
            elif not verify_otp.get('content').get('active'):
                msg = verify_otp['content']['message']
                return error_response_web_app(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors={'otp': [msg]},
                )

            return Response(status=HTTP_204_NO_CONTENT)
        except Exception as e:
            sentry_client.captureException()
            return error_response_web_app(status=HTTP_500_INTERNAL_SERVER_ERROR, message=str(e))


class UploadDocumentView(MFWebAppAPIView):
    serializer_class = DocumentUploadSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )
        field_validation_errors = {}
        data = request.data
        if not data.get('file'):
            field_validation_errors.update({"file": ["Tidak ada file yang dipilih untuk diupload"]})

        if not data.get('type'):
            field_validation_errors.update({"type": ["Type tidak boleh kosong."]})

        if field_validation_errors:
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=field_validation_errors,
            )

        name_file, extension = os.path.splitext(request.data['file'].name)
        request.data['extension'] = extension
        request.data['file_name'] = name_file
        if request.data['type'] in DOCUMENT_TYPE and \
                extension not in DOCUMENT_EXTENSION_FORMAT \
                and extension not in IMAGE_EXTENSION_FORMAT:
            return Response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    'errors': {
                        "file": "Silakan upload file dengan format .csv, .xls, "
                        ".xlsx, .doc, .docx, .pdf, "
                        ".jpeg, .png, .jpg, .webp, atau .bmp"
                    },
                },
            )
        if request.data['type'] in IMAGE_TYPE and extension not in IMAGE_EXTENSION_FORMAT:
            return Response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    'errors': {
                        "file": "Silakan upload file dengan format "
                        ".jpeg, .png, .jpg, .webp, atau .bmp"
                    },
                },
            )
        user = request.user_obj
        application = user.customer.application_set.last()
        allowed_statuses = {ApplicationStatusCodes.FORM_CREATED,
                            ApplicationStatusCodes.FORM_PARTIAL,
                            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED}
        if application.application_status.status_code not in allowed_statuses:
            return error_response_web_app(
                status=HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID
            )

        return process_upload_file(request.data, application)


class DocumentDeleteAllView(MFWebAppAPIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def delete(self, request, *args, **kwargs):
        user = request.user_obj
        application = user.customer.application_set.last()
        if application.application_status.status_code != ApplicationStatusCodes.FORM_CREATED:
            return error_response_web_app(
                status=HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID
            )

        Image.objects.filter(image_source=application.id).delete()
        Document.objects.filter(document_source=application.id).delete()

        return Response(status=HTTP_204_NO_CONTENT)


class DocumentDeleteByIDView(MFWebAppAPIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def delete(self, request, *args, **kwargs):
        user = request.user_obj
        application = user.customer.application_set.last()
        if application.application_status.status_code != ApplicationStatusCodes.FORM_CREATED:
            return error_response_web_app(
                status=HTTP_403_FORBIDDEN,
                message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID
            )
        # to handle image_id (passed as eg: 1234_img) and document_id (passed as eg: 1234) in url
        split_id = self.kwargs['id'].split('_')
        if len(split_id) > 1:
            image = None
            if split_id[1] == 'img' and split_id[0].isdigit():
                image = Image.objects.filter(image_source=application.id,
                                             id=split_id[0]).last()
            if not image:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND, message="Dokumen tidak ditemukan"
                )
            image.delete()
        else:
            document = None
            if split_id[0].isdigit():
                document = Document.objects.filter(document_source=application.id,
                                                   id=split_id[0]).last()
            if not document:
                return error_response_web_app(
                    status=HTTP_404_NOT_FOUND, message="Dokumen tidak ditemukan"
                )

            document.delete()
        return Response(status=HTTP_204_NO_CONTENT)


class SubmitApplicationView(MFWebAppAPIView):
    serializer_application = SubmitApplicationSerializer
    serializer_partnership_application = SubmitPartnershipApplicationDataSerializer

    def post(self, request, *args, **kwargs):
        try:
            user = request.user_obj
            application = user.customer.application_set.last()
            if application.application_status.status_code != ApplicationStatusCodes.FORM_CREATED:
                return error_response_web_app(
                    status=HTTP_403_FORBIDDEN,
                    message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID
                )
            is_have_valid_image_upload, result_check_image_upload = check_image_upload(
                application.id
            )
            if not is_have_valid_image_upload:
                return error_response_web_app(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=result_check_image_upload,
                )

            is_have_valid_document_upload, result_check_document_upload = check_document_upload(
                application.id
            )
            if not is_have_valid_document_upload:
                return error_response_web_app(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=result_check_document_upload,
                )

            data = request.data
            application_serializer = self.serializer_application(application,
                                                                 data=data, partial=True)

            if not application_serializer.is_valid():
                return error_response_web_app(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=application_serializer.errors
                )
            partnership_application_data = PartnershipApplicationData.objects.filter(
                application=application.id).last()
            partnership_application_serializer = self.serializer_partnership_application(
                partnership_application_data,
                data=data, partial=True
            )
            if not partnership_application_serializer.is_valid():
                return error_response_web_app(
                    errors=partnership_application_serializer.errors
                )
            with transaction.atomic():
                application_serializer.save()
                masked_phone_no = str(application.product_line.product_line_code) + str(
                    data['primary_phone_number'])
                application.mobile_phone_1 = masked_phone_no
                application.job_type = 'Pengusaha'
                application.save(update_fields=['mobile_phone_1', 'job_type'])

                partnership_application_serializer.save()
                partnership_application_data.fullname = data['fullname']
                partnership_application_data.birth_place = data['birth_place']
                partnership_application_data.dob = data['dob']
                partnership_application_data.gender = data['gender']
                partnership_application_data.address_street_num = data['address']
                partnership_application_data.address_provinsi = data['address_province']
                partnership_application_data.address_kabupaten = data['address_regency']
                partnership_application_data.address_kecamatan = data['address_district']
                partnership_application_data.address_kelurahan = data['address_subdistrict']
                partnership_application_data.address_kodepos = data['address_zipcode']
                partnership_application_data.mobile_phone_1 = data['primary_phone_number']
                partnership_application_data.last_education = data['last_education']
                partnership_application_data.monthly_income = data['monthly_income']
                partnership_application_data.company_name = data['company_name']
                partnership_application_data.marital_status = data['marital_status']
                partnership_application_data.save()
                partnership_customer_data = PartnershipCustomerData.objects.filter(
                    application_id=application.id).last()
                partnership_customer_data.phone_number = data['primary_phone_number']
                partnership_customer_data.save(update_fields=['phone_number'])
                customer = Customer.objects.filter(id=application.customer.id).last()
                customer.phone = masked_phone_no
                customer.dob = data['dob']
                customer.fullname = data['fullname']
                customer.gender = data['gender']
                customer.save(update_fields=['phone', 'dob', 'fullname', 'gender'])

                populate_zipcode(application.id)
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.FORM_PARTIAL,
                    change_reason="customer_triggered",
                )
                suspicious_hotspot_app_fraud_check(application)

                return success_response_web_app(data=data)
        except Exception as e:
            logger.info({
                "action": "SubmitApplicationView",
                "error": str(e)
            })
            return error_response_web_app(
                message=str(e)
            )


class LimitApprovalView(MFWebAppAPIView):
    serializer_class = LimitApprovalSerializer

    @require_mf_api_v1
    def post(self, request: Request, *args, **kwargs) -> Response:
        try:
            serializer = self.serializer_class(data=request.data)

            if not serializer.is_valid():
                return error_response_web_app(
                    message='validation error',
                    errors=serializer.errors
                )

            application_ids = serializer.validated_data['application_ids']
            action = self.kwargs['action']

            action_option = {"APPROVE", "REJECT"}
            if action.upper() not in action_option:
                return error_response_web_app(
                    message='opsi parameter url hanya ada approve dan reject'
                )

            status_code = ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
            if action.upper() == 'REJECT':
                status_code = ApplicationStatusCodes.APPLICATION_DENIED
            application_data = Application.objects.filter(id__in=application_ids)

            for application in application_data.iterator():
                if (
                    application.application_status_id
                    != ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                ):
                    logger.error(
                        {
                            "action": "LimitApprovalView",
                            "message": "Failed {} application. application status not x121".format(
                                action
                            ),
                            "application_id": application.id,
                            "application_status": application.application_status,
                        }
                    )
                    continue

                process_application_status_change(
                    application.id,
                    status_code,
                    change_reason="agent_triggered",
                )

            return no_content_response_web_app()

        except Exception as e:
            logger.error({
                "action": "LimitApprovalView",
                "error": str(e)
            })
            return error_response_web_app(
                message=ErrorMessageConst.GENERAL_ERROR
            )


class LimitAdjustmentView(MFWebAppAPIView):
    serializer_class = LimitAdjustmentSerializer

    @require_mf_api_v1
    def post(self, request: Request, *args, **kwargs) -> Response:
        try:
            serializer = self.serializer_class(data=request.data)

            if not serializer.is_valid():
                return error_response_web_app(
                    message='validation error',
                    errors=serializer.errors
                )

            limit_amount = serializer.validated_data['limit']
            application_id = self.kwargs['application_id']

            application_status = (
                Application.objects.filter(id=application_id)
                .values_list('application_status_id', flat=True)
                .last()
            )
            if application_status != ApplicationStatusCodes.SCRAPED_DATA_VERIFIED:
                logger.error(
                    {
                        "action": "LimitAdjustmentView",
                        "message": "Failed adjust limit",
                        "application_id": application_id,
                        "application_status": application_status,
                    }
                )
                return error_response_web_app(
                    message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID
                )

            partner_application_data = PartnershipApplicationData.objects.filter(
                application=application_id
            ).last()
            partner_application_data.proposed_limit = limit_amount
            partner_application_data.save()

            return no_content_response_web_app()

        except Exception as e:
            logger.error({
                "action": "LimitAdjustmentView",
                "error": str(e)
            })
            return error_response_web_app(
                message=ErrorMessageConst.GENERAL_ERROR
            )


class WebAppForgotPasswordView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = ForgotPasswordSerializer

    def post(self, request) -> Response:
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )

        email = serializer.validated_data['email'].strip().lower()

        pii_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'email': email}
        )
        existing = PartnershipCustomerData.objects.filter(**pii_filter_dict).exists()
        if not existing:
            """
            if email not registered we still pass but not sent the email
            for handle bruteforce, but we record on the log where email
            failed sent because email not register
            """
            logger.warning({
                "action": "failed_sent_email_forgot_password_mf_web_app",
                "email": email,
                "message": "email not registered",
            })
            return Response(status=HTTP_204_NO_CONTENT)
        try:
            reset_password = process_reset_password_request(email)
            status = reset_password.get('success')
            msg = reset_password.get('message')
            if not status:
                return error_response_web_app(
                    status=HTTP_400_BAD_REQUEST,
                    message=WebAppErrorMessage.FAILURE_FORGOT_PASSWORD,
                    errors={'error': [msg]},
                )
            return Response(status=HTTP_204_NO_CONTENT)
        except Exception:
            sentry_client.captureException()
            return error_response_web_app(
                status=HTTP_400_BAD_REQUEST,
                message=WebAppErrorMessage.FAILURE_FORGOT_PASSWORD,
            )


class WebAppVerifyRestKeyView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = VerifyResetKeySerializer

    def post(self, request) -> Response:
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(status=HTTP_403_FORBIDDEN)

        token = serializer.validated_data['token']
        customer = Customer.objects.get_or_none(reset_password_key=token)

        if not customer:
            return Response(status=HTTP_403_FORBIDDEN)

        partnership_customer_data = customer.partnershipcustomerdata_set.last()

        if not partnership_customer_data:
            return Response(status=HTTP_403_FORBIDDEN)

        if customer.has_resetkey_expired():
            customer.reset_password_key = None
            customer.reset_password_exp_date = None
            customer.save()
            return Response(status=HTTP_403_FORBIDDEN)

        return Response(status=HTTP_204_NO_CONTENT)


class WebAppResetPasswordConfirmView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = ResetPasswordConfirmSerializer

    def post(self, request) -> Response:

        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return error_response_web_app(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors
            )

        password = serializer.validated_data['password']
        token = serializer.validated_data['token']

        customer = Customer.objects.get_or_none(reset_password_key=token)

        if not customer:
            msg = WebAppErrorMessage.FAILURE_TOKEN_FORGOT_PASSWORD
            error = {'token': [msg]}
            return error_response_web_app(status=HTTP_403_FORBIDDEN, errors=error)

        if customer.has_resetkey_expired():
            customer.reset_password_key = None
            customer.reset_password_exp_date = None
            customer.save()
            msg = WebAppErrorMessage.FAILURE_TOKEN_FORGOT_PASSWORD
            error = {'token': [msg]}
            return error_response_web_app(status=HTTP_403_FORBIDDEN, errors=error)

        partnership_customer_data = customer.partnershipcustomerdata_set.last()

        if not partnership_customer_data:
            msg = WebAppErrorMessage.FAILURE_TOKEN_FORGOT_PASSWORD
            error = {'token': [msg]}
            return error_response_web_app(status=HTTP_403_FORBIDDEN, errors=error)

        try:
            with transaction.atomic():
                user = customer.user
                process_confirm_new_password_web_app(
                    customer,
                    partnership_customer_data.email,
                    password,
                    token
                )
                get_access_token = user.partnershipjsonwebtoken_set.filter(
                    token_type=PartnershipTokenType.ACCESS_TOKEN
                ).last()
                # reset jwt token if active
                if get_access_token:
                    inactivate_token(
                        get_access_token.token,
                        get_access_token.partner_name
                    )
            return Response(status=HTTP_204_NO_CONTENT)
        except Exception:
            sentry_client.captureException()
            return error_response_web_app(
                status=HTTP_400_BAD_REQUEST,
                message=WebAppErrorMessage.FAILURE_FORGOT_PASSWORD,
            )


class ApplicationDetails(MFWebAppAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_mf_api_v1
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            return error_response_web_app(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )
        partnership_application_data = (
            PartnershipApplicationData.objects.select_related('application')
            .filter(
                application__product_line=ProductLineCodes.AXIATA_WEB,
                application_id=self.kwargs['application_id'],
            )
            .last()
        )
        list_document_type = DOCUMENT_TYPE.copy()
        list_document_type.update(IMAGE_TYPE)

        if not partnership_application_data:
            return error_response_web_app(message='Application tidak ditemukan')
        try:
            # Detokenize partnership_application_data
            detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_APPLICATION_DATA,
                partnership_application_data,
                partnership_application_data.application.customer.customer_xid,
                ['fullname', 'mobile_phone_1'],
            )

            # Detokenize partnership_application_data
            detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                partnership_application_data.partnership_customer_data,
                partnership_application_data.application.customer.customer_xid,
                ['nik'],
            )

            application_detail = {}
            dob = '-'
            if partnership_application_data.application.dob:
                dob = (partnership_application_data.
                       application.dob.strftime("%Y-%m-%dT%H:%M:%S.%f%z"))
            application_detail['fullname'] = detokenize_partnership_application_data.fullname
            application_detail['company_name'] = (partnership_application_data.
                                                  application.company_name)
            application_detail['monthly_income'] = (partnership_application_data.
                                                    application.monthly_income)
            application_detail['business_category'] = (partnership_application_data.
                                                       business_category)
            application_detail['limit'] = partnership_application_data.proposed_limit
            application_detail['business_duration'] = (partnership_application_data.
                                                       business_duration)
            application_detail['product_line'] = partnership_application_data.product_line
            application_detail['nib'] = partnership_application_data.nib
            application_detail['email'] = partnership_application_data.email
            application_detail[
                'primary_phone_number'
            ] = detokenize_partnership_application_data.mobile_phone_1
            application_detail['dob'] = dob
            application_detail['birth_place'] = (partnership_application_data.
                                                 application.birth_place)
            application_detail['marital_status'] = (partnership_application_data.
                                                    application.marital_status)
            application_detail['gender'] = partnership_application_data.application.gender
            application_detail['address'] = (partnership_application_data.
                                             application.address_street_num)
            application_detail['address_province'] = (partnership_application_data.
                                                      application.address_provinsi)
            application_detail['address_regency'] = (partnership_application_data.
                                                     application.address_kabupaten)
            application_detail['address_district'] = (partnership_application_data.
                                                      application.address_kecamatan)
            application_detail['address_subdistrict'] = (partnership_application_data.
                                                         application.address_kelurahan)
            application_detail['address_zipcode'] = (partnership_application_data.
                                                     application.address_kodepos)
            application_detail['nik'] = detokenize_partnership_customer_data.nik
            application_detail['last_education'] = (partnership_application_data.
                                                    application.last_education)
            application_detail['application_status'] = (partnership_application_data.
                                                        application.application_status.status_code)
            application_detail['ktp'] = []
            application_detail['selfie'] = []
            application_detail['company_photo'] = []
            application_detail['financial_document'] = []
            application_detail['cashflow_report'] = []
            application_detail['nib_document'] = []
            application_detail['other_document'] = []

            images = Image.objects.filter(
                image_source=partnership_application_data.application_id,
                image_type__in=list_document_type)
            for image in images:
                split_str = image.url.split('_')[::-1]
                file_name = ''
                if len(split_str) > 0:
                    file_name = split_str[0]

                data = {
                    "url": get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, image.url),
                    "id": str(image.id) + '_img',
                    "file_name": file_name
                }
                if image.image_type == 'ktp':
                    application_detail['ktp'].append(data)
                elif image.image_type == 'selfie':
                    application_detail['selfie'].append(data)
                elif image.image_type == 'company_photo':
                    application_detail['company_photo'].append(data)
                elif image.image_type == 'financial_document':
                    application_detail['financial_document'].append(data)
                elif image.image_type == 'cashflow_report':
                    application_detail['cashflow_report'].append(data)
                elif image.image_type == 'nib_document':
                    application_detail['nib_document'].append(data)
                else:
                    application_detail['other_document'].append(data)

            documents = Document.objects.filter(
                document_source=partnership_application_data.application_id,
                document_type__in={'company_photo', 'financial_document',
                                   'cashflow_report', 'nib', 'other_document'}
            ).order_by('id')
            for document in documents:
                document_url = None
                if document.url:
                    document_url = get_oss_presigned_url_external(
                        settings.OSS_MEDIA_BUCKET, document.url
                    )
                data = {"url": document_url, "id": document.id, "file_name": document.filename}
                if document.document_type == 'ktp':
                    application_detail['ktp'].append(data)
                if document.document_type == 'selfie':
                    application_detail['selfie'].append(data)
                elif document.document_type == 'company_photo':
                    application_detail['company_photo'].append(data)
                elif document.document_type == 'financial_document':
                    application_detail['financial_document'].append(data)
                elif document.document_type == 'cashflow_report':
                    application_detail['cashflow_report'].append(data)
                elif document.document_type == 'nib_document':
                    application_detail['nib_document'].append(data)
                else:
                    application_detail['other_document'].append(data)

            return success_response_web_app(data=application_detail)
        except Exception as e:
            return error_response_web_app(message=str(e))


class ListApplicationData(MFWebAppAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_mf_api_v1
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            return error_response_web_app(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )
        partnership_application_data = PartnershipApplicationData.objects.select_related(
            'application').filter(
            application__product_line=ProductLineCodes.AXIATA_WEB)
        if self.kwargs['application_type'].lower() == 'resolved':
            application_status = request.GET.get('application_status')
            if application_status and application_status.lower() == 'rejected':
                partnership_application_data = partnership_application_data.filter(
                    application__application_status_id__in={
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    }
                )
            elif application_status and application_status.lower() == 'approved':
                partnership_application_data = partnership_application_data.filter(
                    application__application_status_id=ApplicationStatusCodes.LOC_APPROVED
                )
            elif application_status is None:
                partnership_application_data = partnership_application_data.filter(
                    application__application_status_id__in={
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        ApplicationStatusCodes.LOC_APPROVED,
                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    }
                )
            else:
                return Response(status=HTTP_404_NOT_FOUND)
        elif self.kwargs['application_type'].lower() == 'pending':
            partnership_application_data = partnership_application_data.filter(
                application__application_status_id=ApplicationStatusCodes.
                SCRAPED_DATA_VERIFIED
            )
        else:
            return Response(status=HTTP_404_NOT_FOUND)

        partnership_application_data = partnership_application_data.order_by('-id').all()
        queryset = self.filter_queryset(partnership_application_data)
        try:
            feature_setting = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DETOKENIZE,
                is_active=True,
            ).exists()

            if feature_setting:
                # Detokenize partnership application data
                detokenize_partnership_application_data_list = (
                    partnership_detokenize_sync_primary_object_model_in_bulk(
                        PiiSource.PARTNERSHIP_APPLICATION_DATA,
                        partnership_application_data,
                        ['fullname'],
                    )
                )

            page = self.paginate_queryset(queryset)
            datas = []
            for partnership_application_data in page:
                application_detail = {}
                application_detail['application_id'] = partnership_application_data.application.id
                if not feature_setting:
                    application_detail['fullname'] = partnership_application_data.fullname
                else:
                    customer_xid = partnership_application_data.application.customer.customer_xid
                    application_detail['fullname'] = getattr(
                        detokenize_partnership_application_data_list.get(customer_xid),
                        'fullname',
                        '',
                    )
                application_detail['company_name'] = (partnership_application_data.
                                                      application.company_name)
                application_detail['monthly_income'] = int(
                    partnership_application_data.application.monthly_income or 0)
                application_detail['business_category'] = (partnership_application_data.
                                                           business_category)
                application_detail['limit'] = int(partnership_application_data.proposed_limit or 0)
                application_detail['business_duration'] = (partnership_application_data.
                                                           business_duration)
                risk_status = partnership_application_data.reject_reason
                if not risk_status:
                    risk_status = [{
                        "name": "clear",
                        "label": "Clear"
                    }]
                application_detail['risk_status'] = risk_status
                application_detail['fdc_status'] = get_fdc_data_for_application(
                    partnership_application_data.application.id)
                datas.append(application_detail)
            return self.get_paginated_response(datas)
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=HTTP_404_NOT_FOUND)

            return error_response_web_app(message=str(e))


class DeleteDistributor(MFWebAppAPIView):

    @require_mf_api_v1
    def delete(self, request: Request, *args, **kwargs) -> Response:
        distributor_id = self.kwargs.get('distributor_id')
        partnership_distributor = PartnershipDistributor.objects.filter(
            distributor_id=distributor_id, is_deleted=False
        ).last()

        if not partnership_distributor:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message=WebAppErrorMessage.DISTRIBUTOR_NOT_FOUND,
            )

        is_distributor_used = PartnerLoanRequest.objects.filter(
            partnership_distributor=partnership_distributor
        ).exists()

        if is_distributor_used:
            return error_response_web_app(
                status=HTTP_404_NOT_FOUND,
                message=WebAppErrorMessage.DISTRIBUTOR_IN_USED,
            )

        partnership_distributor.update_safely(
            created_by_user_id=request.user_obj.id, is_deleted=True
        )

        return Response(status=HTTP_204_NO_CONTENT)


class WebAppDashboardUserProfileV2(MFStandardAPIView):
    @require_mf_api_v2
    def get(self, request: Request) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            return error_response_web_app(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )

        hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
        hash_user_id = hashids.encode(user.id)

        data = {
            "user_id": hash_user_id,
            "name": user.username,
            "role": partnership_user.role,
        }
        if partnership_user.role == MFStandardRole.PARTNER_AGENT:
            detokenize_partner = partnership_detokenize_sync_object_model(
                PiiSource.PARTNER,
                partnership_user.partner,
                customer_xid=None,
                fields_param=['name'],
                pii_type=PiiVaultDataType.KEY_VALUE,
            )

            data['partner'] = detokenize_partner.name

        return mf_success_response(data=data)


class MerchantDetailView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application_xid = self.kwargs.get('application_xid')
        pii_partner_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': request.partner_name}
        )
        partner_id = (
            Partner.objects.filter(**pii_partner_filter_dict).values_list('id', flat=True).last()
        )
        if not partner_id:
            return mf_error_response(
                status=status.HTTP_401_UNAUTHORIZED, message=WebAppErrorMessage.INVALID_TOKEN
            )

        application_data = (
            Application.objects.filter(
                application_xid=int(application_xid),
                partner_id=partner_id,
                product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
            )
            .values(
                'id',
                'product_line_id',
                'company_name',
                'monthly_income',
                'dob',
                'birth_place',
                'marital_status',
                'gender',
                'address_street_num',
                'address_provinsi',
                'address_kabupaten',
                'address_kecamatan',
                'address_kelurahan',
                'address_kodepos',
                'last_education',
                'application_status_id',
                'home_status',
                'close_kin_name',
                'close_kin_mobile_phone',
                'kin_name',
                'kin_mobile_phone',
                'number_of_employees',
                'monthly_expenses',
                'bank_name',
                'bank_account_number',
                'customer__customer_xid',
            )
            .last()
        )

        if not application_data:
            return mf_error_response(
                status=status.HTTP_404_NOT_FOUND, message=WebAppErrorMessage.MERCHANT_NOT_FOUND
            )

        partnership_application_data_query = PartnershipApplicationData.objects.filter(
            application_id=application_data['id']
        )
        partnership_application_data = (
            partnership_application_data_query.select_related('partnership_customer_data')
            .values(
                'proposed_limit',
                'business_duration',
                'business_category',
                'product_line',
                'business_type',
                'reject_reason',
            )
            .last()
        )
        resubmit_status = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED

        merchant_status = mapping_merchant_financing_standard_status(
            application_data['application_status_id']
        )

        # TODO: Will update after API Image & Document Finished
        all_single_images = PartnershipImage.objects.filter(
            application_image_source=application_data['id'],
            image_status=PartnershipImageStatus.ACTIVE,
            image_type__in={"ktp", "ktp_selfie", "npwp", "nib", "agent_with_merchant_selfie"},
        ).order_by('id')

        ktp_data = None
        ktp_selfie_data = None
        npwp_data = None
        nib_data = None
        agent_with_merchant_selfie_data = None
        for all_single_image in all_single_images:
            image_type = all_single_image.image_type

            file_id = all_single_image.id
            image_url = None
            filename = None

            if all_single_image.url:
                filename = all_single_image.url.rpartition('/')[-1]
                image_url = get_oss_presigned_url_external(
                    settings.OSS_MEDIA_BUCKET, all_single_image.url
                )

            if image_type == 'ktp':
                ktp_data = {'file_id': file_id, 'file_name': filename, 'file_url': image_url}
            elif image_type == 'ktp_selfie':
                ktp_selfie_data = {'file_id': file_id, 'file_name': filename, 'file_url': image_url}
            elif image_type == 'npwp':
                npwp_data = {'file_id': file_id, 'file_name': filename, 'file_url': image_url}
            elif image_type == 'nib':
                nib_data = {'file_id': file_id, 'file_name': filename, 'file_url': image_url}
            elif image_type == 'agent_with_merchant_selfie':
                agent_with_merchant_selfie_data = {
                    'file_id': file_id,
                    'file_name': filename,
                    'file_url': image_url,
                }

        company_photos = PartnershipImage.objects.filter(
            application_image_source=application_data['id'],
            image_status=PartnershipImageStatus.ACTIVE,
            image_type="company_photo",
        ).order_by('id')[:3]

        company_photo_datas = []
        if company_photos:
            for company_photo in company_photos:
                company_photo_url = get_oss_presigned_url_external(
                    settings.OSS_MEDIA_BUCKET, company_photo.url
                )
                company_photo_data = {
                    'file_id': company_photo.id,
                    'file_name': company_photo.url.rpartition('/')[-1]
                    if company_photo.url
                    else None,
                    'file_url': company_photo_url,
                }
                company_photo_datas.append(company_photo_data)

        cashflow_reports = PartnershipDocument.objects.filter(
            document_source=application_data['id'],
            document_status=PartnershipDocument.CURRENT,
            document_type="cashflow_report",
        ).order_by('id')[:3]

        cashflow_report_datas = []
        if cashflow_reports:
            for cashflow_report in cashflow_reports:
                cashflow_report_url = get_oss_presigned_url_external(
                    settings.OSS_MEDIA_BUCKET, cashflow_report.url
                )
                cashflow_report_data = {
                    'file_id': cashflow_report.id,
                    'file_name': cashflow_report.url.rpartition('/')[-1]
                    if cashflow_report.url
                    else None,
                    'file_url': cashflow_report_url,
                }
                cashflow_report_datas.append(cashflow_report_data)

        dob = None
        if application_data['dob']:
            convert_dob = datetime.combine(application_data['dob'], time.min)
            dob = timezone.localtime(convert_dob)

        # Detokenize partnership application data
        customer_xid = application_data.get('customer__customer_xid')
        partnership_application_data_obj = partnership_application_data_query.last()
        detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_APPLICATION_DATA,
            partnership_application_data_obj,
            customer_xid,
            ['fullname', 'mobile_phone_1', 'email'],
        )

        # Detokenize partnership customer data
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            application_id=application_data['id']
        ).last()
        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            customer_xid,
            ['nik'],
        )

        data = {
            'application_xid': str(application_xid),
            'fullname': detokenize_partnership_application_data.fullname,
            'company_name': application_data['company_name'],
            'monthly_income': application_data['monthly_income'],
            'business_category': partnership_application_data['business_category'],
            'limit': partnership_application_data['proposed_limit'],
            'business_duration': partnership_application_data['business_duration'],
            'product_line': application_data['product_line_id'],
            'email': detokenize_partnership_application_data.email,
            'phone_number': detokenize_partnership_application_data.mobile_phone_1,
            'dob': dob,
            'birth_place': application_data['birth_place'],
            'marital_status': application_data['marital_status'],
            'gender': application_data['gender'],
            'address': application_data['address_street_num'],
            'address_province': application_data['address_provinsi'],
            'address_regency': application_data['address_kabupaten'],
            'address_district': application_data['address_kecamatan'],
            'address_subdistrict': application_data['address_kelurahan'],
            'address_zipcode': application_data['address_kodepos'],
            'nik': detokenize_partnership_customer_data.nik,
            'last_education': application_data['last_education'],
            'application_status': application_data['application_status_id'],
            'merchant_status': merchant_status,
            'home_status': application_data['home_status'],
            'close_kin_name': application_data['close_kin_name'],
            'close_kin_phone_number': application_data['close_kin_mobile_phone'],
            'kin_name': application_data['kin_name'],
            'kin_phone_number': application_data['kin_mobile_phone'],
            'business_type': partnership_application_data['business_type'],
            'total_employee': application_data['number_of_employees'],
            'monthly_expenses': application_data['monthly_expenses'],
            'bank_name': application_data['bank_name'],
            'bank_account_number': application_data['bank_account_number'],
            'ktp': ktp_data,
            'ktp_selfie': ktp_selfie_data,
            'npwp': npwp_data,
            'nib': nib_data,
            'agent_with_merchant_selfie': agent_with_merchant_selfie_data,
            'cashflow_report': cashflow_report_datas if cashflow_report_datas else None,
            'company_photo': company_photo_datas if company_photo_datas else None,
        }

        if application_data['application_status_id'] == resubmit_status:
            data['resubmit_document'] = partnership_application_data['reject_reason'].get(
                'resubmit_document', None
            )

        return mf_success_response(data=data)


class LoginDashboardV2WebApp(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = DashboardLogin2Serializer

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors,
            )

        user = serializer.validated_data['user']
        partnership_user = serializer.validated_data['partnership_user']
        user_role = partnership_user.role

        # Check if user coming from agent will harcoded as julo
        if user_role == MFStandardRole.PARTNER_AGENT:
            detokenize_partner = partnership_detokenize_sync_object_model(
                PiiSource.PARTNER,
                partnership_user.partner,
                customer_xid=None,
                fields_param=['name'],
                pii_type=PiiVaultDataType.KEY_VALUE,
            )

            partner = detokenize_partner.name
        else:
            partner = 'julo'

        feature_setting = FeatureSetting.objects.filter(
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            is_active=True,
        ).last()
        if feature_setting and feature_setting.parameters:
            allowed_partners = feature_setting.parameters.get('api_v2')
            if allowed_partners and partner not in allowed_partners:
                return mf_error_response(status=HTTP_403_FORBIDDEN, message="Maaf, akses ditolak")

        jwt_token = JWTManager(
            user=user,
            partner_name=partner.lower(),
            product_category=PartnershipProductCategory.MERCHANT_FINANCING,
            product_id=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        )
        access_token = jwt_token.create_or_update_token(
            token_type=PartnershipTokenType.ACCESS_TOKEN
        )

        data = {
            'name': user.username,
            'access_token': access_token.token,
            'token_type': 'Bearer',
            'role': user_role,
        }
        if user_role == MFStandardRole.PARTNER_AGENT:
            data['partner'] = partner
        return mf_success_response(data=data)


class LogoutV2(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        auth_token = request.META.get('HTTP_AUTHORIZATION')

        if auth_token:
            bearer_token = auth_token.split()
            if len(bearer_token) != 2 or bearer_token[0].lower() != 'bearer':
                return Response(status=HTTP_204_NO_CONTENT)

            try:
                jwt_token = JWTManager(
                    product_category=PartnershipProductCategory.MERCHANT_FINANCING
                )
                decoded_token = jwt_token.decode_token(bearer_token[1])
                if not decoded_token:
                    return Response(status=HTTP_204_NO_CONTENT)
                partner_name = decoded_token.get('partner')
                jwt_token = JWTManager(
                    partner_name=partner_name,
                    product_category=PartnershipProductCategory.MERCHANT_FINANCING,
                )
                jwt_token.inactivate_token(bearer_token[1])
            except Exception as error:
                logger.error({"action": "LogoutV2", "error": str(error), 'token': bearer_token})

        return Response(status=HTTP_204_NO_CONTENT)


class UploadDistributorDataPreCheck(MFStandardAPIView):
    serializer_class = UploadDistributorDataV2Serializer

    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            if serializer.errors.get('file'):
                error_message = "Gagal Upload File"
                if isinstance(serializer.errors.get('file'), dict) and serializer.errors.get(
                    'file'
                ).get('error_file_media'):
                    description = serializer.errors.get('file').get('error_file_media')
                    meta = {"type": "toast", "description": description}
                    return mf_error_response(
                        status=HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        message=error_message,
                        meta=meta,
                    )
                elif isinstance(serializer.errors.get('file'), dict) and serializer.errors.get(
                    'file'
                ).get('error_file_content'):
                    description = serializer.errors.get('file').get('error_file_content')
                    meta = {"type": "toast", "description": description}
                    return mf_error_response(message=error_message, meta=meta)
                else:
                    # Case to handle if the 'file' field is blank
                    description = serializer.errors.get('file')[0]
                    meta = {"type": "toast", "description": description}
                    return mf_error_response(message=error_message, meta=meta)
            else:
                return mf_error_response(
                    status=HTTP_500_INTERNAL_SERVER_ERROR,
                    message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
                )

        data_reader = serializer.validated_data['file']
        try:
            with transaction.atomic():
                response = validate_and_insert_distributor_data_v2(
                    data_reader, partnership_user, True
                )
                return response
        except Exception as error:
            logger.error({"action": "UploadDistributorDataPreCheck", "error": str(error)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
            )


class UploadDistributorDataV2(MFStandardAPIView):
    serializer_class = UploadDistributorDataV2Serializer

    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            if serializer.errors.get('file'):
                error_message = "Gagal Upload File"
                if isinstance(serializer.errors.get('file'), dict) and serializer.errors.get(
                    'file'
                ).get('error_file_media'):
                    description = serializer.errors.get('file').get('error_file_media')
                    meta = {"type": "toast", "description": description}
                    return mf_error_response(
                        status=HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        message=error_message,
                        meta=meta,
                    )
                elif isinstance(serializer.errors.get('file'), dict) and serializer.errors.get(
                    'file'
                ).get('error_file_content'):
                    description = serializer.errors.get('file').get('error_file_content')
                    meta = {"type": "toast", "description": description}
                    return mf_error_response(message=error_message, meta=meta)
                else:
                    # Case to handle if the 'file' field is blank
                    description = serializer.errors.get('file')[0]
                    meta = {"type": "toast", "description": description}
                    return mf_error_response(message=error_message, meta=meta)
            else:
                return mf_error_response(
                    status=HTTP_500_INTERNAL_SERVER_ERROR,
                    message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
                )

        data_reader = serializer.validated_data['file']
        try:
            with transaction.atomic():
                response = validate_and_insert_distributor_data_v2(
                    data_reader, partnership_user, False
                )
                return response
        except Exception as error:
            logger.error({"action": "UploadDistributorDataV2", "error": str(error)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message=WebAppErrorMessage.FAILURE_FILE_UPLOAD,
            )


class ListDistributorDataV2(MFStandardAPIView, ListAPIView):
    pagination_class = WebPortalPagination
    serializer_class = DistributorListV2Serializer

    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        if not partnership_user:
            return mf_error_response(
                HTTP_401_UNAUTHORIZED,
                WebAppErrorMessage.INVALID_TOKEN,
            )
        distributors = PartnershipDistributor.objects.filter(
            partner=partnership_user.partner,
            is_deleted=False,
        ).all()
        queryset = self.filter_queryset(distributors)
        try:
            page = self.paginate_queryset(queryset)
            datas = []
            for distributor in page:
                serializer = self.serializer_class(distributor)
                datas.append(serializer.data)
            return self.get_paginated_response(datas)
        except Exception as e:
            if str(e) == WebAppErrorMessage.PAGE_NOT_FOUND:
                return Response(status=HTTP_404_NOT_FOUND)

            return mf_error_response(message=str(e))


class DeleteDistributorV2(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def delete(self, request: Request, *args, **kwargs) -> Response:
        distributor_id = self.kwargs.get('distributor_id')
        user = request.user_obj
        partnership_user = user.partnershipuser_set.first()
        partnership_distributor = PartnershipDistributor.objects.filter(
            distributor_id=distributor_id,
            is_deleted=False,
            partner=partnership_user.partner,
        ).last()

        if not partnership_distributor:
            return mf_error_response(
                status=HTTP_404_NOT_FOUND,
                message=WebAppErrorMessage.DISTRIBUTOR_NOT_FOUND,
            )

        is_distributor_used = PartnerLoanRequest.objects.filter(
            partnership_distributor=partnership_distributor
        ).exists()

        if is_distributor_used:
            return mf_error_response(
                status=HTTP_404_NOT_FOUND,
                message=WebAppErrorMessage.DISTRIBUTOR_IN_USED,
            )

        # replace user id when delete the distributor
        partnership_distributor.update_safely(is_deleted=True, created_by_user_id=user.id)

        return mf_success_response(status=HTTP_204_NO_CONTENT)


class MerchantUploadCsvView(MFStandardAPIView):
    serializer = MerchantUploadCsvSerializer

    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request, *args, **kwargs):
        user = request.user_obj
        agent = Agent.objects.filter(user=user).last()
        partnership_user = PartnershipUser.objects.filter(
            user_id=user.id,
        ).first()
        partner = partnership_user.partner
        in_processed_status = {
            UploadAsyncStateStatus.WAITING,
            UploadAsyncStateStatus.PROCESSING,
        }

        # Validate if there is another file in process
        is_upload_in_waiting = UploadAsyncState.objects.filter(
            task_type=MFWebAppUploadAsyncStateType.MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION,
            task_status__in=in_processed_status,
            agent=agent,
            service='oss',
        ).exists()
        if is_upload_in_waiting:
            return mf_error_response(
                message="Gagal Upload File",
                meta={
                    "type": "toast",
                    "description": "File lain sedang diproses silahkan tunggu dan coba lagi nanti",
                },
            )

        try:
            csv_file = request.FILES['file']

            # Validate file format must csv
            extension = os.path.splitext(csv_file.name)[1]
            if extension.lower() != '.csv':
                return mf_error_response(
                    status=HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    message="Gagal Upload File",
                    meta={
                        "type": "toast",
                        "description": "Pastikan kamu meng-upload file dengan format CSV, ya.",
                    },
                )

            serializer = self.serializer(data=request.data)
            if not serializer.is_valid():
                return mf_error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    message="Gagal Upload File",
                    meta={"type": "toast", "description": serializer.errors.get('file')[0]},
                )

            # Create upload async state record
            upload_async_state = UploadAsyncState(
                task_type=MFWebAppUploadAsyncStateType.MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload_async_state.file.save(
                upload_async_state.full_upload_name(csv_file.name), csv_file
            )
            upload_async_state_id = upload_async_state.id

            # Proces merchant financing register asynchronous
            process_mf_web_app_merchant_upload_file_task.delay(
                upload_async_state_id, partner.id, user.id
            )

            return Response(
                status=HTTP_202_ACCEPTED,
                data={
                    "message": "Data Merchant Sedang Di-upload",
                    "meta": {
                        "type": "toast",
                        "description": "Muat ulang halaman ini secara berkala "
                        "untuk lihat perkembangan status upload-nya, ya.",
                    },
                },
            )
        except Exception as e:
            logger.error({"action": "mf_compliance_upload_merchant_csv_view", "error": str(e)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR, message="Gagal Upload File"
            )


class MerchantDownloadCsvView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        upload_async_state_id = self.kwargs.get('history_id')
        user = request.user_obj
        agent_id = Agent.objects.filter(user=user).values_list('id', flat=True).last()

        upload_async_state = UploadAsyncState.objects.filter(
            id=upload_async_state_id,
            task_type=MFWebAppUploadAsyncStateType.MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION,
            agent_id=agent_id,
        ).last()
        if not upload_async_state:
            return mf_error_response(
                status=HTTP_404_NOT_FOUND,
                message="File tidak ditemukan",
            )
        try:
            file_url = upload_async_state.url
            filename = file_url.split("/")[-1]
            document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, file_url)
            response = StreamingHttpResponse(
                streaming_content=document_stream, content_type='text/csv'
            )
            current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")

            response['Content-Disposition'] = 'attachment; filename="{}_{}"'.format(
                current_datetime, filename
            )
            return response

        except Exception as e:
            logger.error({"action": "mf_compliance_download_merchant_csv_view", "error": str(e)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message="Kesalahan server internal. Gagal download file",
            )


class MerchantUploadHistory(MFStandardAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        status = request.GET.get('status', None)

        query_filter = dict()
        user = request.user_obj
        agent_id = Agent.objects.filter(user=user).values_list('id', flat=True).last()

        if status:
            if status == MFWebAppUploadStateTaskStatus.IN_PROGRESS:
                in_processed_status = {
                    UploadAsyncStateStatus.WAITING,
                    UploadAsyncStateStatus.PROCESSING,
                }
                query_filter['task_status__in'] = in_processed_status
            else:
                query_filter['task_status'] = status

        upload_data = (
            UploadAsyncState.objects.filter(
                task_type=MFWebAppUploadAsyncStateType.MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION,
                agent_id=agent_id,
                **query_filter
            )
            .order_by('-id')
            .all()
        )

        queryset = self.filter_queryset(upload_data)
        try:
            data = []
            page = self.paginate_queryset(queryset)
            for element in page:
                filename = ''
                status = element.task_status
                if element.url:
                    filename = element.url.rpartition('/')[-1]
                if status in {
                    UploadAsyncStateStatus.WAITING,
                    UploadAsyncStateStatus.PROCESSING,
                }:
                    status = MFWebAppUploadStateTaskStatus.IN_PROGRESS

                data.append(
                    {
                        'cdate': element.cdate,
                        'filename': filename,
                        'status': status,
                        'history_id': element.id,
                    }
                )
            return self.get_paginated_response(data)
        except Exception as e:
            logger.error({"action": "MerchantUploadHistory", "agent_id": agent_id, "error": str(e)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )


class MerchantListData(MFStandardAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        merchant_status = self.kwargs['merchant_status'].lower()
        partner_name = request.partner_name
        query_filter = {'product_line': ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT}
        if merchant_status == MFStandardMerchantStatus.APPROVED:
            query_filter['application_status_id'] = ApplicationStatusCodes.LOC_APPROVED
        elif merchant_status == MFStandardMerchantStatus.REJECTED:
            query_filter['application_status_id__in'] = {
                ApplicationStatusCodes.APPLICATION_DENIED,
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            }
        elif merchant_status == MFStandardMerchantStatus.IN_PROGRESS:
            query_filter['application_status_id__in'] = {
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            }
        elif merchant_status == MFStandardMerchantStatus.DOCUMENT_RESUBMIT:
            query_filter[
                'application_status_id'
            ] = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        elif merchant_status == MFStandardMerchantStatus.DOCUMENT_REQUIRED:
            query_filter['application_status_id'] = ApplicationStatusCodes.FORM_CREATED

        # Get partner
        pii_partner_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': partner_name}
        )
        partner = Partner.objects.filter(**pii_partner_filter_dict).last()
        if not partner:
            logger.error(
                {
                    'action': "MerchantListData",
                    'message': "partner not found",
                    'partner_name': partner_name,
                }
            )
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        applications = Application.objects.filter(partner_id=partner.id, **query_filter).values(
            'id',
            'application_status_id',
            'application_xid',
            'customer__customer_xid',
        )
        application_data = {}
        for application in applications.iterator():
            application_data[application['id']] = {
                'status': application['application_status_id'],
                'application_xid': application['application_xid'],
                'customer_xid': application['customer__customer_xid'],
            }

        application_ids = applications.values_list('id', flat=True)

        partnership_application_data_query = PartnershipApplicationData.objects.filter(
            application_id__in=application_ids
        )
        query_data = (
            partnership_application_data_query.values(
                'proposed_limit',
                'reject_reason',
                'application_id',
            )
            .order_by('-id')
            .all()
        )
        queryset = self.filter_queryset(query_data)
        try:
            # Detokenize partnership customer data
            partnership_customer_data_list = PartnershipCustomerData.objects.filter(
                application_id__in=application_ids
            )
            detokenize_partnership_customer_data_list = (
                partnership_detokenize_sync_primary_object_model_in_bulk(
                    PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                    partnership_customer_data_list,
                    ['nik', 'email', 'phone_number'],
                )
            )

            # Detokenize partnership application data
            detokenize_partnership_application_data_list = (
                partnership_detokenize_sync_primary_object_model_in_bulk(
                    PiiSource.PARTNERSHIP_APPLICATION_DATA,
                    partnership_application_data_query,
                    ['fullname'],
                )
            )

            data = []
            page = self.paginate_queryset(queryset)
            for partnership_application_data in page:
                application_value = application_data.get(
                    partnership_application_data['application_id'], None
                )
                application_xid = None
                application_status_id = None
                customer_xid = None
                if application_value:
                    application_status_id = application_value.get('status', None)
                    application_xid = application_value.get('application_xid', None)
                    customer_xid = application_value.get('customer_xid')

                value = {
                    'fullname': getattr(
                        detokenize_partnership_application_data_list.get(customer_xid),
                        'fullname',
                        '',
                    ),
                    'application_xid': str(application_xid) if application_xid else None,
                    'nik': getattr(
                        detokenize_partnership_customer_data_list.get(customer_xid), 'nik', ''
                    ),
                    'email': getattr(
                        detokenize_partnership_customer_data_list.get(customer_xid), 'email', ''
                    ),
                    'phone_number': getattr(
                        detokenize_partnership_customer_data_list.get(customer_xid),
                        'phone_number',
                        '',
                    ),
                    'limit': partnership_application_data['proposed_limit'],
                    'application_status': application_status_id,
                }
                if (
                    application_status_id
                    == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
                ):
                    value['resubmit_document'] = partnership_application_data['reject_reason'].get(
                        'resubmit_document', None
                    )

                data.append(value)
            return self.get_paginated_response(data)
        except Exception as e:
            logger.error({"action": "MerchantListData", "error": str(e)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )


class ListApplicationDataV2(MFStandardAPIView, ListAPIView):
    pagination_class = WebPortalPagination

    @require_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        # Default set to product line MF Standard
        query_filter = {'product_line': ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT}

        application_type = self.kwargs['application_type'].lower()
        application_status = request.GET.get('application_status')
        if application_type == MFStandardApplicationType.PENDING:
            query_filter['application_status_id__in'] = {
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            }
        elif application_type == MFStandardApplicationType.RESOLVED:
            if application_status:
                if application_status not in {
                    MFStandardApplicationStatus.APPROVED,
                    MFStandardApplicationStatus.REJECTED,
                    MFStandardApplicationStatus.WAITING_DOCUMENT,
                }:
                    return self.get_paginated_response([])
                application_status = application_status.lower()
                if application_status == MFStandardApplicationStatus.APPROVED:
                    query_filter['application_status_id'] = ApplicationStatusCodes.LOC_APPROVED
                elif application_status == MFStandardApplicationStatus.REJECTED:
                    query_filter['application_status_id__in'] = {
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                    }
                elif application_status == MFStandardApplicationStatus.WAITING_DOCUMENT:
                    query_filter['application_status_id__in'] = {
                        ApplicationStatusCodes.FORM_CREATED,
                        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    }
            else:
                query_filter['application_status_id__in'] = {
                    ApplicationStatusCodes.FORM_CREATED,
                    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    ApplicationStatusCodes.LOC_APPROVED,
                    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                }
        partner_name = request.GET.get('partner')
        if partner_name:
            pii_partner_filter_dict = generate_pii_filter_query_partnership(
                Partner, {'name': partner_name}
            )
            partner_id = (
                Partner.objects.filter(**pii_partner_filter_dict)
                .values_list('id', flat=True)
                .last()
            )
            if not partner_id:
                return self.get_paginated_response([])
            else:
                query_filter['partner_id'] = partner_id

        applications = Application.objects.filter(**query_filter).values(
            'id',
            'partner_id',
            'monthly_income',
            'company_name',
            'application_status_id',
            'creditscore__score',
            'customer__customer_xid',
        )
        application_data = {}
        for application in applications.iterator():
            application_data[application['id']] = {
                'partner_id': application['partner_id'],
                'monthly_income': application['monthly_income'],
                'company_name': application['company_name'],
                'application_status_id': application['application_status_id'],
                'score': application['creditscore__score'],
                'customer_xid': application['customer__customer_xid'],
            }

        application_ids = applications.values_list('id', flat=True)

        partnership_application_data_query = PartnershipApplicationData.objects.filter(
            application_id__in=application_ids
        )
        query_data = (
            partnership_application_data_query.values(
                'application_id',
                'business_category',
                'reject_reason',
                'proposed_limit',
                'business_duration',
            )
            .order_by('-id')
            .all()
        )
        queryset = self.filter_queryset(query_data)
        try:
            # Detokenize partner
            partner_ids = applications.values_list('partner_id', flat=True)
            partner_query = Partner.objects.filter(id__in=partner_ids)
            detokenize_partner_list = partnership_detokenize_sync_kv_in_bulk(
                PiiSource.PARTNER,
                partner_query,
                ['name'],
            )

            # Detokenize partnership application data
            detokenize_partnership_application_data_list = (
                partnership_detokenize_sync_primary_object_model_in_bulk(
                    PiiSource.PARTNERSHIP_APPLICATION_DATA,
                    partnership_application_data_query,
                    ['fullname'],
                )
            )

            data = []
            page = self.paginate_queryset(queryset)
            for partnership_application_data in page:
                application = application_data.get(
                    partnership_application_data['application_id'], None
                )
                application_status_id = None
                partner_id = None
                company_name = None
                monthly_income = None
                score = None
                merchant_status = None
                customer_xid = None
                if application:
                    partner_id = application.get('partner_id')
                    monthly_income = application.get('monthly_income', None)
                    company_name = application.get('company_name', None)
                    application_status_id = application.get('application_status_id', None)
                    score = application.get('score', None)
                    merchant_status = mapping_merchant_financing_standard_status(
                        application_status_id
                    )
                    customer_xid = application.get('customer_xid')

                reject_reason_data = partnership_application_data['reject_reason']
                if reject_reason_data and reject_reason_data.get('rejected_notes'):
                    risk_status = reject_reason_data.get('rejected_notes')
                else:
                    risk_status = [
                        {
                            "name": MFStandardRejectReason.CLEAR.get('name'),
                            "label": MFStandardRejectReason.CLEAR.get('label'),
                        }
                    ]

                value = {
                    'application_id': partnership_application_data['application_id'],
                    'fullname': getattr(
                        detokenize_partnership_application_data_list.get(customer_xid),
                        'fullname',
                        '',
                    ),
                    'partner_name': getattr(detokenize_partner_list.get(partner_id), 'name', ''),
                    'application_status': application_status_id,
                    'company_name': company_name,
                    'monthly_income': monthly_income,
                    'business_category': partnership_application_data['business_category'],
                    'limit': partnership_application_data['proposed_limit'],
                    'business_duration': partnership_application_data['business_duration'],
                    'fdc_status': get_fdc_data_for_application_v2(
                        partnership_application_data['application_id']
                    ),
                    'risk_status': risk_status,
                    'credit_score': score,
                    'merchant_status': merchant_status,
                    # TO DO LIST
                    # for now we hardcoded the documents into list of object
                    # later on we need to create a config for this to be adjustable
                    # we also need to change this on Merchant Detail View
                    'documents': [
                        {
                            'name': "ktp",
                            'label': "Foto KTP",
                            'fileType': "image",
                        },
                        {
                            'name': "ktpSelfie",
                            'label': "Foto Selfie + KTP",
                            'fileType': "image",
                        },
                        {
                            'name': "npwp",
                            'label': "Foto NPWP",
                            'fileType': "image",
                        },
                        {
                            'name': "nib",
                            'label': "Foto NIB",
                            'fileType': "image",
                        },
                        {
                            'name': "agentWithMerchantSelfie",
                            'label': "Foto Agent + Merchant",
                            'fileType': "image",
                        },
                        {
                            'name': "companyPhoto",
                            'label': "Foto Tempat Usaha",
                            'fileType': "image",
                        },
                        {
                            'name': "cashflowReport",
                            'label': "Laporan Arus Kas",
                            'fileType': "document",
                        },
                    ],
                }

                data.append(value)
            return self.get_paginated_response(data)
        except Exception as e:
            print(e)
            logger.error({"action": "ListApplicationDataV2", "error": str(e)})
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )


class MerchantUploadFileView(MFStandardAPIView):
    serializer_class = MerchantDocumentUploadSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @parser_classes(
        (
            FormParser,
            MultiPartParser,
        )
    )
    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request, *args, **kwargs):
        application_xid = self.kwargs.get('application_xid')
        partner_id = (
            Partner.objects.filter(name=request.partner_name).values_list('id', flat=True).last()
        )
        if not partner_id:
            return mf_error_response(
                status=status.HTTP_401_UNAUTHORIZED, message=WebAppErrorMessage.INVALID_TOKEN
            )

        get_application = (
            Application.objects.filter(application_xid=int(application_xid), partner_id=partner_id)
            .values('id', 'customer_id', 'application_status')
            .last()
        )

        if not get_application:
            return mf_error_response(
                status=status.HTTP_404_NOT_FOUND, message=WebAppErrorMessage.APPLICATION_NOT_FOUND
            )

        # Only application 100 and 131 are permitted to upload documents
        allowed_statuses = {
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        }

        application_id = get_application.get('id')
        customer_id = get_application.get('customer_id')
        application_status = get_application.get('application_status')

        if application_status not in allowed_statuses:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST, message=WebAppErrorMessage.APPLICATION_STATUS_NOT_VALID
            )

        data = request.data

        """
        reject if have multiple key for upload document
        we just allow 1 key to process upload document
        """
        if len(data) > 1:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Hanya diperbolehkan mengunggah satu jenis dokumen",
            )

        """
        validate for field cashflow_report and company_photo
        if document more than 3 file we will reject the request
        """
        if len(data.getlist('cashflow_report')) > 3:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 3",
            )
        if len(data.getlist('company_photo')) > 3:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 3",
            )

        """
        validate if have multiple files in a document type that can only be a single
        """
        if len(data.getlist('ktp')) > 1:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 1",
            )
        if len(data.getlist('ktp_selfie')) > 1:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 1",
            )
        if len(data.getlist('npwp')) > 1:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 1",
            )
        if len(data.getlist('nib')) > 1:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 1",
            )
        if len(data.getlist('agent_with_merchant_selfie')) > 1:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message="Jenis Dokumen tidak diperbolehkan mengunggah lebih dari 1",
            )

        serializer = self.serializer_class(data=data)
        if not serializer.is_valid():
            _, error = list(serializer.errors.items())[0]
            if error[0] == WebAppErrorMessage.NOT_ALLOWED_IMAGE_SIZE:
                return mf_error_response(
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    errors=serializer.errors,
                )
            elif error[0] == 'invalid_empty_attachment':
                return mf_error_response(
                    status=status.HTTP_400_BAD_REQUEST,
                    message='File tidak boleh kosong',
                )
            else:
                return mf_error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=serializer.errors,
                )
        validated_data = serializer.validated_data
        is_multiple_file = validated_data.get('is_multiple_file')
        customer_data = {
            'application_id': application_id,
            'customer_id': customer_id,
            'created_by_user_id': request.user_obj.id,
        }
        result_upload, is_success = upload_merchant_financing_onboarding_document(
            data=validated_data, customer_data=customer_data, is_multiple=is_multiple_file
        )

        if is_success:
            return mf_success_response(data=result_upload)
        elif not is_success:
            return mf_error_response(
                status=HTTP_400_BAD_REQUEST,
                message=result_upload,
            )


class ReSubmissionApplicationRequestView(MFStandardAPIView):
    serializer = ReSubmissionApplicationRequestSerializer

    @require_agent_role
    @require_mf_api_v2
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Validate data
        serializer = self.serializer(data=request.data)
        if not serializer.is_valid():
            _, error = list(serializer.errors.items())[0]
            return mf_error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                message=error[0],
            )
        application_ids = serializer.validated_data['application_ids']
        list_of_verification_files = serializer.validated_data['files']
        partnership_application_datas = serializer.validated_data['partnership_application_data']
        is_async_process = False

        # Feature settings to process move status with asynchronous
        mf_standard_async_config = (
            FeatureSetting.objects.filter(feature_name=MFFeatureSetting.MF_STANDARD_ASYNC_CONFIG)
            .values_list('parameters', flat=True)
            .last()
        )

        if mf_standard_async_config and mf_standard_async_config.get(
            MFFeatureSetting.MF_STANDARD_RESUBMISSION_ASYNC_CONFIG
        ):
            is_async_process = True

        try:
            new_status_code = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
            error_application_ids = []
            success_application_ids = []
            is_success_all = True
            for partnership_application_data in partnership_application_datas.iterator():
                application_id = partnership_application_data.application.id
                if partnership_application_data.risk_assessment_check:
                    error_application_ids.append(application_id)
                    is_success_all = False
                    continue

                if is_async_process:
                    # Update application status asynchronously
                    merchant_financing_std_move_status_131_async_process.delay(
                        application_id,
                        list_of_verification_files,
                    )
                    success_application_ids.append(application_id)
                    continue
                else:
                    # Update application status synchronously
                    process_application_status_change(
                        application_id,
                        new_status_code,
                        change_reason="agent_triggered",
                    )
                    reject_reason = {'resubmit_document': list_of_verification_files}
                    partnership_application_data.reject_reason.update(reject_reason)
                    partnership_application_data.save(update_fields=['reject_reason'])
                    success_application_ids.append(application_id)

            if is_success_all:
                title = 'Permintaan untuk Kirim Ulang Dokumen Berhasil Dikirim'
                description = (
                    'Pengajuan merchant ini sekarang bisa dilihat di tab <b>Status Pengajuan</b>'
                    ' dalam tab <b>Menunggu Dokumen</b>.'
                )
                result = {
                    'title': title,
                    'description': description,
                }
                return mf_success_response(data=result)
            elif not is_success_all and error_application_ids and success_application_ids:
                title = 'Permintaan untuk Kirim Ulang Dokumen Berhasil Sebagian'
                total_success_application_ids = len(success_application_ids)
                total_application_ids = len(partnership_application_datas)
                description = (
                    'Hanya <b>{} dari {}</b> pengajuan yang berhasil karena'
                    ' belum melalui penilaian risiko'.format(
                        total_success_application_ids,
                        total_application_ids,
                    )
                )
                result = {
                    'title': title,
                    'description': description,
                }
                meta = {
                    'success_application_ids': success_application_ids,
                    'error_application_ids': error_application_ids,
                }
                return mf_success_response(
                    data=result,
                    meta=meta,
                    status=PartnershipHttpStatusCode.HTTP_207_MULTI_STATUS,
                )
            elif not is_success_all and error_application_ids and not success_application_ids:
                title = 'Permintaan untuk Kirim Ulang Dokumen Gagal Dikirim'
                description = (
                    'Permintaan ini dapat dilakukan jika kamu belum melakukan penilaian risiko.'
                )
                result = {'title': title, 'description': description}
                return mf_error_response(
                    data=result, status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY
                )
        except Exception as error:
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'ReSubmissionApplicationRequestView',
                    'message': 'failed change status',
                    'error': str(error),
                    'application_ids': application_ids,
                    'files': list_of_verification_files,
                }
            )
            result = {
                'title': 'Permintaan untuk Kirim Ulang Dokumen Gagal Dikirim',
                'description': 'Pastikan koneksi internetmu baik lalu ulangi prosesnya ya.',
            }
            return mf_error_response(data=result, status=HTTP_500_INTERNAL_SERVER_ERROR)


class MerchantSubmitDocumentView(MFStandardAPIView):
    serializer = MerchantSubmitFileSerializer

    @require_partner_agent_role
    @require_mf_api_v2
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = request.user_obj
        user_id = user.id

        # Validate if application exists
        application_xid = self.kwargs.get('application_xid')
        application = Application.objects.filter(
            application_xid=int(application_xid),
            product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        ).last()
        if not application:
            return mf_error_response(
                status=HTTP_404_NOT_FOUND,
                message=WebAppErrorMessage.APPLICATION_NOT_FOUND,
            )

        application_id = application.id

        # Validate if user has same partner with application
        partnership_user = PartnershipUser.objects.filter(
            user_id=user_id,
        ).first()
        partner_id = partnership_user.partner.id
        if partner_id != application.partner.id:
            return mf_error_response(
                status=HTTP_403_FORBIDDEN,
                message="Maaf, akses ditolak",
            )

        # Validate application status
        eligible_status = {
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        }
        if application.status not in eligible_status:
            return mf_error_response(
                status=status.HTTP_400_BAD_REQUEST,
                message=WebAppErrorMessage.APPLICATION_STATUS_NOT_VALID,
            )

        # Validate data
        serializer = self.serializer(data=request.data, context={'application_id': application.id})
        if not serializer.is_valid():
            return mf_error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=serializer.errors,
            )

        validated_data = serializer.validated_data

        # Validated required field based on application status
        # For x100: 'ktp', 'ktp_selfie', 'agent_with_merchant_selfie'
        # For x131 based on reject reason on partnership application data
        field_name_mapping = {
            'ktp': "Dokumen Foto KTP",
            'ktp_selfie': "Dokumen Foto Selfie + KTP",
            'agent_with_merchant_selfie': "Dokumen Foto Agent + Merchant",
            'npwp': "Dokumen Foto NPWP",
            'nib': "Dokumen Foto NIB",
            'cashflow_report': "Dokumen Laporan Arus Kas",
            'company_photo': "Dokumen Foto Tempat Usaha",
        }
        error_required = {}
        if application.status == ApplicationStatusCodes.FORM_CREATED:
            required_files = {'ktp', 'ktp_selfie', 'agent_with_merchant_selfie'}
            for file in required_files:
                if not validated_data.get(file):
                    message = "{} tidak boleh kosong".format(field_name_mapping.get(file))
                    error_required[file] = [message]

        elif application.status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
            reject_reason = (
                PartnershipApplicationData.objects.filter(application_id=application_id)
                .values_list("reject_reason", flat=True)
                .last()
            )
            required_files = reject_reason.get('resubmit_document', [])
            for file in required_files:
                if not validated_data.get(file):
                    message = "{} tidak boleh kosong".format(field_name_mapping.get(file))
                    error_required[file] = [message]

        # Return error if there are missing required field
        if error_required:
            return mf_error_response(
                status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                errors=error_required,
            )

        try:
            resubmit_image_id_list = []
            resubmit_image_type_list = []

            # Activate ktp file
            if validated_data.get('ktp'):
                ktp_file = PartnershipImage.objects.filter(pk=validated_data.get('ktp')).last()
                ktp_file.update_safely(image_status=PartnershipImageStatus.ACTIVE)
                resubmit_image_id_list.append(ktp_file.id)
                resubmit_image_type_list.append(ktp_file.image_type)

            # Activate ktp+selfie file
            if validated_data.get('ktp_selfie'):
                ktp_selfie_file = PartnershipImage.objects.filter(
                    pk=validated_data.get('ktp_selfie')
                ).last()
                ktp_selfie_file.update_safely(image_status=PartnershipImageStatus.ACTIVE)
                resubmit_image_id_list.append(ktp_selfie_file.id)
                resubmit_image_type_list.append(ktp_selfie_file.image_type)

            # Activate npwp file
            if validated_data.get('npwp'):
                npwp_file = PartnershipImage.objects.filter(pk=validated_data.get('npwp')).last()
                npwp_file.update_safely(image_status=PartnershipImageStatus.ACTIVE)
                resubmit_image_id_list.append(npwp_file.id)
                resubmit_image_type_list.append(npwp_file.image_type)

            # Activate nib file
            if validated_data.get('nib'):
                nib_file = PartnershipImage.objects.filter(pk=validated_data.get('nib')).last()
                nib_file.update_safely(image_status=PartnershipImageStatus.ACTIVE)
                resubmit_image_id_list.append(nib_file.id)
                resubmit_image_type_list.append(nib_file.image_type)

            # Activate agent with merchant selfie file
            if validated_data.get('agent_with_merchant_selfie'):
                agent_with_merchant_selfie = PartnershipImage.objects.filter(
                    pk=validated_data.get('agent_with_merchant_selfie')
                ).last()
                agent_with_merchant_selfie.update_safely(image_status=PartnershipImageStatus.ACTIVE)
                resubmit_image_id_list.append(agent_with_merchant_selfie.id)
                resubmit_image_type_list.append(agent_with_merchant_selfie.image_type)

            # Activate cashflow report file
            resubmit_document_id_list = []
            if validated_data.get('cashflow_report'):
                for file_id in validated_data.get('cashflow_report'):
                    cashflow_report = PartnershipDocument.objects.filter(pk=file_id).last()
                    cashflow_report.update_safely(document_status=PartnershipDocument.CURRENT)
                    resubmit_document_id_list.append(cashflow_report.id)

            # Activate company photo file
            if validated_data.get('company_photo'):
                for file_id in validated_data.get('company_photo'):
                    company_photo = PartnershipImage.objects.filter(pk=file_id).last()
                    company_photo.update_safely(image_status=PartnershipImageStatus.ACTIVE)
                    resubmit_image_id_list.append(company_photo.id)
                resubmit_image_type_list.append('company_photo')

            if application.status == ApplicationStatusCodes.FORM_CREATED:
                process_application_status_change(
                    application_id,
                    ApplicationStatusCodes.FORM_PARTIAL,
                    change_reason="agent_triggered",
                )
            elif application.status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
                process_application_status_change(
                    application_id,
                    ApplicationStatusCodes.APPLICATION_RESUBMITTED,
                    change_reason="agent_triggered",
                )

                # Remove resubmission list from reject reason
                partnership_application_data = PartnershipApplicationData.objects.filter(
                    application_id=application_id
                ).last()
                reject_reason = partnership_application_data.reject_reason
                del reject_reason['resubmit_document']

                partnership_application_data.reject_reason.update(reject_reason)
                partnership_application_data.save(update_fields=['reject_reason'])

            # mark all other images with same application as 'deleted'
            marked_images = []
            images = PartnershipImage.objects.filter(
                application_image_source=application_id, image_type__in=resubmit_image_type_list
            ).exclude(id__in=resubmit_image_id_list)
            for image in images:
                image.image_status = PartnershipImageStatus.INACTIVE
                marked_images.append(image)

            bulk_update(marked_images, update_fields=["image_status"], using='partnership_db')

            # mark all other document with same application as 'deleted'
            if len(resubmit_document_id_list) > 0:
                marked_documents = []
                documents = PartnershipDocument.objects.filter(
                    document_source=application_id, document_type='cashflow_report'
                ).exclude(id__in=resubmit_document_id_list)
                for document in documents:
                    document.document_status = PartnershipDocument.DELETED
                    marked_documents.append(document)

                bulk_update(
                    marked_documents, update_fields=["image_status"], using='partnership_db'
                )

            return mf_success_response(status=HTTP_204_NO_CONTENT)

        except Exception as e:
            logger.error(
                {
                    "action": "mf_standard_submit_file_view",
                    "application_id": application_id,
                    "data": request.data,
                    "error": str(e),
                }
            )
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR, message="Gagal submit file"
            )


class GetApplicationFileByTypeView(MFStandardAPIView):
    @require_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application_id = self.kwargs.get('application_id')
        file_type = self.kwargs.get('type')
        application = Application.objects.filter(
            id=application_id, product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        ).exists()

        if not application:
            return mf_error_response(
                status=status.HTTP_404_NOT_FOUND, message=WebAppErrorMessage.APPLICATION_NOT_FOUND
            )

        # reformat type parameter since the key use as snake_case
        if '-' in file_type:
            file_type = file_type.replace('-', '_')

        merchant_risk_assessment_result = (
            MerchantRiskAssessmentResult.objects.filter(
                application_id=application_id, name=file_type
            )
            .values('risk', 'notes')
            .last()
        )

        # process get file and mapping response
        if file_type in {'cashflow_report', 'company_photo'}:
            # handle response for multiple file
            files = list()
            risk_assessment = None
            if merchant_risk_assessment_result:
                risk_assessment = {
                    "notes": merchant_risk_assessment_result.get('notes'),
                    "risk": merchant_risk_assessment_result.get('risk'),
                }

            if file_type == 'cashflow_report':
                document_files = PartnershipDocument.objects.filter(
                    document_status=PartnershipDocument.CURRENT,
                    document_source=application_id,
                    document_type=file_type,
                )
                if document_files:
                    for document_file in document_files:
                        file_path = document_file.url
                        file_url = get_oss_presigned_url_external(
                            settings.OSS_MEDIA_BUCKET, file_path
                        )
                        data = {
                            "file_id": document_file.id,
                            "file_name": file_path.split("/")[-1],
                            "file_url": file_url,
                        }
                        files.append(data)
                result = {
                    'file': files,
                    'risk_assessment': risk_assessment,
                }
                return mf_success_response(data=result)

            elif file_type == 'company_photo':
                image_files = PartnershipImage.objects.filter(
                    image_status=PartnershipImageStatus.ACTIVE,
                    application_image_source=application_id,
                    image_type=file_type,
                )
                if image_files:
                    for image_file in image_files:
                        file_path = image_file.url
                        file_url = get_oss_presigned_url_external(
                            settings.OSS_MEDIA_BUCKET, file_path
                        )
                        data = {
                            "file_id": image_file.id,
                            "file_name": file_path.split("/")[-1],
                            "file_url": file_url,
                        }
                        files.append(data)
                result = {
                    'file': files,
                    'risk_assessment': risk_assessment,
                }
                return mf_success_response(data=result)
        else:
            # handle response single file
            file_data = None
            risk_assessment = None
            image_file = PartnershipImage.objects.filter(
                image_status=PartnershipImageStatus.ACTIVE,
                application_image_source=application_id,
                image_type=file_type,
            ).last()

            if image_file:
                file_path = image_file.url
                file_url = get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, file_path)
                file_data = {
                    "file_id": image_file.id,
                    "file_name": file_path.split("/")[-1],
                    "file_url": file_url,
                }

            if merchant_risk_assessment_result:
                risk_assessment = {
                    "notes": merchant_risk_assessment_result.get('notes'),
                    "risk": merchant_risk_assessment_result.get('risk'),
                }

            result = {
                'file': file_data,
                'risk_assessment': risk_assessment,
            }
            return mf_success_response(data=result)


class GetMerchantFileView(MFStandardAPIView):
    @require_partner_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any):
        application_xid = self.kwargs.get('application_xid')
        file_type = self.kwargs.get('file_type')
        file_id = self.kwargs.get('file_id')

        user = request.user_obj
        user_id = user.id

        try:

            # Validate if application exists
            application = (
                Application.objects.filter(
                    application_xid=int(application_xid),
                    product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
                )
                .values('id', 'partner_id')
                .last()
            )
            if not application:
                return mf_error_response(
                    status=HTTP_404_NOT_FOUND,
                    message="Aplikasi tidak ditemukan",
                )

            application_id = application.get('id')

            # Validate if user has same partner with application
            partnership_user = PartnershipUser.objects.filter(
                user_id=user_id,
            ).first()
            partner_id = partnership_user.partner.id
            if partner_id != application.get('partner_id'):
                return mf_error_response(
                    status=HTTP_403_FORBIDDEN,
                    message="Maaf, akses ditolak",
                )

            if file_type == 'image':
                image_file = PartnershipImage.objects.filter(
                    pk=file_id,
                    image_status=PartnershipImageStatus.ACTIVE,
                    application_image_source=application_id,
                ).last()
                if not image_file:
                    return mf_error_response(
                        status=HTTP_404_NOT_FOUND,
                        message="File tidak ditemukan",
                    )

                file_path = image_file.url
                file_url = get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, file_path)
                data = {
                    "file_id": file_id,
                    "file_name": file_path.split("/")[-1],
                    "file_url": file_url,
                }
                return mf_success_response(data=data)

            elif file_type == 'document':
                document = PartnershipDocument.objects.filter(
                    pk=file_id,
                    document_status=PartnershipDocument.CURRENT,
                    document_source=application_id,
                ).last()
                if not document:
                    return mf_error_response(
                        status=HTTP_404_NOT_FOUND,
                        message="File tidak ditemukan",
                    )

                file_path = document.url
                file_url = get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, file_path)
                data = {
                    "file_id": file_id,
                    "file_name": file_path.split("/")[-1],
                    "file_url": file_url,
                }
                return mf_success_response(data=data)

        except Exception as e:
            logger.error(
                {
                    "action": "mf_standard_get_file_view",
                    "application_xid": application_xid,
                    "file_type": file_type,
                    "file_id": file_id,
                    "error": str(e),
                }
            )
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR, message="Gagal mendapatkan file"
            )


class GetApplicationFileView(MFStandardAPIView):
    @require_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any):
        application_id = self.kwargs.get('application_id')
        file_type = self.kwargs.get('file_type')
        file_id = self.kwargs.get('file_id')

        try:

            # Validate if application exists
            application = Application.objects.filter(
                id=application_id,
                product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
            ).exists()
            if not application:
                return mf_error_response(
                    status=HTTP_404_NOT_FOUND,
                    message="Aplikasi tidak ditemukan",
                )

            if file_type == 'image':
                image_file = PartnershipImage.objects.filter(
                    pk=file_id,
                    image_status=PartnershipImageStatus.ACTIVE,
                    application_image_source=application_id,
                ).last()
                if not image_file:
                    return mf_error_response(
                        status=HTTP_404_NOT_FOUND,
                        message="File tidak ditemukan",
                    )

                file_path = image_file.url
                file_url = get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, file_path)
                data = {
                    "file_id": file_id,
                    "file_name": file_path.split("/")[-1],
                    "file_url": file_url,
                }
                return mf_success_response(data=data)

            elif file_type == 'document':
                document = PartnershipDocument.objects.filter(
                    pk=file_id,
                    document_status=PartnershipDocument.CURRENT,
                    document_source=application_id,
                ).last()
                if not document:
                    return mf_error_response(
                        status=HTTP_404_NOT_FOUND,
                        message="File tidak ditemukan",
                    )

                file_path = document.url
                file_url = get_oss_presigned_url_external(settings.OSS_MEDIA_BUCKET, file_path)
                data = {
                    "file_id": file_id,
                    "file_name": file_path.split("/")[-1],
                    "file_url": file_url,
                }
                return mf_success_response(data=data)

            else:
                return mf_error_response(
                    status=HTTP_400_BAD_REQUEST,
                    message="Tipe file tidak valid",
                )

        except Exception as e:
            logger.error(
                {
                    "action": "mf_standard_get_file_view",
                    "application_id": application_id,
                    "file_type": file_type,
                    "file_id": file_id,
                    "error": str(e),
                }
            )
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR, message="Gagal mendapatkan file"
            )


class ApplicationDetailViewV2(MFStandardAPIView):
    @require_agent_role
    @require_mf_api_v2
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application_id = self.kwargs.get('application_id')

        application_data = (
            Application.objects.filter(
                id=application_id, product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
            )
            .select_related('customer')
            .values(
                'id',
                'product_line_id',
                'company_name',
                'monthly_income',
                'dob',
                'birth_place',
                'marital_status',
                'gender',
                'address_street_num',
                'address_provinsi',
                'address_kabupaten',
                'address_kecamatan',
                'address_kelurahan',
                'address_kodepos',
                'last_education',
                'application_status_id',
                'home_status',
                'close_kin_name',
                'close_kin_mobile_phone',
                'kin_name',
                'kin_mobile_phone',
                'number_of_employees',
                'monthly_expenses',
                'bank_name',
                'bank_account_number',
                'partner__name',
                'customer__customer_xid',
            )
            .last()
        )

        if not application_data:
            return mf_error_response(
                status=status.HTTP_404_NOT_FOUND, message=WebAppErrorMessage.APPLICATION_NOT_FOUND
            )

        partnership_application_data_query = PartnershipApplicationData.objects.filter(
            application_id=application_data['id']
        )
        partnership_application_data = partnership_application_data_query.values(
            'proposed_limit',
            'business_duration',
            'business_category',
            'product_line',
            'business_type',
            'reject_reason',
        ).last()

        merchant_status = mapping_merchant_financing_standard_status(
            application_data['application_status_id']
        )

        dob = None
        if application_data['dob']:
            convert_dob = datetime.combine(application_data['dob'], time.min)
            dob = timezone.localtime(convert_dob)

        reject_reason_data = partnership_application_data['reject_reason']
        if reject_reason_data and reject_reason_data.get('rejected_notes'):
            risk_status = reject_reason_data.get('rejected_notes')
        else:
            risk_status = [
                {
                    "name": MFStandardRejectReason.CLEAR.get('name'),
                    "label": MFStandardRejectReason.CLEAR.get('label'),
                }
            ]

        credit_score = (
            CreditScore.objects.filter(application_id=application_id)
            .values_list('score', flat=True)
            .last()
        )

        # Detokenize partnership application data
        customer_xid = application_data.get('customer__customer_xid')
        partnership_application_data_obj = partnership_application_data_query.last()
        detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_APPLICATION_DATA,
            partnership_application_data_obj,
            customer_xid,
            ['fullname', 'mobile_phone_1', 'email'],
        )

        # Detokenize partnership customer data
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            application_id=application_data['id']
        ).last()
        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            customer_xid,
            ['nik'],
        )

        data = {
            'application_id': application_id,
            'fullname': detokenize_partnership_application_data.fullname,
            'company_name': application_data['company_name'],
            'monthly_income': application_data['monthly_income'],
            'business_category': partnership_application_data['business_category'],
            'limit': partnership_application_data['proposed_limit'],
            'business_duration': partnership_application_data['business_duration'],
            'product_line': application_data['product_line_id'],
            'email': detokenize_partnership_application_data.email,
            'phone_number': detokenize_partnership_application_data.mobile_phone_1,
            'dob': dob,
            'birth_place': application_data['birth_place'],
            'marital_status': application_data['marital_status'],
            'gender': application_data['gender'],
            'address': application_data['address_street_num'],
            'address_province': application_data['address_provinsi'],
            'address_regency': application_data['address_kabupaten'],
            'address_district': application_data['address_kecamatan'],
            'address_subdistrict': application_data['address_kelurahan'],
            'address_zipcode': application_data['address_kodepos'],
            'nik': detokenize_partnership_customer_data.nik,
            'last_education': application_data['last_education'],
            'application_status': application_data['application_status_id'],
            'merchant_status': merchant_status,
            'home_status': application_data['home_status'],
            'close_kin_name': application_data['close_kin_name'],
            'close_kin_phone_number': application_data['close_kin_mobile_phone'],
            'kin_name': application_data['kin_name'],
            'kin_phone_number': application_data['kin_mobile_phone'],
            'business_type': partnership_application_data['business_type'],
            'total_employee': application_data['number_of_employees'],
            'monthly_expenses': application_data['monthly_expenses'],
            'bank_name': application_data['bank_name'],
            'bank_account_number': application_data['bank_account_number'],
            'partner_name': application_data['partner__name'],
            'fdc_status': get_fdc_data_for_application_v2(application_id),
            'risk_status': risk_status,
            'credit_score': credit_score,
            # TO DO LIST
            # for now we hardcoded the documents into list of object
            # later on we need to create a config for this to be adjustable
            # we also need to change this on Merchant Detail View
            'documents': [
                {
                    'name': "ktp",
                    'label': "Foto KTP",
                    'fileType': "image",
                },
                {
                    'name': "ktpSelfie",
                    'label': "Foto Selfie + KTP",
                    'fileType': "image",
                },
                {
                    'name': "npwp",
                    'label': "Foto NPWP",
                    'fileType': "image",
                },
                {
                    'name': "nib",
                    'label': "Foto NIB",
                    'fileType': "image",
                },
                {
                    'name': "agentWithMerchantSelfie",
                    'label': "Foto Agent + Merchant",
                    'fileType': "image",
                },
                {
                    'name': "companyPhoto",
                    'label': "Foto Tempat Usaha",
                    'fileType': "image",
                },
                {
                    'name': "cashflowReport",
                    'label': "Laporan Arus Kas",
                    'fileType': "document",
                },
            ],
        }

        return mf_success_response(data=data)


class ApproveRejectViewV2(MFStandardAPIView):
    serializer_class = ApproveRejectSerializer

    @require_mf_api_v2
    @require_agent_role
    def post(self, request: Request, *args, **kwargs) -> Response:
        if self.kwargs["action_type"] == "approve":
            new_status_code = ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
            title_message = 'disetujui'
            process_message = 'persetujuan'
        else:
            new_status_code = ApplicationStatusCodes.APPLICATION_DENIED
            title_message = 'ditolak'
            process_message = 'penolakan'

        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return mf_error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=serializer.errors,
                )

            partnership_application_datas = serializer.initial_data["partnership_application_datas"]
            mf_standard_async_config = (
                FeatureSetting.objects.filter(
                    feature_name=MFFeatureSetting.MF_STANDARD_ASYNC_CONFIG,
                    is_active=True,
                )
                .values_list("parameters", flat=True)
                .last()
            )

            success_application_ids = []
            error_application_ids = []
            for partnership_application_data in partnership_application_datas.iterator():
                if not partnership_application_data.get('risk_assessment_check', False):
                    error_application_ids.append(partnership_application_data.get('application_id'))
                    continue

                if mf_standard_async_config and mf_standard_async_config.get(
                    MFFeatureSetting.MF_STANDARD_APPROVE_REJECT_ASYNC_CONFIG
                ):
                    partnership_application_status_change_async_process.delay(
                        partnership_application_data.get('application_id'),
                        new_status_code,
                        change_reason="agent_triggered",
                    )
                else:
                    process_application_status_change(
                        partnership_application_data.get('application_id'),
                        new_status_code,
                        change_reason="agent_triggered",
                    )
                success_application_ids.append(partnership_application_data.get('application_id'))

            if error_application_ids:
                if success_application_ids:
                    response_data = {
                        'title': 'Sebagian Pengajuan Berhasil {}'.format(
                            title_message.capitalize()
                        ),
                        'description': 'Hanya <b>{} dari {}</b> pengajuan yang berhasil {} '
                        'karena sudah melalui penilaian risiko'.format(
                            len(success_application_ids),
                            len(partnership_application_datas),
                            title_message,
                        ),
                    }
                    return mf_success_response(
                        status=PartnershipHttpStatusCode.HTTP_207_MULTI_STATUS,
                        data=response_data,
                        meta={
                            'success_application_ids': success_application_ids,
                            'error_application_ids': error_application_ids,
                        },
                    )
                else:
                    response_data = {
                        'title': 'Pengajuan Gagal {}'.format(title_message.capitalize()),
                        'description': 'Pastikan kamu sudah melakukan penilaian risiko untuk lanjut'
                        ' ke proses {}, ya.'.format(process_message),
                    }
                    return mf_error_response(
                        status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                        data=response_data,
                    )

            response_data = {
                'title': 'Pengajuan Berhasil {}'.format(title_message.capitalize()),
                'description': 'Pengajuan merchant ini sekarang bisa dilihat di tab '
                '<b>Status Pengajuan</b> dalam tab <b>{}.</b>'.format(title_message.capitalize()),
            }

            return mf_success_response(data=response_data)

        except Exception as e:
            application_ids = request.data.get('application_ids', [])
            response_data = {
                'title': 'Pengajuan Gagal {}'.format(title_message.capitalize()),
                'description': 'Pastikan koneksi internetmu baik lalu ulangi prosesnya, ya.',
            }
            logger.error(
                {
                    "action": "ApproveRejectViewV2",
                    "application_ids": application_ids,
                    "error": str(e),
                }
            )
            return mf_error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                data=response_data,
            )


class ApplicationRiskAssessmentView(MFStandardAPIView):
    """
    This API for create / update application risk assessment data
    then create CreditScore record base on risk assessment result
    """

    serializer = ApplicationRiskAssessmentSerializer

    @require_agent_role
    @require_mf_api_v2
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application_id = self.kwargs.get('application_id')

        try:
            application = (
                Application.objects.filter(
                    id=application_id,
                    product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
                )
                .values('application_status_id')
                .last()
            )
            if not application:
                return mf_error_response(
                    status=HTTP_404_NOT_FOUND,
                    message=WebAppErrorMessage.APPLICATION_NOT_FOUND,
                )

            partnership_application_data = PartnershipApplicationData.objects.filter(
                application_id=application_id
            ).last()
            if not partnership_application_data:
                return mf_error_response(
                    status=HTTP_404_NOT_FOUND,
                    message=WebAppErrorMessage.APPLICATION_NOT_FOUND,
                )

            allowed_statuses = {
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            }
            if application.get('application_status_id') not in allowed_statuses:
                return mf_error_response(
                    status=HTTP_400_BAD_REQUEST,
                    message=WebAppErrorMessage.APPLICATION_STATUS_NOT_VALID,
                )

            # Validate data
            serializer = self.serializer(data=request.data)
            if not serializer.is_valid():
                return mf_error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=serializer.errors,
                )

            with transaction.atomic():
                high_risk_count = 0
                validated_data = serializer.validated_data
                for file_type in validated_data:
                    file = validated_data.get(file_type)
                    risk = file.get('risk')
                    notes = file.get('notes')

                    if risk == 'high':
                        high_risk_count += 1

                    MerchantRiskAssessmentResult.objects.update_or_create(
                        application_id=application_id,
                        name=file_type,
                        defaults={'risk': risk, 'notes': notes},
                    )

                partnership_application_data.update_safely(risk_assessment_check=True)

                # generate credit score based on risk assessment result
                # Credit Score Rules:
                # A -> High risk count == 0
                # B -> High risk count == 1 or 2
                # C -> High risk count >= 3
                if high_risk_count == 0:
                    credit_score = 'A'
                elif high_risk_count in {1, 2}:
                    credit_score = 'B'
                else:
                    credit_score = 'C'

                CreditScore.objects.update_or_create(
                    application_id=application_id, defaults={'score': credit_score}
                )

            return mf_success_response(status=HTTP_204_NO_CONTENT)

        except Exception as e:
            logger.error(
                {
                    "action": "mf_standard_app_risk_assessment_view",
                    "application_id": application_id,
                    "data": request.data,
                    "error": str(e),
                }
            )
            return mf_error_response(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                message="Gagal melakukan risk assessment",
            )


class LimitAdjustmentViewV2(MFStandardAPIView):
    serializer_class = LimitAdjustmentSerializer

    @require_mf_api_v2
    @require_agent_role
    def post(self, request: Request, *args, **kwargs) -> Response:
        try:
            serializer = self.serializer_class(data=request.data)

            if not serializer.is_valid():
                return mf_error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=serializer.errors,
                )

            limit_amount = serializer.validated_data["limit"]
            application_id = self.kwargs["application_id"]

            application_status = (
                Application.objects.filter(
                    id=application_id,
                    product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
                )
                .values_list('application_status_id', flat=True)
                .last()
            )
            if not application_status:
                logger.error(
                    {
                        "action": "LimitAdjustmentViewV2",
                        "message": "Failed adjust limit",
                        "application_id": application_id,
                    }
                )
                return mf_error_response(
                    status=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessageConst.APPLICATION_NOT_FOUND,
                )

            if application_status not in {
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            }:
                logger.error(
                    {
                        "action": "LimitAdjustmentViewV2",
                        "message": "Failed adjust limit",
                        "application_id": application_id,
                        "application_status": application_status,
                    }
                )
                return mf_error_response(message=ErrorMessageConst.APPLICATION_STATUS_NOT_VALID)

            partner_application_data = PartnershipApplicationData.objects.filter(
                application=application_id
            ).last()

            if not partner_application_data.risk_assessment_check:
                errors_response = {'limit': ['Harap melakukan risk assessment terlebih dahulu']}

                return mf_error_response(
                    status=PartnershipHttpStatusCode.HTTP_422_UNPROCESSABLE_ENTITY,
                    errors=errors_response,
                )

            partner_application_data.proposed_limit = limit_amount
            partner_application_data.save()

            return mf_success_response(status=HTTP_204_NO_CONTENT)

        except Exception as e:
            logger.error({"action": "LimitAdjustmentViewV2", "error": str(e)})
            return mf_error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessageConst.GENERAL_ERROR,
            )

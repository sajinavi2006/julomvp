import logging

from django.http import (
    Http404,
    JsonResponse,
)
from django.shortcuts import render
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication

from app_status.views import ApplicationDataWSCListView

from juloserver.account.models import Account
from juloserver.fraud_security.models import FraudBlockAccount
from juloserver.fraud_security.constants import FraudApplicationBucketType, DeviceConst
from juloserver.fraud_security.services import (
    fetch_blacklist_whitelist_records,
    fetch_geohash_applications,
    fetch_unchecked_geohashes,
    process_and_save_whitelist_blacklist_data,
    update_and_record_geohash_result_check,
    update_fraud_block_account_by_agent,
)
from juloserver.fraud_security.serializers import (
    BlacklistWhitelistAddSerializer,
    GeohashApplicationSerializer,
    GeohashBucketSerializer,
    GeohashUpdateStatusSerializer,
    DeviceIdentityRequestSerializer,
    FraudBlockAccountResponse,
    FraudBlockAccountRequest,
)
from juloserver.fraud_security.pagination import GeohashCRMPagination
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Application,
    Device,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.portal.object import (
    julo_login_req_group,
    julo_login_required,
    julo_login_required_group,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    internal_server_error_response,
)
from juloserver.new_crm.utils import crm_permission
from juloserver.portal.object.dashboard.constants import JuloUserRoles

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@julo_login_required
@julo_login_req_group('fraudops')
def fraud_security_page_view(request):
    if request.method == "GET":
        query = request.GET.get("query", '')
        template_name = 'fraud_security/security.html'
        result_list = fetch_blacklist_whitelist_records(query)
        context = {
            "query": query,
            "device_list": result_list,
        }
        return render(request, template_name=template_name, context=context)
    elif request.method == "POST":
        try:
            serializer = BlacklistWhitelistAddSerializer(data=request.POST)
            if serializer.is_valid():
                data = serializer.validated_data
                success, error_message = process_and_save_whitelist_blacklist_data(data)
                return JsonResponse(
                    {
                        "status": "success" if success else "failure",
                        "errors": None,
                        "error_message": error_message,
                    }
                )
            else:
                return JsonResponse(
                    {
                        "status": "failure",
                        "error_message": "Please check your input. Some data are invalid",
                        "errors": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            logger.exception(
                {
                    "action": "process_and_save_whitelist_blacklist_data",
                    "message": "Exception during save",
                    "exc_str": str(e),
                }
            )
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return JsonResponse(
                {
                    "status": "failure",
                    "error_message": "Terjadi kesalahan pada server (500)",
                    "errors": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GeohashCRMView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GeohashBucketSerializer
    authentication_classes = [SessionAuthentication]
    pagination_class = GeohashCRMPagination
    permission_classes = [crm_permission([JuloUserRoles.FRAUD_OPS])]

    def get(self, request):
        search_q = request.GET.get('search_q')
        sort_q = request.GET.get('sort_q')
        data = fetch_unchecked_geohashes(search_q, sort_q)
        paginator = self.pagination_class()
        result_page = paginator.paginate_queryset(data, request)
        serializer = self.serializer_class(result_page, many=True)
        data = {"data": serializer.data, "total_count": data.count()}
        return paginator.get_paginated_response(data)

    def post(self, request):
        update_status_serializer = GeohashUpdateStatusSerializer(data=request.data)
        update_status_serializer.is_valid(raise_exception=True)
        update_and_record_geohash_result_check(
            update_status_serializer.validated_data, request.user
        )
        return success_response()


class GeohashApplicationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GeohashApplicationSerializer
    authentication_classes = [SessionAuthentication]
    pagination_class = GeohashCRMPagination
    permission_classes = [crm_permission([JuloUserRoles.FRAUD_OPS])]

    def get(self, request):
        bucket_id = request.GET.get('bucket_id')
        if not bucket_id:
            return general_error_response("Field 'bucket_id' is required")
        search_q = request.GET.get('search_q')
        sort_q = request.GET.get('sort_q')
        data = fetch_geohash_applications(bucket_id, search_q, sort_q)
        paginator = self.pagination_class()
        result_page = paginator.paginate_queryset(data, request)
        serializer = self.serializer_class(result_page, many=True)
        data = {"data": serializer.data, "total_count": data.count()}
        return paginator.get_paginated_response(data)


@julo_login_required
@julo_login_required_group('fraudops')
class FraudApplicationList(ApplicationDataWSCListView):
    """
    List of application that is in x115. The filter based on bucket_type defined in
    FraudApplicationBucketType. The application list is obtained from FraudApplicationBucket model.
    """

    @property
    def request_bucket_code(self):
        return self.request.resolver_match.kwargs.get('bucket_type')

    def get_queryset(self):
        self.status_code = str(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS)
        self.qs = super(FraudApplicationList, self).get_queryset()
        self.qs = self.qs.filter(
            fraudapplicationbucket__is_active=True,
            fraudapplicationbucket__type=self.request_bucket_code,
        ).distinct()
        return self.qs

    def get_context_data(self, **kwargs):
        context = super(FraudApplicationList, self).get_context_data(**kwargs)
        context['status_code_now'] = FraudApplicationBucketType.label(self.request_bucket_code)

        return context

    def validate_bucket_code(self):
        if self.request_bucket_code not in FraudApplicationBucketType.all_types():
            raise Http404('Bucket [{}] tidak terdaftar'.format(self.request_bucket_code))


class DeviceIdentityView(APIView):
    serializer_class = DeviceIdentityRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        julo_device_id = data.get(DeviceConst.JULO_DEVICE_ID)
        customer = request.user.customer
        if not julo_device_id:
            return general_error_response("julo_device_id is empty")
        Device.objects.create(customer=customer, julo_device_id=julo_device_id)
        return success_response({"message": "Success store device identity"})


class FraudBlockAccountView(APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = FraudBlockAccountResponse

    def get(self, request):
        try:
            account_id = request.query_params.get('account_id', None)
            if not account_id:
                return general_error_response("account_id is empty")
            try:
                int(account_id)
            except Exception as e:
                logger.error("FraudBlockAccountView get, error :  " + str(e))
                return general_error_response("account_id must be a number")

            account = Account.objects.filter(id=account_id).last()
            if not account:
                return general_error_response("account not found")

            fraud_block_account = FraudBlockAccount.objects.filter(account=account).last()
            if not fraud_block_account:
                return success_response([])

            return success_response(self.serializer_class(fraud_block_account).data)
        except Exception as e:
            sentry_client.captureException()
            logger.error("FraudBlockAccountView get, error :  " + str(e))
            return internal_server_error_response(str(e))

    def post(self, request):
        try:
            fraud_block_request = FraudBlockAccountRequest(data=request.data)
            fraud_block_request.is_valid(raise_exception=True)

            account_id = fraud_block_request.validated_data['account_id']
            account = Account.objects.filter(id=account_id).last()
            if not account:
                return general_error_response("account not found")

            application_id = fraud_block_request.validated_data['application_id']
            application = Application.objects.filter(id=application_id).last()
            if not application:
                return general_error_response("application not found")
            if not application.is_julo_one() and not application.is_julo_starter():
                return general_error_response("application is not julo one or jturbo")
            if application.account.id != account.id:
                return general_error_response("account and application is not match")

            is_appeal = fraud_block_request.validated_data['is_appeal']
            is_confirmed_fraud = fraud_block_request.validated_data['is_confirmed_fraud']

            if not is_appeal and is_confirmed_fraud:
                return general_error_response("invalid request")

            fraud_block_account = FraudBlockAccount.objects.filter(account=account).last()
            if not fraud_block_account:
                return general_error_response("FraudBlockAccount not found")
            elif fraud_block_account.is_verified_by_agent:
                return general_error_response("you can't edit this account anymore")

            fraud_block_account = update_fraud_block_account_by_agent(
                fraud_block_account, application, is_appeal, is_confirmed_fraud
            )

            return success_response(self.serializer_class(fraud_block_account).data)
        except Exception as e:
            sentry_client.captureException()
            logger.error("FraudBlockAccountView post, error :  " + str(e))
            return internal_server_error_response(str(e))

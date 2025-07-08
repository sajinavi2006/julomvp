import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import (
    Prefetch,
    Q,
)
from django.http.response import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import (
    ListAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from juloserver.crm.permissions import has_user_groups
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    AccountDeletionStatusChangeReasons,
    CustomerDataChangeRequestConst,
    CustomerRemovalDeletionTypes,
    InAppAccountDeletionMessagesConst,
    InAppAccountDeletionTitleConst,
    ConsentWithdrawal,
)
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    ConsentWithdrawalRequest,
    CustomerDataChangeRequest,
)
from juloserver.customer_module.serializers import (
    AccountDeletionHistorySerializer,
    AccountDeletionInAppHistorySerializer,
    AccountDeletionInAppSerializer,
    CustomerDeleteUpdatedDataSerializer,
    ConsentWithdrawalCurrentStatusSerializer,
    ConsentWithdrawalHistorySerializer,
    CRMSubmitConsentWithdrawalSerializer,
    CRMChangeStatusConsentWithdrawalSerializer,
    CustomerDataChangeRequestApprovalSerializer,
    CustomerDataChangeRequestCRMDetailSerializer,
    CustomerDataChangeRequestCRMSerializer,
    CustomerDataChangeRequestListSerializer,
    CustomerRemovalSerializer,
    DeleteCustomerSerializer,
    SearchCustomerSerializer,
    UpdateStatusOfAccountDeletionRequestSerializer,
    ConsentWithdrawalListRequestSerializer,
)
from juloserver.customer_module.services.account_deletion import (
    customer_deleteable_application_check,
    is_customer_manual_deletable,
    mark_request_deletion_manual_deleted,
    process_revert_applications_status_deletion,
)
from juloserver.customer_module.services.crm_v1 import (
    customer_deletion_process,
    customer_soft_deletion_process,
    process_revert_account_status_460,
    get_latest_withdrawal_requests,
    approval_consent_withdrawal,
)
from juloserver.customer_module.services.customer_related import (
    CustomerDataChangeRequestHandler,
    process_action_consent_withdrawal,
    request_consent_withdrawal,
)

from juloserver.customer_module.tasks.account_deletion_tasks import (
    send_rejected_deletion_request_success_email,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    check_if_customer_is_elgible_to_delete,
    get_active_loan_ids,
    get_customer_deletion_type,
    get_deletion_email_format,
    get_deletion_nik_format,
    get_deletion_phone_format,
    get_old_account_status,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from django.contrib.auth.models import User
from juloserver.julo.models import Application, Customer, CustomerRemoval
from juloserver.new_crm.utils import crm_permission
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    internal_server_error_response,
    not_found_response,
    success_response,
    unauthorized_error_response,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(["cs_admin"])
def dashboard_account_deletion_manual(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(("GET"))

    csrftoken = request.COOKIES.get('csrftoken', '')
    url = (
        settings.CRM_REVAMP_BASE_URL + 'dashboard/cs_admin/manual-deletion/?csrftoken=' + csrftoken
    )

    return redirect(url)


@julo_login_required
@julo_login_required_multigroup(["cs_admin"])
def dashboard_account_deletion_julo_app(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(("GET"))

    csrftoken = request.COOKIES.get('csrftoken', '')
    url = (
        settings.CRM_REVAMP_BASE_URL
        + 'dashboard/cs_admin/deletion-request-inapp/?csrftoken='
        + csrftoken
    )

    return redirect(url)


@julo_login_required
def dashboard_account_deletion_history(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(("GET"))

    csrftoken = request.COOKIES.get('csrftoken', '')
    url = (
        settings.CRM_REVAMP_BASE_URL
        + 'dashboard/account-deletion-histories/?csrftoken='
        + csrftoken
    )
    return redirect(url)


class LargeResultsSetPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'


class AccountDeletionInAppRequestPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class CustomerRemovalView(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = CustomerRemovalSerializer
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        filter_by = self.request.GET.get('filter_by')
        today = timezone.now().date()
        if filter_by == '10D':
            start_date = today - timedelta(days=10)
            end_date = today + timedelta(days=1)
        elif filter_by == '1M':
            start_date = today - timedelta(days=30)
            end_date = today + timedelta(days=1)
        elif filter_by == '2M':
            start_date = today - timedelta(days=60)
            end_date = today + timedelta(days=1)
        else:
            return CustomerRemoval.objects.order_by('-udate')
        return CustomerRemoval.objects.filter(udate__range=(start_date, end_date)).order_by(
            '-udate'
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return success_response(response.data)


class SearchCustomer(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = SearchCustomerSerializer
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response('masukkan customer atau application ID')

        app_or_customer_id = serializer.validated_data['app_or_customer_id']

        customer = Customer.objects.filter(pk=app_or_customer_id)
        applications = Application.objects.filter(pk=app_or_customer_id)

        if customer.exists():
            customer = customer.last()
            application = customer.last_application

        elif applications.exists():
            application = applications.last()
            customer = application.customer

        else:
            msg = {'title': "Akun tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)
        account = customer.account
        status_id = None
        if account:
            status_id = account.status_id
        data = {
            'active_loan_found': False,
            'user_id': customer.user.pk,
            'customer_id': customer.pk,
            'nik': customer.get_nik,
            'application_id': application.pk if application else None,
            'loan_ids': None,
            'customer_status': 'active',
            'account_status_id': status_id,
            'application_status_code': application.status if application else None,
            'show_delete_button': True,
            'is_soft_delete': False,
            'email': customer.get_email,
            'phone_number': customer.get_phone,
            'added_by': None,
        }

        loan_ids = get_active_loan_ids(customer)
        if not customer.user.is_active:
            customer_removal = CustomerRemoval.objects.filter(customer=customer).last()
            data.update({'customer_status': 'deleted', 'show_delete_button': False})
            if customer_removal:
                data.update(
                    {
                        'reason': customer_removal.reason,
                        'deleted_date': customer_removal.udate,
                        'added_by': customer_removal.added_by.username
                        if hasattr(customer_removal, 'added_by')
                        and customer_removal.added_by is not None
                        else None,
                    }
                )
            else:
                data.update(
                    {
                        'reason': None,
                        'deleted_date': None,
                    }
                )

        if loan_ids:
            data.update(
                {'active_loan_found': True, 'loan_ids': loan_ids, 'show_delete_button': False}
            )

        deletion_type = get_customer_deletion_type(customer)
        if deletion_type == CustomerRemovalDeletionTypes.SOFT_DELETE:
            data.update({'is_soft_delete': True})

        if data.get('show_delete_button'):
            is_manual_deleteable, _ = is_customer_manual_deletable(customer)
            if not is_manual_deleteable:
                data.update({'show_delete_button': False})

        if not customer_deleteable_application_check(customer) and data.get('show_delete_button'):
            data.update({'show_delete_button': False})

        return success_response(data=data)


class DeleteCustomerView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = DeleteCustomerSerializer
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        data = dict()
        if not serializer.is_valid():
            return general_error_response('Silakan periksa input kembali')

        customer_id = serializer.validated_data['customer_id']
        reason = serializer.validated_data['reason']

        customer = Customer.objects.filter(pk=customer_id).exclude(
            is_active=False, can_reapply=False
        )
        if not customer.exists():
            msg = {'title': "Akun tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        customer = customer.last()

        if customer.is_active is False and customer.can_reapply is False:
            data.update(
                {'msg': "Customer ID {} tidak ditemukan karena telah dihapus".format(customer.pk)}
            )
            return not_found_response(message=data)

        account = customer.account
        status_id = None

        if account:
            status_id = account.status_id

        applications = customer.application_set.all()
        application = applications.last()
        loan_ids = get_active_loan_ids(customer)

        nik = customer.get_nik
        phone = customer.get_phone
        email = customer.get_email

        if loan_ids:
            data.update(
                {
                    'title': 'Hapus Akun Gagal',
                    'msg': "Maaf, terjadi kesalahan di sistem. Silakan coba lagi.",
                }
            )
            logger.error(
                {
                    'method': 'delete_customer_account',
                    'data': data,
                    'loan_id': loan_ids,
                }
            )
            return general_error_response(message=data)

        if status_id:
            is_deletable, msg = is_customer_manual_deletable(customer)
            if not is_deletable:
                logger.warning(
                    {
                        'action': 'DeleteCustomerView',
                        'message': 'Customer cannot be deleted: {}'.format(msg),
                        'customer_id': customer.id,
                    },
                )
                data.update(
                    {
                        'title': 'Hapus Akun Gagal',
                        'msg': "akun tidak dapat dihapus",
                    }
                )
                return general_error_response(message=data)

        try:
            with transaction.atomic():
                deletion_type = get_customer_deletion_type(customer)
                if deletion_type == CustomerRemovalDeletionTypes.SOFT_DELETE:
                    data = customer_soft_deletion_process(
                        customer.user,
                        customer,
                        account,
                        nik,
                        phone,
                        email,
                        reason,
                    )
                else:
                    data = customer_deletion_process(
                        customer.user,
                        customer,
                        account,
                        nik,
                        phone,
                        email,
                        reason,
                    )
                mark_request_deletion_manual_deleted(request.user, customer, reason)

            if not data:
                return general_error_response(message='Akun tidak bisa di delete')

            logger.info(
                {
                    'method': 'delete_customer_account',
                    'data': data,
                }
            )
            return success_response(data)

        except JuloException as je:
            logger.exception(
                {
                    'method': 'delete_customer_account',
                    'data': data,
                    'error': str(je),
                }
            )
            data.update(
                {
                    'is_deleted': False,
                    'application_id': application.pk if application else None,
                    'customer_id': customer.pk,
                }
            )
            err_msg = {
                'title': 'Hapus Akun Gagal',
                'msg': "Maaf, user telah mencapai batas untuk hapus akun.",
            }
            return general_error_response(data=data, message=err_msg)

        except Exception as e:
            logger.exception(
                {
                    'method': 'delete_customer_account',
                    'data': data,
                    'error': str(e),
                }
            )
            data.update(
                {
                    'is_deleted': False,
                    'application_id': application.pk if application else None,
                    'customer_id': customer.pk,
                }
            )
            get_julo_sentry_client().captureException()
            err_msg = {
                'title': 'Hapus Akun Gagal',
                'msg': "Maaf, terjadi kesalahan di sistem. Silakan coba lagi.",
            }
            return internal_server_error_response(data=data, message=err_msg)


class GetCustomerDeleteUpdatedData(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = CustomerDeleteUpdatedDataSerializer
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        edited_data = dict()
        if not serializer.is_valid():
            return general_error_response('Silakan periksa input kembali')
        nik = serializer.validated_data.get('nik')
        email = serializer.validated_data.get('email')
        phone = serializer.validated_data.get('phone')
        customer_id = serializer.validated_data.get('customer_id')

        customer = Customer.objects.filter(pk=customer_id, is_active=True)

        if not customer.exists():
            msg = {'title': "Akun tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        try:
            if nik:
                edited_nik = get_deletion_nik_format(str(customer_id))
                edited_data.update({'nik': edited_nik})

            if email:
                edited_email = get_deletion_email_format(email, customer_id)
                edited_data.update({'email': edited_email})

            if phone:
                edited_phone = get_deletion_phone_format(customer_id)
                edited_data.update({'phone': edited_phone})
            return success_response(edited_data)

        except JuloException as je:
            logger.exception(
                {
                    'method': 'GetCustomerDeleteUpdatedData',
                    'data': request.data,
                    'error': str(je),
                }
            )

            err_msg = {
                'title': 'Hapus Akun Gagal',
                'msg': "Maaf, user telah mencapai batas untuk hapus akun.",
            }
            return general_error_response(message=err_msg)

        except Exception as e:
            logger.exception(
                {
                    'method': 'GetCustomerDeleteUpdatedData',
                    'data': request.data,
                    'error': str(e),
                }
            )
            get_julo_sentry_client().captureException()
            err_msg = {
                'title': 'Hapus Akun Gagal',
                'msg': "Maaf, terjadi kesalahan di sistem. Silakan coba lagi.",
            }
            return internal_server_error_response(message=err_msg)


class AccountDeleteMenuInApp(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = AccountDeletionInAppSerializer
    pagination_class = AccountDeletionInAppRequestPagination

    def get_queryset(self):
        data = (
            AccountDeletionRequest.objects.filter(
                request_status=AccountDeletionRequestStatuses.PENDING
            )
            .prefetch_related(
                Prefetch(
                    "customer__application_set",
                    to_attr="prefetched_applications",
                    queryset=Application.objects.order_by('-id'),
                ),
            )
            .order_by('cdate')
        )

        search = self.request.GET.get('search', None)
        if search is not None:
            # search by application id
            application = Application.objects.filter(id=search).first()
            if application:
                data = data.filter(customer__id=application.customer_id)
                return data

            # search by customer id
            data = data.filter(customer__id=search)

        return data

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response_count = response.data.get('count')
        if response_count == 0:
            return not_found_response(
                message={'title': 'Akun tidak ditemukan', 'msg': 'Coba lakukan pencarian kembali'}
            )

        return success_response(response.data)


class UpdateStatusOfAccountDeletionRequest(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = UpdateStatusOfAccountDeletionRequestSerializer
    http_method_names = ['post']

    def handle_reject_status(self, agent, customer, account_deletion_request, reason):
        account_deletion_request.update_safely(
            request_status=AccountDeletionRequestStatuses.REJECTED,
            verdict_reason=reason,
            verdict_date=datetime.now(),
            agent=agent,
        )
        if customer.account:
            process_revert_account_status_460(customer.account, reason)

        process_revert_applications_status_deletion(
            customer,
            AccountDeletionStatusChangeReasons.CANCELED_BY_AGENT,
            changed_by=agent,
        )

        send_rejected_deletion_request_success_email.delay(customer.id)

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(InAppAccountDeletionMessagesConst.INVALID_SERIALIZER)

        data = dict()
        customer_id = serializer.validated_data.get('customer_id')
        status = serializer.validated_data.get('status')
        reason = serializer.validated_data.get('reason')

        account_deletion = AccountDeletionRequest.objects.filter(
            customer_id=customer_id, request_status=AccountDeletionRequestStatuses.PENDING
        ).last()

        if not account_deletion:
            return general_error_response(InAppAccountDeletionMessagesConst.REQUEST_NOT_FOUND)

        customer = account_deletion.customer

        if customer.is_active is False:
            data.update(
                {'msg': InAppAccountDeletionMessagesConst.INACTIVE_CUSTOMER.format(customer.pk)}
            )
            return not_found_response(message=data)

        account = customer.account
        status_id = None
        try:
            status_id = get_old_account_status(account) if account else None
        except JuloException as e:
            return general_error_response(str(e))

        application = customer.application_set.last()

        with transaction.atomic():
            if status == AccountDeletionRequestStatuses.REJECTED:
                self.handle_reject_status(request.user, customer, account_deletion, reason)
                return success_response(
                    {
                        'title': InAppAccountDeletionTitleConst.REJECTED,
                        'msg': InAppAccountDeletionMessagesConst.REJECTED.format(customer_id),
                    }
                )

            eligible, error_data = check_if_customer_is_elgible_to_delete(
                customer, status_id, application
            )
            if not eligible:
                self.handle_reject_status(request.user, customer, account_deletion, reason)
                return general_error_response(error_data)

            account_deletion.update_safely(
                request_status=status,
                verdict_reason=reason,
                verdict_date=datetime.now(),
                agent=request.user,
            )
            return success_response(
                {
                    'title': InAppAccountDeletionTitleConst.APPROVED,
                    'msg': InAppAccountDeletionMessagesConst.APPROVED.format(customer_id),
                }
            )


class AccountDeleteMenuInAppHistory(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = AccountDeletionInAppHistorySerializer
    pagination_class = AccountDeletionInAppRequestPagination

    def get_queryset(self):
        data = (
            AccountDeletionRequest.objects.filter(
                request_status__in=(
                    AccountDeletionRequestStatuses.APPROVED,
                    AccountDeletionRequestStatuses.REJECTED,
                    AccountDeletionRequestStatuses.CANCELLED,
                    AccountDeletionRequestStatuses.SUCCESS,
                    AccountDeletionRequestStatuses.FAILED,
                    AccountDeletionRequestStatuses.REVERTED,
                    AccountDeletionRequestStatuses.MANUAL_DELETED,
                )
            )
            .prefetch_related(
                Prefetch(
                    "customer__application_set",
                    to_attr="prefetched_applications",
                    queryset=Application.objects.order_by('-id'),
                ),
            )
            .order_by('-udate')
        )

        search = self.request.GET.get('search', None)
        if search is not None:
            # search by application id
            application = Application.objects.filter(id=search).first()
            if application:
                data = data.filter(customer__id=application.customer_id)
                return data

            # search by customer id
            data = data.filter(customer__id=search)

        return data

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response_count = response.data.get('count')
        if response_count == 0:
            return not_found_response(
                message={'title': 'Akun tidak ditemukan', 'msg': 'Coba lakukan pencarian kembali'}
            )

        return success_response(response.data)


class CustomerDataCRMView(APIView, StandardizedExceptionHandlerMixinV2):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.CS_ADMIN,
                JuloUserRoles.CS_TEAM_LEADER,
                JuloUserRoles.CCS_AGENT,
                JuloUserRoles.BO_GENERAL_CS,
            ]
        )
    ]


class CustomerDataChangeRequestListView(CustomerDataCRMView, ListAPIView):
    serializer_class = CustomerDataChangeRequestListSerializer
    pagination_class = LargeResultsSetPagination
    http_method_names = ['get']
    filter_fields = ['status', 'customer_id', 'application_id']
    non_admin_filter_fields = ['customer_id', 'application_id']

    def get_queryset(self):
        search = self.request.GET.get('search', None)
        queryset = CustomerDataChangeRequest.objects.all().order_by('-id')
        if search:
            queryset = queryset.filter(Q(customer_id=search) | Q(application_id=search))
        return queryset

    def list(self, request, *args, **kwargs):
        # only allow specific filter for non CS_ADMIN roles
        has_non_admin_filter = any(
            [request.GET.get(field, None) for field in self.non_admin_filter_fields]
        )
        if not has_non_admin_filter and not has_user_groups(request.user, [JuloUserRoles.CS_ADMIN]):
            return unauthorized_error_response(message="You are not allowed to access this page")

        response = super(CustomerDataChangeRequestListView, self).list(request, *args, **kwargs)
        if response.data.get('count', 0) == 0:
            msg = {'title': "Data tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        return success_response(response.data)


class CustomerDataChangeRequestDetailView(CustomerDataCRMView, RetrieveUpdateAPIView):
    serializer_class = CustomerDataChangeRequestCRMDetailSerializer
    http_method_names = ['get', 'post']

    def get_queryset(self):
        return CustomerDataChangeRequest.objects.get_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance=instance)
        check_data = serializer.data

        # Previous Data
        previous_request = instance.previous_approved_request
        previous_data = (
            self.serializer_class(instance=previous_request).data if previous_request else None
        )

        # Original Data
        handler = CustomerDataChangeRequestHandler(customer=instance.customer)
        original_data_obj = handler.convert_application_data_to_change_request()
        original_data = self.serializer_class(instance=original_data_obj).data

        # Change Fields for UI
        compare_data = previous_data if previous_data else original_data
        change_fields = [
            key
            for key, value in check_data.items()
            if value is not None and (key not in compare_data or value != compare_data[key])
        ]

        data = {
            'original_data': original_data,
            'previous_data': previous_data,
            'check_data': check_data,
            'change_fields': change_fields,
        }
        return success_response(data=data)

    def post(self, request, *args, **kwargs):
        instance = self.get_object()
        request_data = request.data

        serializer = CustomerDataChangeRequestApprovalSerializer(
            instance, data=request_data, context={'user': request.user}
        )
        if not serializer.is_valid():
            return general_error_response("Ada data yang salah.", data=serializer.errors)

        self.perform_update(serializer)
        return success_response()


class CustomerDataChangeRequestDashboardView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    http_method_names = ['get']

    def get(self, request, *args, **kwargs):
        csrftoken = request.COOKIES.get('csrftoken', '')
        url = (
            settings.CRM_REVAMP_BASE_URL
            + 'dashboard/cs_admin/change-data-self-service/?csrftoken='
            + csrftoken
        )

        return redirect(url)


class CustomerDataChangeRequestCustomerInfoView(CustomerDataCRMView):
    http_method_names = ['get', 'post']

    def get(self, request, *args, **kwargs):
        customer_id = kwargs.get('customer_id')
        if not customer_id:
            return general_error_response("Customer ID tidak ditemukan")

        customer = Customer.objects.filter(id=customer_id).first()
        if not customer:
            return general_error_response("Customer tidak ditemukan")

        handler = CustomerDataChangeRequestHandler(customer=customer)

        previous_request = handler.last_approved_change_request()
        if previous_request is None:
            previous_request = handler.convert_application_data_to_change_request()
        serializer = CustomerDataChangeRequestCRMDetailSerializer(instance=previous_request)
        return success_response(data=serializer.data)

    def post(self, request, *args, **kwargs):
        customer_id = kwargs.get('customer_id')
        if not customer_id:
            return general_error_response("Customer ID tidak ditemukan")

        customer = Customer.objects.filter(id=customer_id).first()
        if not customer:
            return general_error_response("Customer tidak ditemukan")

        handler = CustomerDataChangeRequestHandler(customer=customer)

        if handler.is_submitted():
            return general_error_response("Data sedang dalam proses approval")

        previous_request = handler.last_approved_change_request()
        if previous_request is None:
            previous_request = handler.convert_application_data_to_change_request()

        data = request.data
        data['customer_id'] = customer_id
        serializer = CustomerDataChangeRequestCRMSerializer(
            data=data,
            context={
                'change_request_handler': handler,
                'previous_request': previous_request,
            },
        )
        if not serializer.is_valid():
            return general_error_response("Ada data yang salah.", data=serializer.errors)

        serializer.save(source=CustomerDataChangeRequestConst.Source.ADMIN)
        return created_response({})


class SearchAccountDeletionHistory(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = []

    def list(self, request, *args, **kwargs):
        from juloserver.customer_module.services.pii_vault import (
            detokenize_sync_object_model,
        )
        from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

        identifier = self.request.query_params.get("q", None)
        if identifier is None or not identifier:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        filterset = Q(nik=identifier) | Q(phone=identifier) | Q(email__iexact=identifier)
        active_customer = (
            Customer.objects.filter(filterset, is_active=True)
            .prefetch_related(
                Prefetch(
                    "application_set",
                    queryset=Application.objects.regular_not_deletes().order_by('-id'),
                    to_attr="applications",
                )
            )
            .order_by("-cdate")
            .all()
        )

        deleted_customers = (
            CustomerRemoval.objects.filter(filterset)
            .select_related("customer")
            .prefetch_related(
                Prefetch(
                    "customer__accountdeletionrequest_set",
                    queryset=AccountDeletionRequest.objects.order_by("-id"),
                    to_attr="account_deletion_requests",
                )
            )
            .order_by("-customer__cdate")
            .all()
        )

        detokenized_deleted_customers = detokenize_sync_object_model(
            PiiSource.CUSTOMER_REMOVAL, PiiVaultDataType.KEY_VALUE, deleted_customers
        )

        if not active_customer and not detokenized_deleted_customers:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        data = self.parse_result_account_deletion_history(
            active_customer, detokenized_deleted_customers
        )
        return success_response(data=data)

    @staticmethod
    def parse_result_account_deletion_history(active_customer, deleted_customer):
        active_customer = AccountDeletionHistorySerializer(active_customer, many=True).data
        deleted_customers = AccountDeletionHistorySerializer(deleted_customer, many=True).data

        result = active_customer + deleted_customers
        total_active_customer = len(active_customer)
        total_deleted_customer = len(deleted_customers)
        data = {
            "overview": {
                "total_registration": total_active_customer + total_deleted_customer,
                "total_deletion": total_deleted_customer,
            },
            "results": result,
        }

        return data


@julo_login_required
@julo_login_required_multigroup(["cs_admin"])
def dashboard_consent_withdrawal(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(("GET"))

    csrftoken = request.COOKIES.get('csrftoken', '')
    url = (
        settings.CRM_REVAMP_BASE_URL
        + 'dashboard/cs_admin/consent-withdrawal/?csrftoken='
        + csrftoken
    )

    return redirect(url)


class ConsentWithdrawalHistoryPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"

    def get_paginated_response(self, data, current_status=None):
        return success_response(
            data={
                "current_status": current_status,
                "withdrawal_histories": {
                    "count": self.page.paginator.count,
                    "previous": self.get_previous_link(),
                    "next": self.get_next_link(),
                    "data": data,
                },
            }
        )


class ConsentWithdrawalHistoryView(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    pagination_class = ConsentWithdrawalHistoryPagination
    serializer_class = ConsentWithdrawalHistorySerializer

    def get_customer(self):
        identifier = self.request.query_params.get("search")
        if not identifier:
            return None

        filterset = Q(nik=identifier) | Q(phone=identifier) | Q(email__iexact=identifier)

        if identifier.isdigit():
            filterset |= Q(id=int(identifier)) | Q(current_application_id=int(identifier))

        return (
            Customer.objects.filter(filterset)
            .prefetch_related(
                Prefetch(
                    "application_set",
                    queryset=Application.objects.regular_not_deletes().order_by('-id'),
                    to_attr="applications",
                ),
            )
            .order_by("-cdate")
            .first()
        )

    def get_queryset(self):
        self.customer = self.get_customer()
        if not self.customer:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        return ConsentWithdrawalRequest.objects.filter(customer_id=self.customer.id).order_by(
            "-cdate"
        )

    def list(self, request, *args, **kwargs):
        identifier = self.request.query_params.get("search")
        if not identifier:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        if not hasattr(self, "customer") or not self.customer:
            self.get_queryset()

        if not self.customer:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        current_status = ConsentWithdrawalCurrentStatusSerializer(self.customer).data

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is None:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        customer_ids, user_ids = set(), set()
        for item in page:
            action_by = str(item.action_by).strip()
            if not item.source or action_by in {"", "0", "-"}:
                continue

            if item.source.lower() == "crm":
                user_ids.add(action_by)
            else:
                customer_ids.add(action_by)

        customer_ids = list(customer_ids)
        user_ids = list(user_ids)

        customer_map = {
            str(customer.id): customer for customer in Customer.objects.filter(id__in=customer_ids)
        }
        user_map = {str(user.id): user for user in User.objects.filter(id__in=user_ids)}

        for item in page:
            if not item.action_by or item.action_by == "-":
                item.action_by = "-"
            elif item.action_by == "0":
                item.action_by = "System"
            elif item.source and item.source.lower() == "crm":
                user = user_map.get(item.action_by)
                item.action_by = user.username if user else "-"
            else:
                customer = customer_map.get(item.action_by)
                item.action_by = customer.get_fullname if customer else "-"

        serialized = self.get_serializer(page, many=True)
        return self.paginator.get_paginated_response(serialized.data, current_status=current_status)


class ConsentWithdrawalRequestView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = CRMSubmitConsentWithdrawalSerializer
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        request_data = request.data
        serializer = self.serializer_class(data=request_data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        customer = Customer.objects.filter(
            pk=serializer.validated_data.get('customer_id'), is_active=True
        ).first()

        if not customer:
            msg = {'title': "Akun tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        result, failed_status = request_consent_withdrawal(
            customer,
            serializer.validated_data.get('source'),
            serializer.validated_data.get('reason'),
            serializer.validated_data.get('detail_reason'),
            serializer.validated_data.get('email_requestor'),
            request.user.id,
        )

        if not result:
            if failed_status == ConsentWithdrawal.FailedRequestStatuses.NOT_EXISTS:
                return general_error_response(ConsentWithdrawal.ResponseMessages.USER_NOT_FOUND)
            if failed_status in [
                ConsentWithdrawal.FailedRequestStatuses.ACTIVE_LOANS,
                ConsentWithdrawal.FailedRequestStatuses.LOANS_ON_DISBURSEMENT,
            ]:
                return general_error_response(ConsentWithdrawal.ResponseMessages.HAS_ACTIVE_LOANS)
            if failed_status in [
                ConsentWithdrawal.FailedRequestStatuses.APPLICATION_NOT_ELIGIBLE,
                ConsentWithdrawal.FailedRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
            ]:
                return general_error_response(ConsentWithdrawal.ResponseMessages.USER_NOT_ELIGIBLE)
            if (
                failed_status
                == ConsentWithdrawal.FailedRequestStatuses.INVALID_LENGTH_DETAIL_REASON_INAPP
            ):
                return general_error_response(
                    ConsentWithdrawal.ResponseMessages.INVALID_LENGTH_DETAIL_REASON_INAPP
                )
            if (
                failed_status
                == ConsentWithdrawal.FailedRequestStatuses.INVALID_LENGTH_DETAIL_REASON_CRM
            ):
                return general_error_response(
                    ConsentWithdrawal.ResponseMessages.INVALID_LENGTH_DETAIL_REASON_CRM
                )

            return general_error_response(failed_status)

        # Call ChangeStatusConsentWithdrawalView to process the action
        change_status_view = ChangeStatusConsentWithdrawalView()
        change_status_view.request = request

        # Call the post method with 'approve' action
        change_status_response = change_status_view.post(request, action='approve')

        response_data = change_status_response.data.get('data', {})

        return success_response(
            data={
                "status": response_data.get('status'),
                "requested_date": response_data.get('requested_date'),
                "status_action_date": response_data.get('status_action_date'),
            }
        )


class ChangeStatusConsentWithdrawalView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = CRMChangeStatusConsentWithdrawalSerializer
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        request_data = request.data
        serializer = self.serializer_class(data=request_data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        action = kwargs.get('action')

        customer = Customer.objects.filter(
            pk=serializer.validated_data.get('customer_id'), is_active=True
        ).first()

        if not customer:
            msg = {'title': "Akun tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        if action not in ['regrant', 'reject', 'approve']:
            return general_error_response(ConsentWithdrawal.FailedRequestStatuses.INVALID_ACTION)

        source = serializer.validated_data.get('source')
        if not source:
            return general_error_response(ConsentWithdrawal.FailedRequestStatuses.EMPTY_SOURCE)

        reason = serializer.validated_data.get('reason', None)
        email_requestor = serializer.validated_data.get('email_requestor', None)
        if action == 'regrant':
            if email_requestor is None:
                return general_error_response(ConsentWithdrawal.FailedRequestStatuses.EMPTY_EMAIL)
        elif action in ['reject', 'approve']:
            if reason is None:
                return general_error_response(ConsentWithdrawal.FailedRequestStatuses.EMPTY_REASON)

            if len(reason) > 255:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.REASON_TOO_LONG
                )
            email_requestor = customer.get_email

        if action == 'approve':
            result = approval_consent_withdrawal(
                customer=customer,
                admin_reason=reason,
                source=source,
                action_by=request.user.id,
            )
            if not result:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.FAILED_CHANGE_STATUS
                )
        else:
            result = process_action_consent_withdrawal(
                customer=customer,
                action=action,
                source=source,
                admin_reason=reason,
                email_requestor=email_requestor,
                action_by=request.user.id,
            )

            if not result:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.FAILED_CHANGE_STATUS
                )

        return success_response(
            data={
                "status": result.status,
                "requested_date": result.cdate,
                "status_action_date": result.action_date,
            }
        )


class ConsentWithdrawalListRequestPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"

    def get_paginated_response(self, data):
        return success_response(
            data={
                "count": self.page.paginator.count,
                "previous": self.get_previous_link(),
                "next": self.get_next_link(),
                "data": data,
            }
        )


class ConsentWithdrawalListRequestView(ListAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.CS_ADMIN])]
    serializer_class = ConsentWithdrawalListRequestSerializer
    pagination_class = ConsentWithdrawalListRequestPagination

    @property
    def application_filter(self):
        return Q(application_status=ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL) | Q(
            application_status=ApplicationStatusCodes.LOC_APPROVED,
            account__status=JuloOneCodes.CONSENT_WITHDRAWAL_ON_REVIEW,
        )

    def all_customer(self):
        valid_applications = list(
            Application.objects.filter(self.application_filter).values_list(
                "customer_id", flat=True
            )
        )

        return (
            Customer.objects.filter(id__in=valid_applications)
            .prefetch_related(
                Prefetch(
                    "application_set",
                    queryset=Application.objects.regular_not_deletes()
                    .filter(self.application_filter)
                    .order_by('-id'),
                    to_attr="applications",
                ),
            )
            .distinct()
            .order_by("-cdate")
        )

    def search_customer(self):
        identifier = self.request.query_params.get("search")
        if not identifier:
            return []

        filterset = Q(nik=identifier) | Q(phone=identifier) | Q(email__iexact=identifier)

        if identifier.isdigit():
            filterset |= Q(id=int(identifier)) | Q(current_application_id=int(identifier))

        customer = (
            Customer.objects.filter(filterset)
            .filter(Q(application__in=Application.objects.filter(self.application_filter)))
            .prefetch_related(
                Prefetch(
                    "application_set",
                    queryset=Application.objects.regular_not_deletes()
                    .filter(self.application_filter)
                    .order_by('-id'),
                    to_attr="applications",
                ),
            )
            .distinct()
            .order_by("-cdate")
            .first()
        )
        return [customer] if customer else []

    def get_queryset(self):
        identifier = self.request.query_params.get("search")
        self.customer = self.search_customer() if identifier else self.all_customer()
        if not self.customer:
            return []

        customer_map = {c.id: c for c in self.customer}
        withdrawal_requests = get_latest_withdrawal_requests(customer_map.keys())
        if not withdrawal_requests:
            return []

        combined_data = [
            {'withdrawal': wr, 'customer': customer_map.get(wr.customer_id)}
            for wr in withdrawal_requests
        ]

        return combined_data

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        if not queryset:
            msg = {"title": "Data tidak ditemukan", "msg": "Coba lakukan pencarian kembali"}
            return not_found_response(message=msg)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.paginator.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)

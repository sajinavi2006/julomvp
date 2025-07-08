import ast
import json
import os
import tempfile
import traceback
from builtins import str
from distutils.util import strtobool
from typing import BinaryIO, Optional

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import F
from django.http.response import HttpResponseNotAllowed, JsonResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from juloserver.account.constants import AccountConstant
from juloserver.account.services.account_related import (
    bad_payment_message,
    update_account_app_version,
)
from juloserver.account.services.credit_limit import update_credit_limit_with_clcs
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.apiv1.serializers import ApplicationSerializer
from juloserver.apiv2.services import (
    get_customer_app_actions,
    get_device_app_actions,
    get_eta_time_for_c_score_delay,
)
from juloserver.balance_consolidation.constants import BalanceConsolidationFeatureName
from juloserver.cashback.services import is_cashback_enabled
from juloserver.customer_module.constants import (
    BankAccountCategoryConst,
    ConsentWithdrawal,
    CustomerDataChangeRequestConst,
    EmailChange,
    FailedAccountDeletionRequestStatuses,
)
from juloserver.customer_module.exceptions import (
    CustomerApiException,
    CustomerGeolocationException,
    ExperimentSettingStoringException,
)
from juloserver.customer_module.models import (
    BankAccountCategory,
    CXDocument,
)
from juloserver.customer_module.serializers import (
    BankAccountVerificationSerializer,
    ChangeCurrentEmailSerializer,
    CustomerAppsflyerSerializer,
    CustomerDataChangeRequestSerializer,
    CustomerDataPaydayChangeRequestSerializer,
    CustomerGeolocationSerializer,
    CustomerPointHistorySerializer,
    DocumentUploadSerializer,
    ExperimentDataSerializer,
    LimitTimerSerializer,
    ListBankNameSerializer,
    RequestAccountDeletionSerializer,
    SubmitConsentWithdrawalSerializer,
    SubmitProductLockedSerializer,
    UpdateCustomerActionSerializer,
)
from juloserver.customer_module.services.customer_related import (
    CustomerDataChangeRequestHandler,
    CustomerService,
    cancel_account_request_deletion,
    delete_document_payday_customer_change_request_from_oss,
    get_consent_withdrawal_status,
    get_customer_appsflyer_data,
    get_customer_status,
    get_customer_transactions,
    get_ongoing_account_deletion_request,
    is_consent_withdrawal_allowed,
    is_show_customer_data_menu,
    is_user_delete_allowed,
    master_agreement_created,
    master_agreement_template,
    process_action_consent_withdrawal,
    request_account_deletion,
    request_consent_withdrawal,
    restriction_access,
    set_customer_appsflyer_data,
    submit_customer_product_locked,
)
from juloserver.customer_module.services.experiment_setting import (
    process_experiment_data,
)
from juloserver.customer_module.services.view_related import (
    LimitTimerService,
    get_limit_card_action,
    get_validity_timer_feature_setting,
    is_julo_turbo_upgrade_calculation_process,
    process_customer_update_location,
)
from juloserver.customer_module.tasks.customer_related_tasks import (
    send_consent_withdraw_email,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import BankNameValidationLog, NameBankValidation
from juloserver.disbursement.services import get_validation_method
from juloserver.disbursement.services.xfers import XfersService
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients.xfers import XfersApiError
from juloserver.julo.decorators import deprecated_api
from juloserver.julo.models import (
    Application,
    Bank,
    CreditScore,
    Customer,
    CustomerAppAction,
    FeatureSetting,
)
from juloserver.julo.services import get_julo_one_is_proven
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import get_oss_public_url, upload_file_to_oss
from juloserver.julo_starter.services.services import (
    determine_application_for_credit_info,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.loan.constants import LoanJuloOneConstant
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.loan.services.loan_related import is_julo_one_product_locked
from juloserver.loan.services.views_related import validate_loan_concurrency
from juloserver.loyalty.models import PointHistory
from juloserver.loyalty.services.services import check_loyalty_whitelist_fs
from juloserver.otp.constants import SessionTokenAction
from juloserver.otp.services import verify_otp_session
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pin.decorators import (
    blocked_session,
    pin_verify_required,
    verify_pin_token,
)
from juloserver.pin.services import CustomerPinChangeService, does_user_have_pin
from juloserver.promo.constants import FeatureNameConst as PromoFeatureNameConst
from juloserver.referral.constants import FeatureNameConst as ReferralFeatureNameConst
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    not_found_response,
    success_response,
)

logger = JuloLog(__name__)


class UserConfigView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):

        customer = request.user.customer
        app_version = request.query_params.get('app_version', None)
        customer_action = get_customer_app_actions(customer, app_version)
        application = determine_application_for_credit_info(customer)
        if application:
            detokenize_applications = detokenize_for_model_object(
                PiiSource.APPLICATION,
                [
                    {
                        'customer_xid': application.customer.customer_xid,
                        'object': application,
                    }
                ],
                force_get_local_data=True,
            )
            application = detokenize_applications[0]

        use_new_ui, show_setup_pin = get_customer_status(customer)
        customer_action = get_customer_app_actions(customer, app_version)

        # device app actions
        device = customer.device_set.last()
        device_app_actions = get_device_app_actions(device, app_version) if device else []
        if does_user_have_pin(
            customer.user
        ) and CustomerPinChangeService.check_password_is_out_date(customer.user):
            if customer_action['actions']:
                customer_action['actions'].append('pin_is_outdated')
            else:
                customer_action['actions'] = ['pin_is_outdated']
                logger.warning(
                    {
                        "message": "User config info - Pin is outdated",
                        "app_version": app_version,
                        "cutomer": customer,
                    },
                    request=request,
                )
        account = customer.account
        data = {
            "useNewUi": use_new_ui,
            "showSetupPin": show_setup_pin,
            "isJuloOneCustomer": False,
            "isJuloStarterCustomer": False,
            "customerAction": customer_action,
            "deviceAppAction": device_app_actions,
            "applications": [ApplicationSerializer(application).data],
            "cashback_enabled": None,
            "julover_status": False,
            "isJuloTurboUpgradeProcess": False,
            'show_new_referral': True,
            'show_loyalty': check_loyalty_whitelist_fs(customer.id),
            'show_promo_list': True,
            "has_ongoing_account_deletion_request": False,
            "account_status": None if not account else account.status_id,
        }

        if application:
            data.update(
                {
                    "isJuloOneCustomer": application.is_julo_one(),
                    "isJuloStarterCustomer": application.is_julo_starter(),
                    "julover_status": application.is_julover(),
                    "cashback_enabled": is_cashback_enabled(application),
                }
            )

            if data['isJuloStarterCustomer']:
                data.update(
                    {
                        "isJuloTurboUpgradeProcess": is_julo_turbo_upgrade_calculation_process(
                            application
                        ),
                    }
                )

        referral_whitelist_fs = FeatureSetting.objects.filter(
            feature_name=ReferralFeatureNameConst.WHITELIST_NEW_REFERRAL_CUST, is_active=True
        ).last()
        if referral_whitelist_fs:
            whitelist_customer_ids = referral_whitelist_fs.parameters.get('customer_ids', [])
            data['show_new_referral'] = customer.id in whitelist_customer_ids

        promo_code_list_fs = FeatureSetting.objects.filter(
            feature_name=PromoFeatureNameConst.PROMO_CODE_WHITELIST_CUST, is_active=True
        ).last()
        if promo_code_list_fs:
            promo_code_whitelist_customer_ids = promo_code_list_fs.parameters.get(
                'customer_ids', []
            )
            data['show_promo_list'] = customer.id in promo_code_whitelist_customer_ids

        data['show_customer_data_menu'] = False
        try:
            data['show_customer_data_menu'] = is_show_customer_data_menu(customer)
        except Exception as e:
            logger.error(
                {
                    "message": "Error when check show customer data menu",
                    "customer": customer.id,
                    "error": str(e),
                },
                request=request,
            )
            get_julo_sentry_client().captureException()

        account = customer.account
        if account:
            logger.info(
                {
                    "message": "User config info",
                    "process": "update_account_app_version",
                    "app_version": app_version,
                    "customer": customer,
                },
                request=request,
            )
            update_account_app_version(account, app_version)

        ongoing_deletion_request = get_ongoing_account_deletion_request(customer)
        if ongoing_deletion_request:
            data.update(
                {
                    'has_ongoing_account_deletion_request': True,
                }
            )

        logger.info(
            {
                "message": "Success response user config info",
                "customer": customer,
                "app_version": app_version,
                "data": data,
            },
            request=request,
        )
        return success_response(data)


class CreditInfoView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        if customer:
            detokenize_customers = detokenize_for_model_object(
                PiiSource.CUSTOMER,
                [
                    {
                        'object': customer,
                    }
                ],
                force_get_local_data=True,
            )
            customer = detokenize_customers[0]
        application = customer.application_set.regular_not_deletes().last()

        is_locked_get_dana = True
        is_locked_send_dana = True

        data = {
            "creditInfo": {
                "fullname": customer.fullname,
                "credit_score": None,
                "set_limit": None,
                "available_limit": None,
                "used_limit": None,
                "is_proven": False,
                "limit_message": None,
                "account_state": None,
            },
            "concurrency": None,
            "concurrency_messages": None,
            "loan_agreement_xid": None,
            "account_id": None,
            "product": [],
        }

        if not application:
            return success_response(data)

        account = application.account
        is_proven = get_julo_one_is_proven(account)

        limit_message = None

        application_status_code = application.application_status_id
        account_status_code = None if not account else account.status_id
        now = timezone.localtime(timezone.now())
        eta_time = get_eta_time_for_c_score_delay(application, now=now)
        is_delay = now < eta_time
        delay_for_c_score_condition = (
            application.is_julo_one()
            and application_status_code == ApplicationStatusCodes.FORM_PARTIAL
            and is_delay
        )
        if account and account.status_id == AccountConstant.STATUS_CODE.inactive:
            limit_message = "Akun anda sudah tidak aktif, " "silahkan kontak operator Julo"
        elif (
            not application.customer.can_reapply
            and application_status_code in ApplicationStatusCodes.in_progress_j1()
        ) or delay_for_c_score_condition:
            limit_message = 'Pengajuan kredit JULO sedang dalam proses'

        data.update(
            {
                "creditInfo": {
                    "is_proven": is_proven,
                    "limit_message": limit_message,
                    "account_state": account_status_code,
                },
                "account_id": account.id if account else None,
            }
        )

        credit_score = CreditScore.objects.filter(application_id=application.id).last()
        if credit_score:
            data["creditInfo"]["credit_score"] = credit_score.score

        if (
            account
            and application.status == ApplicationStatusCodes.LOC_APPROVED
            and account.accountlimit_set.last()
        ):
            account_limit = account.accountlimit_set.last()
            update_credit_limit_with_clcs(application)
            data["creditInfo"].update(
                dict(
                    credit_score=account_limit.latest_credit_score.score or "--",
                    set_limit=account_limit.set_limit,
                    available_limit=account_limit.available_limit,
                    used_limit=account_limit.used_limit,
                )
            )

        if account:
            loan = account.loan_set.last()
            if (
                loan
                and loan.status in LoanStatusCodes.inactive_status()
                and not loan.is_credit_card_transaction
            ):
                data["loan_agreement_xid"] = loan.loan_xid

        is_concurrency, concurrency_messages = validate_loan_concurrency(account)
        data["concurrency"] = is_concurrency
        data["concurrency_messages"] = concurrency_messages

        bad_payment_block_message = bad_payment_message(account_status_code)
        if (
            bad_payment_block_message
            and account.status_id in AccountConstant.LOCKED_TRANSACTION_STATUS
        ):
            data["block_message"] = bad_payment_block_message
        elif account and account.status_id in AccountConstant.UNLOCK_STATUS:
            is_locked_get_dana = False
            is_locked_send_dana = not is_proven

        data["product"] = [
            {
                "code": 0,
                "name": "Tarik Dana",
                "is_locked": (
                    is_locked_get_dana
                    or is_julo_one_product_locked(account, LoanJuloOneConstant.TARIK_DANA, 0)
                ),
                "is_partner": False,
            },
            {
                "code": 1,
                "name": "Kirim Dana",
                "is_locked": (
                    is_locked_send_dana
                    or is_julo_one_product_locked(account, LoanJuloOneConstant.KIRIM_DANA, 1)
                ),
                "is_partner": False,
            },
            {
                "code": 4,
                "name": "Pulsa & Data",
                "is_locked": (
                    is_locked_get_dana
                    or is_julo_one_product_locked(account, LoanJuloOneConstant.PPOB_PRODUCT, 4)
                ),
                "is_partner": False,
            },
            {
                "code": 5,
                "name": "PLN",
                "is_locked": (
                    is_locked_get_dana
                    or is_julo_one_product_locked(account, LoanJuloOneConstant.PPOB_PRODUCT, 5)
                ),
                "is_partner": False,
            },
        ]

        data = get_limit_card_action(data)

        return success_response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_bank(request):
    if request.method == 'GET':
        banks_list = Bank.objects.regular_bank()
        if not banks_list:
            return JsonResponse({'success': False, 'data': [], 'errors': 'Bank not found'})
        bank_list = banks_list.order_by('order_position', 'id')
        result = []
        for bank in bank_list:
            bank_dict = dict(
                bank_code=bank.xfers_bank_code,
                bank_name=bank.bank_name_frontend,
                bank_logo=bank.bank_logo,
            )
            result.append(bank_dict)

        return JsonResponse({'success': True, 'data': list(result), 'errors': []})
    else:
        return HttpResponseNotAllowed(['POST', 'PUT'])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_bank_account_category(request):
    bank_account_category = (
        BankAccountCategory.objects.exclude(
            category__in=[
                BankAccountCategoryConst.ECOMMERCE,
                BankAccountCategoryConst.PARTNER,
                BankAccountCategoryConst.EDUCATION,
                BankAccountCategoryConst.HEALTHCARE,
                BankAccountCategoryConst.EWALLET,
                BankAccountCategoryConst.BALANCE_CONSOLIDATION,
            ]
        )
        .annotate(category_id=F('id'))
        .values('category_id', 'category', 'display_label')
    )
    if not bank_account_category:
        return JsonResponse(
            {'success': False, 'data': [], 'errors': 'Bank account category not found'}
        )

    return JsonResponse({'success': True, 'data': list(bank_account_category), 'errors': []})


class ProcessBankAccountVerify(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = BankAccountVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer = Customer.objects.get_or_none(pk=int(data['customer_id']))
        if not customer:
            return general_error_response('Customer not found')
        application = Application.objects.filter(customer=customer).last()
        if not application:
            return general_error_response('Application not found')

        bank = Bank.objects.filter(xfers_bank_code=data['bank_code']).last()
        method = get_validation_method(application)
        name_bank_validation = NameBankValidation(
            bank_code=bank.xfers_bank_code,
            account_number=data['account_number'],
            mobile_phone=application.mobile_phone_1,
            method=method,
        )
        xfers_service = XfersService()
        try:
            name_bank_validation_log = BankNameValidationLog()
            name_bank_validation_log.account_number = data['account_number']
            name_bank_validation_log.method = method
            name_bank_validation_log.application = application
            response_validate = xfers_service.validate(name_bank_validation)
            name_bank_validation_log.validation_id = response_validate['id']
            name_bank_validation_log.validation_status = response_validate['status']
            name_bank_validation_log.validated_name = response_validate['validated_name']
            reason = response_validate['reason']
            if response_validate['reason'] != NameBankValidationStatus.SUCCESS:
                reason = 'Gagal menambahkan rekening bank. Coba kembali beberapa saat.'
            name_bank_validation_log.reason = reason
            name_bank_validation_log.save()
        except XfersApiError:
            return general_error_response('verify bank account failed')
        bank_account_category = BankAccountCategory.objects.get_or_none(pk=data['category_id'])
        if not bank_account_category:
            return general_error_response('Bank account category not found')
        bank_account = dict(
            name_in_bank=response_validate['validated_name'],
            account_number=response_validate['account_no'],
            bank=response_validate['bank_abbrev'],
            bank_name=bank.bank_name,
            category=bank_account_category.category,
            display_label=bank_account_category.display_label,
            category_id=bank_account_category.id,
            description=data['description'],
            bank_logo=bank.bank_logo,
            validated_id=response_validate['id'],
            validation_status=response_validate['status'],
            validated_name=response_validate['validated_name'],
            reason=response_validate['reason'],
        )

        return JsonResponse({'success': True, 'data': bank_account, 'errors': []})


class ChangeCurrentEmail(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ChangeCurrentEmailSerializer

    @pin_verify_required
    def post(self, request):
        customer_service = CustomerService()

        serializer = ChangeCurrentEmailSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        try:
            customer_service.change_email(request.user, email)

            return success_response("Success")
        except CustomerApiException as e:
            return general_error_response(str(e))


class DeprecatedChangeCurrentEmail(StandardizedExceptionHandlerMixin, APIView):
    @deprecated_api(EmailChange.OUTDATED_OLD_VERSION)
    def post(self):
        pass


class MasterAgreementTemplate(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]

    def get(self, request, application_id):

        if not application_id:
            return not_found_response(
                "application not found", {'application_id': 'No valid application'}
            )

        application = Application.objects.get(pk=application_id)
        if not application or not application.is_julo_one_product():
            return general_error_response("Application not valid")

        if (
            application.customer.user.auth_expiry_token.key
            != request.META.get('HTTP_AUTHORIZATION', " ").split(' ')[1]
        ):
            return general_error_response("Token not valid.")

        has_sign_ma = application.has_master_agreement()
        if has_sign_ma:
            return general_error_response("Master Agreement has been signed")

        template = master_agreement_template(application)
        if not template:
            return general_error_response("Master Agreement Template not valid")

        return success_response(
            {"master_agreement_template": template, "customer_name": application.customer.fullname}
        )


class GenerateMasterAgreementView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]

    def get(self, request, application_id):
        if not application_id:
            return not_found_response(
                "appliaction not found", {'application_id': 'No valid application'}
            )

        application = Application.objects.get(pk=application_id)

        if (
            application.customer.user.auth_expiry_token.key
            != request.META.get('HTTP_AUTHORIZATION', " ").split(' ')[1]
        ):
            return general_error_response("Token not valid.")

        has_sign_ma = application.has_master_agreement()
        if has_sign_ma:
            return general_error_response("Master Agreement has been signed")

        master_agreement = master_agreement_created(application_id)

        if not master_agreement:
            return general_error_response("Master Agreement not Created")

        return success_response({"master_agreement_created": True})


class LimitTimerView(StandardizedExceptionHandlerMixin, APIView):
    @cache_expiry_on_headers()
    def get(self, request):
        customer = request.user.customer
        application = customer.last_application
        if not application or not application.is_julo_one_product():
            return success_response()

        try:
            limit_timer_feature = get_validity_timer_feature_setting()
            if not limit_timer_feature:
                return success_response()
            serializer = LimitTimerSerializer(data=limit_timer_feature.parameters)
            serializer.is_valid(raise_exception=True)
            timer_data = serializer.validated_data

            account_id = application.account_id
            today = timezone.localtime(timezone.now()).date()

            timer_service = LimitTimerService(timer_data, today)
            app_x190_history = timer_service.get_app_history_lte_days_after_190(application.id)

            if app_x190_history and timer_service.check_limit_utilization_rate(
                customer.id, account_id
            ):
                rest_of_countdown, show_pop_up = timer_service.calculate_rest_of_countdown(
                    timezone.localtime(app_x190_history['cdate']).date()
                )
                if rest_of_countdown:
                    context = dict(
                        rest_of_countdown_days=rest_of_countdown,
                        information=timer_data['information'],
                        pop_up_message=timer_data['pop_up_message'] if show_pop_up else None,
                    )
                    return success_response(context)
        except Exception as e:
            logger.error(
                {
                    "message": e,
                    "action": "LimitTimerView",
                    "customer_id": customer.id,
                    "application": application.id,
                }
            )
        return success_response()


class ListBankNameView(StandardizedExceptionHandlerMixin, ListAPIView):
    queryset = Bank.objects.all()
    serializer_class = ListBankNameSerializer
    permission_classes = []

    def list(self, request):
        fs = FeatureSetting.objects.filter(
            feature_name=BalanceConsolidationFeatureName.BANK_WHITELIST, is_active=True
        ).last()
        queryset = self.queryset.filter(is_active=True)
        if fs:
            params = fs.parameters
            queryset = queryset.filter(bank_code__in=params.get('bank_codes', []))
        queryset = queryset.order_by('bank_name')

        serializer = self.serializer_class(queryset, many=True)
        return success_response(serializer.data)


class CustomerActionView(StandardizedExceptionHandlerMixin, APIView):
    def patch(self, request, *args, **kwargs):
        serializer = UpdateCustomerActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = request.user.customer

        customer_app_action = CustomerAppAction.objects.filter(
            customer=customer, action=data['action']
        ).last()

        if not customer_app_action:
            return general_error_response("action not found")

        customer_app_action.update_safely(is_completed=data["is_completed"])
        return success_response()


class CustomerAppsflyerView(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = CustomerAppsflyerSerializer
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
        },
        'log_success_response': True,
    }

    def get(self, request, *args, **kwargs):
        data = get_customer_appsflyer_data(request.user)
        if not data:
            return not_found_response('Customer not found')

        return success_response(data)

    def patch(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = set_customer_appsflyer_data(request.user, serializer.validated_data)
        if not data:
            return not_found_response('Customer not found')

        return success_response(data)


class IsCustomerDeleteAllowedView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        is_allowed, failed_status = is_user_delete_allowed(request.user.customer)
        if not is_allowed and failed_status:
            if failed_status == FailedAccountDeletionRequestStatuses.NOT_EXISTS:
                return general_error_response("not_exists:user does not exists")
            if failed_status in [
                FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
                FailedAccountDeletionRequestStatuses.LOANS_ON_DISBURSEMENT,
            ]:
                return general_error_response('active_loan:user have loans on disbursement')
            if failed_status in [
                FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE,
                FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
            ]:
                return general_error_response('not_eligible:user is not eligible to delete account')
            return general_error_response(failed_status)

        return success_response(
            data={
                'delete_allowed': is_allowed,
            }
        )


class RequestCustomerDeletionView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        deletion_request = get_ongoing_account_deletion_request(request.user.customer)
        if not deletion_request:
            return success_response(None)

        data = {
            'request_status': deletion_request.request_status,
            'cdate': timezone.localtime(deletion_request.cdate),
        }

        return success_response(data)

    @verify_pin_token
    @verify_otp_session(SessionTokenAction.ACCOUNT_DELETION_REQUEST)
    def post(self, request, *args, **kwargs):
        serializer = RequestAccountDeletionSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        result, failed_status = request_account_deletion(
            request.user.customer,
            serializer.validated_data.get('reason'),
            serializer.validated_data.get('detail_reason'),
            serializer.validated_data.get('survey_submission_uid'),
        )
        if not result:
            if failed_status == FailedAccountDeletionRequestStatuses.NOT_EXISTS:
                return general_error_response("not_exists:user does not exists")
            if failed_status in [
                FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
                FailedAccountDeletionRequestStatuses.LOANS_ON_DISBURSEMENT,
            ]:
                return general_error_response('active_loan:user have loans on disbursement')
            if failed_status in [
                FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE,
                FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
            ]:
                return general_error_response('not_eligible:user is not eligible to delete account')
            return general_error_response(failed_status)

        return success_response(data='success')

    def delete(self, request):
        cancel_result = cancel_account_request_deletion(request.user.customer)
        if not cancel_result:
            return general_error_response('Failed to cancel account deletion request')

        return success_response(data='success')


class CustomerDataView(StandardizedExceptionHandlerMixinV2, APIView):
    def get_payday_change_data(self, keep_payday, customer_id, customer_data):
        '''
        Get payday change data from redis and set it to customer_data
        Args:
            keep_payday (str): keep_payday query param
            customer_id (int): customer id
            customer_data (dict): customer data to be returned that get from serializer
        '''

        redis_key = "customer_data_payday_change:" + str(customer_id)
        redis_client = get_redis_client()
        payday = redis_client.get(redis_key)

        if not payday:
            return

        try:
            payday_data = json.loads(payday)
        except json.JSONDecodeError:
            logger.error(
                "Invalid JSON data in Redis for payday change request customer " + customer_id
            )
            return None
        except Exception as e:
            logger.error("Error fetching payday data: " + str(e))
            return None

        if (keep_payday and strtobool(keep_payday)) < 1 or not keep_payday:
            delete_document_payday_customer_change_request_from_oss(
                int(payday_data['payday_change_proof_image_id'])
            )
            redis_client.delete_key(redis_key)
            return

        customer_data['payday'] = payday_data['payday']

    def detail_response_data(self, customer, version_code=0):
        change_request_handler = CustomerDataChangeRequestHandler(customer)
        nudge_message = None
        validation_message = ''
        if change_request_handler.is_submitted():
            nudge_message = CustomerDataChangeRequestConst.NudgeMessage.WAITING_FOR_APPROVAL

        current_change_request = change_request_handler.last_approved_change_request()
        if not current_change_request:
            current_change_request = (
                change_request_handler.convert_application_data_to_change_request()
            )

        serializer = CustomerDataChangeRequestSerializer(
            current_change_request,
            context={
                'previous_change_request': current_change_request,
                'payslip_income_multiplier': (
                    change_request_handler.setting.payslip_income_multiplier
                ),
            },
        )

        supported_app_version_code = change_request_handler.setting.supported_app_version_code

        customer_data = serializer.data

        # Get the latest submitted customer data change request
        last_submitted_instance = change_request_handler.last_submitted_change_request()
        latest_submitted_change_request = (
            CustomerDataChangeRequestSerializer(instance=last_submitted_instance).data
            if last_submitted_instance
            else None
        )

        if version_code > supported_app_version_code:
            empty_fields = []
            for field in CustomerDataChangeRequestConst.Field.REQUIRED_FIELD:
                if field in customer_data and not customer_data[field]:
                    field = 'address' if field == 'address_kodepos' else field
                    empty_fields.append(CustomerDataChangeRequestConst.Field.LABEL_MAP[field])

            if empty_fields and not change_request_handler.is_submitted():
                str_empty_fields = ' dan '.join(
                    [', '.join(empty_fields[:-1]), empty_fields[-1]]
                    if len(empty_fields) > 2
                    else empty_fields
                )
                empty_msg = CustomerDataChangeRequestConst.ValidationMessage.REQUIRED_FIELD_EMPTY
                empty_msg = (empty_msg % str_empty_fields).capitalize()
                validation_message = empty_msg
        else:
            for field in CustomerDataChangeRequestConst.Field.REQUIRED_FIELD:
                if field != 'address_kodepos' and field in customer_data:
                    customer_data.pop(field)
                    if latest_submitted_change_request:
                        latest_submitted_change_request.pop(field)

        supported_payday_version_code = change_request_handler.setting.supported_payday_version_code
        if version_code and version_code > supported_payday_version_code:
            keep_payday = self.request.query_params.get('keep_payday', "false")
            self.get_payday_change_data(keep_payday, customer.id, customer_data)

        change_fields = []
        if latest_submitted_change_request:
            # Ensure fields have the same default value when empty
            for field in ["address_longitude", "address_latitude"]:
                if latest_submitted_change_request.get(field) == 0.0:
                    latest_submitted_change_request[field] = None

            # Identify fields that have changed in the latest submitted customer data change request
            change_fields = [
                key
                for key, value in latest_submitted_change_request.items()
                if value is not None and (key not in customer_data or value != customer_data[key])
            ]

        return {
            'request_eligibility_state': change_request_handler.get_permission_status(),
            'nudge_message': nudge_message,
            'validation_message': validation_message,
            'customer_data': customer_data,
            'form_rules': {
                'monthly_income_threshold': serializer.monthly_income_threshold(),
            },
            'change_fields': change_fields,
        }

    @verify_pin_token
    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        version_code = int(request.META.get('HTTP_X_VERSION_CODE', 0))
        response_data = self.detail_response_data(customer, version_code)
        return success_response(response_data)

    @verify_pin_token
    @blocked_session(expire_pin_token=True)
    def post(self, request, *args, **kwargs):
        customer = request.user.customer
        change_request_handler = CustomerDataChangeRequestHandler(customer)
        if (
            change_request_handler.get_permission_status()
            != CustomerDataChangeRequestConst.PermissionStatus.ENABLED
        ):
            return general_error_response("Tidak dapat submit data. Silakan hubungi CS.")

        raw_data = request.data

        version_code = int(request.META.get('HTTP_X_VERSION_CODE', 0))
        supported_app_version_code = change_request_handler.setting.supported_app_version_code
        if version_code and version_code <= supported_app_version_code:
            for field in CustomerDataChangeRequestConst.Field.REQUIRED_FIELD:
                raw_data[field] = (
                    None if field not in raw_data or not raw_data[field] else raw_data[field]
                )

        raw_data['app_version'] = request.META.get('HTTP_X_APP_VERSION')
        raw_data['version_code'] = version_code

        try:
            status, data = change_request_handler.create_change_request(
                raw_data=raw_data,
                source=CustomerDataChangeRequestConst.Source.APP,
            )
            if not status:
                return general_error_response("data_expired:{}".format(data))

            response_data = self.detail_response_data(customer, version_code)
        except ValidationError as e:
            for i in e.detail:
                if e.detail[i][0] == CustomerDataChangeRequestConst.ErrorMessages.TextField:
                    return general_error_response("alert:{}".format(e.detail[i][0]))
                return general_error_response(e.detail[i][0])
        except CustomerApiException as e:
            return general_error_response("Ada data yang salah.", data=ast.literal_eval(str(e)))

        return created_response(response_data)


class CustomerDataUploadView(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = DocumentUploadSerializer

    def process_document_upload(
        self, file: BinaryIO, file_type: str, customer_id: int
    ) -> Optional['CXDocument']:
        """
        Process the upload of a document.

        Args:
            file (BinaryIO): The uploaded file.
            file_type (str): The type of the file.
            customer_id (int): The ID of the customer.

        Returns:
            CXDocument: The created document object.

        Raises:
            IOError: If there's an error handling the file.
            OSError: If there's an error with file operations.
        """
        try:
            _, file_extension = os.path.splitext(file.name)
            filename = file_type + "-" + str(customer_id) + file_extension

            # Use context manager for temporary file handling
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                for chunk in file.chunks():
                    temp_file.write(chunk)
                temp_path = temp_file.name

            try:
                document = CXDocument.objects.create(
                    document_source=customer_id,
                    document_type=file_type,
                    filename=filename,
                    url="cust_" + str(customer_id) + "/" + filename,
                )

                # Upload file to OSS
                upload_file_to_oss(settings.OSS_MEDIA_BUCKET, temp_path, document.url)

                return document

            except Exception as e:
                # Cleanup document if upload fails
                if 'document' in locals():
                    document.delete()
                raise e

        finally:
            # Ensure temporary file is always cleaned up
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)

    def post(self, request, *args, **kwargs):
        """
        Handle the HTTP POST request for creating a new document.

        Args:
            request (HttpRequest): The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            JsonResponse: A JSON response containing the document ID and URL on success,
                        or error details on failure.

        Raises:
            ValidationError: If the request data is invalid.
        """
        try:
            # Validate request data with early return for invalid data
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return general_error_response(serializer.errors)

            # Extract validated data once to avoid multiple dictionary lookups
            validated_data = serializer.validated_data
            file = validated_data['document_file']
            document_type = validated_data['document_type']
            customer_id = request.user.customer.id

            # Process document upload with extracted data
            document = self.process_document_upload(file, document_type, customer_id)

            # Return successful response with minimal data construction
            return success_response(
                {
                    "id": str(document.id),
                    "url": document.document_url,
                }
            )

        except Exception as e:
            # Log the error for debugging (assuming you have a logger configured)
            logger.error(
                {
                    "message": "Document upload failed",
                    "customer": request.user.customer.id,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                },
                request=request,
            )
            get_julo_sentry_client().captureException()
            return general_error_response({"error": "Failed to process document upload"})


class CustomerDataPaydayChangeView(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = CustomerDataPaydayChangeRequestSerializer

    def post(self, request, *args, **kwargs):
        import json
        from datetime import timedelta

        serializers = self.serializer_class(
            data=request.data,
            context={
                "customer": request.user.customer,
            },
        )
        if not serializers.is_valid():
            return general_error_response("Failed to submit payday data", data=serializers.errors)

        data = {
            "payday": serializers.validated_data.get("payday"),
            "payday_change_reason": serializers.validated_data.get("payday_change_reason"),
            "payday_change_proof_image_id": serializers.validated_data.get(
                "payday_change_proof_image_id"
            ),
        }
        redis_client = get_redis_client()
        redis_client.set(
            "customer_data_payday_change:" + str(request.user.customer.id),
            json.dumps(data),
            timedelta(hours=4),
        )
        obj = redis_client.get("customer_data_payday_change:" + str(request.user.customer.id))

        return success_response(json.loads(obj))


class SubmitProductLocked(APIView):
    serializer_class = SubmitProductLockedSerializer

    def post(self, request):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        customer_product_locked = submit_customer_product_locked(customer.id, validated_data)
        return success_response(
            {
                'customer_product_locked_id': customer_product_locked.id,
            }
        )


class FeatureExperimentStoredView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = ExperimentDataSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        customer = request.user.customer
        if not serializer.is_valid():
            logger.error(
                'FeatureExperimentStoredView|'
                'invalid_serializer|error={}, customer_id={}'.format(
                    str(serializer.errors),
                    customer.id if customer else None,
                )
            )
            return general_error_response(str(serializer.errors))

        data = serializer.validated_data
        try:
            process_experiment_data(data, customer)
        except ExperimentSettingStoringException:
            return general_error_response('Invalid Request')

        return success_response(data='successfully')


class CustomerGeolocationView(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    serializer_class = CustomerGeolocationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        customer = request.user.customer
        if not serializer.is_valid():
            logger.error(
                {
                    'message': 'Customer geolocation update latitude',
                    'data': str(request.data),
                    'customer_id': customer.id if customer else None,
                },
                request=request,
            )
            return general_error_response(str(serializer.errors))

        data = serializer.validated_data
        try:
            process_customer_update_location(data, customer)
        except CustomerGeolocationException as error:
            logger.error(
                {
                    'message': 'Failure to process location update',
                    'customer_id': customer.id if customer else None,
                    'error_message': str(error),
                },
                request=request,
            )
            return general_error_response('Failure to process location')

        return success_response(data=serializer.initial_data)


class CustomerLatestTransactionsView(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request):
        try:
            customer = request.user.customer
            results = get_customer_transactions(customer.pk)

            return success_response(results)
        except Exception as e:
            return general_error_response(str(e))


class CustomerLoyaltyPointHistoryAPIView(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = CustomerPointHistorySerializer

    def get(self, request, format=None):
        customer = self.request.user.customer
        previous_month = timezone.localtime(timezone.now()) - relativedelta(months=1)
        point_histories = PointHistory.objects.filter(
            customer_id=customer.id, cdate__gt=previous_month
        ).order_by('-id')
        serializer = self.serializer_class(point_histories, many=True)
        return success_response(serializer.data)


class IsConsentWithdrawalAllowedView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        msg = body = ""
        is_allowed, failed_status = is_consent_withdrawal_allowed(request.user.customer)
        if not is_allowed and failed_status:
            if failed_status == ConsentWithdrawal.FailedRequestStatuses.NOT_EXISTS:
                msg = "not_exists:%s" % ConsentWithdrawal.ResponseMessages.USER_NOT_FOUND
                body = ConsentWithdrawal.ResponseMessages.GENERAL_ERROR_BODY

            if failed_status in [
                FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
                FailedAccountDeletionRequestStatuses.LOANS_ON_DISBURSEMENT,
            ]:
                msg = "active_loan:%s" % ConsentWithdrawal.ResponseMessages.HAS_ACTIVE_LOANS
                body = ConsentWithdrawal.ResponseMessages.ACTIVE_LOAN_ERROR_BODY

            if failed_status in [
                FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE,
                FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
            ]:
                msg = "not_eligible:%s" % ConsentWithdrawal.ResponseMessages.USER_NOT_ELIGIBLE
                body = ConsentWithdrawal.ResponseMessages.GENERAL_ERROR_BODY

        return success_response(
            data={
                "is_allowed": is_allowed,
                "message": msg,
                "dialog": {
                    "body": body,
                },
            }
        )


class SubmitConsentWithdrawalView(StandardizedExceptionHandlerMixinV2, APIView):
    serializer_class = SubmitConsentWithdrawalSerializer

    @verify_pin_token
    @verify_otp_session(SessionTokenAction.CONSENT_WITHDRAWAL_REQUEST)
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        result, failed_status = request_consent_withdrawal(
            request.user.customer,
            serializer.validated_data.get('source'),
            serializer.validated_data.get('reason'),
            serializer.validated_data.get('detail_reason'),
        )
        if not result:
            if failed_status == ConsentWithdrawal.FailedRequestStatuses.NOT_EXISTS:
                return general_error_response(
                    "not_exists:%s" % ConsentWithdrawal.ResponseMessages.USER_NOT_FOUND
                )
            if failed_status in [
                ConsentWithdrawal.FailedRequestStatuses.ACTIVE_LOANS,
                ConsentWithdrawal.FailedRequestStatuses.LOANS_ON_DISBURSEMENT,
            ]:
                return general_error_response(
                    "active_loan:%s" % ConsentWithdrawal.ResponseMessages.HAS_ACTIVE_LOANS
                )
            if failed_status in [
                ConsentWithdrawal.FailedRequestStatuses.APPLICATION_NOT_ELIGIBLE,
                ConsentWithdrawal.FailedRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
            ]:
                return general_error_response(
                    'not_eligible:%s' % ConsentWithdrawal.ResponseMessages.USER_NOT_ELIGIBLE
                )
            return general_error_response(failed_status)

        return success_response(
            data={
                "status": result.status,
                "requested_date": result.cdate,
                "status_action_date": result.cdate,
            }
        )


class ChangeStatusConsentWithdrawalView(StandardizedExceptionHandlerMixinV2, APIView):
    """
    Change status consent withdrawal, customer can cancel request and re-grant after
    request was approved.

    Kwargs:
        action (str): cancel or regrant.

    Returns:
        Boolean: success or failed
    """

    def post(self, request, *args, **kwargs):
        action = kwargs.get('action')
        source = request.data['source']

        if action not in ['cancel', 'regrant']:
            return general_error_response(ConsentWithdrawal.FailedRequestStatuses.INVALID_ACTION)

        if not source:
            return general_error_response(ConsentWithdrawal.FailedRequestStatuses.EMPTY_SOURCE)

        customer = request.user.customer
        if not customer:
            return general_error_response(
                ConsentWithdrawal.FailedRequestStatuses.CUSTOMER_NOT_EXISTS
            )

        result = process_action_consent_withdrawal(
            customer=customer,
            action=action,
            source=source,
            email_requestor=customer.get_email,
            action_by=customer.id,
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


class CustomerRestrictionsView(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request):
        try:
            customer = request.user.customer
            if not customer:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.CUSTOMER_NOT_EXISTS
                )

            is_feature_lock, has_restriction = restriction_access(customer)
            if not has_restriction and not is_feature_lock:
                return success_response(
                    data={"has_restriction": [], "is_feature_lock": False, "dialog": None}
                )

            button_label = ConsentWithdrawal.RestrictionMessages.BUTTON_CANCEL_LABEL
            button_action = ConsentWithdrawal.RestrictionMessages.BUTTON_CANCEL_ACTION
            if (
                ConsentWithdrawal.RestrictionMessages.TAG_CONSENT_WITHDRAWAL_APPROVED
                in has_restriction
            ):
                button_label = ConsentWithdrawal.RestrictionMessages.BUTTON_GIVE_LABEL
                button_action = ConsentWithdrawal.RestrictionMessages.BUTTON_GIVE_ACTION

            return success_response(
                data={
                    'has_restriction': has_restriction,
                    'is_feature_lock': is_feature_lock,
                    "dialog": {
                        "header": ConsentWithdrawal.RestrictionMessages.DIALOG_HEADER_CANNOT_ACCESS,
                        "body": ConsentWithdrawal.RestrictionMessages.DIALOG_BODY_CANNOT_ACCESS
                        + "<b>"
                        + button_label
                        + ".</b>",
                        "image": get_oss_public_url(
                            settings.OSS_MEDIA_BUCKET, 'withdrawal-consent/dialog/feature-lock.png'
                        ),
                        "button_primary": {
                            "name": button_label,
                            "action": button_action,
                        },
                        "button_secondary": {
                            "name": ConsentWithdrawal.RestrictionMessages.BUTTON_BACK_LABEL,
                            "action": ConsentWithdrawal.RestrictionMessages.BUTTON_BACK_ACTION,
                        },
                    },
                }
            )
        except Exception as e:
            return general_error_response(str(e))


class CustomerGetStatusView(StandardizedExceptionHandlerMixinV2, APIView):
    def get(self, request):
        try:
            customer = request.user.customer
            if not customer:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.CUSTOMER_NOT_EXISTS
                )

            consent_withdraw_request = get_consent_withdrawal_status(customer)
            if consent_withdraw_request:
                status = consent_withdraw_request.status
                if status == 'auto_approved':
                    status = 'approved'

                return success_response(
                    data={
                        'status': status,
                        'requested_date': consent_withdraw_request.action_date.strftime(
                            "%H:%M:%S %d-%m-%Y"
                        )
                        if consent_withdraw_request.action_date
                        else "",
                        'status_action_date': consent_withdraw_request.cdate.strftime(
                            "%H:%M:%S %d-%m-%Y"
                        )
                        if consent_withdraw_request.cdate
                        else "",
                    }
                )

            return success_response(
                data={
                    'status': None,
                    'requested_date': None,
                    'status_action_date': None,
                }
            )
        except Exception as e:
            return general_error_response(str(e))


class SendEmaiConsentWithdrawal(StandardizedExceptionHandlerMixinV2, APIView):
    def post(self, request, *args, **kwargs):
        try:
            customer = request.user.customer
            if not customer:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.CUSTOMER_NOT_EXISTS
                )

            action = kwargs.get('action')

            if action not in ['approve', 'cancel', 'request', 'auto_approve']:
                return general_error_response(
                    ConsentWithdrawal.FailedRequestStatuses.INVALID_ACTION
                )

            send_consent_withdraw_email.delay(action, customer_id=customer.id)

            return success_response(data="Email was sent successfully")
        except Exception as e:
            return general_error_response(str(e))

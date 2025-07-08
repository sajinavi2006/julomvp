from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from undecorated import undecorated

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit, AccountProperty
from juloserver.account.services.account_related import (
    bad_payment_message,
    get_dpd_and_lock_colour_by_account,
)
from juloserver.account.services.credit_limit import update_credit_limit_with_clcs
from juloserver.apiv2.services import get_eta_time_for_c_score_delay
from juloserver.credit_card.services.card_related import is_julo_card_whitelist_user
from juloserver.customer_module.constants import (
    BankAccountCategoryConst,
    FeatureNameConst,
)
from juloserver.customer_module.exceptions import CustomerApiException
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.customer_module.serializers import (
    EcommerceBankAccountDestinationSerializer,
    EcommerceBankAccountVerificationSerializer,
    GoogleAnalyticsInstanceDataSerializer,
)
from juloserver.customer_module.services.bank_account_related import (
    get_other_bank_account_destination,
    get_self_bank_account_destination,
)
from juloserver.customer_module.services.view_related import (
    get_limit_card_action,
    get_limit_validity_timer_first_time_x190,
    get_limit_validity_timer_campaign,
)
from juloserver.customer_module.views.views_api_v1 import ChangeCurrentEmail
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import BankNameValidationLog, NameBankValidation
from juloserver.disbursement.services import get_validation_method
from juloserver.disbursement.services.xfers import XfersService
from juloserver.ecommerce.models import (
    EcommerceBankConfiguration,
    EcommerceConfiguration,
)
from juloserver.julo.clients.xfers import XfersApiError
from juloserver.julo.models import (
    Application,
    Bank,
    CreditScore,
    Customer,
    FeatureSetting,
    MobileFeatureSetting,
    PaymentMethod,
)
from juloserver.julo.services import get_julo_one_is_proven
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.loan.services.views_related import validate_loan_concurrency
from juloserver.otp.constants import SessionTokenAction
from juloserver.otp.services import verify_otp_session
from juloserver.payment_point.constants import (
    FeatureNameConst as FeatureNameConstPayment,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.services.views_related import (
    construct_transaction_method_for_android,
)
from juloserver.pin.decorators import blocked_session, pin_verify_required
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    response_template,
    not_found_response,
    success_response,
)
from juloserver.customer_module.services.customer_related import (
    master_agreement_template,
    master_agreement_created,
)
from juloserver.loan_refinancing.templatetags.format_date import format_date_to_locale_format
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.julolog.julolog import JuloLog
from django.db.models import Q
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object


logger = JuloLog(__name__)


class CreditInfoView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):

        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            return general_error_response("Application Not Found")

        account_limit = None
        limit_message = None

        account = application.account
        is_proven = get_julo_one_is_proven(account)
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

        if (
            not application.customer.can_reapply
            and application_status_code in ApplicationStatusCodes.in_progress_j1()
        ) or delay_for_c_score_condition:
            limit_message = 'Pengajuan kredit JULO sedang dalam proses'
        dpd_colour, lock_colour = get_dpd_and_lock_colour_by_account(account)
        # detokenize application, customer here
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
        data = {
            "creditInfo": {
                "fullname": customer.fullname or application.fullname,
                "credit_score": None,
                "set_limit": None,
                "available_limit": None,
                "used_limit": None,
                "is_proven": is_proven,
                "limit_message": limit_message,
                "account_state": account_status_code,
                "dpd_colour": dpd_colour,
            },
            "concurrency": None,
            "concurrency_messages": None,
            "loan_agreement_xid": None,
            "account_id": account.id if account else None,
            "product": [],
        }

        credit_score = CreditScore.objects.filter(application_id=application.id).last()
        if credit_score:
            data["creditInfo"]["credit_score"] = credit_score.score

        if account and application.status == ApplicationStatusCodes.LOC_APPROVED:
            account_limit = (
                AccountLimit.objects.filter(account=account.id).select_related('account').last()
            )
            if account_limit:
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
        label = None
        if account:
            account_property = (
                AccountProperty.objects.filter(account=account.id).select_related('account').last()
            )
            if account_property and account_property.refinancing_ongoing:
                label = "430 Refinancing"
        bad_payment_block_message = bad_payment_message(account_status_code, label)
        if (
            bad_payment_block_message
            and account.status_id in AccountConstant.LOCKED_TRANSACTION_STATUS
        ):
            data["block_message"] = bad_payment_block_message

        data["product"] = []
        transaction_methods = TransactionMethod.objects.all().order_by('id')
        if not is_julo_card_whitelist_user(application.id):
            transaction_methods = transaction_methods.exclude(
                id=TransactionMethodCode.CREDIT_CARD.code
            )
        highlight_setting = MobileFeatureSetting.objects.get_or_none(
            is_active=True, feature_name=FeatureNameConstPayment.TRANSACTION_METHOD_HIGHLIGHT
        )

        for transaction_method in transaction_methods:
            data["product"].append(
                construct_transaction_method_for_android(
                    account,
                    transaction_method,
                    is_proven,
                    lock_colour,
                    application,
                    account_limit,
                    highlight_setting,
                )
            )

        data = get_limit_card_action(data)

        return success_response(data)


class BankView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        ecommerce_name = request.GET.get('ecommerceId', None)

        ecommerce_configuration = EcommerceConfiguration.objects.filter(
            ecommerce_name__iexact=ecommerce_name
        ).last()

        if not ecommerce_configuration:
            return general_error_response('Ecommerce tidak ditemukan')

        ecommerce_bank_configurations = EcommerceBankConfiguration.objects.filter(
            ecommerce_configuration=ecommerce_configuration, is_active=True
        )

        if not ecommerce_bank_configurations:
            return general_error_response('Bank tidak ditemukan')

        data = []

        for ecommerce_bank_configuration in ecommerce_bank_configurations:
            data.append(
                dict(
                    bank_name='{} Virtual Account'.format(
                        ecommerce_bank_configuration.bank.bank_name_frontend
                    ),
                    bank_logo=ecommerce_bank_configuration.bank.bank_logo,
                    bank_code=ecommerce_bank_configuration.bank.xfers_bank_code,
                    bank_prefix=ecommerce_bank_configuration.prefix,
                )
            )

        return success_response(data)


class BankAccountDestinationView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, customer_id):
        user = self.request.user
        customer = Customer.objects.get_or_none(pk=int(customer_id))
        if customer.user_id != user.id:
            return forbidden_error_response('User not allowed')
        if not customer:
            return general_error_response('customer tidak ditemukan')

        self_bank_account = request.GET.get('self_bank_account', False)
        self_bank_account = self_bank_account == 'true'

        ecommerce_name = request.GET.get('ecommerceId', None)

        if ecommerce_name:
            bank_account_destinations = BankAccountDestination.objects.filter(
                customer=customer,
                description__iexact=ecommerce_name,
                bank_account_category__category=BankAccountCategoryConst.ECOMMERCE,
            ).exclude(Q(bank__is_active=False) | Q(is_deleted=True))
        else:
            if not self_bank_account:
                bank_account_destinations = get_other_bank_account_destination(customer)
            else:
                bank_account_destinations = get_self_bank_account_destination(customer)
                if not get_julo_one_is_proven(customer.account) and bank_account_destinations:
                    bank_account_destinations = [bank_account_destinations.first()]

        bank_list = []
        if bank_account_destinations:
            for bank_account_destination in bank_account_destinations:
                bank = bank_account_destination.bank
                bank_name = bank.bank_name_frontend
                if ecommerce_name:
                    bank_name = '{} Virtual Account'.format(bank_name)
                bank_account_data = dict(
                    bank_account_destination_id=bank_account_destination.id,
                    bank_name=bank_name,
                    category=bank_account_destination.bank_account_category.category,
                    category_id=bank_account_destination.bank_account_category.id,
                    display_label=bank_account_destination.bank_account_category.display_label,
                    name=bank_account_destination.name_bank_validation.name_in_bank,
                    bank_logo=bank.bank_logo if bank else None,
                    description=bank_account_destination.description,
                    account_number=bank_account_destination.name_bank_validation.account_number,
                )
                bank_list.append(bank_account_data)
        return success_response(bank_list)

    def post(self, request):
        user = self.request.user
        serializer = EcommerceBankAccountDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ecommerce_name = data['ecommerce_id']
        customer = Customer.objects.get_or_none(pk=int(data['customer_id']))
        if not customer:
            return general_error_response('Customer tidak ditemukan')

        if user.id != customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        application = customer.account.get_active_application()
        bank_account_category = BankAccountCategory.objects.get_or_none(pk=data['category_id'])
        ecommerce_configuration = None
        if ecommerce_name:
            ecommerce_configuration = EcommerceConfiguration.objects.filter(
                ecommerce_name__iexact=ecommerce_name
            ).last()
            if not ecommerce_configuration:
                return general_error_response('ecommerce tidak ditemukan')
            ecommerce_name = ecommerce_configuration.ecommerce_name
        if not bank_account_category and ecommerce_configuration:
            bank_account_category = BankAccountCategory.objects.filter(
                category=BankAccountCategoryConst.ECOMMERCE
            ).last()

        if not bank_account_category:
            return general_error_response('kategori akun bank tidak ditemukan')

        bank = Bank.objects.filter(xfers_bank_code=data['bank_code']).last()
        if bank_account_category.category == BankAccountCategoryConst.ECOMMERCE:
            existed_bank_account = (
                BankAccountDestination.objects.filter(
                    bank=bank,
                    bank_account_category=bank_account_category,
                    account_number=data['account_number'],
                )
                .exclude(customer=customer)
                .exists()
            )
            if existed_bank_account:
                return response_template(
                    status=409,
                    success=False,
                    message=[
                        'Maaf, nomor akun VA Anda sudah terdaftar di User lain, '
                        'mohon masukkan akun VA lainnya.'
                    ],
                )

            existed_bank_account = BankAccountDestination.objects.filter(
                customer=customer,
                description=ecommerce_name,
                bank=bank,
                bank_account_category=bank_account_category,
            )

            if existed_bank_account.filter(account_number=data['account_number']).exists():
                return response_template(
                    status=410,
                    success=False,
                    data={'bank': bank.bank_name_frontend, 'merchant': ecommerce_name},
                    message=[
                        'Mohon maaf, Anda tidak bisa menambahkan Virtual Account {} karena '
                        'sudah terdaftar pada E-commerce {}. Silakan menambahkan Virtual'
                        'Account dari bank lainnya.'.format(bank.bank_name_frontend, ecommerce_name)
                    ],
                )

            allow_multiple_va_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.ALLOW_MULTIPLE_VA, is_active=True
            ).last()
            allow_multiple_va_feature_flag = False
            if (
                allow_multiple_va_feature
                and ecommerce_name in allow_multiple_va_feature.parameters.get('ecommerce_name', [])
            ):
                allow_multiple_va_feature_flag = True

            if existed_bank_account and not allow_multiple_va_feature_flag:
                return response_template(status=409, success=False)

        method = get_validation_method(application)

        # recheck data with previous step (/verify-bank-account) by validate_id
        if not BankNameValidationLog.objects.filter(
            validation_id=data['validated_id'],
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name=data['name_in_bank'],
            account_number=data['account_number'],
            reason=data['reason'],
            method=method,
            application=application,
        ).exists():
            return general_error_response('id validasi tidak valid')  # validation id is invalid

        # detokenize application here
        name_bank_validation = NameBankValidation.objects.create(
            bank_code=bank.xfers_bank_code,
            account_number=data['account_number'],
            name_in_bank=data['name_in_bank'],
            mobile_phone=application.mobile_phone_1,
            method=method,
            validation_id=data['validated_id'],
            validated_name=data['name_in_bank'],
            reason=data['reason'],
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        BankAccountDestination.objects.create(
            bank_account_category=bank_account_category,
            customer=customer,
            bank=bank,
            account_number=data['account_number'],
            name_bank_validation=name_bank_validation,
            description=ecommerce_name,
        )

        response_data = dict(
            category=bank_account_category.display_label,
            account_number=data['account_number'],
            name_in_bank=data['name_in_bank'],
            bank_name=bank.bank_name_frontend,
            bank_logo=bank.bank_logo,
        )

        return success_response(response_data)


class VerifyBankAccountDestination(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = EcommerceBankAccountVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        customer = Customer.objects.get_or_none(pk=int(data['customer_id']))
        if not customer:
            return general_error_response('Customer tidak ditemukan')

        if user.id != customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        if data['is_forbid_all_j1_and_turbo_users_bank_account'] and Application.objects.filter(
            bank_account_number=data['account_number'],
            application_status__in=[
                ApplicationStatusCodes.LOC_APPROVED,
                ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
                ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED,
            ]
        ).exists():
            return general_error_response('No. rekening / VA ini tidak valid untuk diinput')

        is_registered_virtual_account = PaymentMethod.objects.filter(
            virtual_account=data['account_number']
        ).exists()
        if is_registered_virtual_account:
            return response_template(
                status=status.HTTP_417_EXPECTATION_FAILED,
                success=False,
                message=['Maaf rekening ini tidak bisa ditambahkan, coba gunakan rekening lainnya'],
            )

        application = customer.account.get_active_application()
        ecommerce_name = data['ecommerce_id']
        bank = Bank.objects.filter(xfers_bank_code=data['bank_code']).last()
        bank_name_label = bank.bank_name_frontend
        bank_account_category = None
        if ecommerce_name:
            bank_account_category = BankAccountCategory.objects.filter(
                category=BankAccountCategoryConst.ECOMMERCE
            ).last()
            bank_name_label = '{} Virtual Account'.format(bank_name_label)
        if not bank_account_category:
            bank_account_category = BankAccountCategory.objects.get_or_none(pk=data['category_id'])
        method = get_validation_method(application)
        # detokenize application here
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
            response_message = response_validate['reason']
            if response_validate['status'] != NameBankValidationStatus.SUCCESS:
                reason = 'Gagal menambahkan rekening bank. Coba kembali beberapa saat.'
                response_message = 'No. rekening / VA salah atau tidak ditemukan'
            name_bank_validation_log.reason = reason
            name_bank_validation_log.save()
        except XfersApiError:
            return general_error_response('Verifikasi akun bank gagal')
        bank_account = dict(
            name_in_bank=response_validate['validated_name'],
            account_number=response_validate['account_no'],
            bank=response_validate['bank_abbrev'],
            bank_name=bank_name_label,
            category=bank_account_category.category if bank_account_category else None,
            display_label=bank_account_category.display_label if bank_account_category else None,
            category_id=bank_account_category.id if bank_account_category else None,
            description=data['ecommerce_id'],
            bank_logo=bank.bank_logo,
            validated_id=response_validate['id'],
            validation_status=response_validate['status'],
            validated_name=response_validate['validated_name'],
            reason=response_message,
        )

        return success_response(bank_account)


class GoogleAnalyticsInstanceDataView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = GoogleAnalyticsInstanceDataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request.user.customer.update_safely(
                app_instance_id=serializer.validated_data['app_instance_id']
            )

            logger.info(
                {
                    "message": "Google Analytics data",
                    "app_instance_id": serializer.validated_data['app_instance_id'],
                },
                request=request,
            )
            return success_response("Success")
        except CustomerApiException as e:
            logger.error(message=str(e), request=request)
            return general_error_response(str(e))


class ChangeCurrentEmailV2(ChangeCurrentEmail):
    @pin_verify_required
    @verify_otp_session(SessionTokenAction.VERIFY_EMAIL)
    @blocked_session()
    def post(self, request, *args, **kwargs):
        return undecorated(super().post)(self, request)


class MasterAgreementTemplate(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]

    def get(self, request, application_id):
        import datetime

        if not application_id:
            return not_found_response(
                "application not found", {'application_id': 'No valid application'}
            )

        application = Application.objects.get(pk=application_id)
        if (
            not application
            or not application.is_julo_one_product()
            and not application.is_julo_starter()
        ):
            return general_error_response("Application not valid")

        if (
            application.customer.user.auth_expiry_token.key
            != request.META.get('HTTP_AUTHORIZATION', " ").split(' ')[1]
        ):
            return general_error_response("Token not valid.")

        has_sign_ma = application.has_master_agreement()
        if has_sign_ma:
            return general_error_response("Master Agreement has been signed")

        template = master_agreement_template(application, False)
        if not template:
            return general_error_response("Master Agreement Template not valid")

        today = datetime.datetime.now()
        customer_name = application.customer.fullname.title()

        sign_date = (
            '<p style="text-align:right">'
            'Jakarta, ' + format_date_to_locale_format(today) + '</p>'
        )
        sign_julo = (
            '<p><strong>PT. JULO Teknologi Finansial</strong><br>'
            '(dalam kedudukan selaku kuasa Pemberi Dana)<br>'
            '<cite><tt>Adrianus Hitijahubessy</tt></cite></span></p>'
            '<br>Jabatan: Direktur</p>'
        )
        sign_customer = (
            '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
            '<p style="text-align:right"><span style="font-family:Allura">'
            '<cite><tt>' + customer_name + '</tt></cite></span></p>'
            '<p style="text-align:right">' + customer_name + '</p>'
        )

        response = {
            "master_agreement_template": template,
            "customer_name": customer_name,
            "sign_date": sign_date,
            "sign_julo": sign_julo,
            "sign_customer": sign_customer,
        }

        return success_response(response)


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

        master_agreement = master_agreement_created(application_id, True)

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

        account = application.account
        if not account or account.status_id != AccountConstant.STATUS_CODE.active:
            return success_response()

        try:
            resp_data = get_limit_validity_timer_first_time_x190(application)
            if not resp_data:
                resp_data = get_limit_validity_timer_campaign(account, api_version='v2')
        except Exception as e:
            logger.error(
                {
                    "message": e,
                    "action": "LimitTimerView v2",
                    "customer_id": customer.id,
                    "application": application.id,
                }
            )

        return success_response(resp_data) if resp_data else success_response()

from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView

from undecorated import undecorated

from juloserver.account.constants import (
    AccountConstant,
    LimitRecalculation,
)
from juloserver.account.services.account_related import (
    bad_payment_message,
    get_account_property_by_account,
    get_dpd_and_lock_colour_by_account,
)
from juloserver.account.services.credit_limit import update_credit_limit_with_clcs
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.apiv2.services import get_eta_time_for_c_score_delay
from juloserver.application_form.constants import EmergencyContactConst
from juloserver.cfs.constants import TierId
from juloserver.cfs.services.core_services import (
    get_mission_enable_state,
    is_graduate_of,
)
from juloserver.credit_card.services.card_related import is_julo_card_whitelist_user
from juloserver.customer_module.constants import ChangeCustomerPrimaryPhoneMessages
from juloserver.customer_module.serializers import ChangeCurrentEmailV3Serializer
from juloserver.customer_module.services.customer_related import (
    change_customer_primary_phone_number,
    julo_starter_proven_bypass,
    master_agreement_template,
    unbind_customers_gopay_tokenization_account_linking,
)
from juloserver.customer_module.services.view_related import (
    check_whitelist_transaction_method,
    determine_set_limit_for_j1_in_progress,
    get_limit_card_action,
    get_limit_validity_timer_first_time_x190,
    get_limit_validity_timer_campaign,
    determine_neo_banner_by_app_version,
)
from juloserver.customer_module.views.views_api_v1 import ChangeCurrentEmail
from juloserver.customer_module.views.views_api_v2 import (
    BankAccountDestinationView,
    VerifyBankAccountDestination,
)
from juloserver.fraud_security.models import (
    FraudSwiftLimitDrainerAccount,
    FraudTelcoMaidTemporaryBlock,
    FraudBlockAccount,
)
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.julo.constants import (
    MobileFeatureNameConst,
    OnboardingIdConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.julo.models import (
    Application,
    CreditScore,
    FeatureSetting,
    MobileFeatureSetting,
)
from juloserver.julo.services import get_julo_one_is_proven
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo_starter.services.onboarding_check import check_process_eligible
from juloserver.julo_starter.services.services import (
    determine_application_for_credit_info,
    determine_js_workflow,
)
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.loan.services.views_related import (
    validate_loan_concurrency,
    get_loan_xid_from_inactive_loan,
)
from juloserver.loan_refinancing.templatetags.format_date import (
    format_date_to_locale_format,
)
from juloserver.otp.constants import SessionTokenAction
from juloserver.otp.services import verify_otp_session as verify_otp_session_v2
from juloserver.payment_point.constants import FeatureNameConst, TransactionMethodCode
from juloserver.payment_point.models import TransactionCategory, TransactionMethod
from juloserver.payment_point.services.train_related import (
    is_train_ticket_whitelist_user,
)
from juloserver.payment_point.services.views_related import (
    construct_transaction_method_for_android,
)
from juloserver.pin.decorators import (
    blocked_session,
    generate_temporary_session,
    pin_verify_required,
    verify_otp_session,
    verify_pin_token,
    verify_session,
    parse_device_ios_user,
)
from juloserver.pin.services import validate_new_phone_is_verified
from juloserver.promo.services import is_eligible_promo_entry_page
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)
from juloserver.pii_vault.constants import PiiSource, PIIType
from juloserver.pii_vault.services import (
    detokenize_for_model_object,
    detokenize_value_lookup,
)
from juloserver.julo_starter.constants import JuloStarter190RejectReason
from juloserver.julolog.julolog import JuloLog


logger = JuloLog(__name__)


class CreditInfoView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
    }

    @parse_device_ios_user
    def get(self, request, *args, **kwargs):
        customer = request.user.customer
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        is_android_device = True if not device_ios_user else False

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

        ma_setting_active = FeatureSetting.objects.get(
            feature_name="master_agreement_setting",
        )

        data = {
            "creditInfo": {
                "fullname": customer.fullname,
                "credit_score": None,
                "set_limit": None,
                "available_limit": None,
                "used_limit": None,
                "is_proven": None,
                "limit_message": None,
                "account_state": None,
                "dpd_colour": None,
                "proven_graduate": None,
            },
            "concurrency": None,
            "concurrency_messages": None,
            "loan_agreement_xid": None,
            "account_id": None,
            "master_agreement_active": ma_setting_active.is_active,
            "has_master_agreement": False,
            "has_submit_extra_form": False,
            "is_new_user": True,
            "is_use_neo_banner": False,
            "is_swift_limit_drainer": False,
            "application_status": None,
            "product": [],
        }

        application = determine_application_for_credit_info(customer)
        account = application.account if application else None
        account_status_code = account.status_id if account else None
        is_delay, lock_colour, dpd_colour, account_limit = None, None, None, None
        is_proven = False
        eligibility_turbo = check_process_eligible(customer.id)

        if not application and eligibility_turbo:
            if eligibility_turbo['is_eligible'] == 'not_passed':
                data['creditInfo'].update(
                    {
                        "credit_score": '-',
                    }
                )

        if application:
            application_status_code = application.application_status_id
            now = timezone.localtime(timezone.now())
            eta_time = get_eta_time_for_c_score_delay(application, now=now)
            is_delay = now < eta_time
            delay_for_c_score_condition = (
                application.is_julo_one()
                and application_status_code == ApplicationStatusCodes.FORM_PARTIAL
                and is_delay
            )
            limit_message = None
            if delay_for_c_score_condition or (
                not customer.can_reapply
                and application_status_code in ApplicationStatusCodes.in_progress_j1()
            ):
                limit_message = 'Pengajuan kredit JULO sedang dalam proses'
            dpd_colour, lock_colour = get_dpd_and_lock_colour_by_account(account)
            proven_graduate = is_graduate_of(application, TierId.PRO)
            is_proven = get_julo_one_is_proven(account) or julo_starter_proven_bypass(application)

            credit_score = CreditScore.objects.filter(application_id=application.id).last()
            has_submit_extra_form = application.has_submit_extra_form()
            is_new_user = True
            if account:
                is_new_user = account.count_account_payment() == 0
            data['creditInfo'].update(
                {
                    "credit_score": credit_score.score if credit_score else None,
                    "is_proven": is_proven,
                    "limit_message": limit_message,
                    "account_state": account_status_code,
                    "dpd_colour": dpd_colour,
                    "proven_graduate": proven_graduate,
                }
            )
            app_version = request.META.get('HTTP_X_APP_VERSION') or application.app_version
            if app_version != application.app_version:
                application.app_version = app_version
                application.save(update_fields=['app_version'])

            has_neo_banner = determine_neo_banner_by_app_version(
                application=application,
                app_version=app_version,
                is_android_device=is_android_device,
            )

            data.update(
                {
                    "account_id": account.id if account else None,
                    "has_master_agreement": application.has_master_agreement(),
                    "has_submit_extra_form": has_submit_extra_form,
                    "is_new_user": is_new_user,
                    "is_use_neo_banner": has_neo_banner,
                    "application_status": application.status,
                    "product": [],
                }
            )

            if (
                application.application_status_id
                >= ApplicationStatusCodes.MISSING_EMERGENCY_CONTACT
                and application.is_kin_approved in EmergencyContactConst.CAPPED_LIMIT_VALUES
                and application.onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
            ):
                data['customer_capped_limit'] = customer.customer_capped_limit

        if account:
            account_limit = account.accountlimit_set.last()
            is_partial_limit = determine_js_workflow(application)
            if (
                account_limit
                and is_partial_limit
                and application.status
                in (
                    ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
                    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
                )
            ):
                score = (
                    account_limit.latest_credit_score.score
                    if account_limit.latest_credit_score
                    else "--"
                )
                data["creditInfo"].update(
                    dict(
                        credit_score=score,
                        set_limit=account_limit.set_limit,
                        available_limit=account_limit.available_limit
                        if account_limit.available_limit >= 0
                        else 0,
                        used_limit=account_limit.used_limit,
                    )
                )
            elif account_limit and application.application_status_id in (
                ApplicationStatusCodes.LOC_APPROVED,
                ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
                ApplicationStatusCodes.MISSING_EMERGENCY_CONTACT,
            ):
                recalculation_result = update_credit_limit_with_clcs(application)
                limit_newly_recalculated = LimitRecalculation.NO_CHANGE
                if recalculation_result:
                    account_limit.refresh_from_db()
                    old_limit, new_limit = recalculation_result
                    if old_limit > new_limit:
                        limit_newly_recalculated = LimitRecalculation.DECREASE
                    elif old_limit < new_limit:
                        limit_newly_recalculated = LimitRecalculation.INCREASE

                # set limit for dynamic condition JTurbo and J1
                set_limit_dynamic = determine_set_limit_for_j1_in_progress(
                    application, customer, account_limit
                )
                data["creditInfo"].update(
                    dict(
                        credit_score=account_limit.latest_credit_score.score
                        if account_limit.latest_credit_score
                        else "--",
                        set_limit=set_limit_dynamic,
                        available_limit=account_limit.available_limit
                        if account_limit.available_limit >= 0
                        else 0,
                        used_limit=account_limit.used_limit,
                        limit_newly_recalculated=limit_newly_recalculated,
                    )
                )

            data["loan_agreement_xid"] = get_loan_xid_from_inactive_loan(account.pk)

            if account_status_code == AccountConstant.STATUS_CODE.fraud_reported:
                account_swift_blocked = FraudSwiftLimitDrainerAccount.objects.get_or_none(
                    account=account
                )
                account_telco_maid_blocked = FraudTelcoMaidTemporaryBlock.objects.get_or_none(
                    account=account
                )
                fraud_block_account = FraudBlockAccount.objects.get_or_none(
                    account=account, is_need_action=True
                )
                if (
                    account_swift_blocked
                    or account_telco_maid_blocked
                    or fraud_block_account
                ):
                    data['is_swift_limit_drainer'] = True

        if application and application.is_julo_starter():
            if application.account and application.account.accountlimit_set.last():
                account_limit = application.account.accountlimit_set.last()

                hide_limit = False
                if application.application_status_id >= ApplicationStatusCodes.LOC_APPROVED:
                    loc_history = application.applicationhistory_set.filter(
                        status_new=ApplicationStatusCodes.LOC_APPROVED
                    ).last()
                    change_reason = loc_history.change_reason if loc_history else None

                    hide_limit_reason = [
                        JuloStarter190RejectReason.REJECTED,
                        JuloStarter190RejectReason.REJECT_BINARY,
                        JuloStarter190RejectReason.REJECT_DYNAMIC,
                        JuloStarter190RejectReason.REJECT_DUKCAPIL_FR,
                        JuloStarter190RejectReason.REJECT_LOW_DUKCAPIL_FR,
                        JuloStarter190RejectReason.REJECT_HIGH_DUKCAPIL_FR,
                    ]

                    hide_limit = True if change_reason in hide_limit_reason else False

                if (
                    account_limit.available_limit == 0
                    and account_limit.used_limit == 0
                    and not hide_limit
                ):
                    data['creditInfo'].update(
                        {
                            "limit_message": "Pengajuan JULO Turbo sedang dalam proses",
                            "available_limit": None,
                            "used_limit": None,
                            "credit_score": None,
                        }
                    )

                if account_status_code == AccountConstant.STATUS_CODE.deactivated or hide_limit:
                    data['creditInfo'].update(
                        {
                            "set_limit": account_limit.used_limit,
                            "available_limit": 0,
                            "used_limit": account_limit.used_limit,
                        }
                    )

        is_concurrency, concurrency_messages = validate_loan_concurrency(account)
        data["concurrency"] = is_concurrency
        data["concurrency_messages"] = concurrency_messages
        label = None
        if account:
            account_property = get_account_property_by_account(account)
            if account_property and account_property.refinancing_ongoing:
                label = "430 Refinancing"
        bad_payment_block_message = bad_payment_message(account_status_code, label)
        if (
            bad_payment_block_message
            and account_status_code in AccountConstant.LOCKED_TRANSACTION_STATUS
        ):
            data["block_message"] = bad_payment_block_message
        transaction_methods = TransactionMethod.objects.all().order_by('order_number')
        if not application or not is_julo_card_whitelist_user(application.id):
            transaction_methods = transaction_methods.exclude(
                id=TransactionMethodCode.CREDIT_CARD.code
            )
        if not application or not is_train_ticket_whitelist_user(application.id):
            transaction_methods = transaction_methods.exclude(
                id=TransactionMethodCode.TRAIN_TICKET.code
            )
        if application:
            transaction_methods = check_whitelist_transaction_method(
                transaction_methods, TransactionMethodCode.EDUCATION, application.id
            )
        """
        get just 7 transaction method and will add semua product option later,
        so it will fit options in android
        """
        transaction_methods = transaction_methods[:7]
        transaction_method_results = {}  # for reusing the values later
        highlight_setting = MobileFeatureSetting.objects.get_or_none(
            is_active=True, feature_name=FeatureNameConst.TRANSACTION_METHOD_HIGHLIGHT
        )
        product_lock_in_app_bottom_sheet = FeatureSetting.objects.get_or_none(
            is_active=True, feature_name=JuloFeatureNameConst.PRODUCT_LOCK_IN_APP_BOTTOM_SHEET
        )
        for transaction_method in transaction_methods:
            transaction_method_result = construct_transaction_method_for_android(
                account,
                transaction_method,
                is_proven,
                lock_colour,
                application_direct=application if application else None,
                account_limit_direct=account_limit,
                highlight_setting_direct=highlight_setting,
                product_lock_in_app_bottom_sheet=product_lock_in_app_bottom_sheet,
                device_ios_user=device_ios_user,
            )
            transaction_method_results[transaction_method.id] = transaction_method_result
            data['product'].append(transaction_method_result)

        data['product'].append(
            {
                "is_locked": False,
                "is_partner": False,
                "code": TransactionMethodCode.ALL_PRODUCT,
                "name": 'Semua Produk',
                "foreground_icon": '{}foreground_all_products.png'.format(
                    settings.PRODUCTS_STATIC_FILE_PATH
                ),
                "background_icon": None,
                "lock_colour": None,
                "is_new": True,
            }
        )

        data["all_products"] = []
        transaction_categories = TransactionCategory.objects.all().order_by('order_number')

        for transaction_category in transaction_categories:
            product_by_category = dict(category=transaction_category.fe_display_name, product=[])
            transaction_methods = TransactionMethod.objects.filter(
                transaction_category=transaction_category
            ).order_by('order_number')
            if not application or not is_julo_card_whitelist_user(application.id):
                transaction_methods = transaction_methods.exclude(
                    id=TransactionMethodCode.CREDIT_CARD.code
                )
            if not application or not is_train_ticket_whitelist_user(application.id):
                transaction_methods = transaction_methods.exclude(
                    id=TransactionMethodCode.TRAIN_TICKET.code
                )
            if application:
                transaction_methods = check_whitelist_transaction_method(
                    transaction_methods, TransactionMethodCode.EDUCATION, application.id
                )
            for transaction_method in transaction_methods:
                if transaction_method.id in transaction_method_results:
                    product_by_category['product'].append(
                        transaction_method_results[transaction_method.id],
                    )
                else:
                    product_by_category['product'].append(
                        construct_transaction_method_for_android(
                            account,
                            transaction_method,
                            is_proven,
                            lock_colour,
                            application_direct=application if application else None,
                            account_limit_direct=account_limit,
                            highlight_setting_direct=highlight_setting,
                            product_lock_in_app_bottom_sheet=product_lock_in_app_bottom_sheet,
                        )
                    )

            data["all_products"].append(product_by_category)

        data = get_limit_card_action(data)
        data.update(
            {
                'mission_enable_state': get_mission_enable_state(application)
                if application
                else False,
                'promo_entry_page': is_eligible_promo_entry_page(application)
                if application
                else False,
            }
        )

        return success_response(data)


class BankAccountDestinationViewV2(BankAccountDestinationView):
    @verify_session
    @blocked_session(auto_block=True)
    def post(self, request, *args, **kwargs):
        return super().post(request)


class VerifyBankAccountDestinationV2(VerifyBankAccountDestination):
    @verify_otp_session
    @generate_temporary_session
    def post(self, request, *args, **kwargs):
        return super().post(request)


class ChangeCustomerPrimaryPhoneNumber(StandardizedExceptionHandlerMixin, APIView):
    @pin_verify_required
    def post(self, request):
        if 'new_phone_number' not in request.data:
            return general_error_response({'new_phone_number': "This field is required"})
        application = request.user.customer.application_set.regular_not_deletes().last()
        if not application:
            return not_found_response({'application': 'No valid application'})

        new_phone_number = request.data.get('new_phone_number')

        otp_settings = MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.GLOBAL_OTP, is_active=True
        ).last()

        if otp_settings:
            if not validate_new_phone_is_verified(new_phone_number, request.user.customer):
                return general_error_response(ChangeCustomerPrimaryPhoneMessages.FAILED_DUPLICATE)

        from juloserver.julo.models import Customer

        # detokenize query here
        # TODO, make another query with detokenized value in the future
        detokenize_value_lookup(new_phone_number, PIIType.CUSTOMER)
        phone_existed = Customer.objects.filter(phone=new_phone_number, is_active=True).exclude(
            pk=application.customer_id
        )

        if phone_existed:
            return general_error_response(ChangeCustomerPrimaryPhoneMessages.FAILED_DUPLICATE)

        change_success, message, errors = change_customer_primary_phone_number(
            application, new_phone_number
        )

        if not change_success:
            return general_error_response(errors)

        response = {'message': message, 'change_success': change_success}
        account = request.user.customer.account
        if account:
            unlink_type, error_message = unbind_customers_gopay_tokenization_account_linking(
                account
            )
            unbinding = {"unbind_type": unlink_type, "errors": error_message}
            response['unbinding'] = unbinding
        return success_response(response)


class ChangeCurrentEmailV3(ChangeCurrentEmail):
    serializer_class = ChangeCurrentEmailV3Serializer

    @verify_pin_token
    @verify_otp_session_v2(SessionTokenAction.VERIFY_EMAIL)
    @blocked_session(expire_pin_token=True)
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
        company_name = 'PT. JULO Teknologi Finansial'
        lender_text = 'Kuasa dari Pemberi Dana'
        lender_name = 'Gharnis Athe M. Ginting'
        lender_title = 'Kuasa Direktur'
        receiver = 'Penerima Dana'

        response = {
            "master_agreement_template": template,
            "customer_name": customer_name,
            "sign_date": sign_date,
            "company_name": company_name,
            "lender_text": lender_text,
            "lender_name": lender_name,
            "lender_title": lender_title,
            "receiver": receiver,
        }

        return success_response(response)


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
                resp_data = get_limit_validity_timer_campaign(account, api_version='v3')
        except Exception as e:
            logger.error(
                {
                    "message": e,
                    "action": "LimitTimerView v3",
                    "customer_id": customer.id,
                    "application": application.id,
                }
            )

        return success_response(resp_data) if resp_data else success_response()

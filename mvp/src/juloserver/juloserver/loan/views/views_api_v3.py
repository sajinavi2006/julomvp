from __future__ import division
from django.utils import timezone

from django.http.response import JsonResponse
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView
from django.db import transaction
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.channeling_loan.services.general_services import (
    generate_channeling_loan_threshold_bypass_check_history,
)
from juloserver.channeling_loan.services.lender_services import (
    check_channeling_eligibility_bypass_daily_limit,
)
from juloserver.channeling_loan.tasks import send_loan_for_channeling_task
from juloserver.ecommerce.services import (
    get_iprice_bank_destination,
    get_iprice_transaction,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.partners import PartnerConstant
from juloserver.julo_starter.services.services import determine_application_for_credit_info
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    BankDestinationIsNone,
    LoanDbrException,
    LoanNotBelongToUser,
    LoanNotFound,
)
from juloserver.loan.services.loan_creation import LoanCreditMatrices, get_loan_creation_cm_data
from juloserver.loan.services.loan_one_click_repeat import (
    is_show_one_click_repeat,
    get_latest_transactions_info,
)
from juloserver.loan.services.transaction_model_related import MercuryCustomerService
from juloserver.loan.services.views_v3_related import (
    LoanAgreementDetailsV3Service,
    capture_mercury_loan,
)
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_active_platforms_rule,
)
from juloserver.julo.models import (
    FeatureSetting,
    CreditMatrixRepeatLoan,
    Loan,
)
from juloserver.account.models import (
    AccountLimit,
    Account,
)
from juloserver.loan.serializers import LoanRequestSerializerv3, LoanCalculationSerializer
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
    generate_loan_payment_julo_one,
    get_loan_amount_by_transaction_type,
    determine_transaction_method_by_transaction_type,
    get_transaction_type,
    transaction_method_limit_check,
    is_product_locked,
    get_loan_duration,
    get_first_payment_date_by_application,
    refiltering_cash_loan_duration,
    calculate_installment_amount,
    compute_first_payment_installment_julo_one,
    calculate_loan_amount,
    transaction_fdc_risky_check,
    transaction_web_location_blocked_check,
    adjust_loan_with_zero_interest,
    is_eligible_apply_zero_interest,
    is_show_toggle_zero_interest,
    transaction_hardtoreach_check,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    is_eligible_other_active_platforms,
    process_check_gtl,
    capture_platform_for_loan_creation,
)
from juloserver.loan.constants import (
    LoanJuloOneConstant,
    GoogleDemo,
    LoanPurposeConst,
    DBRConst,
    LoanFeatureNameConst,
)
from juloserver.payment_point.services.product_related import (
    determine_transaction_method_by_sepulsa_product,
)
from juloserver.payment_point.services.sepulsa import get_sepulsa_partner_amount
from juloserver.pin.decorators import pin_verify_required, parse_device_ios_user
from juloserver.promo.models import PromoHistory
from juloserver.pin.models import BlacklistedFraudster
from juloserver.promo.constants import PromoCodeVersion, PromoCodeBenefitConst
from juloserver.promo.exceptions import PromoCodeException, PromoCodeBenefitTypeNotSupport
from juloserver.promo.services import PromoCodeService, create_promo_code_usage
from juloserver.promo.services_v3 import get_apply_promo_code_benefit_handler_v2
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    not_found_response,
    unauthorized_error_response,
    success_response,
)
from juloserver.loan.services.adjusted_loan_matrix import (
    get_adjusted_monthly_interest_rate_case_exceed,
    get_adjusted_total_interest_rate,
    validate_max_fee_rule,
    calculate_loan_amount_non_tarik_dana_delay_disbursement,
)
from juloserver.pin.decorators import pin_verify_required, parse_device_ios_user
from juloserver.customer_module.models import BankAccountDestination
import logging

from juloserver.loan.services.views_related import (
    filter_loan_choice,
    validate_loan_concurrency,
    validate_mobile_number,
    update_sepulsa_transaction_for_last_sepulsa_payment_point_inquire_tracking,
    get_other_platform_monthly_interest_rate,
    calculate_saving_information,
    assign_loan_to_healthcare_user,
    get_crossed_loan_disbursement_amount,
    get_crossed_installment_amount,
    LoanTenureRecommendationService,
    apply_pricing_logic,
    check_if_tenor_based_pricing,
    check_tenor_fs,
    get_tenure_intervention,
    show_select_tenure,
)
from juloserver.julo.services2.sepulsa import SepulsaService

from juloserver.qris.services.legacy_service import QrisService

from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    TransactionMethodCode,
)
from juloserver.payment_point.models import (
    PdamOperator,
    TransactionMethod,
    AYCProduct,
    XfersProduct,
)
from juloserver.payment_point.services.sepulsa import get_sepulsa_partner_amount

from juloserver.loan.services.loan_related import (
    suspicious_ip_loan_fraud_check,
    suspicious_hotspot_loan_fraud_check,
)
from juloserver.fraud_score.constants import BonzaConstants
from juloserver.fraud_score.tasks import execute_hit_bonza_storing_api_inhouse
from juloserver.fraud_score.services import eligible_based_on_bonza_scoring
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.pin.models import BlacklistedFraudster
from juloserver.account.constants import TransactionType, AccountConstant
from juloserver.julo.constants import FeatureNameConst, IdentifierKeyHeaderAPI
from juloserver.fraud_security.services import ATODeviceChangeLoanChecker
from juloserver.ecommerce.juloshop_service import get_juloshop_transaction
from juloserver.loan.services.credit_matrix_repeat import get_credit_matrix_repeat
from juloserver.pin.services import is_blacklist_android

from juloserver.education.models import StudentRegister
from juloserver.education.services.views_related import assign_student_to_loan
from juloserver.balance_consolidation.services import (
    check_and_update_loan_balance_consolidation,
    get_or_none_balance_consolidation,
)
from juloserver.balance_consolidation.exceptions import BalanceConsolidationNotMatchException
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.loan.services.lender_related import julo_one_lender_auto_matchmaking
from juloserver.loan.services.julo_care_related import get_eligibility_status
from juloserver.customer_module.services.bank_account_related import (
    get_other_bank_account_destination,
    get_self_bank_account_destination,
)
from juloserver.loan.models import LoanZeroInterest
from juloserver.julo.formulas import round_rupiah
from juloserver.loan.constants import DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
from juloserver.loan.services.dbr_ratio import (
    LoanDbrSetting,
    get_loan_max_duration,
)
from juloserver.loan.services.loan_tax import (
    calculate_tax_amount,
)
from juloserver.loan.services.views_related import (
    get_range_loan_amount,
    get_provision_fee_from_credit_matrix,
)
from juloserver.healthcare.models import HealthcareUser
from juloserver.payment_point.services.ewallet_related import (
    create_ayc_ewallet_transaction_and_bank_info,
    get_payment_point_product,
    create_xfers_ewallet_transaction,
)
from juloserver.payment_point.exceptions import ProductNotFound
from juloserver.loan.services.agreement_related import (
    get_text_agreement_by_document_type,
)
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.loan.services.delayed_disbursement_related import (
    is_eligible_for_delayed_disbursement,
    get_delayed_disbursement_premium,
    DelayedDisbursementQuoteRequest,
    DelayedDisbursementProductCriteria,
    DelayedDisbursementInsuredDetail,
    DelayedDisbursementConst,
    mapping_dd_condition,
    check_daily_monthly_limit,
)
from juloserver.digisign.services.common_services import (
    can_charge_digisign_fee,
    calc_digisign_fee,
    calc_registration_fee
)

from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
from juloserver.loan.constants import (
    DDWhitelistLastDigit,
)
from juloserver.disbursement.services.daily_disbursement_limit import (
    check_daily_disbursement_limit_by_transaction_method,
)


logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


class LoanJuloOne(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanRequestSerializerv3

    @pin_verify_required
    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={'account': request.user.customer.account}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = request.user.customer
        platform_name = request.META.get('HTTP_X_PLATFORM', '')
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})

        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v3.LoanJuloOne",
                "message": "before loan creation API v3",
                'customer_id': customer.id,
                'data': data,
            }
        )
        mobile_number = data['mobile_number']
        if mobile_number and not validate_mobile_number(mobile_number):
            logger.warning(
                {
                    'action': 'LoanJuloOne_v3_InvalidMobileNumber',
                    'data': data,
                    'mobile_number': mobile_number,
                }
            )
            return general_error_response(ErrorMessageConst.PHONE_INVALID)

        #  -- iprice
        is_iprice = False
        iprice_transaction_id = data.get('iprice_transaction_id', None)
        if iprice_transaction_id:
            iprice_transaction = get_iprice_transaction(
                request.user.customer,
                iprice_transaction_id,
            )
            if not iprice_transaction:
                return not_found_response("Iprice Transaction Not Found")

            data['loan_amount_request'] = iprice_transaction.iprice_total_amount
            iprice_bank_destination = get_iprice_bank_destination()
            data['bank_account_destination_id'] = iprice_bank_destination.id
            data['loan_purpose'] = PartnerConstant.IPRICE
            is_iprice = True
        # iprice --
        # juloshop
        juloshop_transaction = None
        juloshop_transaction_xid = data.get('juloshop_transaction_xid', None)
        if juloshop_transaction_xid:
            juloshop_transaction = get_juloshop_transaction(customer, juloshop_transaction_xid)
            data['loan_amount_request'] = juloshop_transaction.transaction_total_amount
            data['loan_purpose'] = PartnerConstant.JULOSHOP
        # juloshop --
        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')
        application = account.get_active_application()
        user = self.request.user
        if application.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        transaction_method_id = data.get('transaction_type_code', None)
        parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
        if is_apply_check_other_active_platforms_using_fdc(
            application.id, parameters, transaction_method_id=transaction_method_id
        ):
            if not is_eligible_other_active_platforms(
                application.id,
                parameters['fdc_data_outdated_threshold_days'],
                parameters['number_of_allowed_platforms'],
            ):
                send_user_attributes_to_moengage_for_active_platforms_rule.delay(
                    customer_id=customer.id, is_eligible=False
                )
                return general_error_response(parameters['ineligible_message_for_old_application'])

        lender = None
        (
            overlimit,
            message,
            is_eligible_for_threshold_bypass,
        ) = check_daily_disbursement_limit_by_transaction_method(account, transaction_method_id)
        if overlimit:
            if is_eligible_for_threshold_bypass:
                lender = check_channeling_eligibility_bypass_daily_limit(application, data)

            if not lender:
                return general_error_response(
                    # 400 with errors[0] contains message to handle backward compatibility
                    message=message,
                    data={
                        # show popup in new application version
                        'error_popup': {
                            'title': 'Wah, Belum Ada Pemberi Dana Yang Tersedia',
                            'banner': {
                                'url': (
                                    'https://statics.julo.co.id/loan/3_platform_validation/'
                                    'ineligible.png'
                                ),
                                'is_active': True,
                            },
                            'content': message,
                            'is_active': True,
                            'error_code': 'DAILY_DISBURSEMENT_LIMIT',
                        },
                    },
                )

        account_limit = account.accountlimit_set.last()
        if data['loan_amount_request'] > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )

        _, concurrency_messages = validate_loan_concurrency(account)
        if concurrency_messages:
            return general_error_response(concurrency_messages['content'])

        is_payment_point = data['is_payment_point'] if 'is_payment_point' in data else False
        data['self_bank_account'] = False if is_payment_point else data['self_bank_account']
        is_fraudster = False
        android_id = data.get('android_id')
        is_fraudster = is_blacklist_android(android_id)

        if transaction_method_id in TransactionMethodCode.mobile_transactions() and mobile_number:
            if BlacklistedFraudster.objects.filter(phone_number=mobile_number).exists():
                is_fraudster = True

        if is_fraudster:
            return general_error_response(
                'Transaksi tidak dapat di proses.'
                'Mohon hubungi cs@julo.co.id untuk detail lebih lanjut'
            )

        loan_amount = data['loan_amount_request']
        product = None
        if is_payment_point:
            payment_point_product_id = data['payment_point_product_id']
            try:
                product, loan_amount = get_payment_point_product(
                    customer.pk, transaction_method_id, loan_amount, payment_point_product_id
                )
            except ProductNotFound:
                sentry.captureException()
                return general_error_response('Produk tidak ditemukan')

        gtl_error_response = process_check_gtl(
            transaction_method_id=transaction_method_id,
            loan_amount=loan_amount,
            application=application,
            customer_id=customer.id,
            account_limit=account_limit,
        )
        if gtl_error_response:
            return gtl_error_response

        transaction_type = None
        transaction_method = None

        if transaction_method_id:
            if is_iprice or juloshop_transaction:
                if transaction_method_id != TransactionMethodCode.E_COMMERCE.code:
                    return general_error_response("Invalid Transaction Method For ecomerce")
            transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
            if transaction_method:
                transaction_type = transaction_method.method

            if transaction_method_id == TransactionMethodCode.HEALTHCARE.code:
                healthcare_user = HealthcareUser.objects.get_or_none(
                    pk=data['healthcare_user_id'], account_id=account.pk, is_deleted=False
                )
                if not healthcare_user:
                    return general_error_response("Healthcare user not found")
                data['bank_account_destination_id'] = healthcare_user.bank_account_destination_id
                data['loan_purpose'] = LoanPurposeConst.BIAYA_KESEHATAN

        # check lock product
        is_consolidation = get_or_none_balance_consolidation(customer.pk)
        if is_product_locked(
                account, transaction_method_id, device_ios_user=device_ios_user
        ) and not is_consolidation:
            return forbidden_error_response(
                'Maaf, Anda tidak bisa menggunakan fitur ini.'
                'Silakan gunakan fitur lain yang tersedia di menu utama.'
            )

        if transaction_method_id == TransactionMethodCode.EDUCATION.code:
            student_register = StudentRegister.objects.get_or_none(pk=data['student_id'])
            if not student_register:
                return general_error_response("Student not found")

            data['bank_account_destination_id'] = student_register.bank_account_destination_id
            data['loan_purpose'] = 'Biaya pendidikan'

        adjusted_loan_amount, credit_matrix, credit_matrix_product_line = calculate_loan_amount(
            application=application,
            loan_amount_requested=loan_amount,
            transaction_type=transaction_type,
            is_payment_point=is_payment_point,
            is_self_bank_account=data['self_bank_account'],
        )
        credit_matrix_product = credit_matrix.product
        monthly_interest_rate = credit_matrix_product.monthly_interest_rate
        origination_fee_pct = credit_matrix_product.origination_fee_pct
        # check credit matrix repeat, and if exist change the provision fee and interest
        credit_matrix_repeat = get_credit_matrix_repeat(
            customer.id,
            credit_matrix_product_line.product.product_line_code,
            transaction_method_id,
        )
        # loan matrices
        loan_matrices = LoanCreditMatrices(
            credit_matrix=credit_matrix,
            credit_matrix_product_line=credit_matrix_product_line,
            credit_matrix_repeat=credit_matrix_repeat,
        )
        loan_cm_data = get_loan_creation_cm_data(loan_matrices)

        tenor_based_pricing = None
        if credit_matrix_repeat:
            origination_fee_pct = credit_matrix_repeat.provision
            monthly_interest_rate = credit_matrix_repeat.interest

            # if NEW_TENOR_BASED_PRICING is active then we use new tenor calculation
            new_tenor_feature_settings = check_tenor_fs()
            transaction_method_id = data.get('transaction_type_code')
            if new_tenor_feature_settings:
                monthly_interest_rate, tenor_based_pricing, _, _, _ = check_if_tenor_based_pricing(
                    customer,
                    new_tenor_feature_settings,
                    data['loan_duration'],
                    credit_matrix_repeat,
                    transaction_method_id,
                    check_duration=True
                )

            # recalculate amount since origination_fee_pct may be changed
            adjusted_loan_amount = get_loan_amount_by_transaction_type(
                loan_amount, origination_fee_pct, data['self_bank_account']
            )

        disbursement_amount_zt = None
        original_loan_amount = adjusted_loan_amount
        original_interest_rate = monthly_interest_rate
        is_disbursement_julo_care = data.get('is_julo_care', False)
        insurance_premium = None
        if is_disbursement_julo_care:
            is_julo_care_eligible, all_insurance_premium = get_eligibility_status(
                customer=customer,
                list_loan_tenure=[data['loan_duration']],
                loan_amount=original_loan_amount,
                device_brand=data.get('device_brand'),
                device_model=data.get('device_model'),
                os_version=data.get('os_version'),
            )
            if is_julo_care_eligible:
                insurance_premium = all_insurance_premium.get(str(data['loan_duration']), None)

        elif not is_disbursement_julo_care and is_eligible_apply_zero_interest(
            transaction_method_id,
            account.customer_id,
            data['loan_duration'],
            data['loan_amount_request'],
            data.get('is_zero_interest'),
        ):
            (
                adjusted_loan_amount_zt,
                adjusted_provision_rate_zt,
                adjusted_disbursement_amount_zt,
                adjusted_interest_rate,
            ) = adjust_loan_with_zero_interest(
                monthly_interest_rate,
                data['loan_duration'],
                origination_fee_pct,
                application,
                data['loan_amount_request'],
                data['self_bank_account'],
                account_limit.available_limit,
            )
            if adjusted_loan_amount_zt:
                adjusted_loan_amount = adjusted_loan_amount_zt
                origination_fee_pct = adjusted_provision_rate_zt
                disbursement_amount_zt = adjusted_disbursement_amount_zt
                monthly_interest_rate = adjusted_interest_rate

        # Delay Disbursement
        dd_premium = 0
        dd_cashback = 0
        dd_threshold_duration = 0
        dd_feature_setting: FeatureSetting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            is_active=True,
        ).last()
        if dd_feature_setting:
            should_apply_delayed_disbursement = is_eligible_for_delayed_disbursement(
                dd_feature_setting,
                request.user.customer.id,
                transaction_method_id,
                adjusted_loan_amount,
            )

            if should_apply_delayed_disbursement:
                dd_premium = get_delayed_disbursement_premium(
                    DelayedDisbursementQuoteRequest(
                        product_criteria=DelayedDisbursementProductCriteria(
                            code=DelayedDisbursementConst.PRODUCT_CODE_DELAYED_DISBURSEMENT,
                            category=DelayedDisbursementConst.PRODUCT_CATEGORY_CASH_LOAN,
                        ),
                        insured_detail=DelayedDisbursementInsuredDetail(
                            loan_id=1,
                            loan_amount=adjusted_loan_amount,
                            loan_duration=data['loan_duration'],
                        ),
                    )
                )
            get_dd_condition = mapping_dd_condition(dd_feature_setting)
            dd_cashback = get_dd_condition.cashback
            dd_threshold_duration = get_dd_condition.threshold_duration

        is_loan_amount_adjusted = True

        # calculate digisign fee
        digisign_fee = 0
        registration_fees_dict = {}
        if can_charge_digisign_fee(application):
            if transaction_method_id:
                digisign_fee = calc_digisign_fee(
                    loan_amount=data['loan_amount_request'],
                    transaction_method_code=transaction_method_id
                )
            registration_fees_dict = calc_registration_fee(application)

        # handle mercury
        # only check status & validate loan duration
        mercury_service = MercuryCustomerService(account=account)
        is_mercury, _ = mercury_service.get_mercury_status_and_loan_tenure(
            transaction_method_id=transaction_method_id,
        )
        current_available_cashloan_limit = None
        if is_mercury:
            current_available_cashloan_limit = (
                mercury_service.calculate_ana_available_cashloan_amount()
            )
        # end mercury logic

        loan_requested = dict(
            is_loan_amount_adjusted=is_loan_amount_adjusted,
            original_loan_amount_requested=loan_amount,
            loan_amount=adjusted_loan_amount,
            loan_duration_request=data['loan_duration'],
            interest_rate_monthly=monthly_interest_rate,
            product=credit_matrix_product,
            provision_fee=origination_fee_pct,
            digisign_fee=digisign_fee,
            registration_fees_dict=registration_fees_dict,
            is_withdraw_funds=data['self_bank_account'],
            disbursement_amount_zt=disbursement_amount_zt,
            insurance_premium=insurance_premium,
            device_brand=data.get('device_brand'),
            device_model=data.get('device_model'),
            os_version=data.get('os_version'),
            is_consolidation=is_consolidation,
            transaction_method_id=transaction_method_id,
            product_line_code=credit_matrix_product_line.product.product_line_code,
            delayed_disbursement_premium=dd_premium,
            dd_cashback=dd_cashback,
            dd_threshold_duration=dd_threshold_duration,
            is_mercury=is_mercury,
        )
        bank_account_destination_id = None
        loan_purpose = None
        is_qris_transaction = transaction_type == TransactionMethodCode.QRIS.name
        if not is_payment_point and not is_qris_transaction:
            bank_account_destination_id = data['bank_account_destination_id']
            loan_purpose = data['loan_purpose']

        bank_account_destination = None
        try:
            if (
                transaction_method_id
                in TransactionMethodCode.require_bank_account_customer_validate()
                and bank_account_destination_id
            ):
                # get bank account based on self / other bank accounts
                if data['self_bank_account']:
                    bank_account_destinations = get_self_bank_account_destination(customer)
                else:
                    bank_account_destinations = get_other_bank_account_destination(customer)

                # make sure user can only disburse to their own registered account
                bank_account_destination = bank_account_destinations.filter(
                    pk=bank_account_destination_id
                ).first()

                if not bank_account_destination:
                    logger.warning(
                        {
                            'action': 'LoanJuloOne_v3_BankDestinationIsNone',
                            'bank_account_destination_id': bank_account_destination_id,
                            'customer': customer,
                            'transaction_method_id': transaction_method_id,
                        }
                    )
                    raise BankDestinationIsNone(
                        "Bank account does not belong to you: {}".format(
                            bank_account_destination_id
                        )
                    )
        except BankDestinationIsNone:
            get_julo_sentry_client().captureException()
            return general_error_response("Bank account does not belong to you")

        if not bank_account_destination:
            # case for PPOB
            bank_account_destination = BankAccountDestination.objects.get_or_none(
                pk=bank_account_destination_id
            )

        # check bank destination exists
        try:
            if transaction_method_id in TransactionMethodCode.require_bank_account_destination():
                if transaction_method_id == TransactionMethodCode.E_COMMERCE.code:
                    # ecommerce is juloshop ignore bank destination
                    if not juloshop_transaction and not bank_account_destination:
                        raise BankDestinationIsNone(
                            "bank destination id: {}".format(bank_account_destination_id)
                        )
                else:
                    if not bank_account_destination:
                        raise BankDestinationIsNone(
                            "bank destination id: {}".format(bank_account_destination_id)
                        )
        except BankDestinationIsNone:
            get_julo_sentry_client().captureException()
            return general_error_response("Bank account not found")

        # Create QRIS Loan at 209 for beginning
        draft_loan = False
        if is_qris_transaction:
            draft_loan = True

        tax = 0
        try:
            loan_update_dict = {}
            with transaction.atomic():
                account_limit = (
                    AccountLimit.objects.select_for_update().filter(account=account).last()
                )
                # Check promo code valid first and apply promo code
                promo_code = None
                promo_code_loan_adjustment_data = None
                if data.get('promo_code', None):
                    promo_code_service = PromoCodeService(
                        promo_code_str=data['promo_code'], version=PromoCodeVersion.V2
                    )
                    (
                        promo_code,
                        promo_code_benefit_type
                    ) = promo_code_service.get_valid_promo_code_v2(
                        application=application,
                        loan_requested=loan_requested,
                    )
                    apply_benefit_service_handler = get_apply_promo_code_benefit_handler_v2(
                        promo_code=promo_code
                    )
                    if promo_code_benefit_type in (
                        PromoCodeBenefitConst.PROMO_CODE_BENEFIT_V2_APPLIED_DURING_LOAN_CREATION
                    ):
                        promo_code_loan_adjustment_data = {
                            'promo_code': promo_code,
                            'handler': apply_benefit_service_handler,
                            'type': promo_code_benefit_type,
                        }

                loan = generate_loan_payment_julo_one(
                    application,
                    loan_requested,
                    loan_purpose,
                    credit_matrix,
                    bank_account_destination,
                    draft_loan=draft_loan,
                    promo_code_data=promo_code_loan_adjustment_data,
                )
                # Create promo code usage if promo code is valid
                if promo_code:
                    promo_code_usage = create_promo_code_usage(
                        loan=loan,
                        promo_code=promo_code,
                        version=PromoCodeVersion.V2,
                    )
                    promo_code.promo_code_daily_usage_count += 1
                    promo_code.promo_code_usage_count += 1
                    promo_code.save()
                    custom_promo_type = 'promo_code:{}'.format(promo_code.code)
                    PromoHistory.objects.create(
                        customer_id=promo_code_usage.customer_id,
                        loan_id=promo_code_usage.loan_id,
                        account_id=loan.account_id,
                        promo_type=custom_promo_type,
                    )

                capture_platform_for_loan_creation(loan, platform_name)
                available_limit = account_limit.available_limit
                if is_mercury:
                    available_limit = current_available_cashloan_limit

                if loan.loan_amount > available_limit:
                    raise AccountLimitExceededException(
                        "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
                    )

                capture_mercury_loan(
                    loan_id=loan.id,
                    is_mercury=is_mercury,
                    transaction_model_customer=mercury_service.transaction_model_customer,
                    current_available_cashloan_limit=current_available_cashloan_limit,
                    cm_max_tenure=loan_cm_data.max_tenure,
                    cm_min_tenure=loan_cm_data.min_tenure,
                )

                if credit_matrix_repeat:
                    CreditMatrixRepeatLoan.objects.create(
                        credit_matrix_repeat=credit_matrix_repeat,
                        loan=loan,
                    )
                    if tenor_based_pricing:
                        tenor_based_pricing.loan = loan
                        tenor_based_pricing.save()
                    if not disbursement_amount_zt:
                        loan.set_disbursement_amount(
                            promo_code_data=promo_code_loan_adjustment_data
                        )
                        loan.save()

                if disbursement_amount_zt:
                    if hasattr(loan, 'loanadjustedrate'):
                        origination_fee_pct = loan.loanadjustedrate.adjusted_provision_rate

                    loan.loanzerointerest = LoanZeroInterest.objects.create(
                        loan=loan,
                        original_loan_amount=original_loan_amount,
                        original_monthly_interest_rate=original_interest_rate,
                        adjusted_provision_rate=origination_fee_pct,
                    )

                # handle for balance consolidation
                if check_and_update_loan_balance_consolidation(loan, transaction_method_id):
                    loan_update_dict['loan_purpose'] = LoanPurposeConst.PERPINDAHAN_LIMIT

                # BONZA SCORING
                if loan.product.product_line_id == ProductLineCodes.J1:
                    bonza_eligible, reject_reason = eligible_based_on_bonza_scoring(
                        loan, transaction_method_id
                    )
                    if not bonza_eligible and reject_reason == BonzaConstants.SOFT_REJECT_REASON:
                        return general_error_response(BonzaConstants.NON_ELIGIBLE_SCORE_SOFT_REJECT)
                    elif not bonza_eligible and reject_reason == BonzaConstants.HARD_REJECT_REASON:
                        return general_error_response(BonzaConstants.NON_ELIGIBLE_SCORE_HARD_REJECT)

                suspicious_ip_loan_fraud_check(loan, request, data.get('is_suspicious_ip'))

                if data.get('latitude') is not None and data.get('longitude') is not None:
                    # this need latitude and longitude to create a new record on device_geolocation
                    suspicious_hotspot_loan_fraud_check(loan, data)

                transaction_fdc_risky_check(loan)

                transaction_web_location_blocked_check(
                    loan=loan, latitude=data.get('latitude'), longitude=data.get('longitude')
                )

                transaction_hardtoreach_check(loan, account.id)

                if not transaction_method:
                    transaction_type = get_transaction_type(
                        data['self_bank_account'], is_payment_point, bank_account_destination
                    )
                    transaction_method = determine_transaction_method_by_transaction_type(
                        transaction_type
                    )

                # qris transaction
                if is_qris_transaction:
                    qr_id = data['qr_id']
                    qirs_service = QrisService(account)
                    qirs_service.init_doku_qris_transaction_payment(
                        qr_id, data['loan_amount_request'], loan
                    )

                if transaction_method.method == TransactionMethodCode.EDUCATION.name:
                    assign_student_to_loan(data['student_id'], loan)

                if transaction_method.method == TransactionMethodCode.HEALTHCARE.name:
                    assign_loan_to_healthcare_user(loan.pk, data['healthcare_user_id'])

                is_others_ewallet_product = isinstance(product, (AYCProduct, XfersProduct))
                if juloshop_transaction:
                    juloshop_transaction.update_safely(loan=loan)

                # if Xfer, AYC EWallet active => use AYC flow else Sepulsa flow
                elif is_others_ewallet_product:
                    if isinstance(product, AYCProduct):
                        bank_account_destination_id = create_ayc_ewallet_transaction_and_bank_info(
                            loan, product, data['mobile_number']
                        )
                        loan_update_dict[
                            'bank_account_destination_id'
                        ] = bank_account_destination_id
                    else:
                        create_xfers_ewallet_transaction(loan, product, data['mobile_number'])

                elif is_payment_point and not is_others_ewallet_product:
                    sepulsa_service = SepulsaService()
                    paid_period = None
                    customer_amount = None
                    total_month_bill = int(data.get('total_month_bill') or 1)
                    admin_fee = product.admin_fee or 0
                    if product.category == SepulsaProductCategory.WATER_BILL:
                        admin_fee = 0
                    product_service_fee = product.service_fee or 0
                    service_fee = product_service_fee * total_month_bill

                    partner_amount = get_sepulsa_partner_amount(loan_amount, product, service_fee)
                    customer_number = None
                    if partner_amount:
                        customer_amount = loan_amount
                    if 'customer_number' in data and data['customer_number']:
                        customer_number = data['customer_number']
                    elif 'bpjs_number' in data and data['bpjs_number']:
                        customer_number = data['bpjs_number']
                        paid_period = data['bpjs_times']

                    sepulsa_transaction = sepulsa_service.create_transaction_sepulsa(
                        customer=loan.customer,
                        product=product,
                        account_name=data['customer_name'],
                        phone_number=data['mobile_number'],
                        customer_number=customer_number,
                        loan=loan,
                        retry_times=0,
                        partner_price=product.partner_price,
                        customer_price=product.customer_price,
                        customer_price_regular=product.customer_price_regular,
                        category=product.category,
                        customer_amount=customer_amount,
                        partner_amount=partner_amount,
                        admin_fee=admin_fee,
                        service_fee=service_fee,
                        paid_period=paid_period,
                        collection_fee=product.collection_fee,
                    )
                    if not transaction_method:
                        transaction_method = determine_transaction_method_by_sepulsa_product(
                            product
                        )
                    if product.category == SepulsaProductCategory.TRAIN_TICKET:
                        sepulsa_service.mapping_train_transaction(sepulsa_transaction)

                    update_sepulsa_transaction_for_last_sepulsa_payment_point_inquire_tracking(
                        account=account,
                        transaction_method_id=transaction_method_id,
                        sepulsa_product=product,
                        sepulsa_transaction=sepulsa_transaction,
                    )

                in_limit, error = transaction_method_limit_check(account, transaction_method)
                if not in_limit:
                    raise AccountLimitExceededException(error)
                update_available_limit(loan)
                loan_update_dict['transaction_method'] = transaction_method
                loan.update_safely(**loan_update_dict)
                tax = loan.get_loan_tax_fee()
                if tax:
                    loan.set_disbursement_amount(
                        promo_code_data=promo_code_loan_adjustment_data,
                    )
                    loan.save()

            # assign lender
            if lender:
                send_loan_for_channeling_task(
                    loan.id, lender_list=[lender.lender_name], is_prefund=True
                )
                generate_channeling_loan_threshold_bypass_check_history(loan.id, lender.id)
            else:
                lender = julo_one_lender_auto_matchmaking(loan)

            if lender:
                loan.update_safely(lender_id=lender.pk, partner_id=lender.user.partner.pk)
        except (
            AccountLimitExceededException,
            BalanceConsolidationNotMatchException,
        ) as e:
            return general_error_response(str(e))
        except NotFound:
            return general_error_response("Invalid promo code")
        except PromoCodeBenefitTypeNotSupport:
            return general_error_response("Promo code benefit type does not support")
        except PromoCodeException as e:
            logger.error(
                {
                    'action': 'LoanJuloOne',
                    'error': str(e),
                    'data': {**request.data, 'loan_id': loan.id, 'user_id': user.id},
                }
            )
            return general_error_response("Promo code can not be used")
        except LoanDbrException as e:
            # log DBR if error dbr
            loan_dbr = LoanDbrSetting(application, True)
            loan_dbr.log_dbr(
                e.loan_amount,
                e.loan_duration,
                e.transaction_method_id,
                DBRConst.LOAN_CREATION,
            )
            return general_error_response(e.error_msg)

        # HITTING BONZA STORING INHOUSE API AFTER SCORING AND LOAN CREATION
        execute_hit_bonza_storing_api_inhouse(loan_id=loan.id)

        # Fraud ATO Device change handler after loan creation.
        ato_device_change_checker = ATODeviceChangeLoanChecker(
            loan=loan, android_id=data.get('android_id')
        )
        if ato_device_change_checker.is_fraud():
            ato_device_change_checker.block()
            return unauthorized_error_response(
                "Sepertinya akunmu bermasalah dan perlu diverifikasi ulang. "
                "Hubungi CS untuk memulai proses verifikasi."
            )

        installment_amount = loan.installment_amount
        if is_payment_point and loan.loan_duration == 1:
            installment_amount = loan.first_installment_amount

        response_data = {
            'loan_id': loan.id,
            'loan_status': loan.status,
            'loan_amount': loan.loan_amount,
            'disbursement_amount': loan.loan_disbursement_amount,
            'tax': tax,
            'loan_duration': loan.loan_duration,
            'installment_amount': installment_amount,
            'monthly_interest': loan.interest_rate_monthly,
            'loan_xid': loan.loan_xid,
        }

        if 'pdam_operator_code' in data:
            pdam_operator = PdamOperator.objects.filter(code=data['pdam_operator_code']).first()
            if not pdam_operator:
                return general_error_response('PDAM Operator tidak ditemukan')
            response_data['operator_description'] = pdam_operator.description

        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v3.LoanJuloOne",
                "message": "after loan creation API v3",
                "customer_id": customer.id,
                "response_data": response_data,
            }
        )

        return JsonResponse({'success': True, 'data': response_data, 'errors': []})


class LoanCalculation(StandardizedExceptionHandlerMixin, APIView):

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        serializer = LoanCalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})

        customer = request.user.customer
        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v3.LoanCalculation",
                "message": "before loan duration API v3",
                "customer_id": customer.id,
                "request_data": data,
            }
        )

        # iprice -----
        iprice_transaction_id = data.get('iprice_transaction_id', None)
        is_iprice = False
        if iprice_transaction_id:
            iprice_transaction = get_iprice_transaction(
                request.user.customer,
                iprice_transaction_id,
            )
            if not iprice_transaction or (
                iprice_transaction
                and data['loan_amount_request'] != iprice_transaction.iprice_total_amount
            ):
                return general_error_response("Invalid iprice transaction")
            is_iprice = True
        # ----- iprice
        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')

        if user.id != account.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        application = account.get_active_application()
        is_payment_point = data.get('is_payment_point', False)
        data['self_bank_account'] = False if is_payment_point else data['self_bank_account']
        transaction_method_id = data.get('transaction_type_code', None)
        transaction_type = None
        if transaction_method_id:
            # iprice --
            if is_iprice and transaction_method_id != TransactionMethodCode.E_COMMERCE.code:
                return general_error_response("Invalid Transaction Method For iPrice")
            # -- iprice
            transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
            if transaction_method:
                transaction_type = transaction_method.method
        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(
            application, data['self_bank_account'], is_payment_point, transaction_type
        )
        # check lock product
        is_consolidation = get_or_none_balance_consolidation(user.customer.pk)
        if is_product_locked(
                account, transaction_method_id, device_ios_user=device_ios_user
        ) and not is_consolidation:
            return forbidden_error_response(
                'Maaf, Anda tidak bisa menggunakan fitur ini.'
                'Silakan gunakan fitur lain yang tersedia di menu utama.'
            )

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        # check credit matrix repeat, and if exist change the max_duration to that
        credit_matrix_repeat = get_credit_matrix_repeat(
            account.customer.id,
            credit_matrix_product_line.product.product_line_code,
            transaction_method_id,
        )
        max_duration = credit_matrix_product_line.max_duration
        min_duration = credit_matrix_product_line.min_duration
        if credit_matrix_repeat:
            max_duration = credit_matrix_repeat.max_tenure
            min_duration = credit_matrix_repeat.min_tenure

        # ana mercury
        mercury_service = MercuryCustomerService(account=account)
        (
            is_mercury,
            mercury_loan_tenure_from_ana,
        ) = mercury_service.get_mercury_status_and_loan_tenure(
            transaction_method_id=transaction_method_id,
        )
        # end mercury

        available_duration = get_loan_duration(
            loan_amount_request=data['loan_amount_request'],
            max_duration=max_duration,
            min_duration=min_duration,
            set_limit=account_limit.set_limit,
            customer=account.customer,
            application=application,
        )
        available_duration = [1] if data['loan_amount_request'] <= 100000 else available_duration
        is_loan_one = available_duration[0] == 1

        if not available_duration:
            return general_error_response('Gagal mendapatkan durasi pinjaman')
        loan_choice = {}
        credit_matrix_product = credit_matrix.product
        origination_fee_pct = credit_matrix_product.origination_fee_pct
        # change origination_fee_pct if repeat order
        if credit_matrix_repeat:
            origination_fee_pct = credit_matrix_repeat.provision
        available_limit = account_limit.available_limit
        loan_amount = get_loan_amount_by_transaction_type(
            data['loan_amount_request'], origination_fee_pct, data['self_bank_account']
        )
        if loan_amount > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )
        provision_fee = int(py2round(loan_amount * origination_fee_pct))
        # available_limit_after_transaction = available_limit - loan_amount
        disbursement_amount = py2round(loan_amount - provision_fee)
        today_date = timezone.localtime(timezone.now()).date()

        is_qris_transaction = transaction_type == TransactionMethodCode.QRIS.name
        is_ecommerce = transaction_type == TransactionType.ECOMMERCE
        first_payment_date = get_first_payment_date_by_application(application)

        # filter out duration less than 60 days due to google restriction for cash loan
        if not is_payment_point:
            available_duration = refiltering_cash_loan_duration(available_duration, application)

        # filter out duration less than equal 2 month for google demo account
        if account.customer.email == GoogleDemo.EMAIL_ACCOUNT:
            for i in range(1, 3):
                if i in available_duration:
                    available_duration.remove(i)
                    # if 1 and 2 is the only duration available, replace it by 3
                    if not available_duration:
                        available_duration.append(3)

        monthly_interest_rate = credit_matrix_product.monthly_interest_rate
        # change monthly_interest_rate if repeat order
        min_pricing = None
        threshold = None
        new_tenor_feature_settings = check_tenor_fs()
        check_cmr_and_transaction_validation = False
        if credit_matrix_repeat:
            monthly_interest_rate = credit_matrix_repeat.interest
            # if NEW_TENOR_BASED_PRICING is active then we use new tenor calculation
            if new_tenor_feature_settings:
                (_,
                 _,
                 min_pricing,
                 threshold,
                 check_cmr_and_transaction_validation
                 ) = check_if_tenor_based_pricing(
                    account.customer,
                    new_tenor_feature_settings,
                    available_duration[0],
                    credit_matrix_repeat,
                    transaction_method_id
                )

        other_platform_monthly_interest_rate = None
        if data['is_show_saving_amount']:
            other_platform_monthly_interest_rate = get_other_platform_monthly_interest_rate()

        is_show_toggle_zt = is_show_toggle_zero_interest(account.customer_id, transaction_method_id)

        # Add to check DBR status
        is_dbr = data.get('is_dbr', False)
        loan_dbr = LoanDbrSetting(application, is_dbr)
        loan_dbr.update_popup_banner(data['self_bank_account'], transaction_method_id)
        popup_banner = loan_dbr.popup_banner
        available_duration.sort()
        max_available_duration = available_duration[-1]
        default_duration_not_available = False

        # Calculate max duration from feature setting
        max_duration = get_loan_max_duration(data['loan_amount_request'], max_duration)

        # JULOCARE
        is_julo_care = (
            data.get('is_julo_care', False)
            and transaction_method_id == TransactionMethodCode.SELF.code
        )
        is_julo_care_eligible = False
        if is_julo_care:
            is_julo_care_eligible, all_insurance_premium = get_eligibility_status(
                customer=account.customer,
                list_loan_tenure=available_duration,
                loan_amount=data['loan_amount_request'],
                device_brand=data.get('device_brand'),
                device_model=data.get('device_model'),
                os_version=data.get('os_version'),
            )

        # flake8: noqa
        # delayed disbursement
        should_apply_delayed_disbursement = False
        dd_premium = 0
        dd_feature_setting: FeatureSetting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            is_active=True,
        ).last()
        if dd_feature_setting:
            should_apply_delayed_disbursement = is_eligible_for_delayed_disbursement(
                dd_feature_setting,
                request.user.customer.id,
                transaction_method_id,
                loan_amount,
            )

            if should_apply_delayed_disbursement:
                dd_premium = get_delayed_disbursement_premium(
                    DelayedDisbursementQuoteRequest(
                        product_criteria=DelayedDisbursementProductCriteria(
                            code=DelayedDisbursementConst.PRODUCT_CODE_DELAYED_DISBURSEMENT,
                            category=DelayedDisbursementConst.PRODUCT_CATEGORY_CASH_LOAN,
                        ),
                        insured_detail=DelayedDisbursementInsuredDetail(
                            loan_id=1,
                            loan_amount=loan_amount,
                            loan_duration=1,
                        ),
                    )
                )
        # flake8: enable

        provision_fee_credit_matrix = 0
        loan_amount_cm = 0
        tag_campaign = ""
        intervention_campaign = ""
        is_show_intervention = False
        loan_campaigns = []
        tenure_intervention = {}
        if credit_matrix_repeat:
            """
            Assign `tag_campaign` (button text) and `tenure_intervention` (bottom sheet data)
            from `thor_tenor_intervention` feature setting for CMR.
            """
            tenure_intervention = get_tenure_intervention()
            provision_fee_credit_matrix, loan_amount_cm = get_provision_fee_from_credit_matrix(
                data['loan_amount_request'], credit_matrix_product, data['self_bank_account']
            )

        digisign_fee = 0
        total_registration_fee = 0
        if can_charge_digisign_fee(application):
            if transaction_method_id:
                digisign_fee = calc_digisign_fee(
                    data['loan_amount_request'], transaction_method_id
                )

            # Only charge one time after registration success.
            registration_fees_dict = calc_registration_fee(application)
            total_registration_fee = sum(list(registration_fees_dict.values()))

        for duration in available_duration:
            if default_duration_not_available and len(loan_choice) >= 4:
                """
                DBR only choose maximum 4 loans,
                currently our process is hardcoded to show 4 loan,
                this may need to be removed
                """
                break

            loan_amount_duration = loan_amount
            monthly_interest_rate_duration = monthly_interest_rate
            if credit_matrix_repeat and \
                    new_tenor_feature_settings and check_cmr_and_transaction_validation:
                is_show_intervention = True
                monthly_interest_rate_duration, _ = apply_pricing_logic(
                    duration,
                    threshold,
                    credit_matrix_repeat,
                    min_pricing
                )
            origination_fee_pct_duration = origination_fee_pct
            provision_fee_duration = provision_fee
            disbursement_amount_duration = disbursement_amount
            disbursement_fee = 0
            is_show_toggle = False

            is_zero_interest = is_eligible_apply_zero_interest(
                transaction_method_id,
                account.customer_id,
                duration,
                data['loan_amount_request'],
            )
            if is_zero_interest:
                (
                    adjusted_loan_amount,
                    adjusted_origination_fee_pct,
                    adjusted_disbursement_amount,
                    adjusted_interest_rate,
                ) = adjust_loan_with_zero_interest(
                    monthly_interest_rate,
                    duration,
                    origination_fee_pct_duration,
                    application,
                    data['loan_amount_request'],
                    data['self_bank_account'],
                    account_limit.available_limit,
                )
                # check and show toggle for zero interest
                if adjusted_loan_amount and is_show_toggle_zt:
                    is_show_toggle = True

                if adjusted_loan_amount and data.get('is_zero_interest'):
                    loan_amount_duration = adjusted_loan_amount
                    origination_fee_pct_duration = adjusted_origination_fee_pct
                    disbursement_amount_duration = adjusted_disbursement_amount
                    monthly_interest_rate_duration = adjusted_interest_rate
                    provision_fee_duration = adjusted_loan_amount - disbursement_amount_duration
                else:
                    is_zero_interest = False

            # JULOCARE, calculate insurance rate
            insurance_premium_rate = 0
            insurance_premium = 0
            if is_julo_care_eligible:
                insurance_premium = all_insurance_premium.get(str(duration))
                if insurance_premium:
                    insurance_premium_rate = float(insurance_premium) / float(
                        data['loan_amount_request']
                    )

            # delayed disbursement, calculate premium rate
            dd_premium_rate = 0
            if should_apply_delayed_disbursement and dd_premium > 0:
                dd_premium_rate = float(dd_premium) / float(loan_amount_duration)

            (
                is_exceeded,
                _,
                max_fee_rate,
                provision_fee_rate,
                adjusted_interest_rate,
                insurance_premium_rate,
                dd_premium_rate,
            ) = validate_max_fee_rule(
                first_payment_date,
                monthly_interest_rate_duration,
                duration,
                origination_fee_pct_duration,
                insurance_premium_rate=insurance_premium_rate,
                delayed_disbursement_rate=dd_premium_rate,
                kwargs={
                    "transaction_method_id": transaction_method_id,
                    "dd_premium": dd_premium,
                    "disbursement_amount": disbursement_amount_duration,
                },  # DD e-wallet
            )
            if is_exceeded:
                (adjusted_total_interest_rate, _, _,) = get_adjusted_total_interest_rate(
                    max_fee=max_fee_rate,
                    provision_fee=provision_fee_rate,
                    insurance_premium_rate=insurance_premium_rate,
                )

                # DD
                if dd_premium:
                    adjusted_total_interest_rate = py2round(
                        adjusted_interest_rate * float(duration), 7
                    )

                # adjust loan amount based on new provision
                if (
                    origination_fee_pct_duration != provision_fee_rate
                    and not data['self_bank_account']
                ):
                    loan_amount_duration = get_loan_amount_by_transaction_type(
                        data['loan_amount_request'], provision_fee_rate, data['self_bank_account']
                    )
                if is_zero_interest:
                    provision_fee_duration = round_rupiah(loan_amount_duration * provision_fee_rate)
                    if data['self_bank_account']:
                        disbursement_amount_duration = round_rupiah(
                            loan_amount_duration - provision_fee_duration
                        )
                else:
                    provision_fee_duration = int(
                        py2round(loan_amount_duration * provision_fee_rate)
                    )
                    disbursement_amount_duration = py2round(
                        loan_amount_duration - provision_fee_duration
                    )

                # JULOCARE, recompute due to rate might be adjusted
                insurance_premium = int(insurance_premium_rate * loan_amount_duration)

                first_month_delta_days = (first_payment_date - today_date).days
                (
                    _,
                    adjusted_monthly_interest_rate,
                ) = get_adjusted_monthly_interest_rate_case_exceed(
                    adjusted_total_interest_rate=adjusted_total_interest_rate,
                    first_month_delta_days=first_month_delta_days,
                    loan_duration=duration,
                )
                monthly_interest_rate_duration = adjusted_monthly_interest_rate

                logger.info(
                    {
                        "action": "juloserver.loan.views.views_api_v3.LoanCalculation",
                        "message": "this duration customer is exceeding max fee",
                        "customer_id": customer.id,
                        "first_month_delta_days": first_month_delta_days,
                        "first_payment_date": first_payment_date,
                        "loan_duration": duration,
                        "adjusted_total_interest_rate": adjusted_total_interest_rate,
                        "max_fee_rate": max_fee_rate,
                        "dd_premium_rate": dd_premium_rate,
                        "adjusted_interest_rate": adjusted_interest_rate,
                        "provision_fee_rate": provision_fee_rate,
                        "insurance_premium_rate": insurance_premium_rate,
                    }
                )

            # JULOCARE
            if is_julo_care and insurance_premium:
                provision_fee_duration += insurance_premium
                disbursement_amount_duration -= insurance_premium
                is_show_toggle = False
                disbursement_fee = 0

            if should_apply_delayed_disbursement and dd_premium_rate:
                # specific for NON TARIK DANA
                # recalculate loan_amount_duration,
                # provision_fee_duration,
                # disbursement_amount_duration
                if transaction_method_id != TransactionMethodCode.SELF.code:
                    loan_amount_duration = calculate_loan_amount_non_tarik_dana_delay_disbursement(
                        disbursement_amount_duration, provision_fee_rate, dd_premium
                    )
                    provision_fee_duration = int(
                        py2round(loan_amount_duration * provision_fee_rate)
                    )
                    disbursement_amount_duration = py2round(
                        loan_amount_duration - provision_fee_duration
                    )

                provision_fee_duration += dd_premium
                disbursement_amount_duration -= dd_premium

            # include tax
            tax = calculate_tax_amount(
                provision_fee_duration + digisign_fee + total_registration_fee,
                credit_matrix_product_line.product.product_line_code,
                application.id,
            )

            # reduce disbursement amount if tarik data, increase loan_amount for other
            if transaction_method_id == TransactionMethodCode.SELF.code:
                disbursement_amount_duration -= tax
                disbursement_amount_duration -= digisign_fee
                disbursement_amount_duration -= total_registration_fee
            else:
                loan_amount_duration += tax
                loan_amount_duration += digisign_fee
                loan_amount_duration += total_registration_fee

            monthly_installment = calculate_installment_amount(
                loan_amount_duration, duration, monthly_interest_rate_duration
            )
            _, _, first_monthly_installment = compute_first_payment_installment_julo_one(
                loan_amount_duration,
                duration,
                monthly_interest_rate_duration,
                today_date,
                first_payment_date,
                is_zero_interest,
            )

            if (
                is_loan_one
                and (is_payment_point or is_qris_transaction or is_ecommerce)
                and not is_exceeded
            ):
                monthly_installment = first_monthly_installment

            # check exceeded case when duration is zero interest
            if is_zero_interest and provision_fee_duration > provision_fee:
                disbursement_fee = provision_fee_duration - provision_fee

            # make sure monthly_payment is not exceeding DBR rule
            is_dbr_exceeded = loan_dbr.is_dbr_exceeded(
                duration=duration,
                payment_amount=monthly_installment,
                first_payment_date=first_payment_date,
                first_payment_amount=first_monthly_installment,
            )

            if default_duration_not_available and duration < max_duration:
                # continue next iteration
                available_duration.append(duration + 1)

            if is_dbr_exceeded:
                if (
                    duration == max_available_duration
                    and duration < max_duration
                    and not loan_choice
                ):
                    default_duration_not_available = True
                    available_duration.append(duration + 1)

                continue

            admin_fee = provision_fee_duration

            # skip tenor when loan_amount_duration > available_limit
            if loan_amount_duration > account_limit.available_limit:
                continue

            # check to show crossed compare between CM and CMR
            # provision_amount, disbursement_amount, installment_amount
            crossed_provision_amount = 0
            crossed_disbursement_amount = 0
            crossed_installment_amount = 0
            crossed_interest_monthly = 0

            if provision_fee_credit_matrix > admin_fee:
                crossed_provision_amount = provision_fee_credit_matrix
                crossed_disbursement_amount = get_crossed_loan_disbursement_amount(
                    transaction_method_id=transaction_method_id,
                    loan_amount=loan_amount_cm,
                    provision_amount_cm=crossed_provision_amount,
                    current_disbursement_amount=disbursement_amount_duration,
                )
            if provision_fee_credit_matrix > 0:
                crossed_interest_monthly = credit_matrix_product.monthly_interest_rate
                installment_amount_cm = get_crossed_installment_amount(
                    loan_amount=loan_amount_cm,
                    loan_duration=duration,
                    interest_rate_cm=credit_matrix_product.monthly_interest_rate,
                    today_date=today_date,
                    first_payment_date=first_payment_date,
                )
                crossed_installment_amount = (
                    installment_amount_cm if installment_amount_cm > monthly_installment else 0
                )

            current_choice = {
                'loan_amount': loan_amount_duration,
                'duration': duration,
                'monthly_installment': monthly_installment,
                'first_monthly_installment': first_monthly_installment,
                'provision_amount': admin_fee,
                'digisign_fee': digisign_fee + total_registration_fee,
                'disbursement_amount': int(disbursement_amount_duration),
                'cashback': int(py2round(loan_amount * credit_matrix_product.cashback_payment_pct)),
                'available_limit': available_limit,
                'available_limit_after_transaction': available_limit - loan_amount_duration,
                'disbursement_fee': disbursement_fee,
                'loan_campaign': DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST if is_zero_interest else '',
                'is_show_toggle': is_show_toggle,
                'tax': tax,
                'insurance_premium_rate': insurance_premium_rate,
                'delayed_disbursement_premium_rate': dd_premium_rate,
                'crossed_provision_amount': crossed_provision_amount,
                'crossed_loan_disbursement_amount': crossed_disbursement_amount,
                'crossed_installment_amount': crossed_installment_amount,
                'tag_campaign': tag_campaign,
                'intervention_campaign': intervention_campaign,
                'is_show_intervention': is_show_intervention,
                'loan_campaigns': loan_campaigns,
            }

            if data['is_show_saving_amount']:
                current_choice['saving_information'] = calculate_saving_information(
                    # monthly installment maybe calculate by first payment installment logic,
                    # so use this value, instead of re-calculate
                    monthly_installment,
                    loan_amount_duration,
                    duration,
                    monthly_interest_rate_duration,
                    other_platform_monthly_interest_rate,
                )
                current_choice['saving_information']['crossed_monthly_interest_rate'] = (
                    crossed_interest_monthly
                    if crossed_interest_monthly > monthly_interest_rate_duration
                    else 0
                )

            loan_choice[duration] = current_choice

        # Display error popup if no loan choice available
        if loan_choice:
            popup_banner['is_active'] = False
        else:
            loan_dbr.log_dbr(
                loan_amount_duration,
                duration,
                transaction_method_id,
                DBRConst.LOAN_DURATION,
            )

        # run tenure recommendation with final value of available duration
        tenureRecommendService = LoanTenureRecommendationService(
            available_tenures=available_duration,
            customer_id=account.customer_id,
            transaction_method_id=transaction_method_id,
        )

        # upload 'loan_campaign' field for response
        tenureRecommendService.set_loan_campaign(
            loan_choice=loan_choice,
        )

        # set loan_campaigns, tag_campaign, is_show_intervention and intervention_campaign
        if credit_matrix_repeat:
            # update loan_choice based on the show_tenure column in cmr
            loan_choice = show_select_tenure(
                show_tenure=credit_matrix_repeat.show_tenure,
                loan_choice=loan_choice,
                customer_id=account.customer_id,
            )
            tenureRecommendService.set_loan_campaigns(
                loan_choice=loan_choice,
            )
            if new_tenor_feature_settings and check_cmr_and_transaction_validation:
                tenureRecommendService.set_intervention_visibility_and_tag_campaign(
                    loan_choice=loan_choice,
                )

        # mercury -- UPDATE loan tenures
        if is_mercury:
            mercury_shown_tenures = mercury_service.compute_mercury_tenures(
                final_tenures=list(loan_choice.keys()),
                mercury_loan_tenures=mercury_loan_tenure_from_ana,
            )
            loan_choice = filter_loan_choice(
                original_loan_choice=loan_choice,
                displayed_tenures=mercury_shown_tenures,
                customer_id=account.customer_id,
            )
        # end mercury logic

        loan_duration_default_index = LoanJuloOneConstant.LOAN_DURATION_DEFAULT_INDEX
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.LOAN_DURATION_DEFAULT_INDEX, is_active=True
        ).last()

        if feature_setting:
            params = feature_setting.parameters
            loan_duration_default_index = params[FeatureNameConst.LOAN_DURATION_DEFAULT_INDEX]

        loan_choice_result = [val for _, val in sorted(loan_choice.items())]
        response_data = {
            'default_index': loan_duration_default_index,
            'loan_choice': loan_choice_result,
            'popup_banner': popup_banner,
            'is_device_eligible': is_julo_care_eligible,
            'is_delayed_disbursement_eligible': should_apply_delayed_disbursement,
            'tenure_intervention': tenure_intervention,
        }

        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v3.LoanCalculation",
                "message": "after loan duration API v3",
                "customer_id": customer.id,
                "response_data": response_data,
            }
        )
        return JsonResponse({'success': True, 'data': response_data, 'errors': []})


class RangeLoanAmount(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, account_id):
        self_bank_account = request.GET.get('self_bank_account', False)
        self_bank_account = self_bank_account == 'true'
        account = Account.objects.get_or_none(pk=int(account_id))
        if not account or account.status_id == AccountConstant.STATUS_CODE.inactive:
            logger.warning(
                {
                    'action': 'loan.views.views_api_v3.RangeLoanAmount_inacitve_account',
                    'account_id': account_id,
                }
            )
            return general_error_response('Account tidak ditemukan')

        user = self.request.user
        application = account.get_active_application()
        if application.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        transaction_method_id = request.GET.get('transaction_type_code', None)
        transaction_type = None
        if transaction_method_id:
            transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
            if transaction_method:
                transaction_type = transaction_method.method

        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(
            application, self_bank_account, None, transaction_type
        )
        if not credit_matrix or not credit_matrix.product:
            logger.info(
                {
                    'message': 'Unauthorized loan request.',
                    'account_id': account_id,
                    'self_bank_account': self_bank_account,
                    'transaction_method_id': transaction_method_id,
                    'credit_matrix': credit_matrix,
                }
            )
            return general_error_response('Product tidak ditemukan.')

        credit_matrix_repeat = get_credit_matrix_repeat(
            account.customer.id,
            credit_matrix_product_line.product.product_line_code,
            transaction_method_id,
        )
        max_duration = credit_matrix_product_line.max_duration
        min_duration = credit_matrix_product_line.min_duration
        origination_fee = credit_matrix.product.origination_fee_pct
        monthly_interest_rate = credit_matrix.product.monthly_interest_rate

        if credit_matrix_repeat:
            max_duration = credit_matrix_repeat.max_tenure
            min_duration = credit_matrix_repeat.min_tenure
            origination_fee = credit_matrix_repeat.provision
            monthly_interest_rate = credit_matrix_repeat.interest

        response_data = get_range_loan_amount(
            account,
            origination_fee,
            monthly_interest_rate,
            transaction_type,
            self_bank_account,
            min_duration,
            max_duration,
        )

        app_version = int(request.META.get('HTTP_X_VERSION_CODE', 0))
        if app_version in (2385, 2386, 2387):
            response_data['default_amount'] = 0

        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v3.RangeLoanAmount",
                "message": "Range-loan-amount API result",
                "customer_id": account.customer.id,
                "account_id": account.id,
                "response": response_data,
            }
        )

        return JsonResponse({'success': True, 'data': response_data, 'errors': []})


class LoanAgreementContentView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        user = request.user
        document_type = request.query_params.get('document_type', None)
        if document_type not in LoanAgreementType.LIST_SHOWING_ON_UI:
            return general_error_response("Document type not found")

        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan XID:{} Not found".format(loan_xid))
        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        text_agreement, _ = get_text_agreement_by_document_type(loan, document_type)

        return success_response(data=text_agreement)


class OneClickRepeatView(APIView):
    @cache_expiry_on_headers()
    def get(self, request):
        customer = request.user.customer
        application = determine_application_for_credit_info(customer)
        if not application:
            return not_found_response('Application Not Found')

        fs = FeatureSetting.objects.filter(
            feature_name=LoanFeatureNameConst.ONE_CLICK_REPEAT, is_active=True
        ).last()

        if not fs or not is_show_one_click_repeat(application):
            return success_response()

        transaction_info = get_latest_transactions_info(customer, True, "v3", application)
        return success_response(transaction_info)


class LoanAgreementDetailsView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, loan_xid):
        try:
            service = LoanAgreementDetailsV3Service(
                query_params=request.query_params,
                user=request.user,
                loan_xid=loan_xid,
            )
            service.verify_loan_access()
            response_data = service.get_response_data()

        except LoanNotFound:
            return general_error_response(
                message="Loan XID:{} Not Found or Expired".format(loan_xid)
            )
        except LoanNotBelongToUser:
            return forbidden_error_response(
                data={'user_id': request.user.id}, message=['User not allowed']
            )

        return success_response(data=response_data)


@dataclass
class DelayedDisbursementContent:
    is_active: Optional[bool] = field(default=False)  # flake8: noqa
    cashback: Optional[int] = field(default=None)  # flake8: noqa
    threshold_duration: Optional[int] = field(default=None)  # flake8: noqa
    tnc: Optional[str] = field(default=None)  # flake8: noqa
    available_transaction_method: Optional[list] = field(default=None)  # flake8: noqa
    minimum_loan_amount: Optional[int] = field(default=None)  # flake8: noqa


def is_even(x) -> bool:
    if x % 2 == 0:
        return True
    return False


def is_odd(x) -> bool:
    return not is_even(x)


class DelayedDisbursementContentView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):

        dd_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            is_active=True,
        ).last()

        # on / off
        if not dd_feature_setting:
            return success_response(data=asdict(DelayedDisbursementContent()))

        condition = dd_feature_setting.parameters.get("condition", None)
        if not condition:
            return success_response(data=asdict(DelayedDisbursementContent()))

        # start and cutoff
        now = timezone.localtime(timezone.now()).time()
        start_time = datetime.strptime(condition.get("start_time"), "%H:%M").time()
        end_time = datetime.strptime(condition.get("cut_off"), "%H:%M").time()
        if not (start_time <= now <= end_time):
            return success_response(data=asdict(DelayedDisbursementContent()))

        whitelist_rule = dd_feature_setting.parameters.get("whitelist_last_digit", 0)
        customer_id = request.user.customer.id
        if whitelist_rule == DDWhitelistLastDigit.ODD.code and not is_odd(customer_id):
            return success_response(data=asdict(DelayedDisbursementContent()))

        if whitelist_rule == DDWhitelistLastDigit.EVEN.code and not is_even(customer_id):
            return success_response(data=asdict(DelayedDisbursementContent()))

        # daily limit and monthly limit: wait for table loan_delay_disbursement
        monthly_limit = condition.get('monthly_limit', 0)
        daily_limit = condition.get('daily_limit', 0)
        is_daily_monthly_limit = check_daily_monthly_limit(customer_id, monthly_limit, daily_limit)
        if not is_daily_monthly_limit:
            return success_response(data=asdict(DelayedDisbursementContent()))

        tnc = ''
        content = dd_feature_setting.parameters.get("content", None)
        if content:
            tnc = content.get('tnc')

        data = DelayedDisbursementContent(
            is_active=dd_feature_setting.is_active,
            tnc=tnc,
            cashback=condition.get('cashback', 0),
            threshold_duration=condition.get('threshold_duration', 0),
            available_transaction_method=condition.get('list_transaction_method_code', []),
            minimum_loan_amount=condition.get('min_loan_amount', 0),
        )

        return success_response(data=asdict(data))

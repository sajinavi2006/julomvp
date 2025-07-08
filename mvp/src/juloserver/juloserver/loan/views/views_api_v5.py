import logging

from django.http.response import JsonResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView

from juloserver.account.models import Account
from juloserver.digisign.services.common_services import (
    calc_digisign_fee,
    calc_registration_fee,
    can_charge_digisign_fee,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, IdentifierKeyHeaderAPI
from juloserver.julo.models import FeatureSetting
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.constants import (
    DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST,
    DBRConst,
    LoanJuloOneConstant,
)
from juloserver.loan.services.adjusted_loan_matrix import (
    calculate_loan_amount_non_tarik_dana_delay_disbursement,
    get_adjusted_monthly_interest_rate_case_exceed,
    get_adjusted_total_interest_rate,
    validate_max_fee_rule,
)
from juloserver.loan.services.dbr_ratio import LoanDbrSetting, get_loan_max_duration
from juloserver.loan.services.delayed_disbursement_related import (
    DelayedDisbursementConst,
    DelayedDisbursementInsuredDetail,
    DelayedDisbursementProductCriteria,
    DelayedDisbursementQuoteRequest,
    get_delayed_disbursement_premium,
    is_eligible_for_delayed_disbursement,
)
from juloserver.loan.services.julo_care_related import get_eligibility_status
from juloserver.loan.services.loan_creation import (
    LoanCreditMatrices,
    get_loan_creation_cm_data,
    get_loan_matrices,
)
from juloserver.loan.services.loan_formula import LoanAmountFormulaService
from juloserver.loan.services.loan_related import (
    adjust_loan_with_zero_interest,
    calculate_installment_amount,
    compute_first_payment_installment_julo_one,
    get_first_payment_date_by_application,
    get_loan_amount_by_transaction_type,
    get_loan_duration,
    is_eligible_apply_zero_interest,
    is_product_locked,
    is_show_toggle_zero_interest,
    refiltering_cash_loan_duration,
)
from juloserver.loan.services.loan_tax import calculate_tax_amount
from juloserver.loan.services.transaction_model_related import MercuryCustomerService
from juloserver.loan.services.views_related import (
    LoanTenureRecommendationService,
    apply_pricing_logic,
    calculate_saving_information,
    check_if_tenor_based_pricing,
    check_tenor_fs,
    filter_loan_choice,
    get_crossed_installment_amount,
    get_crossed_loan_disbursement_amount,
    get_other_platform_monthly_interest_rate,
    get_provision_fee_from_credit_matrix,
    get_tenure_intervention,
    show_select_tenure,
)
from juloserver.loan.services.token_related import LoanTokenData, LoanTokenService
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.pin.decorators import parse_device_ios_user
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
)
from juloserver.balance_consolidation.services import (
    get_or_none_balance_consolidation,
)
from juloserver.julo.formulas import round_rupiah

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


class LoanCalculation(StandardizedExceptionHandlerMixin, APIView):
    class InputSerializer(serializers.Serializer):
        transaction_type_code = serializers.IntegerField(required=True)
        loan_amount_request = serializers.IntegerField(required=True)
        account_id = serializers.IntegerField(required=True)
        is_zero_interest = serializers.BooleanField(required=False)
        is_julo_care = serializers.BooleanField(required=False)
        is_show_saving_amount = serializers.BooleanField(required=False, default=False)
        device_brand = serializers.CharField(required=False)
        device_model = serializers.CharField(required=False)
        os_version = serializers.IntegerField(required=False)

        def validate_loan_amount_request(self, value):
            if value <= 0:
                raise ValidationError('Jumlah pinjaman harus lebih besar dari 0')
            return value

        def validate(self, data):
            """
            Check which campaign is active.
            """
            if data.get('is_zero_interest') and data.get('is_julo_care'):
                raise ValidationError("Multiple campaign active")
            return data

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # get data
        data = serializer.validated_data
        user = self.request.user
        device_ios_user = kwargs.get(IdentifierKeyHeaderAPI.KEY_IOS_DECORATORS, {})
        customer = request.user.customer

        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v5.LoanCalculation",
                "message": "before loan duration API v5",
                "customer_id": customer.id,
                "request_data": data,
            }
        )

        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')

        if user.id != account.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        # set up variables
        app = account.get_active_application()
        transaction_method_id = data.get('transaction_type_code')
        is_payment_point = transaction_method_id in TransactionMethodCode.payment_point()
        self_bank_account = transaction_method_id == TransactionMethodCode.SELF.code

        # transaction_method_name = TransactionMethodCode.code_from_name(transaction_type_code)

        # check lock product
        is_consolidation = get_or_none_balance_consolidation(user.customer.pk)
        if (
            is_product_locked(account, transaction_method_id, device_ios_user=device_ios_user)
            and not is_consolidation
        ):
            return forbidden_error_response(
                'Maaf, Anda tidak bisa menggunakan fitur ini.'
                'Silakan gunakan fitur lain yang tersedia di menu utama.'
            )

        account_limit = account.accountlimit_set.last()

        transaction_method = TransactionMethod.objects.get(pk=transaction_method_id)
        # get credit matrices & data
        loan_matrices = get_loan_matrices(
            transaction_method=transaction_method,
            application=app,
        )
        loan_creation_cm_data = get_loan_creation_cm_data(matrices=loan_matrices)

        # ana mercury
        mercury_service = MercuryCustomerService(account=account)
        (
            is_mercury,
            mercury_loan_tenure_from_ana,
        ) = mercury_service.get_mercury_status_and_loan_tenure(
            transaction_method_id=transaction_method_id,
        )
        # end mercury

        # get available duration
        max_duration = loan_creation_cm_data.max_tenure
        min_duration = loan_creation_cm_data.min_tenure
        available_duration = get_loan_duration(
            loan_amount_request=data['loan_amount_request'],
            max_duration=max_duration,
            min_duration=min_duration,
            set_limit=account_limit.set_limit,
            customer=customer,
            application=app,
        )

        available_duration = [1] if data['loan_amount_request'] <= 100000 else available_duration
        is_loan_one = available_duration[0] == 1

        if not available_duration:
            return general_error_response('Gagal mendapatkan durasi pinjaman')

        origination_fee_pct = loan_creation_cm_data.provision_fee_rate

        adjusted_loan_amount = LoanAmountFormulaService.get_adjusted_amount(
            requested_amount=data['loan_amount_request'],
            provision_rate=origination_fee_pct,
            transaction_method_code=transaction_method_id,
        )
        if adjusted_loan_amount > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )

        provision_fee = int(py2round(adjusted_loan_amount * origination_fee_pct))

        disbursement_amount = py2round(adjusted_loan_amount - provision_fee)
        today_date = timezone.localtime(timezone.now()).date()

        is_qris_transaction = transaction_method_id == TransactionMethodCode.QRIS.code
        is_ecommerce = transaction_method_id == TransactionMethodCode.E_COMMERCE.code
        first_payment_date = get_first_payment_date_by_application(app)

        # filter out duration less than 60 days due to google restriction for cash loan
        if not is_payment_point:
            available_duration = refiltering_cash_loan_duration(available_duration, app)

        # correct interest rate from correct CM
        monthly_interest_rate = loan_creation_cm_data.monthly_interest_rate

        # change monthly_interest_rate if repeat order
        min_pricing = None
        threshold = None
        new_tenor_feature_settings = check_tenor_fs()
        check_cmr_and_transaction_validation = False
        credit_matrix_repeat = loan_matrices.credit_matrix_repeat
        credit_matrix_product_line = loan_matrices.credit_matrix_product_line

        if credit_matrix_repeat:
            # if NEW_TENOR_BASED_PRICING is active then we use new tenor calculation
            if new_tenor_feature_settings:
                (
                    _,
                    _,
                    min_pricing,
                    threshold,
                    check_cmr_and_transaction_validation,
                ) = check_if_tenor_based_pricing(
                    customer,
                    new_tenor_feature_settings,
                    available_duration[0],
                    credit_matrix_repeat,
                    transaction_method_id,
                )

        other_platform_monthly_interest_rate = None
        if data['is_show_saving_amount']:
            other_platform_monthly_interest_rate = get_other_platform_monthly_interest_rate()

        is_show_toggle_zt = is_show_toggle_zero_interest(account.customer_id, transaction_method_id)

        # Add to check DBR status
        is_dbr = True  # always true from front end for V5
        loan_dbr = LoanDbrSetting(app, is_dbr)
        loan_dbr.update_popup_banner(self_bank_account, transaction_method_id)
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
        dd_feature_setting = FeatureSetting.objects.filter(
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
        credit_matrix_product = loan_matrices.credit_matrix.product
        if credit_matrix_repeat:
            """
            Assign `tag_campaign` (button text) and `tenure_intervention` (bottom sheet data)
            from `thor_tenor_intervention` feature setting for CMR.
            """
            tenure_intervention = get_tenure_intervention()
            provision_fee_credit_matrix, loan_amount_cm = get_provision_fee_from_credit_matrix(
                data['loan_amount_request'],
                credit_matrix_product,
                self_bank_account,
            )

        digisign_fee = 0
        total_registration_fee = 0
        if can_charge_digisign_fee(app):
            if transaction_method_id:
                digisign_fee = calc_digisign_fee(data['loan_amount_request'], transaction_method_id)

            # Only charge one time after registration success.
            registration_fees_dict = calc_registration_fee(app)
            total_registration_fee = sum(list(registration_fees_dict.values()))

        loan_token_service = LoanTokenService()
        loan_choice = {}
        for duration in available_duration:
            if default_duration_not_available and len(loan_choice) >= 4:
                """
                DBR only choose maximum 4 loans,
                currently our process is hardcoded to show 4 loan,
                this may need to be removed
                """
                break

            loan_amount_duration = adjusted_loan_amount
            monthly_interest_rate_duration = monthly_interest_rate
            if (
                credit_matrix_repeat
                and new_tenor_feature_settings
                and check_cmr_and_transaction_validation
            ):
                is_show_intervention = True
                monthly_interest_rate_duration, _ = apply_pricing_logic(
                    duration, threshold, credit_matrix_repeat, min_pricing
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
                    app,
                    data['loan_amount_request'],
                    self_bank_account,
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
                if origination_fee_pct_duration != provision_fee_rate and not self_bank_account:
                    loan_amount_duration = get_loan_amount_by_transaction_type(
                        data['loan_amount_request'], provision_fee_rate, self_bank_account
                    )
                if is_zero_interest:
                    provision_fee_duration = round_rupiah(loan_amount_duration * provision_fee_rate)
                    if self_bank_account:
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
                        "action": "juloserver.loan.views.views_api_v5.LoanCalculation",
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
                app.id,
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

            token_data = LoanTokenData(
                loan_requested_amount=data['loan_amount_request'],
                loan_duration=duration,
                customer_id=customer.id,
                expiry_time=LoanTokenService.get_expiry_time(),
                transaction_method_code=transaction_method_id,
            )
            current_choice = {
                'loan_token': loan_token_service.encrypt(data=token_data),
                'loan_amount': loan_amount_duration,
                'duration': duration,
                'monthly_installment': monthly_installment,
                'first_monthly_installment': first_monthly_installment,
                'provision_amount': admin_fee,
                'digisign_fee': digisign_fee + total_registration_fee,
                'disbursement_amount': int(disbursement_amount_duration),
                'cashback': int(
                    py2round(adjusted_loan_amount * credit_matrix_product.cashback_payment_pct)
                ),
                'available_limit': account_limit.available_limit,
                'available_limit_after_transaction': account_limit.available_limit
                - loan_amount_duration,
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
                "action": "juloserver.loan.views.views_api_v5.LoanCalculation",
                "message": "after loan duration API v5",
                "customer_id": customer.id,
                "response_data": response_data,
            }
        )
        return JsonResponse({'success': True, 'data': response_data, 'errors': []})

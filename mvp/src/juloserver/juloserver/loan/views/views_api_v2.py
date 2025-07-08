from __future__ import division
from past.utils import old_div
import math

from undecorated import undecorated
from babel.dates import format_date

from django.http.response import JsonResponse
from django.conf import settings
from django.db.utils import IntegrityError
from juloserver.account.services.credit_limit import update_available_limit
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from django.db import transaction
from django.utils import timezone

from juloserver.digisign.services.digisign_document_services import is_eligible_for_sign_document
from juloserver.ecommerce.services import get_iprice_transaction
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    BankDestinationIsNone,
    LoanDbrException,
)
from juloserver.loan.services.adjusted_loan_matrix import validate_max_fee_rule

from juloserver.payment_point.services.product_related import (
    determine_transaction_method_by_sepulsa_product,
)
from juloserver.promo.constants import PromoCodeVersion
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    forbidden_error_response,
    not_found_response,
)
from juloserver.julo.models import (
    Loan,
    SepulsaProduct,
    FeatureSetting,
)
from juloserver.account.models import AccountLimit, Account
from juloserver.loan.serializers import (
    LoanCalculationSerializer,
    LoanRequestSerializer,
    UserCampaignEligibilityV2RequestSerializer,
)
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
    get_loan_duration,
    calculate_installment_amount,
    generate_loan_payment_julo_one,
    get_loan_amount_by_transaction_type,
    compute_first_payment_installment_julo_one,
    refiltering_cash_loan_duration,
    get_first_payment_date_by_application,
    determine_transaction_method_by_transaction_type,
    get_transaction_type,
    update_loan_status_and_loan_history,
    get_ecommerce_limit_transaction,
    transaction_method_limit_check,
    is_product_locked,
    transaction_fdc_risky_check,
    transaction_hardtoreach_check,
)
from juloserver.pin.decorators import pin_verify_required
from juloserver.loan.constants import (
    LoanJuloOneConstant,
    GoogleDemo,
    LoanFeatureNameConst,
    DBRConst,
)
from juloserver.customer_module.models import BankAccountDestination
import logging
from juloserver.julo.formulas import round_rupiah

from juloserver.julo.statuses import LoanStatusCodes

from juloserver.loan.views.views_api_v1 import LoanAgreementDetailsView
from juloserver.loan.services.views_related import (
    UserCampaignEligibilityAPIV2Service,
    validate_loan_concurrency,
    validate_mobile_number,
    get_manual_signature,
)
from juloserver.loan.services.agreement_related import (
    get_loan_agreement_type,
    get_loan_agreement_template_julo_one,
)

from juloserver.julo.services2.sepulsa import SepulsaService

from juloserver.qris.services.legacy_service import QrisService

from juloserver.payment_point.constants import SepulsaProductCategory, TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.services.sepulsa import get_sepulsa_partner_amount
from juloserver.promo.services import PromoCodeService, get_promo_code_usage
from juloserver.account.constants import TransactionType
from juloserver.loan.services.loan_related import suspicious_ip_loan_fraud_check
from juloserver.fraud_score.constants import BonzaConstants
from juloserver.fraud_score.tasks import execute_hit_bonza_storing_api_inhouse
from juloserver.fraud_score.services import eligible_based_on_bonza_scoring
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.pin.models import BlacklistedFraudster
from juloserver.otp.services import verify_otp_transaction_session
from juloserver.loan.services.sphp import accept_julo_sphp, cancel_loan
from juloserver.ecommerce.services import update_iprice_transaction_loan
from juloserver.ecommerce.juloshop_service import (
    get_juloshop_loan_product_details,
    get_juloshop_transaction_by_loan,
)
from juloserver.pin.services import is_blacklist_android
from juloserver.fraud_score.serializers import fetch_android_id
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.loan.services.lender_related import julo_one_lender_auto_matchmaking
from juloserver.balance_consolidation.services import get_or_none_balance_consolidation
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.julo_starter.services.services import determine_application_for_credit_info
from juloserver.loan.services.loan_one_click_repeat import (
    get_latest_transactions_info,
    is_show_one_click_repeat,
)
from juloserver.loan.services.dbr_ratio import LoanDbrSetting
from juloserver.digisign.services.common_services import (
    can_charge_digisign_fee,
    calc_digisign_fee,
    calc_registration_fee
)
from juloserver.digisign.tasks import sign_document, initial_record_digisign_document

logger = logging.getLogger(__name__)


class LoanCalculation(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = LoanCalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

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
        if is_product_locked(account, transaction_method_id):
            return forbidden_error_response(
                'Maaf, Anda tidak bisa menggunakan fitur ini.'
                'Silakan gunakan fitur lain yang tersedia di menu utama.'
            )

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        available_duration = get_loan_duration(
            data['loan_amount_request'],
            credit_matrix_product_line.max_duration,
            credit_matrix_product_line.min_duration,
            account_limit.set_limit,
            customer=account.customer,
        )
        available_duration = [1] if data['loan_amount_request'] <= 100000 else available_duration
        is_loan_one = available_duration[0] == 1

        if not available_duration:
            return general_error_response('Gagal mendapatkan durasi pinjaman')
        loan_choice = []
        origination_fee_pct = credit_matrix.product.origination_fee_pct
        available_limit = account_limit.available_limit
        loan_amount = get_loan_amount_by_transaction_type(
            data['loan_amount_request'], origination_fee_pct, data['self_bank_account']
        )
        if loan_amount > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )
        provision_fee = int(py2round(loan_amount * origination_fee_pct))
        available_limit_after_transaction = available_limit - loan_amount
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
        monthly_interest_rate = credit_matrix.product.monthly_interest_rate

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
            (
                is_exceeded,
                _,
                max_fee_rate,
                provision_fee_rate,
                adjusted_interest_rate,
                _,
                _,
            ) = validate_max_fee_rule(
                first_payment_date, monthly_interest_rate, duration, origination_fee_pct
            )

            if is_exceeded:
                # adjust loan amount based on new provision
                if origination_fee_pct != provision_fee_rate and not data['self_bank_account']:
                    loan_amount = get_loan_amount_by_transaction_type(
                        data['loan_amount_request'], provision_fee_rate, data['self_bank_account']
                    )
                provision_fee = int(py2round(loan_amount * provision_fee_rate))
                disbursement_amount = py2round(loan_amount - provision_fee)
                monthly_interest_rate = adjusted_interest_rate

            monthly_installment = calculate_installment_amount(
                loan_amount, duration, monthly_interest_rate
            )

            if (
                is_loan_one
                and (is_payment_point or is_qris_transaction or is_ecommerce)
                and not is_exceeded
            ):
                _, _, monthly_installment = compute_first_payment_installment_julo_one(
                    loan_amount, duration, monthly_interest_rate, today_date, first_payment_date
                )

            loan_choice.append(
                {
                    'loan_amount': loan_amount,
                    'duration': duration,
                    'monthly_installment': monthly_installment,
                    'provision_amount': provision_fee,
                    'digisign_fee': digisign_fee + total_registration_fee,
                    'disbursement_amount': int(disbursement_amount),
                    'cashback': int(
                        py2round(loan_amount * credit_matrix.product.cashback_payment_pct)
                    ),
                    'available_limit': available_limit,
                    'available_limit_after_transaction': available_limit_after_transaction,
                }
            )

        return JsonResponse({'success': True, 'data': loan_choice, 'errors': []})


class RangeLoanAmount(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, account_id):
        self_bank_account = request.GET.get('self_bank_account', False)
        self_bank_account = self_bank_account == 'true'
        account = Account.objects.get_or_none(pk=int(account_id))
        if not account:
            return general_error_response('Account tidak ditemukan')
        user = self.request.user
        application = account.get_active_application()
        if application.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')
        account_limit = AccountLimit.objects.filter(account=account).last()
        available_limit = account_limit.available_limit

        # TODO check if this need to send in input param
        is_self_bank_account = True
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
            application, is_self_bank_account, None, transaction_type
        )

        if credit_matrix is None or credit_matrix.product is None:
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

        origination_fee = credit_matrix.product.origination_fee_pct
        max_amount = available_limit
        if not self_bank_account:
            max_amount -= int(py2round(max_amount * origination_fee))
        min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        if transaction_type == TransactionType.ECOMMERCE:
            min_amount_threshold = get_ecommerce_limit_transaction()
        elif transaction_type == TransactionMethodCode.EDUCATION.name:
            min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_EDUCATION
        min_amount = (
            min_amount_threshold if min_amount_threshold < available_limit else available_limit
        )
        response_data = dict(
            min_amount_threshold=min_amount_threshold, min_amount=min_amount, max_amount=max_amount
        )

        return JsonResponse({'success': True, 'data': response_data, 'errors': []})


class LoanJuloOne(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanRequestSerializer

    @pin_verify_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        logger.info(
            {
                'action': 'LoanJuloOne_v2',
                'data': data,
            }
        )
        mobile_number = data['mobile_number']
        if mobile_number and not validate_mobile_number(mobile_number):
            logger.warning(
                {
                    'action': 'LoanJuloOne_v2_InvalidMobileNumber',
                    'data': data,
                    'mobile_number': mobile_number,
                }
            )
            return general_error_response(ErrorMessageConst.PHONE_INVALID)

        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')
        application = account.get_active_application()
        user = self.request.user
        if application.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        if data['loan_amount_request'] > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )

        _, concurrency_messages = validate_loan_concurrency(application.account)
        if concurrency_messages:
            return general_error_response(concurrency_messages['content'])

        is_payment_point = data['is_payment_point'] if 'is_payment_point' in data else False
        data['self_bank_account'] = False if is_payment_point else data['self_bank_account']
        is_fraudster = False
        android_id = fetch_android_id(application.customer)
        is_fraudster = is_blacklist_android(android_id)
        transaction_method_id = data.get('transaction_type_code', None)
        if transaction_method_id in TransactionMethodCode.mobile_transactions() and mobile_number:
            if BlacklistedFraudster.objects.filter(phone_number=mobile_number).exists():
                is_fraudster = True

        if is_fraudster:
            return general_error_response(
                'Transaksi tidak dapat di proses.'
                'Mohon hubungi cs@julo.co.id untuk detail lebih lanjut'
            )

        transaction_type = None
        if transaction_method_id:
            transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
            if transaction_method:
                transaction_type = transaction_method.method
        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(
            application, data['self_bank_account'], is_payment_point, transaction_type
        )
        origination_fee_pct = credit_matrix.product.origination_fee_pct
        loan_amount = data['loan_amount_request']

        if is_payment_point:
            product = SepulsaProduct.objects.filter(
                pk=data['payment_point_product_id'],
            ).last()
            if not product:
                return general_error_response('Produk tidak ditemukan')
            # for postpaid product we need amount from inquiry
            if product.category not in SepulsaProductCategory.POSTPAID:
                loan_amount = product.customer_price_regular

        # check lock product
        if is_product_locked(account, transaction_method_id):
            return forbidden_error_response(
                'Maaf, Anda tidak bisa menggunakan fitur ini.'
                'Silakan gunakan fitur lain yang tersedia di menu utama.'
            )
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            loan_amount, origination_fee_pct, data['self_bank_account']
        )
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

        loan_requested = dict(
            is_loan_amount_adjusted=is_loan_amount_adjusted,
            original_loan_amount_requested=loan_amount,
            loan_amount=adjusted_loan_amount,
            loan_duration_request=data['loan_duration'],
            interest_rate_monthly=credit_matrix.product.monthly_interest_rate,
            product=credit_matrix.product,
            provision_fee=origination_fee_pct,
            is_withdraw_funds=data['self_bank_account'],
            is_consolidation=get_or_none_balance_consolidation(account.customer_id),
            transaction_method_id=transaction_method_id,
            product_line_code=credit_matrix_product_line.product.product_line_code,
            digisign_fee=digisign_fee,
            registration_fees_dict=registration_fees_dict,
        )
        bank_account_destination_id = None
        loan_purpose = None
        is_qris_transaction = transaction_type == TransactionMethodCode.QRIS.name
        if not is_payment_point and not is_qris_transaction:
            bank_account_destination_id = data['bank_account_destination_id']
            loan_purpose = data['loan_purpose']
        bank_account_destination = BankAccountDestination.objects.get_or_none(
            pk=bank_account_destination_id
        )

        # check bank destination exists
        try:
            if (
                transaction_method_id in TransactionMethodCode.require_bank_account_destination()
                and not bank_account_destination
            ):
                raise BankDestinationIsNone(
                    "bank destination id: {}".format(bank_account_destination_id)
                )
        except BankDestinationIsNone:
            get_julo_sentry_client().captureException()
            return general_error_response("Bank account not found")
        #

        # Create QRIS Loan at 209 for beginning
        draft_loan = False
        if is_qris_transaction:
            draft_loan = True

        tax = 0
        try:
            loan_update_dict = {}
            with transaction.atomic():
                account_limit = (
                    AccountLimit.objects.select_for_update()
                    .filter(account=application.account)
                    .last()
                )
                if data['loan_amount_request'] > account_limit.available_limit:
                    raise AccountLimitExceededException(
                        "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
                    )
                loan = generate_loan_payment_julo_one(
                    application,
                    loan_requested,
                    loan_purpose,
                    credit_matrix,
                    bank_account_destination,
                    draft_loan=draft_loan,
                )

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
                transaction_fdc_risky_check(loan)
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

                elif is_payment_point:
                    sepulsa_service = SepulsaService()
                    paid_period = None
                    customer_amount = None
                    partner_amount = get_sepulsa_partner_amount(loan_amount, product)
                    customer_number = None
                    if partner_amount:
                        customer_amount = loan_amount
                    if 'customer_number' in data and data['customer_number']:
                        customer_number = data['customer_number']
                    elif 'bpjs_number' in data and data['bpjs_number']:
                        customer_number = data['bpjs_number']
                        paid_period = data['bpjs_times']

                    sepulsa_service.create_transaction_sepulsa(
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
                        admin_fee=product.admin_fee,
                        service_fee=product.service_fee,
                        paid_period=paid_period,
                        collection_fee=product.collection_fee,
                    )
                    if not transaction_method:
                        transaction_method = determine_transaction_method_by_sepulsa_product(
                            product
                        )
                in_limit, error = transaction_method_limit_check(account, transaction_method)
                if not in_limit:
                    raise AccountLimitExceededException(error)
                update_available_limit(loan)
                loan_update_dict['transaction_method'] = transaction_method
                loan.update_safely(**loan_update_dict)
                tax = loan.get_loan_tax_fee()
                if tax:
                    loan.set_disbursement_amount()
                    loan.save()
            # assgin lender
            lender = julo_one_lender_auto_matchmaking(loan)
            if lender:
                loan.update_safely(lender_id=lender.pk, partner_id=lender.user.partner.pk)

        except AccountLimitExceededException as e:
            return general_error_response(str(e))

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

        disbursement_amount = py2round(loan.loan_amount - loan.provision_fee())
        installment_amount = round_rupiah(
            math.floor(
                (old_div(loan.loan_amount, loan.loan_duration))
                + (loan.interest_rate_monthly * loan.loan_amount)
            )
        )
        if is_payment_point and loan.loan_duration == 1:
            installment_amount = loan.first_installment_amount
        return JsonResponse(
            {
                'success': True,
                'data': {
                    'loan_id': loan.id,
                    'loan_status': loan.status,
                    'loan_amount': loan.loan_amount,
                    'disbursement_amount': disbursement_amount,
                    'tax': tax,
                    'loan_duration': loan.loan_duration,
                    'installment_amount': installment_amount,
                    'monthly_interest': credit_matrix.product.monthly_interest_rate,
                    'loan_xid': loan.loan_xid,
                },
                'errors': [],
            }
        )


class DraftLoanJuloOne(LoanJuloOne):
    serializer_class = LoanRequestSerializer

    def post(self, request):
        trx_method_id = request.data.get('transaction_type_code', None)
        if not trx_method_id or int(trx_method_id) not in TransactionMethodCode.draft_loan():
            return general_error_response("Not Allowed")
        return undecorated(super().post)(self, request)


class EnableLoanJuloOne(StandardizedExceptionHandlerMixin, APIView):
    @pin_verify_required
    def post(self, request, loan_xid):
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan or loan.customer.user_id != request.user.id:
            return general_error_response('Something wrong!')

        if loan.status != LoanStatusCodes.DRAFT:
            return general_error_response('Invalid Loan status')

        update_loan_status_and_loan_history(
            loan_id=loan.id, new_status_code=LoanStatusCodes.INACTIVE, change_reason="Enable Loan"
        )

        return success_response('Success')


class ChangeLoanStatusView(StandardizedExceptionHandlerMixin, APIView):
    @verify_otp_transaction_session
    def post(self, request, loan_xid):
        data = request.data
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        user = self.request.user

        logger.info(
            {
                'action': 'ChangeLoanStatusView',
                'data': {**request.data, 'loan_xid': loan_xid, 'user_id': user.id},
            }
        )

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        if loan.is_credit_card_transaction:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        if not loan or loan.status not in LoanStatusCodes.inactive_status():
            return general_error_response("Loan XID:{} Not found".format(loan_xid))

        if 'status' not in data:
            return general_error_response("No Data Sent")

        if data['status'] == 'finish' and not get_manual_signature(loan):
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        # iPrice ecommerce transaction
        iprice_transaction_id = data.get('iprice_transaction_id', None)
        if iprice_transaction_id:
            update_iprice_transaction_loan(iprice_transaction_id, loan)

        if data['status'] == 'finish' and loan.status == LoanStatusCodes.INACTIVE:
            # case promo code --
            if data.get('promo_code', None) and not loan.is_balance_consolidation:
                try:
                    promo_code_usage = get_promo_code_usage(loan)
                    if not promo_code_usage:
                        promo_code_service = PromoCodeService(
                            promo_code_str=data['promo_code'], version=PromoCodeVersion.V1
                        )
                        promo_code_service.proccess_applied_with_loan(loan=loan)
                except Exception as e:
                    logger.error(
                        {
                            'action': 'ChangeLoanStatusView',
                            'error': str(e),
                            'data': {**request.data, 'loan_xid': loan_xid, 'user_id': user.id},
                        }
                    )
                    return general_error_response("Invalid Promo Code")
            # -- promo code
            if is_eligible_for_sign_document(loan):
                try:
                    digisign_document = initial_record_digisign_document(loan.id)
                    sign_document.delay(digisign_document.id)
                    new_loan_status = LoanStatusCodes.INACTIVE
                except IntegrityError as err:
                    logger.error(
                        {
                            'action': 'ChangeLoanStatusView',
                            'error': str(err),
                            'data': {**request.data, 'loan_xid': loan_xid, 'user_id': user.id},
                        }
                    )
                    return general_error_response(
                        "Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi."
                    )
            else:
                new_loan_status = accept_julo_sphp(loan, "JULO")
        elif data['status'] == 'cancel':
            new_loan_status = cancel_loan(loan)
        else:
            return general_error_response("Invalid Status Request")

        data = {
            'id': loan.id,
            'status': new_loan_status,
            'loan_xid': loan_xid,
        }
        return success_response(data=data)


class LoanAgreementDetailsView(LoanAgreementDetailsView):
    def get(self, request, loan_xid):
        response = super(LoanAgreementDetailsView, self).get(request, loan_xid)
        if response.status_code == HTTP_200_OK:
            response.data['data']['loan_agreement'] = get_loan_agreement_type(loan_xid)

            loan = Loan.objects.get_or_none(loan_xid=loan_xid)
            oldest_payment = loan.payment_set.order_by('payment_number').first()
            response.data['data']['loan']['due_date'] = format_date(
                oldest_payment.due_date, 'd MMM yyyy', locale='id_ID'
            )

            juloshop_transaction = get_juloshop_transaction_by_loan(loan)
            if juloshop_transaction:
                julo_shop_product = get_juloshop_loan_product_details(juloshop_transaction)
                julo_shop_data = {
                    "product_name": julo_shop_product.get('productName'),
                    "bank_name": settings.JULOSHOP_BANK_NAME,
                    "bank_account_name": settings.JULOSHOP_ACCOUNT_NAME,
                    "bank_account_number": settings.JULOSHOP_BANK_ACCOUNT_NUMBER,
                }
                response.data['data']['loan'].update(julo_shop_data)

        return Response(status=response.status_code, data=response.data)


class LoanAgreementContentView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        user = self.request.user
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan XID:{} Not found".format(loan_xid))

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        text_agreement, _ = get_loan_agreement_template_julo_one(loan.id)
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

        transaction_info = get_latest_transactions_info(customer, True, "v2", application)
        return success_response(transaction_info)


class UserCampaignEligibilityView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = UserCampaignEligibilityV2RequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        service = UserCampaignEligibilityAPIV2Service(
            customer=request.user.customer,
            validated_data=data,
        )
        response_data = service.construct_response_data()

        return success_response(data=response_data)

from __future__ import division

from builtins import str
from past.utils import old_div
import math
import logging

from django.http.response import JsonResponse

from juloserver.account.services.credit_limit import update_available_limit
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView
from rest_framework.serializers import ValidationError
from django.conf import settings
from django.db import transaction
from rest_framework.response import Response
from rest_framework import serializers, status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from juloserver.account.services.account_related import get_dpd_and_lock_colour_by_account
from juloserver.credit_card.services.card_related import is_julo_card_whitelist_user
from juloserver.customer_module.services.customer_related import julo_starter_proven_bypass

from juloserver.julocore.python2.utils import py2round
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    LoanDbrException,
)
from juloserver.loan.services.adjusted_loan_matrix import validate_max_fee_rule

from juloserver.payment_point.services.product_related import (
    determine_transaction_method_by_sepulsa_product,
)
from juloserver.payment_point.services.sepulsa import SepulsaLoanService
from juloserver.payment_point.services.train_related import is_train_ticket_whitelist_user
from juloserver.payment_point.services.views_related import construct_transaction_method_for_android
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    not_found_response,
)
from juloserver.julo.models import (
    LoanPurpose,
    ProductLine,
    Loan,
    SepulsaProduct,
    FeatureSetting,
    MobileFeatureSetting
)
from juloserver.account.models import AccountLimit, Account
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.serializers import (
    LoanCalculationSerializer,
    LoanRequestSerializer,
    LoanRequestValidationSerializer,
    LoanDetailsSerializer,
    LoanDurationSimulationSerializer,
    JuloCareCallbackSerializer,
    LoanSignatureUploadSerializer,
)
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
    get_loan_duration,
    calculate_installment_amount,
    generate_loan_payment_julo_one,
    get_loan_amount_by_transaction_type,
    determine_first_due_dates_by_payday,
    compute_first_payment_installment_julo_one,
    get_loan_from_xid,
    refiltering_cash_loan_duration,
    get_first_payment_date_by_application,
    determine_transaction_method_by_transaction_type,
    get_transaction_type,
    is_customer_can_do_zero_interest,
    update_loan_status_and_loan_history
)
from juloserver.pin.decorators import pin_verify_required
from juloserver.account.constants import AccountConstant
from juloserver.julo.constants import FeatureNameConst
from juloserver.loan.constants import (
    LoanJuloOneConstant,
    FIREBASE_LOAN_STAUSES,
    LoanFeatureNameConst,
    DBRConst,
    LockedProductPageConst,
)
from juloserver.loan.services.views_related import (
    get_cross_selling_recommendations,
)
from juloserver.customer_module.models import BankAccountDestination
from juloserver.customer_module.services.view_related import check_whitelist_transaction_method

from juloserver.julo.formulas import round_rupiah
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_one_click_repeat import (
    get_latest_transactions_info,
    is_show_one_click_repeat,
)
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.loan.services.views_related import get_active_platform_rule_response_data

from ..services.views_related import LockedProductPageService, append_qris_method, get_loan_details
from ..services.views_related import TransactionResultAPIService, AvailableLimitInfoAPIService
from ..services.views_related import get_voice_record
from ..services.views_related import get_manual_signature
from ..serializers import CreateVoiceRecordSerializer
from ..serializers import CreateManualSignatureSerializer
from juloserver.julo.tasks import upload_voice_record_julo_one
from juloserver.loan.services.views_related import (
    get_sphp_template_julo_one,
    validate_mobile_number,
    get_list_object_saving_information_duration,
)
from juloserver.julo.tasks import upload_image_julo_one
from ..services.sphp import accept_julo_sphp, cancel_loan
from juloserver.julo.exceptions import JuloException
from ..services.views_related import validate_loan_concurrency
from juloserver.grab.services.loan_related import process_grab_loan_signature_upload_success

from ..services.views_related import get_voice_record_script
from ..services.views_related import get_privy_bypass_feature
from ...julo.product_lines import ProductLineNotFound

from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    forbidden_error_response,
)
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    TransactionMethodCode,
    FeatureNameConst as FeatureNameConstPayment,
)
from juloserver.payment_point.models import TransactionMethod

from juloserver.balance_consolidation.services import get_or_none_balance_consolidation

from juloserver.payment_point.services.sepulsa import get_sepulsa_partner_amount
from juloserver.fraud_score.constants import BonzaConstants
from juloserver.fraud_score.tasks import execute_hit_bonza_storing_api_inhouse
from juloserver.fraud_score.services import eligible_based_on_bonza_scoring
from juloserver.julo.services import prevent_web_login_cases_check, get_julo_one_is_proven
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.julo_starter.services.services import determine_application_for_credit_info
from juloserver.loan.services.julo_care_related import get_julo_care_configuration
from juloserver.loan.services.julo_care_related import update_loan_julo_care
from juloserver.loan.services.dbr_ratio import LoanDbrSetting
from juloserver.loan.utils import is_max_creditors_done_in_1_day
from juloserver.digisign.services.common_services import (
    can_charge_digisign_fee,
    calc_digisign_fee,
    calc_registration_fee
)


logger = logging.getLogger(__name__)


class LoanCalculation(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = LoanCalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')

        if user.id != account.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        application = account.get_active_application()
        is_payment_point = data.get('is_payment_point', False)
        data['self_bank_account'] = False if is_payment_point else data['self_bank_account']
        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(
            application, data['self_bank_account'], is_payment_point
        )
        account_limit = AccountLimit.objects.filter(account=application.account).last()
        available_duration = get_loan_duration(
            data['loan_amount_request'],
            credit_matrix_product_line.max_duration,
            credit_matrix_product_line.min_duration,
            account_limit.set_limit,
        )
        available_duration = [1] if data['loan_amount_request'] <= 100000 else available_duration
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
        first_payment_date = get_first_payment_date_by_application(application)

        # filter out duration less than 60 days due to google restriction for cash loan
        if not is_payment_point:
            available_duration = refiltering_cash_loan_duration(available_duration, application)
        monthly_interest_rate = credit_matrix.product.monthly_interest_rate

        transaction_method_id = data.get('transaction_type_code', None)
        digisign_fee = 0
        total_registration_fee = 0
        if can_charge_digisign_fee(application):
            if transaction_method_id:
                digisign_fee = calc_digisign_fee(
                    application, data['loan_amount_request'], transaction_method_id
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

            if is_payment_point and available_duration[0] == 1 and not is_exceeded:
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
        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(application, is_self_bank_account)
        origination_fee = credit_matrix.product.origination_fee_pct
        max_amount = available_limit
        if not self_bank_account:
            max_amount -= int(py2round(max_amount * origination_fee))
        min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
        min_amount = (
            min_amount_threshold if min_amount_threshold < available_limit else available_limit
        )
        response_data = dict(
            min_amount_threshold=min_amount_threshold, min_amount=min_amount, max_amount=max_amount
        )

        return JsonResponse({'success': True, 'data': response_data, 'errors': []})


def get_julo_one_loan_purpose(request):
    product_line = ProductLine.objects.get_or_none(pk=ProductLineCodes.J1)

    loan_purpose = (
        LoanPurpose.objects.filter(product_lines=product_line).values('purpose').order_by('id')
    )

    return JsonResponse({'success': True, 'data': list(loan_purpose), 'errors': []})


class LoanJuloOne(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanRequestSerializer

    @pin_verify_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        logger.info(
            {
                'action': 'LoanJuloOne_v1',
                'data': data,
            }
        )

        mobile_number = data['mobile_number']
        if mobile_number and not validate_mobile_number(mobile_number):
            logger.warning(
                {
                    'action': 'LoanJuloOne_v1_InvalidMobileNumber',
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

        _, concurrency_messages = validate_loan_concurrency(application.account)
        if concurrency_messages:
            return general_error_response(concurrency_messages['content'])

        is_payment_point = data['is_payment_point'] if 'is_payment_point' in data else False
        data['self_bank_account'] = False if is_payment_point else data['self_bank_account']
        (
            credit_matrix,
            credit_matrix_product_line,
        ) = get_credit_matrix_and_credit_matrix_product_line(
            application, data['self_bank_account'], is_payment_point
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

        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            loan_amount, origination_fee_pct, data['self_bank_account']
        )
        is_loan_amount_adjusted = True

        # calculate digisign fee
        transaction_method_id = data.get('transaction_type_code', None)
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
            digisign_fee=digisign_fee,
            is_withdraw_funds=data['self_bank_account'],
            is_consolidation=get_or_none_balance_consolidation(account.customer_id),
            transaction_method_id=data.get('transaction_type_code', None),
            product_line_code=credit_matrix_product_line.product.product_line_code,
            registration_fees_dict=registration_fees_dict,
        )
        bank_account_destination_id = None
        loan_purpose = None
        if not is_payment_point:
            bank_account_destination_id = data['bank_account_destination_id']
            loan_purpose = data['loan_purpose']
        bank_account_destination = BankAccountDestination.objects.get_or_none(
            pk=bank_account_destination_id
        )

        tax = 0
        try:
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
                )

                # BONZA SCORING
                if loan.product.product_line_id == ProductLineCodes.J1:
                    bonza_eligible, reject_reason = eligible_based_on_bonza_scoring(loan)
                    if not bonza_eligible and reject_reason == BonzaConstants.SOFT_REJECT_REASON:
                        return general_error_response(BonzaConstants.NON_ELIGIBLE_SCORE_SOFT_REJECT)
                    elif not bonza_eligible and reject_reason == BonzaConstants.HARD_REJECT_REASON:
                        return general_error_response(BonzaConstants.NON_ELIGIBLE_SCORE_HARD_REJECT)

                transaction_type = get_transaction_type(
                    data['self_bank_account'], is_payment_point, bank_account_destination
                )
                transaction_method = determine_transaction_method_by_transaction_type(
                    transaction_type
                )
                if is_payment_point:
                    sepulsa_service = SepulsaLoanService()
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
                    transaction_method = determine_transaction_method_by_sepulsa_product(product)

                loan.update_safely(transaction_method=transaction_method)
                tax = loan.get_loan_tax_fee()
                if tax:
                    loan.set_disbursement_amount()
                    loan.save()
                update_available_limit(loan)
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


class LoanRequestValidation(StandardizedExceptionHandlerMixin, APIView):
    http_method_names = ['get']
    serializer_class = LoanRequestValidationSerializer

    def get(self, request, *args, **kwargs):
        user = request.user
        serializer = LoanRequestValidationSerializer(data=request.GET.dict())
        if not serializer.is_valid():
            return general_error_response(serializer.errors)
        data = serializer.data
        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')

        if user.id != account.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        is_consolidation = get_or_none_balance_consolidation(account.customer_id)
        if account.status.status_code not in AccountConstant.UNLOCK_STATUS and not is_consolidation:
            return general_error_response('Account tidak dapat melakukan transaksi saat ini')

        application = account.get_active_application()
        account_limit = AccountLimit.objects.filter(account=application.account).last()
        if data['loan_amount_request'] > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )

        return JsonResponse(
            {
                'success': True,
                'data': {
                    'available_limit': account_limit.available_limit,
                    'loan_amount_request': data['loan_amount_request'],
                },
                'errors': [],
            }
        )


class LoanAgreementDetailsView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, loan_xid):
        user = self.request.user
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        partner_name = request.query_params.get('partner_name', None)

        if not loan:
            return general_error_response(
                message="Loan XID:{} Not Found or Expired".format(loan_xid)
            )

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        return_data = dict()
        return_data['loan'] = get_loan_details(loan)
        return_data['voice_record'] = get_voice_record(loan)
        return_data['manual_signature'] = get_manual_signature(loan)
        return_data['privy_bypass'] = get_privy_bypass_feature(loan)
        login_check, error_message = prevent_web_login_cases_check(user, partner_name)
        return_data['eligible_access'] = dict(is_eligible=login_check, error_message=error_message)

        return success_response(data=return_data)


class LoanAgreementContentView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        user = self.request.user
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan XID:{} Not found".format(loan_xid))

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        text_sphp = get_sphp_template_julo_one(loan.id, type="android")
        return success_response(data=text_sphp)


class LoanUploadSignatureView(StandardizedExceptionHandlerMixin, CreateAPIView):
    serializer_class = CreateManualSignatureSerializer

    def create(self, request, *args, **kwargs):
        user = self.request.user
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan:
            return general_error_response("Loan XID:{} Not found".format(loan_xid))

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        try:
            data = request.POST.copy()
        except TypeError:
            err_msg = "Unsupported file format. Please upload a valid signature"
            return general_error_response(err_msg)

        data['image_source'] = loan.id
        data['image_type'] = 'signature'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        if loan.account and loan.account.is_grab_account():
            is_done_in_one_day = is_max_creditors_done_in_1_day(loan, loan.customer.id)
            if not is_done_in_one_day:
                rejected_message = "No 3 max creditors check"
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    change_reason=rejected_message,
                )
                return general_error_response(rejected_message)

        try:
            self.perform_create(serializer)
            if (
                loan.account
                and loan.account.is_grab_account()
                and loan.loan_status_id == LoanStatusCodes.INACTIVE
            ):
                process_grab_loan_signature_upload_success(loan)
        except JuloException as je:
            return general_error_response(message=str(je))
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        if (
            'upload' not in self.request.POST
            or 'data' not in self.request.POST
            or not self.request.POST['upload']
            or not self.request.POST['data']
        ):
            raise JuloException("No Upload Data")

        loan_signature_upload_serializer = LoanSignatureUploadSerializer(data=self.request.data)
        loan_signature_upload_serializer.is_valid(raise_exception=True)

        signature = serializer.save()
        image_file = self.request.data['upload']
        signature.image.save(self.request.data['data'], image_file)
        upload_image_julo_one.delay(signature.id)


class LoanVoiceUploadView(StandardizedExceptionHandlerMixin, CreateAPIView):
    serializer_class = CreateVoiceRecordSerializer

    def create(self, request, *args, **kwargs):
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        user = self.request.user

        if not loan:
            return general_error_response("Loan XID:{} Not found".format(loan_xid))

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        data = request.POST.copy()
        data['loan'] = loan.id
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except JuloException as je:
            return general_error_response(message=str(je))
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        if (
            'upload' not in self.request.POST
            or 'data' not in self.request.POST
            or not self.request.POST['upload']
            or not self.request.POST['data']
        ):
            raise JuloException("No Upload Data")
        voice_record = serializer.save()
        voice_file = self.request.data['upload']
        voice_record.tmp_path.save(self.request.data['data'], voice_file)
        upload_voice_record_julo_one.delay(voice_record.id)


class ChangeLoanStatusView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request, loan_xid):
        data = request.data
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        user = self.request.user

        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        if loan.is_credit_card_transaction:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        if not loan or loan.status not in LoanStatusCodes.inactive_status():
            return general_error_response("Loan XID:{} Not found".format(loan_xid))
        if 'status' not in data:
            return general_error_response("No Data Sent")
        if data['status'] == 'finish' and loan.status == LoanStatusCodes.INACTIVE:
            # checking deposit status before active rentee loan
            if hasattr(loan, 'paymentdeposit') and not loan.paymentdeposit.is_success():
                return general_error_response("Invalid Status Request")

            new_loan_status = accept_julo_sphp(loan, "JULO")
        elif data['status'] == 'cancel':
            new_loan_status = cancel_loan(loan)
        else:
            return general_error_response("Invalid Status Request")

        return success_response(
            data={'id': loan.id, "status": new_loan_status, "loan_xid": loan_xid}
        )


class VoiceRecordScriptView(APIView):
    def get(self, request, loan_xid):
        loan = get_object_or_404(Loan, loan_xid=loan_xid)
        user = self.request.user
        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])
        try:
            return Response({'script': get_voice_record_script(loan)})
        except ProductLineNotFound as pe:
            return general_error_response(str(pe))


class FirebaseEventLoanListView(APIView):
    def get(self, request):
        try:
            customer = self.request.user.customer
            queryset = Loan.objects.filter(
                loan_status_id__in=FIREBASE_LOAN_STAUSES,
                customer=customer,
                account__isnull=False,
                account__customer=customer,
                application__isnull=True,
            )
            serializer = LoanDetailsSerializer(queryset, many=True)
            return success_response(serializer.data)
        except JuloException as je:
            return general_error_response(str(je))


class RangeLoanAmountSimulation(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        response_data = dict(
            min_amount_threshold=LoanJuloOneConstant.MIN_LOAN_AMOUNT_SIMULATION,
            min_amount=LoanJuloOneConstant.MIN_LOAN_AMOUNT_SIMULATION,
            max_amount=LoanJuloOneConstant.MAX_LOAN_AMOUNT_SIMULATION,
        )
        return success_response(response_data)


class LoanDurationSimulation(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanDurationSimulationSerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        available_duration = get_loan_duration(
            data['loan_amount'],
            LoanJuloOneConstant.MAX_DURATION_SIMULATION,
            LoanJuloOneConstant.MIN_DURATION_SIMULATION,
            LoanJuloOneConstant.MAX_LOAN_AMOUNT_SIMULATION,
        )
        if data['is_payment_point'] and data['loan_amount'] <= 100000:
            available_duration = [1]
        origination_fee = LoanJuloOneConstant.ORIGINATION_FEE_SIMULATION
        interest = LoanJuloOneConstant.INTEREST_SIMULATION
        loan_amount = get_loan_amount_by_transaction_type(
            data['loan_amount'], origination_fee, data['self_bank_account']
        )
        provision_fee = int(py2round(loan_amount * origination_fee))
        available_limit_after_transaction = (
            LoanJuloOneConstant.MAX_LOAN_AMOUNT_SIMULATION - loan_amount
        )
        disbursement_amount = py2round(loan_amount - provision_fee)
        today_date = timezone.localtime(timezone.now()).date()
        first_payment_date = determine_first_due_dates_by_payday(1, today_date, ProductLineCodes.J1)

        loan_choices = []
        for duration in available_duration:
            (
                is_exceeded,
                _,
                max_fee_rate,
                provision_fee_rate,
                adjusted_interest_rate,
                _,
                _,
            ) = validate_max_fee_rule(first_payment_date, interest, duration, origination_fee)

            if is_exceeded:
                # adjust loan amount based on new provision
                if origination_fee != provision_fee_rate and not data['self_bank_account']:
                    loan_amount = get_loan_amount_by_transaction_type(
                        data['loan_amount'], provision_fee_rate, data['self_bank_account']
                    )
                provision_fee = int(py2round(loan_amount * provision_fee_rate))
                disbursement_amount = py2round(loan_amount - provision_fee)
                interest = adjusted_interest_rate

            monthly_installment = calculate_installment_amount(loan_amount, duration, interest)
            if data['is_payment_point'] and available_duration[0] == 1 and not is_exceeded:
                _, _, monthly_installment = compute_first_payment_installment_julo_one(
                    loan_amount, duration, interest, today_date, first_payment_date
                )
            loan_choices.append(
                {
                    'loan_amount': loan_amount,
                    'duration': duration,
                    'monthly_installment': monthly_installment,
                    'provision_amount': provision_fee,
                    'disbursement_amount': int(disbursement_amount),
                    'cashback': int(
                        py2round(loan_amount * LoanJuloOneConstant.CASHBACK_SIMULATION)
                    ),
                    'available_limit': LoanJuloOneConstant.MAX_LOAN_AMOUNT_SIMULATION,
                    'available_limit_after_transaction': available_limit_after_transaction,
                }
            )

        return success_response(loan_choices)


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

        transaction_info = get_latest_transactions_info(customer, True, "v1", application)
        return success_response(transaction_info)


class SavingInformationDuration(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        return success_response(get_list_object_saving_information_duration())


class ZeroInterestPopupBanner(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION, is_active=True
        ).last()

        if not feature_setting:
            return success_response()

        if 'content' not in feature_setting.parameters:
            return success_response()
        return success_response(feature_setting.parameters['content'])


class UserCampaignEligibilityView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        transaction_method_code = int(request.GET.get('transaction_type_code', 0))

        is_zero_interest_eligible, result = is_customer_can_do_zero_interest(
            customer, transaction_method_code
        )

        if not is_zero_interest_eligible:
            result = get_julo_care_configuration(customer, transaction_method_code)

        return success_response(data=result)


class JuloCareCallbackView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        if not update_loan_julo_care(JuloCareCallbackSerializer, request.data):
            return general_error_response("Failed")
        return success_response(data="Success")


class ProductListView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer

        data = {
            "product": [],
        }

        application = determine_application_for_credit_info(customer)
        account = application.account if application else None
        is_proven = False
        lock_colour, account_limit = None, None

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

        # temporary, append qris method last for valid customer
        transaction_methods = append_qris_method(account, list(transaction_methods))

        transaction_method_results = {}  # for reusing the values later
        highlight_setting = MobileFeatureSetting.objects.get_or_none(
            is_active=True, feature_name=FeatureNameConstPayment.TRANSACTION_METHOD_HIGHLIGHT
        )
        product_lock_in_app_bottom_sheet = FeatureSetting.objects.get_or_none(
            is_active=True, feature_name=FeatureNameConst.PRODUCT_LOCK_IN_APP_BOTTOM_SHEET
        )
        if application:
            is_proven = get_julo_one_is_proven(account) or julo_starter_proven_bypass(application)
            _, lock_colour = get_dpd_and_lock_colour_by_account(account)

        if account:
            account_limit = account.accountlimit_set.last()

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
                "campaign": "",
            }
        )

        return success_response(data)


class ActivePlatformRuleCheckView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        transaction_type_code = request.GET.get('transaction_type_code', 0)
        is_success, data = get_active_platform_rule_response_data(
            request.user.customer.account, int(transaction_type_code)
        )
        if is_success:
            return success_response(data=data)

        return general_error_response("Terdapat kesalahan silahkan hubungi customer service JULO.")


class TransactionResultView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, loan_xid):
        """
        Get transaction result Available for J1, Turbo, Julover
        From loan_xid
        """
        loan = get_loan_from_xid(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan not found")

        is_user_allowed = request.user.customer.id == loan.customer_id
        if not is_user_allowed:
            return forbidden_error_response("User not allowed")

        is_product_allowed = loan.is_j1_or_jturbo_loan() or loan.is_julover_loan()
        if not is_product_allowed:
            return forbidden_error_response("Product not allowed")

        service = TransactionResultAPIService(loan=loan)
        response_data = service.construct_response_data()

        return success_response(data=response_data)


class CrossSellingProductsView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        """
        Get Cross Selling Products based on available limit of customer
        """
        transaction_type_code = request.GET.get('transaction_type_code', 0)
        is_success, data = get_cross_selling_recommendations(
            request.user.customer.account, int(transaction_type_code)
        )
        if is_success:
            return success_response(data=data)

        return general_error_response("Terdapat kesalahan silahkan hubungi customer service JULO.")


class AvailableLimitInfoView(StandardizedExceptionHandlerMixin, APIView):
    class InputSerializer(serializers.Serializer):
        # optional case
        transaction_type_code = serializers.IntegerField(required=False)

    def post(self, request, account_id):
        """
        Show Available Limit Info, with FS setting

        If get_cashloan_available_limit param is "true",
        recalculate the mercury cashloan limit
        """
        get_cashloan_available_limit = request.query_params.get(
            'get_cashloan_available_limit', None
        )
        get_cashloan_available_limit = True if get_cashloan_available_limit == "true" else False

        # validation
        serializer = self.InputSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        # service
        service = AvailableLimitInfoAPIService(
            get_cashloan_available_limit=get_cashloan_available_limit,
            account_id=int(account_id),
            input=validated_data,
        )
        response_data = service.construct_response_data()

        logger.info(
            {
                "action": "juloserver.loan.views.views_api_v1.AvailableLimitInfoView",
                "response_data": response_data,
                "account_id": account_id,
            }
        )

        return success_response(data=response_data)


class LockedProductPageView(StandardizedExceptionHandlerMixin, APIView):
    class GetQueryParamsSerializer(serializers.Serializer):
        page = serializers.CharField(required=False)

        def validate_page(self, value):
            if value not in LockedProductPageConst.all_page_names():
                raise ValidationError("Invalid page")

            return value

    def get(self, request):
        input_serializer = self.GetQueryParamsSerializer(data=request.query_params)
        input_serializer.is_valid(raise_exception=True)

        service = LockedProductPageService(
            customer=request.user.customer,
            input_data=input_serializer.validated_data,
        )

        response_data = service.construct_response_data()

        return success_response(data=response_data)

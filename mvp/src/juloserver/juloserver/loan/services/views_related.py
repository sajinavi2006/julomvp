from datetime import datetime
import os
import re
import json
from typing import Dict, Any, List, Optional, Tuple
import redis
import logging
from babel.dates import format_date
from juloserver.digisign.services.common_services import (
    get_total_digisign_fee,
)
from juloserver.ecommerce.juloshop_service import get_juloshop_loan_product_details
from juloserver.julo_financing.constants import (
    JFINACNING_FE_PRODUCT_CATEGORY,
    JFINANCING_VENDOR_NAME,
)
from juloserver.julocore.python2.utils import py2round
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from PIL import Image as Imagealias
from django.db.models import Sum, Q

from juloserver.loan.exceptions import TransactionResultException
from juloserver.loan.services.julo_care_related import get_julo_care_configuration
from juloserver.loan.services.loan_formula import LoanAmountFormulaService
from juloserver.loan.services.loan_tax import get_tax_rate
from juloserver.loan.services.transaction_model_related import MercuryCustomerService

from ..serializers import LoanDetailsSerializer
from ..serializers import VoiceRecordSerializer
from ..serializers import ManualSignatureSerializer
from ..serializers import BankAccountSerializer
from juloserver.healthcare.constants import HealthcareConst
from juloserver.rentee.services import get_rentee_loan_detail
from juloserver.qris.models import QrisPartnerTransaction
from .delayed_disbursement_related import ReturnDelayDisbursementTransactionResult
from .feature_settings import (
    AnaTransactionModelSetting,
    AppendQrisTransactionMethodSetting,
    AvailableLimitInfoSetting,
    LockedProductPageSetting,
    ThorTenorInterventionModelSetting,
    CrossSellingConfigMethodSetting,
)
from juloserver.application_flow.models import (
    DigitalSignatureThreshold,
    VoiceRecordingThreshold,
)
from juloserver.julo.models import (
    Application,
    Customer,
    Document,
    FeatureSetting,
    Image,
    Loan,
    MobileFeatureSetting,
    PaymentMethod,
    SepulsaTransaction,
    VoiceRecord,
    FDCActiveLoanChecking,
    CreditMatrix,
    CreditMatrixRepeatLoan,
)

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.exceptions import JuloException
from juloserver.account.models import Account, AccountProperty, AccountLimit
from juloserver.julo.exceptions import ApplicationNotFound
from juloserver.account.utils import get_first_12_digits
from juloserver.disbursement.models import Disbursement
from juloserver.education.constants import EducationConst
from ...julo.product_lines import ProductLineCodes
from ...julo.product_lines import ProductLineNotFound
from juloserver.julo.constants import MobileFeatureNameConst, WorkflowConst, FeatureNameConst
from juloserver.account_payment.models import AccountPayment
from juloserver.account.constants import ImageSource
from juloserver.customer_module.services.bank_account_related import is_ecommerce_bank_account
from juloserver.julo.services import get_sphp_template
from juloserver.julo.utils import (
    construct_remote_filepath,
    display_rupiah,
    display_rupiah_no_space,
    upload_file_to_oss,
    display_percent_from_float_type,
)
from juloserver.julovers.models import Julovers

from juloserver.loan.services.loan_related import (
    generate_new_payments,
    is_customer_can_do_zero_interest,
    is_qris_1_blocked,
    readjusted_loan_amount_by_max_fee_rule,
    calculate_installment_amount,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    is_eligible_other_active_platforms,
    get_ecommerce_limit_transaction,
    get_first_payment_date_by_application,
    get_loan_duration,
    compute_first_payment_installment_julo_one,
    get_loan_amount_by_transaction_type,
    compute_payment_installment_julo_one,
)
from juloserver.partnership.constants import ErrorMessageConst, SPHPOutputType
from juloserver.account.services.account_related import get_account_property_by_account

from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
    TransactionMethodCode,
)
from juloserver.loan.services.adjusted_loan_matrix import validate_max_fee_rule
from juloserver.digisign.constants import DocumentType, SigningStatus
from juloserver.digisign.models import DigisignDocument
from juloserver.loan.constants import (
    CampaignConst,
    LoanFeatureNameConst,
)
from juloserver.payment_point.models import (
    SepulsaPaymentPointInquireTracking,
    TransactionMethod,
)
from juloserver.julo.models import Payment
from juloserver.loan.constants import (
    LoanJuloOneConstant,
    PHONE_REGEX_PATTERN,
    DEFAULT_OTHER_PLATFORM_MONTHLY_INTEREST_RATE,
    DEFAULT_LIST_SAVING_INFORMATION_DURATION,
    TransactionResultConst,
)
from juloserver.followthemoney.models import LoanAgreementTemplate
from juloserver.followthemoney.constants import LoanAgreementType
from django.template import Context, Template
from juloserver.account.constants import TransactionType
from juloserver.loan.models import (
    AdditionalLoanInformation,
    LoanDelayDisbursementFee,
    TenorBasedPricing,
    LoanTransactionDetail,
)
from juloserver.healthcare.models import HealthcareUser
from django.contrib.contenttypes.models import ContentType
from juloserver.loan.services.dbr_ratio import LoanDbrSetting
from juloserver.julocore.redis_completion_py3 import RedisEnginePy3
from juloserver.payment_point.services.ewallet_related import populate_xfers_or_ayc_ewallet_details
from juloserver.julo.services2.feature_setting import FeatureSettingHelper


logger = logging.getLogger(__name__)


def get_loan_details(loan):
    from juloserver.balance_consolidation.services import \
        get_balance_consolidation_verification_by_loan

    serializer = LoanDetailsSerializer(loan)
    data = serializer.data
    serializer_bank = BankAccountSerializer(loan.bank_account_destination)
    data['bank'] = serializer_bank.data if loan.bank_account_destination else None
    data['topup_pln'] = None
    data['topup_phone'] = None
    data['topup_pdam'] = None
    data['train_ticket'] = None
    data['student_tuition'] = None
    data['category_product_name'] = None
    data['fintech_name'] = None
    (
        data['crossed_interest_rate_monthly'],
        data['crossed_installment_amount'],
        data['crossed_loan_disbursement_amount'],
    ) = get_crossed_interest_and_installment_amount(loan)

    transaction_method = loan.transaction_method
    if transaction_method:
        data['category_product_name'] = transaction_method.fe_display_name

    sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
    if sepulsa_transaction:
        product = sepulsa_transaction.product
        if product.type == SepulsaProductType.MOBILE:
            category = product.category.replace('_', ' ').title() if product.category else None
            price_amount = sepulsa_transaction.customer_price_regular
            data['topup_phone'] = dict(
                phone_number=sepulsa_transaction.phone_number,
                product_name=product.product_name,
                category=category,
                price=price_amount,
                type=product.category,
                serial_number=sepulsa_transaction.serial_number
            )
            if product.category == SepulsaProductCategory.POSTPAID[0]:
                data['topup_phone']['price'] = sepulsa_transaction.customer_amount
                data['topup_phone']['category'] = 'Kartu Pascabayar'
                data['topup_phone']['customer_name'] = sepulsa_transaction.account_name
        elif product.type == SepulsaProductType.ELECTRICITY:
            is_prepaid_electricity = product.category == SepulsaProductCategory.ELECTRICITY_PREPAID
            category = 'Token PLN' if is_prepaid_electricity else 'Tagihan PLN'
            price_amount = sepulsa_transaction.customer_price_regular
            if not is_prepaid_electricity:
                price_amount = sepulsa_transaction.customer_amount
            data['topup_pln'] = dict(
                product_name=product.product_name,
                customer_number=sepulsa_transaction.customer_number,
                customer_name=sepulsa_transaction.account_name,
                price=price_amount,
                category=category,
                type=product.category,
                serial_number=sepulsa_transaction.serial_number
            )
            if is_prepaid_electricity:
                data['topup_pln']['token'] = sepulsa_transaction.transaction_token
        elif product.type == SepulsaProductType.EWALLET:
            data['topup_e_wallet'] = dict(
                product_category="Dompet Digital",
                product_kind=product.product_name,
                price=sepulsa_transaction.customer_price_regular,
                phone_number=sepulsa_transaction.phone_number,
                type=product.category,
                serial_number=sepulsa_transaction.serial_number,
                product_logo=product.ewallet_logo,
            )
        elif product.type == SepulsaProductType.BPJS:
            data['topup_bpjs'] = dict(
                product_category="BPJS Kesehatan",
                product_kind="Tagihan {} bulan".format(sepulsa_transaction.paid_period),
                price=sepulsa_transaction.customer_amount,
                bpjs_number=sepulsa_transaction.customer_number,
                customer_name=sepulsa_transaction.account_name,
                type=product.category,
                serial_number=sepulsa_transaction.serial_number
            )
        elif product.type == SepulsaProductType.PDAM:
            data['topup_pdam'] = dict(
                product_category="Tagihan Air",
                product_kind=sepulsa_transaction.product.product_name,
                nominal=loan.loan_amount,
                product_name=product.product_name,
                customer_number=sepulsa_transaction.customer_number,
                customer_name=sepulsa_transaction.account_name,
                serial_number=sepulsa_transaction.serial_number
            )
        elif product.type == SepulsaProductType.TRAIN_TICKET:
            train_route = "-"
            train_transaction = sepulsa_transaction.traintransaction_set.last()
            if train_transaction:
                depart_station = train_transaction.depart_station
                destination_station = train_transaction.destination_station
                train_route = "{} ({}) - {} ({})".format(
                    depart_station.name,
                    depart_station.code,
                    destination_station.name,
                    destination_station.code,
                )

            data['train_ticket'] = dict(
                product_category="Tiket Kereta",
                product_kind=train_route,
                nominal=loan.loan_amount,
                product_name=product.product_name,
                customer_number=sepulsa_transaction.customer_number,
                customer_name=sepulsa_transaction.account_name,
                serial_number=sepulsa_transaction.serial_number,
                train_route=train_route,
            )
    elif is_ecommerce_bank_account(loan.bank_account_destination):
        data['ecommerce'] = dict(
            product_category="E-commerce",
            product_kind=loan.bank_account_destination.description,
            price=loan.loan_disbursement_amount,
            customer_name=loan.bank_account_destination.name_bank_validation.name_in_bank,
            va_number=loan.bank_account_destination.account_number
        )
    elif loan.is_qris_product:
        data['qris'] = dict(
            product_category="Scan QR",
            price=loan.qris_transaction.amount,
            merchant_name=loan.qris_transaction.merchant_name,
            provision_amount=loan.provision_fee()
        )
    elif loan.is_qris_1_product:
        # use qris keyword to save FE development
        qris_transaction = QrisPartnerTransaction.objects.get(loan_id=loan.id)
        loan_transaction_detail = LoanTransactionDetail.objects.filter(loan_id=loan.id).first()
        detail = loan_transaction_detail.detail if loan_transaction_detail else {}
        partner_transaction_request = (qris_transaction.partner_transaction_request or {})
        transaction_detail = partner_transaction_request.get('transactionDetail', {})
        callback_payload = (qris_transaction.partner_callback_payload or {}).get('data', {})
        data['qris'] = dict(
            product_category="QRIS",
            type="Pembayaran QRIS",
            price=qris_transaction.total_amount,
            merchant_name=qris_transaction.merchant_name,
            provision_amount=None,  # Android not using this field
            product_name=partner_transaction_request.get('productName', '-'),
            terminal_id=transaction_detail.get('terminalId', '-'),
            merchant_city=transaction_detail.get('merchantCity', '-'),
            customer_pan=callback_payload.get('customerPan', '-'),
            merchant_pan=callback_payload.get('merchantPan', '-'),
            admin_fee=detail.get('admin_fee'),
            tax_fee=detail.get('tax_fee'),
            monthly_interest_rate=detail.get('monthly_interest_rate'),
        )
    elif loan.is_jfinancing_product:
        # use qris keyword to save FE development
        data['qris'] = dict(
            product_category=JFINACNING_FE_PRODUCT_CATEGORY,
            price=loan.j_financing_verification.j_financing_checkout.price,
            merchant_name=JFINANCING_VENDOR_NAME,
            provision_amount=None,
        )
    elif loan.is_rentee_loan():
        data['rentee'] = dict(
            product_category="Rentee",
            price=loan.loan_disbursement_amount,
            name_device=loan.loan_purpose,
        )
    elif loan.is_credit_card_product:
        credit_card_transaction = loan.creditcardtransaction_set.last()
        data['julo_card'] = {
            'product_category': "JULO Card",
            'price': credit_card_transaction.amount,
            'merchant_name': credit_card_transaction.terminal_location,
            'provision_amount': loan.provision_fee()
        }
    elif loan.is_education_product:
        education_transaction = loan.loanstudentregister_set.last()
        student = education_transaction.student_register
        bank_account_destination = student.bank_account_destination
        bank = bank_account_destination.bank
        school = student.school

        bank_reference_number = None
        invoice_pdf_link = None
        if loan.status >= LoanStatusCodes.CURRENT:
            disbursement = Disbursement.objects.get_or_none(pk=loan.disbursement_id)
            if disbursement and disbursement.reference_id:
                bank_reference_number = get_first_12_digits(string=disbursement.reference_id)

            document = Document.objects.filter(
                document_source=loan.id,
                document_type=EducationConst.DOCUMENT_TYPE,
            ).last()
            if document:
                invoice_pdf_link = document.document_url

        data['student_tuition'] = {
            'nominal': loan.loan_disbursement_amount,
            'name': student.student_fullname,
            'note': student.note,
            'school': {
                'id': school.id,
                'name': school.name,
            },
            'bank': {
                'name': bank.bank_name_frontend,
                'logo': bank.bank_logo,
                'account_name': bank_account_destination.get_name_from_bank_validation,
                'account_number': bank_account_destination.account_number,
                'reference_number': bank_reference_number,
            },
            'invoice_pdf_link': invoice_pdf_link,
        }
    elif loan.is_healthcare_product:
        bank_reference_number = None
        invoice_pdf_link = None
        if loan.status >= LoanStatusCodes.CURRENT:
            disbursement = Disbursement.objects.get_or_none(pk=loan.disbursement_id)
            if disbursement and disbursement.reference_id:
                bank_reference_number = get_first_12_digits(string=disbursement.reference_id)

            document = Document.objects.filter(
                document_source=loan.id,
                document_type=HealthcareConst.DOCUMENT_TYPE_INVOICE,
            ).last()
            if document:
                invoice_pdf_link = document.document_url

        healthcare_user = (
            HealthcareUser.objects.select_related('healthcare_platform')
            .filter(loans__loan_id=loan.pk)
            .first()
        )
        data['healthcare_user'] = dict(
            healthcare_platform_name=healthcare_user.healthcare_platform.name,
            healthcare_user_fullname=healthcare_user.fullname,
            bank_reference_number=bank_reference_number,
            invoice_pdf_link=invoice_pdf_link,
        )

    # having SepulsaTransaction checking above else go here we only have Xfers or Ayoconnect
    elif loan.is_ewallet_product:
        populate_xfers_or_ayc_ewallet_details(data, loan)

    balance_consolidation_verification = \
        get_balance_consolidation_verification_by_loan(loan.id)
    if balance_consolidation_verification is not None:
        balance_consolidation = balance_consolidation_verification.balance_consolidation
        data['fintech_name'] = balance_consolidation.fintech.name

    return data


def get_voice_record(loan):
    voice_record = VoiceRecord.objects.filter(loan=loan).last()
    serializer = VoiceRecordSerializer(voice_record)
    voice_data = dict()
    voice_data['data'] = serializer.data
    account_property = AccountProperty.objects.filter(account=loan.account).last()
    if not account_property:
        voice_property = True
    else:
        voice_property = account_property.voice_recording
    if voice_property:
        voice_property = get_voice_bypass_feature(loan)
    voice_data['enable'] = voice_property
    return voice_data


def get_manual_signature(loan):
    manual_signature = Image.objects.filter(image_source=loan.id,
                                            image_type='signature').last()
    if not manual_signature:
        return
    else:
        serializer = ManualSignatureSerializer(manual_signature)
        return serializer.data


def get_manual_signature_url_grab(loan):
    manual_signature = Image.objects.filter(
        image_source=loan.id, image_type='signature', image_status=Image.CURRENT
    ).last()
    if not manual_signature:
        return None
    return manual_signature.image_url


def get_sphp_template_privy(loan_id, type="document"):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None
    template = None
    if loan.account:
        if loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
            template = get_sphp_template_grab(loan_id, type)
        elif loan.is_mf_loan():
            from juloserver.merchant_financing.services import get_sphp_loan_merchant_financing
            template = get_sphp_loan_merchant_financing(loan_id)
        elif loan.is_rentee_loan():
            template = get_rentee_sphp_template(loan_id, type)
        else:
            template = get_sphp_template_julo_one(loan_id, type)
    else:
        template = get_sphp_template(loan_id, type)
    return template


def get_sphp_template_julo_one(loan_id, type="document", is_simulation=False, loan_duration=None,
                               is_new_digisign=False):
    from juloserver.loan.services.sphp import get_loan_type_sphp_content
    from juloserver.promo.services import (
        get_interest_discount_promo_code_benifit_applied, get_interest_discount_on_promocode)

    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        return None
    loan_type = get_loan_type_sphp_content(loan)
    lender = loan.lender
    pks_number = '1.JTF.201707'
    if lender and lender.pks_number:
        pks_number = lender.pks_number
    sphp_date = loan.sphp_sent_ts
    application = loan.get_application
    context = {
        'loan': loan,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'agreement_letter_number': pks_number,
        'loan_type': loan_type
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number).first()
        if payment_method:
            context['julo_bank_code'] = payment_method.bank_code
    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    if is_simulation and loan_duration:
        loan_amount = readjusted_loan_amount_by_max_fee_rule(loan, loan_duration)
        payments = generate_new_payments(loan_duration, loan)
        context['loan_amount'] = display_rupiah(loan_amount)
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        # Interest dicount promo updation to sphp
        promo_code_benifit = get_interest_discount_promo_code_benifit_applied(payment.loan)
        if promo_code_benifit:
            discount_duration = promo_code_benifit.get_value('duration', to_type=int)
            if payment.payment_number <= discount_duration:
                interest_discount = get_interest_discount_on_promocode(
                    payment.installment_interest, promo_code_benifit)
                payment.due_amount -= interest_discount
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)

    context['payments'] = payments
    context['max_total_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
    context['provision_fee_amount'] = display_rupiah(loan.provision_fee())
    context['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())
    signature = get_manual_signature(loan)
    if signature and not is_new_digisign:
        context['signature'] = signature['thumbnail_url_api']
    else:
        context['signature'] = ''

    if type == "document":
        template = render_to_string('julo_one_sphp_document.html', context=context)
    elif type == "android":
        if application.product_line_id == ProductLineCodes.JULOVER:
            julover = Julovers.objects.get(application_id=application.id)
            context['real_nik'] = julover.real_nik
            julover_template = LoanAgreementTemplate.objects.get_or_none(
                is_active=True, agreement_type=LoanAgreementType.JULOVERS_SPHP
            )
            if julover_template:
                template = Template(julover_template.body).render(Context(context))
            else:
                template = render_to_string(
                    '../../julovers/templates/julovers/julovers_sphp.html', context=context
                )
        else:
            template = render_to_string('julo_one_sphp.html', context=context)
    elif type == SPHPOutputType.WEBVIEW:
        template = render_to_string('julo_one_sphp_webview.html', context=context)

    return template


def get_sphp_template_grab(loan_id, type="document"):
    loan = Loan.objects.get_or_none(pk=loan_id)
    display_lender_signature = True
    if not loan:
        return None
    template = None
    sphp_date = loan.sphp_sent_ts
    payments = loan.payment_set.order_by('due_date')
    if not payments:
        return None
    start_date = payments.first().due_date
    end_date = payments.last().due_date
    today_date = timezone.localtime(timezone.now()).date()
    application = loan.account.application_set.last()
    provision_fee_amount = loan.provision_fee() + loan.product.admin_fee
    interest_rate = loan.product.interest_rate * 100
    maximum_late_fee_amount = loan.loan_amount if loan.late_fee_amount else 0
    due_amount = Payment.objects.filter(
        payment_status__status_code__in={
            PaymentStatusCodes.PAYMENT_NOT_DUE,
            PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
            PaymentStatusCodes.PAYMENT_DUE_TODAY,
            PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
            PaymentStatusCodes.PAYMENT_1DPD,
            PaymentStatusCodes.PAYMENT_4DPD,
            PaymentStatusCodes.PAYMENT_5DPD,
            PaymentStatusCodes.PAYMENT_8DPD,
            PaymentStatusCodes.PAYMENT_30DPD,
            PaymentStatusCodes.PAYMENT_60DPD,
            PaymentStatusCodes.PAYMENT_90DPD,
            PaymentStatusCodes.PAYMENT_120DPD,
            PaymentStatusCodes.PAYMENT_150DPD,
            PaymentStatusCodes.PAYMENT_180DPD
        },
        loan=loan
    ).aggregate(Sum('due_amount'))['due_amount__sum']
    total_due_amount = due_amount if due_amount else 0
    disbursement_amount = loan.loan_amount - provision_fee_amount
    context = {
        'loan': loan, 'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'start_date': format_date(start_date, 'dd-MM-yyyy', locale='id_ID'),
        'end_date': format_date(end_date, 'dd-MM-yyyy', locale='id_ID'),
        'total_number_of_payments': payments.count(),
        'max_total_late_fee_amount': display_rupiah(loan.late_fee_amount),
        'provision_fee_amount': display_rupiah(provision_fee_amount),
        'interest_rate': '{}%'.format(interest_rate),
        'installment_amount': display_rupiah(loan.installment_amount),
        'maximum_late_fee_amount': display_rupiah(maximum_late_fee_amount),
        'total_due_amount': display_rupiah(total_due_amount),
        'loan_duration': loan.loan_duration,
        'disbursement_amount': display_rupiah(disbursement_amount),
        'monthly_late_fee': 0,
        'max_monthly_late_fee': 0,
        'lender_director': "Dion Soetadi",
        'lender_company_name': "PT Visionet Internasional",
        'lender_license_number': "9120306561159",
        'lender_full_address': "South Quarter, Tower B, Lantai 20, "
                               "Unit A, B, C & D, Jl. R.A. Kartini Kav. 8, "
                               "Jakarta Selatan 12430, Daerah Khusus Ibukota Jakarta 12920",
        'display_lender_signature': display_lender_signature,
        'e_sign_amount': 0,
    }
    signature_url = get_manual_signature_url_grab(loan)
    if signature_url:
        context['signature'] = signature_url
    else:
        context['signature'] = ''
        context['lender_director'] = ''
        context['lender_company_name'] = ''
        context['lender_license_number'] = ''
        context['lender_full_address'] = ''
        context['display_lender_signature'] = False

    if loan.loan_status_id in {
        LoanStatusCodes.LENDER_REJECT,
        LoanStatusCodes.GRAB_AUTH_FAILED
    }:
        context['lender_director'] = ''
        context['lender_company_name'] = ''
        context['lender_license_number'] = ''
        context['lender_full_address'] = ''
        context['display_lender_signature'] = False

    context['today_date_bahasa'] = format_date(sphp_date, 'd MMMM yyyy', locale='id_ID')
    signature_date = loan.sphp_accepted_ts if loan.sphp_accepted_ts else today_date
    context['signature_date'] = format_date(signature_date, 'dd-MM-yyyy', locale='id_ID')

    if type == "document":
        template = render_to_string('grab_skrtp_template.html', context=context)
    elif type == "android":
        template = render_to_string('grab_sphp.html', context=context)
    elif type == "email":
        template = render_to_string('grab_sphp_email.html', context=context)
    return template


def get_rentee_sphp_template(loan_id, type="document"):
    from juloserver.loan.services.sphp import get_loan_type_sphp_content

    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        return None
    loan_type = get_loan_type_sphp_content(loan)
    lender = loan.lender
    pks_number = '1.JTF.201707'
    if lender and lender.pks_number:
        pks_number = lender.pks_number
    sphp_date = loan.sphp_sent_ts
    application = loan.account.application_set.last()
    context = {
        'loan': loan,
        'application': application,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'agreement_letter_number': pks_number,
        'loan_type': loan_type
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number).first()
        if payment_method:
            context['julo_bank_code'] = payment_method.bank_code
    # exclude 13th payment from sphp
    payments = list(loan.payment_set.order_by('id'))
    residual_payments = payments.pop()
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)

    deposit_payment = loan.paymentdeposit

    loan_detail = get_rentee_loan_detail(deposit_payment.rentee_device_id)

    context['device_name'] = deposit_payment.rentee_device.device_name
    context['device_price'] = deposit_payment.rentee_device.price
    context['deposit_amount'] = deposit_payment.deposit_amount
    context['protection_fee'] = deposit_payment.protection_fee
    context['admin_fee'] = deposit_payment.admin_fee
    context['residual_amount'] = loan_detail['residual_loan_amount']
    context['payment_13_due_date'] = format_date(residual_payments.due_date,
                                                 'd MMM yy', locale='id_ID')

    context['payments'] = payments
    context['max_total_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
    context['provision_fee_amount'] = loan_detail['residual_loan_amount']
    context['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())

    if type == "document":
        template = render_to_string('rentee_julo_one_sphp_document.html', context=context)
    if type == "android":
        template = render_to_string('rentee_julo_one_sphp.html', context=context)

    return template


def process_image_upload_julo_one(image, thumbnail=True, source_image_id=None):
    if 3000000000 < int(image.image_source) < 3999999999:
        loan = Loan.objects.get_or_none(pk=image.image_source)
        if not loan:
            raise JuloException("Loan id=%s not found" % image.image_source)
    elif source_image_id == ImageSource.ACCOUNT_PAYMENT:
        account_payment = AccountPayment.objects.get_or_none(pk=int(image.image_source))
        if not account_payment:
            raise JuloException("Account payment id=%s not found" % image.image_source)
        payment = account_payment.payment_set.last()
        loan = payment.loan
    else:
        raise JuloException('Unrecognized image_source=%s' % image.image_source)

    # upload image to s3 and save s3url to field
    cust_id = loan.customer.id
    image_path = image.image.path

    image_remote_filepath = construct_remote_filepath(cust_id, image,
                                                      source_image_id=source_image_id)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image.image.path, image_remote_filepath)
    image.update_safely(url=image_remote_filepath)

    logger.info({
        'status': 'successfull upload image to s3',
        'image_remote_filepath': image_remote_filepath,
        'loan_id': image.image_source,
        'image_type': image.image_type
    })

    if image.image_ext != '.pdf' and thumbnail:

        # create thumbnail
        im = Imagealias.open(image.image.path)
        im = im.convert('RGB')
        size = (150, 150)
        im.thumbnail(size, Imagealias.ANTIALIAS)
        image_thumbnail_path = image.thumbnail_path
        im.save(image_thumbnail_path)

        # upload thumbnail to s3
        thumbnail_dest_name = construct_remote_filepath(cust_id, image, suffix='thumbnail',
                                                        source_image_id=source_image_id)
        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET, image_thumbnail_path, thumbnail_dest_name)
        image.update_safely(thumbnail_url=thumbnail_dest_name)

        logger.info({
            'status': 'successfull upload thumbnail to s3',
            'thumbnail_dest_name': thumbnail_dest_name,
            'loan_id': image.image_source,
            'image_type': image.image_type
        })

        # delete thumbnail from local disk
        if os.path.isfile(image_thumbnail_path):
            logger.info({
                'action': 'deleting_thumbnail_local_file',
                'image_thumbnail_path': image_thumbnail_path,
                'loan_id': image.image_source,
                'image_type': image.image_type
            })
            os.remove(image_thumbnail_path)

    # delete image
    if os.path.isfile(image_path):
        logger.info({
            'action': 'deleting_local_file',
            'image_path': image_path,
            'loan_id': image.image_source,
            'image_type': image.image_type
        })
        image.image.delete()

    if image.image_status != Image.CURRENT:
        return

    # mark all other images with same type as 'deleted'
    images = list(
        Image.objects
        .exclude(id=image.id)
        .exclude(image_status=Image.DELETED)
        .filter(image_source=image.image_source,
                image_type=image.image_type)
    )

    for img in images:
        logger.info({
            'action': 'marking_deleted',
            'image': img.id
        })
        img.update_safely(image_status=Image.DELETED)


def validate_loan_concurrency(account):
    if not account:
        return False, None

    account_property = get_account_property_by_account(account)
    if not account_property:
        return False, None

    concurrency = account_property.concurrency
    _filter = Q(
        loan_status__in=(
            LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.SPHP_EXPIRED,
            LoanStatusCodes.FUND_DISBURSAL_FAILED,
            LoanStatusCodes.PAID_OFF,
        )
    ) | Q(transaction_method_id=TransactionMethodCode.JFINANCING.code)
    loans = account.loan_set.exclude(_filter)
    if not loans:
        return concurrency, None

    concurrency_message = dict(
        title="Halo",
        content=ErrorMessageConst.CONCURRENCY_MESSAGE_CONTENT
    )
    mobile_feature_setting = MobileFeatureSetting.objects.filter(
        feature_name="concurrency_message", is_active=True
    ).last()
    if mobile_feature_setting:
        concurrency_message = mobile_feature_setting.parameters

    loan = loans.last()

    if not account_property.concurrency or (
        account_property.concurrency
        and loan.status == LoanStatusCodes.INACTIVE
        and loan.transaction_method_id != TransactionMethodCode.CREDIT_CARD.code
    ):
        return concurrency, concurrency_message

    return concurrency, None


def get_voice_record_script(loan):
    application = loan.get_application
    if not application:
        raise ApplicationNotFound('Application not Found for Loan ID: {}'.format(loan.id))
    return get_voice_record_script_loan_default(application, loan)


def get_voice_record_script_loan_default(application, loan):
    script = (
        "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
        " %(DOB)s mengajukan pinjaman melalui PT. JULO TEKNOLOGI FINANSIAL"
        " dan telah disetujui sebesar yang tertera pada %(AGREEMENT_NAME)s "
        "%(LOAN_DURATION)s. Saya berjanji untuk melunasi "
        "pinjaman sesuai dengan %(AGREEMENT_NAME)s "
        "yang telah saya tanda tangani."
    )
    if application.product_line_code in ProductLineCodes.allow_for_agreement():
        loan_duration = "selama %s bulan" % loan.loan_duration
    else:
        raise ProductLineNotFound("Not Julo One Product line for application id {}: {}".format(
            application.id,
            application.product_line))
    master_agreement = Document.objects.filter(
        document_type="master_agreement", document_source=application.id
    ).last()
    agreement_name = "Surat Perjanjian Hutang Piutang"
    if master_agreement:
        agreement_name = "Surat Konfirmasi Rincian Transaksi Pendanaan"
    template_data = {
        "TODAY_DATE": format_date(timezone.now().date(), 'd MMMM yyyy', locale='id_ID'),
        "FULL_NAME": application.fullname,
        "DOB": format_date(application.dob, 'd MMMM yyyy', locale='id_ID'),
        "LOAN_AMOUNT": display_rupiah(loan.loan_amount),
        "LOAN_DURATION": loan_duration,
        "AGREEMENT_NAME": agreement_name,
    }
    log_dict = {'loan_id': loan.id}
    log_dict.update(template_data)
    logger.info(log_dict)
    return script % template_data


def get_privy_bypass_feature(loan):
    if loan.transaction_method:
        threshold_setting = DigitalSignatureThreshold.objects.filter(
            transaction_method=loan.transaction_method).last()
    else:
        threshold_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DIGITAL_SIGNATURE_THRESHOLD,
            is_active=True).last()
    if not threshold_setting:
        return False
    threshold_amount = threshold_setting.parameters['digital_signature_loan_amount_threshold']

    if loan.loan_amount >= int(threshold_amount):
        return False
    else:
        return True


def get_voice_bypass_feature(loan):
    if loan.transaction_method:
        threshold_setting = VoiceRecordingThreshold.objects.filter(
            transaction_method=loan.transaction_method).last()
    else:
        threshold_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.VOICE_RECORDING_THRESHOLD,
            is_active=True).last()
    if not threshold_setting:
        return True
    threshold_amount = threshold_setting.parameters['voice_recording_loan_amount_threshold']

    if loan.loan_amount >= int(threshold_amount):
        return True
    else:
        return False


def validate_mobile_number(mobile_number):
    if not re.match(PHONE_REGEX_PATTERN, mobile_number):
        return False
    feature_setting = FeatureSetting.objects.filter(
        feature_name=LoanJuloOneConstant.PHONE_NUMBER_BLACKLIST,
        is_active=True).last()
    if feature_setting:
        params = feature_setting.parameters
        blacklist_phone_number = params['blacklist_phone_numnber']
        if mobile_number in blacklist_phone_number:
            return False
    return True


def update_sepulsa_transaction_for_last_sepulsa_payment_point_inquire_tracking(
    account, transaction_method_id, sepulsa_product, sepulsa_transaction
):
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        is_active=True,
    ).exists():
        return

    # currently, FE guys does not send sepulsa_payment_point_inquire_tracking_id
    # so, we need to get it from the last record
    if transaction_method_id in TransactionMethodCode.inquire_sepulsa_need_validate():
        if (
            transaction_method_id == TransactionMethodCode.LISTRIK_PLN.code
            and sepulsa_product.category == SepulsaProductCategory.ELECTRICITY_PREPAID
        ):
            # skip electricity prepaid
            return

        last_tracking = SepulsaPaymentPointInquireTracking.objects.filter(
            account=account, transaction_method_id=transaction_method_id
        ).last()
        last_tracking.sepulsa_transaction = sepulsa_transaction
        last_tracking.save()


def get_other_platform_monthly_interest_rate():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SAVING_INFORMATION_CONFIGURATION,
        is_active=True,
    ).last()
    if feature_setting:
        return feature_setting.parameters['other_platform_monthly_interest_rate']

    return DEFAULT_OTHER_PLATFORM_MONTHLY_INTEREST_RATE


def calculate_saving_information(
    regular_monthly_installment,
    loan_amount, duration, monthly_interest_rate, other_platform_monthly_interest_rate
):
    total_amount_need_to_paid = regular_monthly_installment * duration

    # monthly interest can be round down to previous thousand,
    # calculate total amount by monthly installment to omit the amount is rounded down in each month
    other_platform_regular_monthly_installment = calculate_installment_amount(
        loan_amount, duration, other_platform_monthly_interest_rate
    )
    other_platform_total_amount_need_to_paid = other_platform_regular_monthly_installment * duration

    return {
        'monthly_interest_rate': monthly_interest_rate,
        'total_amount_need_to_paid': total_amount_need_to_paid,
        'regular_monthly_installment': regular_monthly_installment,
        'other_platform_monthly_interest_rate': other_platform_monthly_interest_rate,
        'other_platform_total_amount_need_to_paid': other_platform_total_amount_need_to_paid,
        'other_platform_regular_monthly_installment': other_platform_regular_monthly_installment,
        'saving_amount_per_monthly_installment': (
            other_platform_regular_monthly_installment - regular_monthly_installment
        ),
        'saving_amount_per_transaction': (
            other_platform_total_amount_need_to_paid - total_amount_need_to_paid
        ),
    }


def get_list_object_saving_information_duration():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SAVING_INFORMATION_CONFIGURATION,
        is_active=True,
    ).last()
    if feature_setting:
        durations = feature_setting.parameters['list_saving_information_duration']
    else:
        durations = DEFAULT_LIST_SAVING_INFORMATION_DURATION

    return [{'duration': duration} for duration in durations]


def get_active_platform_rule_response_data(account, transaction_method_id=None):
    parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
    result = {
        "popup": {
            "bottom_sheet_name": "active_platform_rule",
            "is_active": False,
            "title": "",
            "banner": {
                "is_active": False,
                "url": "",
            },
            "content": "",
            "additional_information": {
                "is_active": False,
                "content": "",
                "clickable_text": "",
                "link": "",
            }
        },
        "warning_message": {
            "is_active": False,
            "title": "",
            "content": "",
            "clickable_text": "",
            "link": ""
        },
        "is_button_enable": True,
    }

    if not parameters or not account:
        return True, result

    try:
        popup = parameters.get('popup', None)
        if popup and popup.get('eligible'):
            result['popup'] = popup.get('eligible')

        application = account.get_active_application()
        if not application:
            raise ApplicationNotFound

        if is_apply_check_other_active_platforms_using_fdc(
            application.id, parameters, transaction_method_id=transaction_method_id
        ):
            if not is_eligible_other_active_platforms(
                application.id,
                parameters['fdc_data_outdated_threshold_days'],
                parameters['number_of_allowed_platforms'],
            ):
                result['popup'] = popup.get('ineligible')
                result['is_button_enable'] = False

                fdc_active_loan_checking = FDCActiveLoanChecking.objects.filter(
                    customer_id=account.customer_id
                ).values('number_of_other_platforms').last()
                warning_message = parameters.get('ineligible_alert_after_fdc_checking')
                if warning_message:
                    warning_message['content'] = warning_message['content'].format(
                        fdc_active_loan_checking.get('number_of_other_platforms', '3')
                    )
                    result['warning_message'] = warning_message
        is_success = True
    except ApplicationNotFound as e:
        is_success = False
        logger.error(
            {
                'action': 'loan.services.views_related.get_active_platform_rule_response_data',
                'error': "Application not found",
                'account_id': account.pk,
                "exception": str(e),
            }
        )

    except Exception as e:
        is_success = False
        logger.error(
            {
                'action': 'loan.services.views_related.get_active_platform_rule_response_data',
                'error': str(e),
                'exception': e,
                'account_id': account.pk,
            }
        )
        get_julo_sentry_client().captureException()

    return is_success, result


def compute_range_max_amount(
    transaction_type: str, available_limit: int, app: Application, provision_rate: float
):
    """
    For tarik, it's same as available limit
    For non-tarik, requires some adjustment based on final loan amount
    """

    # assume available limit is the final ammount
    highest_requested_amount = available_limit
    final_amount = available_limit

    method_code = TransactionMethodCode.code_from_name(transaction_type)

    # adjust based on method, method other than self (to own bank)
    if transaction_type not in [TransactionMethodCode.SELF.name]:

        # create formula object
        formula_service = LoanAmountFormulaService(
            method_code=method_code,
            requested_amount=available_limit,
            tax_rate=get_tax_rate(
                product_line_id=app.product_line_code,
                app_id=app.id,
            ),
            provision_rate=provision_rate,
            total_digisign_fee=get_total_digisign_fee(
                app=app,
                requested_loan_amount=highest_requested_amount,
                transaction_code=method_code,
            ),
            delay_disburesment_fee=0,
        )

        # reverse engineer to a new requested_amount
        # this is the max allowed amount user can make loan
        highest_requested_amount = formula_service.compute_requested_amount_from_final_amount(
            final_amount=final_amount,
        )

        logger.info(
            {
                "action": "juloserver.loan.services.views_related.compute_range_max_amount",
                "message": "calculate max range for non tarik dana",
                "customer_id": app.customer_id,
                "app_id": app.id,
                "formula_data": formula_service.__dict__,
            }
        )

    return highest_requested_amount


def get_range_loan_amount(
    account,
    origination_fee,
    monthly_interest_rate,
    transaction_type,
    self_bank_account,
    min_duration,
    max_duration,
):
    """
    will use same logic from loan duration,
    calculation available duration based on default loan amount (2 mil)
    calculating the adjusted amount, and then the monthly installment
    also calculating the first monthly installment
    and then will check if the default amount (2 million) is eligible for each duration.
    """

    logger.info(
        {
            "action": "juloserver.loan.services.views_related.get_range_loan_amount",
            "message": "before running get_range_loan_amount()",
            "account_id": account.id,
            "customer_id": account.customer_id,
            "origination_fee_from_CM_product": origination_fee,
            "monthly_interest_rate": monthly_interest_rate,
            "transaction_type": transaction_type,
            "self_bank_account": self_bank_account,
            "min_duration": min_duration,
            "max_duration": max_duration,
        }
    )

    account_limit = AccountLimit.objects.filter(account=account).last()
    available_limit = account_limit.available_limit

    # for now, used for mercury ana but could be general
    is_show_information_icon = False

    # mercury service (for ana transaction model) to compute new available limit for user
    original_available_limit = available_limit
    mercury_service = MercuryCustomerService(account=account)
    if (
        mercury_service.is_method_name_valid(method_name=transaction_type)
        and mercury_service.is_customer_eligible()
    ):
        is_mercury_applied, available_limit = mercury_service.get_mercury_available_limit(
            account_limit=account_limit,
            min_duration=min_duration,
            max_duration=max_duration,
            transaction_type=transaction_type,
        )
        is_show_information_icon = is_mercury_applied
        logger.info(
            {
                "action": "juloserver.loan.services.views_related.get_range_loan_amount",
                "message": "after running mercury service",
                "customer_id": mercury_service.customer.id,
                "original_available_limit": original_available_limit,
                "is_mercury_applied": is_mercury_applied,
                "new_available_limit": available_limit,
            }
        )

    application = account.get_active_application()

    max_amount = compute_range_max_amount(
        available_limit=available_limit,
        transaction_type=transaction_type,
        app=application,
        provision_rate=origination_fee,
    )

    loan_amount_fs = get_loan_amount_default_fs(account.customer_id)
    min_amount_threshold = loan_amount_fs.get(
        'min_amount_threshold', LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
    )
    if transaction_type == TransactionType.ECOMMERCE:
        min_amount_threshold = get_ecommerce_limit_transaction()
    elif transaction_type == TransactionMethodCode.EDUCATION.name:
        min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_EDUCATION
    elif transaction_type == TransactionMethodCode.HEALTHCARE.name:
        min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_HEALTHCARE
    min_amount = min_amount_threshold if min_amount_threshold < available_limit else available_limit

    loan_dbr = LoanDbrSetting(application, True)

    max_loan_amount = 0
    if loan_dbr.is_eligible:
        # Only do checking if is eligible
        default_amount = loan_amount_fs.get(
            'dbr_loan_amount_default', LoanJuloOneConstant.DBR_LOAN_AMOUNT_DEFAULT
        )

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        available_duration = get_loan_duration(
            default_amount,
            max_duration,
            min_duration,
            account_limit.set_limit,
            customer=account.customer,
            application=application,
        )
        first_payment_date = get_first_payment_date_by_application(application)
        is_loan_one = available_duration[0] == 1
        is_qris_transaction = transaction_type == TransactionMethodCode.QRIS.name
        is_ecommerce = transaction_type == TransactionType.ECOMMERCE
        is_payment_point = False

        # calculating the amount 2 million for each available duration
        for duration in available_duration:
            loan_amount = default_amount
            (
                is_exceeded,
                _,
                _,
                provision_fee_rate,
                adjusted_interest_rate,
                insurance_premium_rate,
                _,
            ) = validate_max_fee_rule(
                first_payment_date,
                monthly_interest_rate,
                duration,
                origination_fee,
            )

            if is_exceeded:
                # adjust loan amount based on new provision
                if origination_fee != provision_fee_rate and not self_bank_account:
                    loan_amount = get_loan_amount_by_transaction_type(
                        loan_amount, provision_fee_rate, self_bank_account
                    )

                monthly_interest_rate = adjusted_interest_rate

            monthly_installment = calculate_installment_amount(
                loan_amount, duration, monthly_interest_rate
            )

            today_date = timezone.localtime(timezone.now()).date()
            _, _, first_monthly_installment = compute_first_payment_installment_julo_one(
                loan_amount,
                duration,
                monthly_interest_rate,
                today_date,
                first_payment_date,
                False,
            )

            if (
                is_loan_one
                and (is_payment_point or is_qris_transaction or is_ecommerce)
                and not is_exceeded
            ):
                monthly_installment = first_monthly_installment

            is_dbr_exceeded = loan_dbr.is_dbr_exceeded(
                duration=duration,
                payment_amount=monthly_installment,
                first_payment_date=first_payment_date,
                first_payment_amount=first_monthly_installment,
            )
            if not is_dbr_exceeded:
                # if 1 of the durations is eligible, return 2 million
                max_loan_amount = default_amount
                break

        # make sure it wont breach current min&max amount
        # also if no dbr available, will be set to minimum amount
        if max_loan_amount < min_amount:
            max_loan_amount = min_amount
        elif max_loan_amount > max_amount:
            max_loan_amount = max_amount

    result = dict(
        min_amount_threshold=min_amount_threshold,
        min_amount=min_amount,
        max_amount=max_amount,
        default_amount=int(max_loan_amount),
        is_show_information_icon=is_show_information_icon,
    )

    logger.info(
        {
            "action": "juloserver.loan.services.views_related.get_range_loan_amount",
            "message": "Result of get_range_loan_amount()",
            "account": account.id,
            "customer_id": account.customer_id,
            "result": result,
        }
    )
    return result


def assign_loan_to_healthcare_user(loan_id, healthcare_user_id):
    AdditionalLoanInformation.objects.create(
        loan_id=loan_id,
        content_type=ContentType.objects.get_for_model(HealthcareUser),
        object_id=healthcare_user_id,
    )


def is_search_feature_with_redis(feature_name):
    return FeatureSetting.objects.filter(
        feature_name=feature_name,
        is_active=True,
    ).exists()


def search_data_by_name_with_redis(prefix, phrase, limit):
    try:
        redis_completion_engine = RedisEnginePy3(prefix=prefix)
        # in case search by some letters
        if redis_completion_engine.clean_phrase(phrase=phrase):
            response_data = redis_completion_engine.search_json(phrase=phrase, limit=limit)

        # in case not search anything -> get data in hash table
        else:
            redis_client = redis_completion_engine.client
            response_data = []
            count = 0
            for _, value in redis_client.hscan_iter(redis_completion_engine.data_key):
                response_data.append(json.loads(value.decode()))
                count += 1
                if count >= limit:
                    break

        return True, response_data
    except redis.exceptions.RedisError:
        sentry_client = ()
        sentry_client.captureException()
        return False, None


def get_showing_different_pricing_feature_setting():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SHOW_DIFFERENT_PRICING_ON_UI,
        is_active=True,
    ).last()


def get_provision_fee_from_credit_matrix(
    loan_amount_request: int,
    credit_matrix_product: CreditMatrix,
    is_withdraw_funds: bool,
) -> tuple:

    if not get_showing_different_pricing_feature_setting():
        return 0, 0

    provision_rate = credit_matrix_product.origination_fee_pct
    loan_amount = get_loan_amount_by_transaction_type(
        loan_amount_request, provision_rate, is_withdraw_funds
    )
    return int(py2round(loan_amount * provision_rate)), loan_amount


def get_crossed_interest_and_installment_amount(loan: Loan) -> tuple:
    """
    calculate from credit matrix if the loan has CMR
        if CM > CMR => show crossed amount
        if CM == CMR or CM < CMR => not show
        if not CMR => not show
    return: crossed_interest, crossed_installment_amount, crossed_disbursement_amount
    """
    if not get_showing_different_pricing_feature_setting():
        return 0, 0, 0

    credit_matrix_repeat_loan = CreditMatrixRepeatLoan.objects.filter(loan_id=loan.pk).exists()
    if not credit_matrix_repeat_loan:
        return 0, 0, 0

    today_date = timezone.localtime(timezone.now()).date()
    application = loan.account.get_active_application()
    first_payment_date = get_first_payment_date_by_application(application)
    interest_rate_cm = py2round(loan.product.monthly_interest_rate, 3)
    interest_rate_cmr = loan.interest_rate_monthly
    provision_rate_cm = loan.product.origination_fee_pct
    is_withdraw_funds = True

    # calculate installment_amount with CM
    original_loan_amount = loan.loan_amount
    if loan.transaction_method_id != TransactionMethodCode.SELF.code:
        # Other methods: loan_amount_request == loan.loan_disbursement_amount
        original_loan_amount = loan.loan_disbursement_amount
        is_withdraw_funds = False

    adjusted_loan_amount = get_loan_amount_by_transaction_type(
        original_loan_amount, provision_rate_cm, is_withdraw_funds
    )
    installment_amount_cm = get_crossed_installment_amount(
        loan_amount=adjusted_loan_amount,
        loan_duration=loan.loan_duration,
        interest_rate_cm=interest_rate_cm,
        today_date=today_date,
        first_payment_date=first_payment_date,
    )

    # Check crossed
    # crossed_interest_rate
    crossed_interest_rate = interest_rate_cm if interest_rate_cm > interest_rate_cmr else 0

    # crossed_installment_amount
    crossed_installment_amount = 0
    crossed_installment_amount = (
        installment_amount_cm if installment_amount_cm > loan.installment_amount else 0
    )

    # crossed_loan_disbursement_amount
    provision_fee_cm = int(py2round(adjusted_loan_amount * provision_rate_cm))
    crossed_disbursement_amount = get_crossed_loan_disbursement_amount(
        transaction_method_id=loan.transaction_method_id,
        loan_amount=adjusted_loan_amount,
        provision_amount_cm=provision_fee_cm,
        current_disbursement_amount=loan.loan_disbursement_amount,
    )

    return crossed_interest_rate, crossed_installment_amount, crossed_disbursement_amount


class TransactionResultAPIService:
    def __init__(self, loan: Loan) -> None:
        self.loan = loan
        self.loan_details = get_loan_details(loan)
        self.method = loan.transaction_method

    def _get_fe_messages_fs(self) -> MobileFeatureSetting:
        """
        Get FE message setting for this api
        """
        fs = MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.TRANSACTION_RESULT_FE_MESSAGES,
            is_active=True,
        ).last()
        return fs

    def _type(self, title, value, type, image=""):
        return {
            "title": title,
            "value": str(value) if value else "-",
            "type": type,
            "image": image,
        }

    def _text_normal(self, title: str, value: str):
        return self._type(
            title=title,
            value=value,
            type=TransactionResultConst.Type.TEXT_NORMAL,
        )

    def _image_text(self, title: str, value: str, image: str) -> Dict:
        return self._type(
            title=title,
            value=value,
            image=image,
            type=TransactionResultConst.Type.IMAGE_TEXT,
        )

    def _text_copy(self, title: str, value: str):
        return self._type(
            title=title,
            value=value,
            type=TransactionResultConst.Type.TEXT_COPY,
        )

    @property
    def status(self):
        """
        Get status for APIView Transaction Result
        """
        loan_status = self.loan.loan_status_id

        if loan_status >= LoanStatusCodes.CURRENT:
            return TransactionResultConst.Status.SUCCESS

        if loan_status in LoanStatusCodes.fail_status():
            return TransactionResultConst.Status.FAILED

        return TransactionResultConst.Status.IN_PROGRESS

    @property
    def displayed_loan_amount(self) -> str:
        """
        Display to Frontend
        Self & Other show loan amount
        The rest show disbursement amount
        """
        displayed_amount = self.loan.loan_disbursement_amount
        if self.method.id in [TransactionMethodCode.SELF.code, TransactionMethodCode.OTHER.code]:
            displayed_amount = self.loan.loan_amount

        return display_rupiah_no_space(displayed_amount)

    @property
    def status_image_url(self) -> str:
        path = 'transaction_status/{}.png'.format(self.status.lower())
        url = settings.STATIC_ALICLOUD_BUCKET_URL + path

        return url

    @property
    def product_detail(self) -> Dict[str, Any]:
        product_name = self.method.fe_display_name

        # seperating product name for pulsa & paket data
        if self.method.id == TransactionMethodCode.PULSA_N_PAKET_DATA.code:
            details = self.loan_details['topup_phone']
            is_pulsa = details['type'] == SepulsaProductCategory.PULSA
            if is_pulsa:
                product_name = "Pulsa"
            else:
                product_name = "Paket Data"

        # julo shop
        if self.loan.juloshop_transaction:
            product_name = "JULO Shop"

        if self.loan.is_qris_1_product:
            details = self.loan_details['qris']
            product_name = details['product_name']

        return {
            "category_product_name": self.method.fe_display_name,
            "product_name": product_name,
            "product_image": self.method.foreground_icon_url,
            "transaction_type_code": self.method.id,
            "deeplink": TransactionResultConst.DEEPLINK_MAPPING[self.method.id],
        }

    @property
    def content(self) -> Dict[str, Any]:
        content = []
        if self.loan.is_to_self or self.loan.is_to_other:
            bank_logo, bank_name, name_from_bank_validation, account_number = None, None, None, None

            bad = getattr(self.loan, "bank_account_destination", None)
            if bad:
                bank_logo = bad.bank.bank_logo
                bank_name = bad.get_bank_name
                name_from_bank_validation = bad.get_name_from_bank_validation
                account_number = bad.account_number

            content = [
                self._image_text(
                    title="Bank tujuan",
                    value=bank_name,
                    image=bank_logo if bank_logo else "",
                ),
                self._text_normal(
                    title="Pemilik rekening",
                    value=name_from_bank_validation,
                ),
                self._text_normal(
                    title="Nomor rekening",
                    value=account_number,
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
                self._text_normal(
                    title="Dana cair",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
            ]
        elif self.loan.is_ewallet_product:
            details = self.loan_details['topup_e_wallet']
            logo = details['product_logo']
            content = [
                self._image_text(
                    title="Jenis",  # product name
                    value=details['product_kind'],
                    image=logo if logo else "",
                ),
                self._text_normal(
                    title="Nomor HP",
                    value=details['phone_number'],
                ),
                self._text_normal(
                    title="Nominal",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
        elif self.loan.is_mobile_product:
            # mobile & data
            details = self.loan_details['topup_phone']
            content = [
                self._image_text(
                    title="Jenis",  # product name
                    value=details['product_name'],
                    image="",
                ),
                self._text_normal(
                    title="Nomor HP",
                    value=details['phone_number'],
                ),
                self._text_normal(
                    title="Nominal",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
        elif self.loan.is_mobile_postpaid:
            details = self.loan_details['topup_phone']
            content = [
                self._image_text(
                    title="Jenis",  # product name
                    value=details['product_name'],
                    image="",
                ),
                self._text_normal(
                    title="Nomor HP",
                    value=details['phone_number'],
                ),
                self._text_normal(
                    title="Nama",
                    value=details['customer_name'],
                ),
                self._text_normal(
                    title="Nominal tagihan",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
        elif self.loan.is_electricity_product:
            # pre-paid (token) or normal pay
            details = self.loan_details['topup_pln']
            is_prepaid = details["type"] == SepulsaProductCategory.ELECTRICITY_PREPAID
            content = [
                self._text_normal(
                    title="Jenis",  # product name
                    value="Token Listrik PLN" if is_prepaid else "Tagihan Listrik PLN",
                ),
                self._text_normal(
                    title="No.meter / ID pelanggan",
                    value=details['customer_number'],
                ),
                self._text_normal(
                    title="Nama",
                    value=details['customer_name'],
                ),
                self._text_normal(
                    title="Nominal token" if is_prepaid else "Nominal tagihan",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
            # if pre-paid, show token
            if is_prepaid:
                token = details.get("token", None)
                if self.status == TransactionResultConst.Status.SUCCESS and token:
                    field = self._text_copy
                else:
                    # if not success, show empty "-"
                    token = None
                    field = self._text_normal

                content.append(
                    field(
                        title="Token",
                        value=token,
                    )
                )

        elif self.loan.is_water_product:
            details = self.loan_details['topup_pdam']
            content = [
                self._text_normal(
                    title="Nomor pelanggan",
                    value=details['customer_number'],
                ),
                self._text_normal(
                    title="Nama",
                    value=details['customer_name'],
                ),
                self._text_normal(
                    title="Nominal tagihan",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
        elif self.loan.is_bpjs_product:
            details = self.loan_details['topup_bpjs']
            content = [
                self._text_normal(
                    title="Nama peserta",
                    value=details['customer_name'],
                ),
                self._text_normal(
                    title="No. kartu peserta",
                    value=details['bpjs_number'],
                ),
                self._text_normal(
                    title="Nominal tagihan",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
        elif self.loan.is_ecommerce_product:
            # check juloshop
            juloshop_transaction = self.loan.juloshop_transaction
            if juloshop_transaction:
                julo_shop_product = get_juloshop_loan_product_details(juloshop_transaction)
                content = [
                    self._text_normal(
                        title="Nama produk",
                        value=julo_shop_product.get('productName'),
                    ),
                    self._text_normal(
                        title="Jumlah produk",
                        value=str(julo_shop_product.get('quantity')),
                    ),
                    self._text_normal(
                        title="Harga produk",
                        value=display_rupiah_no_space(int(julo_shop_product.get('price'))),
                    ),
                    self._text_normal(
                        title="Nominal",
                        value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                    ),
                    self._text_normal(
                        title="Jumlah pinjaman",
                        value=display_rupiah_no_space(self.loan.loan_amount),
                    ),
                ]
            else:
                # non-juloshop
                details = self.loan_details['ecommerce']
                content = [
                    self._text_normal(
                        title="Jenis",
                        value=details['product_kind'],
                    ),
                    self._text_normal(
                        title="Nomor HP",
                        value=details['va_number'],
                    ),
                    self._text_normal(
                        title="Nominal",
                        value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                    ),
                    self._text_normal(
                        title="Jumlah pinjaman",
                        value=display_rupiah_no_space(self.loan.loan_amount),
                    ),
                ]
        elif self.loan.is_train_ticket_product:
            details = self.loan_details['train_ticket']
            content = [
                self._text_normal(
                    title="Nama pemesan",
                    value=details['customer_name'],
                ),
                self._text_normal(
                    title="Rute",
                    value=details['train_route'],
                ),
                self._text_normal(
                    title="Nominal",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
        elif self.loan.is_healthcare_product:
            details = self.loan_details['healthcare_user']
            bank_data = self.loan_details['bank']
            bad = self.loan.bank_account_destination
            bank_logo = bad.bank.bank_logo
            content = [
                self._text_normal(
                    title="Rumah sakit",
                    value=details['healthcare_platform_name'],
                ),
                self._image_text(
                    title="No.rek./VA",
                    value=bank_data['account_number'],
                    image=bank_logo if bank_logo else "",
                ),
                self._text_normal(
                    title="Nama",
                    value=details['healthcare_user_fullname'],
                ),
                self._text_normal(
                    title="Nominal tagihan",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]
            bank_reference_number = details['bank_reference_number']
            if self.status == TransactionResultConst.Status.SUCCESS and bank_reference_number:
                reference_bank_field = self._text_copy
            else:
                reference_bank_field = self._text_normal
                bank_reference_number = None

            content.append(
                reference_bank_field(
                    title="No. referensi bank",
                    value=bank_reference_number,
                ),
            )

        elif self.loan.is_education_product:
            details = self.loan_details['student_tuition']
            bank_logo = details['bank']['logo']
            content = [
                self._text_normal(
                    title="Sekolah",
                    value=details['school']['name'],
                ),
                self._image_text(
                    title="No.rek./VA",
                    value=details['bank']['account_number'],
                    image=bank_logo if bank_logo else "",
                ),
                self._text_normal(
                    title="Nama",
                    value=details['name'],
                ),
                self._text_normal(
                    title="Nominal tagihan",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                ),
            ]

            bank_reference_number = details['bank']['reference_number']
            if self.status == TransactionResultConst.Status.SUCCESS and bank_reference_number:
                reference_bank_field = self._text_copy
            else:
                reference_bank_field = self._text_normal
                bank_reference_number = None

            content.append(
                reference_bank_field(
                    title="No. referensi bank",
                    value=bank_reference_number,
                ),
            )
        elif self.loan.is_qris_1_product:
            details = self.loan_details['qris']
            content = [
                self._text_normal(
                    title="Jenis",
                    value=details['type'],
                ),
                self._text_normal(
                    title="Lokasi Merchant",
                    value=details['merchant_city'],
                ),
                self._text_normal(
                    title="Merchant PAN",
                    value=details['merchant_pan'],
                ),
                self._text_normal(
                    title="Customer PAN",
                    value=details['customer_pan'],
                ),
                self._text_normal(
                    title="ID terminal merchant",
                    value=details['terminal_id'],
                ),
                self._text_normal(
                    title="Nominal",
                    value=display_rupiah_no_space(self.loan.loan_disbursement_amount),
                ),
            ]
            admin_fee = details.get('admin_fee')
            if admin_fee is not None:
                content.append(
                    self._text_normal(
                        title="Biaya Admin",
                        value=display_rupiah_no_space(admin_fee),
                    )
                )
            tax_fee = details.get('tax_fee')
            if tax_fee is not None:
                content.append(
                    self._text_normal(
                        title="PPN",
                        value=display_rupiah_no_space(tax_fee),
                    )
                )
            monthly_interest_rate = details.get('monthly_interest_rate')
            if monthly_interest_rate is not None:
                content.append(
                    self._text_normal(
                        title="Bunga",
                        value=display_percent_from_float_type(monthly_interest_rate),
                    )
                )

            # appending "jumlah pinjaman" in the end as the ordering at FE is controlled from BE
            content.append(
                self._text_normal(
                    title="Jumlah pinjaman",
                    value=display_rupiah_no_space(self.loan.loan_amount),
                )
            )

        return content

    def _get_juloshop_fe_messages(self) -> Tuple[str, str, str]:
        title = ""
        payment_message = ""
        info_message = ""
        if self.status == TransactionResultConst.Status.SUCCESS:
            title = "Transaksi JULO Shop Berhasil"
            payment_message = "Terima kasih! Kalau butuh yang lainnya, belanjanya di JULO Shop aja!"
        elif self.status == TransactionResultConst.Status.FAILED:
            title = "Transaksi JULO Shop Gagal"
            payment_message = (
                "Dana akan dikembalikan ke limit tersedia. Coba ulangi lagi transaksinya, yuk!"
            )
        else:
            title = "Transaksi JULO Shop sedang diproses. Silakan tunggu, ya!"

        return {
            "title": title,
            "payment_message": payment_message,
            "info_message": info_message,
        }

    @property
    def fe_messages(self) -> Dict[str, Any]:
        # juloshop uses same transaction id as ecommerce
        # so it is hard-coded instead of feature setting
        if self.loan.juloshop_transaction:
            return self._get_juloshop_fe_messages()

        fs = self._get_fe_messages_fs()
        if not fs:
            raise TransactionResultException("Missing transaction result FS for FE messages")

        method_id = str(self.method.id)

        title = fs.parameters[method_id][self.status]['title']
        payment_message = fs.parameters[method_id][self.status]['payment_message']
        info_message = fs.parameters[method_id][self.status]['info_message']

        if self.method.id == TransactionMethodCode.LISTRIK_PLN.code:
            is_prepaid = (
                self.loan_details["topup_pln"]["type"] == SepulsaProductCategory.ELECTRICITY_PREPAID
            )
            # if not pre-paid, doesn't show token(info) message
            if not is_prepaid:
                info_message = ""

        return {
            "title": title,
            "payment_message": payment_message,
            "info_message": info_message,
        }

    @property
    def shown_date(self) -> datetime:
        """
        Disbursement date if success, else show loan cdate
        """
        shown_date = self.loan.cdate
        if self.status == TransactionResultConst.Status.SUCCESS:
            shown_date = self.loan.fund_transfer_ts

        return timezone.localtime(shown_date)

    @property
    def delay_disbursement(self) -> Dict[str, Any]:  # flake8: noqa
        result = ReturnDelayDisbursementTransactionResult(is_eligible=False)
        get_dd = LoanDelayDisbursementFee.objects.get_or_none(loan_id=self.loan)
        if get_dd:
            # get TNC
            dd_feature_setting: FeatureSetting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.DELAY_DISBURSEMENT,
            ).last()
            if dd_feature_setting:
                result.tnc = dd_feature_setting.parameters.get("content", {}).get('tnc', "")
            result.is_eligible = True
            result.threshold_time = get_dd.threshold_time
            result.cashback = get_dd.cashback
            result.agreement_timestamp = get_dd.agreement_timestamp
            result.status = get_dd.status

        # Convert to dictionary
        result_dict = result.to_dict()
        return result_dict

    def construct_response_data(self) -> Dict[str, Any]:
        """
        Construct data for transaction result API
        """
        return {
            "status_image": self.status_image_url,
            "product_detail": self.product_detail,
            "content": self.content,
            "fe_messages": self.fe_messages,
            "shown_amount": self.displayed_loan_amount,
            "disbursement_date": self.shown_date,
            "status": self.status,
            "delay_disbursement": self.delay_disbursement,
        }


def get_crossed_loan_disbursement_amount(
    transaction_method_id: int,
    loan_amount: int,
    provision_amount_cm: int,
    current_disbursement_amount: int,
) -> int:
    """
    Having crossed loan disburesment amount in SELF method only
    Because other methods have loan_amount_request == disbursement_amount
    cm: credit_matrix
    """
    crossed_disbursement_amount = 0
    if transaction_method_id == TransactionMethodCode.SELF.code:
        disbursement_amount_cm = py2round(loan_amount - provision_amount_cm)
        if disbursement_amount_cm < current_disbursement_amount:
            crossed_disbursement_amount = disbursement_amount_cm

    return int(crossed_disbursement_amount)


def get_crossed_installment_amount(
    loan_amount: int,
    loan_duration: int,
    interest_rate_cm: float,
    today_date: str,
    first_payment_date: str,
) -> int:
    """
    if duration > 1 => get normal installment (30 days)
    else first installment (first due date)
    """
    if loan_duration > 1:
        _, _, installment_amount = compute_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate_cm
        )
    else:
        _, _, installment_amount = compute_first_payment_installment_julo_one(
            loan_amount,
            loan_duration,
            interest_rate_cm,
            today_date,
            first_payment_date,
        )
    return installment_amount


def get_loan_amount_default_fs(customer_id: int):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOAN_AMOUNT_DEFAULT_CONFIG, is_active=True
    ).first()

    if not feature_setting:
        return dict()

    parameters = feature_setting.parameters
    whitelist_config = parameters['whitelist']
    if whitelist_config['is_active']:
        return parameters if customer_id in whitelist_config['customer_ids'] else dict()
    return parameters


def get_loan_xid_from_inactive_loan(account_id: int) -> Optional[int]:
    loans = (
        Loan.objects.filter(
            account_id=account_id,
            loan_status_id__in=LoanStatusCodes.inactive_status(),
        )
        .exclude(
            transaction_method_id__in=[
                TransactionMethodCode.JFINANCING.code,
                TransactionMethodCode.CREDIT_CARD.code,
                TransactionMethodCode.QRIS_1.code,
            ]
        )
        .order_by('-id')
        .all()
    )
    for loan in loans:
        is_signing = DigisignDocument.objects.filter(
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER, document_source=loan.id,
            signing_status=SigningStatus.PROCESSING
        ).exists()
        if not is_signing:
            return loan.loan_xid

    return None


def apply_pricing_logic(
        loan_duration,
        threshold_fs,
        credit_matrix_repeat,
        min_pricing
):
    """Apply the price drop logic based on the tenor and pricing rules."""
    drop_pct = 0
    # Sort the configuration by keys (tenor months) in descending order
    pricing_config = {int(k): v for k, v in threshold_fs['data'].items()}
    sorted_config = sorted(pricing_config.items(), reverse=True)

    # Iterate through the sorted ranges
    for min_tenor, price_drop in sorted_config:
        if loan_duration >= min_tenor:
            drop_pct = price_drop
            break
    new_pct = credit_matrix_repeat.interest - drop_pct
    return min(max(new_pct, min_pricing), credit_matrix_repeat.interest), drop_pct


def check_tenor_fs():
    return FeatureSetting.objects.filter(
        feature_name=LoanFeatureNameConst.NEW_TENOR_BASED_PRICING,
        is_active=True
    ).last()


def check_if_tenor_based_pricing(
        customer,
        new_tenor_feature_settings,
        loan_duration,
        credit_matrix_repeat,
        transaction_method_id,
        check_duration=False
):
    threshold_fs = new_tenor_feature_settings.parameters['thresholds']
    cmr_feature_setting = new_tenor_feature_settings.parameters['cmr_segment']
    transaction_method_fs = new_tenor_feature_settings.parameters['transaction_methods']
    min_pricing_fs = new_tenor_feature_settings.parameters['minimum_pricing']
    min_pricing = min_pricing_fs['data'] if min_pricing_fs['is_active'] else\
        LoanJuloOneConstant.MIN_NEW_PCT_THRESHOLD
    monthly_interest_rate = credit_matrix_repeat.interest
    tenor_based_pricing = None

    cmr_segment = credit_matrix_repeat.customer_segment
    cmr_segments = cmr_feature_setting['data']
    segment_validation_result = (not cmr_feature_setting['is_active']) or\
                                (cmr_segment in cmr_segments)

    transaction_method = transaction_method_id
    transaction_methods = transaction_method_fs['data']
    transaction_method_validation_result = (not transaction_method_fs['is_active']) or\
                                           (transaction_method in transaction_methods)
    check_cmr_and_transaction_validation = (
        segment_validation_result and transaction_method_validation_result
    )

    if check_duration and check_cmr_and_transaction_validation:
        monthly_interest_rate, drop_pct = apply_pricing_logic(
            loan_duration,
            threshold_fs,
            credit_matrix_repeat,
            min_pricing
        )
        if drop_pct:
            tenor_based_pricing = TenorBasedPricing.objects.create(
                customer=customer,
                customer_segment=credit_matrix_repeat.customer_segment,
                tenure=loan_duration,
                new_pricing=monthly_interest_rate,
                previous_pricing=credit_matrix_repeat.interest,
                reduce_interest=drop_pct,
                transaction_method=credit_matrix_repeat.transaction_method
            )
    return (
        monthly_interest_rate,
        tenor_based_pricing,
        min_pricing,
        threshold_fs,
        check_cmr_and_transaction_validation
    )


class LoanTenureRecommendationService:
    """
    For Loan Duration API Response
    """

    def __init__(self, available_tenures: List[int], customer_id: int, transaction_method_id: int):
        self.fs = FeatureSettingHelper(
            feature_name=LoanFeatureNameConst.LOAN_TENURE_RECOMMENDATION,
        )
        self.customer_id = customer_id
        self.available_tenures = available_tenures
        self.transaction_method_id = transaction_method_id

    @property
    def campaign_tag(self) -> str:
        return self.fs.params['general_config']['campaign_tag']

    @property
    def intervention_campaign(self) -> str:
        return self.fs.params['general_config']['intervention_campaign']

    @property
    def fs_min_tenure(self) -> int:
        return self.fs.params['general_config']['min_tenure']

    @property
    def fs_max_tenure(self) -> int:
        return self.fs.params['general_config']['max_tenure']

    @property
    def fs_is_active(self) -> bool:
        return self.fs.is_active

    @property
    def is_experiment_active(self) -> bool:
        return self.fs.params['experiment_config']['is_active']

    @property
    def experiment_last_digits(self) -> List[int]:
        return self.fs.params['experiment_config']['experiment_customer_id_last_digits']

    @property
    def experiment_customer_last_digits(self) -> List[int]:

        # valid single digits, ignore number != 0-9
        valid_last_digits = [
            x for x in self.experiment_last_digits if isinstance(x, int) and 0 <= x <= 9
        ]
        return valid_last_digits

    def _is_valid_transaction_method(self) -> bool:
        return (
            int(self.transaction_method_id)
            in self.fs.params['general_config']['transaction_methods']
        )

    def _ends_with(self, num: int, num_list: List[int]) -> bool:
        """
        Check if int ends with a number
        """
        # Get the last digit of the number
        last_digit = int(str(num)[-1])

        # Check if the last digit is in the number_list
        return last_digit in num_list

    def _get_recommended_tenure_from_range(self, min_tenure: int, max_tenure: int) -> Optional[int]:
        """
        Get max available tenure in set range from FS

        e.g.
        min 4, max 10

        1, 2, 3 -> none
        3, 4, 5 -> 5
        8, 9, 10 -> 10
        9, 10, 11 -> 10

        """
        if not self.available_tenures:
            return None

        max_available_tenure = max(self.available_tenures)

        # 1, 2, 3 -> none
        if min_tenure > max_available_tenure:
            return None

        # 3, 4, 5 -> 5
        # 8, 9, 10 -> 10
        if min_tenure <= max_available_tenure <= max_tenure:
            return max_available_tenure

        # 9, 10, 11 -> 10
        if max_available_tenure > max_tenure:
            return max_tenure

    def get_recommended_tenure(self) -> Optional[int]:

        # check last digit of customer id
        is_experiment_user = self._ends_with(
            num=self.customer_id,
            num_list=self.experiment_customer_last_digits,
        )
        is_valid_method = self._is_valid_transaction_method()

        recommended_tenure = None

        if is_valid_method:
            recommended_tenure = self._get_recommended_tenure_from_range(
                min_tenure=self.fs_min_tenure,
                max_tenure=self.fs_max_tenure,
            )
            # check experiment
            if self.is_experiment_active:
                if is_experiment_user:
                    return recommended_tenure

                return None

        return recommended_tenure

    def set_loan_campaign(self, loan_choice: Dict) -> None:
        """
        Update loan_campaign field if loan choice meets condition
        """

        if not self.fs.is_active:
            return

        recommended_tenure = self.get_recommended_tenure()
        if not recommended_tenure:
            return

        tenure_recommendation_tag = self.campaign_tag

        # only one tag per tenure set
        for tenure, data in loan_choice.items():
            if int(tenure) == recommended_tenure:
                data['loan_campaign'] = tenure_recommendation_tag
                break

    def set_loan_campaigns(self, loan_choice: Dict) -> None:
        """
        Update loan_campaigns and tag_campaign field if loan choice meets condition
        """

        if not self.fs.is_active:
            return

        recommended_tenure = self.get_recommended_tenure()
        if not recommended_tenure:
            return

        tenure_recommendation_tag = self.campaign_tag

        # only one tag per tenure set
        for tenure, data in loan_choice.items():
            if int(tenure) == recommended_tenure:
                data['loan_campaigns'] = [tenure_recommendation_tag]
                break

    def set_intervention_visibility_and_tag_campaign(self, loan_choice: Dict) -> None:
        """
        Update intervention_campaign, is_show_intervention, tag_campaign and loan_campaigns field
        if loan choice meets condition
        """

        if not self.fs.is_active:
            return

        recommended_tenure = self.get_recommended_tenure()
        if not recommended_tenure:
            return

        intervention_recommendation_tag = self.intervention_campaign

        # only one tag per tenure set
        for tenure, data in loan_choice.items():
            if int(tenure) == recommended_tenure:
                data['intervention_campaign'] = intervention_recommendation_tag
                data['is_show_intervention'] = False
                data['tag_campaign'] = LoanJuloOneConstant.TAG_CAMPAIGN
                data['loan_campaigns'].append('Lihat Detail')
                break


def get_tenure_intervention() -> dict:
    thor_fs = ThorTenorInterventionModelSetting()
    if thor_fs.is_active:
        return {
            'delay_intervention': thor_fs.delay_intervention,
            'duration_intervention': thor_fs.duration_intervention
        }
    return {}


def append_qris_method(account: Account, transaction_methods) -> List[TransactionMethod]:
    """
    Temporary method to work around QRIS product not showing on front page
    Appending last method to be QRIS_1
    """
    fs = AppendQrisTransactionMethodSetting()
    if account and fs.is_active:
        if not is_qris_1_blocked(account=account, method_code=TransactionMethodCode.QRIS_1.code):
            qris_method = TransactionMethod.objects.get(pk=TransactionMethodCode.QRIS_1.code)
            if qris_method not in transaction_methods:
                transaction_methods[-1] = qris_method

    return transaction_methods


def show_select_tenure(show_tenure: List[int], loan_choice: Dict, customer_id: int) -> Dict:
    if not (show_tenure and loan_choice):
        return loan_choice

    tenure_keys = sorted(loan_choice.keys())
    start = max(show_tenure[0], tenure_keys[0])
    end = min(show_tenure[-1], tenure_keys[-1])
    middle_keys = sorted(set(show_tenure) & set(tenure_keys))

    # if there is no overlap between show_tenure and loan_choice
    if end < start:
        return loan_choice

    result = {
        key: loan_choice[key]
        for key in [start] + [k for k in middle_keys if start < k < end] + [end]
    }

    # Filtering: keep only keys present in show_tenure
    filtered_loan_choice = {key: value for key, value in result.items() if key in show_tenure}

    # logging for trouble shoot
    logger.info(
        {
            "action": "juloserver.loan.services.views_related.show_select_tenure",
            "message": "filter selected tenures based on CM repeat ",
            "original_loan_duration": loan_choice.keys(),
            "after_loan_duration": filtered_loan_choice.keys(),
            "customer_id": customer_id,
        }
    )

    return filtered_loan_choice


def get_cross_selling_recommendations(account, transaction_type):
    account_limit = AccountLimit.objects.filter(
        account=account
    ).values(
        'available_limit'
    ).last()
    feature_setting = CrossSellingConfigMethodSetting()

    if not feature_setting.is_active:
        return True, {}

    products = feature_setting.get_products
    info = feature_setting.get_info_param
    number_of_products = feature_setting.get_number_of_products

    # Filter eligible products based on available limit and lock status
    eligible_products = [
        product for product in products
        if product["minimum_limit"] <= account_limit["available_limit"]
        and not product["is_locked"]
        and product["method"] != transaction_type
    ]

    # Sort by priority and take the top n products
    eligible_products.sort(key=lambda x: x["priority"])
    recommended_products = eligible_products[:number_of_products]

    method_ids = [product["method"] for product in recommended_products]
    transaction_methods = TransactionMethod.objects.filter(id__in=method_ids).values(
        "id", "fe_display_name", "foreground_icon_url"
    )

    transaction_map = {tm["id"]: tm for tm in transaction_methods}

    response_data = {
        "available_limit": display_rupiah_no_space(account_limit["available_limit"]),
        "available_limit_image": feature_setting.get_available_limit_image,
        "cross_selling_message": feature_setting.get_cross_selling_message,
        "recommendation_products": [
            {
                "product_name": transaction_map[product["method"]]["fe_display_name"],
                "product_image": transaction_map[product["method"]]["foreground_icon_url"],
                "product_description": info.get(str(product["method"]), {}).get("message", ""),
                "product_deeplink": info.get(str(product["method"]), {}).get("deeplink", ""),
            }
            for product in recommended_products if product["method"] in transaction_map
        ]
    }

    return True, response_data


class AvailableLimitInfoAPIService:
    def __init__(self, get_cashloan_available_limit: bool, account_id: int, input: Dict):
        """
        input param is data from the API input serializer
        """
        self.fs = AvailableLimitInfoSetting()
        self.mercury_fs = AnaTransactionModelSetting()

        self.get_cashloan_available_limit = get_cashloan_available_limit
        self.input = input
        self.account_id = account_id

    def calculate_cashloan_available_limit(self) -> int:
        from juloserver.loan.services import loan_creation as loan_creation_services

        # case FE wants to calulate cashloan available limit again
        if self.get_cashloan_available_limit and self.mercury_fs.is_active:
            account = Account.objects.get(pk=self.account_id)
            app = account.get_active_application()

            transaction_method_code = self.input['transaction_type_code']
            method = TransactionMethod.objects.get(pk=transaction_method_code)
            self_bank_account = True if transaction_method_code == 1 else False

            # get matrices & data
            matrices = loan_creation_services.get_loan_matrices(
                application=app,
                transaction_method=method,
            )
            creation_cm_data = loan_creation_services.get_loan_creation_cm_data(
                matrices=matrices,
            )

            # calculate using reange loan amount func
            range_loan_amount_result = get_range_loan_amount(
                account=account,
                origination_fee=creation_cm_data.provision_fee_rate,
                monthly_interest_rate=creation_cm_data.monthly_interest_rate,
                transaction_type=method.method,
                self_bank_account=self_bank_account,
                min_duration=creation_cm_data.min_tenure,
                max_duration=creation_cm_data.max_tenure,
            )

            cashloan_available_limit = range_loan_amount_result['max_amount']

        else:
            # otherwise, FE will reuse value somewhere else, we can return zero
            cashloan_available_limit = 0

        return cashloan_available_limit

    def get_normal_available_limit(self) -> int:
        normal_available_limit = (
            AccountLimit.objects.filter(
                account_id=self.account_id,
            )
            .values('available_limit')
            .last()
        )

        return normal_available_limit['available_limit']

    def construct_response_data(self) -> List[Dict]:
        """
        Example response struct:
            {
                "name": "available_cash_loan_limit",
                "title": "Jumlah Pinjaman Tarik Dana",
                "icon": "icon.png",
                "item": [
                    {
                        "item_icon": "icon.png",
                        "item_text": "text"
                    },
                    {
                        "item_icon": "icon.png",
                        "item_text": "text"
                    }
                ],
                "amount": 0
            },
            {
                "name": "normal_available_limit",
                "title": "Jumlah Pinjaman Total Di JULO",
                "icon": "icon.png",
                "item": [
                    {
                        "item_icon": "",
                        "item_text": "text"
                    }
                ],
                "amount": 12000,
            }
        """
        response = []
        if self.fs.is_active:
            displayed_sections = self.fs.displayed_sections

            for section in displayed_sections:
                # similar logic
                section_data = {
                    "name": section,
                    "title": self.fs.get_section_title(section),
                    "icon": self.fs.get_section_icon(section),
                }
                item = []
                for i in self.fs.get_section_items(section):
                    item.append(
                        {
                            "item_icon": i['icon'],
                            "item_text": i['text'],
                        }
                    )
                section_data['item'] = item

                # case for each section
                if section == self.fs.SECTION_AVAILABLE_CASHLOAN_LIMIT:
                    section_data['amount'] = self.calculate_cashloan_available_limit()
                elif section == self.fs.SECTION_NORMAL_AVAILABLE_LIMIT:
                    section_data['amount'] = self.get_normal_available_limit()

                response.append(section_data)

        return response


class UserCampaignEligibilityAPIV2Service:
    def __init__(self, customer: Customer, validated_data: Dict):
        self.customer = customer
        self.data = validated_data
        self.return_data = {
            'campaign_name': '',
            'alert_image': '',
            'alert_description': '',
            'max_default_amount': 0,
            'show_alert': False,
            'show_pop_up': False,
            'toggle_title': '',
            'toggle_description': '',
            'toggle_link_text': '',
            'toggle_click_link': '',
        }

    def is_customer_with_lock_product_campaign(self) -> Tuple[bool, Dict]:
        """
        Check if customer is having locked product campaign
            - Case Mercury: check if they are mercury & is blocked
        """
        is_product_locked_campaign = False
        # Check mercury
        mercury_service = MercuryCustomerService(
            account=self.customer.account,
        )

        mercury_status, _ = mercury_service.get_mercury_status_and_loan_tenure(
            transaction_method_id=self.data['transaction_type_code']
        )

        if mercury_status:
            if mercury_service.is_mercury_customer_blocked():
                self.return_data['campaign_name'] = CampaignConst.PRODUCT_LOCK_PAGE_FOR_MERCURY
                is_product_locked_campaign = True

        return is_product_locked_campaign, self.return_data

    def construct_response_data(self) -> Dict:
        # if no account then < 105, return empty(default) data
        if not self.customer.account:
            return self.return_data

        # lock product campaign (FE will move to lock product page)
        is_product_locked_campaign, response = self.is_customer_with_lock_product_campaign()

        if is_product_locked_campaign:
            return response

        # zero interest campaign
        is_zero_interest_eligible, response = is_customer_can_do_zero_interest(
            customer=self.customer,
            transaction_method_code=self.data['transaction_type_code'],
        )
        if is_zero_interest_eligible:
            return response

        #  julo care campaign
        response = get_julo_care_configuration(
            customer=self.customer,
            transaction_method_code=self.data['transaction_type_code'],
            device_brand=self.data.get('device_brand'),
            device_model=self.data.get('device_model'),
            os_version=self.data.get('os_version'),
        )

        return response


class LockedProductPageService:
    def __init__(self, customer: Customer, input_data: Dict):
        self.customer = customer
        self.fs = LockedProductPageSetting()
        self.input_data = input_data

    def construct_response_data(self) -> Dict:
        lock_page = self.input_data['page']

        # this is for turning on/off repayment button display on UI
        # hardcode to True for now
        is_show_repayment = True

        return {
            "locked_header_image": self.fs.get_header_image_url(setting=lock_page),
            "locked_message": self.fs.get_locked_message(setting=lock_page),
            "is_show_repayment": is_show_repayment,
        }


def filter_loan_choice(
    original_loan_choice: Dict[int, Dict], displayed_tenures: List[int], customer_id: int
) -> Dict[int, Dict]:
    """
    Filter loan choice results (from LoanDurationAPI) based on list of tenures.

    Parameters:
    - loan_choice: A dictionary where keys are tenures and values are dicts with loan data.
    - displayed_tenures: A list of tenures to include in the result.

    Returns:
    - If there is onverlap, returns the over lap
    - Otherwise return original
    """

    # set as original to start
    filtered_choices = original_loan_choice

    if set(filtered_choices.keys()) & set(displayed_tenures):
        filtered_choices = {
            tenure: original_loan_choice[tenure]
            for tenure in displayed_tenures
            if tenure in original_loan_choice.keys()
        }

    logger.info(
        {
            "action": "juloserver.loan.services.views_related.filter_loan_choice",
            "message": "after filtering loan_choices",
            "displayed_tenures": displayed_tenures,
            "original_choices": original_loan_choice.keys(),
            "filtered_choices": filtered_choices.keys(),
            "customer_id": customer_id,
        }
    )

    return filtered_choices

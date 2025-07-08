import logging

from django.utils import timezone
from babel.dates import format_date

from django.conf import settings
from django.template.loader import render_to_string
from django.template import Context
from django.template import Template
from juloserver.dana.tasks import get_dana_loan_agreement_template
from juloserver.digisign.services.digisign_document_services import get_digisign_document_success
from juloserver.followthemoney.constants import LoanAgreementExtensionType
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.utils import (
    display_rupiah_skrtp,
    display_percent_from_float_type,
    convert_payment_number_to_word,
)
from juloserver.julo.models import (
    Loan,
    Document,
    PaymentMethod,
)

from juloserver.julo.services import get_sphp_template
from juloserver.loan.services.sphp import get_loan_type_sphp_content
from juloserver.loan.services.views_related import (
    get_sphp_template_grab,
    get_rentee_sphp_template,
    get_manual_signature,
)
from juloserver.loan.services.loan_related import (
    generate_new_payments,
    readjusted_loan_amount_by_max_fee_rule,
)

from juloserver.followthemoney.models import LoanAgreementTemplate
from juloserver.followthemoney.constants import LoanAgreementType

from juloserver.merchant_financing.services import get_sphp_loan_merchant_financing
from juloserver.followthemoney.services import (
    LoanAgreementLenderSignature,
    LoanAgreementBorrowerSignature,
    LoanAgreementLenderSignatureBSS,
    LoanAgreementBorrowerSignatureBSS,
    GrabLenderAgreementLenderSignature,
    GrabLoanAgreementBorrowerSignature,
    JuloverLoanAgreementBorrowerSignature,
    JuloverLoanAgreementLenderSignature,
    LoanAgreementBorrowerSignatureAxiataWeb,
    LoanAgreementLenderSignatureAxiataWeb,
    LoanAgreementBorrowerSignatureGosel,
    LoanAgreementLenderSignatureGosel,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.views_related import get_sphp_template_julo_one
from juloserver.channeling_loan.constants import BSSChannelingConst
from juloserver.loan.services.loan_related import compute_payment_installment_julo_one
from juloserver.merchant_financing.web_app.services import get_axiata_loan_agreement_template
from juloserver.partnership.services.services import (
    get_gosel_loan_agreement_template,
    get_mf_std_loan_agreement_template,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.qris.services.user_related import get_qris_skrtp_agreement_html


logger = logging.getLogger(__name__)


def get_julo_loan_agreement_template(loan_id, type="document", is_new_digisign=False):
    def _template_return(
        template, agreement_type='sphp', lender_signature=None, borrower_signature=None
    ):
        if not lender_signature:
            lender_signature = LoanAgreementLenderSignature
        if not borrower_signature:
            borrower_signature = LoanAgreementBorrowerSignature
        return template, agreement_type, lender_signature, borrower_signature

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None, None

    account = loan.account
    application = account.last_application
    if not account:
        from juloserver.julo.product_lines import ProductLineCodes

        if loan.application and loan.application.product_line_code in ProductLineCodes.axiata():
            from juloserver.merchant_financing.web_portal.services import (
                get_web_portal_agreement,
            )

            content = get_web_portal_agreement(
                loan, show_provider_signature=True, use_fund_transfer_ts=True
            )
            content = '<html><body>{}</body></html>'.format(content)
            content = content.replace('misc_files/fonts/PinyonScript-Regular.ttf', "")
            return _template_return(content, "sphp")

        return _template_return(get_sphp_template(loan_id, type))

    if account.is_grab_account():
        return _template_return(
            get_sphp_template_grab(loan_id, type),
            lender_signature=GrabLenderAgreementLenderSignature,
            borrower_signature=GrabLoanAgreementBorrowerSignature,
        )

    if loan.is_mf_loan():
        return _template_return(get_sphp_loan_merchant_financing(loan_id))

    if loan.is_rentee_loan():
        return _template_return(get_rentee_sphp_template(loan_id, type))

    template, agreement_type = get_loan_agreement_template_julo_one(
        loan_id, type, is_new_digisign=is_new_digisign
    )

    if application.partner:
        if application.partner.name == PartnerConstant.GOSEL:
            return _template_return(
                template,
                agreement_type,
                lender_signature=LoanAgreementLenderSignatureGosel,
                borrower_signature=LoanAgreementBorrowerSignatureGosel,
            )

    # Channeling BSS have different signature
    if loan.lender and loan.lender.lender_name == BSSChannelingConst.LENDER_NAME:
        return _template_return(
            template,
            agreement_type,
            lender_signature=LoanAgreementLenderSignatureBSS,
            borrower_signature=LoanAgreementBorrowerSignatureBSS,
        )

    if application.is_julover():
        return _template_return(
            template,
            agreement_type,
            lender_signature=JuloverLoanAgreementLenderSignature,
            borrower_signature=JuloverLoanAgreementBorrowerSignature,
        )

    if application.is_mf_web_app_flow():
        return _template_return(
            template,
            agreement_type,
            lender_signature=LoanAgreementLenderSignatureAxiataWeb,
            borrower_signature=LoanAgreementBorrowerSignatureAxiataWeb,
        )

    return _template_return(template, agreement_type)


def get_loan_agreement_type(loan_xid):
    try:
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if loan and loan.account:
            return {
                "type": 'skrtp',
                "text": 'Surat Konfirmasi Rincian Transaksi Pendanaan',
            }
    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.info({
            'action': 'juloserver.loan.views_related.get_loan_agreement_type',
            'loan_xid': loan_xid,
            'error_message': str(e)

        })
    return {
        "type": 'sphp',
        "text": 'Surat Perjanjian Hutang Piutang',
    }


def get_master_agreement(application_id):
    return Document.objects.filter(
        document_type="master_agreement",
        document_source=application_id
    ).last()


def get_loan_agreement_template_julo_one(
    loan_id, type="android", is_simulation=False, loan_duration=None, is_new_digisign=False
):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None, "sphp"

    account = loan.account
    if not account:
        return None, "sphp"

    application = loan.get_application
    if not application:
        return None, "sphp"

    if loan.is_qris_1_product:
        return get_qris_skrtp_agreement_html(loan, application), "skrtp"

    if application.partner:
        if application.partner.name == PartnerConstant.GOSEL:
            return get_gosel_loan_agreement_template(loan, application), "skrtp"

    if application.is_grab():
        return get_sphp_template_grab(loan.id), "sphp"

    if application.is_dana_flow():
        return get_dana_loan_agreement_template(loan), "skrtp"

    if application.is_mf_web_app_flow():
        if application.partner.name in (
            PartnerConstant.AXIATA_PARTNER,
            PartnerConstant.AXIATA_PARTNER_SCF,
            PartnerConstant.AXIATA_PARTNER_IF,
            PartnerNameConstant.AXIATA_WEB,
        ):
            return get_axiata_loan_agreement_template(loan, application, is_new_digisign), "skrtp"
        else:
            return get_mf_std_loan_agreement_template(loan, application), "skrtp"

    if application.is_julover():
        return get_sphp_template_julo_one(
            loan.id, type="android", is_new_digisign=is_new_digisign
        ), "sphp"

    return (
        get_skrtp_template_julo_one(
            loan, account, application, None, is_simulation, loan_duration,
            is_new_digisign=is_new_digisign
        ),
        "skrtp"
    )


def get_skrtp_template_julo_one(loan, account, application, master_agreement,
                                is_simulation=False, loan_duration=None, is_new_digisign=False):
    if not loan or not account or not application:
        return

    account_limit = account.get_account_limit
    if not account_limit:
        return

    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    loan_amount = display_rupiah_skrtp(loan.loan_amount)
    if is_simulation and loan_duration:
        readjusted_loan_amount = readjusted_loan_amount_by_max_fee_rule(loan, loan_duration)
        payments = generate_new_payments(loan_duration, loan)
        loan_amount = display_rupiah_skrtp(readjusted_loan_amount)
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah_skrtp(payment.due_amount + payment.paid_amount)

    _, interest_fee_monthly, _ = compute_payment_installment_julo_one(
        loan.loan_amount, loan.loan_duration, loan.interest_rate_monthly
    )
    julo_bank_code = '-'
    payment_method_name = '-'
    payment_method = PaymentMethod.objects.filter(
        virtual_account=loan.julo_bank_account_number
    ).first()
    if payment_method:
        julo_bank_code = payment_method.bank_code
        payment_method_name = payment_method.payment_method_name

    # esign amount
    digisign_fee = loan.get_digisign_and_registration_fee()

    # sphp_accepted_ts for SMF
    sphp_accepted_ts = None
    if loan.sphp_accepted_ts:
        sphp_accepted_ts = timezone.localtime(loan.sphp_accepted_ts).strftime("%b %d, %Y %H:%M:%S")

    context = {
        'loan': loan,
        'application': application,
        'payments': payments,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'loan_amount': loan_amount,
        'late_fee_amount': display_rupiah_skrtp(loan.late_fee_amount),
        'max_total_late_fee_amount': display_rupiah_skrtp(loan.max_total_late_fee_amount),
        'provision_fee_amount': display_rupiah_skrtp(loan.provision_fee()),
        'loan_tax_amount': display_rupiah_skrtp(loan.get_loan_tax_fee()),
        'interest_fee_monthly': display_rupiah_skrtp(interest_fee_monthly),
        'disbursement_fee': display_rupiah_skrtp(loan.disbursement_fee),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': julo_bank_code,
        'payment_method_name': payment_method_name,
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_date(
            timezone.localtime(loan.sphp_sent_ts), 'd MMMM yyyy', locale='id_ID'
        ),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'loan_type': get_loan_type_sphp_content(loan),
        'hash_master_agreement': '-',
        'available_limit': display_rupiah_skrtp(account_limit.set_limit),
        'company_name': '',
        'poc_name': '',
        'poc_position': '',
        'license_number': '',
        'lender_address': '',
        'lender_signature_name': '',
        'is_new_digisign': is_new_digisign,
        'e_sign_amount': display_rupiah_skrtp(loan.get_loan_digisign_fee()),
        'digisign_fee': display_rupiah_skrtp(digisign_fee),
        'sphp_accepted_ts': sphp_accepted_ts,
    }

    if is_new_digisign:
        context['signature'] = ''
    else:
        signature = get_manual_signature(loan)
        context['signature'] = signature.get('thumbnail_url_api', '') if signature else ''

    lender = loan.lender
    if lender:
        context.update(
            {
                'company_name': lender.company_name,
                'poc_name': lender.poc_name,
                'poc_position': lender.poc_position,
                'license_number': lender.license_number,
                'lender_address': lender.lender_address,
                'lender_signature_name': lender.poc_name,
            }
        )

    # lenders area will be empty if loan is rejected
    if loan.loan_status_id == LoanStatusCodes.LENDER_REJECT:
        context.update(
            {
                'company_name': '',
                'poc_name': '',
                'poc_position': '',
                'license_number': '',
                'lender_address': '',
                'lender_signature_name': '',
            }
        )

    if is_simulation:
        context['lender_signature_name'] = ''

    template = LoanAgreementTemplate.objects.get_or_none(
        lender=lender, is_active=True, agreement_type=LoanAgreementType.SKRTP
    )

    if not template:
        template = LoanAgreementTemplate.objects.get_or_none(
            lender=None, is_active=True, agreement_type=LoanAgreementType.SKRTP
        )

    if not template:
        return render_to_string('loan_agreement/julo_one_skrtp.html', context=context)

    return Template(template.body).render(Context(context))


def get_riplay_template_julo_one(loan: Loan) -> str:
    customer = loan.customer
    payments = loan.payment_set.normal().order_by('payment_number')
    total_due_amount = 0
    last_due_date = None

    for payment in payments:
        # total_due_amount can also be loan.loan_amount
        due_amount = payment.installment_interest + payment.installment_principal
        total_due_amount += due_amount

        payment.display_due_date = convert_payment_number_to_word(payment.payment_number)
        payment.due_amount = display_rupiah_skrtp(due_amount)

        payment.installment_interest = display_rupiah_skrtp(payment.installment_interest)
        payment.installment_principal = display_rupiah_skrtp(payment.installment_principal)

        if payment.payment_number == len(payments):
            last_due_date = format_date(payment.due_date, 'dd-MM-yyyy', locale='id_ID')

    context = {
        'full_name': customer.fullname,
        'display_transaction_method': loan.transaction_method.fe_display_name,
        'loan_amount': display_rupiah_skrtp(loan.loan_amount),
        'last_due_date': last_due_date,
        'interest_rate_monthly': display_percent_from_float_type(loan.interest_rate_monthly),
        'loan_duration': loan.loan_duration,
        'loan_installment_amount': display_rupiah_skrtp(loan.installment_amount),
        'late_fee_rate_per_day': "{}% per hari".format(loan.late_fee_rate_per_day),
        'provision_fee_amount': display_rupiah_skrtp(loan.provision_fee()),
        'additional_fee': display_rupiah_skrtp(0),
        'provision_rate': display_percent_from_float_type(loan.provision_rate),
        'loan_disbursement_amount': display_rupiah_skrtp(loan.loan_disbursement_amount),
        'payments': payments,
        'total_due_amount': display_rupiah_skrtp(total_due_amount),
        'loan_type': get_loan_type_sphp_content(loan),
        'company_name': '',
    }

    lender = loan.lender
    if lender:
        context.update({'company_name': lender.company_name})

    template = LoanAgreementTemplate.objects.get_or_none(
        lender=lender, is_active=True, agreement_type=LoanAgreementType.RIPLAY
    )
    if not template:
        template = LoanAgreementTemplate.objects.get_or_none(
            lender=None, is_active=True, agreement_type=LoanAgreementType.RIPLAY
        )
    if not template:
        return render_to_string('loan_agreement/julo_one_riplay.html', context=context)

    return Template(template.body).render(Context(context))


def get_text_agreement_by_document_type(loan: Loan, document_type):
    if document_type == LoanAgreementType.SKRTP:
        text_agreement, _ = get_loan_agreement_template_julo_one(loan.id)
        extension_type = LoanAgreementExtensionType.HTML
    elif document_type == LoanAgreementType.DIGISIGN_SKRTP:
        success_digisign = get_digisign_document_success(loan.id)
        text_agreement = success_digisign.download_url
        extension_type = LoanAgreementExtensionType.PDF
    else:
        text_agreement = get_riplay_template_julo_one(loan)
        extension_type = LoanAgreementExtensionType.HTML

    return text_agreement, extension_type

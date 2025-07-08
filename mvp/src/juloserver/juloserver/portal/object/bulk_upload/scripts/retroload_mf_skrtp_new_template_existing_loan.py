import os
import tempfile
import pdfkit
import logging

from babel.dates import format_date, format_datetime
from django.conf import settings
from django.db import connection
from django.db.models import F, Prefetch
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.account.models import AccountLimit
from juloserver.integapiv1.models import EscrowPaymentMethod
from juloserver.julo.models import (
    Application,
    Document,
    Loan,
    PaymentMethod,
    SphpTemplate,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tasks import upload_document

from juloserver.julo.utils import display_rupiah

from juloserver.julocore.python2.utils import py2round

from juloserver.partnership.constants import (
    PartnershipFundingFacilities,
    PartnershipProductCategory,
    CARD_ID_METABASE_AXIATA_DISTRIBUTOR,
)

from juloserver.portal.object.bulk_upload.constants import (
    MerchantFinancingCSVUploadPartner, MerchantFinancingSKRTPNewTemplate,
)
from juloserver.sdk.models import AxiataCustomerData
from juloserver.metabase.clients import get_metabase_client
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)

'''
    This logic is for create new MF skrtp template for existing active loan
'''


def get_new_mf_skrtp_content(loan):
    max_limit_amount = 0
    available_limit_amount = 0
    residual_credit_limit_amount = 0

    html_template = loan.html_template
    if not html_template:
        return None

    template = Template(html_template.sphp_template)

    value = loan.product.late_fee_pct * loan.installment_amount
    late_fee_amount = py2round(value if value > 55000 else 55000, -2)
    payment = loan.payment_set.last()
    product_line_id = payment.loan.product.product_line_id
    pl_manual_process_and_rabando = ProductLineCodes.manual_process() + [ProductLineCodes.RABANDO]
    if product_line_id in pl_manual_process_and_rabando:
        late_fee_amount = payment.calculate_late_fee_productive_loan(product_line_id)

    today = timezone.localtime(timezone.now()).date()
    partner = loan.application.partner
    principal_loan_amount = loan.loan_disbursement_amount

    if loan.account_limit:
        max_limit_amount = loan.account_limit.max_limit
        available_limit_amount = loan.account_limit.max_limit
        residual_credit_limit_amount = loan.account_limit.max_limit - loan.loan_amount

    if partner.name == MerchantFinancingCSVUploadPartner.RABANDO:
        bank_account_destination = loan.bank_account_destination
        account_no = bank_account_destination.account_number
        account_holder_name = bank_account_destination.name_bank_validation.validated_name
        bank_name = bank_account_destination.bank.bank_name
    elif partner.name == PartnerConstant.AXIATA_PARTNER:
        max_limit_amount = loan.loan_amount
        available_limit_amount = loan.loan_amount
        principal_loan_amount = loan.loan_amount

        account_no = loan.axiata_distributor['account_no']
        account_holder_name = loan.axiata_distributor['account_holder_name']
        bank_name = loan.axiata_distributor['bank_name']
    else:
        account_no = partner.partner_bank_account_number
        account_holder_name = partner.partner_bank_account_name
        bank_name = partner.partner_bank_name

    if payment.installment_interest:
        monthly_interest_amount = payment.installment_interest - loan.provision_fee()
        provision_fee_amount = loan.provision_fee()
    else:
        monthly_interest_amount = payment.installment_interest
        provision_fee_amount = payment.installment_interest

    # for axiata MTL, replace monthly_interest and provision fee
    if partner.name == PartnerConstant.AXIATA_PARTNER:
        monthly_interest_amount = payment.installment_interest
        provision_fee_amount = loan.provision_fee()
    param = {
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'loan_xid': loan.loan_xid,
        'loan_date': format_date(loan.cdate, 'dd-MM-yyyy', locale='id_ID'),
        'application_xid': loan.application.application_xid,
        'application_x190_date': format_date(loan.application.cdate, 'dd-MM-yyyy', locale='id_ID'),
        'fullname': loan.application.fullname,
        'loan_amount': loan.loan_amount,
        'provision_fee_amount': display_rupiah(provision_fee_amount),
        'late_fee_amount': display_rupiah(late_fee_amount),
        'total_late_fee_amount': display_rupiah(loan.loan_amount),
        'date_today': format_datetime(today, "d MMMM yyyy", locale='id_ID'),
        'customer_name': loan.application.fullname,
        'customer_phone': loan.application.mobile_phone_1,
        'customer_nik': loan.application.ktp,
        'dob': format_datetime(loan.application.dob, "d MMMM yyyy", locale='id_ID'),
        'full_address': loan.application.full_address,
        'legal_entity_partner': loan.application.partner.company_name,
        'pic_email': loan.application.partner.email,
        'max_limit_amount': display_rupiah(max_limit_amount),
        'available_limit_amount': display_rupiah(available_limit_amount),
        'principal_loan_amount': display_rupiah(principal_loan_amount),
        'residual_credit_limit_amount': display_rupiah(residual_credit_limit_amount),
        'maturity_date': format_datetime(payment.due_date, "d MMMM yyyy", locale='id_ID'),
        'account_no': account_no,
        'account_holder_name': account_holder_name,
        'bank_name': bank_name,
        'monthly_interest_amount': display_rupiah(monthly_interest_amount),
    }

    payments = loan.payment_set.all().order_by('id')
    total_interest = sum(payment.installment_interest for payment in payments)
    total_principal = sum(payment.installment_principal for payment in payments)

    total_payment_amount = total_interest + total_principal
    param.update(
        {
            'total_payment_amount': display_rupiah(total_payment_amount),
        }
    )

    if hasattr(loan, 'escrow_payment_method') and loan.escrow_payment_method:
        param.update(
            {
                'bank_code': loan.escrow_payment_method.escrow_payment_method_lookup.payment_method_name,
                'va_number': loan.escrow_payment_method.virtual_account,
            }
        )
    else:
        param.update(
            {
                'bank_code': loan.payment_method.bank_code,
                'va_number': loan.payment_method.virtual_account,
            }
        )

    if loan.application.partner.name == MerchantFinancingCSVUploadPartner.GAJIGESA:
        param.update(
            {
                'funding_facilities': PartnershipFundingFacilities.EMPLOYEE_FINANCING
            }
        )
    else:
        param.update(
            {
                'funding_facilities': PartnershipFundingFacilities.SUPPLY_CHAIN_FINANCING
            }
        )

    lender = loan.lender
    if lender:
        param.update(
            {
                'poc_name': lender.poc_name,
                'poc_position': lender.poc_position,
                'license_number': lender.license_number,
                'lender_address': lender.lender_address,
                'lender_company_name': lender.company_name,
                'lender_signature_name': lender.poc_name,
            }
        )

    if loan.application.partner.name in {
        PartnerConstant.AXIATA_PARTNER,
        MerchantFinancingCSVUploadPartner.RABANDO
    }:
        param.update(
            {
                'mitra_or_receiver': PartnershipFundingFacilities.PENERIMA_DANA
            }
        )
    else:
        param.update(
            {
                'mitra_or_receiver': PartnershipFundingFacilities.MITRA_BISNIS
            }
        )

    context_obj = Context(param)
    if loan.application.partner == MerchantFinancingCSVUploadPartner.BUKUWARUNG:
        template = 'sphp_pilot_bukuwarung_disbursement_upload_template.html'
        sphp_template = render_to_string(f'{template}', context=context_obj)
        return sphp_template
    else:
        content_skrtp = template.render(context_obj)
        return content_skrtp


def create_new_mf_skrtp(loans):
    errors = []

    for loan in loans:
        try:
            MerchantFinancingSKRTPNewTemplate.append(PartnerConstant.AXIATA_PARTNER)
            if loan.application.partner.name in MerchantFinancingSKRTPNewTemplate:
                if (
                    loan.application.partner.name != PartnerConstant.AXIATA_PARTNER
                    and not loan.application.account
                ):
                    errors.append("Account data not found for loan ID {}".format(loan.id))
                    continue
                partner_name = loan.application.partner.name
                application = loan.application
                template = get_new_mf_skrtp_content(loan)
                if not template:
                    errors.append("SKRTP template not found for loan ID {}".format(loan.id))
                    continue

                now = timezone.localtime(timezone.now()).date()
                filename = '{}_{}_{}_{}.pdf'.format(
                    application.fullname,
                    loan.loan_xid,
                    now.strftime("%Y%m%d"),
                    now.strftime("%H%M%S"),
                )
                file_path = os.path.join(tempfile.gettempdir(), filename)

                try:
                    pdfkit.from_string(template, file_path)
                except Exception:
                    errors.append("Failed to create PDF for loan ID {}".format(loan.id))
                    continue

                sphp_julo = Document.objects.create(
                    document_source=loan.id,
                    document_type=f"{partner_name.lower()}_skrtp",
                    filename=filename,
                    loan_xid=loan.loan_xid,
                )
                upload_document(sphp_julo.id, file_path, is_loan=True)
        except Exception as e:
            errors.append("Error processing loan ID {}: {}".format(loan.id, str(e)))

    return errors


def batching_loans(loan_ids):
    batch_size = 500
    counter = 0
    batch_loan_ids = []

    for loan_id in loan_ids:
        batch_loan_ids.append(loan_id)
        counter += 1

        if counter >= batch_size:
            loans = get_loans_info(loan_ids)

            counter = 0
            batch_loan_ids = []
            temp_errors = create_new_mf_skrtp(loans)

    if batch_loan_ids:
        loans = get_loans_info(loan_ids)
        temp_errors = create_new_mf_skrtp(loans)

    return temp_errors


def get_loans_info(loan_ids):
    loans = Loan.objects.select_related('customer', 'lender', 'product').filter(id__in=loan_ids)
    loans = loans.prefetch_related('payment_set')

    customer_ids = [loan.customer_id for loan in loans]

    applications = (
        Application.objects.filter(customer_id__in=customer_ids)
        .select_related('customer', 'account', 'partner')
        .prefetch_related(
            Prefetch('account__accountlimit_set', queryset=AccountLimit.objects.distinct()),
        )
    )

    application_dict = {application.customer_id: application for application in applications}

    julo_bank_account_numbers = [loan.julo_bank_account_number for loan in loans]

    payment_methods = PaymentMethod.objects.filter(virtual_account__in=julo_bank_account_numbers)

    payment_method_dict = {payment.virtual_account: payment for payment in payment_methods}

    unique_partner_names = set(
        application.partner.name for application in applications if application.partner
    )
    escrow_payment_methods = {}
    unique_product_templates = {}

    for partner_name in unique_partner_names:
        if partner_name == MerchantFinancingCSVUploadPartner.GAJIGESA:
            product_name = PartnershipProductCategory.EMPLOYEE_FINANCING
        else:
            product_name = PartnershipProductCategory.MERCHANT_FINANCING
        escrow_payment_method = (
            EscrowPaymentMethod.objects.filter(escrow_payment_gateway__owner__iexact=partner_name)
            .select_related('escrow_payment_gateway', 'escrow_payment_method_lookup')
            .last()
        )
        escrow_payment_methods[partner_name] = escrow_payment_method

        html_template = SphpTemplate.objects.filter(product_name=product_name).last()
        unique_product_templates[partner_name] = html_template

    axiata_customer_data_dict = {}
    axiata_distributor_data_dict = {}
    if PartnerConstant.AXIATA_PARTNER in unique_partner_names:
        axiata_customer_data = AxiataCustomerData.objects.filter(
            application_id__in=[application.id for application in applications]
        )
        for data in axiata_customer_data:
            axiata_customer_data_dict[data.application_id] = data

        distributor_ids = [data.distributor for data in axiata_customer_data]
        distributor_set = set(distributor_ids)
        try:
            metabase_client = get_metabase_client()
            response, error = metabase_client.get_metabase_data_json(
                CARD_ID_METABASE_AXIATA_DISTRIBUTOR
            )
            if error:
                raise Exception(error)

            for res in response:
                if str(res['distributor_id']) in distributor_set:
                    axiata_distributor_data_dict[res['axiata_distributor_id']] = res

        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.capture_exceptions()
            logger.exception(
                {
                    'module': 'get_loans_info',
                    'action': 'get_metabase_data_json',
                    'error': e,
                }
            )

            return

    detail_axiata_distributor_data = None
    for loan in loans:
        application = application_dict.get(loan.customer_id)
        if application:
            loan.application = application

            if application.partner:
                partner_name = application.partner.name
                if partner_name in unique_partner_names:
                    loan.html_template = unique_product_templates[partner_name]
                    loan.escrow_payment_method = escrow_payment_methods[partner_name]
                    loan.payment_method = payment_method_dict.get(loan.julo_bank_account_number)
                else:
                    loan.html_template = None
                    loan.escrow_payment_method = None
                    loan.payment_method = None

                if partner_name == PartnerConstant.AXIATA_PARTNER:
                    axiata_customer_data = axiata_customer_data_dict.get(application.id)
                    if axiata_customer_data:
                        for key, value in axiata_distributor_data_dict.items():
                            if value['distributor_id'] == int(axiata_customer_data.distributor):
                                detail_axiata_distributor_data = value
                        if detail_axiata_distributor_data:
                            axiata_distributor = {
                                'account_no': detail_axiata_distributor_data[
                                    'distributor_bank_account'
                                ],
                                'account_holder_name': detail_axiata_distributor_data[
                                    'distributor_bank_account_name'
                                ],
                                'bank_name': detail_axiata_distributor_data['bank_name'],
                            }
                            loan.axiata_distributor = axiata_distributor
                        else:
                            loan.axiata_distributor = None
                    else:
                        loan.axiata_distributor = None

            # Set last_payment
            loan.last_payment = loan.payment_set.last()

            account = application.account
            if account:
                loan.account_limit = account.accountlimit_set.last()
            else:
                loan.account_limit = None
        else:
            # if not have applications
            loan.applications = None
            loan.html_template = None
            loan.payment_method = None
            loan.last_payment = None

    return loans

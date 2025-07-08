import logging

from babel.dates import format_date, format_datetime, get_day_names
from django.conf import settings
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone

from juloserver.integapiv1.models import EscrowPaymentMethod
from juloserver.julo.models import (
    PaymentMethod,
    SphpTemplate,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.partners import PartnerConstant
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.julo.utils import display_rupiah

from juloserver.julocore.python2.utils import py2round

from juloserver.partnership.constants import (
    PartnershipFundingFacilities,
    PartnershipProductCategory,
    CARD_ID_METABASE_AXIATA_DISTRIBUTOR,
    PartnershipLender,
)
from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from juloserver.pii_vault.constants import PiiSource

from juloserver.portal.object.bulk_upload.constants import (
    MerchantFinancingCSVUploadPartner,
)
from juloserver.sdk.models import AxiataCustomerData
from juloserver.metabase.clients import get_metabase_client
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)

def get_mf_skrtp_content(application, loan, account_limit=None):
    account_no = ""
    account_holder_name = ""
    bank_name = ""
    max_limit_amount = 0
    residual_credit_limit_amount = 0
    available_limit_amount = 0

    partner = application.partner
    if partner.name == MerchantFinancingCSVUploadPartner.GAJIGESA:
        product_name = PartnershipProductCategory.EMPLOYEE_FINANCING
    else:
        product_name = PartnershipProductCategory.MERCHANT_FINANCING

    html_template = SphpTemplate.objects.filter(product_name=product_name).last()
    if not html_template:
        return None

    template = Template(html_template.sphp_template)

    if account_limit:
        max_limit_amount = account_limit.max_limit
        residual_credit_limit_amount = account_limit.available_limit
        available_limit_amount = account_limit.available_limit + loan.loan_amount

    value = loan.product.late_fee_pct * loan.installment_amount
    late_fee_amount = py2round(value if value > 55000 else 55000, -2)
    payment = loan.payment_set.last()
    product_line_id = payment.loan.product.product_line_id
    pl_manual_process_and_rabando = ProductLineCodes.manual_process() + [ProductLineCodes.RABANDO]
    if product_line_id in pl_manual_process_and_rabando:
        late_fee_amount = payment.calculate_late_fee_productive_loan(product_line_id)

    today = timezone.localtime(timezone.now()).date()

    principal_loan_amount = loan.loan_disbursement_amount
    if partner.name == MerchantFinancingCSVUploadPartner.RABANDO:
        bank_account_destination = loan.bank_account_destination
        account_no = bank_account_destination.account_number
        account_holder_name = bank_account_destination.name_bank_validation.validated_name
        bank_name = bank_account_destination.bank.bank_name
    elif partner.name == PartnerConstant.AXIATA_PARTNER:
        max_limit_amount = loan.loan_amount
        available_limit_amount = loan.loan_amount
        principal_loan_amount = loan.loan_amount

        axiata_customer_data = AxiataCustomerData.objects.filter(
            application_id=application.id
        ).last()
        if axiata_customer_data and axiata_customer_data.distributor:
            axiata_distributor = None

            try:
                metabase_client = get_metabase_client()
                response, error = metabase_client.get_metabase_data_json(
                    CARD_ID_METABASE_AXIATA_DISTRIBUTOR
                )
                if error:
                    raise Exception(error)

                for res in response:
                    if str(res['distributor_id']) == axiata_customer_data.distributor:
                        axiata_distributor = res

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

            if axiata_distributor:
                account_no = axiata_distributor['distributor_bank_account']
                account_holder_name = axiata_distributor['distributor_bank_account_name']
                bank_name = axiata_distributor['bank_name']

    else:
        account_no = partner.partner_bank_account_number
        account_holder_name = partner.partner_bank_account_name
        bank_name = partner.partner_bank_name

    monthly_interest_amount = payment.installment_interest - loan.provision_fee()
    param = {
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'loan_xid': loan.loan_xid,
        'loan_date': format_date(loan.cdate, 'dd-MM-yyyy', locale='id_ID'),
        'application_xid': application.application_xid,
        'application_x190_date': format_date(
            application.cdate, 'dd-MM-yyyy', locale='id_ID'),
        'fullname': application.fullname,
        'loan_amount': loan.loan_amount,
        'available_limit': display_rupiah(loan.account.accountlimit_set.last().available_limit),
        'provision_fee_amount': display_rupiah(loan.provision_fee()),
        'interest_rate_in_pct': '{}%'.format(loan.interest_percent_monthly()),
        'late_fee_amount': display_rupiah(late_fee_amount),
        'total_late_fee_amount': display_rupiah(loan.loan_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
        'date_today': format_datetime(today, "d MMMM yyyy", locale='id_ID'),
        'customer_name': application.fullname,
        'customer_phone': application.mobile_phone_1,
        'customer_nik': application.ktp,
        'dob': format_datetime(application.dob, "d MMMM yyyy", locale='id_ID'),
        'full_address': application.full_address,
        'legal_entity_partner': partner.company_name,
        'pic_email': partner.email,
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

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number).first()
        if payment_method:
            param['julo_bank_code'] = payment_method.bank_code
    payments = loan.payment_set.all().order_by('id')
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
    param['payments'] = payments

    total_interest = sum(payment.installment_interest for payment in payments)
    total_principal = sum(payment.installment_principal for payment in payments)

    total_payment_amount = total_interest + total_principal
    param.update(
        {
            'total_payment_amount': display_rupiah(total_payment_amount),
        }
    )

    efishery_partner_set = set()
    for attribute_name in dir(MerchantFinancingCSVUploadPartner):
        if not attribute_name.startswith(
                "__"
        ) and MerchantFinancingCSVUploadPartner.EFISHERY in attribute_name.lower():
            attribute_value = getattr(MerchantFinancingCSVUploadPartner, attribute_name)
            efishery_partner_set.add(attribute_value)

    partner_set = {
        MerchantFinancingCSVUploadPartner.AGRARI,
        MerchantFinancingCSVUploadPartner.GAJIGESA,
    }
    partner_set.update(efishery_partner_set)
    if partner.name in partner_set:
        partner_name = partner.name
        if partner.name in efishery_partner_set:
            partner_name = MerchantFinancingCSVUploadPartner.EFISHERY
        escrow_payment_method = EscrowPaymentMethod.objects.filter(
            escrow_payment_gateway__owner__iexact=partner_name
        ).select_related(
            'escrow_payment_gateway', 'escrow_payment_method_lookup'
        ).last()
        if escrow_payment_method:
            param.update(
                {
                    'bank_code': escrow_payment_method.escrow_payment_method_lookup.payment_method_name,
                    'va_number': escrow_payment_method.virtual_account,
                }
            )
    else:
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number).first()
        if payment_method:
            param.update(
                {
                    'bank_code': payment_method.bank_code,
                    'va_number': payment_method.virtual_account,
                }
            )

    if partner.name == MerchantFinancingCSVUploadPartner.GAJIGESA:
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

    if partner.name in {
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
    if application.partner == MerchantFinancingCSVUploadPartner.BUKUWARUNG:
        template = 'sphp_pilot_bukuwarung_disbursement_upload_template.html'
        sphp_template = render_to_string(f'{template}', context=context_obj)
        return sphp_template
    else:
        content_skrtp = template.render(context_obj)
        return content_skrtp


def get_mf_std_skrtp_content(
    loan,
    application,
    partner_loan_request,
    product_lookup,
    application_dicts,
    account_limit=None,
):
    account_no = ""
    account_holder_name = ""
    bank_name = ""
    max_limit_amount = 0
    residual_credit_limit_amount = 0
    available_limit_amount = 0

    lender = loan.lender
    lender_name = getattr(lender, "lender_name", None)

    partner = application.partner
    if (
        partner.name
        in (
            MerchantFinancingCSVUploadPartner.EFISHERY,
            MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
        )
        and lender_name != PartnershipLender.JTP
    ):
        product_name = PartnershipProductCategory.MF_EFISHERY_NEW
    else:
        product_name = PartnershipProductCategory.MERCHANT_FINANCING

    html_template = SphpTemplate.objects.filter(product_name=product_name).last()
    if not html_template:
        return None

    template = Template(html_template.sphp_template)

    if account_limit:
        max_limit_amount = account_limit.max_limit
        residual_credit_limit_amount = account_limit.available_limit
        available_limit_amount = account_limit.available_limit + loan.loan_amount

    value = product_lookup.late_fee_pct * loan.installment_amount
    late_fee_amount = py2round(value if value > 55000 else 55000, -2)
    payment = loan.payment_set.last()
    product_line_id = product_lookup.product_line_id
    pl_manual_process_and_rabando = ProductLineCodes.manual_process() + [ProductLineCodes.RABANDO]
    if product_line_id in pl_manual_process_and_rabando:
        late_fee_amount = payment.calculate_late_fee_productive_loan(product_line_id)

    today = timezone.localtime(timezone.now()).date()

    principal_loan_amount = loan.loan_disbursement_amount
    if partner.name == MerchantFinancingCSVUploadPartner.RABANDO:
        bank_account_destination = loan.bank_account_destination
        account_no = bank_account_destination.account_number
        account_holder_name = bank_account_destination.name_bank_validation.validated_name
        bank_name = bank_account_destination.bank.bank_name
    elif partner.name in (
        PartnerConstant.AXIATA_PARTNER,
        PartnerConstant.AXIATA_PARTNER_SCF,
        PartnerConstant.AXIATA_PARTNER_IF,
        PartnerNameConstant.AXIATA_WEB,
    ):
        max_limit_amount = loan.loan_amount
        available_limit_amount = loan.loan_amount
        principal_loan_amount = loan.loan_amount

        axiata_customer_data = AxiataCustomerData.objects.filter(
            application_id=application.id
        ).last()
        if axiata_customer_data and axiata_customer_data.distributor:
            axiata_distributor = None

            try:
                metabase_client = get_metabase_client()
                response, error = metabase_client.get_metabase_data_json(
                    CARD_ID_METABASE_AXIATA_DISTRIBUTOR
                )
                if error:
                    raise Exception(error)

                for res in response:
                    if str(res["distributor_id"]) == axiata_customer_data.distributor:
                        axiata_distributor = res

            except Exception as e:
                sentry_client = get_julo_sentry_client()
                sentry_client.capture_exceptions()
                logger.exception(
                    {
                        "module": "get_mf_std_skrtp_content",
                        "action": "get_mf_std_skrtp_content",
                        "error": e,
                    }
                )

                return

            if axiata_distributor:
                account_no = axiata_distributor["distributor_bank_account"]
                account_holder_name = axiata_distributor["distributor_bank_account_name"]
                bank_name = axiata_distributor["bank_name"]

    else:
        bank_account_destination = loan.bank_account_destination

        account_no = bank_account_destination.account_number
        account_holder_name = bank_account_destination.name_bank_validation.validated_name
        bank_name = bank_account_destination.bank.bank_name

    customer_xid = application.customer.customer_xid
    detokenize_application = partnership_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        customer_xid,
        ['fullname'],
    )

    partnership_customer_data = application.partnership_customer_data
    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        customer_xid,
        ['phone_number', 'nik'],
    )

    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid,
        ['email'],
    )

    param = {
        "julo_image": settings.SPHP_STATIC_FILE_PATH + "scraoe-copy-3@3x.png",
        "loan_xid": loan.loan_xid,
        "loan_date": format_date(loan.cdate, "dd-MM-yyyy", locale="id_ID"),
        "loan_day": get_day_names("wide", locale="id_ID")[loan.cdate.weekday()],
        "loan_date_in_words": format_date(loan.cdate, "d MMMM yyyy", locale="id_ID"),
        "application_xid": application.application_xid,
        "application_x190_date": format_date(application.cdate, "dd-MM-yyyy", locale="id_ID"),
        "fullname": detokenize_application.fullname,
        "loan_amount": loan.loan_amount,
        "available_limit": display_rupiah(loan.account.accountlimit_set.last().available_limit),
        "provision_fee_amount": display_rupiah(loan.provision_fee()),
        "interest_rate_in_pct": "{}%".format(loan.interest_percent_monthly()),
        "late_fee_amount": display_rupiah(late_fee_amount),
        "total_late_fee_amount": display_rupiah(loan.loan_amount),
        "julo_bank_name": loan.julo_bank_name,
        "julo_bank_code": "-",
        "julo_bank_account_number": loan.julo_bank_account_number,
        "date_today": format_datetime(today, "d MMMM yyyy", locale="id_ID"),
        "customer_name": detokenize_application.fullname,
        "customer_phone": detokenize_partnership_customer_data.phone_number,
        "customer_nik": detokenize_partnership_customer_data.nik,
        "dob": format_datetime(application.dob, "d MMMM yyyy", locale="id_ID"),
        "full_address": application.full_address,
        "legal_entity_partner": partner.company_name,
        "pic_email": detokenize_partner.email,
        "max_limit_amount": display_rupiah(max_limit_amount),
        "available_limit_amount": display_rupiah(available_limit_amount),
        "principal_loan_amount": display_rupiah(principal_loan_amount),
        "residual_credit_limit_amount": display_rupiah(residual_credit_limit_amount),
        "maturity_date": format_datetime(payment.due_date, "d MMMM yyyy", locale="id_ID"),
        "account_no": account_no,
        "account_holder_name": account_holder_name,
        "bank_name": bank_name,
        "nik": detokenize_partnership_customer_data.nik,
        "business_type": application_dicts[partner_loan_request.loan.application_id2][
            "partnership_application_data"
        ]["business_type"],
        "invoice_no": partner_loan_request.invoice_number,
    }

    if "bca" not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number
        ).first()
        if payment_method:
            param["julo_bank_code"] = payment_method.bank_code

    payments = loan.payment_set.all().order_by("id")

    for payment in payments:
        payment.due_date = format_date(payment.due_date, "d MMM yy", locale="id_ID")
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)

    param["payments"] = payments

    total_interest = sum(payment.installment_interest for payment in payments)
    total_principal = sum(payment.installment_principal for payment in payments)

    total_payment_amount = total_interest + total_principal
    monthly_interest_amount = total_interest - loan.provision_fee()

    param.update(
        {
            "total_payment_amount": display_rupiah(total_payment_amount),
            "monthly_interest_amount": display_rupiah(monthly_interest_amount),
        }
    )

    efishery_partner_set = set()
    for attribute_name in dir(MerchantFinancingCSVUploadPartner):
        if (
            not attribute_name.startswith("__")
            and MerchantFinancingCSVUploadPartner.EFISHERY in attribute_name.lower()
        ):
            attribute_value = getattr(MerchantFinancingCSVUploadPartner, attribute_name)
            efishery_partner_set.add(attribute_value)

    partner_set = {
        MerchantFinancingCSVUploadPartner.AGRARI,
        MerchantFinancingCSVUploadPartner.GAJIGESA,
    }
    partner_set.update(efishery_partner_set)
    if partner.name in partner_set:
        partner_name = partner.name
        if partner.name in efishery_partner_set:
            partner_name = MerchantFinancingCSVUploadPartner.EFISHERY
        escrow_payment_method = (
            EscrowPaymentMethod.objects.filter(escrow_payment_gateway__owner__iexact=partner_name)
            .select_related("escrow_payment_gateway", "escrow_payment_method_lookup")
            .last()
        )
        if escrow_payment_method:
            param.update(
                {
                    "bank_code": escrow_payment_method.escrow_payment_method_lookup.payment_method_name,
                    "va_number": escrow_payment_method.virtual_account,
                }
            )
    else:
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number
        ).first()
        if payment_method:
            param.update(
                {
                    "bank_code": payment_method.bank_code,
                    "va_number": payment_method.virtual_account,
                }
            )

    if partner.name == MerchantFinancingCSVUploadPartner.GAJIGESA:
        param.update({"funding_facilities": PartnershipFundingFacilities.EMPLOYEE_FINANCING})
    else:
        param.update({"funding_facilities": PartnershipFundingFacilities.SUPPLY_CHAIN_FINANCING})

    if lender:
        param.update(
            {
                "poc_name": lender.poc_name,
                "poc_position": lender.poc_position,
                "license_number": lender.license_number,
                "lender_address": lender.lender_address,
                "lender_company_name": lender.company_name,
            }
        )

    if loan.loan_status_id >= LoanStatusCodes.LENDER_APPROVAL:
        param.update(
            {
                "customer_signature_name": detokenize_application.fullname,
            }
        )

    if loan.loan_status_id >= LoanStatusCodes.FUND_DISBURSAL_ONGOING:
        param.update(
            {
                "lender_signature_name": lender.poc_name,
            }
        )

    if partner.name in {PartnerConstant.AXIATA_PARTNER, MerchantFinancingCSVUploadPartner.RABANDO}:
        param.update({"mitra_or_receiver": PartnershipFundingFacilities.PENERIMA_DANA})
    else:
        param.update({"mitra_or_receiver": PartnershipFundingFacilities.MITRA_BISNIS})

    context_obj = Context(param)
    content_skrtp = template.render(context_obj)

    return content_skrtp

from __future__ import division

import logging
import tempfile
import os
import pandas as pd
import urllib.request
import pdfkit

from zipfile import ZipFile
from babel.numbers import format_number
from babel.dates import format_date, format_datetime

from django.conf import settings
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from typing import Dict

from juloserver.loan.utils import get_default_pdf_options
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.channeling_loan.services.general_services import (
    process_loan_for_channeling,
    get_channeling_loan_configuration,
    recalculate_channeling_payment_interest,
    approve_loan_for_channeling,
)
from juloserver.channeling_loan.services.bss_services import (
    change_city_to_dati_code,
    replace_special_chars_for_fields,
)
from juloserver.channeling_loan.models import (
    ChannelingLoanStatus,
)
from juloserver.channeling_loan.constants import (
    ChannelingStatusConst,
    ChannelingConst,
)
from juloserver.channeling_loan.constants.smf_constants import (
    SMFChannelingConst,
    SMFMaritalStatusConst,
    SMFEducationConst,
    SMFDataField,
    SMF_INVOICE_ICON_LINK,
)

from juloserver.customer_module.services.bank_account_related import is_ecommerce_bank_account

from juloserver.disbursement.models import Disbursement

from juloserver.julo.models import (
    Payment,
    Document,
    Loan,
    Image,
    CreditScore,
    SepulsaTransaction,
)

from juloserver.followthemoney.models import LenderBucket

from juloserver.payment_point.constants import SepulsaProductType
from juloserver.payment_point.models import AYCEWalletTransaction

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def generate_smf_disbursement_file(filename, _filter):
    data = {
        "customerdata": [],
        "loandata": [],
        "collateraldata": [],
        "schedule": [],
    }

    channeling_type = ChannelingConst.SMF
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)

    loan_ids = []
    channeling_loan_statuses = (
        ChannelingLoanStatus.objects.filter(**_filter)
        .exclude(channeling_status=ChannelingStatusConst.PREFUND)
        .order_by("-cdate")
    )
    for channeling_loan_status in channeling_loan_statuses:
        loan = channeling_loan_status.loan
        application = loan.get_application
        channeling_loan_status = loan.channelingloanstatus_set.last()
        if channeling_loan_status.channeling_status == ChannelingStatusConst.PENDING:
            status, _ = process_loan_for_channeling(loan)
            if status == "failed":
                continue
            status, _ = approve_loan_for_channeling(
                loan, 'y', channeling_type, channeling_loan_config
            )
            if status == "failed":
                continue
        loan_ids.append(channeling_loan_status.loan_id)

        data["customerdata"].append(construct_smf_customer_data(loan, application))
        data["loandata"].append(construct_smf_loan_data(loan))
        data["collateraldata"].append(construct_smf_collateral_data(loan))
        for schedule in construct_smf_schedule_data(loan):
            data["schedule"].append(schedule)

    file_path = os.path.join(tempfile.gettempdir(), filename)

    df_cust = pd.DataFrame(data["customerdata"], columns=data["customerdata"][0].keys())
    df_loan = pd.DataFrame(data["loandata"], columns=data["loandata"][0].keys())
    df_col = pd.DataFrame(data["collateraldata"], columns=data["collateraldata"][0].keys())
    df_sch = pd.DataFrame(data["schedule"], columns=data["schedule"][0].keys())

    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        df_cust.to_excel(writer, sheet_name='customerdata', index=False)
        df_loan.to_excel(writer, sheet_name='loandata', index=False)
        df_col.to_excel(writer, sheet_name='collateraldata', index=False)
        df_sch.to_excel(writer, sheet_name='schedule', index=False)

    return file_path, loan_ids


def get_smf_refno(loan):
    return "%s%s" % (SMFChannelingConst.PARTNER_CODE, str(loan.loan_xid).zfill(13))


def construct_smf_customer_data(loan, application) -> Dict[str, str]:
    is_repeat = Loan.objects.filter(
        customer=loan.customer, loan_status__gte=LoanStatusCodes.CURRENT
    ).exclude(pk=loan.id).exists()
    credit_score = CreditScore.objects.filter(application=application).last()
    scoregrade = credit_score.score if credit_score and credit_score.score else ""

    data = {
        "refnocustid": str(loan.loan_xid),
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('fullname'): application.fullname,
        "email": application.email,
        "idnumber": application.ktp,
        "grossincome": application.monthly_income * 12,
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('mobileno'): application.mobile_phone_1,
        "transactiontype": loan.transaction_method.fe_display_name,
        "borrowertype": "repeat" if is_repeat else "new",
        "scoregrade": scoregrade,
        "scoreCheck": 1,
        "sectorCheck": 1,
        "incomeCheck": 1,
        "ageCheck": 1,
        "limitSanctioned": loan.loan_amount,
        "limitAvailable": loan.loan_amount,
        "kycpass": 1,
        "fdcpass": 1,
        "isdpd": 1,
        "isrestructure": 1,

        "din": "",
        "custtype": 1,
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('custname'): application.fullname,
        "title": "",
        "custaddress": application.full_address,
        "custrt": "00",
        "custrw": "00",
        "custkel": application.address_kelurahan,
        "custkec": application.address_kecamatan,
        "custcity": application.address_kabupaten,
        "custprov": application.address_provinsi,
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('zipcode'): application.address_kodepos,
        "custdati": change_city_to_dati_code(
            application.address_kabupaten
        ),
        "idtype": 1,
        "idexpired": "2999-12-31",
        "gender": 1 if application.gender == "Pria" else 2,
        "maritalstatus": SMFMaritalStatusConst.LIST[application.marital_status],
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('birthdate'): format_date(
            application.dob, "yyyy-MM-dd", locale="id_ID"
        ),
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('birthplace'): (application.birth_place),
        "birthdati": change_city_to_dati_code(application.address_kabupaten)
        if application.address_kabupaten
        else "",
        "worksince": format_date(
            application.job_start, "yyyy-MM-dd", locale="id_ID"
        ),
        "workradius": 0,
        "employeests": 0,
        "contractend": "",
        "lasteducation": SMFEducationConst.LIST.get(
            application.last_education, ""
        ),
        "economycode": "004190",
        "debiturcode": "9000",
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('mothername'): (
            application.customer_mother_maiden_name
        ),
        "npwp": "0",
        "homestatus": 0,
        "livedsince": format_date(
            application.occupied_since, "yyyy-MM-dd", locale="id_ID"
        ),
        "phonearea": "0",
        SMFChannelingConst.SMF_CUSTOMER_DATA_KEY.get('phoneno'): application.mobile_phone_1 or 0,
        "dependent": application.dependent,
        "expenses": application.monthly_expenses,
        "sameidhomeaddr": 0,
        "custaddresshome": application.full_address,
        "custrthome": "00",
        "custrwhome": "00",
        "custkelhome": application.address_kelurahan,
        "custkechome": application.address_kecamatan,
        "custcityhome": application.address_kabupaten,
        "custprovhome": application.address_provinsi,
        "custziphome": application.address_kodepos,
        "custdatihome": change_city_to_dati_code(
            application.address_kabupaten
        ),
        "spousename": application.spouse_name,
        "spousebirthdate": None,
        "spousebirthplace": "",
        "spouseidtype": 1,
        "spouseidnumber": "",
        "spousephoneno": "",
        "spousemobileno": "",
        "spouseoffice": "",
        "spouseoffinephone": "",
        "relativestype": None,
        "relativesname": application.kin_name or application.spouse_name,
        "custaddressrel": "NA",
        "custrtrel": "",
        "custrwrel": "",
        "custkelrel": "",
        "custkecrel": "",
        "custcityrel": "",
        "custprovrel": "",
        "custziprel": "",
        "phonenorel": "",
        "companyname": "",
        "companyaddr": "",
        "companycity": "",
        "companyzip": "",
        "companyphone": "",
        "deedno": "",
        "deeddate": None,
        "corporatetype": "LIMITED_PARTNERSHIP",
        "jobid": "099",
        "jobtitleid": "69",
        "countryid": "ID",
        "branchcode": "JULO-001",
        "targetmarket": "1",
    }
    replaced_data = replace_special_chars_for_fields(
        data=data,
        fields=[*SMFDataField.customer_address()],
    )
    return replaced_data


def construct_smf_loan_data(loan):
    channeling_loan_config = get_channeling_loan_configuration(ChannelingConst.SMF)
    first_payment = Payment.objects.filter(loan=loan).order_by('due_date').first()
    effectife_rate = SMFChannelingConst.EFFECTIVERATE
    if channeling_loan_config:
        interest_rate = channeling_loan_config["general"]["INTEREST_PERCENTAGE"]
        risk_premium_rate = channeling_loan_config["general"]["RISK_PREMIUM_PERCENTAGE"]
        effectife_rate = interest_rate + risk_premium_rate

    return {
        "refno": get_smf_refno(loan),
        "refnocustid": str(loan.loan_xid),
        "objectvalue": loan.loan_amount,
        "principaltotal": loan.loan_amount,
        "tenor": loan.loan_duration,
        "disbursedate": format_date(
            timezone.localtime(loan.fund_transfer_ts), 'yyyy-MM-dd', locale='id_ID'
        ),
        "effectiverate": effectife_rate,
        "firstinstdate": format_date(
            first_payment.due_date, 'yyyy-MM-dd', locale='id_ID'),
        "installment": loan.installment_amount,
        "ltv": 100,
        "isrestructure": 1,
        "ltvCheck": 1,
        "dbrCheck": 1,
        "loanTenorCheck": 1,

        "tenorunit": 3,
        "loantype": 0,
        "admfee": loan.product.origination_fee_pct,
        "inscode": "1",
        "inspremi": 0,
        "insonloan": 0,
        "installmenttype": 103,
        "branchcode": "ID0010009",
        "typeofuseid": "3",
        "orientationofuseid": "9",
        "debiturcatid": "99",
        "portfoliocatid": "36",
        "credittypeid": "20",
        "creditattributeid": "9",
        "creditcategoryid": "99",
        "fincat": "000",
        "creditdistrib": "3",
        "idcompany": SMFChannelingConst.COMPANYID,
        "interestratecust": "30",
        "deposit": 0,
    }


def construct_smf_collateral_data(loan):
    return {
        "refno": get_smf_refno(loan),
        "productcode": "000",
        "merkcode": "0",
        "modelcode": "0",
        "collateralno": "0",
        "collateraladdress": "NA",
        "collateralname": "NA",
        "engineno": "NA",
        "chassisno": "NA",
        "collateralyear": "0",
        "buildyear": "0",
        "condition": "0",
        "color": "NA",
        "collateralkind": "NA",
        "collateralpurpose": "NA",
        "policeno": "NA",
        "surveydate": "9999-12-31",
        "bindtypecode": "NA",
        "collateraltypecode": "NA",
        "collateralvalue": "0",
        "owncollateral": "00",
    }


def construct_smf_schedule_data(loan):
    payments = loan.payment_set.normal().order_by('payment_number')
    new_interests = recalculate_channeling_payment_interest(loan, ChannelingConst.SMF)
    data = []
    refno = get_smf_refno(loan)
    for _, payment in enumerate(payments):
        data.append(
            {
                "refno": refno,
                "period": str(payment.payment_number),
                "duedate": format_date(payment.due_date, 'yyyy-MM-dd', locale='id_ID'),
                "principal": payment.installment_principal,
                "interest": new_interests[payment.id],
                "principalpaid": 0,
                "interestpaid": 0,
                "penaltypaid": 0,
                "paidsts": 0,
                "paiddate": None,
                "paidtxndate": None,
            }
        )
    return data


def construct_smf_document_data(loan):
    data = []
    refno = get_smf_refno(loan)
    loan_dict = get_smf_document_data([loan.id])[0]
    for mapping in get_smf_document_list():
        try:
            if mapping['field'] == 'lender_bucket_xid':
                lender_bucket = LenderBucket.objects.filter(
                    lender_bucket_xid=loan_dict['lender_bucket_xid']
                ).last()
                loan_dict[mapping['field']] = lender_bucket.id
            source = mapping['model'].objects.filter(
                **{
                    **mapping['filter'],
                    ('%s_source' % mapping['model'].__name__.lower()): loan_dict[mapping['field']]
                }
            ).last()
            data.append(
                {
                    **mapping['data'],
                    "properties": {"type": {"const": mapping['data']['type']}},
                    "refno": refno,
                    "url": source.channeling_related_url(600),
                }
            )
        except Exception as e:
            sentry_client.captureException()
            logger.info({
                'action': 'channeling_loan.services.smf_services.construct_smf_document_data',
                'errors': str(e)
            })
    return data


def generate_smf_zip_file(filename, loan_ids):
    def _send_logger(**kwargs):
        logger_data = {
            'action': 'channeling_loan.services.smf_services.generate_smf_zip_file',
            'filename': filename,
            'loan_ids': loan_ids,
            **kwargs
        }
        logger.info(logger_data)

    file_path = os.path.join(tempfile.gettempdir(), filename)
    z = ZipFile(file_path, "w")

    for loan_dict in list(get_smf_document_data(loan_ids)):
        try:
            ktp = Image.objects.filter(
                image_source=loan_dict['application_id2'], image_type='ktp_self'
            ).last()
            image = urllib.request.urlopen(ktp.image_url)
            z.writestr(
                '%s/%s_ktp.%s' % (
                    loan_dict['loan_xid'],
                    loan_dict['loan_xid'],
                    (ktp.url.split('/')[-1]).split('.')[-1]
                ),
                image.read()
            )
        except Exception as e:
            sentry_client.captureException()
            _send_logger(errors=str(e))

        try:
            selfie = Image.objects.filter(
                image_source=loan_dict['application_id2'], image_type='selfie'
            ).last()
            image = urllib.request.urlopen(selfie.image_url)
            z.writestr(
                '%s/%s_selfie.%s' % (
                    loan_dict['loan_xid'],
                    loan_dict['loan_xid'],
                    (selfie.url.split('/')[-1]).split('.')[-1]
                ),
                image.read()
            )
        except Exception as e:
            sentry_client.captureException()
            _send_logger(errors=str(e))

        try:
            invoice = Document.objects.filter(
                document_source=loan_dict['id'], document_type='smf_invoice',
            ).last()
            page = urllib.request.urlopen(invoice.document_url)
            z.writestr(
                '%s/%s_invoice.pdf' % (loan_dict['loan_xid'], loan_dict['loan_xid']),
                page.read()
            )
        except Exception as e:
            sentry_client.captureException()
            _send_logger(errors=str(e))

        try:
            receipt = Document.objects.filter(
                document_source=loan_dict['id'], document_type='smf_receipt',
            ).last()
            page = urllib.request.urlopen(receipt.document_url)
            z.writestr(
                '%s/%s_receipt.pdf' % (loan_dict['loan_xid'], loan_dict['loan_xid']),
                page.read()
            )
        except Exception as e:
            sentry_client.captureException()
            _send_logger(errors=str(e))

        try:
            loan_agreement = Document.objects.filter(
                document_source=loan_dict['id'],
                document_type__in=(
                    'sphp_privy', 'sphp_julo', 'sphp_grab', 'dana_loan_agreement', 'skrtp_julo',
                ),
            ).last()
            page = urllib.request.urlopen(loan_agreement.document_url)
            z.writestr(
                '%s/%s_loan_agreement.pdf' % (loan_dict['loan_xid'], loan_dict['loan_xid']),
                page.read()
            )
        except Exception as e:
            sentry_client.captureException()
            _send_logger(errors=str(e))

        try:
            lender_bucket = LenderBucket.objects.filter(
                lender_bucket_xid=loan_dict['lender_bucket_xid']
            ).last()
            lender_agreement = Document.objects.filter(
                document_source=lender_bucket.id, document_type='summary_lender_sphp'
            ).last()
            page = urllib.request.urlopen(lender_agreement.document_url)
            z.writestr(
                '%s/%s_lender_agreement.pdf' % (loan_dict['loan_xid'], loan_dict['loan_xid']),
                page.read()
            )
        except Exception as e:
            sentry_client.captureException()
            _send_logger(errors=str(e))
    z.close()
    return file_path


def get_loan_payment_gateway_and_product(loan):
    final_product = payment_gateway = ""

    disbursement = Disbursement.objects.get_or_none(pk=loan.disbursement_id)
    sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
    if disbursement:
        payment_gateway = disbursement.method

    if loan.is_to_self:
        final_product = 'Tarik Tunai'

    elif loan.is_to_other:
        final_product = 'Kirim Tunai'

    elif sepulsa_transaction:
        product = sepulsa_transaction.product
        final_product = product.product_name
        payment_gateway = "Sepulsa"

        if product.type == SepulsaProductType.BPJS:
            final_product = "Tagihan %s bulan" % (sepulsa_transaction.paid_period)

    elif is_ecommerce_bank_account(loan.bank_account_destination):
        final_product = loan.bank_account_destination.description

    elif loan.is_qris_product:
        final_product = "Scan QR"

    elif loan.is_jfinancing_product:
        final_product = "Kredit HP"

    elif loan.is_rentee_loan():
        final_product = "Rentee"

    elif loan.is_credit_card_product:
        final_product = "JULO Card"
        payment_gateway = "BSS"

    elif loan.is_education_product:
        final_product = "Biaya Pendidikan"

    elif loan.is_healthcare_product:
        final_product = "Biaya Kesehatan"

    # having SepulsaTransaction checking above else go here we only have Xfers or Ayoconnect
    elif loan.is_ewallet_product:
        if loan.is_xfers_ewallet_transaction:
            ewallet_transaction = loan.xfers_ewallet_transaction
            ewallet_product = ewallet_transaction.xfers_product
            payment_gateway = 'Xfers'
        else:
            ewallet_transaction = AYCEWalletTransaction.objects.filter(loan_id=loan.pk).last()
            ewallet_product = ewallet_transaction.ayc_product
            payment_gateway = 'Ayoconnect'

        final_product = ewallet_product.product_name

    return final_product, payment_gateway


def generate_smf_receipt_and_invoice(loan, document_type):
    if not loan:
        raise Exception

    product_type, payment_gateway = get_loan_payment_gateway_and_product(loan)

    base_date = loan.fund_transfer_ts
    title = 'Bukti Pembayaran'
    if document_type == 'invoice':
        base_date = loan.sphp_accepted_ts
        title = 'Invoice'

    transaction_code = loan.loan_xid
    sepulsa_transaction = SepulsaTransaction.objects.filter(loan_id=loan.pk).last()
    if sepulsa_transaction:
        transaction_code = sepulsa_transaction.transaction_code
    else:
        disbursement = Disbursement.objects.filter(
            pk=loan.disbursement_id, method='Ayoconnect'
        ).last()
        if disbursement and disbursement.reference_id:
            transaction_code = disbursement.reference_id

    context = {
        'title_header': title,
        'description': (
            '%s ini adalah %s yang sah,'
            ' dan diterbitkan atas nama pengguna'
        ) % (title.capitalize(), title.lower()),
        'title_reference': 'No %s' % title,
        'title_body': 'Detail %s' % ('Transaksi' if document_type == 'invoice' else 'Pembayaran'),
        'reference_id': '%s/%s/%s/%s/%s' % (
            document_type[:3].upper(),
            format_date(timezone.localtime(base_date), "yyyy", locale='id_ID'),
            format_date(timezone.localtime(base_date), "MM", locale='id_ID'),
            format_date(timezone.localtime(base_date), "d", locale='id_ID'),
            transaction_code,
        ),
        'transaction_ts': format_datetime(
            timezone.localtime(base_date), "dd MMM yyyy hh.mm.ss zzz", locale='id_ID'
        ),

        'transaction_method_logo': loan.transaction_method.foreground_icon_url,
        'category_product_name': loan.transaction_method.fe_display_name,
        'transaction_date': format_date(
            timezone.localtime(loan.fund_transfer_ts), "d MMM yyyy", locale='id_ID'
        ),
        'product_type': product_type,
        'fullname': loan.customer.fullname,
        'transaction_code': transaction_code,
        'payment_gateway': payment_gateway,
        'amount': format_number(loan.loan_amount, locale='id_ID'),
        'image_url': '%seducation/' % (settings.STATIC_ALICLOUD_BUCKET_URL),
        'logo': SMF_INVOICE_ICON_LINK,
    }
    if document_type == 'receipt':
        context['status'] = True

    template = render_to_string(
        "%s/juloserver/channeling_loan/templates/invoice_and_receipt_pdf.html" % (
            settings.BASE_DIR
        ),
        context=context
    )

    filename = '%s_%s.pdf' % (loan.loan_xid, document_type)
    local_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        pdfkit.from_string(template, local_path, options=get_default_pdf_options(zoom=1))
    except Exception as e:
        logger.info({'action': 'generate_smf_receipt_and_invoice', 'error': str(e)})
        sentry_client.captureException()
        raise e

    document = Document.objects.create(
        document_source=loan.id,
        document_type='smf_%s' % (document_type),
        filename=filename,
        loan_xid=loan.loan_xid,
    )

    return document.id, local_path


def get_smf_document_data(loan_ids):
    return (
        Loan.objects.filter(pk__in=loan_ids).order_by("-cdate")
    ).annotate(
        lender_bucket_xid=F('lendersignature__lender_bucket_xid'),
    ).values(
        'id',
        'loan_xid',
        'application_id2',
        'lender_bucket_xid',
    )


def get_smf_document_list():
    return [
        {
            "data": {"type": "KTP", "description": "Kartu Tanda Penduduk"},
            "model": Image, "field": "application_id2", "filter": {"image_type": "ktp_self"},
        },
        {
            "data": {"type": "SWK", "description": "Selfie dengan KTP"},
            "model": Image, "field": "application_id2", "filter": {"image_type": "selfie"},
        },
        {
            "data": {"type": "FKT", "description": "Faktur"},
            "model": Document, "field": "id", "filter": {"document_type": "smf_invoice"}
        },
        {
            "data": {"type": "TT", "description": "Tanda Tarima"},
            "model": Document, "field": "id", "filter": {"document_type": "smf_receipt"}
        },
        {
            "data": {"type": "SPK", "description": "Surat Perjanjian Kredit"},
            "model": Document, "field": "id", "filter": {
                "document_type__in": (
                    'sphp_privy', 'sphp_julo', 'sphp_grab', 'dana_loan_agreement', 'skrtp_julo'
                )
            }
        },
        {
            "data": {"type": "PK", "description": "Perjanjian Kerjasama"},
            "model": Document, "field": "lender_bucket_xid",
            "filter": {"document_type": "summary_lender_sphp"},
        },
    ]


def validate_smf_document_data(loan):
    data = {}
    loan_dict = get_smf_document_data([loan.id])[0]
    for mapping in get_smf_document_list():
        logger.info({
            'action': 'channeling_loan.services.smf_services.validate_smf_document_data',
            'loan_id': loan.id,
            'data': mapping['data'],
        })

        try:
            if mapping['field'] == 'lender_bucket_xid':
                lender_bucket = LenderBucket.objects.filter(
                    lender_bucket_xid=loan_dict['lender_bucket_xid']
                ).last()
                loan_dict[mapping['field']] = lender_bucket.id
            source = mapping['model'].objects.filter(
                **{
                    **mapping['filter'],
                    ('%s_source' % mapping['model'].__name__.lower()): loan_dict[mapping['field']]
                }
            ).last()
            data[mapping["data"]["type"]] = True if (source and source.url) else False
        except Exception as e:
            sentry_client.captureException()
            logger.info({
                'action': 'channeling_loan.services.smf_services.validate_smf_document_data',
                'loan_id': loan.id,
                'errors': str(e),
            })

    return data


def construct_smf_api_disbursement_data(loan):
    application = loan.get_application
    return {
        "customerdata": construct_smf_customer_data(loan, application),
        "loandata": construct_smf_loan_data(loan),
        "collateraldata": construct_smf_collateral_data(loan),
        "schedule": construct_smf_schedule_data(loan),
        "documents": construct_smf_document_data(loan),
    }


def construct_smf_api_check_transaction_data(loan):
    return {
        "refno": get_smf_refno(loan),
        "trxtype": "DS",
    }


def check_loan_validation_for_smf(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None, "Loan not found"

    channeling_type = ChannelingConst.SMF
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    if not channeling_loan_config:
        return None, "Channeling config not found"

    general_config = channeling_loan_config.get('general', {})
    if ChannelingConst.API_CHANNELING_TYPE != general_config.get('CHANNELING_TYPE', ''):
        return None, "SMF non API"

    if loan.lender.lender_name != general_config.get('LENDER_NAME', ''):
        return None, "Non SMF Loan"

    return loan, None

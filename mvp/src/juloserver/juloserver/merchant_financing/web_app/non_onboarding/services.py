import csv
import io
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import Dict, Optional, Tuple

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.account.services.account_related import is_new_loan_part_of_bucket5
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.account_payment.models import AccountPayment
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountDestination
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.fdc.files import TempDir
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.banks import BankManager
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.models import (
    Application,
    Bank,
    Document,
    FeatureSetting,
    Loan,
    LoanHistory,
    Partner,
    Payment,
    PaymentMethod,
    ProductLookup,
    StatusLookup,
    UploadAsyncState,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import (
    display_rupiah,
    upload_file_to_oss,
    execute_after_transaction_safely,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.constants import LoanJuloOneConstant
from juloserver.loan.services.loan_related import (
    check_eligible_and_out_date_other_platforms,
    get_loan_amount_by_transaction_type,
    update_fdc_active_loan_checking,
    update_loan_status_and_loan_history,
)
from juloserver.merchant_financing.constants import (
    MF_STANDARD_LOAN_UPLOAD_HEADERS,
    MFFeatureSetting,
    MFStandardProductUploadDetails,
    LenderAxiata,
    FunderAxiata,
)
from juloserver.merchant_financing.tasks import (
    merchant_financing_generate_lender_agreement_document_task,
    mf_send_sms_skrtp,
    upload_document_mf,
)
from juloserver.merchant_financing.utils import (
    compute_loan_calculation_mf_standard,
    compute_mf_standard_amount,
    get_lender_by_partner,
    validate_file_from_url_including_restricted_file,
)
from juloserver.merchant_financing.web_app.constants import (
    MAX_LOAN_AXIATA,
    MAX_LOAN_DURATION_AXIATA,
    MIN_LOAN_AXIATA,
    MFWebMaxPlatformCheckStatus,
)
from juloserver.merchant_financing.web_app.crm.tasks import send_email_skrtp
from juloserver.merchant_financing.web_app.non_onboarding.serializers import (
    MFStandardLoanSubmissionSerializer,
)

from juloserver.merchant_financing.utils import (
    compute_mf_amount,
    get_rounded_monthly_interest_rate,
)

from juloserver.partnership.constants import (
    CSV_DELIMITER_SIZE,
    PartnershipFlag,
    LoanDurationType,
    LoanPurposeType,
    PartnershipFundingFacilities,
    PartnershipImageStatus,
    PartnershipImageProductType,
    PartnershipFeatureNameConst,
)
from juloserver.merchant_financing.web_app.non_onboarding.tasks import (
    merchant_financing_max_platform_check,
)
from juloserver.partnership.models import (
    PartnerLoanRequest,
    PartnershipCustomerData,
    PartnershipDistributor,
    PartnershipDocument,
    PartnershipFeatureSetting,
    PartnershipFlowFlag,
    PartnershipImage,
    PartnershipLoanAdditionalFee,
)
from juloserver.partnership.services.digisign import ParntershipDigisign
from juloserver.partnership.services.services import (
    is_partnership_lender_balance_sufficient,
    partnership_mock_get_and_save_fdc_data,
)
from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.pii_vault.constants import PiiSource
from juloserver.portal.object.bulk_upload.constants import (
    MerchantFinancingCSVUploadPartner,
    MerchantFinancingCSVUploadPartnerDueDateType,
)
from juloserver.portal.object.bulk_upload.services import (
    DAGANGAN,
    VALIDATE_PARTNER_MF_EFISHERY,
    VALIDATE_PARTNER_PRODUCT_LINE,
)
from juloserver.merchant_financing.web_app.tasks import (
    generate_axiata_customer_data_task,
)

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


def create_loan_mf_webapp(data) -> Tuple[str, int]:
    def _upload_file(file, file_type):
        _, file_extension = os.path.splitext(file.name)
        filename = 'mf-webapp-{}-{}{}'.format(file_type, loan.id, file_extension)
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        document = Document.objects.create(
            document_source=loan.id,
            document_type='mf_webapp_{}'.format(file_type),
            filename=filename,
            application_xid=application.application_xid,
        )
        upload_document_mf(document.id, 'loan', file_path)

    user = data.get("user")
    request = data.get("request")

    if not hasattr(user, "customer"):
        return 'customer not found', 0

    account = user.customer.account

    if not account:
        return 'account not found', 0

    if account.status_id != AccountConstant.STATUS_CODE.active:
        return 'Tidak bisa membuat pinjaman baru karena masih ada tunggakan', 0

    application = user.customer.application_set.last()
    if not application:
        return 'application not found', 0

    loan_amount = request.get("loan_amount")

    if request.get("loan_duration") > MAX_LOAN_DURATION_AXIATA:
        return 'max loan_duration is ' + str(MAX_LOAN_DURATION_AXIATA), 0

    if loan_amount > MAX_LOAN_AXIATA:
        return 'max loan_amount is ' + str(MAX_LOAN_AXIATA), 0

    if loan_amount < MIN_LOAN_AXIATA:
        return 'min loan_amount is ' + str(MIN_LOAN_AXIATA), 0

    account_limit = account.accountlimit_set.last()
    if not account_limit:
        return 'account_limit not found', 0

    if loan_amount > account_limit.available_limit:
        return 'Besar pinjaman melebihi limit', 0

    due_amount = (
        AccountPayment.objects.filter(account_id=account)
        .aggregate(total=Sum('due_amount'))
        .get('total')
    )
    total_due = (due_amount or 0) + loan_amount
    if total_due > MAX_LOAN_AXIATA:
        return 'Total semua pinjaman melebihi limit', 0

    loan_type_mapping = {
        PartnershipFundingFacilities.SUPPLY_CHAIN_FINANCING: "SCF",
        PartnershipFundingFacilities.INVOICE_FINANCING: "IF",
    }

    loan_type = request.get("loan_type").upper()
    loan_type = loan_type_mapping.get(loan_type, loan_type)
    try:
        with transaction.atomic():
            disbursement_amount = loan_amount
            is_digisign = False
            partner_name = application.partner.name
            fs = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.PARTNERSHIP_DIGISIGN_PRICING,
                is_active=True,
            ).first()
            if fs and fs.parameters.get(partner_name) and fs.parameters[partner_name]['is_active']:
                is_digisign = True
                partnership_digisign = ParntershipDigisign(fs.parameters[partner_name])
                disbursement_amount -= partnership_digisign.get_fee_charged_to_borrower()

            loan = Loan.objects.create(
                customer=user.customer,
                application_id2=application.id,
                loan_amount=loan_amount,
                loan_duration=request.get("loan_duration"),
                installment_amount=0,
                first_installment_amount=0,
                loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.DRAFT),
                loan_disbursement_amount=disbursement_amount,
                account=account,
                loan_purpose=LoanPurposeType.MODAL_USAHA,
                transaction_method_id=TransactionMethodCode.OTHER.code,  # Kirim Dana
            )
            loan_xid = loan.loan_xid
            if is_digisign:
                partnership_digisign.create_partnership_loan_additional_fee(loan.id)

            detokenize_customer = partnership_detokenize_sync_object_model(
                PiiSource.CUSTOMER,
                user.customer,
                user.customer.customer_xid,
                ['fullname'],
            )
            PartnerLoanRequest.objects.create(
                loan=loan,
                partner=application.partner,
                loan_amount=loan_amount,
                loan_disbursement_amount=disbursement_amount,
                loan_original_amount=loan_amount,
                loan_type=loan_type,
                loan_request_date=loan.cdate,
                loan_duration_type=LoanDurationType.DAYS,
                buyer_name=detokenize_customer.fullname,
                buying_amount=loan_amount,
                financing_amount=loan_amount,
                financing_tenure=request.get("loan_duration"),
                installment_number=request.get("installment_number"),
                invoice_number=request.get("invoice_number"),
            )

            _upload_file(request.get("invoice_file"), 'invoice')
            if request.get("bilyet_file"):
                _upload_file(request.get("bilyet_file"), 'bilyet')

    except Exception as e:
        return str(e), 0

    return None, loan_xid


def update_merchant_financing_webapp_loan(**kwargs) -> Tuple[bool, str]:
    # Validate kwargs
    required_fields = [
        'loan_xid',
        'distributor_code',
        'funder',
        'interest_rate',
        'provision_rate',
        'user_id',
        'partner_id',
    ]
    for field in required_fields:
        if field not in kwargs:
            return False, "Field '{}' tidak ditemukan".format(field)

    with transaction.atomic():
        loan_xid = kwargs['loan_xid']
        distributor_code = kwargs['distributor_code']
        funder = kwargs.get('funder')
        interest_rate_str = kwargs['interest_rate']
        provision_rate_str = kwargs['provision_rate']
        change_by_id = kwargs['user_id']
        partner_id = kwargs['partner_id']

        interest_rate = float(interest_rate_str)
        provision_rate = float(provision_rate_str)

        # Get loan data
        loan = Loan.objects.select_for_update().filter(loan_xid=loan_xid).first()
        if not loan:
            return False, "Pinjaman tidak ditemukan"

        if loan.status != LoanStatusCodes.DRAFT:
            return False, "Status pinjaman tidak sesuai"

        lender_name = LenderAxiata.JTP
        if funder and funder.lower() == FunderAxiata.SMF:
            lender_name = LenderAxiata.SMF
        lender = LenderCurrent.objects.get(lender_name=lender_name)

        application = (
            Application.objects.filter(id=loan.application_id2)
            .select_related("product_line")
            .first()
        )
        if not application:
            return False, "Application tidak ditemukan"

        product_line = application.product_line
        product_lookup = ProductLookup.objects.filter(
            product_line=product_line,
            interest_rate=interest_rate,
            origination_fee_pct=provision_rate,
        ).first()
        if not product_lookup:
            return False, "Product Lookup tidak ditemukan"

        old_status_code = loan.status

        # Update partner loan request
        partnership_distributor = PartnershipDistributor.objects.filter(
            distributor_id=distributor_code
        ).first()
        if not partnership_distributor:
            return False, "Partnership Distributor tidak ditemukan"

        partner_loan_request = (
            PartnerLoanRequest.objects.select_related('loan')
            .filter(loan=loan.id, partner_id=partner_id)
            .first()
        )
        if not partner_loan_request:
            return False, "Partner Loan Request tidak ditemukan"

        partner_loan_request.partnership_distributor = partnership_distributor
        partner_loan_request.funder = funder
        partner_loan_request.interest_rate = interest_rate
        partner_loan_request.provision_rate = provision_rate
        partner_loan_request.funder = funder

        # Create Payment Data
        financing_tenure = partner_loan_request.financing_tenure
        installment_number = partner_loan_request.installment_number
        loan_request_date = partner_loan_request.loan_request_date
        financing_amount = partner_loan_request.loan_amount

        days_delta_each_payment = financing_tenure / installment_number
        first_payment_date = loan_request_date + timedelta(days=days_delta_each_payment)
        disbursement_amount = loan.loan_disbursement_amount - (provision_rate * financing_amount)
        partner_loan_request.loan_disbursement_amount = disbursement_amount
        partner_loan_request.save()

        (
            first_installment_amount,
            installment_each_payment,
            deviation,
            interest_each_payment,
            principal_each_payment,
        ) = compute_mf_amount(
            product_lookup.interest_rate, financing_tenure, installment_number, financing_amount
        )

        # Update loan and save loan_history data
        loan.product = product_lookup
        loan.lender = lender
        loan.loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE)
        loan.installment_amount = installment_each_payment
        loan.first_installment_amount = first_installment_amount
        loan.loan_disbursement_amount = disbursement_amount
        loan.save()

        loan_history_data = {
            "loan": loan,
            "status_old": old_status_code,
            "status_new": loan.status,
            "change_reason": "system triggered",
            "change_by_id": change_by_id,
        }
        LoanHistory.objects.create(**loan_history_data)

        # update available limit
        update_available_limit(loan)
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for payment_number in range(installment_number):
            if payment_number == 0:
                due_date = first_payment_date
                due_amount = first_installment_amount
                installment_interest = interest_each_payment + deviation
            else:
                due_date = first_payment_date + (
                    int(days_delta_each_payment) * relativedelta(days=payment_number)
                )
                due_amount = installment_each_payment
                installment_interest = interest_each_payment

            payment = Payment.objects.create(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=due_amount,
                installment_principal=principal_each_payment,
                installment_interest=installment_interest,
            )

            logger.info(
                {
                    'loan': loan,
                    'payment_number': payment_number,
                    'payment_amount': payment.due_amount,
                    'due_date': due_date,
                    'payment_status': payment.payment_status.status,
                    'status': 'payment_created',
                }
            )

    generate_axiata_customer_data_task.delay(loan.id)
    merchant_financing_max_platform_check.delay(loan.application_id2, False, loan.id)
    return True, ""


def get_loan_detail(loan_xid, partner_id) -> Tuple[bool, str, Optional[dict]]:
    distributor_name = None
    funder = None
    interest_rate = None
    provision_rate = None
    installment_amount = None
    provision_amount = None

    loan = Loan.objects.filter(loan_xid=loan_xid).first()
    if not loan:
        return False, "Pinjaman tidak ditemukan", None

    application = Application.objects.filter(id=loan.application_id2).first()
    if not application:
        return False, "Application tidak ditemukan", None

    partnership_customer_data = (
        PartnershipCustomerData.objects.filter(application_id=application.id)
        .select_related("customer")
        .last()
    )
    if not partnership_customer_data:
        return False, "PartnershipCustomerData tidak ditemukan", None

    detokenized_pcd = partnership_detokenize_sync_object_model(
        pii_source=PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        object_model=partnership_customer_data,
        customer_xid=partnership_customer_data.customer.customer_xid,
        fields_param=["nik"],
    )

    detokenized_customer = partnership_detokenize_sync_object_model(
        pii_source=PiiSource.CUSTOMER,
        object_model=partnership_customer_data.customer,
        customer_xid=partnership_customer_data.customer.customer_xid,
        fields_param=["fullname"],
    )

    partner_loan_request = (
        PartnerLoanRequest.objects.select_related('loan')
        .filter(loan=loan.id, partner_id=partner_id)
        .first()
    )
    if not partner_loan_request:
        return False, "PartnerLoanRequest tidak ditemukan", None

    documents = Document.objects.filter(document_source=loan.id)
    if not documents:
        return False, "Dokumen tidak ditemukan", None

    invoice_file_url = ""
    invoice_file_name = ""
    bilyet_file_url = ""
    bilyet_file_name = ""
    for document in documents.iterator():
        if "invoice" in document.document_type:
            invoice_file_url = document.document_url
            invoice_file_name = document.filename
        elif "bilyet" in document.document_type:
            bilyet_file_url = document.document_url
            bilyet_file_name = document.filename

    if loan.status is not LoanStatusCodes.DRAFT:
        distributor_name = partner_loan_request.partnership_distributor.distributor_name
        funder = partner_loan_request.funder
        installment_amount = loan.installment_amount
        if loan.product:
            provision_amount = ceil(loan.loan_amount * loan.product.origination_fee_pct)
            interest_rate = get_rounded_monthly_interest_rate(loan.product.interest_rate)
            provision_rate = loan.product.origination_fee_pct

    loan_type_reverse_mapping = {
        "SCF": PartnershipFundingFacilities.SUPPLY_CHAIN_FINANCING,
        "IF": PartnershipFundingFacilities.INVOICE_FINANCING,
    }

    loan_type = partner_loan_request.loan_type
    loan_type = loan_type_reverse_mapping.get(loan_type, loan_type)

    loan_detail = {
        'loan_xid': loan.loan_xid,
        'cdate': loan.cdate,
        'borrower_name': detokenized_customer.fullname,
        'nik': detokenized_pcd.nik,
        'loan_status': loan.status,
        'loan_type': loan_type,
        'loan_amount': loan.loan_amount,
        'loan_duration': loan.loan_duration,
        'loan_duration_type': partner_loan_request.loan_duration_type,
        'installment_number': partner_loan_request.installment_number,
        'invoice_number': partner_loan_request.invoice_number,
        'distributor_name': distributor_name,
        'funder': funder,
        'interest_rate': interest_rate,
        'provision_rate': provision_rate,
        'installment_amount': installment_amount,
        'provision_amount': provision_amount,
        'invoice_file': invoice_file_name,
        'invoice_url': invoice_file_url,
        'bilyet_file': bilyet_file_name,
        'bilyet_url': bilyet_file_url,
    }

    return True, "", loan_detail


def merchant_financing_handle_after_fdc_check_success(is_eligible: bool, loan_id: int) -> None:
    partner_loan_request = (
        PartnerLoanRequest.objects.filter(loan_id=loan_id)
        .select_related("loan", "loan__product", "loan__product__product_line")
        .first()
    )
    loan = partner_loan_request.loan
    max_platform_check = partner_loan_request.max_platform_check
    if max_platform_check is not None:
        logger.info(
            {
                "action": "merchant_finacing_max_platform_check_initiate_false",
                "info": "No need to update, max platform check already done for the Loan",
                "data": loan_id,
            }
        )
        return

    if loan.product.product_line.product_line_code == ProductLineCodes.AXIATA_WEB:
        if is_eligible:
            partner_loan_request.max_platform_check = is_eligible
            partner_loan_request.save()
            interest_rate = loan.product.interest_rate
            loan_request_date = partner_loan_request.loan_request_date.strftime('%d/%m/%Y')
            send_email_skrtp.delay(
                loan_id=loan_id, interest_rate=interest_rate, loan_request_date=loan_request_date
            )
            mf_send_sms_skrtp(loan)
        else:
            partner_loan_request.max_platform_check = is_eligible
            partner_loan_request.save()
            update_loan_status_and_loan_history(
                loan_id=loan_id,
                new_status_code=LoanStatusCodes.LENDER_REJECT,
                change_reason="Ineligible active loans from platforms",
            )
    else:
        # TODO: need to handle on loan creation wheter we use the same logic or not
        pass


def get_merchant_loan_detail(loan_xid, user_id) -> Tuple[bool, str, Optional[dict]]:
    loan = Loan.objects.select_related('customer').filter(loan_xid=loan_xid).first()
    if not loan or loan.customer.user.id != user_id:
        return False, "Pinjaman tidak ditemukan", None

    application = Application.objects.filter(id=loan.application_id2).first()
    if not application:
        return False, "Application tidak ditemukan", None

    partnership_customer_data = PartnershipCustomerData.objects.filter(
        application_id=application.id
    ).last()
    if not partnership_customer_data:
        return False, "PartnershipCustomerData tidak ditemukan", None

    partner_loan_request = (
        PartnerLoanRequest.objects.select_related('loan').filter(loan=loan.id).first()
    )
    if not partner_loan_request:
        return False, "PartnerLoanRequest tidak ditemukan", None

    loan_type_reverse_mapping = {
        "SCF": PartnershipFundingFacilities.SUPPLY_CHAIN_FINANCING,
        "IF": PartnershipFundingFacilities.INVOICE_FINANCING,
    }
    loan_type = partner_loan_request.loan_type
    loan_type = loan_type_reverse_mapping.get(loan_type, loan_type)

    documents = Document.objects.filter(document_source=loan.id)
    if not documents:
        return False, "Dokumen tidak ditemukan", None

    invoice_file_url = ""
    invoice_file_name = ""
    bilyet_file_url = ""
    bilyet_file_name = ""
    skrtp_file_url = ""
    skrtp_file_name = ""
    for document in documents.iterator():
        if "invoice" in document.document_type:
            invoice_file_url = document.document_url
            invoice_file_name = document.filename
        elif "bilyet" in document.document_type:
            bilyet_file_url = document.document_url
            bilyet_file_name = document.filename
        elif "skrtp" in document.document_type:
            skrtp_file_url = document.document_url
            skrtp_file_name = document.filename

    provision_amount = 0
    if loan.product:
        provision_amount = ceil(loan.loan_amount * loan.product.origination_fee_pct)
    if partner_loan_request.max_platform_check is True:
        max_platform_check_status = MFWebMaxPlatformCheckStatus.DONE
    elif partner_loan_request.max_platform_check is False:
        max_platform_check_status = MFWebMaxPlatformCheckStatus.FAIL
    else:
        max_platform_check_status = MFWebMaxPlatformCheckStatus.IN_PROGRESS

    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        partnership_customer_data.customer.customer_xid,
        ['email'],
    )
    additional_fee_amount = (
        PartnershipLoanAdditionalFee.objects.filter(
            loan_id=loan.id, charged_to=PartnershipLoanAdditionalFee.BORROWER
        )
        .aggregate(total_fee_amount=Sum("fee_amount"))
        .get("total_fee_amount")
    )

    # mapping loan based on status
    if loan.status == LoanStatusCodes.DRAFT:
        loan_detail = {
            'loan_xid': loan.loan_xid,
            'cdate': loan.cdate,
            'email': detokenize_partnership_customer_data.email,
            'loan_status': loan.status,
            'loan_type': loan_type,
            'loan_amount': loan.loan_amount,
            'loan_duration': loan.loan_duration,
            'loan_duration_type': partner_loan_request.loan_duration_type,
            'installment_number': partner_loan_request.installment_number,
            'invoice_number': partner_loan_request.invoice_number,
            'invoice_file': invoice_file_name,
            'invoice_url': invoice_file_url,
            'bilyet_file': bilyet_file_name,
            'bilyet_url': bilyet_file_url,
            'max_platform_check': max_platform_check_status,
        }
        if additional_fee_amount is not None:
            loan_detail['additional_fee'] = additional_fee_amount

        return True, "", loan_detail

    elif loan.status == LoanStatusCodes.INACTIVE:
        loan_detail = {
            'loan_xid': loan.loan_xid,
            'cdate': loan.cdate,
            'email': detokenize_partnership_customer_data.email,
            'loan_status': loan.status,
            'loan_type': loan_type,
            'loan_amount': loan.loan_amount,
            'loan_duration': loan.loan_duration,
            'loan_duration_type': partner_loan_request.loan_duration_type,
            'installment_number': partner_loan_request.installment_number,
            'invoice_number': partner_loan_request.invoice_number,
            'distributor_name': partner_loan_request.partnership_distributor.distributor_name,
            'funder': partner_loan_request.funder,
            'interest_rate': get_rounded_monthly_interest_rate(partner_loan_request.interest_rate),
            'provision_rate': partner_loan_request.provision_rate,
            'installment_amount': loan.installment_amount,
            'provision_amount': provision_amount,
            'invoice_file': invoice_file_name,
            'invoice_url': invoice_file_url,
            'bilyet_file': bilyet_file_name,
            'bilyet_url': bilyet_file_url,
            'max_platform_check': max_platform_check_status,
        }
        if additional_fee_amount is not None:
            loan_detail['additional_fee'] = additional_fee_amount

        return True, "", loan_detail

    elif loan.status == LoanStatusCodes.LENDER_APPROVAL:
        loan_detail = {
            'loan_xid': loan.loan_xid,
            'cdate': loan.cdate,
            'email': detokenize_partnership_customer_data.email,
            'loan_status': loan.status,
            'loan_type': loan_type,
            'loan_amount': loan.loan_amount,
            'loan_duration': loan.loan_duration,
            'loan_duration_type': partner_loan_request.loan_duration_type,
            'installment_number': partner_loan_request.installment_number,
            'invoice_number': partner_loan_request.invoice_number,
            'distributor_name': partner_loan_request.partnership_distributor.distributor_name,
            'funder': partner_loan_request.funder,
            'interest_rate': get_rounded_monthly_interest_rate(partner_loan_request.interest_rate),
            'provision_rate': partner_loan_request.provision_rate,
            'installment_amount': loan.installment_amount,
            'provision_amount': provision_amount,
            'invoice_file': invoice_file_name,
            'invoice_url': invoice_file_url,
            'bilyet_file': bilyet_file_name,
            'bilyet_url': bilyet_file_url,
            'skrtp_file': skrtp_file_name,
            'skrtp_url': skrtp_file_url,
            'max_platform_check': max_platform_check_status,
        }
        if additional_fee_amount is not None:
            loan_detail['additional_fee'] = additional_fee_amount

        return True, "", loan_detail

    elif loan.status == LoanStatusCodes.CURRENT:
        loan_detail = {
            'loan_xid': loan.loan_xid,
            'cdate': loan.cdate,
            'email': detokenize_partnership_customer_data.email,
            'loan_status': loan.status,
            'loan_type': loan_type,
            'loan_amount': loan.loan_amount,
            'loan_duration': loan.loan_duration,
            'installment_number': partner_loan_request.installment_number,
            'invoice_number': partner_loan_request.invoice_number,
            'distributor_name': partner_loan_request.partnership_distributor.distributor_name,
            'interest_rate': get_rounded_monthly_interest_rate(partner_loan_request.interest_rate),
            'provision_rate': partner_loan_request.provision_rate,
            'installment_amount': loan.installment_amount,
            'provision_amount': provision_amount,
            'invoice_file': invoice_file_name,
            'invoice_url': invoice_file_url,
            'bilyet_file': bilyet_file_name,
            'bilyet_url': bilyet_file_url,
            'skrtp_file': skrtp_file_name,
            'skrtp_url': skrtp_file_url,
            'max_platform_check': max_platform_check_status,
        }
        if additional_fee_amount is not None:
            loan_detail['additional_fee'] = additional_fee_amount

        return True, "", loan_detail

    else:
        loan_detail = {
            'loan_xid': loan.loan_xid,
            'cdate': loan.cdate,
            'email': detokenize_partnership_customer_data.email,
            'loan_status': loan.status,
            'loan_type': loan_type,
            'loan_amount': loan.loan_amount,
            'loan_duration': loan.loan_duration,
            'installment_number': partner_loan_request.installment_number,
            'invoice_number': partner_loan_request.invoice_number,
            'distributor_name': partner_loan_request.partnership_distributor.distributor_name,
            'funder': partner_loan_request.funder,
            'interest_rate': get_rounded_monthly_interest_rate(partner_loan_request.interest_rate),
            'provision_rate': partner_loan_request.provision_rate,
            'installment_amount': loan.installment_amount,
            'provision_amount': provision_amount,
            'invoice_file': invoice_file_name,
            'invoice_url': invoice_file_url,
            'bilyet_file': bilyet_file_name,
            'bilyet_url': bilyet_file_url,
            'skrtp_file': skrtp_file_name,
            'skrtp_url': skrtp_file_url,
            'max_platform_check': max_platform_check_status,
        }
        if additional_fee_amount is not None:
            loan_detail['additional_fee'] = additional_fee_amount

        return True, "", loan_detail


def upload_partnership_document_mf(data) -> Tuple[str, str, str]:
    request = data.get("request")
    loan_xid = data.get("loan_xid")
    user_id = data.get("user_id")
    loan = Loan.objects.filter(loan_xid=loan_xid).last()
    if not loan:
        return "Pinjaman tidak ditemukan", "", ""

    try:
        file = request.get("file")
        file_type = request.get("file_type")
        _, file_extension = os.path.splitext(file.name)
        filename = "mf-std-{}-{}{}".format(file_type, loan_xid, file_extension)
        temp_dir = tempfile.gettempdir()
        local_path = os.path.join(temp_dir, filename)
        with open(local_path, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        if file_type == "merchant_photo":
            document = PartnershipImage.objects.create(
                loan_image_source=loan.id,
                image_type="mf_std_{}".format(file_type),
                product_type=PartnershipImageProductType.MF_API,
                thumbnail_url=filename,
                image_status=PartnershipImageStatus.INACTIVE,
                user_id=user_id,
            )
        else:
            document = PartnershipDocument.objects.create(
                document_source=loan.id,
                document_type="mf_std_{}".format(file_type),
                filename=filename,
                document_status=PartnershipImageStatus.INACTIVE,
                user_id=user_id,
            )

        document.url = "mf_cust_{}/loan_{}/{}".format(loan.customer.id, loan.id, filename)

        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_path, document.url)
        document.save()

        if os.path.isfile(local_path):
            os.remove(local_path)

        if file_type == "merchant_photo":
            file_url = document.image_url_external
        else:
            file_url = document.document_url_external

        return None, document.id, file_url

    except Exception as e:
        logger.exception(
            {
                'action': 'upload_document_mf',
                'loan_xid': loan_xid,
                'local_path': local_path,
                'error': e,
            }
        )
        return str(e), "", ""


def write_row_result(
    row: Dict,
    is_success: bool,
    message: str = None,
):
    return [
        is_success,
        row.get('nik'),
        row.get('distributor'),
        row.get('funder'),
        row.get('type'),
        row.get('loan_request_date'),
        row.get('interest_rate'),
        row.get('provision_fee'),
        row.get('financing_amount'),
        row.get('financing_tenure'),
        row.get('installment_number'),
        row.get('invoice_number'),
        row.get('invoice_link'),
        row.get('giro_link'),
        row.get('skrtp_link'),
        row.get('merchant_photo_link'),
        message,
    ]


def process_mf_standard_loan_submission(
    upload_async_state: UploadAsyncState, partner: Partner
) -> bool:
    from juloserver.merchant_financing.services import (
        mf_standard_max_3_platform_check,
        proces_mf_customer_data,
    )

    upload_file = upload_async_state.file
    file_content = upload_file.read().decode('utf-8')

    sniffer = csv.Sniffer()
    delimiter = str(sniffer.sniff(file_content[:CSV_DELIMITER_SIZE]).delimiter)

    f = io.StringIO(file_content)
    reader = csv.DictReader(f, delimiter=delimiter)

    is_disburse_to_distributor = partner.is_disbursement_to_distributor_bank_account
    is_success_all = True
    local_file_path = upload_async_state.file.path

    # Dictionary to keep track of total financing amount per NIK
    financing_amounts_by_nik = {}
    failed_rows_by_nik = {}
    validated_data_list = []
    loan_amount_total_by_nik = {}

    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        with open(file_path, "w", encoding='utf-8-sig') as f:
            write = csv.writer(f)
            write.writerow(MF_STANDARD_LOAN_UPLOAD_HEADERS)

            bank_names = BankManager.get_bank_names()

            # First pass: Validation and checking total financing amounts
            for row in reader:
                clean_row = {key.lower().strip(): value for key, value in row.items()}
                formatted_data = clean_row

                serializer = MFStandardLoanSubmissionSerializer(data=formatted_data)
                errors_validation = serializer.validate()

                if errors_validation:
                    is_success_all = False
                    write_error_message(write, formatted_data, errors_validation)
                    continue

                validated_format_data = serializer.get_validated_data()

                nik = validated_format_data.get(MFStandardProductUploadDetails.NIK)
                financing_amount = validated_format_data.get(
                    MFStandardProductUploadDetails.FINANCING_AMOUNT
                )

                # Initialize financing amount and failure list for the NIK
                if nik not in financing_amounts_by_nik:
                    financing_amounts_by_nik[nik] = 0
                    failed_rows_by_nik[nik] = []
                    loan_amount_total_by_nik[nik] = 0

                partnership_customer_data = (
                    PartnershipCustomerData.objects.select_related(
                        'application__partner',
                        'application__account',
                        'application__product_line',
                        'application__customer',
                    )
                    .filter(nik=nik, partner=partner.id)
                    .first()
                )
                if not partnership_customer_data:
                    is_success_all = False
                    message = "Partnership customer data not found"
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                application = partnership_customer_data.application
                if not application:
                    is_success_all = False
                    message = "Application not found"
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                    is_success_all = False
                    message = 'Application status is not 190'
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                if not application.account:
                    is_success_all = False
                    message = 'Account not found'
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                account = application.account

                if account.status_id not in {
                    AccountConstant.STATUS_CODE.active,
                    AccountConstant.STATUS_CODE.active_in_grace,
                }:
                    is_success_all = False
                    message = 'Account inactive'
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                if not application.partner or not application.partner.is_csv_upload_applicable:
                    is_success_all = False
                    message = "Invalid partner"
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                loans = account.loan_set.all()
                for loan in loans:
                    if loan.loan_status.status_code == LoanStatusCodes.DRAFT:
                        loan_amount_total_by_nik[nik] += loan.loan_amount

                # Adding to financing amounts by NIK
                financing_amounts_by_nik[nik] += financing_amount + loan_amount_total_by_nik[nik]

                # Check available limit
                account_limit = AccountLimit.objects.filter(account=application.account).last()
                if financing_amounts_by_nik[nik] > account_limit.available_limit:
                    is_success_all = False
                    message = "Financing amount cannot be greater than the available limit"
                    write_error_message(write, formatted_data, message)
                    failed_rows_by_nik[nik].append(row)
                    continue

                # Add account to validated format data
                validated_format_data['account'] = application.account

                # If everything is fine, add to validated data list for second pass
                validated_data_list.append((validated_format_data, application))

            # Second pass: Process the validated data
            for validated_format_data, application in validated_data_list:
                nik = validated_format_data.get(MFStandardProductUploadDetails.NIK)

                # Skip processing if row is in the failed list for the NIK
                if validated_format_data in failed_rows_by_nik[nik]:
                    continue

                formatted_validated_data = format_validated_data(validated_format_data)

                if is_disburse_to_distributor:
                    is_error = False
                    if application.partner.name != MerchantFinancingCSVUploadPartner.RABANDO:
                        is_error = True
                        message = 'Invalid partner'

                    if is_error:
                        is_success_all = False
                        write_error_message(write, formatted_validated_data, message)
                        continue

                    distributor_id = validated_format_data[
                        MFStandardProductUploadDetails.DISTRIBUTOR
                    ]
                    if not distributor_id:
                        is_success_all = False
                        message = "Distributor not found"
                        write_error_message(write, formatted_validated_data, message)
                        continue

                    partnership_distributor = (
                        PartnershipDistributor.objects.select_related("partner")
                        .filter(distributor_id=int(distributor_id))
                        .first()
                    )
                    if not partnership_distributor:
                        is_success_all = False
                        message = "Partnership distributor not found"
                        write_error_message(write, formatted_validated_data, message)
                        continue

                    bank_name = partnership_distributor.bank_name
                    if bank_name not in bank_names:
                        is_success_all = False
                        message = "Bank name not valid"
                        write_error_message(write, formatted_validated_data, message)
                        continue

                    bank = Bank.objects.filter(bank_name=bank_name).first()
                    if not bank:
                        is_success_all = False
                        message = "Bank name not found"
                        write_error_message(write, formatted_validated_data, message)
                        continue

                    distributor_bank_account_number = (
                        partnership_distributor.distributor_bank_account_number
                    )
                    mobile_phone = partnership_distributor.partner.phone
                    name_in_bank = partnership_distributor.distributor_name

                    bank_account_destination = BankAccountDestination.objects.filter(
                        account_number=application.bank_account_number,
                        customer=application.customer,
                        bank_account_category__category=BankAccountCategoryConst.SELF,
                    ).last()
                    validate_bank_data = {
                        'bank_name': bank_name,
                        'account_number': distributor_bank_account_number,
                        'name_in_bank': name_in_bank,
                        'mobile_phone': mobile_phone,
                    }

                    is_success = True
                    if bank_account_destination:
                        name_bank_validation = bank_account_destination.name_bank_validation
                        is_same_account_number = (
                            bank_account_destination.account_number
                            == distributor_bank_account_number
                        )
                        is_same_bank_name = (
                            True if bank and bank_account_destination.bank == bank else False
                        )
                        is_same_name_bank_validation = (
                            name_bank_validation.account_number == distributor_bank_account_number
                        )

                        if (
                            not is_same_account_number
                            or not is_same_bank_name
                            or not is_same_name_bank_validation
                        ):
                            is_success, message = proces_mf_customer_data(
                                validate_bank_data, application
                            )
                    else:
                        is_success, message = proces_mf_customer_data(
                            validate_bank_data, application
                        )

                    if not is_success:
                        is_success_all = False
                        write_error_message(write, formatted_validated_data, message)
                        continue

                # SEOJK Update -> max 3 platform checking
                if application:
                    is_error, message = mf_standard_max_3_platform_check(application, partner)
                    if is_error:
                        is_success_all = False
                        write_error_message(write, formatted_validated_data, message)
                        continue

                is_success, message = mf_standard_loan_creation(
                    validated_format_data, application, partner
                )

                write.writerow(
                    write_row_result(
                        formatted_validated_data,
                        is_success,
                        message,
                    )
                )
                if not is_success:
                    is_success_all = False

        mf_standard_loan_submission_upload_csv_data_to_oss(upload_async_state, file_path=file_path)
    return is_success_all


def format_validated_data(validated_data):
    formatted_data = validated_data.copy()
    formatted_data['loan_request_date'] = validated_data['loan_request_date'].strftime('%d/%m/%Y')
    formatted_data['interest_rate'] = str(validated_data['interest_rate'])
    formatted_data['provision_rate'] = str(validated_data['provision_fee'])
    formatted_data['financing_amount'] = str(validated_data['financing_amount'])
    formatted_data['financing_tenure'] = str(validated_data['financing_tenure'])
    formatted_data['installment_number'] = str(validated_data['installment_number'])
    return formatted_data


def write_error_message(write, formatted_data, message):
    is_success = False
    write.writerow(
        write_row_result(
            formatted_data,
            is_success,
            message,
        )
    )


def mf_standard_loan_creation(validated_format_data, application, partner):
    nik = validated_format_data.get(MFStandardProductUploadDetails.NIK)
    distributor_id = validated_format_data.get(MFStandardProductUploadDetails.DISTRIBUTOR)
    funder = validated_format_data.get(MFStandardProductUploadDetails.FUNDER)
    loan_type = validated_format_data.get(MFStandardProductUploadDetails.TYPE)
    loan_request_date = validated_format_data.get(MFStandardProductUploadDetails.LOAN_REQUEST_DATE)
    interest_rate_request = validated_format_data.get(MFStandardProductUploadDetails.INTEREST_RATE)
    provision_rate_request = validated_format_data.get(
        MFStandardProductUploadDetails.PROVISION_RATE
    )
    loan_amount_request = validated_format_data.get(MFStandardProductUploadDetails.FINANCING_AMOUNT)
    loan_duration = validated_format_data.get(MFStandardProductUploadDetails.FINANCING_TENURE)
    installment_number = validated_format_data.get(
        MFStandardProductUploadDetails.INSTALLMENT_NUMBER
    )
    invoice_number = validated_format_data.get(MFStandardProductUploadDetails.INVOICE_NUMBER)
    account = validated_format_data.get('account')

    application.update_safely(
        job_type="Pengusaha", company_name=partner.name, job_industry="Pedagang"
    )

    mobile_number = application.mobile_phone_1
    if mobile_number:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=LoanJuloOneConstant.PHONE_NUMBER_BLACKLIST, is_active=True
        ).last()
        if feature_setting:
            params = feature_setting.parameters
            blacklist_phone_number = params['blacklist_phone_numnber']
            if mobile_number in blacklist_phone_number:
                return False, "Invalid phone number"

    is_manual_skrtp = False
    partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=MFFeatureSetting.MF_MANUAL_SIGNATURE, is_active=True
    ).first()

    if partnership_feature_setting:
        for param in partnership_feature_setting.parameters:
            if param.get('is_manual') and param.get('partner_id') == partner.id:
                is_manual_skrtp = True
                break

    invoice_link = validated_format_data.get(MFStandardProductUploadDetails.INVOICE_LINK)
    giro_link = validated_format_data.get(MFStandardProductUploadDetails.GIRO_LINK)
    skrtp_link = validated_format_data.get(MFStandardProductUploadDetails.SKRTP_LINK)
    merchant_photo_link = validated_format_data.get(
        MFStandardProductUploadDetails.MERCHANT_PHOTO_LINK
    )
    invoice_file_path = ""
    giro_file_path = ""
    skrtp_file_path = ""
    merchant_photo_file_path = ""
    if invoice_link:
        err, invoice_file_path = validate_file_from_url_including_restricted_file(invoice_link)
        if err:
            return False, err

    if giro_link:
        if not invoice_link:
            return False, "Must upload Invoice files as well, other than the SKRTP/Giro"
        err, giro_file_path = validate_file_from_url_including_restricted_file(giro_link)
        if err:
            return False, err

    if skrtp_link:
        if not invoice_link:
            return False, "Must upload Invoice files as well, other than the SKRTP/Giro"
        if not merchant_photo_link:
            return False, "Must upload SKRTP & merchant photo link together"
        if not is_manual_skrtp:
            return False, "Manual SKRTP is not available for this partner"
        err, skrtp_file_path = validate_file_from_url_including_restricted_file(skrtp_link)
        if err:
            return False, err

    if merchant_photo_link:
        if not invoice_link:
            return False, "Must upload Invoice files as well, other than the SKRTP/Giro"
        if not skrtp_link:
            return False, "Must upload SKRTP & merchant photo link together"
        err, merchant_photo_file_path = validate_file_from_url_including_restricted_file(
            merchant_photo_link
        )
        if err:
            return False, err

    self_bank_account = True
    if (
        partner.is_disbursement_to_partner_bank_account
        or partner.is_disbursement_to_distributor_bank_account
    ):
        self_bank_account = False

    data = dict(
        loan_amount_request=loan_amount_request,
        account_id=account.id,
        loan_duration=loan_duration,
        bank_account_number=application.bank_account_number,
        self_bank_account=self_bank_account,
    )

    decimal_interest_rate_request = Decimal(str(interest_rate_request))
    decimal_one_hundred = Decimal('100')
    decimal_twelve = Decimal('12')

    interest_rate = provision_rate = 0
    if interest_rate_request:
        interest_rate = (decimal_interest_rate_request / decimal_one_hundred) * decimal_twelve
    if provision_rate_request:
        provision_rate = provision_rate_request / 100

    # get product lookup
    product_lookup = ProductLookup.objects.filter(
        interest_rate=interest_rate,
        origination_fee_pct=provision_rate,
        product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
        product_profile__name=partner.name,
    ).last()
    if not product_lookup:
        return False, "Product lookup not found"

    if data['loan_duration'] != application.product_line.max_duration and partner.name == DAGANGAN:
        return False, 'The tenor is not {} days'.format(application.product_line.max_duration)

    if partner.name in VALIDATE_PARTNER_PRODUCT_LINE:
        if (
            data['loan_amount_request'] < application.product_line.min_amount
            or data['loan_amount_request'] > application.product_line.max_amount
        ):
            return False, 'Financing Amount (Rp) must be greater than {} and less than {}'.format(
                display_rupiah(application.product_line.min_amount),
                display_rupiah(application.product_line.max_amount),
            )

    loan_amount = get_loan_amount_by_transaction_type(
        loan_amount_request, provision_rate, data['self_bank_account']
    )

    if distributor_id:
        partnership_distributor = PartnershipDistributor.objects.filter(
            distributor_id=distributor_id,
            is_deleted=False,
        ).last()
    else:
        partnership_distributor = PartnershipDistributor.objects.filter(
            partner=partner.id,
            is_deleted=False,
        ).last()
    if not partnership_distributor:
        return False, "Partnership distributor not found"

    partnership_flow_flag = PartnershipFlowFlag.objects.filter(
        name=PartnershipFlag.DISBURSEMENT_CONFIGURATION,
        partner=partner.id,
    ).last()
    if (
        partnership_flow_flag
        and partnership_flow_flag.configs
        and partnership_flow_flag.configs.get('disburse_to_merchant')
    ):
        # get bank account destination
        bank_account_destination = BankAccountDestination.objects.filter(
            name_bank_validation=application.name_bank_validation,
        ).last()
        if not bank_account_destination:
            return False, "Bank account destination not found"
    else:
        # get bank account destination
        bank_account_destination = BankAccountDestination.objects.filter(
            id=partnership_distributor.bank_account_destination_id,
        ).last()
        if not bank_account_destination:
            return False, "Bank account destination not found"

    # validate installment number and tenure
    if loan_duration % installment_number != 0:
        return False, "Financing tenure divided into instalment number is not valid"

    days_delta_each_payment = loan_duration // installment_number
    first_payment_date = loan_request_date + relativedelta(days=days_delta_each_payment)

    interest_rate_monthly = Decimal(str(product_lookup.interest_rate)) / decimal_twelve
    loan_requested = dict(
        loan_amount=int(loan_amount),
        original_loan_amount_requested=loan_amount_request,
        loan_duration_request=data['loan_duration'],
        interest_rate_monthly=float(interest_rate_monthly),
        is_buku_warung=True if partner == MerchantFinancingCSVUploadPartner.BUKUWARUNG else False,
        product_lookup=product_lookup,
        provision_fee=product_lookup.origination_fee_pct,
        is_withdraw_funds=data['self_bank_account'],
        is_loan_amount_adjusted=True,
        is_dagangan=True if partner == MerchantFinancingCSVUploadPartner.DAGANGAN else False,
        loan_duration_type=LoanDurationType.DAYS,
        nik=nik,
        partnership_distributor=partnership_distributor,
        funder=funder,
        loan_type=loan_type,
        loan_request_date=loan_request_date,
        installment_number=installment_number,
        invoice_number=invoice_number,
        partner_id=partner.id,
        interest_rate=product_lookup.interest_rate,
        financing_tenure=loan_duration,
        bank_account_destination=bank_account_destination,
        first_payment_date=first_payment_date,
        is_manual_skrtp=is_manual_skrtp,
        invoice_file_path=invoice_file_path,
        giro_file_path=giro_file_path,
        skrtp_file_path=skrtp_file_path,
        merchant_photo_file_path=merchant_photo_file_path,
    )

    try:
        with transaction.atomic():
            loan = mf_standard_loan_creation_process(application, loan_requested)
            update_available_limit(loan)
    except Exception as e:
        return False, str(e)

    loan.refresh_from_db()

    return (
        True,
        "Success loan creation with loan_id: {} and application_id: {}.".format(
            loan.id, application.id
        ),
    )


def mf_standard_loan_creation_process(application, loan_requested):
    first_installment_amount = 0
    installment_each_payment = 0
    interest_each_payment = 0
    principal_each_payment = 0
    interest_rest = 0

    loan_purpose = application.loan_purpose
    financing_tenure = loan_requested['financing_tenure']

    disbursement_amount_provision_fee_deduction_pfs = PartnershipFeatureSetting.objects.filter(
        feature_name=MFFeatureSetting.MF_STANDARD_PRICING,
        is_active=True,
    ).first()

    disbursement_amount_provision_fee_deduction_partner_list = []
    if disbursement_amount_provision_fee_deduction_pfs:
        disbursement_amount_provision_fee_deduction_partner_list = (
            disbursement_amount_provision_fee_deduction_pfs.parameters.get(
                "disbursement_amount_with_provision_fee_deduction"
            )
        )

    is_provision_fee_not_included = False
    if application.partner.name in disbursement_amount_provision_fee_deduction_partner_list:
        is_provision_fee_not_included = True

    if application.partner.name == DAGANGAN:
        loan_amount = loan_requested['loan_amount']
        monthly_interest_rate = loan_requested['interest_rate_monthly']
        loan_requested['loan_duration_in_days'] = financing_tenure

        interest_rate = py2round(monthly_interest_rate / 30 * financing_tenure, 4)
        interest_rest = loan_amount * interest_rate

    else:
        if application.partner.name in VALIDATE_PARTNER_MF_EFISHERY:
            loan_amount = loan_requested['original_loan_amount_requested']
        else:
            loan_amount = loan_requested['loan_amount']

        monthly_interest_rate = loan_requested['interest_rate_monthly']

        (
            first_installment_amount,
            installment_each_payment,
            interest_each_payment,
            principal_each_payment,
        ) = compute_mf_standard_amount(
            loan_requested, loan_amount, monthly_interest_rate, is_provision_fee_not_included
        )

    installment_amount = installment_each_payment
    initial_status = LoanStatusCodes.DRAFT

    # mapping lender_id and partner for Loan
    loan_partner, loan_lender = get_lender_by_partner(application)

    due_date = loan_requested['loan_request_date'] + relativedelta(days=financing_tenure)
    if application.partner.name == DAGANGAN:
        loan_cycle_day = due_date.day
    else:
        loan_cycle_day = application.account.cycle_day

    # set payment method for Loan
    loan_julo_bank_name = loan_julo_bank_account_number = ""
    customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
    if customer_has_vas:
        primary_payment_method = customer_has_vas.filter(is_primary=True).last()
        if primary_payment_method:
            loan_julo_bank_name = primary_payment_method.payment_method_name
            loan_julo_bank_account_number = primary_payment_method.virtual_account

    loan_ever_entered_B5 = False
    if is_new_loan_part_of_bucket5(application.account):
        loan_ever_entered_B5 = True

    loan_disbursement_amount = loan_amount
    provision_amount = compute_loan_calculation_mf_standard(loan_requested)

    if is_provision_fee_not_included:
        loan_disbursement_amount -= round(provision_amount)

    transaction_method = TransactionMethod.objects.get(pk=2)
    loan = Loan.objects.create(
        customer=application.customer,
        loan_status=StatusLookup.objects.get(status_code=initial_status),
        loan_amount=loan_amount,
        loan_duration=financing_tenure,
        first_installment_amount=installment_amount,
        installment_amount=installment_amount,
        bank_account_destination=loan_requested['bank_account_destination'],
        account=application.account,
        loan_purpose=loan_purpose,
        application_id2=application.id,
        transaction_method=transaction_method,
        loan_disbursement_amount=loan_disbursement_amount,
        partner=loan_partner,
        product=loan_requested['product_lookup'],
        lender=loan_lender,
        cycle_day=loan_cycle_day,
        julo_bank_name=loan_julo_bank_name,
        julo_bank_account_number=loan_julo_bank_account_number,
        ever_entered_B5=loan_ever_entered_B5,
    )

    if loan_requested['invoice_file_path']:
        is_success = upload_partnership_document_from_url(
            loan, loan_requested['invoice_file_path'], 'invoice'
        )
        if is_success:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.INACTIVE,
                change_by_id=loan.customer.user.id,
            )
            if not loan_requested['is_manual_skrtp']:
                timestamp = datetime.now()
                execute_after_transaction_safely(
                    lambda: send_email_skrtp.delay(
                        loan_id=loan.id,
                        interest_rate=float(loan_requested['interest_rate']),
                        loan_request_date=loan_requested['loan_request_date'].strftime('%d/%m/%Y'),
                        timestamp=timestamp,
                    )
                )
                execute_after_transaction_safely(
                    lambda: mf_send_sms_skrtp.delay(
                        loan_id=loan.id,
                        timestamp=timestamp,
                    )
                )

    if loan_requested['giro_file_path']:
        upload_partnership_document_from_url(loan, loan_requested['giro_file_path'], 'bilyet')

    if loan_requested['skrtp_file_path'] and loan_requested['merchant_photo_file_path']:
        is_success_skrtp = upload_partnership_document_from_url(
            loan, loan_requested['skrtp_file_path'], 'manual_skrtp'
        )
        is_success_merchant_photo = upload_partnership_document_from_url(
            loan, loan_requested['merchant_photo_file_path'], 'merchant_photo'
        )
        if is_success_skrtp and is_success_merchant_photo:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.LENDER_APPROVAL,
                change_by_id=loan.customer.user.id,
            )
            now = timezone.localtime(datetime.now())
            loan.update_safely(
                sphp_sent_ts=now,
                sphp_accepted_ts=now,
            )
            auto_approval_fs = FeatureSetting.objects.get_or_none(
                is_active=True, feature_name=FeatureNameConst.MF_LENDER_AUTO_APPROVE
            )
            if auto_approval_fs and auto_approval_fs.parameters.get('is_enable'):
                if is_partnership_lender_balance_sufficient(loan, True):
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        change_by_id=loan.customer.user.id,
                        change_reason="Lender auto approve",
                    )
                    loan.refresh_from_db()
                    loan_id = loan.id
                    execute_after_transaction_safely(
                        lambda: merchant_financing_generate_lender_agreement_document_task.delay(
                            loan_id
                        )
                    )

    PartnerLoanRequest.objects.create(
        loan=loan,
        partner=application.partner,
        loan_amount=loan_amount,
        loan_disbursement_amount=loan.loan_disbursement_amount,
        loan_original_amount=loan_amount,
        loan_duration_type=LoanDurationType.DAYS,
        provision_amount=round(provision_amount),
        is_manual_skrtp=loan_requested['is_manual_skrtp'],
        funder=loan_requested['funder'],
        loan_type=loan_requested['loan_type'],
        partnership_distributor=loan_requested['partnership_distributor'],
        invoice_number=loan_requested['invoice_number'],
        installment_number=loan_requested['installment_number'],
        financing_amount=loan_requested['original_loan_amount_requested'],
        financing_tenure=financing_tenure,
        interest_rate=loan_requested['interest_rate'],
        provision_rate=loan_requested['provision_fee'],
        loan_request_date=loan_requested['loan_request_date'],
    )

    payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)

    if application.partner.name == DAGANGAN:
        if application.partner.name in VALIDATE_PARTNER_MF_EFISHERY:
            platform_fee = loan_requested['provision_fee'] * loan_amount
            total_interest = interest_rest + platform_fee
            due_amount = round_rupiah(loan_amount + total_interest)
            loan_requested['loan_amount'] = loan_amount
        else:
            due_amount = loan_requested['loan_amount'] + interest_rest

        Payment.objects.create(
            loan=loan,
            payment_status=payment_status,
            payment_number=1,
            due_date=due_date,
            due_amount=due_amount,
            installment_principal=loan_requested['loan_amount'],
            installment_interest=due_amount - loan_requested['loan_amount'],
        )
        loan.update_safely(first_installment_amount=due_amount, installment_amount=due_amount)

    elif application.partner.due_date_type in {
        MerchantFinancingCSVUploadPartnerDueDateType.MONTHLY,
        MerchantFinancingCSVUploadPartnerDueDateType.END_OF_TENOR,
    }:
        bulk_payment = []
        loan_request_date = loan_requested['loan_request_date']
        installment_number = loan_requested['installment_number']

        days_delta_each_payment = financing_tenure // installment_number

        for payment_number in range(installment_number):
            if payment_number == 0:
                due_date = loan_request_date + timedelta(days=days_delta_each_payment)
                due_amount = first_installment_amount
            else:
                if payment_number == installment_number - 1:
                    # For the last installment
                    due_date = loan_request_date + timedelta(days=financing_tenure)
                else:
                    due_date = loan_request_date + timedelta(
                        days=(days_delta_each_payment * (payment_number + 1))
                    )

                due_amount = installment_each_payment

            installment_interest = interest_each_payment

            payment = Payment(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=due_amount,
                installment_principal=principal_each_payment,
                installment_interest=installment_interest,
            )

            bulk_payment.append(payment)

            loan.update_safely(
                first_installment_amount=payment.due_amount,
                installment_amount=payment.due_amount,
            )

        Payment.objects.bulk_create(bulk_payment, batch_size=25)

    return loan


def upload_partnership_document_from_url(loan, file_path, file_type) -> bool:
    try:
        filename = os.path.basename(file_path)
        file_object = io.FileIO(file_path, 'rb')
        file_ext = os.path.splitext(filename)[1]
        filename = "mf-std-{}-{}{}".format(file_type, loan.id, file_ext)

        if file_type == "merchant_photo":
            document = PartnershipImage.objects.create(
                loan_image_source=loan.id,
                image_type="mf_std_{}".format(file_type),
                product_type=PartnershipImageProductType.MF_API,
                thumbnail_url=filename,
                image_status=PartnershipImageStatus.ACTIVE,
                user_id=loan.customer.user_id,
                image=File(file_object),
            )
            local_filepath = document.image.path
        else:
            document = PartnershipDocument.objects.create(
                document_source=loan.id,
                document_type="mf_std_{}".format(file_type),
                filename=filename,
                document_status=PartnershipImageStatus.ACTIVE,
                user_id=loan.customer.user_id,
                file=File(file_object),
            )
            local_filepath = document.file.path

        document.url = "mf_cust_{}/loan_{}/{}".format(loan.customer.id, loan.id, filename)
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_filepath, document.url)
        logger.info(
            {
                'action': 'upload_partnership_document_from_url',
                'loan_id': loan.id,
                'message': 'uploaded to OSS',
                'document': document,
            }
        )
        document.save()
        return True

    except Exception as e:
        logger.exception(
            {
                'action': 'upload_partnership_document_from_url',
                'loan_xid': loan.loan_xid,
                'file_path': file_path,
                'error': e,
            }
        )
        return False


def mf_standard_loan_submission_upload_csv_data_to_oss(upload_async_state, file_path=None):
    if file_path:
        local_file_path = file_path
    else:
        local_file_path = upload_async_state.file.path

    path_and_name, extension = os.path.splitext(local_file_path)
    file_name_elements = path_and_name.split('/')
    folder_name = 'mf_standard_loan_submission'

    dest_name = "{}_{}/{}".format(
        folder_name, upload_async_state.id, file_name_elements[-1] + extension
    )
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, dest_name)

    if os.path.isfile(local_file_path):
        local_dir = os.path.dirname(local_file_path)
        upload_async_state.file.delete()
        if not file_path:
            os.rmdir(local_dir)

    upload_async_state.update_safely(url=dest_name)


def mf_standard_fdc_inquiry_for_outdated_condition(
    fdc_inquiry_data: dict,
    customer_id: int,
    params: dict,
    retry_count: int = 0,
) -> bool:
    function_name = "mf_standard_fdc_inquiry_for_outdated_condition"
    max_retries = params["fdc_inquiry_api_config"]["max_retries"]
    retry_interval_seconds = params["fdc_inquiry_api_config"]["retry_interval_seconds"]

    while retry_count <= max_retries:
        try:
            partner_fdc_mock_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PARTNERSHIP_FDC_MOCK_RESPONSE_SET,
                is_active=True,
            ).exists()

            if partner_fdc_mock_feature:
                partnership_mock_get_and_save_fdc_data(fdc_inquiry_data)
            else:
                get_and_save_fdc_data(fdc_inquiry_data, 1, False)

            update_fdc_active_loan_checking(customer_id, fdc_inquiry_data)

            application_id = params["application_id"]
            outdated_threshold_days = params["outdated_threshold_days"]
            number_allowed_platforms = params["number_allowed_platforms"]

            is_eligible, _ = check_eligible_and_out_date_other_platforms(
                customer_id,
                application_id,
                outdated_threshold_days,
                number_allowed_platforms,
            )

            return is_eligible

        except FDCServerUnavailableException:
            logger.error(
                {
                    "action": function_name,
                    "error": "FDC server cannot be reached",
                    "data": fdc_inquiry_data,
                }
            )

        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

            logger.info(
                {
                    "action": function_name,
                    "error": str(e),
                    "data": fdc_inquiry_data,
                }
            )

        # Retry mechanism
        retry_count += 1
        if retry_count > max_retries:
            logger.info(
                {
                    "action": function_name,
                    "message": "Retry FDC Inquiry has exceeded the maximum limit",
                    "data": fdc_inquiry_data,
                    "extra_data": "retry_count={}".format(retry_count),
                }
            )
            return False

        countdown = retry_interval_seconds * retry_count
        logger.info(
            {
                "action": function_name,
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}|count_down={}".format(retry_count, countdown),
            }
        )

        time.sleep(countdown)

    return False

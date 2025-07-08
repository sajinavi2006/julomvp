import json
import base64
import logging

import pdfkit
from babel.dates import format_date
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.template.loader import render_to_string
from django.utils import timezone

from datetime import timedelta

from requests.exceptions import Timeout
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.grab.clients.paths import GrabPaths
from juloserver.julo.workflows2.tasks import signature_method_history_task_julo_one
from juloserver.julo.models import (
    Bank,
    SepulsaTransaction,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.grab.models import GrabCustomerData
from juloserver.grab.clients.clients import GrabClient, send_grab_api_timeout_alert_slack
from juloserver.grab.exceptions import GrabApiException
from juloserver.julo.exceptions import JuloException
from juloserver.disbursement.models import NameBankValidation
from juloserver.loan.models import (
    SphpContent,
    PaidLetterNote,
    RepaymentPaidLetter,
)
from juloserver.loan.constants import (
    FORBIDDEN_LOAN_PURPOSES,
)
from juloserver.account.services.account_related import risky_change_phone_activity_check

from juloserver.qris.services.legacy_service import QrisService
from .delayed_disbursement_related import get_delay_disbursement

from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo.utils import display_rupiah, get_file_from_oss
from juloserver.loan_refinancing.utils import convert_number_to_word
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import (
    WaiverPaymentRequest,
)
from ...ecommerce.juloshop_service import get_juloshop_transaction_by_loan
from juloserver.fraud_security.services import loan_fraud_block
from ...loan_refinancing.services.loan_related2 import get_refinanced_r1r2r3_payments
from juloserver.loan.tasks.lender_related import (
    loan_lender_approval_process_task,
    process_loan_fdc_other_active_loan_from_platforms_task,
)
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.disbursement.constants import DisbursementVendors

from juloserver.channeling_loan.constants import ChannelingConst
from juloserver.channeling_loan.tasks import (
    send_loans_for_channeling_to_dbs_task,
)

logger = logging.getLogger(__name__)


def accept_julo_sphp(loan, signature_method, is_success_digisign=None):
    from juloserver.merchant_financing.tasks import (
        upload_sphp_loan_merchant_financing_to_oss,
    )
    from juloserver.grab.services.loan_related import check_grab_auth_success
    from juloserver.loan.services.loan_related import (
        is_apply_check_other_active_platforms_using_fdc,
    )
    from juloserver.antifraud.services.binary_checks import get_anti_fraud_binary_check_status

    user = loan.customer.user
    check_predisbursal_check_grab(loan)
    new_loan_status = LoanStatusCodes.LENDER_APPROVAL
    signature_method_history_task_julo_one(loan.id, signature_method)
    # double hit api prevention to raise Exception
    loan.refresh_from_db()
    if loan.status == LoanStatusCodes.LENDER_APPROVAL:
        return new_loan_status
    if loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
        is_auth_called = check_grab_auth_success(loan.id)
        if not is_auth_called:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.LENDER_REJECT,
                change_reason="Auth Signature Check - Failure",
            )
            return
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=new_loan_status,
        change_by_id=user.id,
        change_reason="Digital signature succeed",
    )
    loan.update_safely(sphp_accepted_ts=timezone.now())
    if loan.loan_purpose in FORBIDDEN_LOAN_PURPOSES:
        new_loan_status = LoanStatusCodes.LENDER_REJECT
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=new_loan_status,
            change_by_id=user.id,
            change_reason="Force Reject due to loan purpose",
        )
        return new_loan_status
    # Call Delay Disbursement only if 211 or lander approve
    if new_loan_status == LoanStatusCodes.LENDER_APPROVAL:
        get_delay_disbursement(loan, loan.sphp_accepted_ts)

    account_workflow = loan.account.account_lookup.workflow.name
    if new_loan_status == LoanStatusCodes.LENDER_APPROVAL:
        application = loan.account.last_application
        if loan.transaction_method and (
            account_workflow == WorkflowConst.JULO_STARTER
            or account_workflow == WorkflowConst.JULO_ONE
        ):
            binary_check_result = get_anti_fraud_binary_check_status(
                status=loan.loan_status_id, application_id=application.id, loan_id=loan.id
            )
            logger.info(
                {
                    "action": "loan.services.accept_julo_sphp",
                    "message": "binary_check_result",
                    "application_id": application.id,
                    "loan_id": loan.id,
                    "binary_check_result": binary_check_result,
                },
            )
            if binary_check_result.is_loan_block:
                new_loan_status = loan_fraud_block(
                    application=application,
                    account=application.account,
                    loan=loan,
                    binary_check_status=binary_check_result,
                )
                return new_loan_status

        risky_change_phone_activity = risky_change_phone_activity_check(loan, application)
        if risky_change_phone_activity:
            return new_loan_status

    update_payments_for_grab(loan)
    if account_workflow == WorkflowConst.MERCHANT_FINANCING_WORKFLOW:
        upload_sphp_loan_merchant_financing_to_oss.apply_async((loan.id,), countdown=30)

    is_mf_partner_max_3_platform_check = False
    partnership_mf_is_max_3_platform_check = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC,
        is_active=True,
    ).last()
    if partnership_mf_is_max_3_platform_check:
        application = loan.account.last_application
        if application.partner and application.partner.is_csv_upload_applicable:
            is_mf_partner_max_3_platform_check = True

    if (
        loan.is_j1_or_jturbo_loan()
        and is_apply_check_other_active_platforms_using_fdc(
            loan.account.get_active_application().pk,
            transaction_method_id=loan.transaction_method_id,
        )
        or is_mf_partner_max_3_platform_check
    ):
        process_loan_fdc_other_active_loan_from_platforms_task.delay(
            loan.pk, is_mf_partner_max_3_platform_check
        )
        return new_loan_status

    # Check is channeling
    lender = loan.lender
    if lender and loan.status == LoanStatusCodes.LENDER_APPROVAL:
        if lender.lender_name == ChannelingConst.LENDER_DBS and lender.is_pre_fund_channeling_flow:
            send_loans_for_channeling_to_dbs_task.delay(loan_ids=[loan.id])
            return new_loan_status

    loan_lender_approval_process_task.delay(loan.id, is_success_digisign)
    return new_loan_status


def cancel_loan(loan):
    if loan.transaction_method_id == TransactionMethodCode.CREDIT_CARD.code:
        return
    user = loan.customer.user
    new_loan_status = LoanStatusCodes.CANCELLED_BY_CUSTOMER
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=new_loan_status,
        change_by_id=user.id,
        change_reason="Customer request to cancel",
    )
    if loan.is_qris_product:
        qris_service = QrisService(loan.account)
        qris_service.update_qr_payment_cancel(loan.qris_transaction)

    return new_loan_status


def update_payments_for_grab(loan):
    from juloserver.grab.services.services import GrabLoanService
    if not loan.account.is_grab_account():
        return
    payments = loan.payment_set.all().order_by('payment_number')
    application = loan.account.last_application
    payday = None
    if application:
        if application.payday:
            payday = application.payday
    if not payday:
        payday = 1
    default_timedelta = GrabLoanService.get_timedelta_in_days_for_new_loans()
    for idx, payment in enumerate(payments):
        time_delta = (idx * payday) + default_timedelta
        due_date = timezone.localtime(timezone.now()) + timedelta(days=time_delta)
        payment.update_safely(due_date=due_date)


def check_predisbursal_check_grab(loan):
    if not loan.account:
        return
    if not loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
        return
    customer = loan.customer
    grab_customer = GrabCustomerData.objects.filter(customer=customer).last()
    if grab_customer:
        name_bank_validation = NameBankValidation.objects.get_or_none(
            pk=loan.name_bank_validation_id
        )
        if not name_bank_validation:
            raise JuloException(
                {
                    'action': 'loan_lender_approval_process',
                    'message': 'Name Bank Validation Not Found!!',
                    'loan_id': loan.id,
                }
            )
        bank_code = name_bank_validation.bank_code
        swift_bank_code = ''
        if bank_code:
            filter_param = {}
            if name_bank_validation.method == DisbursementVendors.PG:
                filter_param['id'] = name_bank_validation.bank_id
            else:
                filter_param["xfers_bank_code"] = bank_code

            swift_bank_code = Bank.objects.filter(**filter_param).last()
            if swift_bank_code:
                swift_bank_code = swift_bank_code.swift_bank_code
            else:
                swift_bank_code = ''
        try:
            response = GrabClient().get_pre_disbursal_check(
                phone_number=grab_customer.phone_number,
                bank_code=swift_bank_code,
                bank_account_number=name_bank_validation.account_number,
                application_id=loan.account.last_application.id,
                customer_id=customer.id,
                loan_id=loan.id,
            )
            response_data = json.loads(response.content)
            if 'data' not in response_data:
                update_loan_status_and_loan_history(
                    loan.id,
                    LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    change_reason='Predisbursal Failed - Bank Invalid v1',
                )
                raise GrabApiException("Predisbursal check API Failed")
            if response_data['data']['code']:
                update_loan_status_and_loan_history(
                    loan.id,
                    LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    change_reason='Predisbursal Failed - Bank Invalid v2',
                )
                raise JuloException(
                    {
                        'action': 'loan_lender_approval_process',
                        'message': 'Predisbursal check failed for customer',
                        'loan_id': loan.id,
                    }
                )
        except Timeout as e:
            default_url = GrabPaths.PRE_DISBURSAL_CHECK
            if e.response:
                send_grab_api_timeout_alert_slack.delay(
                    response=e.response,
                    uri_path=e.request.url if e.request else default_url,
                    application_id=loan.account.last_application.id,
                    customer_id=loan.account.last_application.customer.id,
                    loan_id=loan.id,
                )
            else:
                send_grab_api_timeout_alert_slack.delay(
                    uri_path=e.request.url if e.request else default_url,
                    application_id=loan.account.last_application.id,
                    customer_id=loan.account.last_application.customer.id,
                    loan_id=loan.id,
                    err_message=str(e) if e else None,
                )


def get_loan_type_sphp_content(loan):
    transaction_method = loan.transaction_method_id
    sphp_content = SphpContent.objects.filter(
        sphp_variable="loan_type",
        criteria={"transaction_method_id": [transaction_method]},
        product_line=loan.product.product_line,
    ).last()
    if not sphp_content:
        return 'pinjaman tunai'

    loan_type = sphp_content.message
    if transaction_method in TransactionMethodCode.not_show_product_skrtp():
        return loan_type

    sepulsa_transaction = SepulsaTransaction.objects.get_or_none(loan=loan)
    if sepulsa_transaction:
        if transaction_method == TransactionMethodCode.LISTRIK_PLN.code:
            return "{} {}".format(
                loan_type, sepulsa_transaction.product.product_name.replace('Tagihan', '')
            )
        return "{} {}".format(loan_type, sepulsa_transaction.product.product_name)

    elif transaction_method == TransactionMethodCode.E_COMMERCE.code:
        # ecommerce is juloshop don't have bank account destination
        juloshop_transaction = get_juloshop_transaction_by_loan(loan)
        if juloshop_transaction:
            return "{} {}".format(loan_type, juloshop_transaction.seller_name)
        return "{} {}".format(loan_type, loan.bank_account_destination.description)

    return loan_type


def generate_paid_off_letters(loans):
    static_context = {
        'header_image': settings.PAID_LETTER_STATIC_FILE_PATH + 'header-pattern.svg',
        'logo_image': settings.PAID_LETTER_STATIC_FILE_PATH + 'logo-horizontal.svg',
        'stample_image': settings.PAID_LETTER_STATIC_FILE_PATH + 'stample.jpg',
    }
    paid_off_letters_files = []
    pdf_options = {
        'page-size': 'A4',
        'margin-top': '0.5in',
        'margin-right': '0in',
        'margin-bottom': '0.5in',
        'margin-left': '0in',
    }
    with transaction.atomic():
        # Use the first loan for common customer details
        first_loan = loans[0]
        customer = first_loan.customer
        application = first_loan.get_application
        is_grab = first_loan.account.is_grab_account()
        loan_ids = []

        context = {
            'fullname': application.fullname,
            'full_address': application.complete_addresses,
            'date_today': format_date(
                timezone.localtime(timezone.now()).date(), 'd MMMM yyyy', locale='id_ID'
            ),
            'loans': [],  # Will contain all loans data
        }
        template_name = 'j1_paid_letter_format.html'
        subject_title = 'Surat Pelunasan Nasabah J1'

        # Change template if it's a Grab account
        if is_grab:
            subject_title = 'Surat Pelunasan Nasabah Grab'
            template_name = 'grab_paid_letter_format.html'

        # Process each loan
        for loan in loans:
            loan_ids.append(str(loan.loan_xid))
            loan_data = {
                'sphp_number': loan.loan_xid,
                'loan_disbursement_date': format_date(
                    loan.disbursement_date, 'd MMMM yyyy', locale='id_ID'
                ),
            }

            if is_grab:
                payments = loan.payment_set.filter(
                    payment_status__in=PaymentStatusCodes.paid_status_codes()
                ).order_by('due_date')

                loan_data.update(
                    {
                        'loan_amount': display_rupiah(loan.loan_amount),
                        'loan_duration': loan.loan_duration,
                        'installment_date_until': "{} - {}".format(
                            format_date(payments.first().due_date, 'd MMMM yyyy', locale='id_ID'),
                            format_date(payments.last().due_date, 'd MMMM yyyy', locale='id_ID'),
                        ),
                        'installment_amount': display_rupiah(loan.installment_amount),
                    }
                )
            else:
                payments = (
                    loan.payment_set.only('due_date', 'paid_date', 'paid_amount')
                    .normal()
                    .filter(payment_status__in=PaymentStatusCodes.paid_status_codes())
                    .order_by('due_date')
                )

                loan_data.update(
                    {
                        'transaction_detail': loan.transaction_detail_for_paid_letter,
                        'loan_duration': convert_number_to_word(len(payments)),
                        'loan_disbursement_amount': display_rupiah(
                            loan.loan_disbursement_amount,
                        ),
                    }
                )

                refinanced_r1r2r3_payments, program_description = get_refinanced_r1r2r3_payments(
                    payments, loan
                )
                payment_details = []
                for index, payment in enumerate(payments):
                    description = '-'
                    payment_event_types = (
                        payment.paymentevent_set.filter(
                            event_type__in=(
                                'payment',
                                'waive_interest',
                                'waive_late_fee',
                                'waive_principal',
                            )
                        )
                        .values('event_type')
                        .annotate(total_amount=Sum('event_payment'))
                    )
                    payment_detail = next(
                        (data for data in payment_event_types if data['event_type'] == 'payment'),
                        None,
                    )
                    activated_status = CovidRefinancingConst.STATUSES.activated
                    if payment in refinanced_r1r2r3_payments:
                        description = program_description
                    else:
                        waiver_payment_req = WaiverPaymentRequest.objects.filter(
                            payment=payment,
                            waiver_request__loan_refinancing_request__status=activated_status,
                        ).last()
                        if waiver_payment_req:
                            if next(
                                (
                                    data
                                    for data in payment_event_types
                                    if 'waive_' in data['event_type']
                                ),
                                None,
                            ):
                                description = 'Pelunasan dengan diskon'
                                if (
                                    payment_detail
                                    and payment_detail['total_amount'] > 0
                                    and index + 1 < len(payments)
                                ):
                                    description = 'Pembayaran dengan diskon'

                    payment_details.append(
                        dict(
                            payment_number=index + 1,
                            due_date=format_date(payment.due_date, 'd MMMM yyyy', locale='id_ID'),
                            amount=display_rupiah(
                                payment_detail['total_amount'] if payment_detail else 0
                            ),
                            payment_date=format_date(
                                payment.paid_date, 'd MMMM yyyy', locale='id_ID'
                            ),
                            description=description,
                        )
                    )
                loan_data['payment_details'] = payment_details
                context['loans'].append(loan_data)

        # Create a repayment letter for the first loan to get the reference number
        first_letter = RepaymentPaidLetter.objects.create(loan=first_loan, subject=subject_title)
        reference_number = first_letter.reference_number

        # Create letters for the rest of the loans with the same reference number
        for loan in loans[1:]:
            RepaymentPaidLetter.objects.create(
                loan=loan, subject=subject_title, reference_number=reference_number
            )

        context['reference_number'] = reference_number
        context.update(static_context)

        # Generate single PDF for all loans
        template = render_to_string(template_name, context=context)
        paid_off_letter_pdf = pdfkit.from_string(template, False, options=pdf_options)
        paid_off_letters_files.append(
            ('SKL_{}_{}.pdf'.format(customer.fullname, "_".join(loan_ids)), paid_off_letter_pdf)
        )

    return paid_off_letters_files


def write_download_paid_letter_history(loans, user):
    paid_letter_history = []
    for loan in loans:
        paid_letter_history.append(
            PaidLetterNote(
                loan=loan,
                added_by=user,
                note_text="{} paid letter has been generated".format(loan.id),
            )
        )

    PaidLetterNote.objects.bulk_create(paid_letter_history)


def get_update_skrtp_email_template(application):
    template = 'update_skrtp_email.html',
    context = {
        'fullname_with_title': application.fullname_with_title,
    }

    return render_to_string(template, context=context)


def get_pdf_file_attachment(document):
    document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, document.url)
    content = base64.b64encode(document_stream.read()).decode('utf-8')

    attachment_dict = {
        "content": content,
        "filename": document.filename,
        "type": "application/pdf",
    }
    return attachment_dict

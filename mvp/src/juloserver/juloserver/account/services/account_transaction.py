import logging

from django.db import transaction
from django.db.models import Sum, F
from django.conf import settings
from django.utils import timezone

from juloserver.account.models import Account, AccountTransaction
from juloserver.account.utils import get_first_12_digits
from juloserver.account_payment.models import AccountPayment
from juloserver.customer_module.services.bank_account_related import (
    is_ecommerce_bank_account,
)
from juloserver.disbursement.models import Disbursement
from juloserver.healthcare.models import HealthcareUser
from juloserver.julo.models import Loan, SepulsaTransaction, StatusLookup, Payment
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
    TransactionMethodCode,
)
from juloserver.qris.models import QrisPartnerTransaction
from juloserver.waiver.services.waiver_related import automate_late_fee_waiver_for_j1
from juloserver.ecommerce.juloshop_service import (
    get_juloshop_loan_product_details,
    get_juloshop_transaction_by_loan,
)
from juloserver.julo_financing.constants import (
    JFINACNING_FE_PRODUCT_CATEGORY,
    JFINANCING_VENDOR_NAME,
)

logger = logging.getLogger(__name__)

active_loan_status = [
    StatusLookup.CURRENT_CODE,
    StatusLookup.LENDER_APPROVAL,
    StatusLookup.FUND_DISBURSAL_ONGOING,
    StatusLookup.MANUAL_FUND_DISBURSAL_ONGOING,
    StatusLookup.LOAN_1DPD_CODE,
    StatusLookup.LOAN_5DPD_CODE,
    StatusLookup.LOAN_30DPD_CODE,
    StatusLookup.LOAN_60DPD_CODE,
    StatusLookup.LOAN_90DPD_CODE,
    StatusLookup.LOAN_120DPD_CODE,
    StatusLookup.LOAN_150DPD_CODE,
    StatusLookup.LOAN_180DPD_CODE,
    StatusLookup.RENEGOTIATED_CODE,
    StatusLookup.FUND_DISBURSAL_FAILED,
]

inactive_loan_status = [StatusLookup.PAID_OFF_CODE]


def update_account_transaction_towards_late_fee(payment_event):
    with transaction.atomic():
        account_payment = AccountPayment.objects.select_for_update().get(
            pk=payment_event.payment.account_payment.id
        )
        account_payment.update_late_fee_amount(payment_event.event_payment)
        account_transaction, created = AccountTransaction.objects.get_or_create(
            account=payment_event.payment.account_payment.account,
            transaction_date=payment_event.event_date,
            transaction_type='late_fee',
            defaults={
                'transaction_amount': 0,
                'towards_latefee': 0,
                'towards_principal': 0,
                'towards_interest': 0,
                'accounting_date': payment_event.event_date,
            },
        )
        if created:
            account_transaction.transaction_amount = payment_event.event_payment
            account_transaction.towards_latefee = payment_event.event_payment
        else:
            account_transaction.transaction_amount += payment_event.event_payment
            account_transaction.towards_latefee += payment_event.event_payment
        account_transaction.save(update_fields=['transaction_amount', 'towards_latefee'])
        payment_event.account_transaction = account_transaction
        payment_event.save(update_fields=['account_transaction'])
        automate_late_fee_waiver_for_j1(
            payment_event.payment.account_payment,
            -payment_event.event_payment,
            payment_event.payment,
            payment_event.event_date,
        )
        return True


def get_loans(request):
    from juloserver.balance_consolidation.services import \
        get_balance_consolidation_verification_by_loan

    loans = Loan.objects.filter(customer=request.user.customer).annotate(
        category_product_name=F('transaction_method__fe_display_name'),
        # below fields are for education
        school_name=F('loanstudentregister__student_register__school__name'),
        student_fullname=F('loanstudentregister__student_register__student_fullname'),
        note=F('loanstudentregister__student_register__note'),
    )

    data_type = request.GET.get('type')

    if data_type and data_type == "ACTIVE":
        loans = loans.filter(loan_status__in=active_loan_status)
    elif data_type and data_type == "IN_ACTIVE":
        loans = loans.filter(loan_status__in=inactive_loan_status)

    results = []

    if loans:
        for loan in loans.iterator():
            loan_record = {
                "loan_xid": loan.loan_xid,
                "loan_date": timezone.localtime(loan.cdate),
                "loan_amount": loan.loan_amount,
                "status": loan.loan_status_label if loan.loan_status_label else "Sedang diproses",
                "tenure": loan.loan_duration,
                "liquid_fund": loan.loan_disbursement_amount,
                "fintech_name": None,
                "bank_name": None,
                "bank_account_name": None,
                "bank_account_number": None,
                "bank_reference_number": None,
                "disbursement_date": None,
                "product_type": 1,
                "product_name": None,
                "category_product_name": loan.category_product_name,
                "education_data": None,
                "healthcare_data": None,
                "bank_name_frontend": None,
            }
            if is_ecommerce_bank_account(loan.bank_account_destination):
                loan_record["ecommerce_data"] = dict(
                    product_category='E-commerce',
                    product_kind=loan.bank_account_destination.description,
                    nominal=loan.loan_disbursement_amount,
                    name=loan.get_application.fullname,
                )
            # legacy qris product
            if loan.is_qris_product:
                disbursement_date = (
                    timezone.localtime(loan.fund_transfer_ts) if loan.fund_transfer_ts else None
                )
                loan_record["product_type"] = 9
                loan_record["disbursement_date"] = disbursement_date
                loan_record["qris_data"] = dict(
                    product_category='Scan QR',
                    nominal=loan.qris_transaction.amount,
                    name=loan.qris_transaction.merchant_name,
                )
            # new qris product
            if loan.is_qris_1_product:
                qris_transaction = QrisPartnerTransaction.objects.get(loan_id=loan.id)
                disbursement_date = (
                    timezone.localtime(loan.fund_transfer_ts) if loan.fund_transfer_ts else None
                )

                # use old qris template
                loan_record["product_type"] = TransactionMethodCode.QRIS.code
                loan_record["disbursement_date"] = disbursement_date
                loan_record["qris_data"] = dict(
                    product_category="QRIS",
                    nominal=qris_transaction.total_amount,
                    name=qris_transaction.merchant_name,
                )

            if loan.is_jfinancing_product:
                # use Qris field template for FE
                disbursement_date = (
                    timezone.localtime(loan.fund_transfer_ts) if loan.fund_transfer_ts else None
                )
                loan_record["product_type"] = TransactionMethodCode.QRIS.code
                loan_record["disbursement_date"] = disbursement_date
                loan_record["qris_data"] = dict(
                    product_category=JFINACNING_FE_PRODUCT_CATEGORY,
                    nominal=loan.j_financing_verification.j_financing_checkout.price,
                    name=JFINANCING_VENDOR_NAME,
                )
            if loan.is_credit_card_transaction:
                credit_card_transaction = loan.creditcardtransaction_set.last()
                loan_record["product_type"] = TransactionMethodCode.CREDIT_CARD.code
                loan_record["disbursement_date"] = loan.fund_transfer_ts
                loan_record["julo_card_data"] = dict(
                    product_category='JULO Card',
                    nominal=credit_card_transaction.amount,
                    name=credit_card_transaction.terminal_location,
                )
            if loan.is_healthcare_product:
                healthcare_user = (
                    HealthcareUser.objects.select_related('healthcare_platform')
                    .filter(loans__loan_id=loan.pk)
                    .first()
                )
                loan_record['healthcare_data'] = {
                    'healthcare_platform_name': healthcare_user.healthcare_platform.name,
                    'healthcare_user_fullname': healthcare_user.fullname,
                }

            sepulsa_transaction = SepulsaTransaction.objects.get_or_none(loan=loan)
            if sepulsa_transaction:  # ppob transaction
                loan_record["product_type"] = 2
                # set disbursement date to this since ppob loan
                loan_record["disbursement_date"] = timezone.localtime(sepulsa_transaction.cdate)
                # has no disbursement_id

                loan_record["ppob_data"] = {}

                loan_record["ppob_data"]["product_category"] = sepulsa_transaction.product.category
                loan_record["ppob_data"]["product_kind"] = sepulsa_transaction.product.product_name
                loan_record["ppob_data"]["nominal"] = sepulsa_transaction.customer_price_regular

                if (
                    sepulsa_transaction.product.type == SepulsaProductType.MOBILE
                    or sepulsa_transaction.product.type == SepulsaProductType.EWALLET
                ):
                    loan_record["ppob_data"]["phone_number"] = sepulsa_transaction.phone_number
                    category = sepulsa_transaction.product.category
                    product_category_name = category.replace('_', ' ').title() if category else None
                    if sepulsa_transaction.product.category == SepulsaProductCategory.POSTPAID[0]:
                        product_category_name = 'Kartu Pascabayar'
                        loan_record["ppob_data"]["name"] = sepulsa_transaction.account_name
                        loan_record["ppob_data"]["nominal"] = sepulsa_transaction.customer_amount
                    loan_record["ppob_data"]["product_category_name"] = product_category_name
                    if sepulsa_transaction.product.type == SepulsaProductType.EWALLET:
                        loan_record["ppob_data"][
                            "product_category"
                        ] = sepulsa_transaction.product.type
                        loan_record["ppob_data"]["product_category_name"] = "Dompet Digital"
                elif sepulsa_transaction.product.type == SepulsaProductType.ELECTRICITY:
                    loan_record["ppob_data"]["name"] = sepulsa_transaction.account_name
                    loan_record["ppob_data"]["customer_id"] = sepulsa_transaction.customer_number
                    category = sepulsa_transaction.product.category
                    loan_record["ppob_data"]["type"] = category
                    product_category_name = 'Listrik PLN'
                    if category == SepulsaProductCategory.ELECTRICITY_PREPAID:
                        loan_record["ppob_data"]["token"] = sepulsa_transaction.serial_number
                        product_category_name = 'Token PLN'
                    else:
                        loan_record["ppob_data"]["nominal"] = sepulsa_transaction.customer_amount
                    loan_record["ppob_data"]["product_category_name"] = product_category_name
                elif sepulsa_transaction.product.type == SepulsaProductType.BPJS:
                    loan_record["ppob_data"]["name"] = sepulsa_transaction.account_name
                    loan_record["ppob_data"]["nominal"] = sepulsa_transaction.customer_amount
                    loan_record["ppob_data"]["product_kind"] = "Tagihan {} bulan".format(
                        sepulsa_transaction.paid_period
                    )
                    loan_record["ppob_data"]["id_number"] = sepulsa_transaction.customer_number
                    loan_record["ppob_data"]["product_category_name"] = "BPJS Kesehatan"
                elif sepulsa_transaction.product.type == SepulsaProductType.PDAM:
                    customer_number = sepulsa_transaction.customer_number
                    loan_record["ppob_data"]["nominal"] = loan.loan_amount
                    loan_record["ppob_data"]["customer_number"] = customer_number
                    loan_record["ppob_data"]["customer_name"] = sepulsa_transaction.account_name
                    loan_record["ppob_data"]["serial_number"] = sepulsa_transaction.serial_number
                elif sepulsa_transaction.product.type == SepulsaProductType.TRAIN_TICKET:
                    loan_record["ppob_data"]['customer_name'] = sepulsa_transaction.account_name
                    loan_record["ppob_data"]["nominal"] = loan.loan_amount
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
                    loan_record["ppob_data"]['train_route'] = train_route
            else:  # non ppob transaction
                if loan.bank_account_destination and loan.bank_account_destination.bank:
                    loan_record["bank_name"] = loan.bank_account_destination.bank.bank_name
                    loan_record[
                        "bank_name_frontend"
                    ] = loan.bank_account_destination.bank.bank_name_frontend
                if (
                    loan.bank_account_destination
                    and loan.bank_account_destination.name_bank_validation
                ):
                    loan_record[
                        "bank_account_name"
                    ] = loan.bank_account_destination.name_bank_validation.validated_name
                    loan_record[
                        "bank_account_number"
                    ] = loan.bank_account_destination.name_bank_validation.account_number

                if loan.disbursement_id:
                    disbursement = Disbursement.objects.get_or_none(pk=loan.disbursement_id)
                    cdate = timezone.localtime(disbursement.cdate) if disbursement else None
                    loan_record["disbursement_date"] = cdate

                    if (
                        loan.status >= LoanStatusCodes.CURRENT
                        and disbursement
                        and disbursement.reference_id
                    ):
                        loan_record['bank_reference_number'] = get_first_12_digits(
                            string=disbursement.reference_id
                        )

                juloshop_transaction = get_juloshop_transaction_by_loan(loan)
                if juloshop_transaction:
                    julo_shop_product = get_juloshop_loan_product_details(juloshop_transaction)
                    loan_record["product_name"] = julo_shop_product.get('productName')

                    loan_record["bank_name"] = settings.JULOSHOP_BANK_NAME
                    loan_record["bank_account_name"] = settings.JULOSHOP_ACCOUNT_NAME
                    loan_record["bank_account_number"] = settings.JULOSHOP_BANK_ACCOUNT_NUMBER

                # loan for education
                if loan.school_name:
                    loan_record['education_data'] = {
                        'school_name': loan.school_name,
                        'student_fullname': loan.student_fullname,
                        'note': loan.note,
                    }

            balance_consolidation_verification = \
                get_balance_consolidation_verification_by_loan(loan.id)
            if balance_consolidation_verification is not None:
                balance_consolidation = balance_consolidation_verification.balance_consolidation
                loan_record['fintech_name'] = balance_consolidation.fintech.name

            results.append(loan_record)

    return results


def get_loans_amount(request):
    accounts = Account.objects.filter(customer=request.user.customer)

    loans = None

    data_type = request.GET.get('type')

    if data_type and data_type == "ACTIVE":
        loans = Loan.objects.filter(
            customer=request.user.customer, account__in=accounts, loan_status__in=active_loan_status
        ).aggregate(Sum('loan_amount'))
    elif data_type and data_type == "IN_ACTIVE":
        loans = Loan.objects.filter(
            customer=request.user.customer,
            account__in=accounts,
            loan_status__in=inactive_loan_status,
        ).aggregate(Sum('loan_amount'))
    elif data_type and data_type == "ALL":
        loans = Loan.objects.filter(customer=request.user.customer, account__in=accounts).aggregate(
            Sum('loan_amount')
        )

    return loans["loan_amount__sum"] if loans else 0


def get_payment_list_by_loan(customer, loan_xid):
    payments = (
        Payment.objects.select_related('loan')
        .only(
            'id',
            'payment_number',
            'installment_principal',
            'installment_interest',
            'paid_amount',
            'late_fee_amount',
            'due_date',
            'paid_date',
            'payment_status_id',
            'account_payment_id',
            'due_amount',
            'loan_id',
            'cashback_earned',
            'loan__loan_xid',
            'loan__loan_duration',
        )
        .filter(loan__loan_xid=loan_xid, loan__customer=customer, is_restructured=False)
        .order_by('payment_number')
    )

    payment_data = []
    for payment in payments.iterator():
        installment_number = '{}/{}'.format(
            payment.payment_number,
            payments.count(),
        )
        installment_amount = (
            payment.installment_principal + payment.installment_interest + payment.late_fee_amount
        )
        payment_data.append(
            {
                "payment_id": payment.id,
                "loan_xid": payment.loan.loan_xid,
                "due_date": payment.due_date,
                "installment_amount": installment_amount,
                "total_paid_installment": payment.paid_amount,
                "remaining_installment_amount": payment.due_amount,
                "cashback_earned": payment.cashback_earned,
                "installment_number": installment_number,
                "is_paid": payment.status >= PaymentStatusCodes.PAID_ON_TIME,
            }
        )

    return payment_data

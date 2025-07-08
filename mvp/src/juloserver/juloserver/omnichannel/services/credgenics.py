import logging
from typing import List

from dateutil.parser import parse
from django.utils import timezone

from juloserver.account.services.account_related import get_user_timezone
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.account_payment_related import (
    get_potential_cashback_by_account_payment,
)
from juloserver.credgenics.services.loans import get_credgenics_loans_by_customer_ids_v2
from juloserver.customer_module.services.device_related import get_device_repository
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Customer
from juloserver.julocore.utils import get_timezone_offset_in_seconds
from juloserver.omnichannel.models import (
    AccountPaymentAttribute,
    CustomerAttribute,
    OmnichannelCustomer,
)
from juloserver.omnichannel.services.utils import (
    format_number,
    get_payment_url_raw,
)
from babel.dates import format_date

logger = logging.getLogger(__name__)


def construct_omnichannel_customer_using_credgenics_data(
    customer_ids: List[int],
) -> List[OmnichannelCustomer]:
    device_repo = get_device_repository()
    credgenics_loans = get_credgenics_loans_by_customer_ids_v2(customer_ids)

    account_payment_ids = {credgenics_loan.transaction_id for credgenics_loan in credgenics_loans}
    account_payments = AccountPayment.objects.filter(id__in=account_payment_ids).only(
        'id',
        'account_id',
        'account_payment_xid',
        'due_date',
        'paid_amount',
        'paid_late_fee',
        'paid_interest',
        'paid_principal',
        'ptp_date',
        'paid_date',
    )
    account_payment_map = {
        account_payment.id: account_payment for account_payment in account_payments
    }

    customers = Customer.objects.filter(id__in=customer_ids).only(
        'id', 'customer_xid', 'address_kodepos'
    )
    customer_map = {customer.id: customer for customer in customers}

    now = timezone.now()
    customer_data_map = {}
    logger.info(
        {
            "action": "construct_omnichannel_customer_using_credgenics_data",
            "total_input_customer": len(customer_ids),
            "message": "Start iterating",
        }
    )
    problem_customers = {}
    for credgenics_loan in credgenics_loans:
        customer_id = credgenics_loan.client_customer_id
        try:
            if customer_id not in customer_data_map:
                customer = customer_map.get(customer_id)
                customer_timezone = get_user_timezone(
                    int(customer.address_kodepos) if customer.address_kodepos else 20111
                )
                customer_data_map[customer_id] = OmnichannelCustomer(
                    customer_id=str(customer_id),
                    updated_at=now,
                    customer_attribute=CustomerAttribute(
                        account_id=credgenics_loan.account_id,
                        customer_xid=str(customer.customer_xid),
                        customer_id=credgenics_loan.client_customer_id,
                        sms_firstname=credgenics_loan.sms_firstname,
                        email=credgenics_loan.email,
                        fcm_reg_id=device_repo.get_active_fcm_id(customer.id),
                        mobile_phone=credgenics_loan.mobile_phone_1,
                        timezone_offset=get_timezone_offset_in_seconds(customer_timezone),
                        mobile_phone_2=credgenics_loan.mobile_phone_2,
                        full_name=credgenics_loan.nama_customer,
                        first_name=credgenics_loan.first_name,
                        last_name=credgenics_loan.last_name,
                        title_long=credgenics_loan.title_long,
                        title=credgenics_loan.title,
                        name_with_title=credgenics_loan.name_with_title,
                        company_name=credgenics_loan.nama_perusahaan,
                        company_phone_number=credgenics_loan.telp_perusahaan,
                        position_employees=credgenics_loan.posisi_karyawan,
                        spouse_name=credgenics_loan.nama_pasangan,
                        spouse_mobile_phone=credgenics_loan.no_telp_pasangan,
                        kin_name=credgenics_loan.nama_kerabat,
                        kin_relationship=credgenics_loan.hubungan_kerabat,
                        kin_mobile_phone=credgenics_loan.no_telp_kerabat,
                        address_full=credgenics_loan.alamat,
                        city=credgenics_loan.kota,
                        gender=credgenics_loan.jenis_kelamin,
                        dob=parse(credgenics_loan.tgl_lahir).date()
                        if credgenics_loan.tgl_lahir
                        else None,
                        age=credgenics_loan.age,
                        payday=credgenics_loan.tgl_gajian,
                        loan_purpose=credgenics_loan.tujuan_pinjaman,
                        is_autodebet=credgenics_loan.is_autodebet,
                        is_j1_customer=credgenics_loan.is_j1_customer,
                        bank_code=credgenics_loan.bank_code,
                        bank_code_text=credgenics_loan.bank_code_text,
                        bank_name=credgenics_loan.bank_name,
                        va_method_name=credgenics_loan.va_method_name,
                        va_number=credgenics_loan.va_number,
                        va_bca=credgenics_loan.va_bca,
                        va_permata=credgenics_loan.va_permata,
                        va_maybank=credgenics_loan.va_maybank,
                        va_alfamart=credgenics_loan.va_alfamart,
                        va_indomaret=credgenics_loan.va_indomaret,
                        va_mandiri=credgenics_loan.va_mandiri,
                        product_line_code=str(credgenics_loan.tipe_produk),
                        collection_segment=credgenics_loan.collection_segment,
                        customer_bucket_type=credgenics_loan.customer_bucket_type,
                        cashback_new_scheme_experiment_group=(
                            credgenics_loan.cashback_new_scheme_experiment_group
                        ),
                        active_liveness_score=credgenics_loan.active_liveness_score,
                        passive_liveness_score=credgenics_loan.passive_liveness_score,
                        heimdall_score=credgenics_loan.heimdall_score,
                        orion_score=credgenics_loan.orion_score,
                        fpgw=credgenics_loan.fpgw,
                        shopee_score_status=credgenics_loan.shopee_score_status,
                        shopee_score_list_type=credgenics_loan.shopee_score_list_type,
                        total_loan_amount=credgenics_loan.total_loan_amount,
                        application_similarity_score=credgenics_loan.application_similarity_score,
                        mycroft_score=credgenics_loan.mycroft_score,
                        credit_score=credgenics_loan.credit_score,
                        is_risky=credgenics_loan.is_risky,
                        total_cashback_earned=credgenics_loan.total_seluruh_perolehan_cashback,
                        cashback_amount=credgenics_loan.cashback_amount,
                        cashback_counter=credgenics_loan.cashback_counter,
                        cashback_due_date_slash=credgenics_loan.cashback_due_date_slash,
                        refinancing_prerequisite_amount=credgenics_loan.activation_amount,
                        refinancing_status=credgenics_loan.refinancing_status,
                        refinancing_expire_date=(
                            parse(credgenics_loan.program_expiry_date).date()
                            if credgenics_loan.program_expiry_date
                            else None
                        ),
                        zip_code=credgenics_loan.zip_code,
                        uninstall_indicator=credgenics_loan.uninstall_indicator,
                        fdc_risky=credgenics_loan.fdc_risky,
                        sms_primary_va_name=credgenics_loan.sms_primary_va_name,
                        sms_primary_va_number=credgenics_loan.sms_primary_va_number,
                        last_call_agent=credgenics_loan.last_agent,
                        last_call_status=credgenics_loan.last_call_status,
                        is_email_blocked=credgenics_loan.is_email_blocked,
                        is_sms_blocked=credgenics_loan.is_sms_blocked,
                        is_one_way_robocall_blocked=credgenics_loan.is_one_way_robocall_blocked,
                        partner_name=credgenics_loan.partner_name,
                        google_calendar_url=credgenics_loan.google_calendar_url,
                        account_payment=[],
                    ),
                )

            account_payment = account_payment_map.get(credgenics_loan.transaction_id)
            if not account_payment:
                continue
            potential_cashback = get_potential_cashback_by_account_payment(
                account_payment, credgenics_loan.cashback_counter
            )

            formatted_due_amount = format_number(account_payment.due_amount)
            sms_url = get_payment_url_raw(account_payment)

            account_payment_attribute = AccountPaymentAttribute(
                account_id=credgenics_loan.account_id,
                account_payment_id=int(credgenics_loan.transaction_id),
                account_payment_xid=account_payment.account_payment_xid,
                due_date=account_payment.due_date,
                due_amount=credgenics_loan.angsuran_per_bulan,
                late_fee_amount=credgenics_loan.late_fee,
                principal_amount=credgenics_loan.expected_emi_principal_amount,
                interest_amount=credgenics_loan.expected_emi_interest_amount,
                paid_amount=account_payment.paid_amount,
                paid_late_fee_amount=account_payment.paid_late_fee,
                paid_principal_amount=account_payment.paid_principal,
                paid_interest_amount=account_payment.paid_interest,
                paid_date=account_payment.paid_date,
                status_code=credgenics_loan.status_code,
                ptp_date=account_payment.ptp_date,
                short_ptp_date=credgenics_loan.short_ptp_date,
                ptp_amount=credgenics_loan.ptp_amount,
                ptp_robocall_phone_number=credgenics_loan.ptp_robocall_phone_number,
                is_restructured=credgenics_loan.is_restructured,
                autodebet_retry_count=credgenics_loan.autodebet_retry_count,
                is_collection_called=credgenics_loan.is_collection_called,
                is_ptp_robocall_active=credgenics_loan.is_ptp_robocall_active,
                is_reminder_called=credgenics_loan.is_reminder_called,
                is_success_robocall=credgenics_loan.is_success_robocall,
                is_robocall_active=credgenics_loan.is_robocall_active,
                paid_during_refinancing=credgenics_loan.paid_during_refinancing,
                late_fee_applied=credgenics_loan.late_fee_applied,
                is_paid_within_dpd_1to10=credgenics_loan.is_paid_within_dpd_1to10,
                potential_cashback=potential_cashback,
                sms_month=account_payment.due_date.month,
                month_due_date=str(account_payment.due_date),
                year_due_date=account_payment.due_date.year,
                due_date_long=format_date(account_payment.due_date, 'd MMMM yyyy', locale="id_ID"),
                due_date_short=format_date(account_payment.due_date, 'd MMMM', locale="id_ID"),
                sms_payment_details_url=sms_url,
                formatted_due_amount=formatted_due_amount,
                sort_order=credgenics_loan.internal_sort_order,
            )

            customer_data_map[customer_id].customer_attribute.account_payment.append(
                account_payment_attribute,
            )
        except Exception as e:
            logger.exception(
                {
                    "action": "construct_omnichannel_customer_using_credgenics_data",
                    "message": "Error while processing customer",
                    "customer_id": customer_id,
                    "error": str(e),
                }
            )
            problem_customers[customer_id] = str(e)
            get_julo_sentry_client().capture_exceptions()

    # Update customer with no account_payments
    for customer_id in customer_ids:
        if customer_id in customer_data_map:
            continue

        customer_data_map[customer_id] = OmnichannelCustomer(
            customer_id=str(customer_id),
            updated_at=now,
            customer_attribute=CustomerAttribute(
                customer_id=customer_id,
                account_payment=[],
            ),
        )

    logger.info(
        {
            "action": "construct_omnichannel_customer_using_credgenics_data",
            "total_input_customer": len(customer_ids),
            "problem_customers": problem_customers,
            "message": "Finish construct omnichannel customer data.",
        }
    )
    return list(customer_data_map.values())

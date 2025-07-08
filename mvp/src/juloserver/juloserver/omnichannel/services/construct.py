import logging
from datetime import date, timedelta
from typing import (
    List,
    Union,
    Iterator,
)
from babel.dates import format_date
from django.db.models import (
    Sum,
)
from django.utils import timezone

from juloserver.account.models import Account, ExperimentGroup
from juloserver.account.services.account_related import get_user_timezone
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.account_payment_related import (
    get_potential_and_total_cashback,
    get_potential_cashback_by_account_payment,
)
from juloserver.account_payment.services.earning_cashback import (
    get_cashback_experiment,
    get_paramters_cashback_new_scheme,
)
from juloserver.ana_api.models import (
    PdApplicationFraudModelResult,
    PdCreditEarlyModelResult,
)
from juloserver.apiv2.models import (
    PdCollectionModelResult,
    PdCreditModelResult,
    PdBscoreModelResult,
)
from juloserver.application_flow.models import (
    ShopeeScoring,
)
from juloserver.credgenics.services.utils import (
    get_dpd,
    get_first_last_name,
    get_title_long,
    get_is_risky,
)
from juloserver.customer_module.services.device_related import get_device_repository
from juloserver.face_recognition.models import (
    FaceSearchProcess,
    FaceSearchResult,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Application,
    CommsBlocked,
    CreditScore,
    Customer,
    Loan,
    PaymentMethod,
    PTP,
    FDCRiskyHistory,
)
from juloserver.julo.services import (
    get_google_calendar_for_email_reminder,
)
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
)
from juloserver.julocore.utils import get_timezone_offset_in_seconds

# from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.autodebet.services.account_services import get_active_autodebet_account
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.minisquad.services2.ai_rudder_pds import (
    AIRudderPDSServices,
)
from juloserver.minisquad.services2.dialer_related import (
    get_uninstall_indicator_from_moengage_by_customer_id,
)
from juloserver.omnichannel.models import (
    AccountPaymentAttribute,
    CustomerAttribute,
    OmnichannelCustomer,
)
from juloserver.omnichannel.services.utils import (
    parse_to_datetime,
    format_number,
    get_payment_url_raw,
)
from juloserver.minisquad.constants import (
    DialerSystemConst,
)
from juloserver.minisquad.services import get_exclude_account_ids_collection_field_by_account_ids
from juloserver.ana_api.models import PdCustomerSegmentModelResult

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def construct_omnichannel_customers(
    customer_ids: List[int],
) -> List[OmnichannelCustomer]:

    customers = Customer.objects.filter(id__in=customer_ids)
    customer_dict = {customer.id: customer for customer in customers}
    customer_ids = customer_dict.keys()

    application_ids = [customer.current_application_id for customer in customers]
    applications = Application.objects.filter(id__in=application_ids).select_related('product_line')
    application_dict = {application.customer_id: application for application in applications}
    del customers
    del applications

    accounts = Account.objects.filter(customer_id__in=customer_ids)
    accounts_dict = {account.customer_id: account for account in accounts}
    account_ids = accounts.values_list('id', flat=True)
    account_to_customer_ids = {account.id: account.customer_id for account in accounts}
    del accounts

    account_payments = AccountPayment.objects.filter(
        account_id__in=account_ids,
        due_amount__gt=0,
    ).not_paid_active()
    account_payments_dict = {}
    for account_payment in account_payments:
        cust_id = account_to_customer_ids[account_payment.account_id]
        if cust_id not in account_payments_dict:
            account_payments_dict[cust_id] = []
        account_payments_dict[cust_id].append(account_payment)
    del account_payments

    omnichannel_customers = []

    for customer_id in customer_ids:

        account = accounts_dict.get(customer_id)
        if not account:
            continue

        customer = customer_dict.get(customer_id)
        if not customer:
            continue

        application = application_dict.get(customer_id)
        if not application:
            continue

        account_payments = account_payments_dict.get(customer_id, [])

        payment_methods = PaymentMethod.objects.filter(
            is_shown=True,
            customer=customer,
            payment_method_name__in=(
                'INDOMARET',
                'ALFAMART',
                'Bank MAYBANK',
                'PERMATA Bank',
                'Bank BCA',
                'Bank MANDIRI',
            ),
        ).values('payment_method_name', 'virtual_account')

        omnichannel_customer = _construct_omnichannel_customer(
            customer=customer,
            application=application,
            account_payments=account_payments,
            account=account,
            payment_methods=payment_methods,
        )
        if omnichannel_customer:
            omnichannel_customers.append(omnichannel_customer)

    return omnichannel_customers


def _construct_omnichannel_customer(
    customer: Customer,
    application: Application,
    account_payments: List[AccountPayment],
    account: Account,
    payment_methods: List[dict],
) -> Union[OmnichannelCustomer, None]:

    try:
        omnichannel_customer = _construct_customer_attribute(
            customer=customer,
            account=account,
            application=application,
            account_payments=account_payments,
            payment_methods=payment_methods,
        )

        customer_account_payments = []
        for account_payment in account_payments:
            account_payment = _construct_account_payment_attribute(
                account_payment=account_payment,
                account=account,
            )
            customer_account_payments.append(account_payment)

        omnichannel_customer.customer_attribute.account_payment = customer_account_payments
    except Exception as e:
        logger.error(
            {
                'action': '_construct_omnichannel_customer',
                'customer_id': customer.id,
                'message': 'Error constructing omnichannel customer',
                'error': str(e),
            }
        )
        sentry_client.captureException()
        return None

    logger.info(
        {
            'action': '_construct_omnichannel_customer',
            'customer_id': customer.id,
            'message': 'Successfully constructed omnichannel customer',
        }
    )

    return omnichannel_customer


def _construct_customer_attribute(
    customer: Customer,
    account: Account,
    application: Application,
    account_payments: List[AccountPayment],
    payment_methods: List[PaymentMethod],
) -> OmnichannelCustomer:

    ai_rudder_pds_svc = AIRudderPDSServices()

    now = timezone.now()
    local_timenow = timezone.localtime(now)
    device_repo = get_device_repository()
    first_name, last_name = get_first_last_name(customer.fullname)
    customer_timezone = get_user_timezone(
        int(customer.address_kodepos) if customer.address_kodepos else 20111
    )

    oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
    if not oldest_unpaid_account_payment:
        oldest_unpaid_account_payment = account_payments[0] if account_payments else None

    first_name, last_name = get_first_last_name(customer.fullname)

    is_autodebet_active = False
    autodebet_account = get_active_autodebet_account(account_id=account.id)
    if autodebet_account:
        is_autodebet_active = True

    payment_method = PaymentMethod.objects.filter(customer_id=customer.id, is_primary=True).last()

    payment_methods_dict = {
        item['payment_method_name']: item['virtual_account'] for item in payment_methods
    } or {}

    collection_segment_eg = (
        ExperimentGroup.objects.filter(account_id=account.id).values('segment').last()
    )
    collection_segment = collection_segment_eg['segment'] if collection_segment_eg else None

    cashback_new_scheme_experiment_group = False
    experiment_group = get_cashback_experiment(customer.account.id)
    if experiment_group:
        cashback_new_scheme_experiment_group = True

    last_active_liveness_result = ActiveLivenessDetection.objects.filter(
        application_id=application.id,
    ).last()
    last_passive_liveness_result = PassiveLivenessDetection.objects.filter(
        application_id=application.id,
    ).last()

    mycroft_result = PdApplicationFraudModelResult.objects.filter(
        application_id=application.id
    ).last()
    last_credit_score = CreditScore.objects.filter(application=application).last()
    last_active_liveness_result = ActiveLivenessDetection.objects.filter(
        application_id=application.id,
    ).last()
    last_passive_liveness_result = PassiveLivenessDetection.objects.filter(
        application_id=application.id,
    ).last()
    credit_model_result = PdCreditModelResult.objects.filter(application_id=application.id).last()

    orion_result = PdCreditEarlyModelResult.objects.filter(application_id=application.id).last()
    total_loan_amount = (
        Loan.objects.filter(
            account=account,
            loan_status_id__gte=LoanStatusCodes.CURRENT,
        )
        .exclude(
            loan_status_id=LoanStatusCodes.PAID_OFF,
        )
        .aggregate(Sum('loan_amount'))['loan_amount__sum']
    )

    shopee_biz_data = {}
    shopee_score = ShopeeScoring.objects.filter(application_id=application.id).last()
    if (
        shopee_score
        and shopee_score.biz_data is not None
        and isinstance(shopee_score.biz_data, dict)
    ):
        shopee_biz_data = shopee_score.biz_data

    collection_segment_eg = (
        ExperimentGroup.objects.filter(account_id=account.id).values('segment').last()
    )
    collection_segment = collection_segment_eg['segment'] if collection_segment_eg else None

    cashback_new_scheme_experiment_group = False
    experiment_group = get_cashback_experiment(customer.account.id)
    if experiment_group:
        cashback_new_scheme_experiment_group = True

    face_search_result = None
    face_search_process = FaceSearchProcess.objects.filter(application_id=application.id).last()
    if face_search_process:
        face_search_result = FaceSearchResult.objects.filter(
            face_search_process_id=face_search_process.id
        ).last()

    due_date, percentage_mapping = get_paramters_cashback_new_scheme()
    cashback_parameters = dict(
        is_eligible_new_cashback=account.is_cashback_new_scheme,
        due_date=due_date,
        percentage_mapping=percentage_mapping,
        account_status=account.status_id,
    )

    cashback_potential = (
        get_potential_cashback_by_account_payment(
            oldest_unpaid_account_payment,
            account.cashback_counter,
            cashback_parameters=cashback_parameters,
        )
        if oldest_unpaid_account_payment
        else None
    )
    cashback_due_date_slash = (
        format_date(oldest_unpaid_account_payment.due_date - timedelta(days=2), 'dd/MM/yyyy')
        if oldest_unpaid_account_payment
        else None
    )
    potential_cashback, total_cashback = (
        get_potential_and_total_cashback(
            oldest_unpaid_account_payment, account.cashback_counter, customer.id
        )
        if oldest_unpaid_account_payment
        else (None, None)
    )

    all_account_payment = AccountPayment.objects.filter(account=account).exclude(
        due_amount=0, paid_amount=0
    )
    query_filter = dict(status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
    all_account_payment = all_account_payment.filter(**query_filter).order_by('due_date')

    is_email_blocked = False
    is_sms_blocked = False
    is_one_way_robocall_blocked = False
    is_two_way_robocall_blocked = False
    is_pn_blocked = False

    account_payment_current_window = (
        AccountPayment.objects.filter(account=account, due_date__gte=local_timenow.date())
        .exclude(status_id__gte=PaymentStatusCodes.PAID_ON_TIME)
        .order_by('due_date')
        .first()
    )
    if account_payment_current_window:
        account_payment_current_window_dpd = get_dpd(account_payment_current_window)
        comms_blocked = CommsBlocked.objects.filter(
            impacted_payments__contains=[account_payment_current_window.id],
        ).last()
        if comms_blocked and comms_blocked.block_until >= account_payment_current_window_dpd:
            is_email_blocked = comms_blocked.is_email_blocked
            is_sms_blocked = comms_blocked.is_sms_blocked
            is_one_way_robocall_blocked = comms_blocked.is_robocall_blocked
            is_two_way_robocall_blocked = comms_blocked.is_cootek_blocked
            is_pn_blocked = comms_blocked.is_pn_blocked

    (
        refinancing_status,
        refinancing_prerequisite_amount,
        refinancing_expire_date,
    ) = ai_rudder_pds_svc.get_loan_refinancing_data_for_dialer(account)

    is_risky = get_is_risky(account_id=account.id)

    customer_lvl_dpd = (
        get_dpd(oldest_unpaid_account_payment) if oldest_unpaid_account_payment else None
    )

    is_dpd_plus = None
    if customer_lvl_dpd is not None:
        is_dpd_plus = False
        if customer_lvl_dpd > 4:
            is_dpd_plus = True

    try:
        _, _, google_url = get_google_calendar_for_email_reminder(
            application,
            is_dpd_plus,
            True,
            False,
        )
    except Exception as e:
        google_url = None
        logger.error(
            {
                'action': 'parse_credgenics_loan_v2',
                'message': 'Error getting google calendar url',
                'error': str(e),
            }
        )

    if refinancing_expire_date:
        refinancing_expire_date = parse_to_datetime(refinancing_expire_date)

    oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
    if not oldest_unpaid_account_payment:
        oldest_unpaid_account_payment = account_payments[0] if account_payments else None

    last_agent, last_call_status = None, None
    dpd = None
    customer_bucket_type = None
    if oldest_unpaid_account_payment:
        last_agent, last_call_status = ai_rudder_pds_svc.check_last_call_agent_and_status(
            oldest_unpaid_account_payment,
        )

        dpd = get_dpd(oldest_unpaid_account_payment)

        customer_bucket_type = ai_rudder_pds_svc.get_customer_bucket_type(
            oldest_unpaid_account_payment, account, dpd
        )

    from juloserver.waiver.services.account_related import (
        can_account_get_refinancing_centralized,
    )

    is_eligible_refinancing, _ = can_account_get_refinancing_centralized(account.id)
    bss_refinancing_status = ''
    if is_eligible_refinancing:
        bss_refinancing_status = "Pinjaman BSS aktif - bisa ditawarkan R4"

    fdc_risky_history = FDCRiskyHistory.objects.filter(application_id=application.id).last()

    return OmnichannelCustomer(
        customer_id=str(customer.id),
        updated_at=now,
        customer_attribute=CustomerAttribute(
            application_id=application.id,
            account_id=account.id,
            customer_xid=str(customer.customer_xid),
            customer_id=customer.id,
            sms_firstname=first_name,
            email=customer.email,
            fcm_reg_id=device_repo.get_active_fcm_id(customer.id),
            source="daily_sync",
            mobile_phone=format_e164_indo_phone_number(str(application.mobile_phone_1 or '')),
            timezone_offset=get_timezone_offset_in_seconds(customer_timezone),
            mobile_phone_2=format_e164_indo_phone_number(str(application.mobile_phone_2 or '')),
            full_name=application.fullname,
            first_name=first_name,
            last_name=last_name,
            title_long=get_title_long(application.bpk_ibu),
            title=application.bpk_ibu,
            name_with_title='{}{}'.format(application.bpk_ibu, application.fullname),
            company_name=application.company_name,
            company_phone_number=format_e164_indo_phone_number(
                str(application.company_phone_number or '')
            ),
            position_employees=application.position_employees,
            spouse_name=application.spouse_name,
            spouse_mobile_phone=format_e164_indo_phone_number(
                str(application.spouse_mobile_phone or '')
            ),
            kin_name=application.kin_name,
            kin_relationship=application.kin_relationship,
            kin_mobile_phone=format_e164_indo_phone_number(str(application.kin_mobile_phone or '')),
            address_full='{} {} {} {} {} {}'.format(
                application.address_street_num,
                application.address_provinsi,
                application.address_kabupaten,
                application.address_kecamatan,
                application.address_kelurahan,
                application.address_kodepos,
            ),
            city=application.address_kabupaten,
            gender=application.gender,
            dob=application.dob,
            age=local_timenow.year
            - application.dob.year
            - (
                (local_timenow.month, local_timenow.day)
                < (application.dob.month, application.dob.day)
            )
            if application.dob
            else None,
            payday=application.payday,
            loan_purpose=application.loan_purpose,
            is_autodebet=is_autodebet_active,
            is_j1_customer=application.is_julo_one(),
            bank_code=payment_method.bank_code if payment_method else None,
            bank_code_text=payment_method.bank_code if payment_method else None,
            bank_name=application.bank_name,
            va_method_name=payment_method.payment_method_name if payment_method else None,
            va_number=payment_method.virtual_account if payment_method else None,
            va_bca=payment_methods_dict.get('Bank BCA', ''),
            va_permata=payment_methods_dict.get('PERMATA Bank', ''),
            va_maybank=payment_methods_dict.get('Bank MAYBANK', ''),
            va_alfamart=payment_methods_dict.get('ALFAMART', ''),
            va_indomaret=payment_methods_dict.get('INDOMARET', ''),
            va_mandiri=payment_methods_dict.get('Bank MANDIRI', ''),
            product_line_code=str(application.product_line_id),
            product_line_name=application.product_line.product_line_type,
            collection_segment=str(collection_segment),
            cashback_new_scheme_experiment_group=cashback_new_scheme_experiment_group,
            active_liveness_score=last_active_liveness_result.score
            if last_active_liveness_result
            else 0.0,
            passive_liveness_score=last_passive_liveness_result.score
            if last_passive_liveness_result
            else 0.0,
            heimdall_score=credit_model_result.pgood if credit_model_result else 0.0,
            orion_score=orion_result.pgood if orion_result else 0.0,
            # fpgw=total_loan_amount / total_disbursed_amount if total_loan_amount else None,
            shopee_score_status=str(shopee_biz_data.get('hit_reason_code'))
            if shopee_biz_data.get('hit_reason_code', None)
            else '',
            shopee_score_list_type=str(shopee_biz_data.get('list_type'))
            if shopee_biz_data.get('hit_reason_code', None)
            else '',
            total_loan_amount=int(total_loan_amount) if total_loan_amount else None,
            application_similarity_score=face_search_result.similarity
            if face_search_result
            else 0.0,
            mycroft_score=mycroft_result.pgood if mycroft_result else 0.0,
            credit_score=last_credit_score.score if last_credit_score else '',
            total_cashback_earned=total_cashback,
            cashback_amount=cashback_potential,
            cashback_counter=account.cashback_counter,
            cashback_due_date_slash=cashback_due_date_slash,
            refinancing_prerequisite_amount=refinancing_prerequisite_amount,
            refinancing_status=refinancing_status,
            refinancing_expire_date=refinancing_expire_date.date()
            if refinancing_expire_date
            else None,
            zip_code=application.address_kodepos,
            uninstall_indicator=get_uninstall_indicator_from_moengage_by_customer_id(customer.id),
            sms_primary_va_name=customer.primary_va_name,
            sms_primary_va_number=customer.primary_va_number,
            is_risky=is_risky,
            is_email_blocked=is_email_blocked,
            is_sms_blocked=is_sms_blocked,
            is_one_way_robocall_blocked=is_one_way_robocall_blocked,
            is_two_way_robocall_blocked=is_two_way_robocall_blocked,
            is_pn_blocked=is_pn_blocked,
            partner_name=application.partner_name,
            google_calendar_url=google_url,
            account_payment=[],
            last_pay_date=oldest_unpaid_account_payment.paid_date
            if oldest_unpaid_account_payment
            else None,
            last_pay_amount=oldest_unpaid_account_payment.paid_amount
            if oldest_unpaid_account_payment
            else None,
            last_call_agent=last_agent if last_agent else None,
            last_call_status=last_call_status if last_call_status else None,
            program_expiry_date=refinancing_expire_date.date() if refinancing_expire_date else None,
            customer_bucket_type=customer_bucket_type,
            installment_due_amount=oldest_unpaid_account_payment.due_amount
            if oldest_unpaid_account_payment
            else None,
            other_refinancing_status=bss_refinancing_status,
            fdc_risky=fdc_risky_history.is_fdc_risky if fdc_risky_history else None,
            activation_amount=refinancing_prerequisite_amount,
            is_customer_julo_gold=False,
        ),
    )


def _construct_account_payment_attribute(
    account_payment: AccountPayment,
    account: Account,
) -> Union[AccountPaymentAttribute, None]:

    due_amount = account_payment.due_amount
    formatted_due_amount = format_number(due_amount)

    potential_cashback = get_potential_cashback_by_account_payment(
        account_payment, account.cashback_counter
    )

    sms_url = get_payment_url_raw(account_payment)

    prediction_before_call = 1
    collection_model_result = PdCollectionModelResult.objects.filter(
        account_payment_id=account_payment.id
    ).last()
    if collection_model_result:
        prediction_before_call = collection_model_result.prediction_before_call

    internal_sort_order = (1.0 - prediction_before_call) * account_payment.due_amount

    ptp = (
        PTP.objects.only('ptp_date')
        .values('ptp_date')
        .filter(account_payment=account_payment, ptp_date__isnull=False)
        .last()
    )
    ptp_date = ptp.get('ptp_date') if ptp else None

    return AccountPaymentAttribute(
        account_id=int(account_payment.account_id),
        account_payment_id=int(account_payment.id),
        account_payment_xid=account_payment.account_payment_xid,
        due_date=account_payment.due_date,
        due_amount=account_payment.due_amount,
        late_fee_amount=account_payment.late_fee_amount,
        principal_amount=account_payment.principal_amount,
        interest_amount=account_payment.interest_amount,
        paid_amount=account_payment.paid_amount,
        paid_late_fee_amount=account_payment.paid_late_fee,
        paid_principal_amount=account_payment.paid_principal,
        paid_interest_amount=account_payment.paid_interest,
        paid_date=account_payment.paid_date,
        status_code=int(account_payment.status_id),
        ptp_date=ptp_date,
        short_ptp_date=format_date(ptp_date, 'd/M', locale="id_ID") if ptp_date else None,
        ptp_amount=account_payment.ptp_amount,
        ptp_robocall_phone_number=None,
        is_restructured=account_payment.is_restructured,
        autodebet_retry_count=account_payment.autodebet_retry_count,
        is_collection_called=account_payment.is_collection_called,
        is_ptp_robocall_active=account_payment.is_ptp_robocall_active,
        is_reminder_called=account_payment.is_reminder_called,
        is_success_robocall=account_payment.is_success_robocall,
        is_robocall_active=account_payment.is_robocall_active,
        paid_during_refinancing=account_payment.paid_during_refinancing,
        late_fee_applied=account_payment.late_fee_applied,
        is_paid_within_dpd_1to10=account_payment.is_paid_within_dpd_1to10,
        potential_cashback=potential_cashback,
        sms_month=account_payment.due_date.month,
        month_due_date=format_date(account_payment.due_date, 'MMMM', locale="id_ID"),
        year_due_date=account_payment.due_date.year,
        due_date_long=format_date(account_payment.due_date, 'd MMMM yyyy', locale="id_ID"),
        due_date_short=format_date(account_payment.due_date, 'd MMMM', locale="id_ID"),
        sms_payment_details_url=sms_url,
        formatted_due_amount=formatted_due_amount,
        sort_order=internal_sort_order,
    )


def construct_collection_sms_remove_experiment(
    customer_ids: List[int],
    segment: str,
) -> List[OmnichannelCustomer]:
    omnichannel_customers = []
    for customer_id in customer_ids:
        omnichannel_customers.append(
            OmnichannelCustomer(
                customer_id=str(customer_id),
                customer_attribute=CustomerAttribute(
                    coll_experiment_sms_reminder_omnichannel_experiment_group=segment,
                ),
            )
        )
    return omnichannel_customers


def construct_field_collection_excluded_customers(
    customer_ids: List[int],
) -> List[OmnichannelCustomer]:

    accounts = Account.objects.filter(customer_id__in=customer_ids).only('id', 'customer_id')
    account_ids = accounts.values_list('id', flat=True)
    account_id_map = {account.id: account for account in accounts}

    bucket_to_account_ids = {}
    for account in accounts:
        bucket_name = get_dailer_system_const_bucket_name(account.bucket_number)
        if len(bucket_to_account_ids.get(bucket_name, [])) == 0:
            bucket_to_account_ids[bucket_name] = [account.id]
        else:
            bucket_to_account_ids[bucket_name].append(account.id)

    omnichannel_customers = []
    for bucket_name, account_ids in bucket_to_account_ids.items():
        blacklisted_account_ids = get_exclude_account_ids_collection_field_by_account_ids(
            account_ids, bucket_name
        )
        for account_id in blacklisted_account_ids:
            account = account_id_map.get(account_id)
            omnichannel_customers.append(
                OmnichannelCustomer(
                    customer_id=str(account.customer_id),
                    customer_attribute=CustomerAttribute(
                        is_collection_field_blacklisted=True,
                    ),
                )
            )

        unblacklisted_account_ids = list(set(account_ids) - set(blacklisted_account_ids))
        for account_id in unblacklisted_account_ids:
            account = account_id_map.get(account_id)
            omnichannel_customers.append(
                OmnichannelCustomer(
                    customer_id=str(account.customer_id),
                    customer_attribute=CustomerAttribute(
                        is_collection_field_blacklisted=False,
                    ),
                )
            )

    return omnichannel_customers


def get_dailer_system_const_bucket_name(
    bucket_number: int,
) -> DialerSystemConst:
    """
    TODO: create one to dynamically get this based on product line;
    currently it only works for J1
    """
    return getattr(DialerSystemConst, 'DIALER_BUCKET_{}'.format(bucket_number))


def construct_field_julo_gold_customer(
    customer_ids: List[int],
    is_full_rollout: bool,
) -> List[OmnichannelCustomer]:
    today = date.today()

    if not is_full_rollout and not customer_ids:
        raise ValueError("Customer IDs cannot be empty when is_full_rollout is False.")

    customer_julo_golds_qs = PdCustomerSegmentModelResult.objects.filter(partition_date=today)

    if not is_full_rollout:
        customer_julo_golds_qs = customer_julo_golds_qs.filter(customer_id__in=customer_ids)

    customer_julo_golds_qs = customer_julo_golds_qs.extra(
        where=["customer_segment ILIKE %s"],
        params=["%julogold%"],
    ).values_list("customer_id", flat=True)

    omnichannel_customers = [
        OmnichannelCustomer(
            customer_id=str(customer_id),
            customer_attribute=CustomerAttribute(is_customer_julo_gold=True),
        )
        for customer_id in customer_julo_golds_qs
    ]

    return omnichannel_customers


def construct_customer_odin_score() -> Iterator[OmnichannelCustomer]:
    yesterday = date.today() - timedelta(days=1)
    results = (
        PdBscoreModelResult.objects.filter(udate__date=yesterday)
        .values_list('customer_id', 'pgood')
        .iterator()
    )
    return (
        OmnichannelCustomer(
            customer_id=str(customer_id),
            customer_attribute=CustomerAttribute(
                odin_score=pgood,
            ),
        )
        for customer_id, pgood in results
    )

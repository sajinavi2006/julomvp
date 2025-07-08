from datetime import datetime, timedelta
from django.utils import timezone
from typing import (
    Union,
    List,
)
from django.db.models import (
    Sum,
)
from babel.dates import format_date
from juloserver.julo.services2 import (
    encrypt,
)
from django.conf import settings
from juloserver.urlshortener.services import shorten_url

from juloserver.julo.models import CommsBlocked
from juloserver.account.models import ExperimentGroup
from juloserver.credgenics.models.loan import (
    CredgenicsLoan,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account.models import Account
from juloserver.julo.models import (
    Application,
    Customer,
    FDCRiskyHistory,
    CreditScore,
    Loan,
)
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.application_flow.models import (
    ShopeeScoring,
)
from juloserver.minisquad.services2.ai_rudder_pds import (
    AIRudderPDSServices,
)
from juloserver.account_payment.services.earning_cashback import get_cashback_experiment
# from juloserver.face_recognition.services import CheckFaceSimilarity
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.apiv2.models import (
    PdCreditModelResult,
    PdCollectionModelResult,
)

from juloserver.credgenics.services.utils import (
    get_dpd,
    get_first_last_name,
    get_title_long,
    get_is_risky,
)

from juloserver.account_payment.services.account_payment_related import (
    get_potential_and_total_cashback,
    get_potential_cashback_by_account_payment,
)

from juloserver.julo.statuses import (
    PaymentStatusCodes,
)
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
)

from juloserver.julo.services import (
    get_google_calendar_for_email_reminder,
)
from juloserver.julo.models import (
    PaymentMethod,
)
from juloserver.minisquad.services2.dialer_related import (
    get_uninstall_indicator_from_moengage_by_customer_id,
)
from juloserver.ana_api.models import (
    PdApplicationFraudModelResult,
    PdCreditEarlyModelResult,
)

from juloserver.face_recognition.models import (
    FaceSearchResult,
    FaceSearchProcess,
)
from juloserver.autodebet.models import (
    AutodebetAccount,
)
from juloserver.julo.clients import get_julo_sentry_client
import logging
from juloserver.account_payment.services.earning_cashback import get_paramters_cashback_new_scheme

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()

static_allocation_month = datetime(2024, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_credgenics_loan_v2(
    customer: Customer,
    application: Application,
    account_payments: List[AccountPayment],
    account: Account,
    payment_methods: PaymentMethod,
    # ...
    # @kent
) -> Union[CredgenicsLoan, None]:
    """
    Parse the Credgenics loan object PER ACCOUNT
    """

    credgenics_loans = []

    ai_rudder_pds_svc = AIRudderPDSServices()

    cashback_counter = account.cashback_counter or 0
    local_timenow = timezone.localtime(timezone.now())
    payment_methods_dict = {
        item['payment_method_name']: item['virtual_account'] for item in payment_methods
    } or {}

    outstanding_amount = (
        account.accountpayment_set.normal()
        .filter(status_id__lte=PaymentStatusCodes.PAID_ON_TIME)
        .aggregate(Sum('due_amount'))['due_amount__sum']
        or 0
    )
    last_paid_account_payment = (
        account.accountpayment_set.normal()
        .filter(paid_amount__gt=0)
        .exclude(paid_date__isnull=True)
        .order_by('paid_date')
        .last()
    )
    (
        refinancing_status,
        refinancing_prerequisite_amount,
        refinancing_expire_date,
    ) = ai_rudder_pds_svc.get_loan_refinancing_data_for_dialer(account)

    fdc_risky_history = FDCRiskyHistory.objects.filter(application_id=application.id).last()

    # last_loan = Loan.objects.filter(account=account).last()
    payment_method = PaymentMethod.objects.filter(customer_id=customer.id, is_primary=True).last()
    first_name, last_name = get_first_last_name(customer.fullname)

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

    total_disbursed_amount = Loan.objects.filter(account=account,).aggregate(
        Sum('loan_amount')
    )['loan_amount__sum']

    shopee_biz_data = {}
    shopee_score = ShopeeScoring.objects.filter(application_id=application.id).last()
    if (
        shopee_score
        and shopee_score.biz_data is not None
        and isinstance(shopee_score.biz_data, dict)
    ):
        shopee_biz_data = shopee_score.biz_data

    # check_face_similarity_svc = CheckFaceSimilarity(application)
    # face_search_result = check_face_similarity_svc

    collection_segment_eg = (
        ExperimentGroup.objects.filter(account_id=account.id).values('segment').last()
    )
    collection_segment = collection_segment_eg['segment'] if collection_segment_eg else None

    cashback_new_scheme_experiment_group = False
    experiment_group = get_cashback_experiment(customer.account.id)
    if experiment_group:
        cashback_new_scheme_experiment_group = True

    oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
    if not oldest_unpaid_account_payment:
        oldest_unpaid_account_payment = account_payments[0]

    face_search_result = None
    face_search_process = FaceSearchProcess.objects.filter(application_id=application.id).last()
    if face_search_process:
        face_search_result = FaceSearchResult.objects.filter(
            face_search_process_id=face_search_process.id
        ).last()

    is_autodebet_active = False
    autodebet_account = AutodebetAccount.objects.filter(account_id=account.id).last()
    if (
        autodebet_account
        and not autodebet_account.is_deleted_autodebet
        and autodebet_account.activation_ts is not None
    ):
        is_autodebet_active = True

    total_due_amount = (
        account.accountpayment_set.normal()  # exclude refinenced account payments
        .not_paid_active()
        .filter(due_date__lte=local_timenow.date())
        .aggregate(Sum('due_amount'))['due_amount__sum']
        or 0
    )

    due_date, percentage_mapping = get_paramters_cashback_new_scheme()
    cashback_parameters = dict(
        is_eligible_new_cashback=account.is_cashback_new_scheme,
        due_date=due_date,
        percentage_mapping=percentage_mapping,
        account_status=account.status_id,
    )

    cashback_potential = get_potential_cashback_by_account_payment(
        oldest_unpaid_account_payment, cashback_counter, cashback_parameters=cashback_parameters
    )
    cashback_due_date_slash = format_date(
        oldest_unpaid_account_payment.due_date - timedelta(days=2), 'dd/MM/yyyy'
    )
    due_date_long = format_date(
        oldest_unpaid_account_payment.due_date, 'd MMMM yyyy', locale="id_ID"
    )
    month_due_date = format_date(oldest_unpaid_account_payment.due_date, 'MMMM', locale="id_ID")
    potential_cashback, total_cashback = get_potential_and_total_cashback(
        oldest_unpaid_account_payment, cashback_counter, customer.id
    )
    ptp_date = to_rfc3339(str(oldest_unpaid_account_payment.ptp_date))
    sms_due_date_short = format_date(
        oldest_unpaid_account_payment.due_date, "d-MMM", locale="id_ID"
    )
    sms_month = int(format_date(oldest_unpaid_account_payment.due_date, "M", locale="id_ID"))
    sms_url = get_payment_url_raw(oldest_unpaid_account_payment)
    year_due_date = format_date(oldest_unpaid_account_payment.due_date, 'YYYY', locale="id_ID")

    all_account_payment = AccountPayment.objects.filter(account=account).exclude(
        due_amount=0, paid_amount=0
    )
    query_filter = dict(status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
    all_account_payment = all_account_payment.filter(**query_filter).order_by('due_date')
    oldest_account_payment = all_account_payment.first()
    account_payments_due = all_account_payment.filter(due_date__lte=local_timenow).order_by(
        'due_date'
    )
    campaign_due_amount = oldest_account_payment.due_amount if oldest_account_payment else 0
    if account_payments_due:
        campaign_due_amount = account_payments_due.aggregate(due_amount=Sum('due_amount')).get(
            'due_amount'
        )

    formatted_due_amount = format_number(campaign_due_amount)

    is_email_blocked = False
    is_sms_blocked = False
    is_one_way_robocall_blocked = False

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

    for account_payment in account_payments:
        try:
            if (
                account_payment.is_paid
                and not (
                    account_payment.status_id == PaymentStatusCodes.PARTIAL_RESTRUCTURED
                    or account_payment.is_restructured
                )
                and not (
                    account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME
                    and account_payment.due_date > local_timenow.date()
                )
            ):
                continue

            dpd = get_dpd(account_payment)

            prediction_before_call = 1
            collection_model_result = PdCollectionModelResult.objects.filter(
                account_payment_id=account_payment.id
            ).last()
            if collection_model_result:
                prediction_before_call = collection_model_result.prediction_before_call

            internal_sort_order = (1.0 - prediction_before_call) * account_payment.due_amount

            customer_lvl_dpd = get_dpd(oldest_unpaid_account_payment)
            is_risky = get_is_risky(account_id=account.id)

            is_dpd_plus = False
            if dpd > 4:
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

            last_agent, last_call_status = ai_rudder_pds_svc.check_last_call_agent_and_status(
                account_payment
            )

            customer_bucket_type = ai_rudder_pds_svc.get_customer_bucket_type(
                account_payment, account, dpd
            )

            credgenics_loan = CredgenicsLoan(
                transaction_id=account_payment.id,  # transaction_id
                account_id=int(account_payment.account_id),
                client_customer_id=customer.id,  # customer_id
                customer_dpd=customer_lvl_dpd,
                allocation_dpd_value=dpd,
                customer_due_date=to_rfc3339(str(oldest_unpaid_account_payment.due_date))
                if oldest_unpaid_account_payment
                else None,  # oldest unpaid due date
                date_of_default=to_rfc3339(
                    str(account_payment.due_date)
                ),  # same as tanggal jatuh tempo
                total_claim_amount=account_payment.paid_amount
                + account_payment.due_amount,  # same as total_due_amount
                late_fee=account_payment.late_fee_amount,  # same as total_denda
                expected_emi_principal_amount=account_payment.principal_amount,
                expected_emi_interest_amount=account_payment.interest_amount,
                expected_emi=account_payment.principal_amount + account_payment.interest_amount,
                dpd=dpd,
                total_denda=int(abs(account.get_outstanding_late_fee())),
                potensi_cashback=potential_cashback,
                total_seluruh_perolehan_cashback=total_cashback,
                total_due_amount=total_due_amount,
                total_outstanding=outstanding_amount,
                tipe_produk=application.product_line_code,
                last_pay_amount=last_paid_account_payment.paid_amount
                if last_paid_account_payment
                else 0,
                activation_amount=refinancing_prerequisite_amount,
                zip_code=application.address_kodepos,
                angsuran_per_bulan=account_payment.due_amount,
                mobile_phone_1=format_e164_indo_phone_number(str(application.mobile_phone_1 or '')),
                mobile_phone_2=format_e164_indo_phone_number(str(application.mobile_phone_2 or '')),
                nama_customer=application.fullname,
                nama_perusahaan=application.company_name,
                posisi_karyawan=application.position_employees,
                nama_pasangan=application.spouse_name,
                nama_kerabat=application.kin_name,
                hubungan_kerabat=application.kin_relationship,
                alamat='{} {} {} {} {} {}'.format(
                    application.address_street_num,
                    application.address_provinsi,
                    application.address_kabupaten,
                    application.address_kecamatan,
                    application.address_kelurahan,
                    application.address_kodepos,
                ),
                kota=application.address_kabupaten,
                jenis_kelamin=application.gender,
                tgl_lahir=to_rfc3339(str(application.dob)),
                tgl_gajian=application.payday,
                tujuan_pinjaman=application.loan_purpose,
                va_bca=payment_methods_dict.get('Bank BCA', ''),
                va_permata=payment_methods_dict.get('PERMATA Bank', ''),
                va_maybank=payment_methods_dict.get('Bank MAYBANK', ''),
                va_alfamart=payment_methods_dict.get('ALFAMART', ''),
                va_indomaret=payment_methods_dict.get('INDOMARET', ''),
                va_mandiri=payment_methods_dict.get('Bank MANDIRI', ''),
                last_pay_date=to_rfc3339(str(last_paid_account_payment.paid_date))
                if last_paid_account_payment
                else None,
                last_agent=last_agent,
                last_call_status=last_call_status,
                refinancing_status=refinancing_status,
                program_expiry_date=to_rfc3339(str(refinancing_expire_date)),
                customer_bucket_type=customer_bucket_type,
                telp_perusahaan=format_e164_indo_phone_number(
                    str(application.company_phone_number or '')
                ),
                no_telp_pasangan=format_e164_indo_phone_number(
                    str(application.spouse_mobile_phone or '')
                ),
                no_telp_kerabat=format_e164_indo_phone_number(
                    str(application.kin_mobile_phone or '')
                ),
                uninstall_indicator=get_uninstall_indicator_from_moengage_by_customer_id(
                    customer.id
                ),
                fdc_risky=fdc_risky_history.is_fdc_risky if fdc_risky_history else None,
                email=customer.email,
                cashback_new_scheme_experiment_group=cashback_new_scheme_experiment_group,
                va_method_name=payment_method.payment_method_name if payment_method else None,
                va_number=payment_method.virtual_account if payment_method else None,
                short_ptp_date=format_date(account_payment.ptp_date, 'd/M', locale="id_ID")
                if account_payment.ptp_date
                else None,
                is_j1_customer=application.is_julo_one(),
                first_name=first_name,
                last_name=last_name,
                month_due_date=month_due_date,
                year_due_date=year_due_date,
                due_date_long=due_date_long,
                age=local_timenow.year
                - application.dob.year
                - (
                    (local_timenow.month, local_timenow.day)
                    < (application.dob.month, application.dob.day)
                ),
                title=application.bpk_ibu,
                sms_due_date_short=sms_due_date_short,
                sms_month=sms_month,
                sms_firstname=first_name,
                sms_primary_va_name=customer.primary_va_name,
                sms_primary_va_number=customer.primary_va_number,
                sms_payment_details_url=sms_url,
                collection_segment=str(collection_segment),
                bank_code=payment_method.bank_code if payment_method else None,
                bank_code_text=payment_method.bank_code if payment_method else None,
                bank_name=application.bank_name,
                cashback_amount=cashback_potential,
                cashback_counter=account.cashback_counter,
                cashback_due_date_slash=cashback_due_date_slash,
                title_long=get_title_long(application.bpk_ibu),
                name_with_title='{} {}'.format(application.bpk_ibu, application.fullname),
                formatted_due_amount=formatted_due_amount,
                google_calendar_url=google_url,
                shopee_score_status=str(shopee_biz_data.get('hit_reason_code'))
                if shopee_biz_data.get('hit_reason_code', None)
                else '',
                shopee_score_list_type=str(shopee_biz_data.get('list_type'))
                if shopee_biz_data.get('hit_reason_code', None)
                else '',
                # shopee_score_description=shopee_score.list_score if shopee_score else 0,
                mycroft_score=mycroft_result.pgood if mycroft_result else 0.0,
                credit_score=last_credit_score.score if last_credit_score else '',
                active_liveness_score=last_active_liveness_result.score
                if last_active_liveness_result
                else 0.0,
                passive_liveness_score=last_passive_liveness_result.score
                if last_passive_liveness_result
                else 0.0,
                heimdall_score=credit_model_result.pgood if credit_model_result else 0.0,
                orion_score=orion_result.pgood if orion_result else 0.0,
                fpgw=total_loan_amount / total_disbursed_amount
                if total_loan_amount
                else None,  # bagi total disbursement
                total_loan_amount=int(total_loan_amount) if total_loan_amount else None,
                # accpymt
                late_fee_applied=account_payment.late_fee_applied,
                status_code=int(account_payment.status_id),
                is_collection_called=account_payment.is_collection_called,
                is_ptp_robocall_active=account_payment.is_ptp_robocall_active,
                is_reminder_called=account_payment.is_reminder_called,
                is_robocall_active=account_payment.is_robocall_active,
                is_success_robocall=account_payment.is_success_robocall,
                ptp_date=ptp_date,
                ptp_robocall_phone_number=None,
                is_restructured=account_payment.is_restructured,
                account_payment_xid=account_payment.account_payment_xid,
                autodebet_retry_count=account_payment.autodebet_retry_count,
                paid_during_refinancing=account_payment.paid_during_refinancing,
                is_paid_within_dpd_1to10=account_payment.is_paid_within_dpd_1to10,
                allocation_month=to_rfc3339(static_allocation_month.strftime('%Y-%m-%d')),
                ptp_amount=account_payment.ptp_amount,
                partner_name=application.partner_name,
                application_similarity_score=face_search_result.similarity
                if face_search_result
                else 0.0,
                is_autodebet=is_autodebet_active,
                internal_sort_order=internal_sort_order,
                campaign_due_amount=campaign_due_amount,
                is_risky=is_risky,
                is_email_blocked=is_email_blocked,
                is_sms_blocked=is_sms_blocked,
                is_one_way_robocall_blocked=is_one_way_robocall_blocked,
            )
        except Exception as e:
            logger.error(
                {
                    'action': 'parse_credgenics_loan_v2',
                    'customer_id': customer.id,
                    'account_payment_id': account_payment.id,
                    'message': 'Error parsing credgenics loan',
                    'error': str(e),
                }
            )
            sentry_client.captureException()
            continue

        logger.info(
            {
                'action': 'parse_credgenics_loan_v2',
                'customer_id': customer.id,
                'account_payment_id': account_payment.id,
                'message': 'Successfully parsed credgenics loan',
            }
        )
        credgenics_loans.append(credgenics_loan)

    return credgenics_loans


# TODO: move to utils
def count_days_till_today(
    date_source: datetime.date,
) -> int:
    today = datetime.date.today()
    delta = (today - date_source).days
    return int(delta)


def format_number(number: int) -> str:
    formatted_number = "{:,}".format(number)
    return formatted_number.replace(",", ".")


def get_payment_url_raw(model) -> str:
    encrypttext = encrypt()
    account_id = encrypttext.encode_string(str(model.id))
    url = settings.PAYMENT_DETAILS + str(account_id)
    shortened_url = ''
    shortened_url = shorten_url(url)
    shortened_url = shortened_url.replace('https://', '')

    return shortened_url


def to_rfc3339(date_str: str) -> Union[str, None]:
    # ref:https://www.rfc-editor.org/rfc/rfc3339
    if not date_str or date_str == 'None':
        return None

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_obj = date_obj.replace(hour=0, minute=0, second=0)

    if not date_obj.tzinfo:
        return date_obj.strftime('%Y-%m-%dT%H:%M:%SZ')  # return as-is, assuming no TZ == UTC

    date_obj_utc = date_obj - timedelta(hours=date_obj.utcoffset().total_seconds() // 3600)

    return date_obj_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

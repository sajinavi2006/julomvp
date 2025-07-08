from builtins import str
import logging

from time import sleep
from datetime import date, datetime
from celery import task
from django.db.models import Sum, Q
from django.conf import settings
from babel.dates import format_date
from juloserver.julo.utils import display_rupiah
from juloserver.julo.clients import get_julo_pn_client, get_julo_sms_client
from juloserver.julo.models import Application, SkiptraceHistory
from juloserver.julo.constants import WaiveCampaignConst, VoiceTypeStatus
from juloserver.julo.clients import get_voice_client
from juloserver.julo.management.commands import blast_robocall_covid_campaign
from juloserver.promo.management.commands import load_covid_19_osp_recovery
from juloserver.julo.models import (
    Payment,
    Loan,
    CampaignSetting,
    CustomerCampaignParameter,
    EmailHistory,
    VoiceCallRecord,
    EarlyPaybackOffer,
)

from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.apiv2.constants import PromoDate
from juloserver.apiv2.constants import JUNE22_PROMO_BANNER_DICT
from juloserver.apiv2.services2.promo import (
    get_hi_season_experiment_account_payment_ids,
    get_june2022_hi_season_experiment_payment_ids
)

from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.constants import CovidRefinancingConst

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.services2 import get_customer_service
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.exceptions import JuloException

from juloserver.urlshortener.models import ShortenedUrl

from juloserver.minisquad.services import upload_payment_details, record_centerix_log
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_loan_refinancing_request_r4_spcecial_campaign,
    check_loan_refinancing_request_is_r4_spcecial_campaign_by_loan)
from juloserver.account_payment.models import AccountPayment
from juloserver.promo.models import WaivePromo


logger = logging.getLogger(__name__)


@task(name='send_pn_notify_cashback')
def send_pn_notify_cashback(application_id, cashback_amt):
    pn_client = get_julo_pn_client()
    application = Application.objects.get(pk=application_id)
    gcm_reg_id = application.device.gcm_reg_id
    pn_client.cashback_transfer_complete_osp_recovery_apr2020(application_id, gcm_reg_id, cashback_amt)


@task(name='load_campaign_covid_data')
def load_campaign_covid_data():
    if str(date.today().year) != '2020': # run only once
        return
    load_covid_19_osp_recovery.Command().handle()
    logger.info({
        "action": "load_covid_19_osp_recovery",
    })


@task(name='summary_covid_campaign')
def summary_covid_campaign():
    if str(date.today().year) != '2020': # run only once
        return
    loan_ids = WaivePromo.objects.all().eligible_loans(WaiveCampaignConst.OSP_RECOVERY_APR_2020).values_list('loan', flat=True)
    for loan_id in loan_ids:
        summary_covid_campaign_sub_task.delay(loan_id)


@task(name='summary_covid_campaign_sub_task')
def summary_covid_campaign_sub_task(loan_id):
    from juloserver.julo.services2.payment_event import waiver_ops_recovery_campaign_promo
    campaign_start_date = date(2020, 3, 24)
    campaign_end_date = date(2020, 4, 16)
    event_type = 'promo waive late fee'
    waiver_ops_recovery_campaign_promo(loan_id, event_type, campaign_start_date, campaign_end_date)


@task(queue='loan_low')
def sending_robocall_covid_campaign():
    blast_robocall_covid_campaign.Command().handle()


@task(queue='loan_low')
def retry_sending_robocall_covid_campaign():
    blast_robocall_covid_campaign.Command().handle()
    voice_data = VoiceCallRecord.objects.filter(event_type=VoiceTypeStatus.COVID_CAMPAIGN)\
                                .exclude(status='completed')\
                                .values_list('voice_identifier', 'call_price')
    voice_client = get_voice_client()

    for loan_id, call_price in voice_data:
        # convert None or '' to 0
        call_price = call_price or 0
        if float(call_price) <= 0:
            loan = Loan.objects.get_or_none(pk=loan_id)
            if loan and loan.is_active:
                voice_client.covid_19_campaign(loan.application.mobile_phone_1, loan.id)
                sleep(1)


@task(queue='collection_low')
def sms_campaign_for_non_contacted_customer_7am():
    """send sms to noncontacted customer in bucket 2, 3, 4 at 7am"""
    sms_template_code = 1
    sms_campaign_for_non_contacted_customer(sms_template_code)


@task(queue='collection_low')
def sms_campaign_for_non_contacted_customer_12h30pm():
    """send sms to noncontacted customer in bucket 2, 3, 4 at 12h30pm"""
    sms_template_code = 2
    sms_campaign_for_non_contacted_customer(sms_template_code)


@task(queue='collection_low')
def sms_campaign_for_non_contacted_customer_5pm():
    """send sms to noncontacted customer in bucket 2, 3, 4 at 5pm"""
    sms_template_code = 3
    sms_campaign_for_non_contacted_customer(sms_template_code)


def sms_campaign_for_non_contacted_customer(sms_template_code):
    """send sms to noncontacted customer in bucket 2, 3, 4"""
    # get list of non-contacted in bucket 2, 3, 4 without paid off
    application_list = SkiptraceHistory.objects.get_non_contact_bucket_234_wo_paid()
    for application_id in application_list:
        sms_campaign_for_non_contacted_customer_subtask.delay(application_id, sms_template_code)


@task(queue='collection_low')
def sms_campaign_for_non_contacted_customer_subtask(application_id, sms_template_code):
    """peform sms sending in subtask to avoid memmory leak"""
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return

    sms_client = get_julo_sms_client()
    fist_name = application.first_name_with_title_short
    phone_number = application.mobile_phone_1
    message, response, formatted_phone = sms_client.sms_campaign_for_noncontacted_customer(
        phone_number,
        fist_name,
        sms_template_code)

    if response['status'] != '0':
        logger.error({
                "task": "sms_campaign_for_non_contacted_customer",
                "error": response,
                "phone_number": phone_number})
        return

    sms = create_sms_history(response=response,
                             application=application,
                             to_mobile_phone=formatted_phone,
                             phone_number_type="mobile_phone_1",
                             customer=application.customer,
                             template_code='mtlstl_sms_incoming_number_2020',
                             message_content=message)
    logger.info({
            "status": "sms_campaign_for_non_contacted_customer",
            "sms_history_id": sms.id,
            "message_id": sms.message_id})

@task(queue='collection_low')
def risk_customer_early_payoff_campaign():
    campaign_setting = CampaignSetting.objects.filter(campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF,
                                                      is_active=True).last()
    if campaign_setting:
        today = timezone.localtime(timezone.now()).date()
        today_plus10 = today + relativedelta(days=10)
        today_minus10 = today + relativedelta(days=-10)
        today_minus25 = today + relativedelta(days=-25)
        today_minus55 = today + relativedelta(days=-55)
        loan_id_covid_refinancing = LoanRefinancingRequest.objects.values_list('loan', flat=True).filter(
            Q(product_type__in=CovidRefinancingConst.reactive_products()) |
            Q(product_type__in=[CovidRefinancingConst.PRODUCTS.p1, CovidRefinancingConst.PRODUCTS.p4,
                                CovidRefinancingConst.PRODUCTS.r4], status=CovidRefinancingConst.STATUSES.approved)
        )
        loans = Loan.objects.get_queryset().all_active_mtl().exclude(id__in=loan_id_covid_refinancing)
        loan_refinancing_request_campaigns = get_loan_refinancing_request_r4_spcecial_campaign(
            [loan.id for loan in loans]
        )
        r4_special_campaign_loan_ids = {
            special_campaign_rec.loan_id
            for special_campaign_rec in loan_refinancing_request_campaigns}
        r4_special_compaign_loans = []
        normal_loans = []
        for loan in loans:
            if loan.id in r4_special_campaign_loan_ids:
                r4_special_compaign_loans.append(loan)
            else:
                normal_loans.append(loan)
        normal_payments = Payment.objects.not_paid().filter(
            due_date__in=[today_plus10, today_minus10, today_minus25, today_minus55],
            loan__in=normal_loans)
        r4_special_payments = Payment.objects.not_paid().filter(
            due_date__in=[today_plus10, today_minus10],
            loan__in=r4_special_compaign_loans)
        payments = list(normal_payments) + list(r4_special_payments)
        customer_service = get_customer_service()
        start_promo = today
        end_promo = today + relativedelta(days=10)
        for payment in payments:
            customer = payment.loan.customer
            application = payment.loan.application
            loan = payment.loan
            payments_risky = loan.payment_set.all().order_by('payment_number')
            payments_unpaid = payments_risky.not_paid()
            payments_paid = payments_risky.filter(payment_status=PaymentStatusCodes.PAID_ON_TIME)
            paid_day_before_due = None
            if payments_paid:
                for payment_paid in payments_paid:
                    paid_day = payment_paid.paid_date - payment_paid.due_date
                    if -15 <= paid_day.days < 0:
                        paid_day_before_due = paid_day.days
            if paid_day_before_due:
                is_risky = customer_service.check_risky_customer(application.id)

                if is_risky:
                    CustomerCampaignParameter.objects.create(customer=customer,
                                                             campaign_setting=campaign_setting,
                                                             effective_date=today)
                    waive_early_payoff = WaivePromo.objects.filter(
                        loan_id=loan.id,
                        promo_event_type=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
                    )
                    if waive_early_payoff:
                        waive_early_payoff.delete()
                    for payment_unpaid in payments_unpaid:
                        WaivePromo.objects.create(
                            loan_id=payment_unpaid.loan_id,
                            payment_id=payment_unpaid.id,
                            remaining_installment_principal=payment_unpaid.remaining_principal,
                            remaining_installment_interest=payment_unpaid.remaining_interest,
                            remaining_late_fee=payment_unpaid.remaining_late_fee,
                            promo_event_type=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF)

                    send_email_early_payoff_subtask.delay(loan.id, start_promo, end_promo,
                                                          first_email=True)


@task(queue='collection_low')
def send_email_early_payoff_campaign_on_8_am():
    today = timezone.localtime(timezone.now()).date()

    today_minus7 = today + relativedelta(days=-7)
    customers_campaign_parameters = CustomerCampaignParameter.objects.filter(
        effective_date=today_minus7,
        campaign_setting__campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
    )
    if customers_campaign_parameters:
        for customers_campaign_parameter in customers_campaign_parameters:
            loan = customers_campaign_parameter.customer.get_last_loan_active_mtl()

            if loan and not check_loan_refinancing_request_is_r4_spcecial_campaign_by_loan(loan.id):
                start_promo = customers_campaign_parameter.effective_date
                end_promo = customers_campaign_parameter.effective_date + relativedelta(days=10)
                send_email_early_payoff_subtask.delay(loan.id, start_promo, end_promo)

@task(queue='collection_low')
def send_email_early_payoff_campaign_on_10_am():
    from juloserver.julo.services2.payment_event import waiver_early_payoff_campaign_promo

    today = timezone.localtime(timezone.now()).date()

    today_minus3 = today + relativedelta(days=-3)
    today_minus9 = today + relativedelta(days=-9)
    today_minus10 = today + relativedelta(days=-10)
    customers_campaign_parameters = CustomerCampaignParameter.objects.filter(
        effective_date__in=[today_minus3, today_minus9, today_minus10],
        campaign_setting__campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
    )
    if customers_campaign_parameters:
        for customers_campaign_parameter in customers_campaign_parameters:
            loan = customers_campaign_parameter.customer.get_last_loan_active_mtl()

            if loan and not check_loan_refinancing_request_is_r4_spcecial_campaign_by_loan(loan.id):
                start_promo = customers_campaign_parameter.effective_date
                end_promo = customers_campaign_parameter.effective_date + relativedelta(days=10)
                if customers_campaign_parameter.effective_date == today_minus10:
                    waiver_early_payoff_campaign_promo(loan.id, start_promo)
                elif customers_campaign_parameter.effective_date != today_minus10:
                    send_email_early_payoff_subtask.delay(loan.id, start_promo, end_promo)

@task(queue='collection_low')
def send_email_early_payoff_subtask(loan_id, start_promo, end_promo, first_email=None):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None

    customer = loan.customer
    application = loan.application
    payments = loan.payment_set.all().order_by('payment_number')
    list_table = []
    for payment_table in payments:
        dpd = str(payment_table.due_late_days)
        is_paid = 'Tidak'
        if payment_table.payment_status_id in PaymentStatusCodes.paid_status_codes():
            is_paid = 'Ya'
            dpd = '-'
        if payment_table.due_late_days <= 0 and is_paid != 'Ya':
            dpd = 'NA'
            is_paid = 'Not Due'

        list_table.append(
            dict(
                payment_number=payment_table.payment_number,
                installment_principal=display_rupiah(payment_table.original_due_amount),
                due_date=format_date(payment_table.due_date, 'dd-MMMM-YYYY', locale='id_ID'),
                dpd=dpd,
                is_paid=is_paid,
                late_fee_amount=display_rupiah(payment_table.late_fee_amount),
                paid_amount=display_rupiah(payment_table.paid_amount),
                due_amount=display_rupiah(payment_table.due_amount)
            )
        )
    total_amount = Payment.objects.filter(loan=loan).aggregate(
        total_due_amount=Sum('due_amount'),
        total_interest=Sum('installment_interest'),
        total_late_fee=Sum('late_fee_amount'),
        total_installment_principal=Sum('installment_principal'),
    )
    waive_promo = WaivePromo.objects.filter(
        loan=loan,
        promo_event_type=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF
    )
    if not waive_promo:
        return
    total_amount_waive = waive_promo.aggregate(
        total_due_amount=Sum('remaining_installment_principal') + Sum('remaining_installment_interest') + Sum(
            'remaining_late_fee'),
        total_interest=Sum('remaining_installment_interest'),
        total_late_fee=Sum('remaining_late_fee'),
        total_installment_principal=Sum('remaining_installment_principal'))
    total_discount = total_amount['total_due_amount'] - (total_amount_waive['total_interest'] * 0.3) - \
                     total_amount_waive['total_late_fee']
    total_must_paid = total_amount['total_due_amount']
    if total_discount <= 0:
        return
    total_installment_amount = total_amount['total_installment_principal'] + total_amount['total_interest']
    early_payback_event_path = settings.EMAIL_STATIC_FILE_PATH + 'Early_Payback_Event.png'
    context = dict(
        total_interest_discount=display_rupiah((0.3 * total_amount_waive['total_interest'])),
        fullname_with_title=loan.application.fullname_with_title,
        total_installment_amount=display_rupiah(total_installment_amount),
        total_current_late_fee=display_rupiah(total_amount['total_late_fee']),
        total_due_amount=display_rupiah(total_amount['total_due_amount']),
        total_discount=display_rupiah(int(total_discount)),
        total_before_discount=display_rupiah(total_must_paid),
        table_list=list_table,
        base_url=settings.BASE_URL,
        end_promo=end_promo,
        start_promo=start_promo,
        early_payback_event=early_payback_event_path
    )
    julo_email_client = get_julo_email_client()
    try:
        status, headers, subject, msg = julo_email_client.email_early_payoff_campaign(context, email_to=customer.email)
        template_code = "email_early_payback_1"

        email_history = EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=template_code,
            status=status,
            payment=payments.not_paid().order_by('payment_number').first()
        )
        if first_email:
            record_early_payback_offer.delay(loan_id, email_history.status)

        logger.info({
            "action": "email_early_payback_1",
            "customer_id": customer.id,
            "promo_type": template_code
        })
    except Exception as e:
        logger.error({
            "action": "email_early_payback_1",
            "message": str(e)
        })


@task(name='schedule_for_dpd_minus_to_centerix')
def schedule_for_dpd_minus_to_centerix():
    """send dpd_minus flow the order T-5, T-3, T-1"""
    send_dpd_minus_to_centerix(-5)
    send_dpd_minus_to_centerix(-3)
    send_dpd_minus_to_centerix(-1)


def send_dpd_minus_to_centerix(dpd):
    today = timezone.localtime(timezone.now()).date()
    """send dpd minus T-5, T-3, T-1 payments to centerix"""
    if dpd not in [-5, -3, -1]:
        logger.error({
            "action": "send_dpd_minus_to_centerix",
            "error": "dpd is not expected",
            "data": {"dpd": dpd}
        })
        return
    campaign_code = "JULO_T{}_RISKY_CUSTOMERS".format(dpd)

    # get data from pd_collection_model_result table, order by sort_rank column and ascending(1, 2, 3)
    collection_model_payments = PdCollectionModelResult.objects.filter(range_from_due_date=dpd,
                                                                       prediction_date=today) \
                                                               .order_by('sort_rank')
    payment_ids = collection_model_payments.values_list('payment_id', flat=True)
    logger.info({
        "action": "send_dpd_minus_to_centerix",
        "data": {
            "dpd": dpd,
            "campaign_code": campaign_code,
            "payment_ids": payment_ids
        }
    })
    if collection_model_payments:
        response = upload_payment_details(collection_model_payments, campaign_code)
        record_centerix_log(collection_model_payments, campaign_code)
        logger.info({
            "action": "send_dpd_minus_to_centerix",
            "response": response
        })


@task(name='record_early_payback_offer')
def record_early_payback_offer(loan_id, email_status):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return
    application = loan.application
    payment = Payment.objects.by_loan(loan).not_paid().order_by('payment_number').first()
    customer_campaign_parameters = CustomerCampaignParameter.objects.filter(
        customer=loan.customer,
        campaign_setting__campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF,
    )
    if customer_campaign_parameters:
        cycle_number = customer_campaign_parameters.count()
        promo_date = customer_campaign_parameters.last().effective_date
        EarlyPaybackOffer.objects.create(
            loan=loan,
            application=application,
            is_fdc_risky=True,
            cycle_number=cycle_number,
            promo_date=promo_date,
            dpd=payment.due_late_days,
            email_status=email_status,
            paid_off_indicator=False,
        )


@task(name='check_early_payback_offer_data')
def check_early_payback_offer_data():
    early_payback_offers = EarlyPaybackOffer.objects.filter(
        Q(paid_off_indicator=False) |
        Q(email_status__in=['sent_to_sendgrid', 'delivered', '202', 'open', 'processed'])
    )

    if not early_payback_offers:
        return

    for early_payback_offer in early_payback_offers.iterator():
        update_data_early_payback_offer_subtask.delay(early_payback_offer.id)


@task(name='update_data_early_payback_offer_subtask')
def update_data_early_payback_offer_subtask(early_payback_offer_id):
    early_payback_offer = EarlyPaybackOffer.objects.filter(pk=early_payback_offer_id).last()
    email_history = EmailHistory.objects.filter(
        application=early_payback_offer.application,
        template_code='email_early_payback_1',
    ).last()
    if not email_history:
        return
    paid_off = False
    if early_payback_offer.loan.status == LoanStatusCodes.PAID_OFF:
        paid_off = True
    early_payback_offer.update_safely(
        paid_off_indicator=paid_off,
        email_status=email_history.status,
    )


@task(name='update_is_fdc_risky_early_payback_offer')
def update_is_fdc_risky_early_payback_offer(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if application and application.is_fdc_risky is None:
        return

    early_payback_offers = EarlyPaybackOffer.objects.filter(
        application=application
    )

    if early_payback_offers:
        early_payback_offers.update(
            is_fdc_risky=application.is_fdc_risky
        )

#june 2022 Hi Season
@task(name='run_send_email_june2022_hi_season')
def run_send_email_june2022_hi_season():
    today = timezone.localtime(timezone.now()).date()
    promo_start = datetime.strptime(PromoDate.JUNE22_PROMO_EMAIL_START_DATE, '%Y-%m-%d')
    promo_end = datetime.strptime(PromoDate.JUNE22_PROMO_EMAIL_END_DATE, '%Y-%m-%d')
    if today < promo_start.date() or today > promo_end.date():
        return

    due_date_target = today + relativedelta(days=6)
    payment_ids = get_june2022_hi_season_experiment_payment_ids(due_date_target)
    account_payment_ids = get_hi_season_experiment_account_payment_ids(due_date_target)
    cash_url = "https://www.julo.co.id/blog/kini-melesat-julo"
    for payment_id in payment_ids:
        email_june2022_hi_season_subtask.delay(payment_id, cash_url)
    for account_payment_id in account_payment_ids:
        email_june2022_hi_season_subtask.delay(account_payment_id, cash_url, True)


@task(name='email_june2022_hi_season_subtask')
def email_june2022_hi_season_subtask(payment_id, shortened_url, is_account_payment=False):
    if not is_account_payment:
        payment = Payment.objects.get_or_none(id=payment_id)
        if payment is None:
            raise JuloException("Payment not found")
        customer = payment.loan.customer
        application = payment.loan.application
    else:
        payment = AccountPayment.objects.get_or_none(id=payment_id)
        if payment is None:
            raise JuloException("Account Payment not found")
        customer = payment.account.customer
        application = payment.account.application_set.last()

    payment_t_minus_target = payment.due_date - relativedelta(days=3)
    banner_url = JUNE22_PROMO_BANNER_DICT['email'][str(payment_t_minus_target)]

    # Do send email
    julo_email_client = get_julo_email_client()
    try:
        _status, headers, subject, msg = julo_email_client.email_june_2022_promo(
            customer,
            banner_url,
            payment_t_minus_target,
            shortened_url)
        template_code = "email_june2022_hi_season"

        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=customer.email,
            subject=subject,
            application=application,
            message_content=msg,
            template_code=template_code,
        )

        logger.info({
            "action": "email_june2022_hi_season",
            "customer_id": customer.id,
            "promo_type": template_code
        })
    except Exception as e:
        logger.info({
            "action": "email_june2022_hi_season",
            "customer_id": customer.id,
            "errors": str(e)
        })


#June Hi Season
@task(name='run_send_pn1_june22_hi_season_8h')
def run_send_pn1_june22_hi_season_8h():
    today = timezone.localtime(timezone.now()).date()

    promo_start_pn1 = datetime.strptime(PromoDate.JUNE22_PROMO_PN1_START_DATE, '%Y-%m-%d')
    promo_end_pn1 = datetime.strptime(PromoDate.JUNE22_PROMO_PN1_END_DATE, '%Y-%m-%d')

    if today < promo_start_pn1.date() or today > promo_end_pn1.date():
        return
    due_date_target = today + relativedelta(days=5)
    pn_type = 'pn1_8h'

    payment_ids = get_june2022_hi_season_experiment_payment_ids(due_date_target)
    account_payment_ids = get_hi_season_experiment_account_payment_ids(due_date_target)
    for payment_id in payment_ids:
        send_pn_june22_hi_season_subtask.delay(payment_id, pn_type)
    for account_payment_id in account_payment_ids:
        send_pn_june22_hi_season_subtask.delay(account_payment_id, pn_type, True)


@task(name='run_send_pn2_june22_hi_season_8h')
def run_send_pn2_june22_hi_season_8h():
    today = timezone.localtime(timezone.now()).date()

    promo_start_pn2 = datetime.strptime(PromoDate.JUNE22_PROMO_PN2_START_DATE, '%Y-%m-%d')
    promo_end_pn2 = datetime.strptime(PromoDate.JUNE22_PROMO_PN2_END_DATE, '%Y-%m-%d')

    if today < promo_start_pn2.date() or today > promo_end_pn2.date():
        return

    due_date_target = today + relativedelta(days=3)
    pn_type = 'pn2_8h'

    payment_ids = get_june2022_hi_season_experiment_payment_ids(due_date_target)
    account_payment_ids = get_hi_season_experiment_account_payment_ids(due_date_target)
    for payment_id in payment_ids:
        send_pn_june22_hi_season_subtask.delay(payment_id, pn_type)
    for account_payment_id in account_payment_ids:
        send_pn_june22_hi_season_subtask.delay(account_payment_id, pn_type, True)


@task(name='send_pn_june22_hi_season_subtask')
def send_pn_june22_hi_season_subtask(payment_id, pn_type, is_account_payment=False):
    if not is_account_payment:
        payment = Payment.objects.get_or_none(id=payment_id)
        if payment is None:
            raise JuloException("Payment not found")
        device = payment.loan.application.device
    else:
        payment = AccountPayment.objects.get_or_none(id=payment_id)
        if payment is None:
            raise JuloException("Account Payment not found")
        device = payment.account.application_set.last().device

    if not device:
        logger.warning({
            'action': 'send_pn_june22_hi_season_subtask',
            'data': {'payment_id': payment_id, 'pn_type': pn_type},
            'message': 'Device can not be found'
        })
        return

    gcm_reg_id = device.gcm_reg_id
    payment_t_minus_target = payment.due_date - relativedelta(days=3)

    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_june2022_hi_season(gcm_reg_id, pn_type, payment_t_minus_target)
    logger.info(
        {
            "action": "send_pn_june22_hi_season_subtask",
            "gcm_reg_id": gcm_reg_id,
        }
    )

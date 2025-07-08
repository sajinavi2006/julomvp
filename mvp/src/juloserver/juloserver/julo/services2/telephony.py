from builtins import str
from celery import task
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ..clients import get_autodial_client
from ..clients import get_robocall_client
from ..exceptions import JuloException
from ..models import Payment
from ..models import QuirosProfile
from ..models import QuirosCallRecord
from ..models import Skiptrace
from ..product_lines import ProductLineCodes
from ..services import choose_number_to_robocall


class TelephonyServiceError(JuloException):
    pass


def call_customer(agent, phone_number, skiptrace_id):

    quiros_profile = QuirosProfile.objects.get(agent=agent)
    update_telephony_token_if_needed(quiros_profile)

    skiptrace = Skiptrace.objects.get(id=skiptrace_id)
    customer_info = construct_customer_info_string(skiptrace)

    telephony_client = get_autodial_client(token=quiros_profile.current_token)
    call_id = telephony_client.call(customer_info, phone_number)

    QuirosCallRecord.objects.create(
        agent=agent, skiptrace=skiptrace, call_id=call_id, phone_number=phone_number)


def hangup_customer_call(agent, phone_number, skiptrace_id):

    quiros_profile = QuirosProfile.objects.get(agent=agent)
    update_telephony_token_if_needed(quiros_profile)

    skiptrace = Skiptrace.objects.get(id=skiptrace_id)
    quiros_record = QuirosCallRecord.objects.filter(
        agent=agent, skiptrace=skiptrace, phone_number=phone_number).last()
    if not quiros_record:
        return
    call_id = quiros_record.call_id

    telephony_client = get_autodial_client(token=quiros_profile.current_token)
    telephony_client.hangup(call_id)


def construct_customer_info_string(skiptrace):
    """
    Since this info useful for reporting only, might be good not to reveal
    too much customer info for protecting our customers' data
    """
    customer_info = '%s %s %s' % (
        skiptrace.application.application_xid,
        skiptrace.application.status,
        skiptrace.application.product_line_code
    )
    return customer_info


def update_telephony_token_if_needed(quiros_profile):
    if quiros_profile.does_token_need_renewal:
        telephony_client = get_autodial_client()
        token = telephony_client.login(
            quiros_profile.username, quiros_profile.password)
        quiros_profile.update_token(token)
        quiros_profile.save()


@task(name='check_all_agents_dialing_token')
def check_all_agents_dialing_token():
    for quiros_profile in QuirosProfile.objects.all():
        update_telephony_token_if_needed(quiros_profile)


@task(name='update_all_call_records')
def update_all_call_records():

    qcr_values_list = QuirosCallRecord.objects\
        .filter(status=None)\
        .values_list('id', 'call_id')\
        .order_by('id')

    for qcr_id, call_id in qcr_values_list:
        update_call_record.delay(qcr_id, call_id)


@task(name='update_call_record')
def update_call_record(quiros_call_record_id, call_id):

    for quiros_profile in QuirosProfile.objects.all():
        update_telephony_token_if_needed(quiros_profile)

    autodial_client = get_autodial_client(token=quiros_profile.current_token)
    result = autodial_client.get_report_by_call_id_if_exists(call_id)

    quiros_call_record = QuirosCallRecord.objects.get(id=quiros_call_record_id)
    quiros_call_record.status = result['status']
    quiros_call_record.duration = result['duration']
    quiros_call_record.extension = result['extension']
    quiros_call_record.created_time = result['created']
    quiros_call_record.save()


################################################################################

# @task(name='trigger_robocall')
# def trigger_robocall():
#     sentry_client = get_julo_sentry_client()
#     autodialer_client = get_julo_autodialer_client()
#     mtl_days_from_now = [3, 5]
#     all_robocall_active = Payment.objects.filter(is_robocall_active=True)
#     MTL_robocall_active = all_robocall_active.filter(
#     loan__application__product_line__product_line_code__in=ProductLineCodes.mtl())
#     for day_from_now in mtl_days_from_now:
#         selected_due_date = date.today() + relativedelta(days=day_from_now)
#         for payment in MTL_robocall_active.filter(due_date=selected_due_date):
#             if payment.payment_status.status_code < PaymentStatusCodes.PAYMENT_DUE_TODAY:
#                 try:
#                     number_to_call, skiptrace_id = choose_number_to_robocall(
#                         payment.loan.application)
#                     autodialer_client.robodial(number_to_call,
#                                                skiptrace_id,
#                                                str(payment.payment_number),
#                                                str(payment.due_amount),
#                                                str(payment.due_date), 1)
#                     AutoDialerRecord.objects.create(payment=payment,
#                                                     skiptrace=Skiptrace.objects.filter(
#                                                         id=skiptrace_id).first()
#                     )
#                 except Exception as e:
#                     sentry_client.captureException()


def get_reports_from_campaigns_and_delete():
    pass


def retry_campaign():
    """
    API call to get campaign status
    If there are unprocessed, call the retry API
    :return:
    """


@task(name='populate_customer_buckets_for_robocalling_today')
def populate_customer_buckets_for_robocalling_today():
    mtl_due_date_reminders.delay()
    # another campaign
    # another campaign
    # another campaign


@task(name='mtl_due_date_reminders')
def mtl_due_date_reminders():
    """
    query payments to be robocalled
    get skiptrace for each payment
    create bucket for today for this query
    add skiptraces to bucket
    create campaign for today for this
    add bucket to campaign
    trigger retries
    """
    # retry_interval_mins = 300

    mtl_codes = ProductLineCodes.mtl()
    payments = Payment.objects.normal()\
        .filter(is_robocall_active=True)\
        .by_product_line_codes(mtl_codes)\
        .not_overdue()

    today = timezone.now().date()
    days_before_list = [3, 5]

    bucket_label = '_'.join([
        'bucket',
        'product_codes',
        '_'.join(mtl_codes),
        'dpd_minus',
        '_'.join(days_before_list),
        str(today)
    ])
    robocall_client = get_robocall_client()
    bucket_id = robocall_client.create_bucket(bucket_label)

    for days_before in days_before_list:

        selected_due_date = today + relativedelta(days=days_before)
        for payment in payments.filter(due_date=selected_due_date):

            number_to_call, skiptrace_id = choose_number_to_robocall(
                payment.loan.application)

            skiptrace = Skiptrace.objects.get(id=skiptrace_id)
            customer_info = construct_customer_info_string(skiptrace)

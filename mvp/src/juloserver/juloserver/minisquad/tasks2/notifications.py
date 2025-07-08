import logging
from _operator import or_
from ast import literal_eval
from datetime import timedelta
from functools import reduce

from django.utils import timezone
from dateutil.relativedelta import relativedelta
from celery import task
from django.conf import settings
from django.db.models import (
    Q,
)

from juloserver.account.models import ExperimentGroup
from juloserver.account_payment.models import AccountPayment
from juloserver.apiv2.models import (
    PdCollectionModelResult,
)
from juloserver.julo.clients import (
    get_julo_pn_client,
    get_external_email_client,
    get_julo_sentry_client,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import ExperimentSetting, Customer, Loan, EmailHistory, FeatureSetting

from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.minisquad.constants import (
    RedisKey,
    ExperimentConst,
)
from juloserver.minisquad.models import intelixBlacklist
from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids
from juloserver.minisquad.services2.notification_related import (
    determine_segment_for_collection_tailor,
    construct_experiment_data_for_email_and_robocall_collection_tailor_experiment,
)
from juloserver.minisquad.utils import (
    validate_activate_experiment,
)
from juloserver.moengage.services.data_constructors import loan_refinancing_request_staus
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.pn_delivery.models import PNDelivery
from juloserver.loan_refinancing.services.notification_related import CovidLoanRefinancingEmail
from juloserver.portal.core.templatetags.unit import format_rupiahs, convert_date_to_string
from django.template.loader import render_to_string
from babel.dates import format_date
from juloserver.julo.constants import EmailDeliveryAddress
from juloserver.minisquad.constants import FeatureNameConst
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
)
import os
import base64
import re

logger = logging.getLogger(__name__)

@task(queue="collection_low")
def send_slack_notification_intelix_blacklist():
    today = timezone.localtime(timezone.now()).date()
    a_week_ago = today - relativedelta(weeks=1)
    account_ids = intelixBlacklist.objects.filter(
        cdate__date__gte=a_week_ago
    ).filter(
        Q(expire_date__gte=today) | Q(expire_date__isnull=True)
    ).values_list('account', flat=True)
    message = 'This week there are {} rows added \nAccount id : {}'.format(
        len(account_ids), account_ids
    )
    if settings.ENVIRONMENT != 'prod':
        message += "\n*( TESTING PURPOSE ONLY FROM %s )*" % (
            settings.ENVIRONMENT.upper())
    get_slack_bot_client().api_call("chat.postMessage",
                                    channel="C023HFK1X9S",
                                    text=message)


@task(queue="collection_normal")
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILOR_EXPERIMENT)
def send_pn_for_collection_tailor_experiment(*args, **kwargs):
    redis_client = get_redis_client()
    cached_oldest_account_payment_ids = redis_client.get_list(RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
    if not cached_oldest_account_payment_ids:
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        if oldest_account_payment_ids:
            redis_client.set_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
    else:
        oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))
    collection_tailor_experiment = kwargs['experiment']
    criteria = collection_tailor_experiment.criteria
    eligible_dpd_params = criteria.get('eligible_dpd')
    sort_method_list = criteria.get('sort_method_list')
    is_full_rollout = criteria.get('is_full_rollout')
    # for loop tailor types
    filter_sort_method_objects = Q()
    for method_type in sort_method_list:
        filter_sort_method_objects |= Q(sort_method__endswith=method_type)

    data_for_send_pn = []
    for eligible_dpd_param in eligible_dpd_params:
        dpd = eligible_dpd_param["dpd"]
        range_from_due_filter = eligible_dpd_param["checking_dpd_at"]
        if dpd is None or range_from_due_filter is None:
            continue
        data_for_send_pn.extend(
            determine_segment_for_collection_tailor(
                dpd, range_from_due_filter, oldest_account_payment_ids, filter_sort_method_objects)
        )
    if not data_for_send_pn:
        return

    # trigger for insert into experiment group
    if not is_full_rollout:
        redis_client.delete_key(RedisKey.TAILOR_EXPERIMENT_FOR_LOG)
        redis_client.set(
            RedisKey.TAILOR_EXPERIMENT_FOR_LOG,
            data_for_send_pn, timedelta(hours=22)
        )

    redis_client.delete_key(RedisKey.TAILOR_EXPERIMENT_DATA)
    redis_client.set(
        RedisKey.TAILOR_EXPERIMENT_DATA,
        data_for_send_pn, timedelta(hours=22)
    )
    if is_full_rollout:
        from juloserver.moengage.tasks import \
            trigger_send_user_attribute_collection_tailor_experiment
        trigger_send_user_attribute_collection_tailor_experiment.delay()
    else:
        save_tailor_experiment_log.delay()


@task(queue="collection_normal")
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILOR_EXPERIMENT)
def save_tailor_experiment_log(*args, **kwargs):
    from juloserver.moengage.tasks import trigger_send_user_attribute_collection_tailor_experiment
    collection_tailor_experiment = kwargs['experiment']
    redis_client = get_redis_client()
    experiment_data = redis_client.get(RedisKey.TAILOR_EXPERIMENT_FOR_LOG)
    if not experiment_data:
        return

    criteria = collection_tailor_experiment.criteria
    is_full_rollout = criteria.get('is_full_rollout')
    if is_full_rollout:
        return
    experiment_data = literal_eval(experiment_data)
    converted_data = []
    for data in experiment_data:
        converted_data.append(
            ExperimentGroup(
                experiment_setting=collection_tailor_experiment,
                group='control' if not data['segment'] else 'experiment',
                segment=data['segment'], account_payment_id=data['account_payment']
            )
        )
    ExperimentGroup.objects.bulk_create(converted_data)
    redis_client.delete_key(RedisKey.TAILOR_EXPERIMENT_FOR_LOG)
    # trigger send data to moengage
    trigger_send_user_attribute_collection_tailor_experiment.delay()


@task(queue='collection_normal')
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILOR_EXPERIMENT)
def trigger_manual_send_pn_for_unsent_collection_tailor_experiment_backup(*args, **kwargs):
    collection_tailor_experiment = kwargs['experiment']
    criteria = collection_tailor_experiment.criteria
    # Check get the dpd list from experiment
    for eligible_dpd in criteria.get('eligible_dpd'):
        send_unsent_pn_for_collection_tailor_experiment_backup.delay(eligible_dpd.get("dpd"))


@task(queue='collection_normal')
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILOR_EXPERIMENT)
def send_unsent_pn_for_collection_tailor_experiment_backup(dpd, *args, **kwargs):
    collection_tailor_experiment = kwargs['experiment']
    today_date = timezone.localtime(timezone.now()).date()
    due_date_base_on_dpd = today_date - timedelta(days=dpd)
    criteria = collection_tailor_experiment.criteria
    is_full_rollout = criteria.get('is_full_rollout')
    tailor_data = []
    collection_tailor_data = PdCollectionModelResult.objects.none()
    if is_full_rollout:
        segment_list = criteria.get('sort_method_list')
        redis_client = get_redis_client()
        tailor_data = redis_client.get(RedisKey.TAILOR_EXPERIMENT_DATA)
        if not tailor_data:
            return
        tailor_data = literal_eval(tailor_data)
        # filter only related dpd
        tailor_data = [d for d in tailor_data if d['send_as_dpd'] == dpd]
    else:
        collection_tailor_data = ExperimentGroup.objects.filter(
            cdate__date=today_date, experiment_setting=collection_tailor_experiment,
            account_payment__isnull=False, account_payment__due_date=due_date_base_on_dpd
        ).exclude(group='control').values_list('segment', flat=True).distinct('segment')
        segment_list = collection_tailor_data.values_list('segment', flat=True).distinct('segment')

    if not tailor_data:
        return

    check_template_codes = []
    for segment in segment_list:
        check_template_codes.append('J1_pn_{}_T{}'.format(segment, str(dpd)))
    if not check_template_codes:
        return

    sent_account_payments_ids = PNDelivery.objects.filter(
        created_on__date=today_date, source='MOENGAGE').filter(
        reduce(or_, [
            Q(pn_blast__name__contains=template_code) for template_code in check_template_codes])
    ).values_list('pntracks__account_payment_id', flat=True)
    unsent_experiment_groups = []
    if is_full_rollout:
        already_sent_account_payment_ids = set(list(sent_account_payments_ids))
        # remove already sent account payment via MOE
        unsent_experiment_groups = [
            tailor_item for tailor_item in tailor_data if tailor_item['account_payment']
            not in already_sent_account_payment_ids]
    else:
        low_risk_collection_models = collection_tailor_data.exclude(
            account_payment_id__in=sent_account_payments_ids
        ).filter(
            account_payment__account__account_lookup__workflow__name=WorkflowConst.JULO_ONE
        ).exclude(account_payment__status__in=PaymentStatusCodes.paid_status_codes())
        unsent_experiment_groups.extend(list(low_risk_collection_models))
    if not unsent_experiment_groups:
        logger.info({
            "action": "send_unsent_pn_for_collection_tailor_experiment_backup",
            "message": "no unsent data"
        })
        return

    for unsent_experiment_group in unsent_experiment_groups:
        if is_full_rollout:
            account_payment = AccountPayment.objects.get_or_none(
                pk=unsent_experiment_group.get('account_payment'))
            collection_segment = unsent_experiment_group.get('segment')
            if account_payment.status_id in PaymentStatusCodes.paid_status_codes():
                continue
        else:
            account_payment = unsent_experiment_group.account_payment
            collection_segment = unsent_experiment_group.segment
        device = account_payment.account.application_set.last().device
        backup_template_code = 'J1_pn_{}_backup_T{}'.format(
            collection_segment, str(dpd))

        if not device or not device.gcm_reg_id:
            logger.info({
                "action": "send_unsent_pn_for_collection_tailor_experiment_backup",
                "template_code": backup_template_code,
                "account_payment_id": account_payment.id,
                "message": "customer did not have device"
            })
            continue

        gcm_reg_id = device.gcm_reg_id
        julo_pn_client = get_julo_pn_client()
        julo_pn_client.pn_tailor_backup(
            gcm_reg_id,
            account_payment,
            backup_template_code,
            dpd
        )


@task(queue="collection_normal")
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILORED_EXPERIMENT_ROBOCALL)
def send_robocall_for_collection_tailor_experiment(*args, **kwargs):
    today_date = timezone.localtime(timezone.now()).date()
    redis_client = get_redis_client()
    cached_oldest_account_payment_ids = redis_client.get_list(RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
    if not cached_oldest_account_payment_ids:
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        if oldest_account_payment_ids:
            redis_client.set_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
    else:
        oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

    robocall_collection_tailor_experiment = kwargs['experiment']
    criteria = robocall_collection_tailor_experiment.criteria
    eligible_dpd_params = criteria.get('eligible_dpd')
    sort_method_list = criteria.get('sort_method_list')
    account_id_tail = criteria.get('account_id_tail')
    control_group = account_id_tail["control_group"]
    experiment_group = account_id_tail["experiment_group"]
    data_for_experiment_group_table = []

    # for loop tailor types
    filter_sort_method_objects = Q()
    for method_type in sort_method_list:
        filter_sort_method_objects |= Q(sort_method__endswith='_'+method_type)

    # for loop account id tail
    filter_account_id_objects = Q()
    for account_id in experiment_group:
        filter_account_id_objects |= Q(account__id__endswith=account_id)

    for eligible_dpd_param in eligible_dpd_params:
        dpd = eligible_dpd_param["dpd"]
        range_from_due_filter = eligible_dpd_param["checking_dpd_at"]
        if dpd is None or range_from_due_filter is None:
            continue
    
        # eligible account payment base on dpd
        eligible_account_payment = AccountPayment.objects.filter(
            pk__in=oldest_account_payment_ids, due_date=today_date-timedelta(days=dpd),
            account__application__partner__isnull=True
        )

        # control group data
        control_group_account_payments = eligible_account_payment.extra(
            where=["right(account_payment.account_id::text, 1) in %s"],
            params=[tuple(list(map(str, control_group)))]
        ).extra(
            select={
                'account_payment': 'account_payment_id',
                'segment': "''",
                'send_as_dpd': dpd
            }
        ).values('account_payment', 'segment', 'send_as_dpd')
        data_for_experiment_group_table.extend(
            list(control_group_account_payments))

        # experiment group data
        eligible_account_payment = eligible_account_payment.exclude(
            pk__in=list(control_group_account_payments.values_list('id', flat=True))
        )
        if eligible_account_payment:    
            eligible_account_payment_ids = list(eligible_account_payment.values_list('id', flat=True))
            # experiment group data from pd_collection_model_result_exclude table
            experiment_from_exclude_model = construct_experiment_data_for_email_and_robocall_collection_tailor_experiment(
                eligible_account_payment_ids, filter_account_id_objects,
                filter_sort_method_objects, range_from_due_filter, dpd, True
            )
            if experiment_from_exclude_model:
                data_for_experiment_group_table.extend(
                    list(experiment_from_exclude_model)
                )
                eligible_account_payment = eligible_account_payment.exclude(
                    pk__in=list(experiment_from_exclude_model.values_list('account_payment', flat=True))
                )

        if eligible_account_payment:
            eligible_account_payment_ids = list(eligible_account_payment.values_list('id', flat=True))
            # experiment group data from pd_collection_model_result table
            experiment_from_non_exclude_model = construct_experiment_data_for_email_and_robocall_collection_tailor_experiment(
                eligible_account_payment_ids, filter_account_id_objects,
                filter_sort_method_objects, range_from_due_filter, dpd, False
            )
            # omiting experiment group data present in pd_collection_model_result table
            if experiment_from_non_exclude_model:
                eligible_account_payment = eligible_account_payment.exclude(
                    pk__in=list(experiment_from_non_exclude_model.values_list('account_payment', flat=True))
                )
                 
        if eligible_account_payment:
            eligible_account_payment = eligible_account_payment.extra(
                select={
                    'account_payment': 'account_payment_id',
                    'segment': """SELECT CASE WHEN due_amount >= 500000 THEN 'bull' ELSE 'scorpion' END""",
                    'send_as_dpd': dpd
                }
            ).values('account_payment', 'segment', 'send_as_dpd')

            data_for_experiment_group_table.extend(
                list(eligible_account_payment))

    # trigger for insert into experiment group
    if data_for_experiment_group_table:
        redis_client.set(
            RedisKey.ROBOCALL_TAILOR_EXPERIMENT_FOR_LOG,
            data_for_experiment_group_table,
            timedelta(hours=4)
        )

    save_robocall_tailor_experiment_log.delay()


@task(queue="collection_normal")
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILORED_EXPERIMENT_ROBOCALL)
def save_robocall_tailor_experiment_log(*args, **kwargs):
    robocall_collection_tailored_experiment = kwargs['experiment']
    redis_client = get_redis_client()
    experiment_data = redis_client.get(RedisKey.ROBOCALL_TAILOR_EXPERIMENT_FOR_LOG)
    if not experiment_data:
        return

    experiment_data = literal_eval(experiment_data)
    converted_data = []
    for data in experiment_data:
        converted_data.append(
            ExperimentGroup(
                experiment_setting=robocall_collection_tailored_experiment,
                group='control' if not data['segment'] else 'experiment',
                segment=data['segment'], account_payment_id=data['account_payment']
            )
        )

    ExperimentGroup.objects.bulk_create(converted_data)
    redis_client.delete_key(RedisKey.ROBOCALL_TAILOR_EXPERIMENT_FOR_LOG)


@task(queue='collection_normal')
def write_data_to_experiment_group(
        experiment_setting_id, control_account_payment_ids, experiment_account_payment_ids):
    if not ExperimentSetting.objects.get_or_none(pk=experiment_setting_id):
        return

    constructed_data = []
    control_account_payments = AccountPayment.objects.filter(id__in=control_account_payment_ids)
    experiment_account_payments = AccountPayment.objects.filter(
        id__in=experiment_account_payment_ids)
    for account_payment in control_account_payments.iterator():
        constructed_data.append(
            ExperimentGroup(
                account_payment_id=account_payment.id,
                account_id=account_payment.account_id,
                experiment_setting_id=experiment_setting_id,
                group='control'
            )
        )
    for account_payment in experiment_account_payments.iterator():
        constructed_data.append(
            ExperimentGroup(
                account_payment_id=account_payment.id,
                account_id=account_payment.account_id,
                experiment_setting_id=experiment_setting_id,
                group='experiment'
            )
        )
    ExperimentGroup.objects.bulk_create(constructed_data, batch_size=1000)


@task(queue='retrofix_normal')
def send_r4_promo_for_b5_lender_jtf(**kwargs):
    fn_name = 'send_email_r4_promo_for_b5'
    logger.info({"action": fn_name, "message": "start"})
    loan_refinancing_request_id = kwargs.get('loan_refinancing_request_id', None)
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        id=loan_refinancing_request_id
    ).last()
    api_key = kwargs.get('api_key', None)
    curr_retries_attempt = send_r4_promo_for_b5_lender_jtf.request.retries
    try:
        loan_refinancing_email = CovidLoanRefinancingEmail(loan_refinancing_request)
        loan_refinancing_email.send_r4_promo_for_b5_lender_jtf(api_key)
        logger.info({"action": "send_email_r4_promo_for_b5", "message": "finish"})
    except Exception as e:
        if curr_retries_attempt >= send_r4_promo_for_b5_lender_jtf.max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'Maximum retry for process_data_generation_b5',
                    'error': str(e),
                }
            )
            return
        raise send_r4_promo_for_b5_lender_jtf.retry(
            countdown=600,
            exc=e,
            max_retries=3,
            kwargs={
                'loan_refinancing_request_id': loan_refinancing_request_id,
                'api_key': api_key,
            },
        )


@task(queue='retrofix_normal')
def send_r4_promo_blast(**kwargs):
    """
    loan_refinancing_request_id: 123
    dab_lender: 'jtp, jh'
    dpd: 181
    """
    fn_name = 'send_r4_promo_blast'
    logger.info({"action": fn_name, "message": "start"})
    loan_refinancing_request_id = kwargs.get('loan_refinancing_request_id')
    dab_lender = kwargs.get('dab_lender', '')
    lender_list = dab_lender.split(', ')
    dpd = int(kwargs.get('dpd', 0))
    curr_retries_attempt = send_r4_promo_blast.request.retries
    lender_name = ''

    if 'jh' in lender_list and 'jtp' in lender_list:
        lender_name = 'JTPJH'
    elif 'jh' in lender_list:
        lender_name = 'JH'
    elif 'jtp' in lender_list:
        lender_name = 'JTP'

    if dpd >= 181 and dpd <= 270:
        dpd_group = 181
    else:
        dpd_group = 271

    template_code = f'waiver_promo_dpd{dpd_group}_{lender_name}'
    template = template_code

    promo_blast_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAIVER_R4_PROMO_BLAST, is_active=True
    ).last()
    if promo_blast_fs:
        parameters = promo_blast_fs.parameters
        template_raw = parameters.get('templates').get(template_code).get('html')
    else:
        template = f'covid_refinancing/{template_code}.html'

    try:
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            id=loan_refinancing_request_id
        ).last()
        loan_refinancing_email = CovidLoanRefinancingEmail(loan_refinancing_request)
        loan_refinancing_email.send_r4_promo_blast(template, template_code, template_raw)
        logger.info({"action": "send_r4_promo_blast", "message": "finish"})
    except Exception as e:
        if curr_retries_attempt >= send_r4_promo_blast.max_retries:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'Maximum retry for process_data_generation_b5',
                    'error': str(e),
                }
            )
            return
        raise send_r4_promo_blast.retry(
            countdown=600,
            exc=e,
            max_retries=3,
            kwargs={
                'loan_refinancing_request_id': loan_refinancing_request_id,
                'dab_lender': dab_lender,
                'dpd': dpd,
            },
        )


@task(queue='retrofix_normal')
def send_wl_blast_for_b5(**kwargs):
    fn_name = 'send_wl_blast_for_b5'

    customer_id = kwargs.get('customer_id')
    fullname_raw = kwargs.get('fullname_raw')
    due_amount_raw = kwargs.get('due_amount_raw')
    all_skrtp_number = kwargs.get('all_skrtp_number')
    sendgrid_api_key = kwargs.get('sendgrid_api_key')
    client_email_from = kwargs.get('client_email_from')
    index = kwargs.get('index')

    logger.info({"action": fn_name, "message": "start", 'customer_id': customer_id})

    julo_email_client = get_external_email_client(sendgrid_api_key, client_email_from)

    date_today = format_date(timezone.now().date(), 'dd MMMM yyyy', locale='id_ID')

    # html generation
    html_filename = 'manual_warning_letter_b5_dpd121_JTF.html'
    attachment_filename = 'Surat_Kuasa-KALD.pdf'

    # pdf generation
    attachment_path = os.path.join('static/pdf/warning_letter', attachment_filename)
    attachment_content = None

    with open(attachment_path, 'rb') as f:
        data = f.read()
        attachment_content = base64.b64encode(data).decode('utf-8')
        f.close()

    skrtp_number_list = [x for x in str(all_skrtp_number).split(',')]

    try:
        template_code = html_filename.replace('.html', '')

        customer = Customer.objects.get_or_none(id=customer_id)
        if not customer:
            logger.error(
                {'error': 'customer not found', 'customer_id': customer_id, 'index': index}
            )
            return

        account = customer.account

        application = account.application_set.last()

        address = application.full_address or '-'
        fullname = fullname_raw if fullname_raw else customer.fullname
        fullname = re.sub("[^a-zA-Z\\s\\-\\'\\']", ' ', fullname).split(' ')
        fullname = " ".join(list(map(lambda x: x.capitalize(), fullname)))
        due_amount_clean = str(due_amount_raw).replace(',', '')
        due_amount = format_rupiahs(due_amount_clean, 'default-0')

        skrtp_list = []
        skrtp_loans = Loan.objects.filter(loan_xid__in=skrtp_number_list)

        for skrtp_loan in skrtp_loans:
            if not skrtp_loan.sphp_accepted_ts:
                continue
            skrtp_list.append(
                dict(
                    skrtp_no=skrtp_loan.loan_xid,
                    skrtp_sign_date=format_date(
                        timezone.localtime(skrtp_loan.sphp_accepted_ts).date(),
                        'dd MMMM yyyy',
                        locale='id_ID',
                    ),
                )
            )

        payment_detail_list = []
        payments = list(
            AccountPayment.objects.normal()
            .filter(
                status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
                status_id__gte=PaymentStatusCodes.PAYMENT_DUE_TODAY,
                account_id=account.id,
            )
            .order_by('due_date')
        )
        for payment in payments:
            payment_detail_list.append(
                dict(
                    due_date_formatted=convert_date_to_string(payment.due_date, "dd MMM yyyy"),
                    due_amount=format_rupiahs(payment.due_amount, 'default-0'),
                    late_fee_amount=format_rupiahs(payment.remaining_late_fee, 'default-0'),
                    principal_amount=format_rupiahs(payment.remaining_principal, 'default-0'),
                    interest_amount=format_rupiahs(payment.remaining_interest, 'default-0'),
                    dpd=payment.due_late_days,
                )
            )

        subject = 'Surat Peringatan Keterlambatan'

        email_from = EmailDeliveryAddress.COLLECTIONS_JTF
        name_from = "JULO"
        reply_to = EmailDeliveryAddress.COLLECTIONS_JTF
        email_cc = None
        email_to = application.email if application.email else customer.email

        context = {
            'skrtp_list': skrtp_list,
            'fullname': fullname,
            'date_today': date_today,
            'address': address,
            'due_amount': due_amount,
            'payment_detail_list': payment_detail_list,
            'poa_date': '1 Agustus 2024',
        }

        msg = render_to_string(html_filename, context)

        pdf_content = attachment_content

        status, _, headers = julo_email_client.send_email(
            subject,
            msg,
            email_to,
            email_from=email_from,
            email_cc=email_cc,
            name_from=name_from,
            reply_to=reply_to,
            attachment_dict={
                "content": pdf_content,
                "filename": attachment_filename,
                "type": "application/pdf",
            },
            content_type='text/html',
        )
        logger.info(
            {
                'action': 'blast one time warning letter B5 success',
                'template_code': template_code,
                'julo_email_client': julo_email_client,
                'index': index,
            }
        )

        EmailHistory.objects.create(
            to_email=email_to,
            subject=subject,
            sg_message_id=headers['X-Message-Id'],
            template_code=template_code,
            customer=customer,
            message_content=msg,
            status=str(status),
        )
    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        logger.error(
            {
                'function_name': fn_name,
                'customer_id': customer_id,
                'error': str(e),
            }
        )

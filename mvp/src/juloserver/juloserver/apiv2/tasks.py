import logging

from celery import task
from django.db import transaction
from django.utils import timezone
from itertools import islice

from juloserver.apiv3.models import SubDistrictLookup
from juloserver.julo.constants import ProductLineCodes, WorkflowConst
from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    ApplicationFieldChange,
    CreditScore,
    CustomerAppAction,
    Workflow,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import post_anaserver
from juloserver.qaapiv1.services import customer_rescrape_action
from juloserver.account_payment.models import PaymentDetailPageAccessHistory
from juloserver.account.models import Account

from .models import EtlJob, EtlStatus
from .services import generate_address_from_geolocation, get_credit_score3
from juloserver.julo.constants import FeatureNameConst, OnboardingIdConst
from juloserver.julo.models import FeatureSetting, OnboardingEligibilityChecking
from juloserver.julolog.julolog import JuloLog
from juloserver.application_flow.constants import ApplicationDsdMessageConst
from juloserver.application_flow.services import is_agent_assisted_submission_flow
from juloserver.omnichannel.services.construct import construct_customer_odin_score
from juloserver.omnichannel.tasks import send_omnichannel_customer_attributes

logger = logging.getLogger(__name__)
juloLogger = JuloLog(__name__)


@task(queue='application_normal')
def generate_credit_score():
    scheduler_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GENERATE_CREDIT_SCORE
    ).last()
    if scheduler_fs and not scheduler_fs.is_active:
        juloLogger.info({
            'message': 'Generate Credit Score Task setting not active'
        })
        return

    from juloserver.application_flow.services2.credit_score_dsd import (
        process_check_without_dsd_data,
    )
    from juloserver.application_flow.constants import AnaServerFormAPI

    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.TRIGGER_RESCRAPE_AND_FORCE_LOGOUT
    ).last()

    allow_trigger_rescrape = True
    allow_force_logout = True
    if fs is not None:
        if fs.is_active is False:
            allow_trigger_rescrape = False
            allow_force_logout = False
        else:
            parameters = fs.parameters
            if parameters is not None:
                if parameters['rescrape'] is False:
                    allow_trigger_rescrape = False
                if parameters['force_logout'] is False:
                    allow_force_logout = False

    juloLogger.info(
        {
            'message': '[start_execute] Generate Credit Score Task',
            'allow_trigger_rescrape': allow_trigger_rescrape,
            'allow_force_logout': allow_force_logout,
        }
    )

    from juloserver.monitors.notifications import notify_failed_post_anaserver

    current_datetime = timezone.localtime(timezone.now())
    recent_partial_applications = (
        Application.objects.regular_not_deletes()
        .filter(application_status_id=ApplicationStatusCodes.FORM_PARTIAL, creditscore=None)
        .exclude(workflow__name=WorkflowConst.GRAB)
        .exclude(
            product_line_id__in={ProductLineCodes.EFISHERY, ProductLineCodes.EFISHERY_KABAYAN_LITE}
        )
        .order_by('id')
    )

    juloLogger.info(
        {'message': 'Total executed applications', 'target_total': len(recent_partial_applications)}
    )

    for application in recent_partial_applications:
        is_rescrape_action = False

        # skip process if application have this tag
        is_have_tag_agent_assisted = is_agent_assisted_submission_flow(application)
        if is_have_tag_agent_assisted:
            logger.info(
                {
                    'message': 'skip process generate credit score for this application',
                    'is_agent_assisted_submission_flow': is_have_tag_agent_assisted,
                    'application': application.id,
                }
            )
            continue

        # double check if it has got a score now
        scores = CreditScore.objects.filter(application=application)
        if scores.count() > 0:
            logger.info(
                {
                    'message': 'application already get credit score will skip the process',
                    'application_id': application.id,
                }
            )
            continue

        if application.is_web_app() or application.is_partnership_app():
            continue

        # determine double check is need to rescrape action or not
        is_passed_check, is_call_ana_server, flag = process_check_without_dsd_data(
            application_id=application.id
        )

        if flag in ApplicationDsdMessageConst.LIST_OF_FLAG_SKIP_PROCESS:
            logger.info(
                {
                    'message': '[skip_process] skip process for this application',
                    'application_id': application.id,
                    'reason': flag,
                    'is_call_ana_server': is_call_ana_server,
                }
            )
            continue

        customer = application.customer
        etl_status_obj = EtlStatus.objects.filter(application_id=application.id).last()
        if etl_status_obj:
            if etl_status_obj.meta_data == {}:
                is_rescrape_action = True
            else:
                post_ana = True
                if application.onboarding_id == OnboardingIdConst.JULO_360_TURBO_ID:
                    # check the fdc still in progress
                    on_check = OnboardingEligibilityChecking.objects.filter(
                        customer_id=application.customer_id
                    ).last()
                    if on_check and not on_check.fdc_inquiry:
                        post_ana = False

                if post_ana:
                    ana_data = {'application_id': application.id}

                    url = AnaServerFormAPI.SHORT_FORM
                    if application.is_julo_one_ios():
                        url = AnaServerFormAPI.IOS_FORM

                    post_anaserver(url=url, json=ana_data)

                    etl_errors = etl_status_obj.errors
                    if (
                        etl_errors != {}
                        and current_datetime.hour % 2 == 0
                        and current_datetime.minute < 30
                    ):
                        if len(etl_errors) > 2:
                            etl_errors = list(etl_errors.keys())

                        # slack notification
                        notify_data = {
                            'action': "generate_credit_score celery task",
                            'errors': etl_errors,
                            'application_id': application.id,
                        }
                        notify_failed_post_anaserver(notify_data)

        done_dsd_job = EtlJob.objects.filter(
            application_id=application.id, data_type='dsd', status='done'
        ).last()

        if not done_dsd_job:
            is_rescrape_action = True

        if (
            is_rescrape_action
            and flag not in ApplicationDsdMessageConst.LIST_OF_FLAG_DONT_ALLOW_RESCRAPE
        ):
            if allow_trigger_rescrape:
                juloLogger.info(
                    {
                        'message': 'do rescrape',
                        'customer_id': customer.id,
                        'application_id': application.id,
                        'flag': flag,
                    }
                )
                rescrape_status, message = customer_rescrape_action(customer, 'rescrape')
                juloLogger.info(
                    {
                        'message': 'result rescrape',
                        'customer_id': customer.id,
                        'application_id': application.id,
                        'rescrape_status': str(rescrape_status),
                        'rescrape_message': str(message),
                        'flag': flag,
                    }
                )
            if allow_force_logout:
                juloLogger.info(
                    {
                        'message': 'do force logout',
                        'customer_id': customer.id,
                        'application_id': application.id,
                        'flag': flag,
                    }
                )
                force_logout_action = CustomerAppAction.objects.filter(
                    customer=customer, action="force_logout", is_completed=False
                ).last()

                if not force_logout_action:
                    CustomerAppAction.objects.create(
                        customer=customer, action='force_logout', is_completed=False
                    )
                    juloLogger.info(
                        {
                            'message': 'force logout action created',
                            'customer_id': customer.id,
                            'application_id': application.id,
                        }
                    )

        # dsd ETL are done, but no credit score, so generate...
        if done_dsd_job:
            juloLogger.info(
                {
                    'message': 'call get_credit_score3',
                    'customer_id': customer.id,
                    'application_id': application.id,
                    'is_call_ana_server': is_call_ana_server,
                    'flag': flag,
                }
            )
            get_credit_score3(application.id)


@task(name='generate_address_from_geolocation_async')
def generate_address_from_geolocation_async(address_geolocation_id):
    address_geolocation = AddressGeolocation.objects.get_or_none(pk=address_geolocation_id)

    if address_geolocation:
        generate_address_from_geolocation(address_geolocation)

    logger.warn(
        {
            'action': 'generate_address_from_geolocation_async',
            'status': 'address_geolocation %s not found' % (address_geolocation_id),
        }
    )


@task(queue='application_normal')
def check_signal_anomaly_workflow_id_null():
    anomaly_apps = Application.objects.filter(
        application_status__status_code=ApplicationStatusCodes.NOT_YET_CREATED
    )
    if anomaly_apps:
        workflow_init = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
        if workflow_init:
            for app in anomaly_apps:
                with transaction.atomic():
                    if not hasattr(app, 'workflow'):
                        app.workflow = workflow_init
                        app.save()

                    process_application_status_change(
                        app.id,
                        ApplicationStatusCodes.FORM_CREATED,
                        change_reason='customer_triggered',
                    )

                    ApplicationFieldChange.objects.create(
                        application=app,
                        field_name='workflow_id',
                        old_value=None,
                        new_value=workflow_init.id,
                    )

                    logger.info(
                        {
                            'status': 'set workflow_id for signal not triggered anomaly',
                            'application_id': app.id,
                        }
                    )


@task(name='populate_zipcode')
def populate_zipcode(application_id):
    application = (
        application_id
        if not isinstance(application_id, int)
        else Application.objects.get(pk=application_id)
    )
    if application.address_kodepos or not application.address_kelurahan:
        return

    sub_district = SubDistrictLookup.objects.filter(
        sub_district__iexact=application.address_kelurahan,
        district__district__iexact=application.address_kecamatan,
        district__city__city__iexact=application.address_kabupaten,
        district__city__province__province__iexact=application.address_provinsi,
    ).last()

    if sub_district:
        application.update_safely(address_kodepos=sub_district.zipcode)


@task(queue='repayment_high')
def record_payment_detail_page_access_history(account_id, url):
    if not account_id:
        logger.error(
            {
                'action': 'juloserver.apiv2.tasks.record_payment_detail_page_access_history',
                'error': 'account not found',
            }
        )
        return

    if not url:
        logger.error(
            {
                'action': 'juloserver.apiv2.tasks.record_payment_detail_page_access_history',
                'error': 'url not found',
            }
        )
        return

    account = Account.objects.filter(pk=account_id).last()
    pm_detail_history = PaymentDetailPageAccessHistory.objects.filter(account=account).last()
    if pm_detail_history:
        pm_detail_history.update_safely(access_count=pm_detail_history.access_count + 1)
    else:
        PaymentDetailPageAccessHistory.objects.create(account=account, url=url, access_count=1)


@task(bind=True, queue="repayment_high")
def send_customer_odin_score_to_omnichannel(self):
    def log_status(message, batch_num=None):
        log_info = {'action': 'send_odin_score_customer_to_omnichannel', 'message': message}
        if batch_num is not None:
            log_info['batch'] = batch_num
        logger.info(log_info)

    def send_batch(batch, batch_num, retry_count=0, max_retries=5):
        try:
            log_status('sending', batch_num)
            send_omnichannel_customer_attributes(batch, self)
        except Exception as exc:
            if retry_count >= max_retries:
                log_status('failed after {} retries for batch {}'.format(max_retries, batch_num))
                raise
            log_status('retrying batch {}'.format(batch_num))
            countdown = 2**retry_count
            self.retry(
                exc=exc,
                countdown=countdown,
                kwargs={
                    'batch': batch,
                    'batch_num': batch_num,
                    'retry_count': retry_count + 1,
                    'max_retries': max_retries,
                },
            )

    log_status('start')

    batch_size = 100000
    customers = construct_customer_odin_score()
    batch_num = 1

    while True:
        batch = list(islice(customers, batch_size))
        if not batch:
            break

        send_batch(batch, batch_num)
        batch_num += 1

    log_status('finish')

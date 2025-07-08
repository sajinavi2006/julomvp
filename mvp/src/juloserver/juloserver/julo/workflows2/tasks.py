from __future__ import absolute_import

from builtins import range, str


try:
    import services  # noft
except ImportError:
    from juloserver.julo import services

import base64
import datetime
import json
import logging
import os
import tempfile
import time
import traceback
from datetime import date, timedelta

import celery
import google.oauth2.credentials
import semver
import xlwt
from celery import task
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.utils import timezone
from google.auth.transport.requests import AuthorizedSession

from juloserver.ana_api.services import run_sonic_model
from juloserver.apiv1.serializers import ApplicationOriginalSerializer
from juloserver.apiv2.services import get_credit_score3
from juloserver.disbursement.constants import (
    DisbursementVendors,
    NameBankValidationStatus,
)
from juloserver.disbursement.models import Disbursement as Disbursement2
from juloserver.disbursement.models import NameBankValidation
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.disbursement.services.xfers import XfersService
from juloserver.followthemoney.models import LenderBalanceCurrent, LenderCurrent
from juloserver.grab.constants import GrabEmailTemplateCodes, GrabSMSTemplateCodes
from juloserver.income_check.services import check_salary_izi_data
from juloserver.julo.clients import (
    get_julo_apps_flyer,
    get_julo_digisign_client,
    get_julo_email_client,
    get_julo_face_rekognition,
    get_julo_pn_client,
    get_julo_sentry_client,
    get_julo_sms_client,
)
from juloserver.julo.clients.constants import (
    DigisignResponseInfo,
    DigisignResultCode,
    IDCheckStatus,
)
from juloserver.julo.constants import (
    ADVANCE_AI_ID_CHECK_APP_STATUS,
    DigitalSignatureProviderConstant,
    DisbursementStatus,
    FeatureNameConst,
)
from juloserver.julo.exceptions import InvalidBankAccount, SmsNotSent
from juloserver.julo.formulas import count_expired_date_131
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    ApplicationNote,
    AppsFlyerLogs,
    AwsFaceRecogLog,
    Customer,
    Document,
    EmailHistory,
    FaceRecognition,
    FeatureSetting,
    JobType,
    Loan,
    MobileFeatureSetting,
    SignatureMethodHistory,
    SignatureVendorLog,
    WorkflowFailureAction,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.services2 import (
    get_advance_ai_service,
    get_appsflyer_service,
    get_customer_service,
)
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    display_rupiah,
    format_e164_indo_phone_number,
    format_mobile_phone,
    have_pn_device,
)
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.partnership.models import (
    PartnershipApplicationFlag,
    PartnershipFlowFlag,
)
from juloserver.sdk.constants import PARTNER_PEDE

logger = logging.getLogger(__name__)
client = get_julo_sentry_client()


class DuplicateException(Exception):
    pass


class TaskWithRetry(celery.Task):
    max_retries = 2
    default_retry_delay = 10

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Log the exceptions at retry."""
        logger.exception(exc)
        logger.warning('Retry to executing %s ' % str(self.request.task))
        logger.warning('Retry: {}.'.format(self.request))

    def on_success(self, retval, task_id, args, kwargs):
        """Log the exceptions at retry."""
        logger.info('Succeed: {}.'.format(self.request))
        recalled_action_args = self.request.args
        if isinstance(recalled_action_args, dict) and recalled_action_args['failure_action']:
            logger.info('Recalled succeed for %s with failure_action_id %s' % (str(self.request.task),
                                                                                recalled_action_args['id']))
            failure_action = WorkflowFailureAction.objects.get_or_none(pk=recalled_action_args['id'])
            if failure_action:
                failure_action.task_id = self.request.id
                failure_action.recalled_counter += 1
                failure_action.is_recalled_succeed = True
                failure_action.save()

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Log the exceptions on failure."""
        logger.exception(exc)
        logger.error('%s failed to executed' % str(self.request.task))
        logger.error('Failure: {}.'.format(self.request))
        application = Application.objects.get_or_none(pk=int(self.request.args[0]))
        recalled_action_args = self.request.args
        if isinstance(recalled_action_args, dict) and recalled_action_args['failure_action']:

            failure_action = WorkflowFailureAction.objects.get_or_none(pk=recalled_action_args['id'])
            if failure_action:
                failure_action.task_id = self.request.id
                failure_action.error_message = str(exc)
                failure_action.recalled_counter += 1
                failure_action.is_recalled_succeed = False
                failure_action.save()
        else:
            if application:
                WorkflowFailureAction.objects.create(
                    application_id=application.id,
                    task_id=self.request.id,
                    action_name=self.request.task,
                    action_type='async',
                    arguments=self.request.args,
                    error_message=str(exc),
                )
                if str(self.request.task) in (
                    "send_sms_status_change_131_task",
                    "send_sms_status_change_task",
                ):
                    note = 'ERROR sms notifikasi gagal terkirim \n' + str(exc)
                    ApplicationNote.objects.create(note_text=note, application_id=application.id)


@task(name='reminder_push_notif_application_status_105', base=TaskWithRetry, bind=True)
def reminder_push_notif_application_status_105(self, application_id, failure_action=None):
    try:
        application = Application.objects.get_or_none(pk=application_id)
        credit_score_list = ["B-", "B+", "A-"]

        if application:
            status = ApplicationStatusCodes.FORM_PARTIAL
            credit_score = get_credit_score3(application.id)
            user_credit_score = credit_score.score.upper()

            if application.application_status == status and user_credit_score in credit_score_list:
                device = application.device
                application_id = application.id

                logger.info({
                    'action': 'send_reminder_push_notif_application_status_105',
                    'application_id': application_id,
                    'device_id': device.id,
                    'gcm_reg_id': device.gcm_reg_id
                })

                julo_pn_client = get_julo_pn_client()
                julo_pn_client.reminder_app_status_105(device.gcm_reg_id, application_id, user_credit_score)
    except Exception as e:
        raise self.retry(exc=e)


@task(name='appsflyer_update_status_task', base=TaskWithRetry, bind=True)
def appsflyer_update_status_task(self, application_id, event_name, failure_action=None,
                                 status_old=None, status_new=None, extra_params={}, version='v1'):
    try:
        application = Application.objects.get_or_none(pk=application_id)
        if application:
            existed_event = AppsFlyerLogs.objects.filter(
                event_name=event_name, application=application).exists()
            is_application_event = str(event_name)[0] == '1'

            if is_application_event and existed_event:
                logger.error({
                    'event': 'appsflyer_update_status_task',
                    'msg': 'duplicate appsflyer event',
                    'data': {'application_id': application.id, 'event_name': event_name}
                })
                return

            if version == 'v2':
                from juloserver.application_flow.services import get_extra_params_dynamic_events
                extra_params = get_extra_params_dynamic_events(application)

            julo_apps_flyer = get_julo_apps_flyer()
            response = julo_apps_flyer.post_event(application, event_name, extra_params)
            if not status_old and not status_new:
                application_history = application.applicationhistory_set.order_by('id').last()
                if application_history:
                    status_new = application_history.status_new
                    status_old = application_history.status_old
            AppsFlyerLogs.objects.create(
                status_new=status_new, status_old=status_old, application=application,
                appsflyer_device_id=application.customer.appsflyer_device_id,
                appsflyer_log_code=response.status_code,event_name=event_name,
                customer=application.customer,
                appsflyer_customer_id=application.customer.appsflyer_customer_id,
            )
    except Exception as e:
        logger.error(
            {
                'action': 'appsflyer_update_status_task',
                'application_id': application_id,
                'error': str(e),
            }
        )


@task(queue='application_normal')
def do_advance_ai_id_check_task(application_id):
    from juloserver.ana_api.models import SdBankAccount, SdBankStatementDetail
    from juloserver.apiv2.services import check_iti_repeat
    from juloserver.application_flow.constants import JuloOneChangeReason
    from juloserver.application_flow.services import (
        JuloOneService,
        is_experiment_application,
        store_application_to_experiment_table,
    )
    from juloserver.application_flow.services2.autodebit import AutoDebit
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.boost.services import check_scrapped_bank
    from juloserver.income_check.services import is_income_in_range
    from juloserver.julo.product_lines import ProductLineCodes
    from juloserver.julo.services import process_application_status_change
    from juloserver.julo.services2.high_score import (
        do_high_score_full_bypass,
        feature_high_score_full_bypass,
    )
    from juloserver.partnership.leadgenb2b.onboarding.services import (
        is_income_in_range_leadgen_partner,
    )
    from juloserver.partnership.services.services import (
        is_income_in_range_agent_assisted_partner,
    )
    from juloserver.application_flow.services import remove_session_check_hsfbp

    logger.info(
        {
            "message": "do_advance_ai_id_check_task executed",
            "application_id": application_id,
        }
    )
    application = Application.objects.get_or_none(pk=application_id)
    result_index_face = None

    if application:

        advance_ai_service = get_advance_ai_service()
        id_check_status = IDCheckStatus.SUCCESS
        status_next = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        change_reason = 'Passed KTP Check'

        id_check_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ID_CHECK,
            category="experiment",
            is_active=True).last()

        if id_check_feature:
            retries = 0
            max_retries = 10
            while retries < max_retries:
                id_check_status = advance_ai_service.run_id_check(application)
                if id_check_status == IDCheckStatus.RETRY_LATER:
                    logger.info({
                        'task': 'do_advance_ai_id_check_task',
                        'application_id': application.id,
                        'response': id_check_status,
                        'retry_count': retries
                    })
                    time.sleep(1)
                else:
                    break
                retries += 1

        if id_check_status in (IDCheckStatus.PERSON_NOT_FOUND, IDCheckStatus.INVALID_ID_NUMBER):
            logger.info(
                {
                    "message": "do_advance_ai_id_check_task: id_check_status not success",
                    "application_id": application_id,
                }
            )
            # change status to x125
            status_next = ApplicationStatusCodes.CALL_ASSESSMENT
            change_reason = 'KTP Invalid' if id_check_status == IDCheckStatus.PERSON_NOT_FOUND else 'Invalid ID Number ID Check Run'

        # Check old status code still fulfill advance ai requirement status
        app = Application.objects.get_or_none(pk=application_id)
        old_status_code = app.status
        if old_status_code != ADVANCE_AI_ID_CHECK_APP_STATUS:
            logger.info(
                {
                    "message": "do_advance_ai_id_check_task: wrong advance ai id status",
                    "application_id": application_id,
                }
            )
            remove_session_check_hsfbp(application_id)
            return False

        if app.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            logger.info(
                {
                    "message": "do_advance_ai_id_check_task: in document submitted status",
                    "application_id": application_id,
                }
            )
            face_recognition = FaceRecognition.objects.get_or_none(
                feature_name='face_recognition',
                is_active=True
            )
            if face_recognition and app.product_line_code in ProductLineCodes.new_lended_by_jtp():
                logger.info(
                    {
                        "message": "do_advance_ai_id_check_task: face recognition check",
                        "application_id": application_id,
                    }
                )
                rekognition = get_julo_face_rekognition()
                result_index_face = rekognition.run_index_face(application_id, repeat_face_recog=False)
                if result_index_face and \
                        not result_index_face['passed'] and \
                        id_check_status == IDCheckStatus.SUCCESS:
                    change_reason = result_index_face['change_reason']
                    status_next = result_index_face['new_status_code']

                if result_index_face and result_index_face['passed'] and id_check_status == IDCheckStatus.SUCCESS:
                    change_reason = 'Passed KTP Check and Face Check'
                elif result_index_face and result_index_face['passed'] and id_check_status != IDCheckStatus.SUCCESS:
                    change_reason = 'Invalid KTP and Passed Face Check'

        if id_check_status == IDCheckStatus.SUCCESS:
            if not face_recognition or \
                    (face_recognition and result_index_face and result_index_face['passed']) or \
                    (face_recognition and result_index_face is None):
                from juloserver.julo.services2.high_score import eligible_hsfbp_goldfish

                logger.info(
                    {
                        "message": "do_advance_ai_id_check_task: no face recognition",
                        "application_id": application_id,
                    }
                )

                store_application_to_experiment_table(application, 'ExperimentCreditMatrix')
                eligible_hsfbp = feature_high_score_full_bypass(application)
                has_pending_autodebit = AutoDebit(application).has_pending_tag
                if (
                    eligible_hsfbp or eligible_hsfbp_goldfish(application)
                ) and not has_pending_autodebit:
                    logger.info(
                        {
                            "message": "do_advance_ai_id_check_task: trigger hsfbp",
                            "application_id": application_id,
                        }
                    )
                    do_high_score_full_bypass(application)
                    application_tag_tracking_task.delay(
                        application_id, None, None, None, 'is_hsfbp', 1
                    )
                    return

                elif is_experiment_application(application.id, 'ExperimentUwOverhaul'):
                    if application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                        remove_session_check_hsfbp(application_id)
                        if check_iti_repeat(application.id) and not AutoDebit(application).has_pending_tag:
                            application_tag_tracking_task.delay(
                                application.id,
                                None,
                                None,
                                None,
                                'is_sonic',
                                1,
                                traceback.format_stack()
                            )

                            run_sonic_model(application)
                            return

                        else:
                            salary_izi_data = check_salary_izi_data(application)
                            is_salaried = JobType.objects.get_or_none(job_type=application.job_type).is_salaried

                            if salary_izi_data and is_salaried:
                                sonic_tag_status = None
                                # checking the income range, by default using j1 else check leadgen
                                if (
                                    is_income_in_range(application)
                                    or is_income_in_range_leadgen_partner(application)
                                    or is_income_in_range_agent_assisted_partner(application)
                                ):
                                    if not AutoDebit(application).has_pending_tag:
                                        sonic_tag_status = 1
                                        run_sonic_model(application)
                                else:
                                    sonic_tag_status = 0

                                    application_tag_tracking_task.delay(
                                        application.id,
                                        None,
                                        None,
                                        None,
                                        'is_mandatory_docs',
                                        1,
                                        traceback.format_stack()

                                    )

                                if sonic_tag_status is not None:
                                    application_tag_tracking_task.delay(
                                        application.id,
                                        None,
                                        None,
                                        None,
                                        'is_sonic',
                                        sonic_tag_status
                                    )
                                return

                            else:
                                is_scrapped_bank = check_scrapped_bank(application)
                                is_data_check_passed = False
                                if is_scrapped_bank:
                                    sd_bank_account = SdBankAccount.objects.filter(application_id=application.id).last()
                                    if sd_bank_account:
                                        sd_bank_statement_detail = SdBankStatementDetail.objects.filter(
                                            sd_bank_account=sd_bank_account).last()
                                        if sd_bank_statement_detail:
                                            is_data_check_passed = True

                                if not is_data_check_passed:
                                    from juloserver.bpjs.services import Bpjs
                                    is_data_check_passed = Bpjs(application=application).is_scraped

                                if is_data_check_passed:
                                    change_reason = JuloOneChangeReason.MEDIUM_SCORE_BY_PASS

                                    if JuloOneService.is_high_c_score(application):
                                        change_reason = JuloOneChangeReason.HIGH_C_SCORE_BY_PASS

                                    new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                                    process_application_status_change(
                                        application.id, new_status_code, change_reason)
                                else:
                                    application_tag_tracking_task.delay(
                                        application.id,
                                        None,
                                        None,
                                        None,
                                        'is_mandatory_docs',
                                        1,
                                        traceback.format_stack()

                                    )
                                return

        if id_check_status != IDCheckStatus.RETRY_LATER:
            remove_session_check_hsfbp(application_id)
            process_application_status_change(application.id, status_next, change_reason=change_reason)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def update_status_apps_flyer_task(self, application_id, status, advance_ai_id_check=False,
                                  status_old=None, status_new=None):
    from juloserver.julo.product_lines import ProductLineCodes
    from juloserver.julo.services import process_application_status_change
    from juloserver.google_analytics.tasks import send_event_to_ga_task_async
    from juloserver.google_analytics.constants import GAEvent

    logger.info(
        {
            "message": "update_status_apps_flyer_task executed",
            "application_id": application_id,
            "advance_ai_id_check": advance_ai_id_check,
        }
    )
    application = Application.objects.get_or_none(pk=application_id)
    if application:
        try:
            appsflyer_service = get_appsflyer_service()
            appsflyer_service.info_application_status(
                application_id, status, status_old, status_new)

            # status 120 advance_ai_id_check code block
            if advance_ai_id_check and application.application_status_id == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:

                customer_service = get_customer_service()
                skip_pv_dv = customer_service.is_application_skip_pv_dv(application_id)
                appsflyer_update_status_task.delay(
                    application.id,
                    appsflyer_service.get_event_name(application, status),
                    status_old=status_old,
                    status_new=status_new,
                    version='v2'
                )
                send_event_to_ga_task_async(
                    customer_id=application.customer.id,
                    event=GAEvent.X120,
                    version='v2',
                )
                if skip_pv_dv:
                    logger.info(
                        {
                            "message": "update_status_apps_flyer_task skip PV DV",
                            "application_id": application_id,
                        }
                    )
                    face_recognition = FaceRecognition.objects.get_or_none(
                        feature_name='face_recognition',
                        is_active=True
                    )
                    if face_recognition and application.product_line_code in ProductLineCodes.lended_by_jtp():
                        rekognition = get_julo_face_rekognition()
                        result_index_face = rekognition.run_index_face(application_id, repeat_face_recog=False)
                        if result_index_face and not result_index_face['passed']:
                            change_reason = result_index_face['change_reason']
                            new_status_code = result_index_face['new_status_code']

                    if not face_recognition or \
                            (face_recognition and result_index_face and result_index_face['passed']) or \
                            (face_recognition and result_index_face is None):
                        result_bypass = customer_service.do_high_score_full_bypass_or_iti_bypass(application_id)
                        if result_bypass:
                            new_status_code = result_bypass['new_status_code']
                            change_reason = result_bypass['change_reason']
                    if application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                        process_application_status_change(
                            application_id, new_status_code, change_reason=change_reason)
                else:
                    logger.info(
                        {
                            "message": "update_status_apps_flyer_task with PV DV. do_advance_ai_id_check_task triggered",
                            "application_id": application_id,
                        }
                    )
                    do_advance_ai_id_check_task.delay(application_id)

        except Exception as e:
            raise self.retry(exc=e)
    else:
        logger.info({
            'task': 'update_status_apps_flyer_task',
            'status': 'application not found / application status is not 120',
            'application_id': application_id,
            'advance_ai_id_check': advance_ai_id_check
        })


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def send_email_status_change_task(self, application_id, new_status_code, change_reason,
                                    failure_action=None, to_partner=False, email_setting=None):
    try:
        application = Application.objects.get_or_none(pk=application_id)
        email_method = 'email_notification_' + str(new_status_code)
        email_cls = get_julo_email_client()
        email_client = getattr(email_cls, email_method)
        to_email = application.email
        if not to_email:
            to_email = application.customer.email
            application.email = application.customer.email

        if application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            status, headers, subject, msg = email_client(application, change_reason, to_partner, email_setting)
        else:
            status, headers, subject, msg = email_client(application, change_reason)

        if status is None:
            return

        customer = application.customer
        message_id = headers['X-Message-Id']

        template_code = 'email_notif_' + str(new_status_code)
        if to_partner == True:
            template_code = 'email_notif_' + str(new_status_code) + '_partner'
        elif email_setting and email_setting.get('attach_sphp_customer') == True:
            template_code = 'email_notif_' + str(new_status_code) + '_pdf'

        EmailHistory.objects.create(
            application=application,
            customer=customer,
            sg_message_id=message_id,
            to_email=to_email,
            subject=subject,
            message_content=msg,
            template_code=template_code
        )
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def process_documents_verified_action_task(self, application_id, failure_action=None):
    try:
        application = Application.objects.get_or_none(pk=application_id)
        if have_pn_device(application.device):
            julo_pn_client = get_julo_pn_client()
            julo_pn_client.inform_docs_verified(application.device.gcm_reg_id, application.id)
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def send_sms_status_change_131_task(self, application_id, failure_action=None):
    application = Application.objects.get_or_none(pk=application_id)
    sms_client_method_name = 'sms_resubmission_request_reminder'
    julo_sms_client = get_julo_sms_client()
    sms_client_method = getattr(julo_sms_client, sms_client_method_name)
    expired_day = count_expired_date_131(timezone.localtime(timezone.now()).date())

    try:
        txt_msg, response, template = sms_client_method(application, expired_day)

        if response['status'] != '0':
            client.captureException()
            logger.error({
                'send_status': response['status'],
                'application_id': application.id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': sms_client_method_name,
                'error_text': response.get('error-text'),
            })
            raise SmsNotSent(response.get('error-text'))
        else:
            customer = application.customer
            sms = create_sms_history(response=response,
                       customer=customer,
                       application=application,
                       template_code=template,
                       message_content=txt_msg,
                       phone_number_type='mobile_phone_1',
                       to_mobile_phone=format_e164_indo_phone_number(response['to']))

            logger.info({
                'status': 'sms_created',
                'application_id': application.id,
                'sms_history_id': sms.id,
                'message_id': sms.message_id
            })

    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def send_sms_status_change_task(self, application_id, change_reason, failure_action=None):
    application = Application.objects.get_or_none(pk=application_id)
    sms_client_method_name = 'sms_legal_document_resubmission'

    julo_sms_client = get_julo_sms_client()
    sms_client_method = getattr(julo_sms_client, sms_client_method_name)

    try:
        txt_msg, response, template = sms_client_method(application, change_reason)

        if response['status'] != '0':
            client.captureException()
            logger.error({
                'send_status': response['status'],
                'application_id': application.id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': sms_client_method_name,
                'error_text': response.get('error-text'),
            })
            raise SmsNotSent(response.get('error-text'))
        else:
            customer = application.customer
            sms = create_sms_history(response=response,
                                     customer=customer,
                                     application=application,
                                     template_code=template,
                                     message_content=txt_msg,
                                     phone_number_type='mobile_phone_1',
                                     to_mobile_phone=format_e164_indo_phone_number(response['to']))

            logger.info({
                'status': 'sms_created',
                'application_id': application.id,
                'sms_history_id': sms.id,
                'message_id': sms.message_id
            })

    except Exception as e:
        raise self.retry(exc=e)


@task(name='send_sms_status_change_172pede_task', base=TaskWithRetry, bind=True)
def send_sms_status_change_172pede_task(self, application_id):
    application = Application.objects.get_or_none(pk=application_id)
    sms_client_method_name = 'sms_reminder_172'

    julo_sms_client = get_julo_sms_client()
    sms_client_method = getattr(julo_sms_client, sms_client_method_name)

    try:
        txt_msg, response, template = sms_client_method(application.mobile_phone_1)

        if response['status'] != '0':
            client.captureException()
            logger.error({
                'send_status': response['status'],
                'application_id': application.id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': sms_client_method_name,
                'error_text': response.get('error-text'),
            })
            raise SmsNotSent(response.get('error-text'))
        else:
            customer = application.customer
            sms = create_sms_history(response=response,
                                     customer=customer,
                                     application=application,
                                     template_code=template,
                                     message_content=txt_msg,
                                     phone_number_type='mobile_phone_1',
                                     to_mobile_phone=format_e164_indo_phone_number(response['to']))

            logger.info({
                'status': 'sms_created',
                'application_id': application.id,
                'sms_history_id': sms.id,
                'message_id': sms.message_id
            })

    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def create_application_original_task(self, application_id, failure_action=None):
    try:
        application = Application.objects.get_or_none(id=application_id)
        if application.applicationoriginal_set.all().count() > 0:
            return

        # Although not in views, using DRF Serializer is the easiest way
        # to "copy" the fields in this specific case
        application_data = model_to_dict(application)
        application_original_serializer = ApplicationOriginalSerializer(data=application_data)
        application_original_serializer.is_valid(raise_exception=True)
        application_original_serializer.save(current_application=application)

    except Exception as e:
        raise self.retry(exc=e)


@task(name='reminder_sms_grab_notification', base=TaskWithRetry, bind=True)
def reminder_sms_grab_notification(self, application_id):
    julo_sms_client = get_julo_sms_client()
    application = Application.objects.get_or_none(pk=application_id)
    if application.application_status == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
        if application.mobile_phone_1:
            try:
                message1, response1 = julo_sms_client.sms_grab_notification(application.mobile_phone_1, True)
            except SmsNotSent as e:
                note = 'ERROR sms notifikasi gagal terkirim \n' + str(e)
                application_note = ApplicationNote.objects.create(
                    note_text=note, application_id=application.id
                )
        if application.mobile_phone_2:
            try:
                message2, response2 = julo_sms_client.sms_grab_notification(application.mobile_phone_2, True)
            except SmsNotSent as e:
                note = 'ERROR sms notifikasi gagal terkirim \n' + str(e)
                application_note = ApplicationNote.objects.create(
                    note_text=note, application_id=application.id
                )


@task(name='set_google_calender_task', base=TaskWithRetry, bind=True)
def set_google_calender_task(self, application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if application:
        customer = application.customer
        if customer.google_refresh_token:
            try:
                with open(settings.GOOGLE_CLIENT_SECRET) as f:
                    google_cred = json.load(f)
                credentials = google.oauth2.credentials.Credentials(
                    customer.google_access_token,
                    refresh_token=customer.google_refresh_token,
                    token_uri=google_cred['web']['token_uri'],
                    client_id=google_cred['web']['client_id'],
                    client_secret=google_cred['web']['client_secret'])
                authed_session = AuthorizedSession(credentials)
            except Exception as e:
                raise self.retry(exc=e)

            payments = application.loan.payment_set.all()
            payment_methods = application.loan.paymentmethod_set.all()
            payment_method_list = ""
            for payment_method in payment_methods:
                payment_method_list += "%s a/n JULO dengan nomor Virtual Account %s\n" % (
                    payment_method.payment_method_name,
                    payment_method.virtual_account
                )

            for payment in payments:
                description = ("%s angsuran ke %s Anda di JULO jatuh tempo pada hari %s sejumlah %s Anda dapat melakukan"
                               "pembayaran ke :\n\n%s\nLakukan pembayaran tepat waktu dan kumpulkan Cashback yang dapat"
                               "dicairkan setelah pinjaman di JULO selesai. Terima kasih.") % (
                    application.fullname_with_title,
                    str(payment.payment_number),
                    date.strftime(payment.notification_due_date, '%d-%b-%Y'),
                    display_rupiah(payment.due_amount),
                    payment_method_list
                )

                data = {
                    'summary': 'Pembayaran Pinjaman ke-'+ str(payment.payment_number) +' di JULO',
                    'location': 'Jakarta',
                    'description': description,
                    'start': {
                        'dateTime': date.strftime(payment.notification_due_date, '%Y-%m-%d') + 'T10:00:00+07:00',
                        'timeZone': 'Asia/Jakarta',
                    },
                    'end': {
                        'dateTime': date.strftime(payment.notification_due_date, '%Y-%m-%d') + 'T13:00:00+07:00',
                        'timeZone': 'Asia/Jakarta',
                    },
                    'attendees': [
                        {'email': application.email}
                    ],
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'email', 'minutes': 30},
                            {'method': 'popup', 'minutes': 10},
                        ],
                    },
                }
                response = authed_session.post(
                    'https://www.googleapis.com/calendar/v3/calendars/primary/events', json=data)

                logger.info({
                    'action': 'set calendar event for payment reminder',
                    'application_id': application_id,
                    'response_status':response.status_code,
                    'message': response.json(),
                })


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def sending_reconfirmation_email_175_task(self, application_id):
    try:
        app = Application.objects.get(pk=application_id)
        last_175_app_history = app.applicationhistory_set.filter(status_new=175).last()
        if last_175_app_history:
            last_change_reason = last_175_app_history.change_reason
            template = "email_reconfirmation175_%s"
            if "Name validation failed" in last_change_reason:
                template = template % "invalid_name"
            elif "RECIPIENT_NOT_FOUND_ERROR" in last_change_reason:
                template = template % "recipient_not_found"
            else:
                return
        else:
            return
        last_164_app_history = app.applicationhistory_set.filter(status_new=164).last()
        if last_164_app_history:
            disbursement_date = timezone.localtime(last_164_app_history.udate).date()
            email = app.email
            fullname = app.fullname_with_title
            bank_name = app.bank_name
            account_number = app.bank_account_number
            holder_name = app.name_in_bank

            email_cls = get_julo_email_client()
            status, headers, subject, msg = email_cls.email_reconfirmation_175(
                email, fullname, disbursement_date, bank_name, account_number, holder_name, template)
            customer = app.customer
            message_id = headers['X-Message-Id']
            EmailHistory.objects.create(
                application=app,
                customer=customer,
                sg_message_id=message_id,
                to_email=email,
                subject=subject,
                message_content=msg,
                template_code=template
            )
            logger.info({
                'action': 'sending_reconfirmation_email_175_task',
                'application_id': application_id,
                'message_id': headers['X-Message-Id'],
            })
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def signature_method_history_task(self, application_id, signature_method):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return None

    old_signature = SignatureMethodHistory.objects.filter(application=application)
    if old_signature:
        old_signature.update(is_used=False, partner_id=application.loan.partner)

    #create new signature history
    same_signature = SignatureMethodHistory.objects.filter(
        application=application,
        signature_method=signature_method).last()
    if same_signature:
        same_signature.is_used = True
        same_signature.partner_id = application.loan.partner
        same_signature.save()
    else:
        SignatureMethodHistory.objects.create(
            application=application,
            partner_id=application.loan.partner,
            signature_method=signature_method
        )


@task(name='signature_method_history_task_julo_one', base=TaskWithRetry, bind=True)
def signature_method_history_task_julo_one(self, loan_id, signature_method):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return None

    old_signature = SignatureMethodHistory.objects.filter(loan=loan)
    if old_signature:
        old_signature.update(is_used=False)

    #create new signature history
    same_signature = SignatureMethodHistory.objects.filter(
        loan=loan,
        signature_method=signature_method).last()
    if same_signature:
        same_signature.is_used = True
        same_signature.save()
    else:
        SignatureMethodHistory.objects.create(
            loan=loan,
            signature_method=signature_method
        )


@task(name='upload_sphp_from_digisign_task', base=TaskWithRetry, bind=True)
def upload_sphp_from_digisign_task(self, application_id):
    from ..services import process_application_status_change
    try:
        digisign_client = get_julo_digisign_client()
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return None

        # Check existing document was exist or not
        existing_sphp = Document.objects.get_or_none(document_source=application_id, document_type="sphp_digisign")
        if existing_sphp:
            document_id = existing_sphp.id
            filename = existing_sphp.filename
        else:
            now = datetime.datetime.now()
            filename = '{}_{}_{}_{}.pdf'.format(
                application.fullname,
                application.application_xid,
                now.strftime("%Y%m%d"),
                now.strftime("%H%M%S"))
            sphp = Document(document_source=application_id, document_type="sphp_digisign", filename=filename)
            sphp.save()
            document_id = sphp.id

        # Send document process to digisign
        send_document_response = digisign_client.send_document(document_id, application_id, filename)
        send_document_response_json = send_document_response['JSONFile']
        if send_document_response_json['result'] != DigisignResultCode.SUCCESS:
            # Failed response
            if send_document_response_json['result'] in DigisignResultCode.fail_to_145():
                mobile_featuring = MobileFeatureSetting.objects.filter(
                    feature_name='digital_signature_failover',is_active=True
                    ).last()
                if not mobile_featuring and application.status not in [
                    ApplicationStatusCodes.DIGISIGN_FAILED,
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                ]:
                    note = send_document_response_json['notif']
                    process_application_status_change(
                        application_id,ApplicationStatusCodes.DIGISIGN_FAILED,
                        change_reason='digisign send document failed',
                        note=note)

    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def send_registration_and_document_digisign_task(self, application_id):
    from ..services import process_application_status_change
    try:
        digisign_client = get_julo_digisign_client()
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return None
        application_history_147 = ApplicationHistory.objects.filter(
            application=application,
            status_new=ApplicationStatusCodes.DIGISIGN_FACE_FAILED).first()

        # generate history signature
        if not application_history_147:
            signature_method_history_task(application_id, 'Digisign')

        # Registration process to digisign
        user_status_response = digisign_client.user_status(application.email)
        user_status_response_json = user_status_response['JSONFile']
        aws_data = AwsFaceRecogLog.objects.filter(customer=application.customer, application=application,
                                                  is_indexed=True,
                                                  is_quality_check_passed=True).last()
        digital_signature_face_result = None
        if aws_data:
            digital_signature_face_result = aws_data.digital_signature_face_result
            digital_signature_face_result.update_safely(is_used_for_registration=False,
                                                        digital_signature_provider=DigitalSignatureProviderConstant.DIGISIGN)
        if user_status_response_json['result'] == DigisignResultCode.DATA_NOT_FOUND:
            register_response = digisign_client.register(application_id)
            register_response_json = register_response['JSONFile']
            if digital_signature_face_result:
                digital_signature_face_result.update_safely(
                    is_used_for_registration=True)

            if register_response_json['result'] == DigisignResultCode.SUCCESS:
                # Success response
                customer = Customer.objects.get_or_none(pk=application.customer_id)
                customer.is_digisign_registered = True
                customer.save()
                if digital_signature_face_result:
                    digital_signature_face_result.update_safely(is_passed=True)

            else:
                # Failed response
                note = register_response_json['notif']
                if 'info' in register_response_json:
                    note += ' info:{}'.format(register_response_json['info'])
                if 'data' in register_response_json:
                    note += ' data:{}'.format(register_response_json['data'])

                failover_digisign_inactive = MobileFeatureSetting.objects.get_or_none(
                    feature_name='digital_signature_failover',
                    is_active=False,
                )

                if failover_digisign_inactive:
                    if application_history_147:
                        change_reason = 'face_resubmission_for_digisign_registration'
                        application_status_code = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
                        signature_method_history_task.delay(application.id, 'JULO')
                        if digital_signature_face_result and \
                            register_response_json['result'] in DigisignResultCode.fail_to_147() and \
                            'info' in register_response_json and \
                            register_response_json['info'] not in DigisignResponseInfo.exclude_info():
                            digital_signature_face_result.update_safely(is_passed=False)
                    elif register_response_json['result'] in DigisignResultCode.fail_to_147() and \
                            'info' in register_response_json and \
                            register_response_json['info'] not in DigisignResponseInfo.exclude_info():
                        julo_pn_client = get_julo_pn_client()
                        change_reason = 'Digisign_face_registration_fail'
                        application_status_code = ApplicationStatusCodes.DIGISIGN_FACE_FAILED
                        message_pn = 'Kami membutuhkan selfie Anda untuk melanjutkan tanda tangan digital, Yuk upload dengan klik disini'
                        julo_pn_client.pn_face_recognition(application.device.gcm_reg_id, message_pn)
                        if digital_signature_face_result:
                            digital_signature_face_result.update_safely(is_passed=False)
                    elif register_response_json['result'] in DigisignResultCode.fail_to_145():
                        if application.status not in [
                            ApplicationStatusCodes.DIGISIGN_FAILED,
                            ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
                            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                        ]:
                            change_reason = 'digisign registration failed'
                            application_status_code = ApplicationStatusCodes.DIGISIGN_FAILED

                    process_application_status_change(
                        application_id,
                        application_status_code,
                        change_reason=change_reason,
                        note=note)
                if register_response_json['result'] in DigisignResultCode.fail_to_145():
                    mobile_featuring = MobileFeatureSetting.objects.filter(
                        feature_name='digital_signature_failover',is_active=True
                        ).last()
                    if not mobile_featuring and application.status not in [
                        ApplicationStatusCodes.DIGISIGN_FAILED,
                        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                    ]:
                        process_application_status_change(
                            application_id,
                            ApplicationStatusCodes.DIGISIGN_FAILED,
                            change_reason='digisign registration failed',
                            note=note)

                logger.info({
                    'action': 'digisign_failed_register',
                    'note': note,
                    'result_code': register_response_json['result'],
                })

                return None

        # Fix major discrepancy between E-KYC Digisign API and Digisign Document API
        # upload document digisign
        upload_sphp_from_digisign_task(application_id)

    except Exception as e:
        raise self.retry(exc=e)

@task(queue='application_normal', base=TaskWithRetry, bind=True)
def process_after_digisign_failed(self, application_id):
    from juloserver.julo.services import process_application_status_change
    try:
        application = Application.objects.get(id=application_id)
        if application.is_julo_one() and \
                application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
            return
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
            change_reason='digisign registration failed',
            note='change status to 171 after 1 day')

    except Exception as e:
        raise self.retry(exc=e)

@task(queue='application_normal', base=TaskWithRetry, bind=True)
def download_sphp_from_digisign_task(self, application_id):
    from ..tasks import upload_document
    try:
        digisign_client = get_julo_digisign_client()
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return None

        document = Document.objects.get_or_none(document_source=application_id, document_type="sphp_digisign")
        if not document:
            return None

        # Get sphp with signed from digisign
        file_base64_response = digisign_client.get_download_file_base64(document.id)
        file_base64_response_json = file_base64_response['JSONFile']
        if file_base64_response_json['result'] != DigisignResultCode.SUCCESS:
            return None

        base64String = file_base64_response_json['file']
        with open(document.filename, 'wb') as file:
            file.write(base64.b64decode(base64String))

        upload_document.delay(document.id, document.filename)
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def create_lender_sphp_task(self, application_id):
    from juloserver.followthemoney.tasks import generate_lender_loan_agreement

    from ..services import get_lender_sphp
    from ..tasks import upload_document

    try:
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return

        loan = Loan.objects.get_or_none(application=application)
        if not loan:
            return

        generate_lender_loan_agreement.delay(application.id)
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def create_sphp_task(self, application_id):
    from juloserver.followthemoney.tasks import generate_sphp

    try:
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return

        loan = Loan.objects.get_or_none(application=application)
        if not loan:
            return

        generate_sphp.delay(application.id)
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal')
def lender_auto_approval_task(application_id, gaps):
    from juloserver.followthemoney.tasks import (
        approved_application_process_disbursement,
    )

    from ..services import process_application_status_change

    application = Application.objects.get_or_none(pk=application_id)

    if application and application.status == ApplicationStatusCodes.LENDER_APPROVAL:
        loan = application.loan

        approved_application_process_disbursement.delay(application_id, loan.partner.id)


@task(queue='application_normal')
def lender_auto_expired_task(application_id, lender_id):
    from juloserver.followthemoney.tasks import auto_expired_application_tasks
    auto_expired_application_tasks.delay(application_id, lender_id)


@task(queue='application_normal')
def send_back_to_170_for_disbursement_auto_retry_task(application_id, max_retries):
    from juloserver.disbursement.services.xfers import XfersConst

    from ..services import process_application_status_change

    application = Application.objects.get(pk=application_id)

    loan = application.loan
    disbursement = Disbursement2.objects.get_or_none(
        pk=loan.disbursement_id, method=DisbursementVendors.XFERS,
        disburse_status=XfersConst().MAP_STATUS[XfersConst().STATUS_FAILED])
    if not disbursement:
        logger.info({'task': 'send_back_to_170_for_disbursement_auto_retry_task',
                     'application_id': application_id,
                     'status': 'disbursement method is not xfers or status not failed'})
        return

    is_retrying, response = XfersService().check_disburse_status(disbursement)

    if is_retrying:
        with transaction.atomic():
            if disbursement.retry_times >=max_retries:
                new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_ONGOING
                change_reason = XfersConst().RETRY_EXCEEDED_CHANGE_REASON
                note = 'Disbursement via Xfers retry attempt is exceeded please disburse manually'

                logger.info({'task': 'send_back_to_170_for_disbursement_auto_retry_task',
                             'application_id': application_id,
                             'status': 'max_retries exceeded sent it to status 177',
                             'response': response})
            else:
                disbursement.retry_times += 1
                disbursement.save(update_fields=['retry_times', 'udate'])
                new_status_code = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
                change_reason = XfersConst().RETRY_CHANGE_REASON
                note = 'Disbursement via Xfers retry attempt %s' % str(disbursement.retry_times)

                logger.info({'task': 'send_back_to_170_for_disbursement_auto_retry_task',
                             'application_id': application_id,
                             'status': 'retrying disburse sent it back to status 170',
                             'response': response})
    else:
        if response['status'] == XfersConst().STATUS_COMPLETED:
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                application.email, disbursement.name_bank_validation.bank_code,
                disbursement.name_bank_validation.account_number,
                disbursement.name_bank_validation.method)

            logger.info({'task': 'send_back_to_170_for_disbursement_auto_retry_task',
                         'application_id': application_id,
                         'status': 'disbursement completed based on check_disburse_status',
                         'response': response})

    process_application_status_change(application.id, new_status_code, change_reason, note)


@task(name='pending_disbursement_notification_task', base=TaskWithRetry, bind=True)
def pending_disbursement_notification_task(self):
    try:
        now = timezone.now()
        time_difference_170 = now - timedelta(hours=3)
        time_difference_181 = now - timedelta(minutes=5)

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PENDING_DISBURSEMENT_NOTIFICATION_MEMBER,
            category="disbursement",
            is_active=True).first()

        if not feature_setting:
            return

        parameters = feature_setting.parameters

        users = ",".join(parameters['users'])
        application_histories = list(set(ApplicationHistory.objects.values_list('application_id', flat=True) \
            .filter((Q(status_new=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED) & Q(cdate__lt=time_difference_170))
                | (Q(status_new=ApplicationStatusCodes.FUND_DISBURSAL_FAILED) & Q(cdate__lt=time_difference_181)))
        ))

        if application_histories:
            # create XLS file
            file_name = "Pending_Disbursement_Notification-%s.xls" % (
                timezone.localtime(now).strftime("%d%m%Y%-H%M"))
            file_path = os.path.join(tempfile.gettempdir(), file_name)

            wb = xlwt.Workbook(encoding='utf-8')
            ws = wb.add_sheet("List Application", cell_overwrite_ok=True)
            row_num = 0
            font_style = xlwt.XFStyle()
            font_style.font.bold = True

            columns = ('No',
                'Application ID',
                'Bucket',
                'Bank Name',
                'Disbursement Method',
                'Disbursement ID',
                'Disbursement Status',
                'Reason',
                'Time')

            column_size = list(range(len(columns)))
            for col_num in column_size:
                ws.write(row_num, col_num, columns[col_num], font_style)

            application_170_181 = [
                ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            ]
            for application_history in application_histories:
                application = Application.objects.get_or_none(pk=application_history,
                                                              application_status__in=application_170_181)
                if application:
                    loan = Loan.objects.get_or_none(application=application)
                    if loan:
                        disbursement = Disbursement2.objects.get_or_none(pk=loan.disbursement_id)
                        if disbursement:
                            condition_170 = (application.application_status.status_code == ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED and
                                (disbursement.disburse_status == DisbursementStatus.INITIATED or
                                disbursement.disburse_status == DisbursementStatus.PENDING))
                            condition_181 = (application.application_status.status_code == ApplicationStatusCodes.FUND_DISBURSAL_FAILED and
                                disbursement.disburse_status == DisbursementStatus.FAILED)

                            if condition_170 or condition_181:
                                row_num = row_num + 1
                                data = (row_num,
                                    application.id,
                                    application.status,
                                    application.bank_name,
                                    disbursement.method,
                                    disbursement.disburse_id,
                                    disbursement.disburse_status,
                                    disbursement.reason,
                                    str(timezone.localtime(disbursement.cdate)))

                                # Sheet body, remaining rows
                                font_style = xlwt.XFStyle()

                                data_size = list(range(len(data)))
                                for data_slice in data_size:
                                    ws.write(row_num, data_slice, data[data_slice], font_style)

            wb.save(file_path)

            if row_num > 0:
                initial_comment = "These applications disbursement process are interrupted and have been in 170/181 longer than it should be. Please do immediate check and take any action needed to prevent more delay!\n\n\nBest Regards,\nJULO Product Team"
                xls = open(file_path, 'rb')
                get_slack_bot_client().api_call('files.upload',
                    channels=users,
                    filename=file_name,
                    file=xls,
                    initial_comment=initial_comment,
                    headers="application/x-www-form-urlencoded")
                xls.close()

            feature_setting.parameters = {
                'last_application_170_processed_date': str(time_difference_170),
                'users': parameters['users'],
                'last_application_181_processed_date': str(time_difference_181)}
            feature_setting.save()

    except Exception as e:
        raise self.retry(exc=e)


@task(name='send_warning_message_balance_amount')
def send_warning_message_balance_amount(lender_name=PartnerConstant.JTP_PARTNER):
    from juloserver.followthemoney.tasks import calculate_available_balance
    from juloserver.portal.core.templatetags.unit import format_rupiahs
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.NOTIFICATION_BALANCE_AMOUNT,
        category="disbursement",
        is_active=True).first()
    if not feature_setting:
        return
    lender = LenderCurrent.objects.filter(lender_name=lender_name).last()
    current_lender_balance = LenderBalanceCurrent.objects.filter(lender=lender).last()
    available_balance = calculate_available_balance(
        current_lender_balance.id, 'transaction')
    balance_threshold = float(feature_setting.parameters['balance_threshold'])
    if float(available_balance) < balance_threshold:
        # send message
        messages = "*Warning Message*\n"
        if settings.ENVIRONMENT != 'prod':
            messages = "*Warning Message ( TESTING PURPOSE ONLY FROM %s )* \n" % (settings.ENVIRONMENT.upper())
        message = "{0} Disbursement Balance is Low\n balance : {1} \n" \
                  "Please do transfer fund immediately!\n\n".format(lender.lender_name,
                                                                    format_rupiahs(available_balance, 'no'))
        messages += message
        for user in feature_setting.parameters['users']:
            get_slack_bot_client().api_call("chat.postMessage",
                                            channel=user,
                                            text=messages)


@task(name='send_notification_message_balance_amount')
def send_notification_message_balance_amount(lender_name=PartnerConstant.JTP_PARTNER):
    from juloserver.followthemoney.tasks import calculate_available_balance
    from juloserver.portal.core.templatetags.unit import format_rupiahs
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.NOTIFICATION_BALANCE_AMOUNT,
        category="disbursement",
        is_active=True).first()
    if not feature_setting:
        return
    lender = LenderCurrent.objects.filter(lender_name=lender_name).last()
    current_lender_balance = LenderBalanceCurrent.objects.filter(lender=lender).last()
    available_balance = calculate_available_balance(
        current_lender_balance.id, 'transaction')
    messages = "*Notification Message*\n"
    if settings.ENVIRONMENT != 'prod':
        messages = "*Notification Message ( TESTING PURPOSE ONLY FROM %s )* \n" % (settings.ENVIRONMENT.upper())
    message = "{0} Balance for Disbursement Information\n" \
              "{0} balance : {1}\n\n".format(lender.lender_name,
                                             format_rupiahs(available_balance, 'no'))
    messages += message
    for user in feature_setting.parameters['users']:
        get_slack_bot_client().api_call("chat.postMessage",
                                        channel=user,
                                        text=messages)


@task(name='update_application_status_code_129_to_139')
def update_application_status_code_129_to_139():
    from ..services import process_application_status_change
    now = timezone.now()
    thirty_day_ago = now - relativedelta(days=30)

    status = 129
    app_ids = Application.objects.filter(
        (Q(product_line_id=31)) | (Q(product_line_id=30)),
        application_status_id=status,
        cdate__lt=thirty_day_ago,
        workflow__isnull=False
    ).values_list("id", flat=True)

    if app_ids:
        for app in app_ids:
            process_application_status_change(
                app,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                change_reason='expired after 30 days'
            )

@task(name='stuck_auto_retry_disbursement_via_xfers_wiper')
def stuck_auto_retry_disbursement_via_xfers_wiper():
    from juloserver.disbursement.services.xfers import XfersConst
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
        category="disbursement",
        is_active=True).first()

    params = feature.parameters
    if not feature:
        logger.info({'task': 'stuck_auto_retry_disbursement_via_xfers_wiper',
                     'status': 'feature inactive'})
        return

    disburse_failed_loan_ids = Application.objects.select_related('loan__disbursement_id').filter(
        application_status_id=ApplicationStatusCodes.FUND_DISBURSAL_FAILED).values_list('loan', flat=True)

    disbursements = Disbursement2.objects.filter(
        pk__in=disburse_failed_loan_ids, method=DisbursementVendors.XFERS,
        disburse_status=XfersConst().MAP_STATUS[XfersConst().STATUS_FAILED])
    if not disbursements:
        logger.info({'task': 'stuck_auto_retry_disbursement_via_xfers_wiper',
                     'status': 'no application need to proccessed'})
        return

    for disbursement in disbursements:
        stuck_auto_retry_disbursement_via_xfers_wiper_sub_task.delay(disbursement.id,
                                                                     params['max_retries'])


@task(name='stuck_auto_retry_disbursement_via_xfers_wiper_sub_task')
def stuck_auto_retry_disbursement_via_xfers_wiper_sub_task(disbursement_id, max_retries):
    from juloserver.disbursement.services.xfers import XfersConst

    from ..services import process_application_status_change

    disbursement = Disbursement2.objects.get(pk=disbursement_id)
    application = Application.objects.filter(loan__disbursement_id=disbursement.id)
    if 'Back-end server is at capacity' in disbursement.reason and disbursement.reference_id == None:
        is_retrying = True
        response = 'retrying (Back-end server is at capacity) failed from xfers'
    else:
        is_retrying, response = XfersService().check_disburse_status(disbursement)

    if is_retrying:
        with transaction.atomic():
            if disbursement.retry_times >= max_retries:
                new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_ONGOING
                change_reason = XfersConst().RETRY_EXCEEDED_CHANGE_REASON
                note = 'Disbursement via Xfers retry attempt is exceeded please disburse manually'

                logger.info({'task': 'stuck_auto_retry_disbursement_via_xfers_wiper_sub_task',
                             'application_id': application.id,
                             'status': 'max_retries exceeded sent it to status 177',
                             'response': response})
            else:
                disbursement.retry_times += 1
                disbursement.save(update_fields=['retry_times', 'udate'])
                new_status_code = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
                change_reason = XfersConst().RETRY_CHANGE_REASON
                note = 'Disbursement via Xfers retry attempt %s' % str(disbursement.retry_times)

                logger.info({'task': 'stuck_auto_retry_disbursement_via_xfers_wiper_sub_task',
                             'application_id': application.id,
                             'status': 'retrying disburse sent it back to status 170',
                             'response': response})
    else:
        if response['status'] == XfersConst().STATUS_COMPLETED:
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s account number %s via %s' % (
                application.email, disbursement.name_bank_validation.bank_code,
                disbursement.name_bank_validation.account_number,
                disbursement.name_bank_validation.method)

            logger.info({'task': 'stuck_auto_retry_disbursement_via_xfers_wiper_sub_tas',
                         'application_id': application.id,
                         'status': 'disbursement completed based on check_disburse_status',
                         'response': response})

    process_application_status_change(application.id, new_status_code, change_reason, note)

@task(name='record_digital_signature')
def record_digital_signature(application_id, signature_params):
    loan = Loan.objects.get_or_none(application_id=application_id)
    application = Application.objects.get(id=application_id)
    if not application.is_julo_one() and not application.is_grab():
        application = None

    SignatureVendorLog.objects.create(
        loan=loan,
        partner_id=loan.application.partner if loan else application.partner,
        application=application,
        vendor=signature_params["vendor"],
        event=signature_params["event"],
        response_code=int(signature_params["response_code"]),
        response_string=signature_params["response_string"],
        request_string=signature_params["request_string"],
        document=signature_params["document"],
    )


@task(name='record_digital_signature_julo_one')
def record_digital_signature_julo_one(loan_id, signature_params):
    loan = Loan.objects.get_or_none(id=loan_id)
    application = None
    SignatureVendorLog.objects.create(
        loan=loan,
        application=application,
        vendor=signature_params["vendor"],
        event=signature_params["event"],
        response_code=int(signature_params["response_code"]),
        response_string=signature_params["response_string"],
        request_string=signature_params["request_string"],
        document=signature_params["document"],
    )

@task(queue='application_normal')
def run_index_faces(application_id, repeat_face_recog=True, skip_pv_dv=False):
    rekognition = get_julo_face_rekognition()
    rekognition.run_index_face(application_id, repeat_face_recog, skip_pv_dv)


@task(queue='application_normal')
def process_pg_validate_bank_task(application_id):
    from juloserver.pii_vault.constants import PiiSource
    from juloserver.pii_vault.services import detokenize_for_model_object
    from juloserver.disbursement.models import NameBankValidation, BankNameValidationLog
    from juloserver.disbursement.constants import NameBankValidationStatus
    from juloserver.julo.services2.client_paymet_gateway import ClientPaymentGateway
    from juloserver.julo.banks import BankManager

    application = Application.objects.filter(id=application_id).last()
    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [
            {
                'customer_xid': application.customer.customer_xid,
                'object': application,
            }
        ],
        force_get_local_data=True,
    )
    application = detokenized_applications[0]
    logger.info(
        {
            'action': 'process_pg_validate_bank_task',
            'message': 'initiate process_pg_validate_bank_task',
            'application_id': application_id,
        }
    )
    if not application:
        logger.error(
            {
                'action': 'process_pg_validate_bank_task',
                'message': 'application not found',
                'application_id': application_id,
            }
        )
        return

    name_bank_validation_id = application.name_bank_validation_id
    validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
    if validation is None or validation.validation_status != NameBankValidationStatus.SUCCESS:

        bank = BankManager.get_by_name_or_none(application.bank_name)
        if not bank:
            logger.error(
                {
                    'action': 'process_pg_validate_bank_task',
                    'message': 'bank {} not found'.format(application.bank_name),
                    'application_id': application_id,
                }
            )
            return

        try:
            payload = {
                "bank_account": application.bank_account_number,
                "bank_id": bank.id,
                "bank_account_name": application.name_in_bank,
            }
            client = ClientPaymentGateway(
                client_id=settings.ONBOARDING_PG_CLIENT_ID,
                api_key=settings.ONBOARDING_PG_API_KEY,
            )
            with transaction.atomic():
                name_bank_validation = NameBankValidation.objects.create(
                    bank_id=bank.id,
                    bank_code=bank.bank_code,
                    account_number=payload.get('bank_account'),
                    name_in_bank=payload.get('bank_account_name'),
                    mobile_phone=application.mobile_phone_1,
                    method="PG",
                )
                update_fields = [
                    'bank_id',
                    'bank_code',
                    'account_number',
                    'name_in_bank',
                    'mobile_phone',
                    'method',
                ]
                name_bank_validation.create_history('create', update_fields)
                update_fields_for_log_name_bank_validation = [
                    'validation_status',
                    'validated_name',
                    'reason',
                ]

                name_bank_validation_id = name_bank_validation.id
                application.update_safely(name_bank_validation_id=name_bank_validation_id)
                result = client.verify_bank_account(payload)
                is_http_request_success = result.get('success')
                data = result.get('data')
                reason = None

                if is_http_request_success:  # handle status 200
                    validation_result_data = data.get('validation_result')
                    status = validation_result_data.get('status')
                    bank_account_info = validation_result_data.get('bank_account_info')
                    reason = validation_result_data.get('message')
                    if status == 'success':
                        name_bank_validation.validation_status = NameBankValidationStatus.SUCCESS
                        name_bank_validation.validated_name = bank_account_info.get(
                            'bank_account_name'
                        )
                        application.update_safely(
                            bank_account_number=bank_account_info.get('bank_account'),
                            name_in_bank=bank_account_info.get('bank_account_name'),
                        )
                        is_validation_success = True
                    else:
                        name_bank_validation.validation_status = NameBankValidationStatus.FAILED
                else:
                    # case if error 400, 401, 429, 500
                    reason = result.get('errors')[0]
                    name_bank_validation.validation_status = NameBankValidationStatus.FAILED

                logger.info(
                    {
                        'action': 'process_pg_validate_bank_task',
                        'is_http_request_success': is_http_request_success,
                        'application_id': application_id,
                        'error': result.get('errors'),
                    }
                )

                name_bank_validation.reason = reason
                name_bank_validation.save(update_fields=update_fields_for_log_name_bank_validation)
                name_bank_validation.create_history(
                    'update_status', update_fields_for_log_name_bank_validation
                )
                name_bank_validation.refresh_from_db()
                # create name_bank_validation_log
                name_bank_validation_log = BankNameValidationLog()
                name_bank_validation_log.validated_name = name_bank_validation.name_in_bank
                name_bank_validation_log.account_number = name_bank_validation.account_number
                name_bank_validation_log.method = name_bank_validation.method
                name_bank_validation_log.application = application
                name_bank_validation_log.reason = reason
                name_bank_validation_log.validation_status = name_bank_validation.validation_status
                name_bank_validation_log.validated_name = name_bank_validation.validated_name
                name_bank_validation_log.save()
                return
        except Exception as error:
            logger.error({
                'action': 'process_pg_validate_bank_task',
                'message': str(error),
                'application_id': application_id,    
            })
            return
    else:
        logger.info(
            {
                'action': 'process_pg_validate_bank_task',
                'message': 'validation_status already success',
                'application_id': application_id,    
            }
        )
        application.update_safely(
            bank_account_number=validation.account_number,
            name_in_bank=validation.validated_name,
        )
        return


@task(queue='application_xfers')
def process_validate_bank_task(application_id, is_experiment=None, force_validate=False, new_data=None):
    from juloserver.disbursement.constants import NameBankValidationVendors

    application = Application.objects.get_or_none(id=application_id)
    is_julo_one = application.is_julo_one()
    is_grab = application.is_grab()
    is_julo_starter = application.is_julo_starter()
    is_julo_one_ios = application.is_julo_one_ios()
    is_old_version = True

    # partnership agent assisted flow
    agent_assisted_app_flag_name = False
    if application and application.partner:
        agent_assisted_app_flag_name = (
            PartnershipApplicationFlag.objects.filter(application_id=application_id)
            .values_list('name', flat=True)
            .exists()
        )

    if application and application.partner and agent_assisted_app_flag_name:
        from juloserver.partnership.constants import PartnershipFlag
        from juloserver.partnership.services.services import bypass_name_bank_validation

        """
        -if config set false and field bank_name or bank_account_number is None we bypass bank validation.
        -if config set false and field bank_name or bank_account_number is have value
        we still running process_validate_bank_task
        """
        if not application.bank_name or not application.bank_account_number:
            field_flag = PartnershipFlowFlag.objects.filter(
                partner_id=application.partner.id,
                name=PartnershipFlag.FIELD_CONFIGURATION
            ).last()
            if field_flag:
                # If flag set to False, we do bypass name bank validation
                if not field_flag.configs.get('bank_name') or not field_flag.configs.get(
                    'bank_account_number'
                ):
                    bypass_name_bank_validation(application)
                    return

    if application.app_version:
        is_old_version = (
            semver.match(application.app_version, NameBankValidationStatus.OLD_VERSION_APPS)
            and not is_julo_one_ios
        )

    if is_julo_one or is_grab or is_julo_starter or is_julo_one_ios:
        name_bank_validation_id = application.name_bank_validation_id
    else:
        loan = application.loan
        name_bank_validation_id = loan.name_bank_validation_id

    data_to_validate = {'name_bank_validation_id': name_bank_validation_id,
                        'bank_name': application.bank_name,
                        'account_number': application.bank_account_number,
                        'name_in_bank': application.name_in_bank,
                        'mobile_phone': application.mobile_phone_1,
                        'application': application
                        }
    if new_data:
        data_to_validate['name_in_bank'] = new_data['name_in_bank']
        data_to_validate['bank_name'] = new_data['bank_name']
        data_to_validate['account_number'] = new_data['bank_account_number']
        data_to_validate['name_bank_validation_id'] = None
        if is_grab:
            data_to_validate['mobile_phone'] = format_mobile_phone(application.mobile_phone_1)
    validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
    # checking is validation is not success already
    if validation is None or validation.validation_status != NameBankValidationStatus.SUCCESS \
            or force_validate:
        if validation:
            validation.update_safely(method=NameBankValidationVendors.XFERS)
        validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        validation_id = validation.get_id()
        if not is_julo_one and not is_grab and not is_julo_starter and not is_julo_one_ios:
            loan.name_bank_validation_id = validation_id
            loan.save(update_fields=['name_bank_validation_id'])
        application.update_safely(name_bank_validation_id=validation_id)
        validation.validate()
        validation_data = validation.get_data()
        if not validation.is_success():
            if (is_old_version and not is_experiment) or validation_data['attempt'] >= 3 or \
                    PARTNER_PEDE == application.partner_name:
                validation_data['go_to_175'] = True
            if (
                (is_grab and application.status == ApplicationStatusCodes.LOC_APPROVED)
                or is_julo_one
                or is_julo_starter
                or is_julo_one_ios
            ):
                logger.warning(
                    'Julo one name bank validation error | application_id=%s, '
                    'validation_data=%s' % (application.id, validation_data)
                )
                return

            if is_grab:
                services.process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                    'name_bank_validation_failed'
                )
                return

            raise InvalidBankAccount(validation_data)
        else:
            # update table with new verified BA
            application.update_safely(
                bank_account_number=validation_data['account_number'],
                name_in_bank=validation_data['validated_name'],
            )
            if is_grab and application.status != ApplicationStatusCodes.LOC_APPROVED:
                services.process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    "system_triggered"
                )
    else:
        # update table with new verified BA
        application.update_safely(
            bank_account_number=validation.account_number,
            name_in_bank=validation.validated_name,
        )
        if is_grab and application.status != ApplicationStatusCodes.LOC_APPROVED:
            services.process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                "system_triggered"
            )


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def send_grab_sms_status_change_131_task(self, application_id, failure_action=None):
    application = Application.objects.filter(pk=application_id).last()
    if not application.is_grab():
        return

    template_code = GrabSMSTemplateCodes.GRAB_SMS_APP_AT_131
    try:
        julo_sms_client = get_julo_sms_client()
        julo_sms_client.send_grab_sms_based_on_template_code(
            template_code, application
        )
    except Exception as e:
        raise self.retry(exc=e)


@task(queue='application_normal', base=TaskWithRetry, bind=True)
def send_grab_email_status_change_131_task(self, application_id, failure_action=None):
    try:
        application = Application.objects.filter(pk=application_id).last()
        if not application.is_grab():
            return

        template_code = GrabEmailTemplateCodes.GRAB_EMAIL_APP_AT_131
        to_email = application.email
        if not to_email:
            application.email = application.customer.email
        get_julo_email_client().send_grab_email_based_on_template_code(
            template_code, application, 72
        )

    except Exception as e:
        raise self.retry(exc=e)

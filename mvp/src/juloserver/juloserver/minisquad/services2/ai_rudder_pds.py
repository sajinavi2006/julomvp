import base64
import logging
import re
from typing import (
    Dict,
    List,
    Optional,
    Union,
    Any,
)

from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import (
    QuerySet,
    Q,
    Sum,
)
from django.utils import timezone
from datetime import (
    date,
    datetime,
    timedelta,
    time,
)
from requests import (
    ConnectionError,
    HTTPError,
    Timeout,
)
from rest_framework.exceptions import ValidationError

from juloserver.account.models import Account, ExperimentGroup
from juloserver.account_payment.models import (
    AccountPaymentNote,
    AccountPayment,
)
from juloserver.account_payment.services.account_payment_related import (
    get_potential_and_total_cashback,
    process_crm_unpaid_loan_account_details_list,
)
from juloserver.apiv2.models import CollectionCallPriority, PdCollectionModelResult
from juloserver.dana.models import DanaCustomerData
from juloserver.integapiv1.serializers import AiRudderCustomerDataSerializer
from juloserver.julo.models import (
    SkiptraceHistory,
    SkiptraceHistoryPDSDetail,
    Skiptrace,
    PTP,
    SkiptraceResultChoice,
    Application,
    CallLogPocAiRudderPds,
    PaymentMethod,
    FeatureSetting,
    FDCRiskyHistory,
    CustomerWalletHistory,
    Payment,
    ApplicationFieldChange,
    PaymentEvent,
    ExperimentSetting,
    CollectionPrimaryPTP,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import ptp_create_v2
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import (
    format_valid_e164_indo_phone_number,
    format_e164_indo_phone_number,
    format_nexmo_voice_phone_number,
    masking_phone_number_value,
    execute_after_transaction_safely,
)
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.services.customer_related import get_refinancing_status_display
from juloserver.minisquad.clients.airudder_pds import AIRudderPDSClient
from juloserver.minisquad.clients import get_julo_ai_rudder_pds_client

from juloserver.minisquad.constants import (
    AIRudderPDSConstant,
    AiRudder,
    ICARE_DEFAULT_ZIP_CODE,
    DialerSystemConst,
    FeatureNameConst,
    DialerTaskStatus,
    ExperimentConst,
    DialerServiceTeam,
    RedisKey,
    IntelixResultChoiceMapping,
    DialerTaskType,
    SkiptraceHistoryEventName,
)
from juloserver.minisquad.models import (
    AIRudderPayloadTemp,
    CollectionDialerTemporaryData,
    DialerTask,
    intelixBlacklist,
    SentToDialer,
    CollectionRiskSkiptraceHistory,
    RiskCallLogPocAiRudderPds,
    RiskHangupReasonPDS,
    BucketRecoveryDistribution,
    CollectionIneffectivePhoneNumber,
    ManualDCAgentAssignment,
    CollectionSkiptraceEventHistory,
)
from juloserver.minisquad.services import (
    get_bucket_status,
    update_collection_risk_verification_call_list,
    get_exclude_account_ids_by_intelix_blacklist_improved,
    get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved,
    get_other_numbers_to_pds,
)
from juloserver.minisquad.services2.airudder import (
    airudder_construct_status_and_status_group,
)
from juloserver.minisquad.services2.dialer_related import (
    get_populated_data_for_calling,
    get_uninstall_indicator_from_moengage_by_customer_id,
    record_history_dialer_task_event,
    is_account_emergency_contact_experiment,
    get_sort_order_from_ana,
    extract_bucket_number,
)
import pytz
from django.db.utils import IntegrityError
from juloserver.minisquad.models import (
    HangupReasonPDS,
    VendorRecordingDetail,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.grab.models import (
    GrabSkiptraceHistory,
    GrabCallLogPocAiRudderPds,
    GrabHangupReasonPDS
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.minisquad.constants import ReasonNotSentToDialer
from juloserver.minisquad.utils import get_feature_setting_parameters
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    is_omnichannel_account,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting
from juloserver.omnichannel.models import OmnichannelPDSActionLogTask
from juloserver.credgenics.constants.feature_setting import CommsType
from babel.dates import format_date
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst as JuloFeatureNameConst,
)
from django_bulk_update.helper import bulk_update
from dateutil.relativedelta import relativedelta
from juloserver.ana_api.models import CollectionB5, CollectionB6
from juloserver.julo.services2.experiment import get_experiment_setting_by_code
from juloserver.account.constants import AccountLookupName
from juloserver.collops_qa_automation.utils import (
    extract_bucket_name_dialer,
    extract_bucket_name_dialer_bttc,
)
from django.db.models import F, FloatField, ExpressionWrapper
from juloserver.streamlined_communication.models import Holiday

logger = logging.getLogger(__name__)


def get_account_payment_base_on_mobile_phone(
    mobile_phone, partner=None, retroload_date=None, account_payment_id=''
):
    from juloserver.julo.utils import format_mobile_phone
    current_date = timezone.localtime(timezone.now()).date()

    formated_main_phone = format_mobile_phone(mobile_phone)
    account = None
    account_payment_param = None

    if account_payment_id:
        return AccountPayment.objects.filter(pk=int(account_payment_id)).last()

    current_date = timezone.localtime(timezone.now())
    if not retroload_date:
        # current day
        ai_rudder_payload = AIRudderPayloadTemp.objects.filter(
            phonenumber=mobile_phone, tipe_produk__in=AiRudder.J1_ELIGIBLE_PRODUCT
        ).last()
        if ai_rudder_payload:
            return ai_rudder_payload.account_payment
    # for retrload or manual upload
    application = (
        Application.objects.select_related('customer')
        .filter(
            mobile_phone_1__in=[formated_main_phone, mobile_phone.replace('+', '')],
            application_status_id__gte=ApplicationStatusCodes.LOC_APPROVED,
            product_line__product_line_code__in=ProductLineCodes.julo_product(),
        )
        .last()
    )
    if not application:
        application_change = ApplicationFieldChange.objects.filter(
            field_name='mobile_phone_1',
            old_value__in=[formated_main_phone, mobile_phone.replace('+', '')],
            application__application_status_id__gte=ApplicationStatusCodes.LOC_APPROVED,
            application__product_line__product_line_code__in=ProductLineCodes.julo_product(),
        ).last()
        if not application_change:
            errMsg = "Application doesnt not exists for this phone number {}".format(mobile_phone)
            raise Exception(errMsg)
        application = application_change.application
    account = application.customer.account_set.last()

    if retroload_date and partner is None:
        current_date = retroload_date
        start_of_day = retroload_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        sent_to_dialer = SentToDialer.objects.filter(
            account=account, cdate__gte=start_of_day, cdate__lt=end_of_day, task_id__isnull=False
        ).last()
        if sent_to_dialer:
            return sent_to_dialer.account_payment
    if not account:
        errMsg = "Account doesnt not exists for this phone number {}".format(mobile_phone)
        raise Exception(errMsg)

    cdate_start = current_date.replace(hour=2, minute=0, second=0, microsecond=0)
    cdate_end = cdate_start + timedelta(days=1)
    payment_event = (
        PaymentEvent.objects.filter(
            cdate__gte=cdate_start,
            cdate__lt=cdate_end,
            payment__account_payment__in=list(
                account.accountpayment_set.normal().values_list('id', flat=True)
            ),
        )
        .order_by('cdate')
        .first()
    )
    if not payment_event:
        return (
            account.accountpayment_set.normal()
            .filter(status__lt=PaymentStatusCodes.PAID_ON_TIME)
            .order_by('due_date')
            .first()
        )
    return payment_event.payment.account_payment


def get_account_or_account_payment_base_on_mobile_phone(mobile_phone, start_time=None):
    current_date = timezone.localtime(timezone.now()).date()
    if start_time:
        current_date = start_time.date()
    formated_main_phone = format_nexmo_voice_phone_number(mobile_phone)
    application = Application.objects.select_related('account').filter(
        mobile_phone_1=formated_main_phone,
        application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        product_line__product_line_code__in=ProductLineCodes.grab(),
        account_id__isnull=False).last()
    if not application:
        return None, None
    account = application.account
    account_payments = account.accountpayment_set.normal().order_by('due_date','id')
    account_payment_param = None
    for account_payment in account_payments:
        paid_date = account_payment.paid_date
        if (paid_date and paid_date == current_date) or not paid_date:
            return account_payment, account
        account_payment_param = account_payment
    return account_payment_param, account


class AIRudderPDSServices(object):
    def __init__(self):
        self.AI_RUDDER_PDS_CLIENT = get_julo_ai_rudder_pds_client()
        self.current_date = timezone.localtime(timezone.now()).date()
        self.tommorow_date = timezone.localtime(timezone.now() + timedelta(days=1)).date()
        self.yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()

    def get_list_of_task_id_today(self) -> List:
        end_time = timezone.localtime(timezone.now())
        start_time = end_time.replace(hour=0, minute=1, second=0, microsecond=0)
        data = self.AI_RUDDER_PDS_CLIENT.query_task_list(
            check_start_time=start_time, check_end_time=end_time)
        if not data or not data.get('list'):
            return []
        task_list = data.get('list')
        return [item['taskId'] for item in task_list if item.get('state', '') != 'Finished']

    def get_list_of_task_id_with_date_range(
            self, start_time: datetime, end_time: datetime) -> List:
        data = self.AI_RUDDER_PDS_CLIENT.query_task_list(
            check_start_time=start_time, check_end_time=end_time)
        if not data or not data.get('list'):
            return []
        task_list = data.get('list')
        return [item['taskId'] for item in task_list]

    def get_list_of_task_id_with_date_range_and_group(
            self, start_time: datetime, end_time: datetime, retries_time: int = 0) -> List:
        data = self.AI_RUDDER_PDS_CLIENT.query_task_list(
            check_start_time=start_time, check_end_time=end_time, retries_time=retries_time)
        if not data or not data.get('list'):
            return []
        task_list = data.get('list')
        return [item['taskId'] + '@@' +
                item['groupName'] + '@@' +
                item['source'] + '@@' +
                item['name'] for item in task_list]

    def delete_single_call_from_calling_queue(
            self, account_payment: AccountPayment):
        '''
        for delete customer from calling queue for now we can detect customer using
        mobile phone 1
        '''
        account = account_payment.account
        application = account_payment.account.last_application
        is_for_dana = application.is_dana_flow()
        task_ids = []
        mobile_phone_1 = application.mobile_phone_1
        dialer_data = SentToDialer.objects.filter(
            cdate__gte=timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=1),
            task_id__isnull=False,
            account_payment=account_payment,
        ).last()
        if is_for_dana:
            """
            to reduce traffic for dana customer that not call
            """
            if not dialer_data:
                return
            task_ids = [dialer_data.task_id]
            mobile_number = (
                DanaCustomerData.objects.filter(account_id=account.id)
                .values('mobile_number')
                .first()
            )
            mobile_phone_1 = mobile_number.get('mobile_number')

        else:
            redis_client = get_redis_client()
            redis_key = RedisKey.DAILY_TASK_IDS_FOR_CANCEL_CALL
            task_ids = redis_client.get_list(redis_key)
            if task_ids:
                task_ids = [item.decode("utf-8") for item in task_ids]
            else:
                task_ids = self.get_list_of_task_id_today()
                if len(task_ids) > 0:
                    redis_client.set_list(redis_key, task_ids, timedelta(minutes=5))

            # for bttc purpose
            AIRudderPayloadTemp.objects.filter(account_payment_id=account_payment.id).delete()
        if not mobile_phone_1:
            raise Exception(
                'AI Rudder Service error: Mobile phone 1 is null account payment id {}'.format(
                    account_payment.id)
            )
        mobile_phone_1 = format_valid_e164_indo_phone_number(mobile_phone_1)
        success_deleted, failed_message = self.do_delete_phone_numbers_from_call_queue(
            task_ids, [mobile_phone_1])
        if failed_message:
            raise Exception(
                'AI Rudder Service error: {}'.format(
                    str(failed_message))
            )
        if success_deleted and dialer_data:
            dialer_data.update_safely(is_deleted=True)

        return True

    def do_delete_phone_numbers_from_call_queue(self, task_ids: List, phone_numbers: List) -> tuple:
        success_deleted = set()
        failed_deleted = []
        for task_id in task_ids:
            response = self.AI_RUDDER_PDS_CLIENT.cancel_phone_call_by_phone_numbers(
                task_id, phone_numbers)
            if response.get('message') == AIRudderPDSConstant.SUCCESS_MESSAGE_RESPONSE:
                success_deleted_phone_number = response.get('body')
                if not success_deleted_phone_number:
                    continue
                success_deleted = success_deleted.union(set(success_deleted_phone_number))
            else:
                failed_deleted.append(response.get('message', 'message not exists on payload'))


        success_deleted = list(success_deleted)
        if not success_deleted:
            logger.info(
                {
                    'action': 'AI Rudder Services -> do_delete_phone_numbers_from_call_queue',
                    'message': "AI Rudder Service error: failed cancel call for "
                               "this task ids {} and this phone numbers {}".format(
                        str(task_ids), str(phone_numbers))
                }
            )
            return [], failed_deleted

        logger.info(
            {
                "action": "delete_single_call_from_calling_queue",
                "message": "success delete numbers {}".format(str(success_deleted)),
            }
        )
        return success_deleted, failed_deleted

    def delete_bulk_call_from_calling_queue(
            self, phone_numbers: list, task_ids: List = []) -> tuple:
        if not task_ids:
            task_ids = self.get_list_of_task_id_today()
        if not task_ids:
            raise Exception('AI Rudder Service error: dont have tasks list')
        formated_phone_numbers = []
        failed_formated_phone_numbers = []
        for phone_number in phone_numbers:
            try:
                mobile_phone_1 = format_valid_e164_indo_phone_number(phone_number)
                formated_phone_numbers.append(mobile_phone_1)
            except Exception as e:
                failed_formated_phone_numbers.append(phone_number)

        if not formated_phone_numbers:
            raise Exception(
                "all given phone numbers not in correct format {}, failed formated {}".format(
                str(phone_numbers), str(failed_formated_phone_numbers)))
        if failed_formated_phone_numbers:
            logger.info({
                'action': 'delete_bulk_call_from_calling_queue',
                'message': 'failed formated phone numbers {}'.format(failed_formated_phone_numbers)
            })
        return self.do_delete_phone_numbers_from_call_queue(task_ids, formated_phone_numbers)

    def get_call_results_data_by_task_id(
        self,
        task_id: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 0,
        total_only: bool = False,
        offset: int = 0,
        call_id: str = '',
        retries_time: int = 0,
        need_customer_info: bool = False,
    ) -> List:
        if not task_id:
            raise Exception(
                'AI Rudder Service error: tasks id is null for this time range {} - {}'.format(
                    str(start_time), str(end_time)
                )
            )

        response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(
            task_id=task_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
            call_id=call_id,
            retries_time=retries_time,
            need_customer_info=need_customer_info,
        )
        body = response.get('body', None)
        if not body:
            logger.info({'action': 'AI Rudder PDS services', 'message': 'response dont have body'})
            return []

        if total_only:
            total = body.get('total', None)
            if not total:
                logger.info(
                    {'action': 'AI Rudder PDS services',
                    'message': 'response body dont have column total'})
                return 0

            return total

        list_data = body.get('list', None)
        if not list_data:
            logger.info(
                {'action': 'AI Rudder PDS services',
                 'message': 'response body dont have column list'})
            return []

        return list_data

    def determine_used_model_by_task(self, task_name):
        model_list = {
            'skiptrace_history': SkiptraceHistory,
            'call_log_poc': CallLogPocAiRudderPds,
            'hangup_pds': HangupReasonPDS,
        }
        if task_name and "RISK_UNVERIFIED" in task_name:
            model_list['skiptrace_history'] = CollectionRiskSkiptraceHistory
            model_list['call_log_poc'] = RiskCallLogPocAiRudderPds
            model_list['hangup_pds'] = RiskHangupReasonPDS

        return model_list

    def retro_load_write_data_to_skiptrace_history(
            self, data, hangup_reason=None, retro_cdate=None, task_name=None):
        from juloserver.minisquad.tasks2.dialer_system_task import \
            sync_up_skiptrace_history, download_call_recording_result
        from juloserver.omnichannel.tasks.customer_related import send_pds_action_log
        used_model_dictionary = self.determine_used_model_by_task(task_name)
        skiptrace_history_model = used_model_dictionary.get('skiptrace_history')

        talk_result = data.get('talk_result', '')
        is_connected = talk_result == 'Connected'
        call_id = data.get('unique_call_id', None)
        task_id = data.get('dialer_task_id', None)
        fn_name = 'retro_load_write_data_to_skiptrace_history'
        logger.info({
            'function_name': fn_name,
            'message': 'Start process write_data_to_skiptrace_history',
            'call_id': call_id
        })
        if skiptrace_history_model.objects.filter(external_unique_identifier=call_id).exists():
            logger.info({
                'function_name': fn_name,
                'message': "external unique identifier exists {} will process sync up".format(call_id)
            })
            self.sync_up_skiptrace_history_services(data, retro_cdate, task_name)
            return

        phone_number = data.get('phone_number', '')
        main_number = data.get('main_number', '')
        if phone_number == '':
            errMsg = "Phone number not valid, please provide valid phone number! {}".format(call_id)
            raise Exception(errMsg)

        customize_res = data.get('customizeResults', {})
        agent_user = None
        spoke_with = customize_res.get('Spokewith', '')
        non_payment_reason = customize_res.get('non_payment_reason', '')

        agent_name = data.get('agent_name', None)
        if agent_name:
            agent_user = User.objects.filter(username=agent_name).last()
            if not agent_user:
                errMsg = "Agent name not valid, please provide " \
                         "valid agent name with this call id {}".format(call_id)
                raise Exception(errMsg)

            CuserMiddleware.set_user(agent_user)

        account_payment = get_account_payment_base_on_mobile_phone(
            main_number,
            partner=None,
            retroload_date=retro_cdate,
            account_payment_id=data.get('account_payment_id', ''),
        )
        if not account_payment:
            errMsg = "Account Payment doesnt not exists for this call id {}".format(call_id)
            raise Exception(errMsg)

        account = account_payment.account
        customer = account.customer
        application = account.customer.application_set.last()

        with transaction.atomic():
            phone_number = format_e164_indo_phone_number(phone_number)
            skiptrace = Skiptrace.objects.filter(
                phone_number=phone_number,
                customer_id=customer.id
            ).last()
            if not skiptrace:
                skiptrace = Skiptrace.objects.create(
                    phone_number=phone_number,
                    customer_id=customer.id,
                    contact_source=data.get('contact_source', '')
                )

            ptp_notes = ''
            ptp_amount = customize_res.get('PTP Amount', '')
            ptp_date = customize_res.get('ptp_date', '')
            if ptp_amount != '' and ptp_date != '':
                if not PTP.objects.filter(
                        ptp_date=ptp_date, ptp_amount=ptp_amount, agent_assigned=agent_user,
                        account_payment=account_payment
                ).exists():
                    ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                    account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create_v2(account_payment, ptp_date, ptp_amount, agent_user, True, False)
                    if retro_cdate:
                        created_ptp = PTP.objects.filter(
                            ptp_date=ptp_date, ptp_amount=ptp_amount, agent_assigned=agent_user,
                            account_payment=account_payment).last()
                        if created_ptp:
                            created_ptp.cdate = retro_cdate
                            created_ptp.save()

            hangup_reason_in_payload = data.get('hangup_reason', None)
            if not hangup_reason_in_payload:
                hangup_reason_in_payload = hangup_reason

            construct_status_data = hangup_reason_in_payload if not is_connected else customize_res
            callback_type = AiRudder.AGENT_STATUS_CALLBACK_TYPE \
                if is_connected else AiRudder.CONTACT_STATUS_CALLBACK_TYPE
            status, status_group = airudder_construct_status_and_status_group(
                callback_type, construct_status_data, True, hangup_reason_in_payload
            )

            identifier = status_group if \
                callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
            is_identifier_exist = identifier != ''
            filter_identifier = identifier if is_identifier_exist else 'NULL'
            skiptrace_res_choice = SkiptraceResultChoice.objects.all().extra(
                where=["lower(name) =  %s"], params=[filter_identifier.lower()]).last()
            if not skiptrace_res_choice:
                errMsg = "Call status not valid call id {}".format(call_id)
                raise Exception(errMsg)

            start_time = data.get('start_ts', '')
            end_time = data.get('end_ts', '')
            if not start_time or not end_time:
                raise Exception("start ts or end ts is null {}".format(call_id))

            skiptrace_history_data = dict(
                start_ts=start_time, end_ts=end_time,
                skiptrace_id=skiptrace.id,
                payment_id=None,
                payment_status=None,
                loan_id=None,
                loan_status=None,
                application_id=application.id,
                application_status=application.status,
                account_id=account.id,
                account_payment_id=account_payment.id,
                account_payment_status_id=account_payment.status_id,
                agent_id=agent_user.id if agent_user else None,
                agent_name=agent_user.username if agent_user else None,
                notes=data.get('skiptrace_notes', None),
                non_payment_reason=non_payment_reason,
                spoke_with=spoke_with,
                status_group=status_group,
                status=status,
                source=AiRudder.AI_RUDDER_SOURCE,
                call_result=skiptrace_res_choice,
                external_unique_identifier=call_id,
                external_task_identifier=task_id)

            if skiptrace_history_model is CollectionRiskSkiptraceHistory:
                skiptrace_history_data.pop('application_status', None)
                skiptrace_history_data.pop('loan_id', None)
                skiptrace_history_data.pop('loan_status', None)
                skiptrace_history_data.pop('payment_id', None)

            skiptrace_history = skiptrace_history_model.objects.create(**skiptrace_history_data)
            if skiptrace_history and retro_cdate:
                skiptrace_history.cdate = retro_cdate
                skiptrace_history.save()
            hangup_reason_id = data.get('hangup_reason')
            if hangup_reason_id:
                # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
                self.write_hangup_reason(
                    skiptrace_history.id, int(hangup_reason_id), task_name=task_name
                )
                self.count_ineffective_phone_number(
                    skiptrace.id, int(hangup_reason_id), end_time.date(), task_name
                )

            self.write_skiptrace_history_pds_detail(skiptrace_history.id, data)
            execute_after_transaction_safely(
                lambda: send_pds_action_log.delay(
                    [
                        OmnichannelPDSActionLogTask(
                            skiptrace_history_id=skiptrace_history.id,
                            contact_source=data.get('contact_source'),
                            task_name=data.get('task_name'),
                        )
                    ]
                )
            )


            if type(skiptrace_history) is CollectionRiskSkiptraceHistory:
                update_collection_risk_verification_call_list(skiptrace_history)
            skiptrace_notes = data.get('skiptrace_notes', None)
            if skiptrace_notes or ptp_notes:
                contact_source = data.get('contact_source', '') or skiptrace.contact_source
                account_payment_note = AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    account_payment=account_payment,
                    added_by=agent_user,
                    extra_data={
                        "call_note": {
                            "contact_source": contact_source,
                            "phone_number": phone_number,
                            "call_result": status,
                            "spoke_with": spoke_with,
                            "non_payment_reason": non_payment_reason,
                        }
                    }
                )

                if account_payment_note and retro_cdate:
                    account_payment_note.cdate = retro_cdate
                    account_payment_note.save()

            if data.get('rec_link') and data.get('answertime') and not VendorRecordingDetail.objects.filter(
                unique_call_id=call_id).exists() and not retro_cdate:
                    download_call_recording_result.delay(
                        call_id=call_id,
                        task_name=data.get('task_name'),
                        link=data.get('rec_link'),
                        answer_time=data.get('answertime'),
                    )

            logger.info({
                'function_name': fn_name,
                'message': 'Success process skiptrace history for this call id {}'.format(call_id),
            })

        return True

    def get_list_of_task_id_and_task_name_with_date_range(
            self, start_time: datetime, end_time: datetime, retries_time: int = 0) -> List:
        data = self.AI_RUDDER_PDS_CLIENT.query_task_list(
            check_start_time=start_time, check_end_time=end_time, retries_time=retries_time)
        if not data or not data.get('list'):
            return []
        task_list = data.get('list')
        return [
            dict(task_id=item['taskId'], task_name=item['name']) for item in task_list]

    def get_download_link_of_call_recording_by_call_id(self, call_id: str):
        if not call_id:
            logger.info({
                'action': 'get_download_link_of_call_recording_by_call_id',
                'message': 'call id is null'
            })
            return

        response = self.AI_RUDDER_PDS_CLIENT.get_recording_url_by_call_id(
            call_id=call_id)
        body = response.get('body', None)
        if not body:
            logger.info({
                'action': 'get_download_link_of_call_recording_by_call_id',
                'message': 'response dont have body'
            })
            return

        link_recording = body.get('link', None)
        if not link_recording:
            logger.info({
                'action': 'get_download_link_of_call_recording_by_call_id',
                'message': 'response body dont have key list'
            })
            return

        return link_recording

    def get_eligible_phone_number_list(
        self,
        application,
        detokenized_data=None,
        ineffective_consecutive_days: int = 0,
        bucket_number: int = 0,
        ineffective_refresh_days: int = 0,
    ) -> dict:
        from juloserver.minisquad.tasks2.dialer_system_task import (
            reset_count_ineffective_phone_numbers_by_skiptrace_ids,
            record_skiptrace_event_history_task,
        )

        inefffective_phone_numbers = []
        mobile_phone_1 = (
            getattr(detokenized_data, 'mobile_phone_1', None) or application.mobile_phone_1
        )
        phone_numbers = dict(
            company_phone_number=format_e164_indo_phone_number(
                str(application.company_phone_number or '')) ,
            kin_mobile_phone=format_e164_indo_phone_number(str(application.kin_mobile_phone or '')),
            spouse_mobile_phone=format_e164_indo_phone_number(
                str(application.spouse_mobile_phone or '')
            ),
            mobile_phone_1=format_e164_indo_phone_number(str(mobile_phone_1 or '')),
            mobile_phone_2=format_e164_indo_phone_number(str(application.mobile_phone_2 or '')),
            phonenumber=format_e164_indo_phone_number(str(mobile_phone_1 or '')),
        )
        today = timezone.localtime(timezone.now()).date()
        intelix_blacklist_data = intelixBlacklist.objects.filter(
            skiptrace__customer=application.customer
        ).filter(
            Q(expire_date__gte=today) | Q(expire_date__isnull=True)
        ).select_related('skiptrace')

        for intelix_blacklist in intelix_blacklist_data.iterator():
            for index in phone_numbers:
                if phone_numbers[index] == format_e164_indo_phone_number(
                        intelix_blacklist.skiptrace.phone_number):
                    phone_numbers[index] = ''
                    break

        if not ineffective_consecutive_days or bucket_number < 1:
            return phone_numbers, inefffective_phone_numbers
        phone_number_list = [phone_number for _, phone_number in phone_numbers.items()]
        skiptraces = Skiptrace.objects.filter(
            customer=application.customer, phone_number__in=phone_number_list
        ).values_list('pk', 'phone_number')
        skiptrace_dict = {item[0]: item[1] for item in skiptraces}
        skiptrace_ids = [item[0] for item in skiptraces]
        inefffective_skiptraces = CollectionIneffectivePhoneNumber.objects.filter(
            skiptrace_id__in=skiptrace_ids,
            ineffective_days__gte=ineffective_consecutive_days,
        ).values_list('pk', 'skiptrace_id')
        inefffective_ids = []
        inefffective_skiptrace_ids = []
        for item in inefffective_skiptraces:
            inefffective_ids.append(item[0])
            inefffective_skiptrace_ids.append(item[1])
        # refresh ineffective days
        if ineffective_refresh_days:
            reset_count_ineffective_phone_numbers_by_skiptrace_ids.delay(
                skiptrace_ids,
                ineffective_refresh_days,
            )

        if not inefffective_skiptrace_ids:
            return phone_numbers, inefffective_phone_numbers

        # just in case when bucket changes
        CollectionIneffectivePhoneNumber.objects.filter(
            pk__in=inefffective_ids,
            flag_as_unreachable_date__isnull=True,
        ).update(flag_as_unreachable_date=today)
        record_skiptrace_event_history_task.delay(
            inefffective_skiptrace_ids,
            ineffective_refresh_days,
            ineffective_consecutive_days,
            bucket_number,
        )
        inefffective_phone_numbers = [
            val for key, val in skiptrace_dict.items() if key in inefffective_skiptrace_ids
        ]
        phone_number_filtered = {
            key: '' if val in inefffective_phone_numbers else val
            for key, val in phone_numbers.items()
        }
        phone_number = (
            phone_number_filtered.get('mobile_phone_1')
            or phone_number_filtered.get('mobile_phone_2')
            or phone_number_filtered.get('spouse_mobile_phone')
            or phone_number_filtered.get('company_phone_number')
        )
        phone_number_filtered.update(phonenumber=phone_number)
        return phone_number_filtered, inefffective_phone_numbers

    def check_last_call_agent_and_status(self, account_payment: AccountPayment) -> tuple:
        ptp = account_payment.ptp_set.last()
        if not ptp:
            return '', ''

        if ptp.ptp_date in [self.current_date, self.tommorow_date]:
            agent = ptp.agent_assigned
            return '' if not agent else agent.username, 'RPC-PTP'
        elif ptp.ptp_date == self.yesterday:
            agent = ptp.agent_assigned
            return '' if not agent else agent.username, 'RPC-Broken PTP'

        return '', ''

    def get_loan_refinancing_data_for_dialer(self, account: Account) -> tuple:
        loan_refinancing = LoanRefinancingRequest.objects.filter(account=account).last()
        if not loan_refinancing:
            return '', 0, ''

        refinancing_status = get_refinancing_status_display(loan_refinancing)
        refinancing_prerequisite_amount = loan_refinancing.last_prerequisite_amount
        refinancing_expire_date = loan_refinancing.expire_date

        return refinancing_status, refinancing_prerequisite_amount, refinancing_expire_date

    def get_customer_bucket_type(
            self, account_payment: AccountPayment, account: Account, dpd: int) -> str:
        previous_payments_on_bucket = account.accountpayment_set.filter(
            id__lt=account_payment.id,
            status_id__gt=PaymentStatusCodes.PAID_ON_TIME,
            paid_date__isnull=False
        )
        if account_payment.is_paid and account_payment.status_id == PaymentStatusCodes.PAID_ON_TIME:
            return 'NA'
        if dpd <= 0 and not account_payment.is_paid:
            return 'NA'
        current_payment_bucket = get_bucket_status(dpd)
        biggest_entered_bucket = 0
        for previous_payment in previous_payments_on_bucket:
            calculate_pay_on_dpd = previous_payment.paid_date - previous_payment.due_date
            dpd_when_paid = calculate_pay_on_dpd.days
            previous_bucket = get_bucket_status(dpd_when_paid)
            if previous_bucket > biggest_entered_bucket:
                biggest_entered_bucket = previous_bucket

        if current_payment_bucket <= biggest_entered_bucket:
            return 'Stabilized'

        return 'Fresh'

    def construct_payload(
        self,
        populated_data: CollectionDialerTemporaryData,
        bucket_name: str,
        sorted_account=None,
        experiment_phonenumber=None,
        is_jturbo_merge: bool = False,
        bttc_dict: dict = {},
        max_sent_other_number: int = 0,
        ineffective_consecutive_days: int = 0,
        ineffective_refresh_days: int = 0,
    ) -> Union:
        from juloserver.waiver.services.account_related import (
            can_account_get_refinancing_centralized,
        )

        if not populated_data:
            return None

        if isinstance(populated_data, AccountPayment):
            # this if from AccountPayment model
            account_payment = populated_data
            account = account_payment.account
            customer = account.customer
        else:
            # this if from CollectionDialerTemporaryData model
            account_payment = populated_data.account_payment
            customer = populated_data.customer
            account = account_payment.account

        regex_pattern = r'JTURBO'
        if bucket_name in (DialerSystemConst.DIALER_BUCKET_6_1, DialerSystemConst.DIALER_BUCKET_5):
            application = account.get_active_application()
        elif re.search(regex_pattern, bucket_name):
            application = customer.application_set.filter(
                product_line=ProductLineCodes.TURBO
            ).last()
        else:
            product_line = (
                ProductLineCodes.J1
                if account.account_lookup.name
                in [AccountLookupName.JULO1, AccountLookupName.JULOIOS]
                else ProductLineCodes.TURBO
            )
            application = customer.application_set.filter(product_line=product_line).last()

        zip_code = application.address_kodepos
        if application.partner and application.partner.name in \
                PartnerConstant.ICARE_PARTNER and not application.address_kodepos:
            zip_code = ICARE_DEFAULT_ZIP_CODE

        bucket_name_to_store = (
            bucket_name.replace('JTURBO', 'JULO') if is_jturbo_merge else bucket_name
        )

        sort_order = None
        if bttc_dict:
            sort_order = bttc_dict.get('sort_rank', None)
            bucket_name = bttc_dict.get('bucket_name', None)
            bucket_name_to_store = bucket_name
        elif (
            isinstance(populated_data, CollectionDialerTemporaryData) and populated_data.sort_order
        ):
            sort_order = populated_data.sort_order
        elif sorted_account:
            sort_order = sorted_account

        if isinstance(populated_data, AccountPayment):
            alamat = '{} {} {} {} {} {}'.format(
                application.address_street_num,
                application.address_provinsi,
                application.address_kabupaten,
                application.address_kecamatan,
                application.address_kelurahan,
                application.address_kodepos)
            dpd = account_payment.dpd
            payload = AIRudderPayloadTemp(
                account_payment_id=account_payment.id,
                account_id=account.id,
                customer=customer,
                nama_perusahaan=application.company_name,
                posisi_karyawan=application.position_employees,
                nama_pasangan=application.spouse_name,
                nama_kerabat=application.kin_name,
                hubungan_kerabat=application.kin_relationship,
                jenis_kelamin=application.gender,
                tgl_lahir=application.dob,
                tgl_gajian=application.payday,
                tujuan_pinjaman=application.loan_purpose,
                tanggal_jatuh_tempo=account_payment.due_date,
                alamat=alamat,
                kota=application.address_kabupaten,
                dpd=dpd,
                partner_name=application.partner.name if application.partner else None,
                tgl_upload=datetime.strftime(self.current_date, "%Y-%m-%d"),
                tipe_produk=application.product_line.product_line_type,
                zip_code=zip_code,
                bucket_name=bucket_name_to_store,
                total_denda=abs(account.get_outstanding_late_fee()),
                total_due_amount=account.accountpayment_set.normal().not_paid_active().filter(
                    due_date__lte=self.current_date).aggregate(
                    Sum('due_amount'))['due_amount__sum'] or 0,
                total_outstanding=account.accountpayment_set.normal().filter(
                    status_id__lte=PaymentStatusCodes.PAID_ON_TIME).aggregate(
                    Sum('due_amount'))['due_amount__sum'] or 0,
                angsuran_per_bulan=account_payment.due_amount,
                application_id=application.id,
                sort_order=sort_order,
            )
        else:
            # this if from CollectionDialerTemporaryData model
            dpd = populated_data.dpd
            payload = AIRudderPayloadTemp(
                account_payment_id=account_payment.id,
                account_id=account_payment.account_id,
                customer=customer,
                nama_customer=populated_data.nama_customer,
                nama_perusahaan=populated_data.nama_perusahaan,
                posisi_karyawan=populated_data.posisi_karyawan,
                nama_pasangan=populated_data.nama_pasangan,
                nama_kerabat=populated_data.nama_kerabat,
                hubungan_kerabat=populated_data.hubungan_kerabat,
                jenis_kelamin=populated_data.jenis_kelamin,
                tgl_lahir=populated_data.tgl_lahir,
                tgl_gajian=populated_data.tgl_gajian,
                tujuan_pinjaman=populated_data.tujuan_pinjaman,
                tanggal_jatuh_tempo=populated_data.tanggal_jatuh_tempo,
                alamat=populated_data.alamat,
                kota=populated_data.kota,
                dpd=populated_data.dpd,
                partner_name=populated_data.partner_name,
                sort_order=sort_order,
                tgl_upload=datetime.strftime(self.current_date, "%Y-%m-%d"),
                tipe_produk=populated_data.tipe_produk,
                zip_code=zip_code,
                bucket_name=bucket_name_to_store,
                total_denda=abs(account_payment.account.get_outstanding_late_fee()),
                total_due_amount=account.accountpayment_set.normal().not_paid_active().filter(
                    due_date__lte=self.current_date).aggregate(
                    Sum('due_amount'))['due_amount__sum'] or 0,
                total_outstanding=account.accountpayment_set.normal().filter(
                    status_id__lte=PaymentStatusCodes.PAID_ON_TIME).aggregate(
                    Sum('due_amount'))['due_amount__sum'] or 0,
                angsuran_per_bulan=account_payment.due_amount,
                va_indomaret=populated_data.va_indomaret,
                va_alfamart=populated_data.va_alfamart,
                va_maybank=populated_data.va_maybank,
                va_permata=populated_data.va_permata,
                va_bca=populated_data.va_bca,
                va_mandiri=populated_data.va_mandiri,
            )
            is_bttc = 'bttc' in bucket_name_to_store.lower()
            bucket_number = extract_bucket_number(bucket_name_to_store, is_bttc, populated_data.dpd)
            phone_numbers, ineffective_phone_numbers = self.get_eligible_phone_number_list(
                application,
                populated_data,
                ineffective_consecutive_days,
                bucket_number=bucket_number,
                ineffective_refresh_days=ineffective_refresh_days,
            )
            if experiment_phonenumber:
                payload.phonenumber = experiment_phonenumber
            else:
                payload.phonenumber = phone_numbers['phonenumber']
                payload.mobile_phone_1_2 = phone_numbers['mobile_phone_1']
                payload.mobile_phone_1_3 = phone_numbers['mobile_phone_1']
                payload.mobile_phone_1_4 = phone_numbers['mobile_phone_1']
                payload.mobile_phone_2 = phone_numbers['mobile_phone_2']
                payload.mobile_phone_2_2 = phone_numbers['mobile_phone_2']
                payload.mobile_phone_2_3 = phone_numbers['mobile_phone_2']
                payload.mobile_phone_2_4 = phone_numbers['mobile_phone_2']
                payload.telp_perusahaan = phone_numbers['company_phone_number']
                payload.no_telp_kerabat = ''
                payload.no_telp_pasangan = phone_numbers['spouse_mobile_phone']

            other_numbers = None
            if max_sent_other_number and not experiment_phonenumber:
                phone_number_list = [phone_number for _, phone_number in phone_numbers.items()]
                other_numbers = get_other_numbers_to_pds(
                    account_payment.account,
                    phone_number_list,
                    max_sent_other_number,
                    ineffective_phone_numbers,
                )
                payload.other_numbers = other_numbers
            if not phone_numbers['phonenumber']:
                if not other_numbers:
                    raise Exception('all phone number indicated as ineffective')
                else:
                    payload.phonenumber = other_numbers[0]

        last_paid_account_payment = account.accountpayment_set.normal().filter(
            paid_amount__gt=0).exclude(paid_date__isnull=True).order_by('paid_date').last()
        last_pay_date, last_pay_amount = "", 0
        if last_paid_account_payment:
            last_pay_date = last_paid_account_payment.paid_date
            last_pay_amount = last_paid_account_payment.paid_amount

        payload.last_pay_date = last_pay_date
        payload.last_pay_amount = last_pay_amount

        last_agent, last_call_status = self.check_last_call_agent_and_status(account_payment)
        payload.last_agent = last_agent
        payload.last_call_status = last_call_status

        refinancing_status, refinancing_prerequisite_amount, refinancing_expire_date = \
            self.get_loan_refinancing_data_for_dialer(account)

        is_eligible_refinancing, _ = can_account_get_refinancing_centralized(account.id)
        bss_refinancing_status = ''
        if is_eligible_refinancing:
            bss_refinancing_status = "Pinjaman BSS aktif - bisa ditawarkan R4"
        payload.status_refinancing_lain = bss_refinancing_status
        payload.refinancing_status = refinancing_status
        payload.activation_amount = refinancing_prerequisite_amount
        payload.program_expiry_date = refinancing_expire_date
        payload.promo_untuk_customer = ''
        payload.customer_bucket_type = self.get_customer_bucket_type(
            account_payment, account, dpd)
        payload.uninstall_indicator = get_uninstall_indicator_from_moengage_by_customer_id(customer.id)

        fdc_risky = None
        fdc_risky_udate = '-'
        fdc_risky_history = FDCRiskyHistory.objects.filter(application_id=application.id).last()
        if fdc_risky_history:
            fdc_risky = fdc_risky_history.is_fdc_risky
            fdc_risky_udate = format_date(fdc_risky_history.udate, "d MMM yyyy", locale="id_ID")
        payload.fdc_risky = {True: "Yes {}".format(fdc_risky_udate), False: "No {}".format(fdc_risky_udate), None: "-"}.get(fdc_risky, "-")

        payload.risk_score = account_payment.risk_score

        cashback_counter = account.cashback_counter or 0
        potensi_cashback, total_cashback_earned = get_potential_and_total_cashback(account_payment, cashback_counter, customer.id)
        if type(potensi_cashback) is tuple:
            potensi_cashback = potensi_cashback[0]

        payload.potensi_cashback = potensi_cashback
        payload.total_seluruh_perolehan_cashback = total_cashback_earned

        payload.unpaid_loan_account_details = self.get_unpaid_loan_description_list_pds(
            account_payment
        )

        return payload

    def process_construction_data_for_dialer(
            self, bucket_name: str, retries_times: int) -> int:
        from juloserver.minisquad.tasks2 import write_not_sent_to_dialer_async

        fn_name = 'process_construction_data_for_dialer'
        identifier = 'construct_{}_retries_{}'.format(bucket_name, retries_times)
        logger.info({'action': fn_name, 'identifier': identifier, 'state': 'querying'})
        populated_dialer_call_data = get_populated_data_for_calling(bucket_name)
        sorted_account_payment_dict = None
        if not populated_dialer_call_data:
            raise Exception("Not Found data in ops.collection_dialer_temporary_data")

        if bucket_name in [
            DialerSystemConst.DIALER_BUCKET_1,
            DialerSystemConst.DIALER_BUCKET_3,
            DialerSystemConst.DIALER_BUCKET_2,
        ]:
            account_payments = AccountPayment.objects.filter(
                id__in=populated_dialer_call_data.values_list('account_payment_id', flat=True)
            )
            sorted_account_payment_dict = get_sort_order_from_ana(account_payments)

        data_count = populated_dialer_call_data.count()
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'queried',
            'total_data': data_count
        })
        populated_dialer_call_data = populated_dialer_call_data.select_related(
            'account_payment', 'customer', 'account_payment__account'
        ).prefetch_related(
            'customer__application_set', 'account_payment__ptp_set',
            'account_payment__account__accountpayment_set'
        )
        # bathing data creation prevent full memory
        batch_size = 500
        counter = 0
        processed_data_count = 0
        formated_ai_rudder_payload = []
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'construct',
        })
        # implementing experiment for b1
        bucket1_experiment = [
            DialerSystemConst.DIALER_BUCKET_1,
            DialerSystemConst.DIALER_BUCKET_1_NC,
        ]
        # implement merge jturbo bucket
        is_merge_jturbo = False
        eligible_bucket_numbers_to_merge = []
        merge_j1_jturbo_bucket_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT,
            is_active=True,
        ).last()
        if merge_j1_jturbo_bucket_fs:
            bucket_number = extract_bucket_number(bucket_name)
            bucket_name_lower = bucket_name.lower()
            eligible_bucket_numbers_to_merge = merge_j1_jturbo_bucket_fs.parameters.get(
                'bucket_numbers_to_merge', []
            )
            is_merge_jturbo = (
                True
                if 'jturbo' in bucket_name_lower
                and bucket_number in eligible_bucket_numbers_to_merge
                else False
            )
        group_bucket = {}
        if is_merge_jturbo:
            bucket1_experiment.extend(
                [
                    DialerSystemConst.DIALER_JTURBO_B1,
                    DialerSystemConst.DIALER_JTURBO_B1_NON_CONTACTED,
                ]
            )
        if bucket_name in bucket1_experiment:
            b1_experiment_setting = (
                ExperimentSetting.objects.filter(
                    is_active=True, code=ExperimentConst.B1_SPLIT_GROUP_EXPERIMENT
                )
                .filter(
                    (
                        Q(start_date__date__lte=self.current_date)
                        & Q(end_date__date__gte=self.current_date)
                    )
                    | Q(is_permanent=True)
                )
                .last()
            )
            if b1_experiment_setting and b1_experiment_setting.criteria:
                criteria = b1_experiment_setting.criteria
                group_bucket = {
                    number: group for group, numbers in criteria.items() for number in numbers
                }
        max_sent_other_number = 0
        pass_other_number_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PASS_OTHER_NUMBER_TO_PDS,
            is_active=True,
        ).last()
        if pass_other_number_fs:
            bucket_number = extract_bucket_number(bucket_name)
            parameters = pass_other_number_fs.parameters
            bucket_numbers = parameters.get('bucket_numbers', [])
            max_sent_other_number = (
                parameters.get('max_phone_number', 0) if bucket_number in bucket_numbers else 0
            )

        dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name)
        dialer_task = DialerTask.objects.filter(
            type=dialer_task_type,
            vendor=DialerSystemConst.AI_RUDDER_PDS,
            cdate__gte=self.current_date,
        ).last()

        # check ineffective number
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()
        params = fs.parameters if fs else {}
        for item in populated_dialer_call_data:
            try:
                bucket_name_for_construct = bucket_name
                if group_bucket and group_bucket.get(item.account_payment.account.cycle_day, ''):
                    bucket_name_for_construct = (
                        bucket_name_for_construct
                        + '_'
                        + group_bucket.get(item.account_payment.account.cycle_day)
                    )
                sorted_account = None

                if sorted_account_payment_dict:
                    sorted_account = sorted_account_payment_dict.get(item.account_payment_id)
                param_per_bucket = params.get(bucket_name_for_construct, {})
                consecutive_days = param_per_bucket.get('consecutive_days', 0)
                ineffective_refresh_days = (
                    param_per_bucket.get('threshold_refresh_days')
                    if param_per_bucket.get('is_ineffective_refresh', False)
                    else 0
                )
                formatted_data = self.construct_payload(
                    item,
                    bucket_name_for_construct,
                    sorted_account,
                    is_jturbo_merge=is_merge_jturbo,
                    max_sent_other_number=max_sent_other_number,
                    ineffective_consecutive_days=consecutive_days,
                    ineffective_refresh_days=ineffective_refresh_days,
                )
            except Exception as e:
                if 'ineffective' in str(e):
                    bucket_name = (
                        bucket_name_for_construct.replace('JTURBO', 'JULO')
                        if is_merge_jturbo
                        else bucket_name_for_construct
                    )
                    write_not_sent_to_dialer_async.delay(
                        bucket_name=bucket_name,
                        reason=ReasonNotSentToDialer.UNSENT_REASON[
                            'INEFFECTIVE_PHONE_NUMBER'
                        ].strip("'"),
                        account_payment_ids=[item.account_payment_id],
                        dialer_task_id=dialer_task.id,
                    )
                    continue
                get_julo_sentry_client().captureException()
                logger.error({'action': fn_name, 'state': 'payload generation', 'error': str(e)})
                continue

            formated_ai_rudder_payload.append(formatted_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info({
                    'action': fn_name,
                    'identifier': identifier,
                    'state': 'bulk_create',
                    'counter': counter,
                })
                AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formated_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formated_ai_rudder_payload:
            processed_data_count += counter
            logger.info({
                'action': fn_name,
                'identifier': identifier,
                'state': 'bulk_create_last_part',
                'counter': counter,
            })
            AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)

        # update sort order for B3 and B4
        lower_bucket_name = bucket_name.lower()
        if ('julo_b4' in lower_bucket_name) and populated_dialer_call_data:
            payload_datas = AIRudderPayloadTemp.objects.filter(bucket_name=bucket_name).order_by(
                '-tanggal_jatuh_tempo', '-total_outstanding'
            )
            sort_rank = 1
            for payload_data in payload_datas:
                payload_data.sort_order = sort_rank
                sort_rank += 1
            bulk_update(payload_datas, update_fields=['sort_order'], batch_size=500)

        if not processed_data_count:
            raise Exception("error when construct the data")

        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'constructed',
        })
        return processed_data_count

    def get_group_name_by_bucket(self, bucket_name: str):
        group_name_mapping = {
            DialerSystemConst.DIALER_BUCKET_3: 'Group_Bucket3',
            DialerSystemConst.DIALER_BUCKET_3_NC: 'Group_Bucket3',
        }
        feature_group_mapping_config = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_GROUP_NAME_CONFIG, is_active=True).last()

        if feature_group_mapping_config:
            group_name_mapping = feature_group_mapping_config.parameters

        return group_name_mapping.get(bucket_name, None)

    def create_new_task(
            self, bucket_name: str, ai_rudder_payload_ids: List[int], page_number: int = 0,
            callback_url: str = "{}/api/minisquad/airudder/webhooks".format(settings.BASE_URL)
    ):
        fn_name = 'AIRudderPDSServices.create_new_task'
        current_time = timezone.localtime(timezone.now())
        task_name = "{}-{}".format(bucket_name, current_time.strftime('%Y%m%d-%H%M'))
        setting_env = settings.ENVIRONMENT.upper()
        if setting_env != 'PROD':
            task_name = "{}-{}".format(setting_env, task_name)

        if page_number:
            task_name = '{}-{}'.format(task_name, page_number)

        group_name = self.get_group_name_by_bucket(bucket_name)
        if not group_name:
            raise Exception('Group name for bucket {} is not configure yet'.format(bucket_name))

        data_to_call = (
            AIRudderPayloadTemp.objects.filter(pk__in=ai_rudder_payload_ids)
            .order_by('sort_order')
            .values(
                'account_payment_id',
                'account_id',
                'customer_id',
                'phonenumber',
                'nama_customer',
                'nama_perusahaan',
                'posisi_karyawan',
                'dpd',
                'total_denda',
                'potensi_cashback',
                'total_seluruh_perolehan_cashback',
                'total_due_amount',
                'total_outstanding',
                'angsuran_ke',
                'tanggal_jatuh_tempo',
                'nama_pasangan',
                'nama_kerabat',
                'hubungan_kerabat',
                'alamat',
                'kota',
                'jenis_kelamin',
                'tgl_lahir',
                'tgl_gajian',
                'tujuan_pinjaman',
                'tgl_upload',
                'va_bca',
                'va_permata',
                'va_maybank',
                'va_alfamart',
                'va_indomaret',
                'va_mandiri',
                'tipe_produk',
                'last_pay_date',
                'last_pay_amount',
                'partner_name',
                'last_agent',
                'last_call_status',
                'refinancing_status',
                'activation_amount',
                'program_expiry_date',
                'customer_bucket_type',
                'promo_untuk_customer',
                'zip_code',
                'mobile_phone_2',
                'telp_perusahaan',
                'mobile_phone_1_2',
                'mobile_phone_2_2',
                'no_telp_pasangan',
                'mobile_phone_1_3',
                'mobile_phone_2_3',
                'no_telp_kerabat',
                'mobile_phone_1_4',
                'mobile_phone_2_4',
                'angsuran_per_bulan',
                'uninstall_indicator',
                'fdc_risky',
                'risk_score',
                'status_refinancing_lain',
                'other_numbers',
                'unpaid_loan_account_details',
            )
            .exclude(account_payment__due_amount=0)
            .order_by('sort_order')
        )
        if not data_to_call:
            raise Exception('Data not exists yet for {} {}'.format(bucket_name, page_number))
        # since ai rudder only accept string value then we need convert all of int value like
        # account_payment_id to str
        integer_fields = [
            'account_payment_id', 'account_id', 'customer_id', 'dpd', 'total_denda',
            'potensi_cashback', 'total_seluruh_perolehan_cashback', 'total_due_amount', 'total_outstanding', 'angsuran_ke',
            'tipe_produk', 'last_pay_amount', 'activation_amount', 'zip_code', 'angsuran_per_bulan',
        ]
        array_fields = ['other_numbers']
        # Convert integer fields to strings
        converted_data = []
        for item in data_to_call:
            converted_item = {field: str(value) for field, value in item.items() if
                              field in integer_fields}
            converted_item.update(
                {
                    field: value
                    for field, value in item.items()
                    if field not in integer_fields and field not in array_fields
                }
            )
            other_numbers = item.get('other_numbers', [])
            if other_numbers:
                index = 1
                field_name = 'new_phone_number_{}'
                for number in other_numbers:
                    converted_item.update({field_name.format(index): number})
                    index += 1
            converted_data.append(converted_item)

        strategy_config = {}
        feature_group_mapping_config = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True).last()
        if feature_group_mapping_config:
            parameter = feature_group_mapping_config.parameters
            strategy_config = parameter.get(bucket_name, {})

        raw_start_time_config = strategy_config.get('start_time', '')
        '''
            For this experiment we need to handle start time to blank because we need start
            theh call after previous page finished. So we need to set the start time to blank
        '''
        es_sort_phonenumber_v2 = get_experiment_setting_by_code(
            ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
        )
        if es_sort_phonenumber_v2 and page_number > 1:
            experiment_bucket_list = es_sort_phonenumber_v2.criteria["experiment_bucket_list"]
            experiment_bucket_list = list(experiment_bucket_list.values())
            if bucket_name in experiment_bucket_list:
                raw_start_time_config = ''

        start_time_config = (
            raw_start_time_config.split(':') if raw_start_time_config else raw_start_time_config
        )
        end_time_config = strategy_config.get('end_time', '20:0').split(':')
        start_time = (
            start_time_config
            if not start_time_config
            else timezone.localtime(timezone.now()).replace(
                hour=int(start_time_config[0]), minute=int(start_time_config[1]), second=0
            )
        )
        end_time = timezone.localtime(
            timezone.now()).replace(
            hour=int(end_time_config[0]), minute=int(end_time_config[1]), second=0)
        rest_times = strategy_config.get('rest_times', [['12:00', '13:00']])
        formated_rest_times = []
        for rest_time in rest_times:
            formated_rest_times.append(
                {
                    "start": "{}:00".format(rest_time[0]),
                    "end": "{}:00".format(rest_time[1])
                }
            )
        strategy_config['restTimes'] = formated_rest_times
        if int(strategy_config.get('autoSlotFactor', 0)) == 0:
            strategy_config['slotFactor'] = strategy_config.get('slotFactor', 2.5)

        if not strategy_config.get('autoQA', ''):
            strategy_config['autoQA'] = 'Y'
            strategy_config['qaConfigId'] = 142

        if callback_url:
            encoded_bytes = base64.b64encode(callback_url.encode('utf-8'))
            callback_url = encoded_bytes.decode('utf-8')

        strategy_config['qaLimitLength'] = strategy_config.get('qaLimitLength', 0)
        strategy_config['qaLimitRate'] = strategy_config.get('qaLimitRate', 100)

        response = self.AI_RUDDER_PDS_CLIENT.create_task(
            task_name, start_time, end_time,
            group_name=group_name, list_contact_to_call=converted_data,
            strategy_config=strategy_config, call_back_url=callback_url)

        response_body = response.get('body')
        if not response_body:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response)))

        tasks_id = response_body.get("taskId")
        if not tasks_id:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response_body)))

        return tasks_id, data_to_call.values_list('account_payment_id', flat=True)

    def update_task_id_on_sent_to_dialer(
            self, bucket_name: str, account_payment_ids: List[int], task_id: str):
        fn_name = 'AIRudderPDSServices.update_task_id_on_sent_to_dialer'
        data = SentToDialer.objects.filter(
            bucket=bucket_name,
            account_payment_id__in=account_payment_ids,
            cdate__date=timezone.localtime(timezone.now()).date(),
            dialer_task__vendor=DialerSystemConst.AI_RUDDER_PDS,)
        if not data.exists():
            raise Exception(
                "{} fail because data that need update not exists on sent to dialer".format(
                    fn_name)
            )

        data.update(task_id=task_id)

    def crud_strategy_configuration(self, operation: str, bucket_name: str, data_to_save={}):
        feature_group_mapping_config = FeatureSetting.objects.get(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG)
        message = ''
        param = feature_group_mapping_config.parameters
        if operation == 'delete':
            if bucket_name in param:
                del param[bucket_name]
                message = 'berhasil menghapus {}'.format(bucket_name)
            else:
                raise Exception("bucket {} not exists in current configuration".format(bucket_name))
        elif operation in ('edit', 'add'):
            param[bucket_name] = data_to_save
            message = 'berhasil {} {}'.format(operation, bucket_name)
        else:
            raise Exception("Cannot handle other operation")

        feature_group_mapping_config.parameters = param
        feature_group_mapping_config.save()
        return True, message

    @transaction.atomic
    def store_call_result_agent(self, callback_data, task_name=None):
        from juloserver.minisquad.services2.airudder import format_ptp_date
        from juloserver.minisquad.tasks2 import delete_connected_call_from_dialer

        # adding cancel call connected
        fn_name = 'store_call_result_agent'
        logger.info(
            {
                'function_name': fn_name,
                'message': 'Start running store_call_result_agent',
            }
        )

        callback_type = callback_data['type']
        callback_body = callback_data['body']
        customer_info = callback_body.get('customerInfo', {})
        customize_res = callback_body.get('customizeResults', {})

        phone_number = callback_body.get('phoneNumber', '')
        if phone_number == '':
            errMsg = "Phone number not valid, please provide valid phone number!"
            logger.error({ 'function_name': fn_name, 'message': errMsg })

            return False, errMsg

        used_model_dictionary = self.determine_used_model_by_task(task_name)
        skiptrace_history_model = used_model_dictionary.get('skiptrace_history')

        agent_user = None
        spoke_with, non_payment_reason = None, None
        if callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE:
            spoke_with = customize_res.get('Spokewith', None)
            non_payment_reason = (
                customize_res.get('Nopaymentreason', '')
                or customize_res.get('nopaymentreason', '')
                or customize_res.get('no_payment_reason', '')
            )

            non_payment_reason = non_payment_reason.replace('_', ' ')

            agent_name = callback_body.get('agentName', None)
            agent_user = User.objects.filter(username=agent_name).last()

            if not agent_user:
                errMsg = "Agent name not valid, please provide valid agent name"
                logger.error({'function_name': fn_name, 'message': errMsg})

                return False, errMsg

            CuserMiddleware.set_user(agent_user)

        account_id = customer_info.get('account_id', None)
        account = Account.objects.filter(id=account_id).last()
        if not account:
            errMsg = "account_id is not valid"
            logger.error({ 'function_name': fn_name, 'message': errMsg })

            return False, errMsg

        acc_payment_id = customer_info.get('account_payment_id')
        acc_payment = account.accountpayment_set.filter(id=acc_payment_id).last()
        if not acc_payment:
            errMsg = "account_payment_id is not valid"
            logger.error({ 'function_name': fn_name, 'message': errMsg })

            return False, errMsg

        customer = account.customer
        application = account.customer.application_set.last()

        # with transaction.atomic():
        phone_number = format_e164_indo_phone_number(phone_number)
        skiptrace = Skiptrace.objects.filter(
            phone_number=phone_number,
            customer_id=customer.id
        ).last()
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=phone_number,
                customer_id=customer.id,
                contact_source=callback_body.get('phoneTag', '')
            )

        ptp_notes = ''
        ptp_amount = customize_res.get('PTP Amount', '')
        ptp_date = format_ptp_date(customize_res.get('PTP Date', ''))
        if ptp_amount != '' and ptp_date != '':
            ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
            acc_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
            ptp_create_v2(acc_payment, ptp_date, ptp_amount, agent_user, True, False)

        hangup_reason = callback_body.get('hangupReason', None)
        construct_status_data = hangup_reason if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else customize_res
        status, status_group = airudder_construct_status_and_status_group(
            callback_type, construct_status_data, True, hangup_reason
        )

        identifier = status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
        is_identifier_exist = identifier != ''

        filter_identifier = identifier if is_identifier_exist else 'NULL'
        skiptrace_res_choice = SkiptraceResultChoice.objects.filter(name=filter_identifier).last()
        if not skiptrace_res_choice:
            errMsg = "Call status not valid"
            logger.error({ 'function_name': fn_name, 'message': errMsg })

            return False, errMsg

        call_id = callback_body.get('callid', None)
        task_id = callback_body.get('taskId', None)
        current_date_time = timezone.localtime(timezone.now())
        current_time = current_date_time.time()

        es_sort_phonenumber = get_experiment_setting_by_code(
            ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_EXPERIMENT
        )
        es_sort_phonenumber_v2 = get_experiment_setting_by_code(
            ExperimentConst.COLLECTION_SORT_CALL_PRIORITY_V2_EXPERIMENT
        )
        if skiptrace_res_choice.name not in AiRudder.NOT_CONNECTED_CALL_STATUS_LIST and (
            es_sort_phonenumber or es_sort_phonenumber_v2
        ):
            finish_call_time = time(21, 0)
            if not current_time >= finish_call_time or settings.ENVIRONMENT != 'prod':
                delete_connected_call_from_dialer.delay(account_id)

        skiptrace_history_data = dict(
            start_ts=datetime(1970, 1, 1),
            skiptrace_id=skiptrace.id,
            payment_id=None,
            payment_status=None,
            loan_id=None,
            loan_status=None,
            application_id=application.id,
            application_status=application.status,
            account_id=account_id,
            account_payment_id=acc_payment_id,
            account_payment_status_id=acc_payment.status_id,
            agent_id=agent_user.id if agent_user else None,
            agent_name=agent_user.username if agent_user else None,
            notes=callback_body.get('talkremarks', None),
            non_payment_reason=non_payment_reason if 'RPC' in filter_identifier else '',
            spoke_with=spoke_with,
            status_group=status_group,
            status=status,
            source=AiRudder.AI_RUDDER_SOURCE,
            call_result=skiptrace_res_choice,
            external_unique_identifier=call_id,
            external_task_identifier=task_id,
        )

        stateKey = 'state' if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else 'State'
        state = callback_body.get(stateKey, None)
        timestamp = callback_body.get('timestamp', None)
        timestamp_datetime = datetime.fromtimestamp(int(timestamp) / 1000.0) if timestamp else None

        start_ts, end_ts = None, None
        if state and timestamp:
            if state in AiRudder.START_TS_STATE:
                start_ts = timestamp_datetime
                skiptrace_history_data['start_ts'] = start_ts
            if state in AiRudder.END_TS_STATE:
                end_ts = timestamp_datetime
                skiptrace_history_data['end_ts'] = end_ts

        if not is_identifier_exist:
            del skiptrace_history_data['status']
            del skiptrace_history_data['status_group']
            del skiptrace_history_data['non_payment_reason']
            del skiptrace_history_data['spoke_with']
            del skiptrace_history_data['notes']

        if skiptrace_history_model is CollectionRiskSkiptraceHistory:
            skiptrace_history_data.pop('application_status', None)
            skiptrace_history_data.pop('loan_id', None)
            skiptrace_history_data.pop('loan_status', None)
            skiptrace_history_data.pop('payment_id', None)

        try:
            with transaction.atomic():
                skiptrace_history = skiptrace_history_model.objects.create(**skiptrace_history_data)
        except IntegrityError:
            skiptrace_history = skiptrace_history_model.objects.get_or_none(
                external_unique_identifier=call_id)

            skiptrace_history_data.pop('skiptrace_id', None)
            skiptrace_history_data.pop('payment_id', None)
            skiptrace_history_data.pop('payment_status', None)
            skiptrace_history_data.pop('loan_id', None)
            skiptrace_history_data.pop('loan_status', None)
            skiptrace_history_data.pop('application_id', None)
            skiptrace_history_data.pop('application_status', None)
            skiptrace_history_data.pop('account_id', None)
            skiptrace_history_data.pop('account_payment_id', None)
            skiptrace_history_data.pop('account_payment_status_id', None)
            skiptrace_history_data.pop('source', None)
            skiptrace_history_data.pop('external_unique_identifier', None)
            skiptrace_history_data.pop('external_task_identifier', None)

            if start_ts == None:
                skiptrace_history_data.pop('start_ts', None)

            utc = pytz.UTC
            new_end_ts = timestamp_datetime.replace(tzinfo=utc)

            is_update = False
            if skiptrace_history.end_ts != None:
                curr_end_ts = skiptrace_history.end_ts.replace(tzinfo=utc)
                is_update = new_end_ts > curr_end_ts
            else:
                is_update = True

            if is_update:
                if (
                    skiptrace_history.call_result.name not in ['ACW - Interrupt', 'NULL']
                    or skiptrace_res_choice.name == 'NULL'
                ):
                    del skiptrace_history_data['call_result']

                skiptrace_history.update_safely(**skiptrace_history_data)

        skiptrace_notes = callback_body.get('talkremarks', None)
        call_log_poc_model = used_model_dictionary.get('call_log_poc')
        if skiptrace_notes or ptp_notes:
            is_acc_payment_note_exist = call_log_poc_model.objects.filter(call_id=call_id, talk_remarks__isnull=False) \
                .exclude(talk_remarks__exact='') \
                .exists()
            if not is_acc_payment_note_exist:
                contact_source = callback_body.get('phoneTag', '') or skiptrace.contact_source
                AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    account_payment=acc_payment,
                    added_by=agent_user,
                    extra_data={
                        "call_note": {
                            "contact_source": contact_source,
                            "phone_number": phone_number,
                            "call_result": status,
                            "spoke_with": spoke_with,
                            "non_payment_reason": non_payment_reason,
                        }
                    }
                )

        task_name = callback_body.get('taskName', None)
        call_log_data = {
            'skiptrace_history': skiptrace_history,
            'call_log_type': callback_type,
            'task_id': callback_body.get('taskId', None),
            'task_name': task_name,
            'group_name': callback_body.get('groupName', None),
            'state': state,
            'phone_number': masking_phone_number_value(phone_number),
            'call_id': call_id,
            'contact_name': callback_body.get('contactName', None),
            'address': callback_body.get('address', None),
            'info_1': callback_body.get('info1', None),
            'info_2': callback_body.get('info2', None),
            'info_3': callback_body.get('info3', None),
            'remark': callback_body.get('remark', None),
            'main_number': masking_phone_number_value(callback_body.get('mainNumber', None)),
            'phone_tag': callback_body.get('phoneTag', '') or skiptrace.contact_source,
            'private_data': callback_body.get('privateData', None),
            'timestamp': timestamp_datetime,
            'recording_link': callback_body.get('recLink', None),
            'talk_remarks': skiptrace_notes,
            'nth_call': callback_body.get('nthCall', None),
            'hangup_reason': hangup_reason,
        }

        call_log_poc_model.objects.create(**call_log_data)

        if state == AiRudder.STATE_TALKRESULT and \
            callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE:
            vendor_recording_detail = VendorRecordingDetail.objects.filter(
                unique_call_id=call_id).last()
            if vendor_recording_detail:
                vendor_recording_detail.update_safely(
                    call_status=skiptrace_history.call_result)

        if type(skiptrace_history) is CollectionRiskSkiptraceHistory:
            update_collection_risk_verification_call_list(skiptrace_history)

        if skiptrace_res_choice.name in IntelixResultChoiceMapping.CONNECTED_STATUS and (
            'dana' not in task_name and 'grab' not in task_name
        ):
            AIRudderPayloadTemp.objects.filter(account_payment_id=acc_payment_id).delete()
            agent_assignment = ManualDCAgentAssignment.objects.filter(
                account_id=account_id,
                is_eligible=True,
            ).last()
            if agent_assignment:
                removal_notes = 'Connected Call : %s' % current_date_time.strftime("%d-%m-%Y")
                assignment_notes = (
                    agent_assignment.assignment_notes + '\n' + removal_notes
                    if agent_assignment.assignment_notes
                    else removal_notes
                )
                agent_assignment.update_safely(assignment_notes=assignment_notes, is_eligible=False)

        logger.info(
            {
                'function_name': fn_name,
                'message': 'Success process store_call_result_agent',
            }
        )

        return True, 'success'


    def recon_store_call_result(self, task_id, call_id, task_name=None):
        logger.info(
            {
                'function_name': 'recon_store_call_result',
                'message': 'Start running recon_store_call_result',
            }
        )

        response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(task_id, call_id)
        body = response.get('body', None)
        if not body:
            raise ValueError('')

        list_data = body.get('list', None)
        if not list_data:
            raise ValueError('')

        data = list_data[0]
        used_model_dictionary = self.determine_used_model_by_task(task_name)
        skiptrace_history_model = used_model_dictionary.get('skiptrace_history')
        skiptrace_history = skiptrace_history_model.objects.get(external_unique_identifier=call_id)

        datetime_format = '%Y-%m-%dT%H:%M:%S%z'
        start_ts = datetime.strptime(data.get('calltime', ''), datetime_format)

        update_date = {'start_ts': start_ts}
        skiptrace_history.update_safely(**update_date)

        hangup_reason_id = data.get('hangupReason')
        if hangup_reason_id and hangup_reason_id >= 0:
            # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
            # execute on final state agent level
            self.write_hangup_reason(skiptrace_history.id, hangup_reason_id, task_name=task_name)
            end_time = skiptrace_history.end_ts.date()
            self.count_ineffective_phone_number(
                skiptrace_history.skiptrace_id, hangup_reason_id, end_time, task_name
            )
        # function download recording move to sync up hourly
        # make sure final state and try to update
        if type(skiptrace_history) is CollectionRiskSkiptraceHistory:
            update_collection_risk_verification_call_list(skiptrace_history)
        logger.info(
            {
                'function_name': 'recon_store_call_result',
                'message': 'Finish running recon_store_call_result',
                'call_id': call_id,
            }
        )

    def write_hangup_reason(self, skiptrace_history_id, hangup_reason_id, task_name=None):
        reason = AiRudder.HANGUP_REASON_PDS.get(hangup_reason_id)
        used_model_dictionary = self.determine_used_model_by_task(task_name)
        hangup_pds_model = used_model_dictionary.get('hangup_pds')
        if hangup_pds_model.objects.filter(
            hangup_reason=hangup_reason_id, skiptrace_history_id=skiptrace_history_id
        ).exists():
            return

        data_to_insert = {
            'hangup_reason': hangup_reason_id,
            'reason': reason,
            'skiptrace_history_id': skiptrace_history_id,
        }
        hangup_pds_model.objects.create(**data_to_insert)

    def write_skiptrace_history_pds_detail(self, skiptrace_history_id, data):
        if SkiptraceHistoryPDSDetail.objects.filter(
            skiptrace_history_id=skiptrace_history_id,
        ).exists():
            return

        data_to_insert = {
            'skiptrace_history_id': skiptrace_history_id,
            'call_result_type': data.get('talk_results_type'),
            'nth_call': data.get('nth_call'),
            'ringtime': data.get('ringtime_ts'),
            'answertime': data.get('answertime_ts'),
            'talktime': data.get('talktime_ts'),
            'customize_results': data.get('customizeResults'),
        }

        SkiptraceHistoryPDSDetail.objects.create(**data_to_insert)

    def process_construction_data_for_dialer_bucket_0(
            self, bucket_name: str, retries_times: int, dialer_task: Any) -> int:
        from juloserver.cootek.services import (
            get_j1_account_payment_for_cootek,
            get_jturbo_account_payment_for_cootek,
        )
        from juloserver.minisquad.tasks2.dialer_system_task import (
            trigger_construct_call_data_bucket_current_bttc,
        )
        from juloserver.minisquad.tasks2 import write_not_sent_to_dialer_async

        fn_name = 'process_construction_data_for_dialer_bucket_0'
        identifier = 'construct_{}_retries_{}'.format(bucket_name, retries_times)
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'querying'
        })
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERYING))

        today = timezone.localtime(timezone.now()).date()
        filter_dict = dict(due_date=today)
        account_payment_qs = None
        regex_pattern = r'JTURBO'
        if re.search(regex_pattern, bucket_name):
            # handle jturbo
            account_payment_qs = get_jturbo_account_payment_for_cootek(filter_dict)
        else:
            account_payment_qs = get_j1_account_payment_for_cootek(filter_dict)

        account_payment_qs = account_payment_qs.exclude(due_amount=0)

        data_count = account_payment_qs.count()
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'queried',
            'total_data': data_count
        })
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.QUERIED,
                 data_count=data_count))
        if not data_count:
            raise Exception("Not Found data for bucket {} and dpd {}".format(bucket_name, 0))

        account_payment_qs = account_payment_qs.select_related(
            'account', 'account__customer'
        ).prefetch_related('account__customer__application_set', 'ptp_set')
        account_ids = set(account_payment_qs.values_list('account_id', flat=True))
        exclude_data_dict = {
            item[0]: item[1] for item in account_payment_qs.values_list('account_id', 'id')
        }
        black_list_account_payment_ids = set()
        autodebet_account_payment_ids = set()

        intelix_blacklist_account_ids = set(
            get_exclude_account_ids_by_intelix_blacklist_improved(account_ids)
        )
        if intelix_blacklist_account_ids:
            black_list_account_payment_ids = [
                exclude_data_dict.get(account_id) for account_id in intelix_blacklist_account_ids
            ]
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON[
                    'USER_REQUESTED_DIALER_SERVICE_REMOVAL'
                ].strip("'"),
                account_payment_ids=black_list_account_payment_ids,
                dialer_task_id=dialer_task.id,
            )

        # remove account that already detected as intelix blacklist
        account_ids = account_ids.difference(intelix_blacklist_account_ids)
        autodebet_account_ids = set(
            get_turned_on_autodebet_customer_exclude_for_dpd_plus_improved(
                account_ids, for_dpd='dpd_zero'
            )
        )
        if autodebet_account_ids:
            autodebet_account_payment_ids = [
                exclude_data_dict.get(account_id) for account_id in autodebet_account_ids
            ]
            write_not_sent_to_dialer_async.delay(
                bucket_name=bucket_name,
                reason=ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET'].strip("'"),
                account_payment_ids=autodebet_account_payment_ids,
                dialer_task_id=dialer_task.id,
            )

        not_eligible_account_payment_ids = set(black_list_account_payment_ids) | set(
            autodebet_account_payment_ids
        )
        account_payment_qs = account_payment_qs.exclude(pk__in=not_eligible_account_payment_ids)

        if not account_payment_qs:
            raise Exception("No Account Payments")

        merge_j1_jturbo_bucket_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT,
            is_active=True,
        ).last()
        is_merge_jturbo = False
        if merge_j1_jturbo_bucket_fs:
            eligible_bucket_numbers_to_merge = merge_j1_jturbo_bucket_fs.parameters.get(
                'bucket_numbers_to_merge', []
            )
            if 0 in eligible_bucket_numbers_to_merge:
                is_merge_jturbo = True

        # bathing data creation prevent full memory
        batch_size = 1000
        counter = 0
        processed_data_count = 0
        formated_ai_rudder_payload = []
        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'constructing',
        })
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTING)
        )

        omnichannel_exclusion_request = get_omnichannel_comms_block_active(
            OmnichannelIntegrationSetting.CommsType.PDS
        )

        # bttc experiment
        bucket_name_lower = bucket_name.lower()
        bttc_experiment = get_experiment_setting_by_code(ExperimentConst.BTTC_EXPERIMENT)
        if bttc_experiment:
            bucket_number = extract_bucket_number(bucket_name)
            bttc_bucket_numbers = bttc_experiment.criteria.get('bttc_bucket_numbers', [])
            if bucket_number in bttc_bucket_numbers:
                account_payment_ids = list(account_payment_qs.values_list('pk', flat=True))
                trigger_construct_call_data_bucket_current_bttc.delay(
                    bucket_name, bttc_experiment.id, account_payment_ids, is_t0=True
                )
                raise Exception("All current data handled by bttc")

        # check ineffective number
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()
        params = fs.parameters if fs else {}
        param_per_bucket = params.get(bucket_name, {})
        consecutive_days = param_per_bucket.get('consecutive_days', 0)
        ineffective_refresh_days = (
            param_per_bucket.get('threshold_refresh_days')
            if param_per_bucket.get('is_ineffective_refresh', False)
            else 0
        )
        for account_payment in account_payment_qs:
            if omnichannel_exclusion_request.is_excluded and is_omnichannel_account(
                exclusion_req=omnichannel_exclusion_request, account_id=account_payment.account_id
            ):
                write_not_sent_to_dialer_async.delay(
                    bucket_name=bucket_name,
                    reason=ReasonNotSentToDialer.UNSENT_REASON['OMNICHANNEL_EXCLUSION'].strip("'"),
                    account_payment_ids=[account_payment.id],
                    dialer_task_id=dialer_task.id,
                )
                continue
            try:
                formatted_data = self.construct_payload(
                    account_payment,
                    bucket_name,
                    is_jturbo_merge=is_merge_jturbo,
                    ineffective_consecutive_days=consecutive_days,
                    ineffective_refresh_days=ineffective_refresh_days,
                )
            except Exception as e:
                if 'ineffective' in str(e):
                    bucket_name = (
                        bucket_name.replace('JTURBO', 'JULO') if is_merge_jturbo else bucket_name
                    )
                    write_not_sent_to_dialer_async.delay(
                        bucket_name=bucket_name,
                        reason=ReasonNotSentToDialer.UNSENT_REASON[
                            'INEFFECTIVE_PHONE_NUMBER'
                        ].strip("'"),
                        account_payment_ids=[account_payment.id],
                        dialer_task_id=dialer_task.id,
                    )
                    continue
                logger.error({
                    'action': fn_name,
                    'account_payment_id': account_payment.id,
                    'state': 'payload generation',
                    'error': str(e)
                })
                get_julo_sentry_client().captureException()
                continue
            formated_ai_rudder_payload.append(formatted_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formated_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formated_ai_rudder_payload:
            processed_data_count += counter
            AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)

        if not processed_data_count:
            raise Exception("error when construct the data")

        logger.info({
            'action': fn_name,
            'identifier': identifier,
            'state': 'constructed',
        })
        record_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED,
                 data_count=processed_data_count))
        return processed_data_count

    def delete_airudder_payload_temp_t0(self, airudder_payload_ids):
        # this funtion to delete data on airudder temp payload
        # since unused anymore, because we not sent anymore to airudder
        # especially for good intentions, autodebet and intelix blacklist
        list_to_be_delete = AIRudderPayloadTemp.objects.filter(
            id__in=airudder_payload_ids)
        if not list_to_be_delete.exists():
            logger.info({
                'action': 'delete_airudder_payload_temp_t0',
                'info': "there's no data to be delete",
            })
            return

        list_to_be_delete.delete()

    def j1_get_task_ids_dialer(self, date: datetime, retries_time: int = 0):
        # Get the start of the day (midnight)
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        # Get the end of the day (just before midnight)
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)

        tasks_id_and_name = self.get_list_of_task_id_and_task_name_with_date_range(
            start_time=start_of_day, end_time=end_of_day, retries_time=retries_time)
        j1_filtered_tasks = []
        for task in tasks_id_and_name:
            task_name = task['task_name'].lower()
            if 'dana' in task_name or 'grab' in task_name:
                continue
            j1_filtered_tasks.append(task)
        return j1_filtered_tasks

    def create_new_task_for_grab(
            self, bucket_name, batch_num, data_to_send,
            callback_url: str = "{}/api/minisquad/grab/airudder/webhooks".format(settings.BASE_URL)):
        total_uploaded_data = 0
        fn_name = 'AIRudderPDSServices.create_new_task_for_grab'
        current_time = timezone.localtime(timezone.now())
        task_name = "{}-{}".format(bucket_name, current_time.strftime('%Y%m%d-%H%M'))
        setting_env = settings.ENVIRONMENT.upper()
        if setting_env != 'PROD':
            task_name = "{}-{}".format(setting_env, task_name)

        if batch_num:
            task_name = '{}-{}'.format(task_name, batch_num)

        logger.info({
            'action': 'upload_grab_data',
            'message': 'before hit upload queue ai rudder API for grab data',
            'total_data_to_send': len(data_to_send)
        })

        group_name = self.get_group_name_by_bucket(bucket_name)
        if not group_name:
            logger.exception({
                'action': fn_name,
                'message': 'Group name for bucket {} is not configure yet'.format(bucket_name)
            })
            return '', total_uploaded_data

        strategy_config = {}
        feature_group_mapping_config = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True).last()
        if feature_group_mapping_config:
            parameter = feature_group_mapping_config.parameters
            strategy_config = parameter.get(bucket_name, {})

        start_time_config = strategy_config.get('start_time', '8:0').split(':')
        end_time_config = strategy_config.get('end_time', '20:0').split(':')
        start_time = timezone.localtime(timezone.now()).replace(
            hour=int(start_time_config[0]), minute=int(start_time_config[1]), second=0)
        end_time = timezone.localtime(
            timezone.now()).replace(
            hour=int(end_time_config[0]), minute=int(end_time_config[1]), second=0)
        rest_times = strategy_config.get('rest_times', [['12:00', '13:00']])
        formated_rest_times = []
        for rest_time in rest_times:
            formated_rest_times.append(
                {
                    "start": "{}:00".format(rest_time[0]),
                    "end": "{}:00".format(rest_time[1])
                }
            )
        strategy_config['restTimes'] = formated_rest_times
        if not int(strategy_config.get('autoSlotFactor', 0)):
            strategy_config['slotFactor'] = strategy_config.get('slotFactor', 2.5)

        if not strategy_config.get('autoQA'):
            strategy_config['autoQA'] = 'Y'
            strategy_config['qaConfigId'] = 142

        if callback_url:
            encoded_bytes = base64.b64encode(callback_url.encode('utf-8'))
            callback_url = encoded_bytes.decode('utf-8')

        response = self.AI_RUDDER_PDS_CLIENT.create_task(
            task_name, start_time, end_time,
            group_name=group_name, list_contact_to_call=data_to_send,
            strategy_config=strategy_config, call_back_url=callback_url,
            partner_name=AiRudder.GRAB)
        response_body = response.get('body')
        if not response_body:
            logger.exception({
                'action': fn_name,
                'message': 'failed to upload grab data to ai rudder',
                # 'response_status': response.status_code,
                'response': str(response)
            })
            return '', total_uploaded_data

        tasks_id = response_body.get("taskId")
        if not tasks_id:
            logger.exception({
                'action': fn_name,
                'message': 'failed to upload grab data to ai rudder.',
                'response': str(response_body)
            })
            return '', total_uploaded_data

        return tasks_id, len(data_to_send)

    def update_grab_task_id_on_sent_to_dialer(
            self, bucket_name: str, account_ids: List[int], dialer_task_id: str, task_id: str
    ):
        fn_name = 'AIRudderPDSServices.update_grab_task_id_on_sent_to_dialer'
        current_time = timezone.localtime(timezone.now())
        today_min = datetime.combine(current_time, time.min)
        today_max = datetime.combine(current_time, time.max)
        data = SentToDialer.objects.filter(
            bucket=bucket_name,
            account_id__in=account_ids,
            cdate__range=(today_min, today_max),
            dialer_task_id=dialer_task_id
        )
        if data:
            data.update(task_id=task_id)
        else:
            logger.exception({
                'action': fn_name,
                'message': "failed because data that need update not exists on sent to dialer"
            })

    def get_task_ids_from_sent_to_dialer(self, bucket_list: List,
                                         date: datetime, redis_key: str,
                                         sync_t0: bool = False):
        # sync_t0 parameter for sync task id especially for T0 bucket
        # since we sent it at noon
        # Get the start of the day (midnight)
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        # Get the end of the day (just before midnight)
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        redis_client = get_redis_client()
        task_id_list = redis_client.get_list(redis_key)
        if sync_t0 or not task_id_list:
            task_id_list = list(SentToDialer.objects.filter(
                task_id__isnull=False,
                cdate__range=(start_of_day, end_of_day),
                bucket__in=bucket_list
            ).distinct('task_id').values_list('task_id', flat=True))
            if sync_t0:
                redis_client.delete_key(redis_key)
            redis_client.set_list(redis_key, task_id_list, timedelta(hours=12))
            return task_id_list

        return [item.decode("utf-8") for item in task_id_list]

    def construct_skiptrace_history_data(self, callback_data):
        from juloserver.minisquad.services2.airudder import format_ptp_date
        data = {}
        fn_name = 'grab_store_call_result_agent - construct_skiptrace_history_data'
        logger.info({
            'function_name': fn_name,
            'message': 'Start running grab_store_call_result_agent',
        })

        callback_type = callback_data['type']
        callback_body = callback_data['body']
        customer_info = callback_body.get('customerInfo', {})
        customize_res = callback_body.get('customizeResults', {})

        phone_number = callback_body.get('phoneNumber', '')
        if phone_number == '':
            errMsg = "Phone number not valid, please provide valid phone number!"
            logger.error({'function_name': fn_name, 'message': errMsg})

            return False, errMsg, data

        agent_user = None
        spoke_with, non_payment_reason = None, None
        if callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE:
            spoke_with = customize_res.get('Spokewith', None)
            non_payment_reason = customize_res.get('Nopaymentreason', None)

            agent_name = callback_body.get('agentName', None)
            agent_user = User.objects.filter(username=agent_name).last()

            if not agent_user:
                errMsg = "Agent name not valid, please provide valid agent name"
                logger.error({'function_name': fn_name, 'message': errMsg})

                return False, errMsg, data

            CuserMiddleware.set_user(agent_user)

        account_id = customer_info.get('account_id', None)
        account = Account.objects.filter(id=account_id).last()
        if not account:
            errMsg = "account_id is not valid"
            logger.error({'function_name': fn_name, 'message': errMsg})

            return False, errMsg, data

        acc_payment_id = customer_info.get('account_payment_id')
        acc_payment = None
        if acc_payment_id:
            acc_payment = (account.accountpayment_set.not_paid_active().
                           order_by('-id').filter(id=acc_payment_id).last())
        else:
            acc_payment = (account.accountpayment_set.not_paid_active().
                           order_by('-id').last())

        customer = account.customer
        application = account.customer.application_set.last()

        # with transaction.atomic():
        phone_number = format_e164_indo_phone_number(phone_number)
        skiptrace = Skiptrace.objects.filter(
            phone_number=phone_number,
            customer_id=customer.id
        ).last()
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=phone_number,
                customer_id=customer.id,
                contact_source=callback_body.get('phoneTag', '')
            )

        ptp_notes = ''
        ptp_amount_str = customize_res.get('PTP Amount', '')
        ptp_amount = ptp_amount_str.replace('.', '')
        ptp_date = format_ptp_date(customize_res.get('PTP Date', ''))
        if ptp_amount != '' and ptp_date != '':
            ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
            acc_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
            logger.info(
                {
                    "action": "ptp_create_v2",
                    "account_payment_id": acc_payment.id,
                    "ptp_date": ptp_date,
                    "ptp_amount": ptp_amount,
                    "agent_user": agent_user.id,
                    "function": fn_name,
                    "source": "Grab Airudder Webhook",
                }
            )
            ptp_create_v2(acc_payment, ptp_date, ptp_amount, agent_user, False, True)
            payment = Payment.objects.filter(account_payment=acc_payment).first()
            if payment:
                payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)

        hangup_reason = callback_body.get('hangupReason', None)
        construct_status_data = hangup_reason \
            if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else customize_res
        status, status_group = airudder_construct_status_and_status_group(callback_type, construct_status_data)

        identifier = status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
        is_identifier_exist = identifier != ''

        filter_identifier = identifier if is_identifier_exist else 'NULL'
        skiptrace_res_choice = SkiptraceResultChoice.objects.filter(name=filter_identifier).last()
        if not skiptrace_res_choice:
            errMsg = "Call status not valid"
            logger.error({'function_name': fn_name, 'message': errMsg})

            return False, errMsg, data

        call_id = callback_body.get('callid', None)

        skiptrace_history_data = dict(
            start_ts=datetime(1970, 1, 1),
            skiptrace_id=skiptrace.id,
            payment_id=None,
            payment_status=None,
            loan_id=None,
            loan_status=None,
            application_id=application.id,
            application_status=application.status,
            account_id=account_id,
            account_payment_id=acc_payment_id,
            account_payment_status_id=acc_payment.status_id if acc_payment and acc_payment.status_id else None,
            agent_id=agent_user.id if agent_user else None,
            agent_name=agent_user.username if agent_user else None,
            notes=callback_body.get('talkremarks', None),
            non_payment_reason=non_payment_reason,
            spoke_with=spoke_with,
            status_group=status_group,
            status=status,
            source=AiRudder.AI_RUDDER_SOURCE,
            call_result=skiptrace_res_choice,
            external_unique_identifier=call_id,
        )

        stateKey = 'state' if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else 'State'
        state = callback_body.get(stateKey, None)
        timestamp = callback_body.get('timestamp', None)
        timestamp_datetime = datetime.fromtimestamp(int(timestamp) / 1000.0) if timestamp else None

        start_ts, end_ts = None, None
        if state and timestamp:
            if state in AiRudder.START_TS_STATE:
                start_ts = timestamp_datetime
                skiptrace_history_data['start_ts'] = start_ts
            if state in AiRudder.END_TS_STATE:
                end_ts = timestamp_datetime
                skiptrace_history_data['end_ts'] = end_ts

        if not is_identifier_exist:
            for field in ['status', 'status_group',
                          'non_payment_reason', 'spoke_with', 'notes']:
                del skiptrace_history_data[field]

        try:
            with transaction.atomic():
                grab_skiptrace_history = GrabSkiptraceHistory.objects.create(**skiptrace_history_data)
        except IntegrityError:
            grab_skiptrace_history = GrabSkiptraceHistory.objects.filter(
                external_unique_identifier=call_id).first()
            for field in ['skiptrace_id', 'payment_id',
                          'payment_status', 'loan_id', 'loan_status',
                          'application_id', 'application_status', 'account_id',
                          'account_payment_id', 'account_payment_status_id',
                          'source', 'external_unique_identifier']:
                del skiptrace_history_data[field]

            if start_ts is None:
                del skiptrace_history_data['start_ts']

            utc = pytz.UTC
            new_end_ts = timestamp_datetime.replace(tzinfo=utc)

            is_update = False
            if grab_skiptrace_history.end_ts is not None:
                curr_end_ts = grab_skiptrace_history.end_ts.replace(tzinfo=utc)
                is_update = new_end_ts > curr_end_ts
            else:
                is_update = True

            if is_update:
                if (grab_skiptrace_history.call_result.name != 'NULL'
                        or skiptrace_res_choice.name == 'NULL'):
                    del skiptrace_history_data['call_result']

                grab_skiptrace_history.update_safely(**skiptrace_history_data)

        skiptrace_notes = callback_body.get('talkremarks', None)
        if skiptrace_notes or ptp_notes:
            is_acc_payment_note_exist = GrabCallLogPocAiRudderPds.objects.filter(call_id=call_id,
                                                                                 talk_remarks__isnull=False) \
                .exclude(talk_remarks__exact='') \
                .exists()
            if not is_acc_payment_note_exist:
                AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    account_payment=acc_payment,
                    added_by=agent_user,
                    extra_data={
                        "call_note": {
                            "contact_source": callback_body.get('phoneTag', ''),
                            "phone_number": phone_number,
                            "call_result": status,
                            "spoke_with": spoke_with,
                            "non_payment_reason": non_payment_reason,
                        }
                    }
                )
        data = {
            'grab_skiptrace_history_id': grab_skiptrace_history.id,
            'timestamp': timestamp_datetime,
            'phone_tag': callback_body.get('phoneTag', '') or skiptrace.contact_source,
            'hangup_reason': hangup_reason,
            'state': state,
            'phone_number': phone_number,
            'call_id': call_id,
            'talk_remarks': skiptrace_notes,
        }
        return True, '', data

    def construct_call_log_data(self, callback_data, data):
        callback_type = callback_data['type']
        callback_body = callback_data['body']
        call_log_data = {
            'call_log_type': callback_type,
            'task_id': callback_body.get('taskId', None),
            'task_name': callback_body.get('taskName', None),
            'group_name': callback_body.get('groupName', None),
            'contact_name': callback_body.get('contactName', None),
            'address': callback_body.get('address', None),
            'info_1': callback_body.get('info1', None),
            'info_2': callback_body.get('info2', None),
            'info_3': callback_body.get('info3', None),
            'remark': callback_body.get('remark', None),
            'main_number': callback_body.get('mainNumber', None),
            'private_data': callback_body.get('privateData', None),
            'recording_link': callback_body.get('recLink', None),
            'nth_call': callback_body.get('nthCall', None)
        }
        call_log_data.update(data)
        GrabCallLogPocAiRudderPds.objects.create(**call_log_data)
        grab_skiptrace_history = GrabSkiptraceHistory.objects.filter(
            pk=data['grab_skiptrace_history_id']
        ).last()
        if (
            data['state'] == AiRudder.STATE_TALKRESULT
            and callback_type == AiRudder.AGENT_STATUS_CALLBACK_TYPE
        ):
            vendor_recording_detail = VendorRecordingDetail.objects.filter(
                unique_call_id=data['call_id']).last()
            if vendor_recording_detail:
                vendor_recording_detail.update_safely(
                    call_status=grab_skiptrace_history.call_result)

    @transaction.atomic
    def grab_store_call_result_agent(self, callback_data):
        is_success_construct_skiptrace, msg, data = self.construct_skiptrace_history_data(callback_data)
        fn_name = 'grab_store_call_result_agent'
        if not is_success_construct_skiptrace:
            return False, msg

        self.construct_call_log_data(callback_data, data)
        logger.info({
            'function_name': fn_name,
            'message': 'Success process store_call_result_agent',
        })

        return True, 'success'

    def grab_write_hangup_reason(self, grab_skiptrace_history_id, hangup_reason_id):
        reason = AiRudder.HANGUP_REASON_PDS.get(hangup_reason_id)
        GrabHangupReasonPDS.objects.create(
            grab_skiptrace_history_id=grab_skiptrace_history_id,
            hangup_reason=hangup_reason_id,
            reason=reason,
        )

    def grab_recon_store_call_result(self, task_id, call_id):
        from juloserver.minisquad.tasks2.dialer_system_task_grab import \
            grab_download_call_recording_result
        fn_name = 'grab_recon_store_call_result'
        logger.info({
            'function_name': fn_name,
            'message': 'Start running recon_store_call_result',
        })

        response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(task_id, call_id)
        body = response.get('body', None)
        if not body:
            raise ValueError('')

        list_data = body.get('list', None)
        if not list_data:
            raise ValueError('')

        data = list_data[0]
        skiptrace_history = GrabSkiptraceHistory.objects.get(external_unique_identifier=call_id)

        datetime_format = '%Y-%m-%dT%H:%M:%S%z'
        start_ts = datetime.strptime(data.get('calltime', ''), datetime_format)

        update_date = {'start_ts': start_ts}
        skiptrace_history.update_safely(**update_date)

        if data.get('hangupReason') and data.get('hangupReason') >= 0:
            # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
            # execute on final state agent level
            self.grab_write_hangup_reason(skiptrace_history.id, data.get('hangupReason'))

        if data.get('reclink', ''):
            # download call recording
            grab_download_call_recording_result.delay(
                call_id=call_id,
                task_name=data.get('taskName'),
                link=data.get('reclink')
            )

        logger.info({
            'function_name': fn_name,
            'message': 'Finish running recon_store_call_result',
            'call_id': call_id,
        })

    def validate_grab_retro_load_write_data(self, data):
        fn_name = 'validate_grab_retro_load_write_data'
        call_id = data.get('unique_call_id', None)
        agent_user = None
        if GrabSkiptraceHistory.objects.filter(external_unique_identifier=call_id).exists():
            logger.info(
                {
                    'function_name': fn_name,
                    'message': "skip because external unique identifier exists {}".format(call_id),
                }
            )
            return False, agent_user

        phone_number = data.get('phone_number', '')
        if phone_number == '':
            errMsg = "Phone number not valid, please provide valid phone number! {}".format(call_id)
            raise Exception(errMsg)

        agent_name = data.get('agent_name', None)
        if agent_name:
            agent_user = User.objects.filter(username=agent_name).last()
            if not agent_user:
                errMsg = (
                    "Agent name not valid, please provide "
                    "valid agent name with this call id {}".format(call_id)
                )
                raise Exception(errMsg)

            CuserMiddleware.set_user(agent_user)

        return True, agent_user

    def update_grab_ptp_details(self, data, account_payment, agent_user, retro_cdate):
        customize_res = data.get('customizeResults', {})
        ptp_notes = ''
        ptp_amount_str = customize_res.get('PTP Amount', '')
        ptp_amount = ptp_amount_str.replace('.', '')
        ptp_date = customize_res.get('ptp_date', '')
        if ptp_amount != '' and ptp_date != '':
            if not PTP.objects.filter(
                    ptp_date=ptp_date,
                    ptp_amount=ptp_amount,
                    agent_assigned=agent_user,
                    account_payment=account_payment,
            ).exists():
                ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                logger.info(
                    {
                        "action": "ptp_create_v2",
                        "account_payment_id": account_payment.id,
                        "ptp_date": ptp_date,
                        "ptp_amount": ptp_amount,
                        "agent_user": agent_user.id,
                        "function": 'update_grab_ptp_details',
                        "source": "Grab Consume",
                    }
                )
                ptp_create_v2(account_payment, ptp_date, ptp_amount, agent_user, False, True)
                payment = Payment.objects.filter(account_payment=account_payment).first()
                if payment:
                    payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                if retro_cdate:
                    created_ptp = PTP.objects.filter(
                        ptp_date=ptp_date,
                        ptp_amount=ptp_amount,
                        agent_assigned=agent_user,
                        account_payment=account_payment,
                    ).last()
                    if created_ptp:
                        created_ptp.cdate = retro_cdate
                        created_ptp.save()

        return ptp_notes

    def update_grab_skip_trace_details(self, data, account_payment, agent_user,
                                       retro_cdate, hangup_reason, ptp_notes, account):
        customize_res = data.get('customizeResults', {})
        spoke_with = customize_res.get('spoke_with', '')
        non_payment_reason = customize_res.get('non_payment_reason', '')
        hangup_reason_in_payload = data.get('hangup_reason', None)
        call_id = data.get('unique_call_id', None)
        talk_result = data.get('talk_result', '')
        is_connected = talk_result == 'Connected'
        if account_payment:
            account = account_payment.account

        phone_number = data.get('phone_number', '')
        phone_number = format_e164_indo_phone_number(phone_number)

        customer = account.customer
        application = account.customer.application_set.last()
        skiptrace = Skiptrace.objects.filter(
            phone_number=phone_number, customer_id=customer.id
        ).last()
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=phone_number, customer_id=customer.id
            )
        if not hangup_reason_in_payload:
            hangup_reason_in_payload = hangup_reason

        construct_status_data = hangup_reason_in_payload if not is_connected else customize_res
        callback_type = (
            AiRudder.AGENT_STATUS_CALLBACK_TYPE
            if is_connected
            else AiRudder.CONTACT_STATUS_CALLBACK_TYPE
        )
        status, status_group = airudder_construct_status_and_status_group(
            callback_type, construct_status_data
        )

        identifier = (
            status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
        )
        is_identifier_exist = identifier != ''
        filter_identifier = identifier if is_identifier_exist else 'NULL'
        skiptrace_res_choice = (
            SkiptraceResultChoice.objects.all()
            .extra(where=["lower(name) =  %s"], params=[filter_identifier.lower()])
            .last()
        )
        if not skiptrace_res_choice:
            errMsg = "Call status not valid call id {}".format(call_id)
            raise Exception(errMsg)

        start_time = data.get('start_ts', '')
        end_time = data.get('end_ts', '')
        if not start_time or not end_time:
            raise Exception("start ts or end ts is null {}".format(call_id))

        grab_skiptrace_history_data = dict(
            start_ts=start_time,
            end_ts=end_time,
            skiptrace_id=skiptrace.id,
            payment_status=None,
            application_id=application.id,
            account_id=account.id,
            account_payment_id=account_payment.id if account_payment and account_payment.id else None,
            account_payment_status_id=account_payment.status_id
            if account_payment and account_payment.status_id else None,
            agent_id=agent_user.id if agent_user else None,
            agent_name=agent_user.username if agent_user else None,
            notes=data.get('skiptrace_notes', None),
            non_payment_reason=non_payment_reason,
            spoke_with=spoke_with,
            status_group=status_group,
            status=status,
            source=AiRudder.AI_RUDDER_SOURCE,
            call_result=skiptrace_res_choice,
            external_unique_identifier=call_id,
            external_task_identifier=data.get('task_id')
        )

        grab_skiptrace_history = GrabSkiptraceHistory.objects.create(
            **grab_skiptrace_history_data
        )
        if grab_skiptrace_history and retro_cdate:
            grab_skiptrace_history.cdate = retro_cdate
            grab_skiptrace_history.save()
            if data.get('hangup_reason'):
                # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
                self.grab_write_hangup_reason(
                    grab_skiptrace_history.id, int(data.get('hangup_reason'))
                )

        skiptrace_notes = data.get('skiptrace_notes', None)
        if skiptrace_notes or ptp_notes:
            is_acc_payment_note_exist = (
                GrabCallLogPocAiRudderPds.objects.filter(
                    call_id=call_id, talk_remarks__isnull=False
                )
                .exclude(talk_remarks__exact='')
                .exists()
            )
            if not is_acc_payment_note_exist:
                account_payment_note = AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    account_payment=account_payment,
                    added_by=agent_user,
                    extra_data={
                        "call_note": {
                            "contact_source": data.get('contact_source', ''),
                            "phone_number": phone_number,
                            "call_result": status,
                            "spoke_with": spoke_with,
                            "non_payment_reason": non_payment_reason,
                        }
                    },
                )

                if account_payment_note and retro_cdate:
                    account_payment_note.cdate = retro_cdate
                    account_payment_note.save()
        return

    def grab_retro_load_write_data_to_skiptrace_history(
            self, data, hangup_reason=None, retro_cdate=None
    ):
        fn_name = 'grab_retro_load_write_data_to_skiptrace_history'
        logger.info(
            {
                'function_name': fn_name,
                'partner': 'grab',
                'message': 'Start process write_data_to_skiptrace_history',
            }
        )
        is_valid_data, agent_user = self.validate_grab_retro_load_write_data(data)
        if not is_valid_data:
            return

        call_id = data.get('unique_call_id', None)
        main_number = data.get('main_number', '')
        account_payment, account = get_account_or_account_payment_base_on_mobile_phone(main_number)
        if not account:
            return

        with transaction.atomic():
            ptp_notes = self.update_grab_ptp_details(data, account_payment, agent_user, retro_cdate)
            self.update_grab_skip_trace_details(data, account_payment, agent_user,
                                                retro_cdate, hangup_reason, ptp_notes, account)

            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'Success process skiptrace history for this call id {}'.format(
                        call_id
                    ),
                }
            )

        return True

    def get_grab_call_results_data_by_task_id(
            self,
            task_id: str,
            start_time: datetime,
            end_time: datetime,
            limit: int = 0,
            total_only: bool = False,
            offset: int = 0,
            retries_time: int = 0
    ) -> List:
        if not task_id:
            raise Exception(
                'AI Rudder Service error: tasks id is null for this time range {} - {}'.format(
                    str(start_time), str(end_time)
                )
            )

        response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(
            task_id=task_id, start_time=start_time, end_time=end_time, limit=limit, offset=offset,
            retries_time=retries_time
        )
        body = response.get('body', None)
        if not body:
            logger.info({'action': 'AI Rudder PDS services', 'message': 'response dont have body'})
            return []

        if total_only:
            total = body.get('total', None)
            if not total:
                logger.info(
                    {
                        'action': 'AI Rudder PDS services',
                        'message': 'response body dont have column total',
                    }
                )
                return 0

            return total

        list_data = body.get('list', None)
        if not list_data:
            logger.info(
                {
                    'action': 'AI Rudder PDS services',
                    'message': 'response body dont have column list',
                }
            )
            return []

        return list_data

    def construct_call_log_data_for_manual_upload(self, data, task_detail):
        call_log_data = {}
        for ind, detail in enumerate(task_detail.split("@@")):
            if ind == 1:
                call_log_data.update({'group_name': detail})
        call_log_data.update(data)
        GrabCallLogPocAiRudderPds.objects.create(**call_log_data)

    def update_account_payment_notes(self, data):
        print(data)
        skiptrace_notes = data.get('skiptrace_notes', None)
        if skiptrace_notes or data.get('ptp_notes'):
            is_acc_payment_note_exist = (
                GrabCallLogPocAiRudderPds.objects.filter(
                    call_id=data.get('call_id'), talk_remarks__isnull=False
                )
                .exclude(talk_remarks__exact='')
                .exists()
            )
            if not is_acc_payment_note_exist:
                account_payment_note = AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(data.get('ptp_notes'), skiptrace_notes),
                    account_payment=data.get('account_payment'),
                    added_by=data.get('agent_user'),
                    extra_data={
                        "call_note": {
                            "contact_source": data.get('contact_source', ''),
                            "phone_number": data.get('phone_number'),
                            "call_result": data.get('status'),
                            "spoke_with": data.get('spoke_with'),
                            "non_payment_reason": data.get('non_payment_reason'),
                        }
                    },
                )

                if account_payment_note and data.get('retro_cdate'):
                    account_payment_note.cdate = data.get('retro_cdate')
                    account_payment_note.save()

    def update_grab_skip_trace_details_for_manual_upload(
        self, data, account_payment, agent_user,
        retro_cdate, hangup_reason, ptp_notes, account
    ):
        customize_res = data.get('customizeResults', {})
        spoke_with = customize_res.get('Spokewith', '')
        non_payment_reason = customize_res.get('nopaymentreason', '')
        hangup_reason_in_payload = data.get('hangup_reason', None)
        call_id = data.get('unique_call_id', None)
        talk_result = data.get('talk_result', '')
        is_connected = talk_result == 'Connected'
        if account_payment:
            account = account_payment.account

        phone_number = data.get('phone_number', '')
        phone_number = format_e164_indo_phone_number(phone_number)

        customer = account.customer
        application = account.customer.application_set.last()
        skiptrace = Skiptrace.objects.filter(
            phone_number=phone_number, customer_id=customer.id
        ).last()
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                phone_number=phone_number, customer_id=customer.id
            )
        if not hangup_reason_in_payload:
            hangup_reason_in_payload = hangup_reason

        construct_status_data = hangup_reason_in_payload if not is_connected else customize_res
        callback_type = (
            AiRudder.AGENT_STATUS_CALLBACK_TYPE
            if is_connected
            else AiRudder.CONTACT_STATUS_CALLBACK_TYPE
        )
        status, status_group = airudder_construct_status_and_status_group(
            callback_type, construct_status_data
        )

        identifier = (
            status_group if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE else status
        )
        is_identifier_exist = identifier != ''
        filter_identifier = identifier if is_identifier_exist else 'NULL'
        skiptrace_res_choice = (
            SkiptraceResultChoice.objects.all()
            .extra(where=["lower(name) =  %s"], params=[filter_identifier.lower()])
            .last()
        )
        if not skiptrace_res_choice:
            errMsg = "Call status not valid call id {}".format(call_id)
            raise Exception(errMsg)

        start_time = data.get('start_ts', '')
        end_time = data.get('end_ts', '')
        if not start_time or not end_time:
            raise Exception("start ts or end ts is null {}".format(call_id))

        grab_skiptrace_history_data = dict(
            start_ts=start_time,
            end_ts=end_time,
            skiptrace_id=skiptrace.id,
            payment_status=None,
            application_id=application.id,
            application_status=application.status,
            account_id=account.id,
            account_payment_id=account_payment.id if account_payment and account_payment.id else None,
            account_payment_status_id=account_payment.status_id
            if account_payment and account_payment.status_id else None,
            agent_id=agent_user.id if agent_user else None,
            agent_name=agent_user.username if agent_user else None,
            notes=data.get('skiptrace_notes', None),
            non_payment_reason=non_payment_reason,
            spoke_with=spoke_with,
            status_group=status_group,
            status=status,
            source=AiRudder.AI_RUDDER_SOURCE,
            call_result=skiptrace_res_choice,
            external_unique_identifier=call_id,
            external_task_identifier=data.get('task_id')
        )

        grab_skiptrace_history = GrabSkiptraceHistory.objects.create(
            **grab_skiptrace_history_data
        )
        if grab_skiptrace_history and retro_cdate:
            grab_skiptrace_history.cdate = retro_cdate
            grab_skiptrace_history.save()
            if data.get('hangup_reason'):
                # hangup reason reference to minisquad.constants.HANGUP_REASON_PDS
                self.grab_write_hangup_reason(
                    grab_skiptrace_history.id, int(data.get('hangup_reason'))
                )
        details = {
            'ptp_notes': ptp_notes,
            'skiptrace_notes': data.get('skiptrace_notes', None),
            'agent_user': agent_user,
            'phone_number': phone_number,
            'call_id': call_id,
            'account_payment': account_payment,
            'status': status,
            'spoke_with': spoke_with,
            'non_payment_reason': non_payment_reason,
            'retro_cdate': retro_cdate
        }
        self.update_account_payment_notes(
            details
        )
        details = {
            'grab_skiptrace_history_id': grab_skiptrace_history.id,
            'timestamp': None,
            'phone_tag': data.get('phoneTag', '') or skiptrace.contact_source,
            'hangup_reason': data.get('hangup_reason'),
            'phone_number': phone_number,
            'call_id': call_id,
            'talk_remarks': data.get('skiptrace_notes', None),
            'remark': data.get('remark', None),
            'main_number': data.get('mainNumber', None),
            'recording_link': data.get('recLink', None),
            'nth_call': data.get('nthCall', None),
            'task_id': data.get('task_id'),
            'task_name': data.get('task_name')
        }
        return details

    def grab_retro_load_write_data_to_skiptrace_history_table_for_manual_upload(
        self, data, task_detail, start_time, hangup_reason=None, retro_cdate=None
    ):
        fn_name = 'grab_retro_load_write_data_to_skiptrace_history_table_for_manual_upload'
        logger.info(
            {
                'function_name': fn_name,
                'partner': 'grab',
                'message': 'Start process write_data_to_skiptrace_history',
            }
        )
        is_valid_data, agent_user = self.validate_grab_retro_load_write_data(data)
        if not is_valid_data:
            return

        call_id = data.get('unique_call_id', None)
        main_number = data.get('main_number', '')
        account_payment, account = get_account_or_account_payment_base_on_mobile_phone(
            main_number, start_time=start_time
        )
        if not account:
            return

        with transaction.atomic():
            ptp_notes = self.update_grab_ptp_details(data, account_payment, agent_user, retro_cdate)
            details = self.update_grab_skip_trace_details_for_manual_upload(
                data, account_payment, agent_user,
                retro_cdate, hangup_reason, ptp_notes, account
            )

            if details:
                self.construct_call_log_data_for_manual_upload(details, task_detail)
                if details.get('recording_link'):
                    from juloserver.minisquad.tasks2.dialer_system_task_grab import \
                        grab_download_call_recording_result
                    grab_download_call_recording_result.delay(
                        call_id=call_id,
                        task_name=details.get('task_name'),
                        link=details.get('recording_link'),
                        is_manual_upload=True
                    )

            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'Success process skiptrace history for this call id {}'.format(
                        call_id
                    ),
                }
            )

        return True

    def get_skiptrace_result_choice_for_retroload(self, data):
        customize_res = data.get('customizeResults', {})
        status, _ = airudder_construct_status_and_status_group(
            AiRudder.AGENT_STATUS_CALLBACK_TYPE, customize_res)
        return status

    def sync_up_skiptrace_history_services(
        self, data, retro_date, task_name=None, call_result_sync_only=False
    ):
        """
        on this task, will do several things
        1. update start_ts, call result, etc
        2. record on hangup_reason_pds
        3. save recording call
        4. PTP
        """

        from juloserver.minisquad.tasks2.dialer_system_task import \
            download_call_recording_result
        from juloserver.omnichannel.tasks.customer_related import send_pds_action_log

        fn_name = 'sync_up_skiptrace_history_services'
        call_id = data.get('unique_call_id')
        used_model_dictionary = self.determine_used_model_by_task(task_name)
        skiptrace_history_model = used_model_dictionary.get('skiptrace_history')
        hangup_reason_model = used_model_dictionary.get('hangup_pds')
        skiptrace_history = (
            skiptrace_history_model.objects.filter(external_unique_identifier=call_id)
            .values('id', 'start_ts', 'call_result', 'account_payment')
            .last()
        )
        if not skiptrace_history:
            logger.info({
                'action': fn_name,
                'message': 'skiptrace history not found',
                'data': data
            })
            return

        skiptrace_need_to_update_dict = {}
        customize_res = data.get('customizeResults', {})
        spoke_with = customize_res.get('Spokewith', '')
        non_payment_reason = customize_res.get('non_payment_reason', '') or customize_res.get(
            'nopaymentreason', ''
        )
        need_to_check_ptp_and_note = False
        status = ''
        agent_user = None
        # sync up end_ts
        skiptrace_need_to_update_dict.update(end_ts=data.get('end_ts', ''))
        # sync up start_ts
        validation_date = datetime(2000, 12, 12)
        if skiptrace_history.get('start_ts').date() < validation_date.date():
            skiptrace_need_to_update_dict.update(start_ts=data.get('start_ts'))
        # sync up call result

        if (
            SkiptraceResultChoice.objects.filter(
                pk=skiptrace_history.get('call_result'), name='NULL'
            ).exists()
            or call_result_sync_only
        ):
            hangup_reason_dict = AiRudder.HANGUP_REASON_STATUS_GROUP_MAP
            hangup_reason_ids_without_null = [
                key for key, value in hangup_reason_dict.items() if value != 'NULL']
            hangup_reason_ids_without_null.append(12)
            hangupd_reason_id = int(data.get('hangup_reason'))
            if hangupd_reason_id in hangup_reason_ids_without_null:
                talk_result = data.get('talk_result', '')
                is_connected = hangupd_reason_id == 12 or talk_result == 'Connected'
                construct_status_data = hangupd_reason_id if not is_connected else customize_res
                callback_type = AiRudder.AGENT_STATUS_CALLBACK_TYPE \
                    if is_connected else AiRudder.CONTACT_STATUS_CALLBACK_TYPE
                status, status_group = airudder_construct_status_and_status_group(
                    callback_type, construct_status_data, True, hangupd_reason_id
                )
                identifier = (
                    status_group
                    if callback_type == AiRudder.CONTACT_STATUS_CALLBACK_TYPE
                    else status
                )
                is_identifier_exist = identifier != ''
                filter_identifier = identifier if is_identifier_exist else 'NULL'
                skiptrace_res_choice = SkiptraceResultChoice.objects.all().extra(
                    where=["lower(name) =  %s"], params=[filter_identifier.lower()]).last()
                skiptrace_need_to_update_dict.update(
                    call_result=skiptrace_res_choice,
                    status_group=status_group,
                    status=status,
                    notes=data.get('skiptrace_notes', None),
                    spoke_with=spoke_with,
                    non_payment_reason=non_payment_reason)
                need_to_check_ptp_and_note = True
        logger.info({
            'action': fn_name,
            'message': 'data need to sync',
            'data': data,
            'column': skiptrace_need_to_update_dict,
            'need_to_check_ptp_notes': need_to_check_ptp_and_note,
        })
        if not skiptrace_need_to_update_dict:
            logger.info({
                'action': fn_name,
                'message': 'data no need to sync',
                'data': data
            })
            return

        skiptrace_history_obj = skiptrace_history_model.objects.filter(
            pk=skiptrace_history.get('id')
        ).last()
        skiptrace_history_obj.update_safely(**skiptrace_need_to_update_dict)

        logger.info({
            'action': fn_name,
            'message': 'start to sync up hangup reason and recording',
            'data': data
        })

        hangup_reason_id = int(data.get('hangup_reason'))
        # check if not yet record on hangup_reason_pds table
        if not hangup_reason_model.objects.filter(
            skiptrace_history_id=skiptrace_history.get('id')).exists():
            self.write_hangup_reason(skiptrace_history.get('id'), hangup_reason_id)

        end_time = skiptrace_history_obj.end_ts.date()
        self.count_ineffective_phone_number(
            skiptrace_history_obj.skiptrace_id, hangup_reason_id, end_time, task_name
        )

        self.write_skiptrace_history_pds_detail(
            skiptrace_history_obj.id,
            data,
        )
        execute_after_transaction_safely(
            lambda: send_pds_action_log.delay(
                [
                    OmnichannelPDSActionLogTask(
                        skiptrace_history_id=skiptrace_history_obj.id,
                        contact_source=data.get('contact_source'),
                        task_name=data.get('task_name'),
                    )
                ]
            )
        )

        # save recording call
        if (
            data.get('rec_link')
            and data.get('answertime')
            and not VendorRecordingDetail.objects.filter(unique_call_id=call_id).exists()
        ):
            download_call_recording_result.delay(
                call_id=call_id,
                task_name=data.get('task_name'),
                link=data.get('rec_link'),
                answer_time=data.get('answertime'),
            )

        if retro_date:
            # this for retroload case
            # no need to create PTP or Account Payment Note, not impact to agent KPI
            logger.info({
                'action': fn_name,
                'message': 'skip to next code, this retroload case',
                'data': data
            })
            return

        logger.info({
            'action': fn_name,
            'message': 'start to sync up ptp',
            'data': data
        })
        # check PTP
        ptp_notes = ''
        ptp_amount = customize_res.get('PTP Amount', '')
        ptp_date = customize_res.get('ptp_date', '')
        account_payment = AccountPayment.objects.filter(
            pk=skiptrace_history.get('account_payment')).last()
        if not account_payment:
            errMsg = "Account Payment doesnt not exists for this call id {}".format(call_id)
            raise Exception(errMsg)

        account = account_payment.account
        customer = account.customer

        if need_to_check_ptp_and_note:
            agent_name = data.get('agent_name', None)
            if agent_name:
                agent_user = User.objects.filter(username=agent_name).last()
                if not agent_user:
                    errMsg = "Agent name not valid, please provide " \
                            "valid agent name with this call id {}".format(call_id)
                    raise Exception(errMsg)
                CuserMiddleware.set_user(agent_user)
            else:
                CuserMiddleware.del_user()

            if ptp_amount != '' and ptp_date != '':
                if not PTP.objects.filter(
                        ptp_date=ptp_date, ptp_amount=ptp_amount, agent_assigned=agent_user,
                        account_payment=account_payment
                ).exists():
                    ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                    account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create_v2(account_payment, ptp_date, ptp_amount, agent_user, True, False)

            logger.info({
                'action': fn_name,
                'message': 'start to sync up notes',
                'data': data
            })

            phone_number = data.get('phone_number', '')
            if phone_number == '':
                errMsg = "Phone number not valid, please provide valid phone number! {}".format(call_id)
                raise Exception(errMsg)

            skiptrace_notes = data.get('skiptrace_notes', None)
            skiptrace = Skiptrace.objects.filter(
                phone_number=phone_number,
                customer_id=customer.id
            ).last()
            if not call_result_sync_only and (skiptrace_notes or ptp_notes):
                contact_source = data.get('contact_source', '') or skiptrace.contact_source
                AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    account_payment=account_payment,
                    added_by=agent_user,
                    extra_data={
                        "call_note": {
                            "contact_source": contact_source,
                            "phone_number": phone_number,
                            "call_result": status,
                            "spoke_with": spoke_with,
                            "non_payment_reason": non_payment_reason,
                        }
                    }
                )

    def grab_delete_single_call_from_calling_queue(
            self, account: Account):
        '''
            for delete customer from calling queue for now we can detect customer using
            mobile phone 1
        '''
        current_time = timezone.localtime(timezone.now())
        today_min = datetime.combine(current_time, time.min)
        today_max = datetime.combine(current_time, time.max)
        dialer_data = SentToDialer.objects.filter(
            cdate__range=(today_min, today_max),
            account=account,
            bucket=AiRudder.GRAB
        ).last()
        if not dialer_data:
            current_time = timezone.localtime(timezone.now()).time()
            if current_time > time(hour=5, minute=30):
                return False

            SentToDialer.objects.filter(
                cdate__range=(today_min, today_max), bucket=AiRudder.GRAB,
                account=account).update(is_deleted=True)
            return True

        dialer_task_id = dialer_data.task_id
        if not dialer_task_id:
            raise Exception('AI Rudder task_id is empty in sent_to_dialer')

        task_ids = [dialer_task_id]
        if not task_ids:
            task_ids = self.get_list_of_task_id_today()

        application = account.last_application
        mobile_phone_1 = application.mobile_phone_1
        if not mobile_phone_1:
            raise Exception(
                'AI Rudder Service error: Mobile phone 1 is null account id {}'.format(
                    account.id)
            )
        mobile_phone_1 = format_valid_e164_indo_phone_number(mobile_phone_1)
        success_deleted, failed_message = self.do_delete_phone_numbers_from_call_queue(
            task_ids, [mobile_phone_1])
        if failed_message:
            raise Exception(
                'AI Rudder Service error: {}'.format(
                    str(failed_message))
            )
        if success_deleted:
            dialer_data.update_safely(is_deleted=True)

        return True

    def fix_start_ts_skiptrace_history(self, start_time: datetime, end_time: datetime):
        fn_name = 'AIRudderPDSServices.fix_start_ts_skiptrace_history'
        logger.info({'action': fn_name, 'message': 'task begin'})
        skiptrace_histories = SkiptraceHistory.objects.filter(
            source=AiRudder.AI_RUDDER_SOURCE,
            cdate__range=(start_time, end_time),
            external_task_identifier__isnull=False,
            start_ts__lt='2000-01-01 00:00:00+0700',  # query start_ts 1970
        )
        for skiptrace_history in skiptrace_histories.iterator():
            try:
                task_id = skiptrace_history.external_task_identifier
                call_id = skiptrace_history.external_unique_identifier

                logger.info(
                    {
                        'action': fn_name,
                        'message': 'start fix data',
                        'task_id': task_id,
                        'call_id': call_id,
                    }
                )

                data = self.get_call_results_data_by_task_id(
                    task_id, start_time, end_time, limit=1, call_id=call_id
                )
                if not data:
                    logger.info(
                        {
                            'action': fn_name,
                            'message': "there's no result data from AiRudder API",
                            'task_id': task_id,
                            'call_id': call_id,
                        }
                    )
                    continue

                SkiptraceHistory.objects.filter(pk=skiptrace_history.id).update(
                    start_ts=datetime.strptime(data[0]['calltime'], '%Y-%m-%dT%H:%M:%S%z')
                )
                logger.info(
                    {
                        'action': fn_name,
                        'message': 'finished fix data',
                        'task_id': task_id,
                        'call_id': call_id,
                    }
                )
            except Exception as err:
                print(str(err))
                logger.error(
                    {
                        'action': fn_name,
                        'message': "there's an issue: {}".format(str(err)),
                        'task_id': task_id,
                        'call_id': call_id,
                    }
                )
                get_julo_sentry_client().captureException()
                continue

        logger.info({'action': fn_name, 'message': 'task finish'})

    def process_eleminate_manual_task(self, list_of_task: List) -> List:
        filtered_list_of_task = []
        for task in list_of_task:
            task_id = task.get('task_id', '')
            task_name = task.get('task_name', '').lower()
            if not any(
                substring in task_name for substring in AiRudder.TASK_NAME_CONTAINS_MANUAL_UPLOAD
            ):
                filtered_list_of_task.append(task_id)

        return filtered_list_of_task

    def process_retroload_sent_to_dialer_subtask(
        self, list_of_task: List, sent_to_dialer_ids: List, start_time: datetime, end_time: datetime
    ):
        fn_name = 'process_retroload_sent_to_dialer_subtask'
        logger.info({'action': fn_name, 'message': 'task begin'})

        sent_to_dialers = sent_to_dialer = SentToDialer.objects.select_related(
            'account_payment'
        ).filter(pk__in=sent_to_dialer_ids)
        for sent_to_dialer in sent_to_dialers.iterator():
            try:
                account_payment_id = (
                    sent_to_dialer.account_payment.id if sent_to_dialer.account_payment else None
                )
                if not account_payment_id:
                    logger.info(
                        {
                            'action': fn_name,
                            'message': 'there no account payment for sent to dialer {}'.format(
                                sent_to_dialer.id
                            ),
                        }
                    )
                    continue
                skiptrace_history = SkiptraceHistory.objects.filter(
                    source=AiRudder.AI_RUDDER_SOURCE,
                    end_ts__range=(start_time, end_time),
                    account_payment_id=account_payment_id,
                    external_task_identifier__isnull=False,
                    external_task_identifier__in=list_of_task,
                ).last()
                if not skiptrace_history:
                    logger.info(
                        {
                            'action': fn_name,
                            'message': 'there no task id for account payment id {}'.format(
                                account_payment_id
                            ),
                        }
                    )
                    continue
                SentToDialer.objects.filter(pk=sent_to_dialer.id).update(
                    task_id=skiptrace_history.external_task_identifier
                )
            except Exception as err:
                logger.error({'action': fn_name, 'message': str(err)})
                get_julo_sentry_client().captureException()
                continue
        logger.info({'action': fn_name, 'message': 'task finished'})

    def construct_payload_for_b5(
        self,
        populated_data: CollectionB5,
        bucket_name: str,
        ineffective_consecutive_days: int = 0,
        ineffective_refresh_days: int = 0,
    ) -> Union:
        if not populated_data:
            raise Exception("error when construct the data")

        fn_name = 'construct_payload_for_b5'

        logger.info({'action': fn_name, 'message': 'mapping data'})

        account_payment = AccountPayment.objects.filter(pk=populated_data.account_payment_id).last()
        phone_number_dict = dict(
            phonenumber=populated_data.phonenumber,
            mobile_phone_2=populated_data.mobile_phone_2,
            no_telp_pasangan=populated_data.no_telp_pasangan,
            telp_perusahaan=populated_data.telp_perusahaan,
        )
        bucket_number = 5
        phone_number_filtred = self.get_eligible_phone_number_list_b5(
            populated_data.customer_id,
            phone_number_dict,
            bucket_number,
            ineffective_consecutive_days,
            ineffective_refresh_days,
        )
        if not phone_number_filtred['phonenumber']:
            raise Exception('all phone number indicated as ineffective')

        payload = AIRudderPayloadTemp(
            account_payment_id=populated_data.account_payment_id,
            account_id=populated_data.account_id,
            customer_id=populated_data.customer_id,
            nama_customer=populated_data.nama_customer,
            nama_perusahaan=populated_data.nama_perusahaan,
            posisi_karyawan=populated_data.posisi_karyawan,
            nama_pasangan=populated_data.nama_pasangan,
            nama_kerabat=populated_data.nama_kerabat,
            hubungan_kerabat=populated_data.hubungan_kerabat,
            jenis_kelamin=populated_data.jenis_kelamin,
            tgl_lahir=datetime.strftime(populated_data.tgl_lahir, "%Y-%m-%d")
            if populated_data.tgl_lahir
            else '',
            tgl_gajian=populated_data.tgl_gajian,
            tujuan_pinjaman=populated_data.tujuan_pinjaman,
            tanggal_jatuh_tempo=populated_data.tanggal_jatuh_tempo,
            alamat=populated_data.alamat,
            kota=populated_data.kota,
            dpd=populated_data.dpd,
            partner_name=populated_data.partner_name,
            tgl_upload=datetime.strftime(populated_data.tgl_upload, "%Y-%m-%d")
            if populated_data.tgl_upload
            else '',
            tipe_produk=populated_data.tipe_produk,
            total_denda=populated_data.total_denda,
            total_due_amount=populated_data.total_due_amount,
            total_outstanding=populated_data.total_outstanding,
            angsuran_ke=populated_data.angsuran_ke,
            va_bca=populated_data.va_bca,
            va_permata=populated_data.va_permata,
            va_maybank=populated_data.va_maybank,
            va_alfamart=populated_data.va_alfamart,
            va_indomaret=populated_data.va_indomaret,
            va_mandiri=populated_data.va_mandiri,
            last_pay_date=populated_data.last_pay_date,
            last_pay_amount=populated_data.last_pay_amount,
            last_agent=populated_data.last_agent,
            last_call_status=populated_data.last_call_status,
            refinancing_status=populated_data.refinancing_status,
            activation_amount=populated_data.activation_amount,
            program_expiry_date=populated_data.program_expiry_date,
            phonenumber=phone_number_filtred.get('phonenumber', ''),
            mobile_phone_2=phone_number_filtred.get('mobile_phone_2', ''),
            no_telp_pasangan=phone_number_filtred.get('no_telp_pasangan', ''),
            telp_perusahaan=phone_number_filtred.get('telp_perusahaan', ''),
            bucket_name=bucket_name,
            unpaid_loan_account_details=self.get_unpaid_loan_description_list_pds(account_payment),
        )

        return payload

    def construct_payload_for_b6(self, populated_data: CollectionB6, bucket_name: str) -> Union:
        if not populated_data:
            raise Exception("error when construct the data")

        fn_name = 'construct_payload_for_b6'

        logger.info({'action': fn_name, 'message': 'mapping data'})

        account_payment = AccountPayment.objects.filter(pk=populated_data.account_payment_id).last()
        payload = AIRudderPayloadTemp(
            account_payment_id=populated_data.account_payment_id,
            account_id=populated_data.account_id,
            customer_id=populated_data.customer_id,
            nama_customer=populated_data.nama_customer,
            nama_perusahaan=populated_data.nama_perusahaan,
            posisi_karyawan=populated_data.posisi_karyawan,
            nama_pasangan=populated_data.nama_pasangan,
            nama_kerabat=populated_data.nama_kerabat,
            hubungan_kerabat=populated_data.hubungan_kerabat,
            jenis_kelamin=populated_data.jenis_kelamin,
            tgl_lahir=datetime.strftime(populated_data.tgl_lahir, "%Y-%m-%d")
            if populated_data.tgl_lahir
            else '',
            tgl_gajian=populated_data.tgl_gajian,
            tujuan_pinjaman=populated_data.tujuan_pinjaman,
            tanggal_jatuh_tempo=populated_data.tanggal_jatuh_tempo,
            alamat=populated_data.alamat,
            kota=populated_data.kota,
            dpd=populated_data.dpd,
            partner_name=populated_data.partner_name,
            tgl_upload=datetime.strftime(populated_data.tgl_upload, "%Y-%m-%d")
            if populated_data.tgl_upload
            else '',
            tipe_produk=populated_data.tipe_produk,
            total_denda=populated_data.total_denda,
            total_due_amount=populated_data.total_due_amount,
            total_outstanding=populated_data.total_outstanding,
            angsuran_ke=populated_data.angsuran_ke,
            va_bca=populated_data.va_bca,
            va_permata=populated_data.va_permata,
            va_maybank=populated_data.va_maybank,
            va_alfamart=populated_data.va_alfamart,
            va_indomaret=populated_data.va_indomaret,
            va_mandiri=populated_data.va_mandiri,
            last_pay_date=populated_data.last_pay_date,
            last_pay_amount=populated_data.last_pay_amount,
            last_agent=populated_data.last_agent,
            last_call_status=populated_data.last_call_status,
            refinancing_status=populated_data.refinancing_status,
            activation_amount=populated_data.activation_amount,
            program_expiry_date=populated_data.program_expiry_date,
            phonenumber=populated_data.phonenumber,
            mobile_phone_2=populated_data.mobile_phone_2,
            no_telp_pasangan=populated_data.no_telp_pasangan,
            telp_perusahaan=populated_data.telp_perusahaan,
            bucket_name=bucket_name,
            unpaid_loan_account_details=self.get_unpaid_loan_description_list_pds(account_payment),
        )

        return payload

    def process_construction_data_for_dialer_b5(
        self, bucket_name: str, page_number: int, clean_account_payment_ids: [], dialer_task_id: int
    ) -> int:
        from juloserver.minisquad.tasks2 import write_not_sent_to_dialer_async

        fn_name = 'process_construction_data_for_dialer_b5'
        identifier = 'construct_{}_page_{}'.format(bucket_name, page_number)
        logger.info({'action': fn_name, 'identifier': identifier, 'state': 'querying'})

        # populate data
        assigned = "Desk Collection - Inhouse"
        current_date = timezone.localtime(timezone.now()).date()
        bucket_recover_is_running = get_feature_setting_parameters(
            FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'is_running'
        )
        if bucket_recover_is_running:
            collection_b5_data_for_today = BucketRecoveryDistribution.objects.filter(
                bucket_name=DialerSystemConst.DIALER_BUCKET_5,
                assignment_generated_date=current_date,
                account_payment_id__in=list(clean_account_payment_ids),
                assigned_to=assigned,
            ).select_related('account_payment')
        else:
            collection_b5_data_for_today = CollectionB5.objects.filter(
                cdate__date=self.current_date,
                account_payment_id__in=list(clean_account_payment_ids),
                assigned_to=assigned,
            )
        if not collection_b5_data_for_today:
            raise Exception("Not Found data in collection B5 for today")

        data_count = collection_b5_data_for_today.count()
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'queried',
                'total_data': data_count,
            }
        )

        if not data_count:
            raise Exception("Not Found populated_b5_data")

        # bathing data creation prevent full memory
        batch_size = 500
        counter = 0
        processed_data_count = 0
        formated_ai_rudder_payload = []
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'construct',
            }
        )
        # check ineffective number
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()
        params = fs.parameters if fs else {}
        param_per_bucket = params.get(bucket_name, {})
        consecutive_days = param_per_bucket.get('consecutive_days', 0)
        ineffective_refresh_days = (
            param_per_bucket.get('threshold_refresh_days')
            if param_per_bucket.get('is_ineffective_refresh', False)
            else 0
        )
        # implementing experiment for b5
        for item in collection_b5_data_for_today:
            try:
                if bucket_recover_is_running:
                    account_payment = item.account_payment
                    if not account_payment:
                        continue
                    formatted_data = self.construct_payload(
                        account_payment,
                        bucket_name,
                        ineffective_consecutive_days=consecutive_days,
                        ineffective_refresh_days=ineffective_refresh_days,
                    )
                else:
                    formatted_data = self.construct_payload_for_b5(
                        item,
                        bucket_name,
                        ineffective_consecutive_days=consecutive_days,
                        ineffective_refresh_days=ineffective_refresh_days,
                    )
            except Exception as e:
                if 'ineffective' in str(e):
                    write_not_sent_to_dialer_async.delay(
                        bucket_name=bucket_name,
                        reason=ReasonNotSentToDialer.UNSENT_REASON[
                            'INEFFECTIVE_PHONE_NUMBER'
                        ].strip("'"),
                        account_payment_ids=[account_payment.id],
                        dialer_task_id=dialer_task_id,
                    )
                    continue
                logger.error(
                    {
                        'action': fn_name,
                        'state': 'payload generation',
                        'identifier': identifier,
                        'error': str(e),
                    }
                )
                get_julo_sentry_client().captureException()
                continue

            formated_ai_rudder_payload.append(formatted_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info(
                    {
                        'action': fn_name,
                        'identifier': identifier,
                        'state': 'bulk_create',
                        'counter': counter,
                    }
                )
                AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formated_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formated_ai_rudder_payload:
            processed_data_count += counter
            logger.info(
                {
                    'action': fn_name,
                    'identifier': identifier,
                    'state': 'bulk_create_last_part',
                    'counter': counter,
                }
            )
            AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)

        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'constructed',
            }
        )
        return processed_data_count

    def process_construction_data_for_dialer_b6(
        self, bucket_name: str, page_number: int, clean_account_payment_ids: []
    ) -> int:
        fn_name = 'process_construction_data_for_dialer_b6'
        identifier = 'construct_{}_page_{}'.format(bucket_name, page_number)
        logger.info({'action': fn_name, 'identifier': identifier, 'state': 'querying'})

        # populate data
        collection_b6_data_for_today = CollectionB6.objects.filter(
            assignment_datetime__date=self.current_date,
            account_payment_id__in=list(clean_account_payment_ids),
        )
        if not collection_b6_data_for_today:
            raise Exception("Not Found data in ana.collection_b6 for today")

        data_count = collection_b6_data_for_today.count()
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'queried',
                'total_data': data_count,
            }
        )

        if not data_count:
            raise Exception("Not Found populated_b6_data")

        # bathing data creation prevent full memory
        batch_size = 500
        counter = 0
        processed_data_count = 0
        formated_ai_rudder_payload = []
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'construct',
            }
        )
        # implementing experiment for b6
        for item in collection_b6_data_for_today:
            try:
                formatted_data = self.construct_payload_for_b6(item, bucket_name)
            except Exception as e:
                logger.error(
                    {
                        'action': fn_name,
                        'state': 'payload generation',
                        'identifier': identifier,
                        'error': str(e),
                    }
                )
                get_julo_sentry_client().captureException()
                continue

            formated_ai_rudder_payload.append(formatted_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info(
                    {
                        'action': fn_name,
                        'identifier': identifier,
                        'state': 'bulk_create',
                        'counter': counter,
                    }
                )
                AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formated_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formated_ai_rudder_payload:
            processed_data_count += counter
            logger.info(
                {
                    'action': fn_name,
                    'identifier': identifier,
                    'state': 'bulk_create_last_part',
                    'counter': counter,
                }
            )
            AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)

        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'constructed',
            }
        )
        return processed_data_count

    def process_construction_data_for_dialer_bttc(
        self,
        bucket_name: str,
        bucket_name_bttc: str,
        retries_times: int,
        account_payment_ids: list,
        third_party: str = DialerSystemConst.AI_RUDDER_PDS,
    ) -> int:
        from juloserver.minisquad.tasks2 import write_not_sent_to_dialer_async

        fn_name = 'process_construction_data_for_dialer_bttc'
        identifier = 'construct_{}_retries_{}'.format(bucket_name_bttc, retries_times)
        logger.info({'action': fn_name, 'identifier': identifier, 'state': 'querying'})

        current_time = timezone.localtime(timezone.now())
        account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids).exclude(
            due_amount=0
        )
        sort_order_from_ana = get_sort_order_from_ana(account_payments)
        data_count = account_payments.count()
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'queried',
                'total_data': data_count,
            }
        )
        populated_dialer_call_data = account_payments.select_related(
            'account__customer', 'account'
        ).prefetch_related('account__customer__application_set', 'ptp_set')
        # bathing data creation prevent full memory
        batch_size = 500
        counter = 0
        processed_data_count = 0
        formated_ai_rudder_payload = []
        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'construct',
            }
        )

        omnichannel_exclusion_request = get_omnichannel_comms_block_active(
            OmnichannelIntegrationSetting.CommsType.PDS
        )
        dialer_task_type = DialerTaskType.get_construct_dialer_type(bucket_name_bttc)
        dialer_task = DialerTask.objects.filter(
            type=dialer_task_type, vendor=third_party, cdate__gte=current_time.date()
        ).last()

        # check ineffective number
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()
        params = fs.parameters if fs else {}
        param_per_bucket = params.get(bucket_name_bttc, {})
        consecutive_days = param_per_bucket.get('consecutive_days', 0)
        ineffective_refresh_days = (
            param_per_bucket.get('threshold_refresh_days')
            if param_per_bucket.get('is_ineffective_refresh', False)
            else 0
        )
        for item in populated_dialer_call_data:
            if omnichannel_exclusion_request.is_excluded and is_omnichannel_account(
                exclusion_req=omnichannel_exclusion_request, account_id=item.account_id
            ):
                write_not_sent_to_dialer_async.delay(
                    bucket_name=bucket_name,
                    reason=ReasonNotSentToDialer.UNSENT_REASON['OMNICHANNEL_EXCLUSION'].strip("'"),
                    account_payment_ids=[item.id],
                    dialer_task_id=dialer_task.id,
                )
                continue
            try:
                sort_rank = sort_order_from_ana.get(item.id, None)
                bttc_dict = dict(bucket_name=bucket_name_bttc, sort_rank=sort_rank)
                formatted_data = self.construct_payload(
                    item,
                    bucket_name,
                    bttc_dict=bttc_dict,
                    ineffective_consecutive_days=consecutive_days,
                    ineffective_refresh_days=ineffective_refresh_days,
                )
            except Exception as e:
                if 'ineffective' in str(e):
                    write_not_sent_to_dialer_async.delay(
                        bucket_name=bucket_name,
                        reason=ReasonNotSentToDialer.UNSENT_REASON[
                            'INEFFECTIVE_PHONE_NUMBER'
                        ].strip("'"),
                        account_payment_ids=[item.id],
                        dialer_task_id=dialer_task.id,
                    )
                    continue
                get_julo_sentry_client().captureException()
                logger.error({'action': fn_name, 'state': 'payload generation', 'error': str(e)})
                continue

            formated_ai_rudder_payload.append(formatted_data)
            counter += 1

            # Check if the batch size is reached, then perform the bulk_create
            if counter >= batch_size:
                logger.info(
                    {
                        'action': fn_name,
                        'identifier': identifier,
                        'state': 'bulk_create',
                        'counter': counter,
                    }
                )
                AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)
                processed_data_count += counter
                # Reset the counter and the list for the next batch
                counter = 0
                formated_ai_rudder_payload = []

        # Insert any remaining objects in the final batch
        if formated_ai_rudder_payload:
            processed_data_count += counter
            logger.info(
                {
                    'action': fn_name,
                    'identifier': identifier,
                    'state': 'bulk_create_last_part',
                    'counter': counter,
                }
            )
            AIRudderPayloadTemp.objects.bulk_create(formated_ai_rudder_payload)

        if not processed_data_count:
            raise Exception("error when construct the data")

        logger.info(
            {
                'action': fn_name,
                'identifier': identifier,
                'state': 'constructed',
            }
        )
        return processed_data_count

    def get_unpaid_loan_description_list_pds(self, account_payment: AccountPayment):
        data = process_crm_unpaid_loan_account_details_list(account_payment)
        if not data:
            return ''

        detail_list = data[0]
        attributes = detail_list.get('attributes', {})
        result = ''
        for attribute in attributes:
            loan_id = attribute.get('loan_id', '')
            loan_amount = (
                attribute.get('loan_amount', '').replace("Rp", "").replace(".", "").strip()
            )
            total_due_amount = (
                attribute.get('calculated_total_due_amount', '')
                .replace("Rp", "")
                .replace(".", "")
                .strip()
            )
            total_paid_amount = attribute.get('total_paid_amount', '')
            transaction_method = attribute.get('transaction_method', '')
            unpaid_installment = attribute.get('installment_count', '')
            total_overdue_unpaid_due_amount = (
                attribute.get('calculated_overdue_unpaid_amount', '')
                .replace("Rp", "")
                .replace(".", "")
                .strip()
            )
            result += f"""
                    loan_id: {loan_id},
                    loan_amount: {loan_amount},
                    total_due_amount: {total_due_amount},
                    total_paid_amount: {total_paid_amount},
                    transaction_method: {transaction_method},
                    unpaid_installment: {unpaid_installment},
                    total_overdue_unpaid_due_amount: {total_overdue_unpaid_due_amount},
                """
            result += ' | '
        result = result.rstrip(' | ')
        return result

    def count_ineffective_phone_number(
        self, skiptrace_id: int, hangup_reason_id: int, last_call_date: date, task_name: str
    ):
        fn_name = 'count_ineffective_phone_number'
        logger.info(
            {
                'action': fn_name,
                'skiptrace_id': skiptrace_id,
                'hangup_reason_id': hangup_reason_id,
                'message': 'task start',
            }
        )
        fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True
        ).last()
        params = fs.parameters if fs else {}
        if not fs or not params:
            logger.warning(
                {
                    'action': fn_name,
                    'skiptrace_id': skiptrace_id,
                    'hangup_reason_id': hangup_reason_id,
                    'message': 'feature setting inactive or parametes is null',
                }
            )
            return
        if 'bttc' in task_name.lower():
            bucket_name = extract_bucket_name_dialer_bttc(task_name)
        else:
            bucket_name = extract_bucket_name_dialer(task_name)
        param_per_bucket = params.get(bucket_name, {})
        if 'consecutive_days' not in param_per_bucket:
            logger.info(
                {
                    'action': fn_name,
                    'skiptrace_id': skiptrace_id,
                    'hangup_reason_id': hangup_reason_id,
                    'message': 'this feature is not eligible for {} bucket'.format(bucket_name),
                }
            )
            return
        bucket_number = extract_bucket_number(bucket_name, 'bttc' in task_name.lower())
        unreachable_hangup_ids = param_per_bucket.get(
            'unreachable_hangup_ids', AiRudder.UNREACHABLE_HANGUP_IDS
        )
        consecutive_threshold_day = param_per_bucket.get('consecutive_days')
        threshold_refresh_days = param_per_bucket.get('threshold_refresh_days')
        inefffective_history = CollectionIneffectivePhoneNumber.objects.filter(
            skiptrace_id=skiptrace_id
        ).last()
        current_date = last_call_date
        yesterday = current_date - relativedelta(days=1)
        if hangup_reason_id in unreachable_hangup_ids:
            if not inefffective_history:
                flag_as_unreachable_date = current_date if 1 == consecutive_threshold_day else None
                CollectionIneffectivePhoneNumber.objects.create(
                    skiptrace_id=skiptrace_id,
                    last_unreachable_date=last_call_date,
                    ineffective_days=1,
                    flag_as_unreachable_date=flag_as_unreachable_date,
                )
                self.record_skiptrace_event_history(
                    skiptrace_id,
                    1,
                    bucket_number,
                    consecutive_threshold_day,
                    threshold_refresh_days,
                    SkiptraceHistoryEventName.UNREACHABLE,
                )
                logger.info(
                    {
                        'action': fn_name,
                        'skiptrace_id': skiptrace_id,
                        'hangup_reason_id': hangup_reason_id,
                        'message': 'task finished, create new history',
                    }
                )
                return

            last_unreachable = inefffective_history.last_unreachable_date
            # check is consecutive days
            if last_call_date > last_unreachable:
                yesterday_is_holiday = self.yesterday_is_holiday(yesterday)
                current_count = (
                    inefffective_history.ineffective_days + 1
                    if last_unreachable == yesterday or yesterday_is_holiday
                    else 1
                )
                flag_as_unreachable_date = (
                    current_date if current_count == consecutive_threshold_day else None
                )
                inefffective_history.update_safely(
                    ineffective_days=current_count,
                    last_unreachable_date=last_call_date,
                    flag_as_unreachable_date=flag_as_unreachable_date,
                )
                self.record_skiptrace_event_history(
                    skiptrace_id,
                    current_count,
                    bucket_number,
                    consecutive_threshold_day,
                    threshold_refresh_days,
                    SkiptraceHistoryEventName.UNREACHABLE,
                )
                logger.info(
                    {
                        'action': fn_name,
                        'skiptrace_id': skiptrace_id,
                        'hangup_reason_id': hangup_reason_id,
                        'message': 'task finished and count increase',
                    }
                )
                return
        else:
            if (
                inefffective_history
                and last_call_date >= inefffective_history.last_unreachable_date
            ):
                last_ineffective = inefffective_history.ineffective_days
                last_udate = inefffective_history.udate.date()
                inefffective_history.update_safely(
                    ineffective_days=0,
                    flag_as_unreachable_date=None,
                )
                logger.info(
                    {
                        'action': fn_name,
                        'skiptrace_id': skiptrace_id,
                        'hangup_reason_id': hangup_reason_id,
                        'message': 'task finished, and succeesed reset',
                    }
                )
                if last_ineffective == 0 and last_call_date == last_udate:
                    return
                self.record_skiptrace_event_history(
                    skiptrace_id,
                    0,
                    bucket_number,
                    consecutive_threshold_day,
                    threshold_refresh_days,
                    SkiptraceHistoryEventName.REACHABLE,
                )
                return

        logger.info(
            {
                'action': fn_name,
                'skiptrace_id': skiptrace_id,
                'hangup_reason_id': hangup_reason_id,
                'message': 'count no need to update',
            }
        )
        return


    def process_collection_priority_call(self, cdtd_experiment_data, bucket_name):
        fn_name = "proccess_collection_call_priority"
        customer_ids = cdtd_experiment_data.values_list('customer_id', flat=True)
        current_date = timezone.localtime(timezone.now()).date()
        priority_call_data = CollectionCallPriority.objects.filter(
            customer_id__in=list(customer_ids),
            partition_date=current_date,
        ).values('customer_id', 'sort_rank', 'phone_number')
        '''
            Expected results
            {
                customer_id: [(phone_number, sort_rank), (phone_number, sort_rank),]
            }
        '''

        if not priority_call_data:
            raise Exception("Data on Priority call not exists")

        from itertools import groupby
        from operator import itemgetter
        import copy

        # Sort by customer_id to ensure proper grouping
        sorted_priority_call_data = sorted(priority_call_data, key=itemgetter("customer_id"))
        priority_call_data_dict = {
            customer_id: [
                (format_e164_indo_phone_number(entry["phone_number"]), entry["sort_rank"])
                for entry in entries
            ]
            for customer_id, entries in groupby(
                sorted_priority_call_data, key=itemgetter("customer_id")
            )
        }

        formated_data = []
        batch_size = 5000
        counter = 0

        logger.info(
            {'action': fn_name, 'state': 'queried', 'total_data': cdtd_experiment_data.count()}
        )

        for item in cdtd_experiment_data:
            customer_id = item.customer_id
            duplicate_payload = None
            try:
                for collection_priority_data in priority_call_data_dict.get(customer_id, None):
                    sort_rank = collection_priority_data[1]
                    phone_number = collection_priority_data[0]
                    if duplicate_payload:
                        data = copy.deepcopy(duplicate_payload)
                        data.phonenumber = phone_number
                        data.sort_order = sort_rank
                    else:
                        data = self.construct_payload(
                            item,
                            bucket_name,
                            sort_rank,
                            phone_number,
                            is_jturbo_merge=False,
                            max_sent_other_number=0,
                        )
                        duplicate_payload = data

                    formated_data.append(data)
                    counter += 1

            except Exception as e:
                logger.error({'action': fn_name, 'state': 'payload generation', 'error': str(e)})
                continue

            if counter >= batch_size:
                logger.info(
                    {
                        'action': fn_name,
                        'state': 'bulk_create',
                        'counter': counter,
                    }
                )
                AIRudderPayloadTemp.objects.bulk_create(formated_data)

                counter = 0
                formated_data = []

        if not formated_data:
            logger.info(
                {
                    'action': fn_name,
                    'state': 'failure',
                    'counter': counter,
                }
            )
            raise Exception("Data for construct not success")

        logger.info(
            {
                'action': fn_name,
                'state': 'finish',
                'counter': counter,
            }
        )
        AIRudderPayloadTemp.objects.bulk_create(formated_data)
        return True

    def process_separate_bau_and_experiment_collection_priority(
        self, bau_populated_dialer_call_data, bucket_name
    ):
        fn_name = "process_separate_bau_and_experiment_collection_priority"
        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name,
                'state': 'querying',
            }
        )
        bau_customer_ids = bau_populated_dialer_call_data.values_list('customer_id', flat=True)
        current_date = timezone.localtime(timezone.now()).date()
        priority_call_experiment_customer_ids = list(
            CollectionCallPriority.objects.filter(
                customer_id__in=list(bau_customer_ids),
                partition_date=current_date,
            ).values_list('customer_id', flat=True)
        )

        if not priority_call_experiment_customer_ids:
            logger.info(
                {
                    'action': fn_name,
                    'identifier': bucket_name,
                    'state': 'queried',
                }
            )
            return bau_populated_dialer_call_data, CollectionDialerTemporaryData.objects.none()
        experiment_data = bau_populated_dialer_call_data.filter(
            customer_id__in=priority_call_experiment_customer_ids
        )
        bau_populated_dialer_call_data = bau_populated_dialer_call_data.exclude(
            customer_id__in=priority_call_experiment_customer_ids
        )
        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name,
                'state': 'queried',
                'data': {
                    'bau': len(bau_populated_dialer_call_data),
                    'experiment': len(experiment_data),
                },
            }
        )
        return bau_populated_dialer_call_data, experiment_data

    def process_sorting_riskier_experiment(
        self, bucket_name, experiment_bucket_name, eligible_customer_id_tails
    ):
        fn_name = "process_sorting_riskier_experiment"
        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name,
                'state': 'querying',
            }
        )
        eligible_experiment_data = AIRudderPayloadTemp.objects.filter(
            bucket_name=bucket_name, sort_order__isnull=False
        ).extra(
            where=["RIGHT(customer_id::text, 1) IN %s"], params=[tuple(eligible_customer_id_tails)]
        )
        if not eligible_experiment_data:
            logger.info(
                {
                    'action': fn_name,
                    'identifier': bucket_name,
                    'state': 'failed',
                    'message': 'not found eligible data for experiment',
                }
            )
            return False

        current_date = timezone.localtime(timezone.now()).date()
        sort_order_experiment = (
            PdCollectionModelResult.objects.filter(
                account_payment_id__in=list(
                    eligible_experiment_data.values_list('account_payment_id', flat=True)
                ),
                prediction_date=current_date,
            )
            .annotate(
                order_custom=ExpressionWrapper(
                    F("prediction_before_call") * F("due_amount"), output_field=FloatField()
                )
            )
            .order_by("-order_custom")
            .values("account_payment_id")
        )
        ranked_results = {
            r["account_payment_id"]: rank + 1 for rank, r in enumerate(sort_order_experiment)
        }
        if not ranked_results:
            logger.info(
                {
                    'action': fn_name,
                    'identifier': bucket_name,
                    'state': 'failed',
                    'message': 'not found rank eligible data for experiment',
                }
            )
            return False

        for payload in eligible_experiment_data:
            payload.sort_order = ranked_results.get(payload.account_payment_id, None)
            payload.bucket_name = experiment_bucket_name

        bulk_update(
            eligible_experiment_data, update_fields=['sort_order', 'bucket_name'], batch_size=500
        )
        experiment_setting = get_experiment_setting_by_code(
            ExperimentConst.COLLECTION_SORT_RISKIER_CUSTOMER
        )
        experiment_data = []
        final_data = AIRudderPayloadTemp.objects.filter(
            bucket_name__in=[bucket_name, experiment_bucket_name]
        )
        for item in final_data:
            experiment_group = 'control'
            if item.bucket_name == experiment_bucket_name:
                experiment_group = 'experiment'
            experiment_data.append(
                ExperimentGroup(
                    account_id=item.account_id,
                    account_payment_id=item.account_payment_id,
                    experiment_setting=experiment_setting,
                    group=experiment_group,
                )
            )

        ExperimentGroup.objects.bulk_create(experiment_data, batch_size=2000)
        logger.info({'action': fn_name, 'identifier': bucket_name, 'state': 'finish'})
        return True

    def process_collection_priority_call_v2(self, bucket_name_list, experiment_bucket_dict):
        import pandas as pd
        fn_name = "process_collection_priority_call_v2"
        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name_list,
                'state': 'querying',
            }
        )
        qs = (
            AIRudderPayloadTemp.objects.filter(bucket_name__in=bucket_name_list)
            .order_by('sort_order')
            .values_list('account_id', flat=True)
        )
        data = list(dict.fromkeys(qs))
        if not data:
            raise Exception("Data on Priority call not exists")

        df = pd.DataFrame(data)
        # round robin only take the odd rows
        odd_rows = df.iloc[1::2]
        experiment_account_ids = odd_rows[0].tolist()
        experiment_data = AIRudderPayloadTemp.objects.filter(
            bucket_name__in=bucket_name_list,
            account_id__in=experiment_account_ids,
        ).order_by('sort_order')
        account_payment_ids_experiment = []
        experiment = []
        experiment_bucket_list = {}
        for row in experiment_data:
            # Handle column value movement
            phone_numbers = [row.mobile_phone_2, row.no_telp_pasangan, row.telp_perusahaan]
            # Shift phone number to the left if any phone numbmer is null or blank
            non_empty = [v for v in phone_numbers if v]  # Collect non-empty values
            phone_numbers[:] = non_empty + [None] * (len(phone_numbers) - len(non_empty))
            # Update the row with the new values
            row.mobile_phone_2, row.no_telp_pasangan, row.telp_perusahaan = phone_numbers
            experiment_bucket_name = experiment_bucket_dict.get(row.bucket_name, row.bucket_name)
            experiment_bucket_list[experiment_bucket_name] = row.bucket_name
            row.bucket_name = experiment_bucket_name
            experiment.append(row)
            account_payment_ids_experiment.append(row.account_payment_id)

        if not account_payment_ids_experiment:
            raise Exception("Data on Priority call not exists")

        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name_list,
                'state': 'updating',
            }
        )
        bulk_update(
            experiment,
            update_fields=['mobile_phone_2', 'no_telp_pasangan', 'telp_perusahaan', 'bucket_name'],
            batch_size=500,
        )
        # for handling double handler on dialer
        CollectionDialerTemporaryData.objects.filter(
            account_payment_id__in=account_payment_ids_experiment
        ).delete()

        logger.info(
            {
                'action': fn_name,
                'identifier': bucket_name_list,
                'state': 'finish',
            }
        )
        return experiment_bucket_list

    def write_collection_priority_call_v2_log(
        self, bucket_name, experiment_bucket_name, experiment_setting_id
    ):
        experiment_data = []
        final_data = AIRudderPayloadTemp.objects.filter(
            bucket_name__in=[bucket_name, experiment_bucket_name]
        )
        for item in final_data:
            experiment_group = 'control'
            if item.bucket_name == experiment_bucket_name:
                experiment_group = 'experiment'
            experiment_data.append(
                ExperimentGroup(
                    account_id=item.account_id,
                    account_payment_id=item.account_payment_id,
                    experiment_setting_id=experiment_setting_id,
                    group=experiment_group,
                )
            )

        ExperimentGroup.objects.bulk_create(experiment_data, batch_size=2000)
        return True

    def yesterday_is_holiday(self, yesterday_date: date):
        date_str = yesterday_date.strftime("%Y-%m-%d")
        redis_client = get_redis_client()
        redis_key = RedisKey.YESTERDAY_IS_HOLIDAY.format(date_str)
        cache_redis = redis_client.get(redis_key)
        if not cache_redis:
            now = timezone.localtime(timezone.now())
            end_time = now.replace(hour=23, minute=59, second=59)
            expiry_in_seconds = end_time - now
            is_holiday = Holiday.objects.filter(holiday_date=yesterday_date).exists()
            redis_client.set(redis_key, is_holiday, expiry_in_seconds)
            return is_holiday
        return True if cache_redis == 'True' else False

    def record_skiptrace_event_history(
        self,
        skiptrace_id: int,
        unreachable_days: int,
        bucket_number: int,
        consecutive_config_days: int,
        refresh_config_days: int,
        event_name: str,
    ):
        today = timezone.localtime(timezone.now()).date()
        skiptrace = Skiptrace.objects.filter(pk=skiptrace_id).last()
        CollectionSkiptraceEventHistory.objects.create(
            event_date=today,
            skiptrace_id=skiptrace_id,
            customer_id=skiptrace.customer.id,
            unreachable_days=unreachable_days,
            bucket_number=bucket_number,
            consecutive_config_days=consecutive_config_days,
            refresh_config_days=refresh_config_days,
            event_name=event_name,
        )
        return

    def get_call_results_data_by_task_id_with_retry_mechasm(
        self,
        task_id: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 0,
        total_only: bool = False,
        offset: int = 0,
        call_id: str = '',
        retries_time: int = 0,
        need_customer_info: bool = False,
    ) -> List:
        try:
            if not task_id:
                raise Exception(
                    'AI Rudder Service error: tasks id is null for this time range {} - {}'.format(
                        str(start_time), str(end_time)
                    )
                )

            response = self.AI_RUDDER_PDS_CLIENT.query_task_detail(
                task_id=task_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                offset=offset,
                call_id=call_id,
                retries_time=retries_time,
                need_customer_info=need_customer_info,
            )
            body = response.get('body', None)
            if not body:
                logger.info(
                    {
                        'action': 'AI Rudder PDS services get_call_results_data_by_task_id_with_retry_mechasm',
                        'message': 'response dont have body',
                    }
                )
                return []

            if total_only:
                total = body.get('total', None)
                if not total:
                    logger.info(
                        {
                            'action': 'AI Rudder PDS services get_call_results_data_by_task_id_with_retry_mechasm',
                            'message': 'response body dont have column total',
                        }
                    )
                    return 0

                return total

            list_data = body.get('list', None)
            if not list_data:
                logger.info(
                    {
                        'action': 'AI Rudder PDS services get_call_results_data_by_task_id_with_retry_mechasm',
                        'message': 'response body dont have column list',
                    }
                )
                return []

            return list_data
        except Exception as err:
            logger.info(
                {
                    'action': 'AI Rudder PDS services get_call_results_data_by_task_id_with_retry_mechasm',
                    'error_message': str(err),
                }
            )
            if retries_time < 3:
                retries_time += 1
                self.get_call_results_data_by_task_id_with_retry_mechasm(
                    task_id,
                    start_time,
                    end_time,
                    limit=1,
                    total_only=True,
                    retries_time=retries_time,
                )
            else:
                return

    def get_eligible_phone_number_list_b5(
        self,
        customer_id: int,
        phone_numbers: dict,
        bucket_number: int = 0,
        ineffective_consecutive_days: int = 0,
        ineffective_refresh_days: int = 0,
    ) -> dict:
        from juloserver.minisquad.tasks2.dialer_system_task import (
            reset_count_ineffective_phone_numbers_by_skiptrace_ids,
            record_skiptrace_event_history_task,
        )

        inefffective_phone_numbers = []
        today = timezone.localtime(timezone.now()).date()
        if not ineffective_consecutive_days:
            return phone_numbers

        phone_number_list = [phone_number for _, phone_number in phone_numbers.items()]
        skiptraces = Skiptrace.objects.filter(
            customer=customer_id, phone_number__in=phone_number_list
        ).values_list('pk', 'phone_number')
        skiptrace_dict = {item[0]: item[1] for item in skiptraces}
        skiptrace_ids = [item[0] for item in skiptraces]
        inefffective_skiptraces = CollectionIneffectivePhoneNumber.objects.filter(
            skiptrace_id__in=skiptrace_ids,
            ineffective_days__gte=ineffective_consecutive_days,
        ).values_list('pk', 'skiptrace_id')
        inefffective_ids = []
        inefffective_skiptrace_ids = []
        for item in inefffective_skiptraces:
            inefffective_ids.append(item[0])
            inefffective_skiptrace_ids.append(item[1])
        # refresh ineffective days
        if ineffective_refresh_days:
            reset_count_ineffective_phone_numbers_by_skiptrace_ids.delay(
                skiptrace_ids,
                ineffective_refresh_days,
            )

        if not inefffective_skiptrace_ids:
            return phone_numbers

        # just in case when bucket changes
        CollectionIneffectivePhoneNumber.objects.filter(
            pk__in=inefffective_ids,
            flag_as_unreachable_date__isnull=True,
        ).update(flag_as_unreachable_date=today)
        record_skiptrace_event_history_task.delay(
            inefffective_skiptrace_ids,
            ineffective_refresh_days,
            ineffective_consecutive_days,
            bucket_number,
        )
        inefffective_phone_numbers = [
            val for key, val in skiptrace_dict.items() if key in inefffective_skiptrace_ids
        ]
        phone_number_filtered = {
            key: '' if val in inefffective_phone_numbers else val
            for key, val in phone_numbers.items()
        }
        phone_number = (
            phone_number_filtered.get('phonenumber')
            or phone_number_filtered.get('mobile_phone_2')
            or phone_number_filtered.get('no_telp_pasangan')
            or phone_number_filtered.get('telp_perusahaan')
        )
        phone_number_filtered.update(phonenumber=phone_number)
        return phone_number_filtered


class AiRudderPDSSettingManager:
    """
    This class is managed the configuration used per bucket_name of the AiRudder PDS.
    It is not recommended to have a singleton of this class in the whole application life-cycle.
    Because the feature setting object is stored in a variable.

    It is okay to have this object in a single HTTP/celery request.

    The responsibilities of this class are
    * Manage the configuration in the feature setting

    The managed feature names are
    * FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG (ai_rudder_tasks_strategy_config)
    * FeatureNameConst.SENDING_RECORDING_CONFIGURATION (sending_recording_configuration)
    """

    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self._setting_map = {}

    def _get_setting(self, feature_name: str) -> Optional[FeatureSetting]:
        """
        Get the active feature setting from the database and cache it in the memory.
        Args:
            feature_name (str): the feature setting name.
        Returns:
            FeatureSetting|None: the active feature setting.
        """
        if feature_name not in self._setting_map:
            self._setting_map[feature_name] = FeatureSetting.objects.get_or_none(
                feature_name=feature_name,
                is_active=True,
            )
        return self._setting_map[feature_name]

    def get_strategy_config(self) -> Optional[Dict]:
        """
        Get the strategy configuration for the AiRudder PDS.
        Returns:
            Dict|None: the strategy configuration in the parameters.
        """
        setting = self._get_setting(FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG)
        if setting is None:
            return None
        return setting.parameters.get(self.bucket_name)

    def is_sending_recording_enabled(self) -> bool:
        """
        Check if the recording sending is enabled for the bucket_name.
        Refer to "juloserver.collops_qa_automation.tasks.upload_recording_file_to_airudder_task"
        Returns:
            bool: the recording sending is enabled or not.
        """
        setting = self._get_setting(JuloFeatureNameConst.SENDING_RECORDING_CONFIGURATION)
        if setting is None:
            return False

        return self.bucket_name in setting.parameters.get('buckets', [])

    @transaction.atomic()
    def remove_config_from_setting(self):
        """
        Remove the bucket name from all feature setting
        """
        self.remove_strategy_config_setting()
        self.remove_sending_recording_setting()
        self._setting_map = {}

    @transaction.atomic()
    def save_strategy_config(self, strategy_config: dict):
        """
        Save the strategy configuration for the AiRudder PDS.
        Args:
            strategy_config (dict): the strategy configuration. For the dict content please refer to
                * the prod or non-prod feature setting parameter.
                * AiRudderConfigSerializer class definition.
        """
        setting = (
            FeatureSetting.objects.select_for_update()
            .filter(feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG, is_active=True)
            .first()
        )
        if setting is None:
            return

        if self.bucket_name in setting.parameters:
            return

        from juloserver.integapiv1.serializers import AiRudderConfigSerializer

        serializer = AiRudderConfigSerializer(strategy_config)

        setting.parameters[self.bucket_name] = serializer.data
        setting.save()

    @transaction.atomic()
    def enable_sending_recording(self):
        """
        Enable the recording sending for the bucket_name.
        """
        setting = (
            FeatureSetting.objects.select_for_update()
            .filter(
                feature_name=JuloFeatureNameConst.SENDING_RECORDING_CONFIGURATION, is_active=True
            )
            .first()
        )
        if setting is None:
            return

        if self.bucket_name in setting.parameters['buckets']:
            return

        if self.bucket_name not in setting.parameters['buckets']:
            setting.parameters['buckets'].append(self.bucket_name)
            setting.save()

    @transaction.atomic()
    def remove_strategy_config_setting(self):
        setting = (
            FeatureSetting.objects.select_for_update()
            .filter(
                feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG,
            )
            .first()
        )
        if setting is None:
            return

        logger.info(
            {
                "action": "AiRudderPDSSettingManager.remove_strategy_config_setting",
                "message": "removing bucket from setting",
                "bucket_name": self.bucket_name,
                "current_parameters": setting.parameters,
            }
        )
        if self.bucket_name in setting.parameters:
            setting.parameters.pop(self.bucket_name, None)
            setting.save()

    @transaction.atomic()
    def remove_sending_recording_setting(self):
        setting = (
            FeatureSetting.objects.select_for_update()
            .filter(
                feature_name=JuloFeatureNameConst.SENDING_RECORDING_CONFIGURATION,
            )
            .first()
        )
        if setting is None:
            return

        logger.info(
            {
                "action": "AiRudderPDSSettingManager.remove_sending_recording_setting",
                "message": "removing bucket from setting",
                "bucket_name": self.bucket_name,
                "current_parameters": setting.parameters,
            }
        )
        if self.bucket_name in setting.parameters['buckets']:
            setting.parameters['buckets'].remove(self.bucket_name)
            setting.save()


class AiRudderPDSSender:
    """
    The responsibilities of this class are
    * Send the request data to AiRudder.

    Use "send_task()" to trigger the PDS task creation.
    """

    def __init__(
        self,
        bucket_name: str,
        customer_list: List[dict],
        strategy_config: dict,
        callback_url: str,
        batch_number: int = 0,
        source: str = '',
    ):
        """
        Initialize the AiRudderPDSSender objects
        Args:
            bucket_name (bucket_name): the bucket name of the AiRudder PDS.
            customer_list (list[dict]): The customer data that will be sent to AiRudder.
                Make sure all the customer attribute has been registered to the system.
            strategy_config (dict): the AiRudder strategy configuration. For the dict content please refer to
                * the prod or non-prod feature setting parameter "ai_rudder_tasks_strategy_config".
                * AiRudderConfigSerializer class definition.
            callback_url (str): the callback url for AiRudder to send the call result.
            batch_number (int): the batch number of the task. Default is 0.
        """
        self.bucket_name = bucket_name
        self.batch_number = batch_number
        self.strategy_config = self._validate_strategy_config(strategy_config)
        self.group_name = self.strategy_config["groupName"]
        self.customer_list = self._validate_customer_list(customer_list)
        self.source = source

        self.callback_url = None
        if callback_url:
            encoded_bytes = base64.b64encode(callback_url.encode('utf-8'))
            self.callback_url = encoded_bytes.decode('utf-8')

        self._airudder_client = None
        self._task_name = None

    @staticmethod
    def _validate_strategy_config(raw_strategy_config: dict) -> dict:
        """
        Validate the strategy configuration.
        """
        if not raw_strategy_config:
            raise Exception("Strategy configuration is empty")

        from juloserver.integapiv1.serializers import AiRudderConfigSerializer

        serializer = AiRudderConfigSerializer(data=raw_strategy_config)
        serializer.is_valid(raise_exception=True)
        strategy_config = serializer.validated_data

        # Adjust the start_time to match the need of AiRudder Format.
        current_time = timezone.localtime(timezone.now())
        start_time = strategy_config.get('start_time')
        end_time = strategy_config.get('end_time')
        if start_time is None:
            start_time = current_time
        start_time = current_time.replace(hour=start_time.hour, minute=start_time.minute, second=0)
        end_time = current_time.replace(hour=end_time.hour, minute=end_time.minute, second=0)

        if start_time <= current_time:
            start_time = current_time.replace(second=0) + timedelta(minutes=2)

        if end_time <= start_time:
            raise ValueError("End time must be greater than start time")

        strategy_config['start_time'] = start_time
        strategy_config['end_time'] = end_time

        rest_times = strategy_config.get('rest_times', [[time(12, 0), time(13, 0)]])
        formated_rest_times = []
        for rest_time in rest_times:
            formated_rest_times.append(
                {
                    "start": rest_time[0].isoformat(),
                    "end": rest_time[1].isoformat(),
                }
            )
        strategy_config['restTimes'] = formated_rest_times
        if "rest_times" in strategy_config:
            del strategy_config["rest_times"]

        if int(strategy_config.get('autoSlotFactor', 0)) == 0:
            strategy_config['slotFactor'] = strategy_config.get('slotFactor', 2.5)

        if not strategy_config.get('autoQA', ''):
            strategy_config['autoQA'] = 'Y'
            strategy_config['qaConfigId'] = 142

        strategy_config['qaLimitLength'] = strategy_config.get('qaLimitLength', 0)
        strategy_config['qaLimitRate'] = strategy_config.get('qaLimitRate', 100)

        return strategy_config

    @staticmethod
    def _validate_customer_list(customer_list: List[dict]) -> List[dict]:
        """
        Convert all customer data to string
        Args:
            customer_list (List[dict]): customer list

        Returns:
            customer list
        """
        for customer in customer_list:
            for key, value in customer.items():
                if value is None:
                    customer[key] = ''
                elif isinstance(value, date) or isinstance(value, time):
                    customer[key] = value.isoformat()
                elif not isinstance(value, str):
                    customer[key] = str(value)
        return customer_list

    def set_client(self, client: AIRudderPDSClient):
        """
        Specify the client class to be used for sending the request.
        Args:
            client (AIRudderPDSClient): The PDS client class
        """
        self._airudder_client = client

    def _client(self) -> AIRudderPDSClient:
        """
        Get the client class to be used for sending the request.
        Returns:
            AIRudderPDSClient: The PDS client class
        """
        if self._airudder_client is None:
            self._airudder_client = get_julo_ai_rudder_pds_client()
        return self._airudder_client

    def task_name(self):
        if self._task_name:
            return self._task_name

        current_time = timezone.localtime(timezone.now())
        task_name = "{}__{}__{}".format(
            self.bucket_name,
            self.batch_number,
            current_time.strftime('%Y%m%d-%H%M'),
        )
        if self.source:
            task_name = "{}__{}".format(task_name, self.source)

        setting_env = settings.ENVIRONMENT.upper()
        if setting_env != 'PROD':
            task_name = "{}__{}".format(setting_env, task_name)

        self._task_name = task_name
        return task_name

    def send_task(self) -> str:
        """
        Send and create the task to AiRudder. No DB operation is done in this method.
        Returns:
            str: the task_id obtained from the AiRudder Client.
        """
        fn_name = "AiRudderPDSSender.send_task"
        airudder_client = self._client()
        task_name = self.task_name()
        start_time = self.strategy_config.get('start_time')
        end_time = self.strategy_config.get('end_time')

        response = airudder_client.create_task(
            task_name=task_name,
            start_time=start_time,
            end_time=end_time,
            group_name=self.group_name,
            list_contact_to_call=self.customer_list,
            call_back_url=self.callback_url,
            strategy_config=self.strategy_config,
        )

        response_body = response.get('body')
        if not response_body:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response)
                )
            )

        task_id = response_body.get("taskId")
        if not task_id:
            raise Exception(
                "{} not return correct response. returned response {}".format(
                    fn_name, str(response_body)
                )
            )

        return task_id

    def account_payment_ids(self):
        return [
            customer.get('account_payment_id')
            for customer in self.customer_list
            if customer.get('account_payment_id')
        ]


class AiRudderPDSManager:
    """
    The responsibilities of this class is to manage the AiRudder PDS task creation.
    The class depends on the AiRudderPDSSender and AiRudderPDSSettingManager.
    """

    MAX_RETRIES = 3

    class NeedRetryException(Exception):
        pass

    class NoNeedRetryException(Exception):
        pass

    def __init__(
        self,
        dialer_task: DialerTask,
        airudder_sender: AiRudderPDSSender,
    ):
        self.dialer_task = dialer_task
        self.airudder_sender = airudder_sender

    def create_task(self, batch_number: int = 0, retry_number: int = 0) -> Optional[str]:
        """
        Create the task to AiRudder. It will raise an exception if the task creation is failed.
        The retry mechanism is implemented outside the method.

        Args:
            batch_number (int): the current batch number.
            retry_number (int): the current retry number.

        Returns:
            str: the task_id obtained from the AiRudder Client.

        Raises:
            NeedRetryException: if the retry is needed.
            NoNeedRetryException: if the retry is not needed.
        """
        record_history_dialer_task_event(
            dict(
                dialer_task=self.dialer_task,
                status=DialerTaskStatus.UPLOADING_PER_BATCH.format(batch_number, retry_number),
            ),
            is_update_status_for_dialer_task=False,
        )

        try:
            task_id = self.airudder_sender.send_task()
        except (ConnectionError, Timeout) as e:
            self._retrying(e, retry_number, batch_number)
            return
        except HTTPError as e:
            http_resp = e.response
            if not http_resp:
                self._retrying(e, retry_number, batch_number)
                return

            if http_resp.status_code == 429 or http_resp.status_code >= 500:
                self._retrying(e, retry_number, batch_number)
                return

            raise e

        # Store customer data to ops.ai_rudder_payload_temp
        self._store_to_airudder_payload_temp()

        from juloserver.minisquad.tasks2 import write_log_for_report_async

        write_log_for_report_async.delay(
            bucket_name=self.airudder_sender.bucket_name,
            task_id=task_id,
            account_payment_ids=self.airudder_sender.account_payment_ids(),
            dialer_task_id=self.dialer_task.id,
        )

        record_history_dialer_task_event(
            dict(
                dialer_task=self.dialer_task,
                status=DialerTaskStatus.UPLOADED_PER_BATCH.format(batch_number),
            ),
            is_update_status_for_dialer_task=False,
        )

        return task_id

    def _store_to_airudder_payload_temp(self):
        now = timezone.localtime(timezone.now())
        customer_list = self.airudder_sender.customer_list

        existing_account_payment_ids = AIRudderPayloadTemp.objects.filter(
            account_payment_id__in=self.airudder_sender.account_payment_ids(),
            bucket_name=self.airudder_sender.bucket_name,
        ).values_list('account_payment_id', flat=True)

        airudder_payload_temps = []
        for customer in customer_list:
            account_payment_id = customer['account_payment_id']
            if account_payment_id in existing_account_payment_ids:
                continue

            # Remove empty string value
            customer = {key: value for key, value in customer.items() if value != ''}

            airudder_payload_temps.append(
                AIRudderPayloadTemp(
                    account_payment_id=customer.get('account_payment_id'),
                    account_id=customer.get('account_id'),
                    customer_id=customer.get('customer_id'),
                    phonenumber=customer.get('phonenumber'),
                    nama_customer=customer.get('nama_customer'),
                    nama_perusahaan=customer.get('nama_perusahaan'),
                    posisi_karyawan=customer.get('posisi_karyawan'),
                    dpd=customer.get('dpd'),
                    total_denda=customer.get('total_denda'),
                    total_due_amount=customer.get('total_due_amount'),
                    total_outstanding=customer.get('total_outstanding'),
                    angsuran_ke=customer.get('angsuran_ke'),
                    tanggal_jatuh_tempo=customer.get('tanggal_jatuh_tempo'),
                    nama_pasangan=customer.get('nama_pasangan'),
                    nama_kerabat=customer.get('nama_kerabat'),
                    hubungan_kerabat=customer.get('hubungan_kerabat'),
                    alamat=customer.get('alamat'),
                    kota=customer.get('kota'),
                    jenis_kelamin=customer.get('jenis_kelamin'),
                    tgl_lahir=customer.get('tgl_lahir'),
                    tgl_gajian=customer.get('tgl_gajian'),
                    tujuan_pinjaman=customer.get('tujuan_pinjaman'),
                    jumlah_pinjaman=customer.get('jumlah_pinjaman'),
                    tgl_upload=datetime.strftime(now, "%Y-%m-%d"),
                    va_bca=customer.get('va_bca'),
                    va_permata=customer.get('va_permata'),
                    va_maybank=customer.get('va_maybank'),
                    va_alfamart=customer.get('va_alfamart'),
                    va_indomaret=customer.get('va_indomaret'),
                    va_mandiri=customer.get('va_mandiri'),
                    tipe_produk=customer.get('tipe_produk'),
                    last_pay_date=customer.get('last_pay_date'),
                    last_pay_amount=customer.get('last_pay_amount'),
                    partner_name=customer.get('partner_name'),
                    last_agent=customer.get('last_agent'),
                    last_call_status=customer.get('last_call_status'),
                    refinancing_status=customer.get('refinancing_status'),
                    activation_amount=customer.get('activation_amount'),
                    program_expiry_date=customer.get('program_expiry_date'),
                    customer_bucket_type=customer.get('customer_bucket_type'),
                    promo_untuk_customer=customer.get('promo_untuk_customer'),
                    zip_code=customer.get('zip_code'),
                    mobile_phone_2=customer.get('mobile_phone_2'),
                    telp_perusahaan=customer.get('telp_perusahaan'),
                    mobile_phone_1_2=customer.get('mobile_phone_1_2'),
                    mobile_phone_2_2=customer.get('mobile_phone_2_2'),
                    no_telp_pasangan=customer.get('no_telp_pasangan'),
                    mobile_phone_1_3=customer.get('mobile_phone_1_3'),
                    mobile_phone_2_3=customer.get('mobile_phone_2_3'),
                    no_telp_kerabat=customer.get('no_telp_kerabat'),
                    mobile_phone_1_4=customer.get('mobile_phone_1_4'),
                    mobile_phone_2_4=customer.get('mobile_phone_2_4'),
                    bucket_name=self.airudder_sender.bucket_name,
                    sort_order=customer.get('sort_order'),
                    angsuran_per_bulan=customer.get('angsuran_per_bulan'),
                    uninstall_indicator=customer.get('uninstall_indicator'),
                    fdc_risky=customer.get('fdc_risky'),
                    potensi_cashback=customer.get('potensi_cashback'),
                    total_seluruh_perolehan_cashback=customer.get(
                        'total_seluruh_perolehan_cashback'
                    ),
                    status_refinancing_lain=customer.get('status_refinancing_lain'),
                    application_id=customer.get('application_id'),
                )
            )

        AIRudderPayloadTemp.objects.bulk_create(airudder_payload_temps, batch_size=1000)

    def _retrying(self, e, retry_number: int, batch_number: int = 0):
        """
        Retry workflow
        Args:
            e (Exception): the exception that will be raised.
            retry_number (int):
            batch_number (int):
        Raises:
            NeedRetryException: if the retry is needed.
            NoNeedRetryException: if the retry is not needed.
        """
        if retry_number >= self.MAX_RETRIES:
            record_history_dialer_task_event(
                dict(
                    dialer_task=self.dialer_task,
                    status=DialerTaskStatus.FAILURE_BATCH.format(batch_number),
                    error=str(e),
                ),
                error_message=str(e),
            )
            raise self.NoNeedRetryException("max retry has been reached") from e

        record_history_dialer_task_event(
            dict(
                dialer_task=self.dialer_task,
                status=DialerTaskStatus.PROCESS_FAILED_ON_PROCESS_RETRYING,
                error=str(e),
            ),
            error_message=str(e),
            is_update_status_for_dialer_task=False,
        )
        raise self.NeedRetryException("need to retry") from e

import json
import logging
import os
import io
import csv
from urllib.parse import urlparse, parse_qs
from datetime import datetime

from babel.dates import format_date, format_datetime
from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_protect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser

from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.account_payment.services.account_payment_related import (
    construct_loan_in_account_payment_listv2,
    get_late_fee_amount_by_account_payment,
)
from juloserver.apiv2.serializers import SkipTraceSerializer
from juloserver.apiv3.models import DistrictLookup, SubDistrictLookup
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.omnichannel.tasks.customer_related import send_dialer_blacklist_customer_attribute
from juloserver.minisquad.services2.ai_rudder_pds import AIRudderPDSServices
from juloserver.minisquad.utils import (
    collection_detokenize_sync_object_model,
    get_feature_setting_parameters,
)
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.sdk.serializers import CustomerSerializer
from juloserver.sdk.services import xls_to_dict
from juloserver.collection_vendor.constant import CollectionVendorAssignmentConstant
from juloserver.dana.models import DanaSkiptraceHistory
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.julo.constants import InAppPTPDPD
from juloserver.julo.models import (
    Loan,
    SkiptraceResultChoice,
    Skiptrace,
    PaymentNote,
    SkiptraceHistory,
    PaymentMethod,
    FeatureSetting,
    InAppPTPHistory,
    Customer,
    Image,
    PaymentMethodLookup,
    Application,
    PTP,
)
from juloserver.julo.services import ptp_create, ptp_create_v2
from juloserver.julo.tasks import update_skiptrace_number
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.minisquad.constants import (
    DialerTaskStatus,
    IntelixResultChoiceMapping,
    DialerTaskType,
    IntelixTeam,
    FeatureNameConst,
    SkiptraceContactSource,
    AiRudder,
    DialerSystemConst,
)
from juloserver.minisquad.models import (
    DialerTask,
    CallbackPromiseApp,
    intelixBlacklist,
)
from juloserver.minisquad.serializers import (
    IntelixUploadCallSerializer,
    IntelixCallResultsRealtimeSerializer,
    CallRecordingDetailSerializer,
    GenesysManualUploadCallSerializer,
    IntelixBlackListAccountPhoneSerializer,
    IntelixBlackListAccountSerializer,
    BulkCancelCallForm, BulkChangeUserRoleForm,
)
from juloserver.minisquad.tasks import (
    trigger_insert_col_history,
    bulk_change_users_role_async,
    sent_webhook_to_field_collection_service_by_category,
)
from juloserver.minisquad.services2.intelix import (
    update_intelix_callback, construct_status_and_status_group,
    store_call_recording_details_from_intelix,
    create_history_dialer_task_event,
)
from juloserver.minisquad.tasks import (
    store_intelix_call_result,
    process_download_manual_upload_intelix_csv_files,
    do_delete_download_manual_upload_intelix_csv,
    remove_phone_number_task,
)
from juloserver.minisquad.services import (
    exclude_payment_from_daily_upload,
    account_bucket_name_definition,
    block_intelix_comms_ptp)
from juloserver.minisquad.utils import (
    collection_detokenize_sync_object_model,
    collection_detokenize_sync_kv_in_bulk,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    not_found_response,
    general_error_response,
    forbidden_error_response,
)
from juloserver.followthemoney.utils import (
    server_error_response,
)
from juloserver.collection_vendor.task import assign_agent_for_bucket_5, \
    assign_agent_for_julo_one_bucket_5
from juloserver.account.models import Account, AdditionalCustomerInfo
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.minisquad.tasks2.intelix_task import (
    create_failed_call_results, download_call_recording_via_sftp)
from juloserver.minisquad.tasks2.genesys_task import store_genesys_call_results
import pytz
from juloserver.portal.object import (
    julo_login_required_group,
    julo_login_required,
    julo_login_required_multigroup)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from django.shortcuts import render
from django.db import connection
from django.db.models import Prefetch, Q
from juloserver.minisquad.serializers import IntelixFilterSerializer
from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.constants import FilterQueryBucket, AiRudder
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from juloserver.collection_vendor.celery_progress import Progress
from juloserver.account_payment.models import AccountPayment
from juloserver.grab.models import GrabSkiptraceHistory
from juloserver.minisquad.services2.phone_number_related import RemovePhoneNumberParamDTO
from juloserver.minisquad.tasks2.dialer_system_task import (
    bulk_delete_phone_numbers_from_dialer,
    process_airudder_store_call_result,
    process_data_generation_b5,
    process_data_generation_b6,
    trigger_data_generation_bucket_current,
    trigger_data_generation_bttc_bucket1,
)
from juloserver.grab.tasks import send_grab_failed_deduction_slack
from juloserver.minisquad.tasks2.dialer_system_task_grab import grab_process_airudder_store_call_result
from juloserver.julo.clients import get_julo_sentry_client
from rest_framework.permissions import BasePermission

from juloserver.urlshortener.services import get_payment_detail_shortened_url
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.moengage.tasks import trigger_update_risk_segment_customer_attribute_for_moengage
from types import SimpleNamespace
from juloserver.waiver.services.account_related import can_account_get_refinancing_centralized
logger = logging.getLogger(__name__)


class IsDataPlatformToken(BasePermission):
    def has_permission(self, request, view):
        specific_username = 'dataplatform'

        # Check if the user is authenticated
        if not request.user.is_authenticated:
            return False

        # Check if the username matches
        if request.user.username != specific_username:
            return False

        return True


class IntelixUploadCallResults(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = IntelixUploadCallSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data_reader = data['csv_file']
        uploader_email = data['email_address']
        store_intelix_call_result.delay(list(data_reader), uploader_email)
        return success_response()


class UpdateIntelixSkiptraceDataAgentLevel(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = IntelixCallResultsRealtimeSerializer

    def post(self, request):
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_AGENT_LEVEL,
            error=''
        )
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=serializer.errors,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                serializer.errors, DialerTaskStatus.FAILURE, dialer_task
            )
            serializer.is_valid(raise_exception=True)

        token = request.META['HTTP_AUTHORIZATION']
        if not token == settings.INTELIX_JULO_TOKEN:
            error_msg = 'Invalid authentication credentials'
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=error_msg,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                error_msg, DialerTaskStatus.FAILURE, dialer_task
            )
            return general_error_response(error_msg)

        loan_id = request.POST.get('LOAN_ID', False)
        payment_id = request.POST.get('PAYMENT_ID', False)
        account_id = request.POST.get('ACCOUNT_ID', False)
        account_payment_id = request.POST.get('ACCOUNT_PAYMENT_ID', False)
        skiptrace_callback_time = request.data['CALLBACK_TIME'] \
            if request.data['CALLBACK_TIME'] else None
        if skiptrace_callback_time and len(skiptrace_callback_time) > 12:
            time_index = 5 if len(skiptrace_callback_time) == 16 else 8
            skiptrace_callback_time = skiptrace_callback_time[-time_index:]

        skiptrace_notes = request.data['NOTES']
        skiptrace_agent_name = request.data['AGENT_NAME']
        start_time = datetime.strptime(request.data['START_TS'], '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(request.data['END_TS'], '%Y-%m-%d %H:%M:%S')
        non_payment_reason = None if 'NON_PAYMENT_REASON' not in request.data else \
            request.data['NON_PAYMENT_REASON']

        spoke_with = request.data['SPOKE_WITH']
        call_id = request.data.get('CALL_ID', None)
        loan_status = None
        payment_status = None
        account_payment_status_id = None
        is_julo_one = False
        account_payment = None
        is_grab = False
        is_dana = False
        # loan_id is primary key for non j1 customers
        if loan_id:
            loan = Loan.objects.get_or_none(pk=loan_id)
            is_julo_one = False
            account_id = None
            account_payment_id = None
            account = None

            if not loan:
                error_msg = 'Not found loan for loan_id - {}'.format(loan_id)
                create_failed_call_results(
                    dict(
                        dialer_task=dialer_task,
                        error=error_msg,
                        call_result=json.dumps(request.data)
                    )
                )
                update_intelix_callback(
                    error_msg, DialerTaskStatus.FAILURE, dialer_task
                )
                return general_error_response(error_msg)

            payment = loan.payment_set.get_or_none(id=payment_id)

            if not payment:
                error_msg = 'Not found payment for loan {} with payment id - {}'.format(
                    loan_id, payment_id
                )
                create_failed_call_results(
                    dict(
                        dialer_task=dialer_task,
                        error=error_msg,
                        call_result=json.dumps(request.data)
                    )
                )
                update_intelix_callback(
                    error_msg, DialerTaskStatus.FAILURE, dialer_task
                )
                return general_error_response(error_msg)

            application = loan.application
            loan_status = loan.loan_status.status_code
            customer = application.customer
            payment_status = payment.payment_status.status_code

        # account_id is primary key for non j1 customers
        if account_id:
            not_active_account_payment_qs = AccountPayment.objects.not_paid_active().order_by('due_date')
            prefetched_not_active_account_payments = Prefetch(
                'accountpayment_set',
                queryset=not_active_account_payment_qs,
                to_attr="prefetch_not_active_account_payment")
            join_tables = [prefetched_not_active_account_payments, ]
            account = Account.objects.select_related('account_lookup__workflow').prefetch_related(
                *join_tables).filter(id=account_id).last()
            loan_id = None
            payment_id = None
            is_julo_one = True
            is_grab = False
            is_dana = account.is_dana

            if not account:
                error_msg = 'Not found account for account_id - {}'.format(account_id)
                create_failed_call_results(
                    dict(
                        dialer_task=dialer_task,
                        error=error_msg,
                        call_result=json.dumps(request.data)
                    )
                )
                update_intelix_callback(
                    error_msg, DialerTaskStatus.FAILURE, dialer_task
                )
                return general_error_response(error_msg)
            if account.is_grab_account():
                is_grab = True
                application = account.customer.application_set.last()
                customer = account.customer
                if account_payment_id:
                    account_payment = account.accountpayment_set.get_or_none(id=account_payment_id)
                    account_payment_status_id = account_payment.status_id
                else:
                    if len(account.prefetch_not_active_account_payment) > 0:
                        account_payment = account.prefetch_not_active_account_payment[0]
                    else:
                        account_payment = account.accountpayment_set.last()
                    if account_payment:
                        account_payment_status_id = account_payment.status_id
                        account_payment_id = account_payment.id
                    else:
                        logger.exception({
                            "action": "UpdateIntelixSkiptraceDataAgentLevel",
                            "error": "AccountPayment is Missing for account",
                            "account_id": account_id
                        })

            else:
                account_payment = account.accountpayment_set.get_or_none(id=account_payment_id)

                if not account_payment:
                    error_msg = 'Not found account_payment for account {} with account_payment id - {}'\
                        .format(
                            account_id, account_payment_id
                        )
                    create_failed_call_results(
                        dict(
                            dialer_task=dialer_task,
                            error=error_msg,
                            call_result=json.dumps(request.data)
                        )
                    )
                    update_intelix_callback(
                        error_msg, DialerTaskStatus.FAILURE, dialer_task
                    )
                    return general_error_response(error_msg)
                if is_dana:
                    application = account.dana_customer_data.application
                else:
                    application = account.customer.application_set.last()
                customer = account.customer
                account_payment_status_id = account_payment.status_id

        if not loan_id and not account_id:
            error_msg = 'Account_ID and Loan_ID were not posted'
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=error_msg,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                error_msg, DialerTaskStatus.FAILURE, dialer_task
            )
            return general_error_response(error_msg)

        skiptrace_phone = request.POST.get('PHONE_NUMBER', False)
        agent_user = User.objects.filter(username=skiptrace_agent_name.lower()).last()
        if agent_user is None:
            error_msg = 'Invalid agent details - {}'.format(skiptrace_agent_name)
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=error_msg,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                error_msg, DialerTaskStatus.FAILURE, dialer_task
            )
            return general_error_response(error_msg)

        call_status = request.data['CALL_STATUS']
        skip_result_choice = SkiptraceResultChoice.objects.filter(
            name__iexact=call_status
        ).last()
        if not skip_result_choice:
            mapping_key = call_status.lower()
            julo_skiptrace_result_choice = None \
                if mapping_key not in IntelixResultChoiceMapping.MAPPING_STATUS \
                else IntelixResultChoiceMapping.MAPPING_STATUS[mapping_key]

            skip_result_choice = SkiptraceResultChoice.objects.filter(
                name__iexact=julo_skiptrace_result_choice).last()
            if not skip_result_choice:
                error_msg = 'Invalid skip_result_choice with value {}'.format(call_status)
                create_failed_call_results(
                    dict(
                        dialer_task=dialer_task,
                        error=error_msg,
                        call_result=json.dumps(request.data)
                    )
                )
                update_intelix_callback(
                    error_msg, DialerTaskStatus.FAILURE, dialer_task
                )
                return general_error_response(error_msg)

        CuserMiddleware.set_user(agent_user)
        skiptrace_obj = Skiptrace.objects.filter(
            phone_number=format_e164_indo_phone_number(skiptrace_phone),
            customer_id=customer.id).last()

        if not skiptrace_obj:
            skiptrace_obj = Skiptrace.objects.create(
                phone_number=format_e164_indo_phone_number(skiptrace_phone),
                customer_id=customer.id
            )

        skiptrace_id = skiptrace_obj.id
        ptp_notes = ''
        if 'PTP_AMOUNT' in request.data and 'PTP_DATE' in request.data:
            ptp_amount = request.data['PTP_AMOUNT']
            ptp_date = request.data['PTP_DATE']
            if ptp_amount and ptp_date:
                ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                if not is_julo_one and not is_grab:
                    payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create_v2(payment, ptp_date, ptp_amount, agent_user, is_julo_one)
                else:
                    account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
                    ptp_create_v2(account_payment, ptp_date, ptp_amount,
                                  agent_user, is_julo_one, is_grab)

        skiptrace_result_id = skip_result_choice.id

        status_group, status = construct_status_and_status_group(skip_result_choice.name)
        if skiptrace_notes or ptp_notes:
            call_note = {
                "contact_source": skiptrace_obj.contact_source,
                "phone_number": str(skiptrace_obj.phone_number),
                "call_result": status,
                "spoke_with": spoke_with,
                "non_payment_reason": non_payment_reason or ''
            }
            if not is_julo_one and not is_grab:
                PaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    payment=payment,
                    added_by=agent_user,
                    extra_data={
                        'call_note': call_note
                    }
                )
            else:
                AccountPaymentNote.objects.create(
                    note_text='{};{}'.format(ptp_notes, skiptrace_notes),
                    account_payment=account_payment,
                    added_by=agent_user,
                    extra_data={
                        'call_note': call_note
                    }
                )
        data_to_save = dict(
            start_ts=start_time, end_ts=end_time,
            application_id=application.id,
            loan_id=loan_id,
            agent_name=agent_user.username,
            call_result_id=skiptrace_result_id,
            agent_id=agent_user, skiptrace_id=skiptrace_id,
            payment_id=payment_id,
            notes=skiptrace_notes,
            callback_time=skiptrace_callback_time,
            loan_status=loan_status,
            payment_status=payment_status,
            application_status=application.status,
            non_payment_reason=non_payment_reason,
            spoke_with=spoke_with,
            status_group=status_group,
            status=status,
            account_id=account_id,
            account_payment_id=account_payment_id,
            account_payment_status_id=account_payment_status_id,
            source='Intelix',
            unique_call_id=call_id)
        model = SkiptraceHistory
        if is_grab:
            model = GrabSkiptraceHistory
        elif is_dana:
            model = DanaSkiptraceHistory
            del data_to_save['loan_id']
            del data_to_save['loan_status']
            del data_to_save['payment_id']
            del data_to_save['application_status']

        model.objects.create(**data_to_save)

        if not is_julo_one and not is_grab:

            if agent_user:
                trigger_insert_col_history(
                    payment.id, agent_user.id, skip_result_choice.id, is_julo_one)

            error_msg = 'Details updated for loan - {}' .format(loan.id)

            if skip_result_choice.name in \
                    CollectionVendorAssignmentConstant.SKIPTRACE_CALL_STATUS_ASSIGNED_CRITERIA \
                    and payment.bucket_number_special_case == 5:
                assign_agent_for_bucket_5.delay(agent_user_id=agent_user.id, loan_id=loan.id)
        elif is_grab:
            if agent_user:
                trigger_insert_col_history(
                    account_payment.id, agent_user.id, skip_result_choice.id, is_julo_one)

            error_msg = 'Details updated for account - {}'.format(account.id)

        else:

            if agent_user:
                trigger_insert_col_history(
                    account_payment.id, agent_user.id, skip_result_choice.id, is_julo_one, is_dana)

            error_msg = 'Details updated for account - {}' .format(account.id)

            if skip_result_choice.name in \
                    CollectionVendorAssignmentConstant.SKIPTRACE_CALL_STATUS_ASSIGNED_CRITERIA \
                    and account_payment.bucket_number_special_case == 5 and not is_dana:
                assign_agent_for_julo_one_bucket_5.delay(
                    agent_user_id=agent_user.id, account_payment_id=account_payment_id)

        update_intelix_callback(
            error_msg, DialerTaskStatus.SUCCESS, dialer_task
        )

        return success_response({'message': error_msg})


class StoringCallRecordingDetail(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = CallRecordingDetailSerializer

    def post(self, request):
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.STORING_RECORDING_INTELIX,
            error=''
        )
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=serializer.errors,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                serializer.errors, DialerTaskStatus.FAILURE, dialer_task
            )
            serializer.is_valid(raise_exception=True)

        token = request.META['HTTP_AUTHORIZATION']
        if not token == settings.INTELIX_JULO_TOKEN:
            error_msg = 'Invalid authentication credentials'
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=error_msg,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                error_msg, DialerTaskStatus.FAILURE, dialer_task
            )
            return general_error_response(error_msg)

        data = serializer.validated_data
        try:
            store_status, error_message, recording_detail_id = store_call_recording_details_from_intelix(
                data
            )
        except Exception as e:
            error_msg = str(e)
            create_failed_call_results(
                dict(
                    dialer_task=dialer_task,
                    error=error_msg,
                    call_result=json.dumps(request.data)
                )
            )
            update_intelix_callback(
                error_msg, DialerTaskStatus.FAILURE, dialer_task
            )

            if data.get('BUCKET') == IntelixTeam.GRAB:
                logger.error({
                    'function_name': 'POST StoringCallRecordingDetail',
                    'message': str(e),
                    'data': data
                })
            return general_error_response(error_msg)

        if not store_status:
            update_intelix_callback(
                error_message, DialerTaskStatus.FAILURE, dialer_task
            )
            if data.get('BUCKET') == IntelixTeam.GRAB:
                logger.error({
                    'function_name': 'POST StoringCallRecordingDetail',
                    'message': error_message,
                    'data': data
                })
            return general_error_response(error_message)

        update_intelix_callback(
            error_message, DialerTaskStatus.SUCCESS, dialer_task
        )
        download_call_recording_via_sftp.delay(
            dialer_task_id=dialer_task.id,
            vendor_recording_detail_id=recording_detail_id)
        return success_response({'message': error_message})


class CallbackPromiseSetSlotTime(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        account = application.account
        data = request.data
        account_payment = account.get_last_unpaid_account_payment()
        if not account_payment:
            return general_error_response("Tagihan sudah dibayar")

        today_date = timezone.localtime(timezone.now()).date()
        bucket_name = account_bucket_name_definition(account_payment)
        callback_promise = CallbackPromiseApp.objects.filter(
            account=account, account_payment=account_payment,
            bucket=bucket_name,
            cdate__date=today_date
        ).last()
        if callback_promise:
            return general_error_response("Sudah menentukan waktu telepon")

        selected_time_slot_start = data.get('selected_time_slot_start')
        selected_time_start_list = selected_time_slot_start.split(':')
        start_hours = selected_time_start_list[0]
        end_hours = int(start_hours) + 1
        selected_time_slot_end = f'{end_hours}:00'
        yesterday = today_date - relativedelta(days=1)
        yesterday_call = SkiptraceHistory.objects.filter(
            cdate__date=yesterday, account_payment=account_payment,
        ).exclude(
            call_result__name__in=IntelixResultChoiceMapping.CONNECTED_STATUS
        ).last()
        created_callback_promise = CallbackPromiseApp.objects.create(
            account=account,
            account_payment=account_payment,
            selected_time_slot_start=selected_time_slot_start,
            selected_time_slot_end=selected_time_slot_end,
            bucket=bucket_name,
            skiptrace_history=yesterday_call,
        )
        if created_callback_promise:
            today = timezone.localtime(timezone.now()).replace(
                hour=int(start_hours), minute=int(selected_time_start_list[1]))
            next_call_datetime = today + relativedelta(days=1)
            formated_selected_time = format_datetime(
                next_call_datetime, 'EEEE, d MMM yyyy, H.mm', locale='id_ID')
            success_message = f'Terima Kasih sudah menentukan waktu telepon kamu. ' \
                              f'<b>{formated_selected_time} WIB</b> ' \
                              f'Tim JULO akan menghubungi kamu'
            return success_response({'message': success_message})


class InAppPtp(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        customer = request.user.customer
        if not customer:
            return general_error_response('no data')
        application = customer.application_set.regular_not_deletes().last()
        account = application.account
        data = request.data
        account_payment = account.get_last_unpaid_account_payment()
        if not account_payment:
            return general_error_response('Tagihan sudah dibayar')

        ptp_date = datetime.strptime(
            data.get('ptp_date'), "%Y-%m-%d").date()
        ptp_amount = data.get('ptp_amount')
        payment_channel_id = data.get('payment_channel')

        try:
            feature_setting = FeatureSetting.objects.filter(
                feature_name=JuloFeatureNameConst.IN_APP_PTP_SETTING, is_active=True
            ).last()
            if feature_setting:
                card_appear_dpd = feature_setting.parameters.get('dpd_start_appear') or InAppPTPDPD.DPD_START_APPEAR
            else:
                card_appear_dpd = None
            in_app_ptp_history = InAppPTPHistory.objects.create(
                card_appear_dpd=card_appear_dpd,
                dpd=account_payment.dpd,
                account_payment=account_payment,
                payment_method_id=payment_channel_id,
            )
            ptp_create_v2(
                account_payment,
                ptp_date,
                ptp_amount,
                request.user,
                is_julo_one=True,
                in_app_ptp_history_id=in_app_ptp_history.id
            )
            account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)
            if payment_channel_id:
                payment_method = PaymentMethod.objects.get_or_none(
                    pk=payment_channel_id)
            if payment_method:
                PaymentMethod.objects.filter(
                    customer=account.customer, is_primary=True).update(is_primary=False)
                payment_method.update_safely(is_primary=True)
            comms_block = ptp_date - account_payment.due_date
            block_intelix_comms_ptp(account, account_payment, ptp_date, comms_block.days)
            formatted_date = format_date(ptp_date, 'EEEE, d MMM yyyy', locale='id_ID')
            success_message = (f'Terima Kasih sudah menentukan hari janji bayar kamu. Pada hari '
                               f'<b>{formatted_date}</b> kamu akan menerima tagihan untuk melakukan pembayaran tagihan.')
            return success_response({'message': success_message})
        except Exception as e:
            return general_error_response({'message': 'ptp is not created or updated'}, e)


class GenesysManualUploadCallResults(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GenesysManualUploadCallSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data_reader = data['csv_file']
        store_genesys_call_results.delay(list(data_reader))
        return success_response()


class IntelixBlackListAccount(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = IntelixBlackListAccountSerializer
    phone_serializer_class = IntelixBlackListAccountPhoneSerializer

    def post(self, request):
        blacklist_status = "Blacklist"
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            message = serializer.errors
            return general_error_response(message=str(message))
        data = serializer.validated_data
        date = datetime.strptime(str(data['expire_date']), '%Y-%m-%d')
        account_id = data['account_id']
        account = Account.objects.select_related('customer').filter(
            id=account_id).last()
        reason_removal = data['reason_removal']
        description = data['description']
        if description:
            reason_removal = "{} - {}".format(reason_removal, description)
        if account:
            blacklist = intelixBlacklist.objects.filter(account=account).last()
            post_data = dict(
                account=account, expire_date=date,
                reason_for_removal=reason_removal, user=request.user
            )
            if blacklist:
                blacklist.update_safely(**post_data)
            else:
                blacklist = intelixBlacklist.objects.create(**post_data)

            send_dialer_blacklist_customer_attribute.delay(blacklist.id)

            phone_list = []
            phone_number_list = Skiptrace.objects.filter(customer_id=account.customer.id)
            if phone_number_list:
                for phone in phone_number_list:
                    phone = {
                        'contact_name': phone.contact_name,
                        'contact_source': phone.contact_source,
                        'phone_number': phone.phone_number
                    }
                    phone_serializer_class = IntelixBlackListAccountPhoneSerializer(
                        data=phone)
                    if not phone_serializer_class.is_valid():
                        continue
                    phone_data = phone_serializer_class.validated_data
                    phone_list.append(phone_data)

            response = {
                'account_id': account.id,
                'account_status': account.status_id,
                'full_name': account.customer.fullname,
                'email': account.customer.email,
                'app_id': account.last_application.id,
                'blacklist_status': blacklist_status,
                'reason_removal': blacklist.reason_for_removal,
                "expire_date": blacklist.expire_date.strftime('%Y-%m-%d'),
                "phone_list": phone_list,
                "black_list_by": blacklist.user.username if blacklist.user else "",
            }

            return success_response(response)

        else:
            response = {
                'message': "failed",

            }

            return general_error_response(message="Account not found", data=response)

    def get(self, request):
        account_id = request.GET['account_id']
        blacklist_status = "Not Blacklist"
        reason_removal = "-"
        expire_date = "-"
        blacklist_by = "-"
        account = Account.objects.select_related('customer').filter(
            id=account_id).last()
        if account:
            phone_list = []
            phone_number_list = Skiptrace.objects.filter(
                customer_id=account.customer.id)
            if phone_number_list:
                for phone in phone_number_list:
                    phone = {
                        'contact_name': phone.contact_name,
                        'contact_source': phone.contact_source,
                        'phone_number': phone.phone_number
                    }
                    phone_serializer_class = IntelixBlackListAccountPhoneSerializer(
                        data=phone)
                    if not phone_serializer_class.is_valid():
                        continue
                    phone_data = phone_serializer_class.validated_data
                    phone_list.append(phone_data)
            blacklist = intelixBlacklist.objects.filter(account=account.id).last()
            if blacklist:
                reason_removal = blacklist.reason_for_removal
                blacklist_by = blacklist.user.username if blacklist.user else ""
                if blacklist.expire_date:
                    expire_date = datetime.strptime(str(blacklist.expire_date), '%Y-%m-%d')

                    if expire_date.date() >= datetime.now().date():
                        blacklist_status = "Blacklist"
                        expire_date = expire_date

            response = {
                'account_id': account.id,
                'account_status': account.status_id,
                'full_name': account.customer.fullname,
                'email': account.customer.email,
                'app_id': account.last_application.id,
                'blacklist_status': blacklist_status,
                'reason_removal': reason_removal,
                "expire_date": expire_date,
                "phone_list": phone_list,
                "black_list_by": blacklist_by
            }
            return success_response(response)
        else:
            response = {
                'message': "failed",
            }
            return general_error_response(message="Account not found", data=response)


@julo_login_required
def blacklist_dialer_account(request):
    is_have_access = request.user.groups.filter(
        name__in=(JuloUserRoles.COLLECTION_SUPERVISOR, JuloUserRoles.OPS_TEAM_LEADER)
    ).exists()
    context = dict(
        token=request.user.auth_expiry_token.key
    )
    if not is_have_access:
        return render(
            request,
            '403.html',
            context
        )
    template = 'blacklist/blacklist.html'
    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.OPS_TEAM_LEADER, JuloUserRoles.CS_TEAM_LEADER, JuloUserRoles.COLLECTION_SUPERVISOR])
def collection_download_manual_upload_intelix_csv(request):
    template = 'minisquad/collection_download_manual_upload_intelix_csv.html'
    context = dict(
        lists=FilterQueryBucket.FILTER_QUERY_BUCKET
    )
    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.PHONE_DELETE_NUMBER_FEATURE_USER])
def delete_phone_number(request):
    if request.POST:
        return delete_phone_number_post(request)

    template = 'minisquad/delete_phone_number.html'
    context = dict(list_filter_query_bucket=FilterQueryBucket.FILTER_QUERY_BUCKET)

    return render(request, template, context)


class AiRudderWebhooks(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = request.data
        fn_name = 'airudder_webhooks_api'
        callback_type = serializer.get('type', None)
        callback_body = serializer.get('body', None)

        if callback_type not in [
            AiRudder.AGENT_STATUS_CALLBACK_TYPE,
            AiRudder.TASK_STATUS_CALLBACK_TYPE,
        ]:
            return JsonResponse({'status': 'skipped'})
        try:
            if not (callback_type) or not (callback_body):
                logger.error(
                    {
                        'function_name': fn_name,
                        'message': 'invalid json body payload',
                        'callback_type': callback_type,
                        'data': serializer,
                    }
                )
                return JsonResponse(
                    status=400,
                    data={'status': 'failed', 'message': 'Please provide valid json body payload'},
                )
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process airudder webhook',
                    'callback_type': callback_type,
                    'data': serializer,
                }
            )

            if 'grab' in callback_body.get('taskName', '').lower():
                grab_process_airudder_store_call_result.delay(serializer)
            else:
                process_airudder_store_call_result.delay(serializer)

            logger.info(
                {
                    'function_name': fn_name,
                    'callback_type': callback_type,
                    'message': 'sent to async task',
                    'data': serializer,
                }
            )
            return JsonResponse({'status': 'success'})
        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process airudder webhook',
                    'data': serializer,
                    'callback_type': callback_type,
                }
            )
            return JsonResponse(status=500, data={'status': 'failed', 'message': str(e)})


def delete_phone_number_post(request):
    try:
        execute_time = timezone.localtime(timezone.now())

        if ('phone_number_delete' not in request.FILES):
            raise Exception('File tidak ada')

        file_data = request.FILES['phone_number_delete']
        if str(file_data).endswith('.csv') == False:
            raise Exception('Format file diwajibkan CSV')

        csv_file = file_data.read().decode('utf-8')

        reader = csv.DictReader(io.StringIO(csv_file), delimiter=',')
        list_reader = list(reader)

        dict_from_csv = dict(list_reader[0])
        list_of_column_names = list(dict_from_csv.keys())
        if len(list_of_column_names) != 2:
            raise Exception('Jumlah header column melebihi dari format yang ditentukan')
        if 'account_id' not in list_of_column_names or 'phone_number' not in list_of_column_names:
            raise Exception('Format header salah')

        remove_phone_number_params = []

        for row in list_reader:
            curr_param = RemovePhoneNumberParamDTO(
                row['account_id'],
                row['phone_number'],
            )
            remove_phone_number_params.append(curr_param)

        remove_phone_number_task.delay(execute_time, remove_phone_number_params)

        template = 'minisquad/delete_phone_number.html'
        context = {'load_message': 'success'}

        return render(request, template, context)
    except Exception as e:
        template = 'minisquad/delete_phone_number.html'
        context = {'load_message': 'failed', 'message': e}
        return render(request, template, context)


def process_bulk_download_manual_upload_intelix_csv_files_trigger(request):
    if request.POST:
        serializer = IntelixFilterSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        redisClient = get_redis_client()

        response = HttpResponse(
            content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename={}_{}.csv'.format(
            data.get('filter_query_bucket').lower().replace(
                " ", "_", -1), timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
        )

    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.BULK_DOWNLOAD_PROCESS_METABASE,
        error=''
    )

    process_download_async = process_download_manual_upload_intelix_csv_files.delay(
        dialer_task.id, data.get('filter_query_bucket'))

    redisClient.set(
        process_download_async.task_id,
        {'state': 'PROGRESS', 'pending': True,
         'current': 0,
         'total': 0, 'percent': 0,
         'description': ''})

    return JsonResponse({
        'status': 'success',
        'download_cache_id': None,
        'task_id': process_download_async.task_id
    })


@never_cache
def get_bulk_download_manual_upload_intelix_csv_files_progress(request, task_id):
    progress = Progress(task_id)
    response = progress.get_info()
    if progress.result.state == 'SUCCESS':
        response.update(download_cache_id=progress.result.description)

    return HttpResponse(json.dumps(response), content_type='application/json')


def do_download_manual_upload_intelix_csv_files_progress(request, csv_file_name):
    """
    Deprecated. The url to this view has been removed.
    The download functionally shouldn't from NFS. It is recommended to use OSS/GCS signed url.
    """
    filename = str(csv_file_name) + ".csv"
    csv_filepath = os.path.join(settings.MEDIA_ROOT, filename)
    fh = open(csv_filepath, 'rb')
    response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
    response['Content-Disposition'] = 'attachment; filename=' + os.path.basename(csv_filepath)
    do_delete_download_manual_upload_intelix_csv.delay(csv_file_name)
    return response


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.OPS_TEAM_LEADER, JuloUserRoles.COLLECTION_SUPERVISOR])
def page_bulk_cancel_call_from_ai_rudder(request):
    template = 'ai_rudder_related/bulk_cancel_call_from_task_page.html'
    message = ''
    errors = []
    if request.POST:
        uploaded_file = request.FILES['uploaded_file']
        form = BulkCancelCallForm(request.POST, request.FILES)
        if form.is_valid():
            csv_data = form.cleaned_data.get('uploaded_file')
            bulk_delete_phone_numbers_from_dialer.delay(csv_data, uploaded_file.name)
            message = 'success'
        else:
            errors = form.errors.values()
            message = 'failed'

    context = {'load_message': message, 'errors': errors}
    return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.COLLECTION_SUPERVISOR])
def page_ai_rudder_task_configuration(request):
    template = 'ai_rudder_related/ai_rudder_create_task_configuration.html'
    message = ''
    errors = []
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG).last()
    if not feature:
        return render(request, '404.html')

    max_sent_other_number = 0
    pass_other_number_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PASS_OTHER_NUMBER_TO_PDS,
        is_active=True,
    ).last()
    if pass_other_number_fs:
        parameters = pass_other_number_fs.parameters
        max_sent_other_number = parameters.get('max_phone_number', 0)

    allowed_dialing_order = AiRudder.ALLOWED_DIALING_ORDER
    new_phone_name = 'new_phone_number_{}'
    if max_sent_other_number:
        for number in range(1, max_sent_other_number + 1):
            allowed_dialing_order.append(new_phone_name.format(number))

    allowed_dialing_order = list(set(allowed_dialing_order))
    context = {
        'load_message': message,
        'errors': errors,
        'data': feature.parameters,
        'allowed_dialing_order': allowed_dialing_order,
    }
    return render(request, template, context)


@csrf_protect
def ai_rudder_task_configuration_api(request):
    services = AIRudderPDSServices()
    operation = request.POST.get('operation')
    bucket_name = request.POST.get('bucket_name', '')
    data_to_save = request.POST.get('data_to_save', {})
    if data_to_save:
        data_to_save = json.loads(data_to_save)
    message = ''
    try:
        status, message = services.crud_strategy_configuration(operation, bucket_name, data_to_save)
    except Exception as e:
        return JsonResponse({
            'status': 'failure',
            'messages': str(e)
        })

    return JsonResponse({
        'status': 'success',
        'messages': message
    })


class GrabAiRudderWebhooks(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = request.data
        fn_name = 'grab_airudder_webhooks_api'
        callback_type = serializer.get('type', None)
        callback_body = serializer.get('body', None)
        if callback_type != AiRudder.AGENT_STATUS_CALLBACK_TYPE:
            return JsonResponse({'status': 'skipped'})
        try:
            if not (callback_type) or not (callback_body):
                logger.error({
                    'function_name': fn_name,
                    'message': 'invalid json body payload',
                    'callback_type': callback_type,
                })
                return JsonResponse(status=400, data={'status': 'failed',
                                                      'message': 'Please provide valid json body payload'})
            logger.info({
                'function_name': fn_name,
                'message': 'start process airudder webhook',
                'callback_type': callback_type,
            })
            grab_process_airudder_store_call_result.delay(serializer)
            logger.info({
                'function_name': fn_name,
                'callback_type': callback_type,
                'message': 'sent to async task',
            })
            return JsonResponse({'status': 'success'})
        except Exception as e:
            logger.error({
                'function_name': fn_name,
                'message': 'failed process airudder webhook',
                'data': serializer,
                'callback_type': callback_type,
            })
            return JsonResponse(status=500, data={'status': 'failed', 'message': str(e)})


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.IT_TEAM])
def page_bulk_change_user_role(request):
    template = 'minisquad/it_bulk_change_roles_pages.html'
    errors = []
    status = ''
    if request.POST:
        uploaded_file = request.FILES['uploaded_file']
        form = BulkChangeUserRoleForm(request.POST, request.FILES)
        if form.is_valid():
            csv_data = form.cleaned_data.get('uploaded_file')
            bulk_change_users_role_async.delay(csv_data, uploaded_file.name)
            status = 'success'
        else:
            status = 'failed'
            errors = form.errors.values()

    context = {'status': status, 'errors': errors}
    return render(request, template, context)


class BucketRiskAiRudderWebhooks(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = request.data
        fn_name = 'airudder_webhooks_api_for_bucket_risk'
        callback_type = serializer.get('type', None)
        callback_body = serializer.get('body', None)
        if callback_type != AiRudder.AGENT_STATUS_CALLBACK_TYPE:
            return JsonResponse({'status': 'skipped'})
        try:
            if not (callback_type) or not (callback_body):
                logger.error({
                    'function_name': fn_name,
                    'message': 'invalid json body payload',
                    'callback_type': callback_type,
                })
                return JsonResponse(status=400, data={'status': 'failed', 'message': 'Please provide valid json body payload'})
            logger.info({
                'function_name': fn_name,
                'message': 'start process airudder webhook',
                'callback_type': callback_type,
            })
            process_airudder_store_call_result.delay(serializer)
            logger.info({
                'function_name': fn_name,
                'callback_type': callback_type,
                'message': 'sent to async task',
            })
            return JsonResponse({'status': 'success'})
        except Exception as e:
            logger.error({
                'function_name': fn_name,
                'message': 'failed process airudder webhook',
                'data': serializer,
                'callback_type': callback_type,
            })
            return JsonResponse(status=500, data={'status': 'failed', 'message': str(e)})


class UpdateFCSkiptrace(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        # Extract the encoded URL from the POST data
        account_id = request.POST.get('account_xid')
        if not account_id:
            return JsonResponse(
                {'success': False, 'data': None, 'errors': ['missing account_xid param']}
            )
        phone_number = request.POST.get('phone_number')
        if not phone_number:
            return JsonResponse(
                {'success': False, 'data': None, 'errors': ['missing phone_number param']}
            )
        name = request.POST.get('name')
        if not name:
            return JsonResponse({'success': False, 'data': None, 'errors': ['missing name param']})

        try:
            application = Application.objects.filter(account_id=account_id).last()
            if not application:
                return JsonResponse(
                    {'success': False, 'data': None, 'errors': ['application not found']}
                )

            update_skiptrace_number(
                application.id, SkiptraceContactSource.FC_CUSTOMER_MOBILE_PHONE, phone_number, name
            )
        except Exception as e:
            return JsonResponse({'success': False, 'data': None, 'errors': [str(e)]})

        # Return the parsed information as a JSON response
        return JsonResponse(
            {'success': True, 'data': "phone number {} updated".format(phone_number), 'errors': []}
        )


class Bucket5DataGenerationTrigger(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsDataPlatformToken]

    def post(self, request):
        fn_name = 'Bucket5DataGenerationTrigger'
        bucket_recover_is_running = get_feature_setting_parameters(
            FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'is_running'
        )
        if bucket_recover_is_running:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'process handled by bucket recover distributon B5',
                }
            )
            return success_response()

        dialer_task = DialerTask.objects.create(
            vendor=AiRudder.AI_RUDDER_SOURCE, type=DialerTaskType.PROCESS_POPULATE_B5, error=''
        )
        try:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process trigger bucket 5 data generation',
                }
            )
            sent_webhook_to_field_collection_service_by_category.delay(
                category='population', bucket_type='b5'
            )
            process_data_generation_b5.delay(dialer_task_id=dialer_task.id)
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'sent to async task',
                }
            )
            return success_response()
        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process trigger bucket 5 data generation',
                }
            )
            error_msg = str(e)
            create_failed_call_results(
                dict(dialer_task=dialer_task, error=error_msg, call_result=json.dumps(request.data))
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                    error_message=error_msg,
                )
            )
            get_julo_sentry_client().captureException()
            return server_error_response(str(e))


class GetAccountDetail(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, account_id):
        account = Account.objects.get_or_none(pk=account_id)
        if not account:
            return JsonResponse(
                {'success': False, 'data': None, 'errors': ['account tidak ditemukan']}
            )

        customer = account.customer

        if not customer:
            return JsonResponse(
                {'success': False, 'data': None, 'errors': ['customer tidak ditemukan']}
            )

        application = customer.application_set.last()
        if not application:
            return JsonResponse(
                {'success': False, 'data': None, 'errors': ['application tidak ditemukan']}
            )
        application_detokenized = collection_detokenize_sync_object_model(
            PiiSource.APPLICATION,
            application,
            application.customer.customer_xid,
        )
        document_ktp = None
        document_selfie = None
        images = Image.objects.filter(
            image_source=application.id,
            image_type__in=('ktp_self', 'selfie'),
            image_status=Image.CURRENT,
        )
        for image in images:
            if image.image_type == 'ktp_self':
                document_ktp = {
                    "image_thumbnail": image.collection_thumbnail_url(600),
                    "image_detail": image.collection_image_url(600),
                    "type": "ktp",
                }
            elif image.image_type == 'selfie':
                document_selfie = {
                    "image_thumbnail": image.collection_thumbnail_url(600),
                    "image_detail": image.collection_image_url(600),
                    "type": "selfie",
                }

        def get_serialized_phone(customer_id, contact_source, many=False):
            query = Skiptrace.objects.filter(
                customer_id=customer_id,
                contact_source=contact_source)
            if not many:
                number_object = query.order_by('id').last()
                if number_object:
                    detokenized_skiptrace = collection_detokenize_sync_object_model(
                        PiiSource.SKIPTRACE,
                        number_object,
                        None,
                        None,
                        PiiVaultDataType.KEY_VALUE,)
                    if isinstance(detokenized_skiptrace, SimpleNamespace):
                        number_object.phone_number = getattr(
                            detokenized_skiptrace, 'phone_number', number_object.phone_number
                        )
                        number_object.contact_name = getattr(
                            detokenized_skiptrace, 'contact_name', number_object.contact_name
                        )
                    else:
                        number_object = detokenized_skiptrace
                    return SkipTraceSerializer(number_object).data
                else:
                    return None
            number_objects = Skiptrace.objects.filter(
                customer_id=customer_id,
                contact_source__in=contact_source).order_by('contact_source','id')

            if number_objects:
                skiptrace_list_detokenize = collection_detokenize_sync_kv_in_bulk(
                    PiiSource.SKIPTRACE,
                    number_objects,
                    ['phone_number', 'contact_name'],
                )
                for skiptrace in number_objects:
                    detokenized_skiptrace = skiptrace_list_detokenize.get(skiptrace.id)
                    if isinstance(detokenized_skiptrace, SimpleNamespace):
                        skiptrace.phone_number = getattr(
                            detokenized_skiptrace, 'phone_number', skiptrace.phone_number
                        )
                        skiptrace.contact_name = getattr(
                            detokenized_skiptrace, 'contact_name', skiptrace.contact_name
                        )
                    else:
                        skiptrace = detokenized_skiptrace
                return SkipTraceSerializer(number_objects, many=True).data
            else:
                return []

        # Fetch phone numbers
        mobile_phone_1 = get_serialized_phone(customer.id, SkiptraceContactSource.MOBILE_PHONE_1)
        mobile_phone_2 = get_serialized_phone(customer.id, SkiptraceContactSource.MOBILE_PHONE_2)
        kin_mobile_phone = get_serialized_phone(customer.id, SkiptraceContactSource.KIN_MOBILE_PHONE)
        company_phone_number = get_serialized_phone(customer.id, SkiptraceContactSource.COMPANY_PHONE_NUMBER)

        # Fetch FC phone numbers (support multiple sources)
        fc_phone_numbers = get_serialized_phone(
            customer.id,
            [
                SkiptraceContactSource.FC_CUSTOMER_MOBILE_PHONE,
                'old_' + SkiptraceContactSource.FC_CUSTOMER_MOBILE_PHONE
            ],
            many=True
        )

        # Get payment method
        payment_method_dict = None
        payment_method = (
            PaymentMethod.objects.filter(
                Q(is_primary=True, payment_method_name__icontains='Bank')
                | Q(payment_method_code=PaymentMethodCodes.BCA),
                customer_id=customer.id,
            )
            .order_by('-is_primary')
            .first()
        )
        if payment_method:
            detokenized_payment_method = collection_detokenize_sync_object_model(
                PiiSource.PAYMENT_METHOD,
                payment_method,
                None,
                ['virtual_account'],
                PiiVaultDataType.KEY_VALUE,
            )

            payment_method_data = PaymentMethodLookup.objects.filter(
                name=payment_method.payment_method_name
            ).first()
            payment_method_dict = {
                'payment_method_id': payment_method.id,
                'bank_name': payment_method_data.bank_virtual_name,
                'method_icon': payment_method_data.image_logo_url,
                'method_va': detokenized_payment_method.virtual_account,
            }

        oldest_unpaid = account.get_oldest_unpaid_account_payment()
        is_ptp_active = PTP.objects.filter(
            ptp_date__gte=timezone.localtime(timezone.now()).date(),
            account_id=account.id,
        ).exists()

        is_refinance_eligible, _ = can_account_get_refinancing_centralized(account_id)

        address_info = {
            'fullname': application_detokenized.fullname,
            'province': application_detokenized.address_provinsi,
            'city': application_detokenized.address_kabupaten,
            'district': application_detokenized.address_kecamatan,
            'sub_district': application_detokenized.address_kelurahan,
            'zipcode': application_detokenized.address_kodepos,
            'address_detail': application_detokenized.full_address,
            'outstanding_amount': account.get_total_outstanding_amount() or 0,
            'overdue_amount': account.get_total_overdue_amount() or 0,
            'due_date': oldest_unpaid.due_date if oldest_unpaid else None,
            'document_ktp': document_ktp,
            'document_selfie': document_selfie,
            'mobile_phone_1': mobile_phone_1,
            'mobile_phone_2': mobile_phone_2,
            'kin_mobile_phone': kin_mobile_phone,
            'company_name': application_detokenized.company_name,
            'company_address': application_detokenized.company_address,
            'company_phone_number': company_phone_number,
            'fc_phone_numbers': fc_phone_numbers,
            'payment_method': payment_method_dict,
            'payment_detail_url': get_payment_detail_shortened_url(oldest_unpaid)
            if oldest_unpaid
            else '-',
            'is_refinancing_active': account.get_all_active_loan()
            .filter(is_restructured=True)
            .exists(),
            'is_ptp_active': is_ptp_active,
            'is_refinance_eligible': is_refinance_eligible,
        }

        return JsonResponse({'success': True, 'data': address_info, 'errors': []})


class Bucket6DataGenerationTrigger(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsDataPlatformToken]

    def post(self, request):
        dialer_task = DialerTask.objects.create(
            vendor=AiRudder.AI_RUDDER_SOURCE, type=DialerTaskType.PROCESS_POPULATE_B6_1, error=''
        )
        fn_name = 'Bucket6DataGenerationTrigger'
        try:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process trigger bucket 6 data generation',
                }
            )
            process_data_generation_b6.delay(dialer_task_id=dialer_task.id)
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'sent to async task',
                }
            )
            return success_response()
        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process trigger bucket 6 data generation',
                }
            )
            error_msg = str(e)
            create_failed_call_results(
                dict(dialer_task=dialer_task, error=error_msg, call_result=json.dumps(request.data))
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                    error_message=error_msg,
                )
            )
            get_julo_sentry_client().captureException()
            return server_error_response(str(e))


class FieldCollDataPopulationTrigger(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsDataPlatformToken]

    def post(self, request, bucket_type):
        if bucket_type not in ['b2', 'b3', 'b5']:
            return not_found_response("Invalid bucket type")

        fn_name = 'FieldCollDataPopulationTrigger'
        try:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process field coll data population trigger',
                    'bucket_type': bucket_type,
                }
            )
            sent_webhook_to_field_collection_service_by_category.delay(
                category='population', bucket_type=bucket_type
            )
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'sent to async task',
                    'bucket_type': bucket_type,
                }
            )

            return success_response()
        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process field coll data population trigger',
                }
            )
            get_julo_sentry_client().captureException()
            return server_error_response(str(e))


class TriggerDataGenerationCurrentBucket(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsDataPlatformToken]

    def post(self, request):
        fn_name = 'TriggerDataGenerationCurrentBucket'
        try:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process trigger data generation current bucket',
                }
            )
            trigger_data_generation_bucket_current.delay()
            trigger_update_risk_segment_customer_attribute_for_moengage.delay()
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'sent to async task',
                }
            )
            return success_response()
        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process trigger data generation current bucket',
                }
            )
            get_julo_sentry_client().captureException()
            return server_error_response(str(e))


class TriggerProcessBTTCBucket1(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsDataPlatformToken]

    def post(self, request):
        fn_name = 'TriggerProcessBTTCBucket1'
        try:
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'start process',
                }
            )
            # trigger for Jturbo
            is_merge_jturbo = False
            eligible_bucket_numbers_to_merge = []
            merge_j1_jturbo_bucket_fs = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT,
                is_active=True,
            ).last()
            if merge_j1_jturbo_bucket_fs:
                bucket_number = 1
                eligible_bucket_numbers_to_merge = merge_j1_jturbo_bucket_fs.parameters.get(
                    'bucket_numbers_to_merge', []
                )
                is_merge_jturbo = (
                    True if bucket_number in eligible_bucket_numbers_to_merge else False
                )
            trigger_data_generation_bttc_bucket1.delay(
                bucket_name=DialerSystemConst.DIALER_BUCKET_1, is_merge_jturbo=is_merge_jturbo
            )
            logger.info(
                {
                    'function_name': fn_name,
                    'message': 'sent to async task',
                }
            )
            return success_response()
        except Exception as e:
            logger.error(
                {
                    'function_name': fn_name,
                    'message': 'failed process trigger data generation',
                }
            )
            get_julo_sentry_client().captureException()
            return server_error_response(str(e))


class FCAccountPaymentList(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, account_id):
        account = Account.objects.get_or_none(pk=account_id)
        if not account:
            return not_found_response(
                "Account untuk account id {} tidak ditemukan".format(account_id)
            )

        account_payments = (
            AccountPayment.objects.filter(
                account=account,
                status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            )
            .exclude(due_amount=0)
            .order_by('due_date')
        )

        results = []
        for account_payment in account_payments:
            loans = construct_loan_in_account_payment_listv2(account_payment.id, False)

            due_amount = account_payment.due_amount
            late_fee = None
            late_fee_amount, grace_period = get_late_fee_amount_by_account_payment(
                account_payment=account_payment,
                is_paid_off_account_payment=False,
            )
            if late_fee_amount:
                late_fee = dict(amount=late_fee_amount, grace_period=grace_period)

            results.append(
                dict(
                    account_payment_id=account_payment.id,
                    due_status=account_payment.due_statusv2(),
                    due_amount=due_amount,
                    due_date=account_payment.due_date,
                    dpd=account_payment.dpd,
                    paid_date=account_payment.paid_date,
                    loans=loans,
                    late_fee=late_fee,
                )
            )

        return success_response(results)

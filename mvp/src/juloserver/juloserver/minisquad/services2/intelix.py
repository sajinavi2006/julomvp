import ast
import json
import re
from builtins import str
from builtins import range
import logging
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta, date, time

from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from django.db.models import Sum, Q, Prefetch, ExpressionWrapper, F, IntegerField, Max
from django.db.utils import ProgrammingError

from juloserver.julo.models import (Payment,
                                    SkiptraceHistory,
                                    PaymentMethod,
                                    CustomerCampaignParameter,
                                    CampaignSetting,
                                    EmailHistory,
                                    VoiceCallRecord,
                                    CootekRobocall,
                                    ApplicationNote,
                                    PTP, Loan, SkiptraceResultChoice, Skiptrace, Application,
                                    PaymentEvent)
from juloserver.julo.constants import WaiveCampaignConst, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.grab.models import GrabIntelixCScore
from .dialer_related import get_uninstall_indicator_from_moengage_by_customer_id
from ..models import (
    CollectionHistory,
    SentToDialer,
    DialerTaskEvent,
    VendorRecordingDetail,
    intelixBlacklist,
    TemporaryStorageDialer,
    CollectionDialerTemporaryData,
    NotSentToDialer
)
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes
from juloserver.apiv2.models import (
    PdCollectionModelResult,
    PdBTTCModelResult,
)
from juloserver.pn_delivery.models import PNDelivery
from juloserver.julo.services2 import get_customer_service
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.services.customer_related import get_refinancing_status_display
from juloserver.minisquad.services import check_customer_bucket_type, get_bucket_status
from juloserver.julo.partners import PartnerConstant
from juloserver.minisquad.constants import (ICARE_DEFAULT_ZIP_CODE, IntelixTeam,
                                            IntelixResultChoiceMapping, DEFAULT_DB)
from ...account.models import Account
from juloserver.autodebet.services.account_services import get_autodebet_bank_name
from ...collection_vendor.models import AgentAssignment, SubBucket
from ...collection_vendor.services import last_agent_active_waiver_request
from juloserver.account_payment.models import AccountPayment
from juloserver.minisquad.clients import get_julo_intelix_client
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.grab.exceptions import GrabLogicException
from ...grab.models import GrabLoanData, GrabCollectionDialerTemporaryData, \
    GrabConstructedCollectionDialerTemporaryData
from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.utils import DialerEncoder
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants

logger = logging.getLogger(__name__)

NEED_PAYMENT_RELATION = (
    PdCollectionModelResult, CollectionHistory, SkiptraceHistory,
    PdBTTCModelResult
)


def construct_payments_data_for_intelix(payments, bucket_name):
    params_list = []
    if not payments:
        return params_list

    for item in payments:
        # need get payment from it relation
        relation_type = type(item)
        if relation_type in NEED_PAYMENT_RELATION:

            try:
                payment = item.payment
            except Payment.DoesNotExist as error:
                logger.error({
                    "action": "construct_data_for_intelix",
                    "error": error,
                    "data": {"payment_id": payment.id}
                })
                continue
        else:
            payment = item

        if not payment.loan or payment.due_amount == 0:
            continue

        params = construct_parameter_for_intelix_upload(payment, bucket_name, False)
        if not params:
            continue

        params_list.append(params)

    return params_list


def construct_account_payment_data_for_intelix(
        account_payments,
        bucket_name
):
    params_list = []

    if not account_payments:
        return params_list

    for item in account_payments:
        relation_type = type(item)
        if relation_type in NEED_PAYMENT_RELATION:
            try:
                account_payment = item.account_payment
            except AccountPayment.DoesNotExist as error:
                logger.error({
                    "action": "construct_data_for_intelix",
                    "error": error,
                    "data": {"account_payment_id": account_payment.id}
                })
                continue
        else:
            account_payment = item

        if not account_payment.payment_set.exists() or account_payment.due_amount == 0:
            continue

        params = construct_parameter_for_intelix_upload(account_payment, bucket_name, True)
        if not params:
            continue
        params_list.append(params)

    return params_list


def construct_data_for_intelix(
        payments,
        account_payments,
        bucket_name
):
    payment_params = construct_payments_data_for_intelix(payments, bucket_name)
    account_payment_params = construct_account_payment_data_for_intelix(
        account_payments, bucket_name
    )

    return payment_params + account_payment_params


def construct_parameter_for_intelix_upload(data, bucket_name, is_julo_one):
    from juloserver.account.services.account_related import get_experiment_group_data
    from juloserver.loan_refinancing.services.offer_related import \
        is_account_can_offered_refinancing
    def check_active_ptp(ptp_param, today_param, tomorrow_param, is_julo_one):
        last_agent_check = ''
        last_call_status_check = ''
        if ptp_param and ptp_param.ptp_date in [today_param, tomorrow_param]:
            last_call_status_check = 'RPC-PTP'
            last_agent_check = ptp_param.agent_assigned.username

        if ptp_param and ptp_param.ptp_date == yesterday:
            last_call_status_check = 'RPC-Broken PTP'

            if not is_julo_one:
                application = ptp_param.payment.loan.application
            else:
                application = ptp_param.account_payment.account.application_set.last()

            ApplicationNote.objects.create(
                note_text="Broken PTP", application_id=application.id, application_history_id=None
            )

        return last_agent_check, last_call_status_check

    payment_id = None
    loan_id = None
    account_payment_id = None
    account_id = None
    application = None
    ptp = None
    params = {}

    if data.__class__ is AccountPayment:
        payment = data
        ptp = PTP.objects.filter(account_payment=payment).last()
        account_payment_id = payment.id
        account_id = payment.account_id
        jturbo_pattern = re.compile(r'JTURBO', re.IGNORECASE)
        if bool(jturbo_pattern.search(bucket_name)):
            application = payment.account.customer.application_set.filter(
                product_line=ProductLineCodes.TURBO).last()
        else:
            application = payment.account.customer.application_set.filter(
                product_line=ProductLineCodes.J1).last()

    elif data.__class__ is Payment:
        payment = data
        application = payment.loan.application
        ptp = PTP.objects.filter(payment=payment).last()
        payment_id = payment.id
        loan = payment.loan
        loan_id = loan.id

    if application:
        address = '{} {} {} {} {} {}'.format(
            application.address_street_num,
            application.address_provinsi,
            application.address_kabupaten,
            application.address_kecamatan,
            application.address_kelurahan,
            application.address_kodepos)

    # Get payment data
    today = timezone.localtime(timezone.now()).date()
    today_str = datetime.strftime(today, "%Y-%m-%d")

    yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    tomorrow = timezone.localtime(timezone.now() + timedelta(days=1)).date()

    others, last_pay_details, overdue_amount = construct_additional_data_for_intelix(
        data, is_julo_one)
    va_indomaret, va_alfamart, va_maybank, va_permata, va_bca = get_payment_method_for_intelix(
        data, is_julo_one
    )

    promo, refinancing_status, refinancing_prerequisite_amount, refinancing_expire_date = \
        get_loan_refinancing_data_for_intelix(data, is_julo_one)

    # PTP
    last_agent = ''
    last_call_status = ''
    sub_bucket_assign_time_bucket_5 = None
    if bucket_name == IntelixTeam.JULO_B5:
        sub_bucket_assign_time_bucket_5 = SubBucket.sub_bucket_five(1)
    elif bucket_name == IntelixTeam.JULO_B6_1:
        sub_bucket_assign_time_bucket_5 = SubBucket.sub_bucket_six(1)
    elif bucket_name == IntelixTeam.JULO_B6_2:
        sub_bucket_assign_time_bucket_5 = SubBucket.sub_bucket_six(2)
    elif bucket_name == IntelixTeam.JULO_B6_3:
        sub_bucket_assign_time_bucket_5 = SubBucket.sub_bucket_six(3)
    elif bucket_name == IntelixTeam.JULO_B6_4:
        sub_bucket_assign_time_bucket_5 = SubBucket.sub_bucket_six(4)

    if sub_bucket_assign_time_bucket_5:
        agent_assignment_filter = dict(
            is_active_assignment=True,
            sub_bucket_assign_time=sub_bucket_assign_time_bucket_5
        )
        if is_julo_one:
            agent_assignment_filter['account_payment'] = payment
        else:
            agent_assignment_filter['payment'] = payment

        newest_agent_assignment = AgentAssignment.objects.filter(
            **agent_assignment_filter
        ).last()
        if newest_agent_assignment:
            last_agent = newest_agent_assignment.agent.username

        if not last_agent:
            last_agent = last_agent_active_waiver_request(
                payment, is_julo_one=is_julo_one)

            if not last_agent:
                if ptp:
                    last_agent, last_call_status = check_active_ptp(
                        ptp, today, tomorrow, is_julo_one)
    else:
        if ptp:
            last_agent, last_call_status = check_active_ptp(
                ptp, today, tomorrow, is_julo_one)

    repeat_or_first_time = ''
    disbursement_period = ''
    partner_name = ''
    autodebet_status = "Tidak Aktif"
    refinancing_info = ''
    if account_id:
        account = payment.account
        for loan in account.get_all_active_loan():
            fund_transfer_ts = loan.fund_transfer_ts
            if fund_transfer_ts:
                may_june_cohorts_flagging = fund_transfer_ts.strftime("%b %Y")
                if may_june_cohorts_flagging in ['May 2021', 'Jun 2021']:
                    disbursement_period = may_june_cohorts_flagging
                    break

        autodebet_bank_name = get_autodebet_bank_name(account)
        if autodebet_bank_name:
            autodebet_status = 'Aktif ({})'.format(autodebet_bank_name)
        is_can_refinancing = is_account_can_offered_refinancing(account)
        refinancing_info = "Memenuhi Syarat Refinancing, {}".format(
            "Ya" if is_can_refinancing else "Tidak")

    if not is_julo_one and application:
        if application.partner:
            partner_name = application.partner.name
        fund_transfer_ts = loan.fund_transfer_ts
        if fund_transfer_ts:
            disbursement_period = fund_transfer_ts.strftime("%b %Y")

        if application.product_line:
            product_line_code = application.product_line.product_line_code
            if product_line_code in (ProductLineCodes.MTL1, ProductLineCodes.STL1):
                repeat_or_first_time = 'First Time'
            elif product_line_code in (ProductLineCodes.MTL2, ProductLineCodes.STL2):
                repeat_or_first_time = 'Repeat'

    if application:
        phone_numbers = get_phone_numbers_filter_by_intelix_blacklist(application)
        params = {
            "loan_id": loan_id,
            "payment_id": payment_id,
            "customer_id": application.customer.id,
            "application_id": application.id,
            "nama_customer": str(application.fullname),
            "mobile_phone_1": phone_numbers['mobile_phone_1'],
            "mobile_phone_2": phone_numbers['mobile_phone_2'],
            "nama_perusahaan": str(application.company_name),
            "posisi_karyawan": str(application.position_employees),
            "telp_perusahaan": phone_numbers['company_phone_number'],
            "dpd": get_dpd_for_intelix(payment),
            "angsuran/bulan": overdue_amount,
            "denda": payment.late_fee_amount,
            "outstanding": get_oustanding_for_intelix(payment),
            "angsuran_ke": refinancing_info,
            "tanggal_jatuh_tempo": str(payment.due_date),
            "nama_pasangan": str(application.spouse_name),
            "no_telp_pasangan": phone_numbers['spouse_mobile_phone'],
            "nama_kerabat": str(application.kin_name),
            "no_telp_kerabat": phone_numbers['kin_mobile_phone'],
            "hubungan_kerabat": str(application.kin_relationship),
            "alamat": address,
            "kota": str(application.address_kabupaten),
            "jenis_kelamin": str(application.gender),
            "tgl_lahir": str(application.dob),
            "tgl_gajian": str(application.payday),
            "tujuan_pinjaman": str(application.loan_purpose),
            "tgl_upload": today_str,
            "va_bca": va_bca,
            "va_permata": va_permata,
            "va_maybank": va_maybank,
            "va_alfamart": va_alfamart,
            "va_indomaret": va_indomaret,
            "campaign": "JULO",
            "tipe_produk": application.product_line.product_line_type,
            "jumlah_pinjaman": get_jumlah_pinjaman(payment),
            "tenor": get_tenor_for_intelix(payment),
            "partner_name": partner_name,
            "last_agent": last_agent,
            "last_call_status": last_call_status,
            "refinancing_status": str(refinancing_status),
            "activation_amount": str(refinancing_prerequisite_amount),
            "program_expiry_date": str(refinancing_expire_date),
            "customer_bucket_type": check_customer_bucket_type(payment),
            "promo_untuk_customer": promo,
            "zip_code": ICARE_DEFAULT_ZIP_CODE
            if application.partner and application.partner.name in
               PartnerConstant.ICARE_PARTNER and not application.address_kodepos else
            application.address_kodepos,
            'team': bucket_name,
            'disbursement_period': disbursement_period,
            'repeat_or_first_time': repeat_or_first_time,
            'account_id': account_id,
            'account_payment_id': account_payment_id,
            'is_j1': is_julo_one,
            'Autodebit': autodebet_status,
        }
        _, experiment_data = get_experiment_group_data(
            MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            account_id)
        if experiment_data:
            params.update(experiment='Late fee dpd 1, {}'.format(
                'No' if experiment_data.group == 'control' else 'Yes'))

        params.update(others)
        params.update(last_pay_details)

    return params


def record_intelix_log(objects, bucket, dialer_task):
    if not objects:
        return
    sent_to_dialers = []
    if bucket in IntelixTeam.ALL_BUCKET_5_TEAM:
        for param in objects:
            sent_to_dialer = dict(
                bucket=bucket,
                sorted_by_collection_model=False,
                dialer_task=dialer_task,
            )
            payment_id = param.get('payment_id')
            if payment_id:
                payment = Payment.objects.get_or_none(
                    id=payment_id)
                if not payment:
                    continue

                sent_to_dialer.update(loan=payment.loan, payment=payment)
            else:
                account_payment_id = param.get('account_payment_id')
                if not account_payment_id:
                    continue
                account_payment = AccountPayment.objects.get_or_none(
                    pk=account_payment_id)
                if not account_payment:
                    continue
                account = account_payment.account
                sent_to_dialer.update(
                    account=account,
                    account_payment=account_payment
                )

            last_agent = User.objects.filter(username=param['last_agent']).last()
            last_status = param['last_call_status']
            sent_to_dialer.update(
                bucket=bucket,
                sorted_by_collection_model=False,
                dialer_task=dialer_task,
                last_agent=last_agent,
                last_call_status=last_status
            )

            sent_to_dialers.append(SentToDialer(**sent_to_dialer))
    else:
        for _object in objects:
            # since we combined 2 sorted and not sorted then this way is for getting is_sorted
            is_sorted_by_collection_model = True if type(_object) == PdCollectionModelResult \
                else False
            if type(_object) in NEED_PAYMENT_RELATION:
                try:
                    payment = _object.payment
                except Payment.DoesNotExist as error:
                    logger.error({
                        "action": "upload_payment_details",
                        "error": error,
                        "data": {"payment_id": payment.payment_id}
                    })
                    continue
            else:
                payment = _object

            sent_to_dialer = dict(
                loan=payment.loan,
                payment=payment,
                bucket=bucket,
                sorted_by_collection_model=is_sorted_by_collection_model,
                dialer_task=dialer_task
            )

            sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers)


def record_intelix_log_for_j1(objects, bucket, dialer_task, bttc_class_range=None):
    if not objects:
        return
    sent_to_dialers = []

    for _object in objects:
        # since we combined 2 sorted and not sorted then this way is for getting is_sorted
        is_sorted_by_collection_model = True if type(_object) == PdCollectionModelResult else False
        if type(_object) in NEED_PAYMENT_RELATION:
            try:
                account_payment = _object.account_payment
            except AccountPayment.DoesNotExist as error:
                logger.error({
                    "action": "upload_payment_details",
                    "error": error,
                    "data": {"account_payment_id": account_payment.accunt_payment_id}
                })
                continue
        else:
            account_payment = _object
        if account_payment:
            sent_to_dialer = dict(
                account=account_payment.account,
                account_payment=account_payment,
                bucket=bucket,
                sorted_by_collection_model=is_sorted_by_collection_model,
                dialer_task=dialer_task
            )
            if is_sorted_by_collection_model:
                sent_to_dialer.update(sort_rank=_object.sort_rank)
            if bttc_class_range:
                sent_to_dialer.update(bttc_class_range=bttc_class_range)
            sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers)


def record_intelix_log_for_grab(objects, bucket, dialer_task):
    if not objects:
        return
    sent_to_dialers = []

    for _object in objects:
        # since we combined 2 sorted and not sorted then this way is for getting is_sorted
        is_sorted_by_collection_model = True if type(_object) == PdCollectionModelResult \
            else False
        if type(_object) in NEED_PAYMENT_RELATION:
            try:
                account_payment = _object.account_payment
            except AccountPayment.DoesNotExist as error:
                logger.error({
                    "action": "upload_payment_details",
                    "error": error,
                    "data": {"account_payment_id": account_payment.accunt_payment_id}
                })
                continue
        else:
            account_payment = _object

        if account_payment:
            sent_to_dialer = dict(
                account=account_payment.account,
                account_payment=account_payment,
                bucket=bucket,
                sorted_by_collection_model=is_sorted_by_collection_model,
                dialer_task=dialer_task
            )

            sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers)


def create_history_dialer_task_event(param, error_message=None):
    DialerTaskEvent.objects.create(**param)
    if 'status' in param:
        param['dialer_task'].update_safely(
            status=param['status'],
            error=error_message
        )


def update_intelix_callback(error_msg, status, dialer_task):
    dialer_task.update_safely(
        status=status,
        error=error_msg
    )


def check_avoid_comms(payment, is_julo_one=False):
    avoid_comms = False
    today = timezone.localtime(timezone.now()).date()
    today_datetime = timezone.localtime(timezone.now())
    today_minus10 = today - relativedelta(days=10)
    payment_id = None
    account_payment_id = None

    if payment.__class__ is Payment:
        payment_id = payment.id
        application_id = payment.loan.application_id
    elif payment.__class__ is AccountPayment:
        account_payment_id = payment.id
        application_id = payment.account.customer.application_set.last().id

    range_start = datetime.combine(today_minus10, time(0, 0, 0))
    range_end = datetime.combine(today_datetime + timedelta(days=1), time(0, 0, 0))

    email_history = EmailHistory.objects.filter(
        application_id=application_id,
        cdate__gte=range_start,
        cdate__lt=range_end,
        status__in=['open', 'clicked']
    )

    if not is_julo_one:
        voice_call_records = VoiceCallRecord.objects.filter(
            voice_identifier=payment_id,
            cdate__date__gte=today_minus10,
            cdate__date__lte=today,
            account_payment_id=account_payment_id
        ).exclude(call_price=0).exclude(call_price=None)

    else:
        voice_call_records = VoiceCallRecord.objects.filter(
            cdate__date__gte=today_minus10,
            cdate__date__lte=today,
            account_payment_id=account_payment_id
        ).exclude(call_price=0).exclude(call_price=None)

    cootek_robocall = CootekRobocall.objects.filter(
        account_payment_id=account_payment_id,
        payment=payment_id,
        cdate__date__gte=today_minus10,
        cdate__date__lte=today,
        call_status='finished'
    )

    pn_delivery = PNDelivery.objects.filter(
        pntracks__application_id=application_id,
        created_on__date__gte=today_minus10,
        created_on__date__lte=today,
        status='clicked'
    )

    if not any((email_history, voice_call_records, cootek_robocall, pn_delivery)):
        avoid_comms = True

    return avoid_comms


def construct_status_and_status_group(skiptrace_result_name):
    skip_status_mappings = {'RPC - Regular': 'CONTACTED',
                            'RPC - PTP': 'CONTACTED',
                            'PTPR': 'CONTACTED',
                            'RPC - HTP': 'CONTACTED',
                            'RPC - Broken Promise': 'CONTACTED',
                            'Broken Promise': 'CONTACTED',
                            'RPC - Call Back': 'CONTACTED',
                            'Call Back': 'CONTACTED',
                            'WPC - Regular': 'CONTACTED',
                            'WPC - Left Message': 'CONTACTED',
                            'Answering Machine': 'NO CONTACTED',
                            'Busy Tone': 'NO CONTACTED',
                            'Ringing': 'NO CONTACTED',
                            'Rejected/Busy': 'NO CONTACTED',
                            'No Answer': 'NO CONTACTED',
                            'Dead Call': 'NO CONTACTED',
                            'Ringing no pick up / Busy': 'NO CONTACTED',
                            'Whatsapp - Text': 'WHATSAPP',
                            'WPC': 'CONTACTED',
                            'RPC': 'CONTACTED',
                            'Short Call': 'CONTACTED',
                            'cancel': 'NO CONTACTED',
                            'HANG UP': 'NO CONTACTED',
                            }
    skip_group_mappings = {'Not Connected': 'NO CONTACTED',
                           'Connected': 'CONTACTED',
                           'NO CONTACTED': 'NO CONTACTED'
                           }
    skip_result_status = skip_status_mappings.get(skiptrace_result_name)
    skip_result_group = skip_group_mappings.get(skiptrace_result_name)
    if skip_result_status:
        status_group = skip_result_status
        status = skiptrace_result_name
    elif skip_result_group:
        status_group = skip_result_group
        status = ''
    elif skiptrace_result_name == 'Hard To Pay':
        status_group = 'CONTACTED'
        status = 'RPC - HTP'
    else:
        status_group = skiptrace_result_name
        status = ''

    return status_group, status


def is_have_active_ptp_for_bucket_5_for_intelix(
        payment_or_account_payment, compare_date, is_julo_one=False):
    ptp_filter = dict(ptp_date__gte=compare_date)
    if is_julo_one:
        ptp_filter['account_payment'] = payment_or_account_payment
    else:
        ptp_filter['payment'] = payment_or_account_payment
    ptp = PTP.objects.filter(**ptp_filter).last()
    return True if ptp else False


def bucket_five_last_agent_with_previous_paid_payment(
        payment_or_account_payment, sub_bucket, is_julo_one=False):
    today = timezone.localtime(timezone.now()).date()
    sub_bucket_assign_time = sub_bucket
    # check if previous payment is change loan level dpd and paid already
    previous_agent_assignment_filter = dict(
        is_transferred_to_other=False,
        sub_bucket_assign_time=sub_bucket_assign_time
    )
    if is_julo_one:
        previous_payment_or_account_payment = payment_or_account_payment.get_previous_account_payment()
        previous_agent_assignment_filter['account_payment'] = previous_payment_or_account_payment
    else:
        previous_payment_or_account_payment = payment_or_account_payment.get_previous_payment()
        previous_agent_assignment_filter['payment'] = previous_payment_or_account_payment
    previous_agent_assignment = None
    if previous_payment_or_account_payment and previous_payment_or_account_payment.is_paid:
        previous_agent_assignment = AgentAssignment.objects.filter(
            **previous_agent_assignment_filter).last()

    if previous_agent_assignment:
        previous_assignment_time_plus_31 = timezone.localtime(
            previous_agent_assignment.assign_time).date() + timedelta(days=31)
        previous_assignment_reach_181 = previous_payment_or_account_payment.due_date + timedelta(
            days=(sub_bucket_assign_time.end_dpd + 1))
        closest_limit_date = min([previous_assignment_time_plus_31, previous_assignment_reach_181])
        if today <= closest_limit_date:
            return previous_agent_assignment.agent.username
        else:
            if is_have_active_ptp_for_bucket_5_for_intelix(
                    previous_payment_or_account_payment, closest_limit_date,
                    is_julo_one=is_julo_one):
                return previous_agent_assignment.agent.username

    return ''


def construct_additional_data_for_intelix(data, is_julo_one, db_name = DEFAULT_DB):
    last_pay_details = {'last_pay_date': '', 'last_pay_amount': ''}
    others = {}
    max_payment_number = 15
    min_payment_number = 1
    payment_number = 0
    overdue_amount = 0
    last_payment_number = 15
    today = timezone.localtime(timezone.now()).date()

    if not data:
        return others, last_pay_details, overdue_amount

    if not is_julo_one:
        payment = data
        loan = payment.loan
        overdue_amount = payment.due_amount
        other_payments = Payment.objects.using(db_name).normal().filter(loan=loan).order_by('payment_number')
        other_payments = other_payments.filter(is_restructured=False)
        other_payment_payment_numbers = other_payments.values_list('payment_number', flat=True)
    else:
        payment = data
        overdue_amount = payment.due_amount
        account = payment.account
        other_payments = AccountPayment.objects.using(db_name).normal().filter(account=account).order_by('id')

    if other_payments:
        last_pay_amount = other_payments.last().paid_amount
        last_pay_dates = other_payments.last().paid_date
        last_pay_date = '' if last_pay_dates is None else last_pay_dates

        last_pay_details = {'last_pay_date': str(last_pay_date), 'last_pay_amount': last_pay_amount}

        for other_payment in other_payments:
            month_of_year = datetime.strftime(other_payment.due_date, "%B %Y")
            month = month_of_year.split()[0][0:3]
            year = month_of_year.split()[1]
            payment_number += 1
            if not is_julo_one:
                status_code = other_payment.payment_status.status_code
                value = month + ' ' + year + "; " + str(status_code) + "; " + str(
                    other_payment.due_amount)
                others['%s_status_tagihan' % str(other_payment.payment_number)] = value
            else:
                status_code = other_payment.status_id
                value = month + ' ' + year + "; " + str(status_code) + "; " + str(
                    other_payment.due_amount)
                others['%s_status_tagihan' % str(payment_number)] = value
                last_payment_number = payment_number

            if ((PaymentStatusCodes.PAYMENT_1DPD <= status_code <= PaymentStatusCodes.PAYMENT_180DPD
                    or other_payment.due_date == today)
                    and other_payment.id != payment.id):
                overdue_amount += other_payment.due_amount

    if not is_julo_one:
        for payment_number in range(min_payment_number, max_payment_number + 1):
            if payment_number not in other_payment_payment_numbers:
                others['%s_status_tagihan' % str(payment_number)] = 'N.A'
    else:
        if last_payment_number < max_payment_number:
            for x in range(last_payment_number + 1, max_payment_number + 1):
                others['%s_status_tagihan' % str(x)] = 'N.A'

    return others, last_pay_details, overdue_amount


def get_payment_method_for_intelix(data, is_julo_one, db_name = DEFAULT_DB):
    va_indomaret = ''
    va_alfamart = ''
    va_maybank = ''
    va_permata = ''
    va_bca = ''

    if not data:
        return va_indomaret, va_alfamart, va_maybank, va_permata, va_bca

    payment_method_filter = dict(
        is_shown=True,
    )
    if is_julo_one:
        customer = data.account.customer
        payment_method_filter.update(customer=customer)
    else:
        loan = data.loan
        payment_method_filter.update(loan=loan)

    payment_methods = PaymentMethod.objects.using(db_name).filter(**payment_method_filter)

    if payment_methods:
        for payment_method in payment_methods:
            if payment_method.payment_method_name == 'INDOMARET':
                va_indomaret = payment_method.virtual_account
            if payment_method.payment_method_name == 'ALFAMART':
                va_alfamart = payment_method.virtual_account
            if payment_method.payment_method_name == 'Bank MAYBANK':
                va_maybank = payment_method.virtual_account
            if payment_method.payment_method_name == 'PERMATA Bank':
                va_permata = payment_method.virtual_account
            if payment_method.payment_method_name == 'Bank BCA':
                va_bca = payment_method.virtual_account

    return va_indomaret, va_alfamart, va_maybank, va_permata, va_bca


def get_loan_refinancing_data_for_intelix(data, is_julo_one, db_name = DEFAULT_DB):
    today = timezone.localtime(timezone.now()).date()
    promo = ''
    refinancing_status = ''
    refinancing_prerequisite_amount = ''
    refinancing_expire_date = ''

    if not data:
        return promo, refinancing_status, refinancing_prerequisite_amount, refinancing_expire_date

    if is_julo_one:
        loan = data.payment_set.last().loan
        application = data.account.customer.application_set.last()
    else:
        loan = data.loan
        application = data.loan.application

    loan_refinancing = LoanRefinancingRequest.objects.using(db_name).filter(loan=loan).last()
    if loan_refinancing:
        refinancing_status = get_refinancing_status_display(loan_refinancing)
        refinancing_prerequisite_amount = loan_refinancing.last_prerequisite_amount
        refinancing_expire_date = loan_refinancing.expire_date

    if application and application.product_line.product_line_code in ProductLineCodes.mtl() and \
            loan.status != LoanStatusCodes.SELL_OFF:
        today_plus10 = today + relativedelta(days=10)
        today_minus10 = today + relativedelta(days=-10)
        today_minus25 = today + relativedelta(days=-25)
        today_minus55 = today + relativedelta(days=-55)
        check_risky_on_dpd = [today_plus10, today_minus10, today_minus25, today_minus55]
        campaign_setting = CampaignSetting.objects.using(db_name).filter(
            campaign_name=WaiveCampaignConst.RISKY_CUSTOMER_EARLY_PAYOFF, is_active=True).last()
        customer_campaign_params = CustomerCampaignParameter.objects.using(db_name).filter(
            customer=application.customer,
            campaign_setting=campaign_setting,
        ).last()
        if customer_campaign_params and \
                today <= customer_campaign_params.effective_date + relativedelta(days=10):
            promo = 'Early Payback (Promo 30%)'
        elif data.due_date in check_risky_on_dpd:
            customer_service = get_customer_service()
            if customer_service.check_risky_customer(application.id):
                promo = 'Early Payback (Promo 30%)'

    return promo, refinancing_status, refinancing_prerequisite_amount, refinancing_expire_date


def get_payment_number(payment):
    if not payment:
        return ''
    if payment.__class__ is Payment:
        return payment.payment_number

    if payment.__class__ is AccountPayment:
        return ''


def get_angsuran_for_intelix(payment):
    if not payment:
        return 0
    if payment.__class__ is Payment:
        loan = payment.loan
        return loan.installment_amount
    elif payment.__class__ is AccountPayment:
        return payment.due_amount


def get_oustanding_for_intelix(payment):
    if not payment:
        return
    if payment.__class__ is Payment:
        loan = payment.loan
        sum_details = loan.payment_set.normal().filter(
            payment_status_id__lte=PaymentStatusCodes.PAID_ON_TIME).aggregate(Sum('due_amount'))
    elif payment.__class__ is AccountPayment:
        account = payment.account
        sum_details = account.accountpayment_set.normal().filter(
            status_id__lte=PaymentStatusCodes.PAID_ON_TIME).aggregate(Sum('due_amount'))
    if not sum_details['due_amount__sum']:
        return 0
    return sum_details['due_amount__sum']


def get_jumlah_pinjaman(payment):
    if not payment:
        return 0

    if payment.__class__ is Payment:
        loan = payment.loan
        return loan.loan_amount
    elif payment.__class__ is AccountPayment:
        account = payment.account
        sum_details = account.loan_set.filter(
            loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            loan_status_id__gt=LoanStatusCodes.INACTIVE).aggregate(Sum('loan_amount'))
        return sum_details['loan_amount__sum']


def get_tenor_for_intelix(payment):
    if payment.__class__ is Payment:
        loan = payment.loan
        return loan.loan_duration
    return None


def get_dpd_for_intelix(payment):
    if payment.__class__ is Payment:
        return payment.due_late_days
    else:
        return payment.dpd


def construct_payments_and_account_payment_sorted_by_collection_models(data, bucket_name):
    params_list = []
    if not data:
        return params_list

    for item in data:
        # need get payment from it relation
        relation_type = type(item)
        payment_or_account_payment = item
        is_julo_one = True if relation_type == AccountPayment else False
        if relation_type in NEED_PAYMENT_RELATION:
            try:
                if item.account_payment:
                    payment_or_account_payment = item.account_payment
                    is_julo_one = True
                else:
                    payment_or_account_payment = item.payment
            except Payment.DoesNotExist as error:
                logger.error({
                    "action": "construct_payments_and_account_payment_sorted_by_collection_models",
                    "error": error,
                    "data": {"payment_id": payment_or_account_payment.id}
                })
                continue
            except AccountPayment.DoesNotExist as error:
                logger.error({
                    "action": "construct_payments_and_account_payment_sorted_by_collection_models",
                    "error": error,
                    "data": {"account_payment_id": payment_or_account_payment.id}
                })
                continue
        skip_criteria = payment_or_account_payment.payment_set.exists() if is_julo_one else \
            payment_or_account_payment.loan
        if not skip_criteria or payment_or_account_payment.due_amount == 0:
            continue
        params = construct_parameter_for_intelix_upload(
            payment_or_account_payment, bucket_name, is_julo_one)
        if not params:
            continue

        params_list.append(params)

    return params_list


def record_intelix_log_sorted_by_collection_model(
        objects, bucket, dialer_task, bttc_class_range=None):
    if not objects:
        return
    sent_to_dialers = []
    for _object in objects:
        # since we combined 2 sorted and not sorted then this way is for getting is_sorted
        is_sorted_by_collection_model = True if type(_object) == PdCollectionModelResult \
            else False
        item = _object
        is_julo_one = True if type(_object) == AccountPayment else False
        if type(_object) in NEED_PAYMENT_RELATION:
            try:
                if _object.account_payment:
                    item = _object.account_payment
                    is_julo_one = True
                else:
                    item = _object.payment
            except Payment.DoesNotExist as error:
                logger.error({
                    "action": "record_intelix_log_sorted_by_collection_model",
                    "error": error,
                    "data": {"payment_id": item.payment_id}
                })
                continue
            except AccountPayment.DoesNotExist as error:
                logger.error({
                    "action": "record_intelix_log_sorted_by_collection_model",
                    "error": error,
                    "data": {"account_payment_id": item.payment_id}
                })
                continue

        sent_to_dialer = dict(
            bucket=bucket,
            sorted_by_collection_model=is_sorted_by_collection_model,
            dialer_task=dialer_task
        )
        if is_julo_one:
            sent_to_dialer.update(
                account=item.account,
                account_payment=item
            )
            if is_sorted_by_collection_model:
                sent_to_dialer.update(sort_rank=_object.sort_rank)
            if bttc_class_range:
                sent_to_dialer.update(bttc_class_range=bttc_class_range)
        else:
            sent_to_dialer.update(loan=item.loan, payment=item)

        sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers)


def get_all_system_call_result_from_intelix():
    end_date = timezone.localtime(timezone.now()).replace(minute=0, second=0)
    start_date = end_date - timedelta(hours=1)
    intelix_client = get_julo_intelix_client()

    data = intelix_client.download_system_call_results(start_date, end_date)

    return data


def store_call_recording_details_from_intelix(valid_data):
    data = dict(valid_data)
    agent_username = data['AGENT_NAME']
    call_status = data['CALL_STATUS']
    account_id = data.get('ACCOUNT_ID')
    account_payment_id = data.get('ACCOUNT_PAYMENT_ID')
    payment_id = data.get('PAYMENT_ID')
    loan_id = data.get('LOAN_ID')
    start_time = data['START_TS']
    end_time = data['END_TS']
    duration = (end_time - start_time).total_seconds()
    unique_call_id = data['CALL_ID']
    if VendorRecordingDetail.objects.filter(unique_call_id=unique_call_id).exists():
        error_msg = 'duplicate unique call id {}'.format(unique_call_id)
        return False, error_msg, None

    data_for_save = dict(
        bucket=data['BUCKET'],
        duration=round(duration),
        call_start=start_time,
        call_end=end_time,
        call_to=data['CALL_TO'],
        voice_path=data['VOICE_PATH'],
        unique_call_id=unique_call_id
    )
    # loan_id is primary key for non j1 customers
    if loan_id:
        loan = Loan.objects.get_or_none(pk=loan_id)
        if not loan:
            error_msg = 'Not found loan for loan_id - {}'.format(loan_id)
            return False, error_msg, None

        payment = loan.payment_set.get_or_none(id=payment_id)

        if not payment:
            error_msg = 'Not found payment for loan {} with payment id - {}'.format(
                loan_id, payment_id
            )
            return False, error_msg, None
        data_for_save.update(payment=payment)
    # account_id is primary key for non j1 customers
    if account_id:
        account = Account.objects.get_or_none(pk=account_id)
        if not account:
            error_msg = 'Not found account for account_id - {}'.format(account_id)
            return False, error_msg, None

        account_payment = account.accountpayment_set.get_or_none(id=account_payment_id)
        if not data['BUCKET'] == IntelixTeam.GRAB and not account_payment:
            error_msg = 'Not found account_payment for account {} with account_payment id - {}' \
                .format(account_id, account_payment_id)
            return False, error_msg, None
        customer = account.customer
        skiptrace_obj = Skiptrace.objects.filter(
            phone_number=format_e164_indo_phone_number(data['CALL_TO']),
            customer_id=customer.id).last()
        data_for_save.update(
            account_payment=account_payment,
            skiptrace=skiptrace_obj
        )

    user_obj = User.objects.filter(username=agent_username.lower()).last()
    if user_obj is None:
        error_msg = 'Invalid agent details - {}'.format(agent_username)
        return False, error_msg, None

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
            return False, error_msg, None

    data_for_save.update(
        agent=user_obj,
        call_status=skip_result_choice
    )
    vendor_recording_detail = VendorRecordingDetail.objects.create(
        **data_for_save
    )
    if vendor_recording_detail:
        return True, 'success save recording detail', vendor_recording_detail.id

    return False, 'error when save data to vendor recording detail', None


def get_phone_numbers_filter_by_intelix_blacklist(application, db_name = DEFAULT_DB):
    phone_numbers = dict(
        company_phone_number=str(application.company_phone_number),
        kin_mobile_phone=str(application.kin_mobile_phone),
        spouse_mobile_phone=str(application.spouse_mobile_phone),
        mobile_phone_1=str(application.mobile_phone_1),
        mobile_phone_2=str(application.mobile_phone_2)
    )
    if application.is_julo_one():
        today = timezone.localtime(timezone.now()).date()
        intelix_blacklist_data = intelixBlacklist.objects.using(db_name).filter(
            skiptrace__customer=application.customer
        ).filter(
            Q(expire_date__gte=today) | Q(expire_date__isnull=True)
        ).select_related('skiptrace')

        for intelix_blacklist in intelix_blacklist_data.iterator():
            for index in phone_numbers:
                if format_e164_indo_phone_number(phone_numbers[index]) == \
                        format_e164_indo_phone_number(intelix_blacklist.skiptrace.phone_number):
                    phone_numbers[index] = ''
                    break

    return phone_numbers


def serialize_format_sent_to_dialer(object, bucket, dialer_task, bttc_class_range=None):
    if not object:
        return
    # since we combined 2 sorted and not sorted then this way is for getting is_sorted
    is_sorted_by_collection_model = True if type(object) == PdCollectionModelResult \
        else False
    is_julo_one = True if type(object) == AccountPayment else False
    original_object = object
    if type(object) in NEED_PAYMENT_RELATION:
        try:
            if object.account_payment:
                object = object.account_payment
                is_julo_one = True
            else:
                object = object.payment
        except Payment.DoesNotExist as error:
            logger.error({
                "action": "serialize_format_sent_to_dialer",
                "error": error,
                "data": {"payment_id": object.payment_id}
            })
            return {}

        except AccountPayment.DoesNotExist as error:
            logger.error({
                "action": "serialize_format_sent_to_dialer",
                "error": error,
                "data": {"account_payment_id": object.payment_id}
            })
            return {}

    sent_to_dialer = dict(
        bucket=bucket,
        sorted_by_collection_model=is_sorted_by_collection_model,
        dialer_task=dialer_task
    )
    if is_julo_one:
        sent_to_dialer.update(
            account=object.account,
            account_payment=object
        )
        if is_sorted_by_collection_model:
            sent_to_dialer.update(sort_rank=original_object.sort_rank)
        if bttc_class_range:
            sent_to_dialer.update(bttc_class_range=bttc_class_range)
    else:
        sent_to_dialer.update(loan=object.loan, payment=object)

    return sent_to_dialer


def construct_data_for_sent_to_intelix_by_temp_data(populated_temp_data_qs, db_name = DEFAULT_DB):
    from juloserver.account.services.account_related import get_experiment_group_data
    from juloserver.loan_refinancing.services.offer_related import \
        is_account_can_offered_refinancing
    def check_active_ptp_improved(ptp_obj, application_obj, today_param, tomorrow_param):
        last_agent_check = ''
        last_call_status_check = ''
        if ptp_obj and ptp_obj.ptp_date in [today_param, tomorrow_param]:
            last_call_status_check = 'RPC-PTP'
            if ptp_obj.agent_assigned:
                last_agent_check = ptp_obj.agent_assigned.username

        if ptp_obj and ptp_obj.ptp_date == yesterday:
            last_call_status_check = 'RPC-Broken PTP'
            ApplicationNote.objects.create(
                note_text="Broken PTP",
                application_id=application_obj.id,
                application_history_id=None,
            )

        return last_agent_check, last_call_status_check

    # Get payment data
    today = timezone.localtime(timezone.now()).date()
    today_str = datetime.strftime(today, "%Y-%m-%d")
    yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    tomorrow = timezone.localtime(timezone.now() + timedelta(days=1)).date()
    constructed_calling_data = []
    account_payment_dict = dict(
        (obj.account_payment_id, obj.account_payment) for obj in populated_temp_data_qs)

    populated_temp_data_qs_list = populated_temp_data_qs.values(
        'application_id', 'customer_id', 'nama_customer', 'nama_perusahaan', 'posisi_karyawan',
        'nama_pasangan', 'nama_kerabat', 'hubungan_kerabat', 'jenis_kelamin', 'tgl_lahir',
        'tgl_gajian', 'tujuan_pinjaman', 'tanggal_jatuh_tempo', 'alamat', 'kota', 'tipe_produk',
        'partner_name', 'account_payment_id', 'dpd', 'team'
    )
    for populated_temp_data in populated_temp_data_qs_list.iterator():
        account_payment = account_payment_dict.get(populated_temp_data['account_payment_id'])
        if not account_payment:
            continue
        account = account_payment.account
        application = account.last_application
        ptp = PTP.objects.using(db_name).filter(account_payment=account_payment).last()
        # PTP
        last_agent = ''
        last_call_status = ''
        if ptp:
            last_agent, last_call_status = check_active_ptp_improved(
                ptp, application, today, tomorrow)
        repeat_or_first_time = ''
        disbursement_period = ''
        partner_name = ''
        autodebet_status = "Tidak Aktif"
        for loan in account.get_all_active_loan():
            fund_transfer_ts = loan.fund_transfer_ts
            if fund_transfer_ts:
                may_june_cohorts_flagging = fund_transfer_ts.strftime("%b %Y")
                if may_june_cohorts_flagging in ['May 2021', 'Jun 2021']:
                    disbursement_period = may_june_cohorts_flagging
                    break

        autodebet_bank_name = get_autodebet_bank_name(account, db_name=db_name)
        if autodebet_bank_name:
            autodebet_status = 'Aktif ({})'.format(autodebet_bank_name)

        phone_numbers = get_phone_numbers_filter_by_intelix_blacklist(application)
        others, last_pay_details, overdue_amount = construct_additional_data_for_intelix(
            account_payment, True, db_name=db_name)
        va_indomaret, va_alfamart, va_maybank, va_permata, va_bca = get_payment_method_for_intelix(
            account_payment, True, db_name=db_name)

        promo, refinancing_status, refinancing_prerequisite_amount, refinancing_expire_date = \
            get_loan_refinancing_data_for_intelix(account_payment, True, db_name=db_name)
        zip_code = application.address_kodepos
        if application.partner and application.partner.name in \
                PartnerConstant.ICARE_PARTNER and not application.address_kodepos:
            zip_code = ICARE_DEFAULT_ZIP_CODE
        is_can_refinancing = is_account_can_offered_refinancing(account)
        refinancing_info = "Memenuhi Syarat Refinancing, {}".format(
            "Ya" if is_can_refinancing else "Tidak")
        params = {
            "loan_id": None,
            "payment_id": None,
            "mobile_phone_1": phone_numbers['mobile_phone_1'],
            "mobile_phone_2": phone_numbers['mobile_phone_2'],
            "telp_perusahaan": phone_numbers['company_phone_number'],
            "angsuran/bulan": overdue_amount,
            "denda": abs(account_payment.account.get_outstanding_late_fee()),
            "outstanding": get_oustanding_for_intelix(account_payment),
            "angsuran_ke": refinancing_info,
            "no_telp_pasangan": phone_numbers['spouse_mobile_phone'],
            "no_telp_kerabat": phone_numbers['kin_mobile_phone'],
            "tgl_upload": today_str,
            "va_bca": va_bca,
            "va_permata": va_permata,
            "va_maybank": va_maybank,
            "va_alfamart": va_alfamart,
            "va_indomaret": va_indomaret,
            "campaign": get_uninstall_indicator_from_moengage_by_customer_id(account.customer_id),
            "jumlah_pinjaman": get_jumlah_pinjaman(account_payment),  # on the fly
            "tenor": None,
            "partner_name": partner_name,
            "last_agent": last_agent,
            "last_call_status": last_call_status,
            "refinancing_status": str(refinancing_status),
            "activation_amount": str(refinancing_prerequisite_amount),
            "program_expiry_date": str(refinancing_expire_date),
            "customer_bucket_type": check_customer_bucket_type(account_payment),
            "promo_untuk_customer": promo,
            "zip_code": zip_code,
            'disbursement_period': disbursement_period,
            'repeat_or_first_time': repeat_or_first_time,
            'account_id': account_payment.account_id,
            'is_j1': True,
            'Autodebit': autodebet_status
        }
        _, experiment_data = get_experiment_group_data(
            MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            account_payment.account_id)
        if experiment_data:
            params.update(experiment='Late fee dpd 1, {}'.format(
                'No' if experiment_data.group == 'control' else 'Yes'))
        constructed_data = populated_temp_data
        constructed_data.update(params)
        constructed_data.update(others)
        constructed_data.update(last_pay_details)
        constructed_calling_data.append(constructed_data)

    return constructed_calling_data


def record_intelix_log_improved(objects, bucket, dialer_task):
    if not objects:
        return
    sent_to_dialers = []

    for _object in objects:
        account_payment = _object.account_payment
        sent_to_dialer = dict(
            account=account_payment.account,
            account_payment=account_payment,
            bucket=bucket,
            sorted_by_collection_model=True if _object.sort_order else False,
            sort_rank=_object.sort_order,
            dialer_task=dialer_task
        )
        sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers, batch_size=500)


def get_eligible_grab_payment_for_dialer(
        rank: int = 7, restructured_loan_ids_list=None,
        loan_xids_based_on_c_score_list=None):
    from juloserver.moengage.utils import chunks
    n_chunks = 200
    """
    Get eligible grab account payment for dialer

    Params:
        rank: rank of priority order
        rank: 1 - 6 are related to c score where
        - odd ones for dpd loans
        - even ones are for restructured loans
        - High Risk = 200-449
        - Medium Risk = 450-599
        - Low Risk = 600-800

        Rank order:
        1. User with high risk c-score and in dpd 2 - 90 and outstanding amount > 100k
        2. User with high risk c-score and in dpd 2 - 90, outstanding amount > 100k
        with Restructure applied (if there is no payment from the last 2 days)
        3. User with medium risk c-score and in dpd 7 - 90 and outstanding amount > 100k
        4. User with medium risk c-score and in dpd 7 - 90, outstanding amount > 100k
        with Restructure applied (if there is no payment from the last 2 days)
        5. User with low risk c-score and in dpd 14 - 90 and outstanding amount > 100k
        6. User with low risk c-score and in dpd 14 - 90, outstanding amount > 100k
        with Restructure applied (if there is no payment from the last 2 days)
        7. User in dpd 2 - 90 and outstanding amount > 100K
        8. User in dpd 2 - 90 with Restructure applied (if there is no payment from the last 2 days)
        ----- DEPRICATED ----
        9. User in dpd 2 - 90 and outstanding amount < 700k
        10. User in dpd above 90

    Return:
        - eligible_Account_payment_qs : AccountPayment = Account Payment queryset object
    """
    if loan_xids_based_on_c_score_list is None:
        loan_xids_based_on_c_score_list = []
    if restructured_loan_ids_list is None:
        restructured_loan_ids_list = []
    logger.info({
        "task": "get_eligible_grab_payment_for_dialer",
        "rank": rank,
        "status": "starting task"
    })
    DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID = 2
    MINIMUM_DPD_VALUE = 2
    use_outstanding = False
    is_below_700k = False
    is_restructured = False
    is_loan_below_91 = True
    is_include_restructure_and_normal = False
    exclusion_filter = Q()
    inclusion_filter = {
        'loan__loan_status_id__in': LoanStatusCodes.grab_current_until_90_dpd(),
        'payment_status_id__in': {
            PaymentStatusCodes.PAYMENT_DUE_TODAY,
            PaymentStatusCodes.PAYMENT_1DPD,
            PaymentStatusCodes.PAYMENT_5DPD,
            PaymentStatusCodes.PAYMENT_30DPD,
            PaymentStatusCodes.PAYMENT_60DPD,
            PaymentStatusCodes.PAYMENT_90DPD
        },
        'is_restructured': False,
        'loan__account__account_lookup__workflow__name': WorkflowConst.GRAB
    }
    is_above_100k = False

    if rank == 1:
        # high risk without restructure loan
        use_outstanding = True
        is_above_100k = True

    elif rank == 2:
        # high risk only restructure loan
        is_restructured = True
        use_outstanding = True
        is_above_100k = True
        restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
            restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
        ) if restructured_loan_ids_list else []

    elif rank == 3:
        # medium risk without restructure loan
        use_outstanding = True
        is_above_100k = True

    elif rank == 4:
        # medium risk only restructure loan
        is_restructured = True
        use_outstanding = True
        is_above_100k = True
        restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
            restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
        ) if restructured_loan_ids_list else []

    elif rank == 5:
        # low risk without restructure loan
        use_outstanding = True
        is_above_100k = True

    elif rank == 6:
        # low risk only restructure loan
        is_restructured = True
        use_outstanding = True
        is_above_100k = True
        restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
            restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
        ) if restructured_loan_ids_list else []

    elif rank == 7:
        use_outstanding = True
        is_above_100k = True
    elif rank == 8:
        is_restructured = True
        restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
            restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
        ) if restructured_loan_ids_list else []
    else:
        raise Exception("INVALID RANK FOR GRAB INTELIX RANK({})".format(rank))

    """
    check if both data should be included
    if not then check it is should be restructured only data or normal data only
    """
    if not is_include_restructure_and_normal:
        if not is_restructured:
            exclusion_filter = exclusion_filter | (Q(loan_id__in=restructured_loan_ids_list))
        else:
            inclusion_filter.update({'loan_id__in': restructured_loan_ids_list})

    grab_loan_data_set = GrabLoanData.objects.only(
        'loan_halt_date', 'loan_resume_date', 'account_halt_info',
        'id', 'loan_id', 'is_repayment_capped')
    prefetch_grab_loan_data = Prefetch(
        'loan__grabloandata_set', to_attr='grab_loan_data_set', queryset=grab_loan_data_set)

    prefetch_join_tables = [
        prefetch_grab_loan_data
    ]

    oldest_payment_qs = Payment.objects.select_related('loan__customer').prefetch_related(
        *prefetch_join_tables
    ).filter(
        **inclusion_filter
    ).exclude(
        exclusion_filter
    )

    """
    filter by loan xid based on payment object that already get from this query
    but first, i remove the filter for this `loan__loan_xid__in`
    oldest_payment_qs = Payment.objects.select_related('loan__customer').prefetch_related(
        *prefetch_join_tables
    ).filter(
        **inclusion_filter
    ).exclude(
        exclusion_filter
    )

    get loan xid filter by loan_id and rank (previously it's only filter by rank)
    """
    loans_ids_list = list(set(oldest_payment_qs.values_list('loan_id', flat=True)))

    # dont chunk for rank 7 and 8
    if rank in {7,8} and loans_ids_list:
        n_chunks = len(loans_ids_list)

    for i in range(0, len(loans_ids_list), n_chunks):
        loans_ids_list_chunked = loans_ids_list[i:i+n_chunks]

        # This query will give us the most oldest not paid active payment details for
        # for all loans in loans_ids_list
        query_for_oldest_payment = """
        WITH cte AS
            (
                SELECT p.loan_id as loan_id, p.payment_id as payment_id, p.due_date as payment_due_date,
                ROW_NUMBER() OVER (PARTITION BY p.loan_id ORDER BY
                p.due_date asc) AS rn from ops.loan l join ops.payment p on p.loan_id = l.loan_id
                where l.loan_status_code >= 220 and p.loan_id in {loans_ids_list_chunked}
                and l.loan_status_code < 250 and p.payment_status_code < 330
                and p.is_restructured = false
                group by p.loan_id, p.payment_id order by p.due_date asc
            )
        SELECT loan_id, payment_id, payment_due_date
        FROM cte
        WHERE rn = 1;
        """
        if len(loans_ids_list_chunked) <= 0:
            return Payment.objects.none(), []
        total_number_of_loans = len(loans_ids_list_chunked)
        batch_size = 5000
        loan_oldest_payment_mapping = dict()
        loan_oldest_payment_loan_list = set()
        loan_oldest_payment_list = set()
        for idx in list(range(0, total_number_of_loans, batch_size)):
            if total_number_of_loans == 1:
                query_for_oldest_payment_batched = query_for_oldest_payment.format(
                    loans_ids_list_chunked="(" + str(loans_ids_list_chunked[0]) + ")")
            else:
                query_for_oldest_payment_batched = query_for_oldest_payment.format(
                    loans_ids_list_chunked=
                    str(tuple(loans_ids_list_chunked[idx: idx + batch_size])))
            with connection.cursor() as cursor:
                cursor.execute(query_for_oldest_payment_batched)
                data = cursor.fetchall()

            for loan_id, payment_id, payment_due_date in data:
                if loan_id not in loan_oldest_payment_mapping:
                    loan_oldest_payment_mapping[loan_id] = dict()
                    loan_oldest_payment_loan_list.add(loan_id)
                    loan_oldest_payment_list.add(payment_id)
                loan_oldest_payment_mapping[loan_id]['oldest_payment'] = payment_id
                loan_oldest_payment_mapping[loan_id]['oldest_due_date'] = payment_due_date

        optimized_payment_qs = Payment.objects.select_related('loan__customer').prefetch_related(
            *prefetch_join_tables
        ).filter(
            id__in=loan_oldest_payment_list
        )

        loan_xids = optimized_payment_qs.filter(loan__isnull=False, loan__loan_xid__isnull=False).\
            prefetch_related('loan').values_list('loan__loan_xid', flat=True)

        # filter optimized payment qs with loan_xid
        loan_xids_based_on_c_score_list = get_loan_xids_based_on_c_score(
            GrabIntelixCScore.objects.all(), rank, loan_xid=loan_xids
        )

        if rank not in {7,8}:
            optimized_payment_qs = optimized_payment_qs.filter(
                loan__loan_xid__in=loan_xids_based_on_c_score_list
            )
        else:
            # for rank 7 and 8 the loan xid used for exlucding
            optimized_payment_qs = optimized_payment_qs.exclude(
                loan__loan_xid__in=loan_xids_based_on_c_score_list
            )

        total_oldest_payment_qs = optimized_payment_qs.count()
        split_threshold = 5000
        grouped_by_loan_customer_and_max_dpd = []

        for iterator in list(range(0, total_oldest_payment_qs, split_threshold)):
            oldest_payment_qs_sliced = optimized_payment_qs[iterator:iterator + split_threshold]

            """
            group the data by loan_id and max_dpd
            e.g:
            [
                {'loan_id': 3000009060, 'loan__customer_id': 10001, 'max_dpd': 487},
                {'loan_id': 3000009075, 'loan__customer_id': 10001, 'max_dpd': 695},
                {'loan_id': 3000009083, 'loan__customer_id': 10003, 'max_dpd': 695}
            ]
            """

            for payment in oldest_payment_qs_sliced:
                if not any(
                        d['loan_id'] == payment.loan.id and d['customer_id'] == payment.loan.customer.id
                        for
                        d in grouped_by_loan_customer_and_max_dpd):
                    try:
                        max_dpd = get_max_dpd_intellix_on_loan_level(
                            payment, loan_oldest_payment_loan_list, loan_oldest_payment_mapping)
                    except GrabLogicException as gle:
                        logger.info({
                            "task": "get_eligible_grab_payment_for_dialer",
                            "status": "skipping_payment",
                            "payment_id": payment.id
                        })
                        continue
                    if max_dpd < MINIMUM_DPD_VALUE:
                        continue
                    temp_grouped_dict = {
                        'loan_id': payment.loan.id,
                        'customer_id': payment.loan.customer.id,
                        'max_dpd': max_dpd
                    }
                    grouped_by_loan_customer_and_max_dpd.append(temp_grouped_dict)

        # get the highest dpd from loan which have same customer_id
        unique_loan_customer_and_dpd = {}
        for item in grouped_by_loan_customer_and_max_dpd:
            final_dpd = item.get('max_dpd')
            if item.get('customer_id') not in unique_loan_customer_and_dpd:
                unique_loan_customer_and_dpd[item.get("customer_id")] = item
            elif item.get('customer_id') in unique_loan_customer_and_dpd and \
                    unique_loan_customer_and_dpd[item.get('customer_id')].get(
                        'max_dpd') < final_dpd:
                unique_loan_customer_and_dpd[item.get("customer_id")] = item

        # get all data with correct dpd required
        loan_ids_with_correct_dpd = set()
        for data in unique_loan_customer_and_dpd.values():
            loan_id = data.get('loan_id')
            max_dpd = data.get('max_dpd')
            is_loan_max_dpd_around_2_and_90_high_risk = 2 <= max_dpd <= 90 and rank in {1, 2}
            is_loan_max_dpd_around_7_and_90 = 7 <= max_dpd <= 90 and rank in {3, 4}
            is_loan_max_dpd_around_14_and_90 = 14 <= max_dpd <= 90 and rank in {5, 6}
            is_loan_max_dpd_around_2_and_90 = 2 <= max_dpd <= 90 and rank > 6
            is_loan_max_dpd_above_90 = max_dpd > 90
            if (is_loan_below_91 and is_loan_max_dpd_around_2_and_90) or (
                    not is_loan_below_91 and is_loan_max_dpd_above_90) or (
                    is_loan_below_91 and is_loan_max_dpd_around_2_and_90_high_risk) or (
                    is_loan_below_91 and is_loan_max_dpd_around_7_and_90) or (
                    is_loan_below_91 and is_loan_max_dpd_around_14_and_90):
                loan_ids_with_correct_dpd.add(loan_id)

        data = None
        for loan_ids_with_correct_dpd_chunked in chunks(list(loan_ids_with_correct_dpd), n_chunks):
            loan_ids_with_correct_dpd_chunked = set(loan_ids_with_correct_dpd_chunked)
            filtered_data_by_dpd = optimized_payment_qs.filter(
                loan_id__in=loan_ids_with_correct_dpd_chunked)
            list_account_ids = []
            if use_outstanding:
                loan_ids_with_correct_outstanding = set()
                # will replace this section using raw query later
                for payment in filtered_data_by_dpd.iterator():
                    loan = payment.loan
                    outstanding_amount = loan.payment_set.not_paid_active().aggregate(
                        Sum('due_amount'))['due_amount__sum'] or 0

                    if is_above_100k and outstanding_amount > 100000:
                        loan_ids_with_correct_outstanding.add(loan.id)
                        if loan.account_id:
                            list_account_ids.append(loan.account_id)

                data = optimized_payment_qs.filter(loan_id__in=loan_ids_with_correct_outstanding).\
                    order_by('loan_id', 'id').distinct('loan_id')
            else:
                for payment in filtered_data_by_dpd.iterator():
                    loan = payment.loan
                    if loan.account_id:
                        list_account_ids.append(loan.account_id)
                data = filtered_data_by_dpd.order_by('loan_id', 'id').distinct('loan_id')
            if list_account_ids:
                list_account_ids = list(set(list_account_ids))
            logger.info({
                "task": "get_eligible_grab_payment_for_dialer",
                "rank": rank,
                "status": "ending task"
            })
            yield data, list_account_ids


def get_grab_populated_data_for_calling(
        bucket_name, temporary_id_list, is_only_payment_id=False, specific_grab_payment_ids=None
):
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    filter_dict = dict(
        team=bucket_name,
        cdate__range=(today_min, today_max),
        id__in=temporary_id_list
    )
    if specific_grab_payment_ids:
        filter_dict.update(dict(id__in=specific_grab_payment_ids))

    populated_call_dialer_data = GrabCollectionDialerTemporaryData.objects.filter(**filter_dict)
    if is_only_payment_id:
        return list(populated_call_dialer_data.values_list('payment_id', flat=True))
    return populated_call_dialer_data


def construct_grab_data_for_sent_to_intelix_by_temp_data(populated_temp_data_qs):
    # Get payment data
    today = timezone.localtime(timezone.now()).date()
    today_str = datetime.strftime(today, "%Y-%m-%d")
    constructed_calling_data = []
    for populated_temp_data in populated_temp_data_qs:
        payment = Payment.objects.get(pk=populated_temp_data.payment_id)
        if not payment:
            continue
        loan = payment.loan
        account = loan.account
        application = account.last_application
        last_agent = ''
        last_call_status = ''
        repeat_or_first_time = ''
        disbursement_period = ''
        partner_name = ''
        autodebet_status = "Tidak Aktif"

        phone_numbers = get_grab_phone_numbers_filter_by_intelix_blacklist(application)
        others, last_pay_details, outstanding_amount = construct_additional_data_for_intelix_grab(
            payment)
        va_indomaret, va_alfamart, va_maybank, va_permata, va_bca = '', '', '', '', ''

        zip_code = application.address_kodepos
        params = {
            "loan_id": None,
            "payment_id": None,
            "mobile_phone_1": phone_numbers['mobile_phone_1'],
            "mobile_phone_2": phone_numbers['mobile_phone_2'],
            "telp_perusahaan": phone_numbers['company_phone_number'],
            "angsuran/bulan": get_angsuran_for_intelix_grab(payment),
            "denda": get_late_fee_amount_intelix_grab(payment),
            "outstanding": outstanding_amount,
            "angsuran_ke": '',
            "no_telp_pasangan": phone_numbers['spouse_mobile_phone'],
            "no_telp_kerabat": phone_numbers['kin_mobile_phone'],
            "tgl_upload": today_str,
            "va_bca": va_bca,
            "va_permata": va_permata,
            "va_maybank": va_maybank,
            "va_alfamart": va_alfamart,
            "va_indomaret": va_indomaret,
            "campaign": "JULO",
            "jumlah_pinjaman": get_jumlah_pinjaman_intelix_grab(payment),  # on the fly
            "tenor": None,
            "partner_name": partner_name,
            "last_agent": last_agent,
            "last_call_status": last_call_status,
            "customer_bucket_type": check_grab_customer_bucket_type(payment),
            "zip_code": zip_code,
            'disbursement_period': disbursement_period,
            'repeat_or_first_time': repeat_or_first_time,
            'account_id': payment.loan.account_id,
            'is_j1': False,
            'Autodebit': autodebet_status,
            'refinancing_status': '',
            'activation_amount': '',
            'program_expiry_date': '',
            'promo_untuk_customer': ''
        }
        constructed_data = dict()
        constructed_data['application_id'] = populated_temp_data.application_id
        constructed_data['customer_id'] = populated_temp_data.customer_id
        constructed_data['nama_customer'] = populated_temp_data.nama_customer
        constructed_data['nama_perusahaan'] = populated_temp_data.nama_perusahaan
        constructed_data['posisi_karyawan'] = populated_temp_data.posisi_karyawan
        constructed_data['nama_pasangan'] = populated_temp_data.nama_pasangan
        constructed_data['nama_kerabat'] = populated_temp_data.nama_kerabat
        constructed_data['hubungan_kerabat'] = populated_temp_data.hubungan_kerabat
        constructed_data['jenis_kelamin'] = populated_temp_data.jenis_kelamin
        constructed_data['tgl_lahir'] = populated_temp_data.tgl_lahir
        constructed_data['tgl_gajian'] = populated_temp_data.tgl_gajian
        constructed_data['tujuan_pinjaman'] = populated_temp_data.tujuan_pinjaman
        constructed_data['tanggal_jatuh_tempo'] = populated_temp_data.tanggal_jatuh_tempo
        constructed_data['alamat'] = populated_temp_data.alamat
        constructed_data['kota'] = populated_temp_data.kota
        constructed_data['tipe_produk'] = populated_temp_data.tipe_produk
        constructed_data['partner_name'] = populated_temp_data.partner_name
        constructed_data['account_payment_id'] = populated_temp_data.account_payment_id
        constructed_data['dpd'] = populated_temp_data.dpd
        constructed_data['team'] = populated_temp_data.team
        constructed_data['loan_id'] = populated_temp_data.loan_id
        constructed_data['payment_id'] = populated_temp_data.payment_id
        constructed_data.update(params)
        constructed_data.update(others)
        constructed_data.update(last_pay_details)
        constructed_calling_data.append(constructed_data)

    return constructed_calling_data


def construct_and_temporary_save_grab_intelix_data(populated_temp_data_qs):
    logger.info({
        "action": "construct_and_temporary_save_grab_intelix_data",
        "status": "starting construct_and_temporary_save_grab_intelix_data",
    })
    constructed_calling_data_obj = []
    today = timezone.localtime(timezone.now()).date()
    today_str = datetime.strftime(today, "%Y-%m-%d")
    max_create_batch_size = 25
    total_data = 0
    for populated_temp_data in populated_temp_data_qs:
        payment = populated_temp_data.payment
        if not payment:
            continue
        loan = payment.loan
        if loan.status not in set(LoanStatusCodes.grab_current_until_180_dpd()):
            continue
        account = loan.account
        application = account.prefetched_applications[0]
        phone_numbers = get_grab_phone_numbers_filter_by_intelix_blacklist(application)
        others, last_pay_details, outstanding_amount = construct_additional_data_for_intelix_grab(
            payment)
        zip_code = application.address_kodepos
        angsuran = get_angsuran_for_intelix_grab(payment)
        denda = 0
        jumlah_pinjaman = get_jumlah_pinjaman_intelix_grab(payment)
        customer_bucket_type = check_grab_customer_bucket_type(payment)
        grab_constructed = GrabConstructedCollectionDialerTemporaryData(
            application_id=populated_temp_data.application_id,
            customer_id=populated_temp_data.customer_id,
            nama_customer=populated_temp_data.nama_customer,
            nama_perusahaan=populated_temp_data.nama_perusahaan,
            posisi_karyawan=populated_temp_data.posisi_karyawan,
            nama_pasangan=populated_temp_data.nama_pasangan,
            nama_kerabat=populated_temp_data.nama_kerabat,
            hubungan_kerabat=populated_temp_data.hubungan_kerabat,
            jenis_kelamin=populated_temp_data.jenis_kelamin,
            tgl_lahir=populated_temp_data.tgl_lahir,
            tgl_gajian=populated_temp_data.tgl_gajian,
            tujuan_pinjaman=populated_temp_data.tujuan_pinjaman,
            tanggal_jatuh_tempo=populated_temp_data.tanggal_jatuh_tempo,
            alamat=populated_temp_data.alamat,
            kota=populated_temp_data.kota,
            tipe_produk=populated_temp_data.tipe_produk,
            partner_name=populated_temp_data.partner_name,
            account_payment_id=populated_temp_data.account_payment_id,
            dpd=populated_temp_data.dpd,
            team=populated_temp_data.team,
            loan_id=None,
            payment_id=None,
            mobile_phone_1=phone_numbers['mobile_phone_1'],
            mobile_phone_2=phone_numbers['mobile_phone_2'],
            telp_perusahaan=phone_numbers['company_phone_number'],
            angsuran=angsuran,
            denda=denda,
            outstanding=outstanding_amount,
            angsuran_ke='',
            no_telp_pasangan=phone_numbers['spouse_mobile_phone'],
            no_telp_kerabat=phone_numbers['kin_mobile_phone'],
            tgl_upload=today_str,
            va_bca='',
            va_permata='',
            va_maybank='',
            va_alfamart='',
            va_indomaret='',
            campaign="JULO",
            jumlah_pinjaman=jumlah_pinjaman,
            tenor=None,
            last_agent='',
            last_call_status='',
            customer_bucket_type=customer_bucket_type,
            zip_code=zip_code,
            disbursement_period='',
            repeat_or_first_time='',
            account_id=payment.loan.account_id,
            is_j1=False,
            Autodebit="Tidak Aktif",
            refinancing_status='',
            activation_amount='',
            program_expiry_date='',
            promo_untuk_customer='',
            last_pay_date=last_pay_details["last_pay_date"],
            last_pay_amount=last_pay_details["last_pay_amount"],
            status_tagihan=others,  # JSON field,
            sort_order=populated_temp_data.sort_order
        )
        constructed_calling_data_obj.append(grab_constructed)
        total_data += 1
        if len(constructed_calling_data_obj) == max_create_batch_size:
            GrabConstructedCollectionDialerTemporaryData.objects.bulk_create(
                constructed_calling_data_obj, batch_size=max_create_batch_size
            )
            constructed_calling_data_obj = []

    if constructed_calling_data_obj:
        GrabConstructedCollectionDialerTemporaryData.objects.bulk_create(
            constructed_calling_data_obj
        )

    logger.info({
        "action": "construct_and_temporary_save_grab_intelix_data",
        "status": "ending construct_and_temporary_save_grab_intelix_data",
    })

    return total_data


def construct_additional_data_for_intelix_grab(data):
    last_pay_details = {'last_pay_date': '', 'last_pay_amount': 0}
    others = {}
    outstanding_amount = 0
    INTELIX_MAX_CAPACITY = 16

    if not data:
        return others, last_pay_details, outstanding_amount

    payment = data
    loan = payment.loan
    account = loan.account
    all_loans = account.loan_set.all()
    payment_dict_outer = defaultdict()
    for loan_obj in all_loans:
        if loan_obj.loan_status_id not in set(LoanStatusCodes.grab_above_90_dpd()):
            continue
        payments = loan_obj.payment_set.normal().order_by('payment_number')
        for payment_iter in payments:
            if payment_iter.payment_status_id not in set(PaymentStatusCodes.not_paid_status_codes()):
                continue
            payment_dict_outer = update_payment_dict(payment_dict_outer, payment_iter)

    payment_due_dates = list(payment_dict_outer.keys())
    payment_due_dates.sort()

    if payment_due_dates:
        last_pay_amount = payment_dict_outer[payment_due_dates[-1]]['paid_amount']
        last_pay_dates = payment_dict_outer[payment_due_dates[-1]]['paid_date']
        last_pay_date = '' if last_pay_dates is None else last_pay_dates

        last_pay_details = {'last_pay_date': str(last_pay_date), 'last_pay_amount': last_pay_amount}
        final_idx = 0
        for idx, payment_due_date in enumerate(payment_due_dates):
            final_idx = idx + 1
            """
                if more than 15 status tagihan exist then
                break out since intelix
                can handle only 15 at a time on agent page.
                This section avoids sending unnecessary data to intelix.
            """
            if final_idx < INTELIX_MAX_CAPACITY:
                month_of_year = datetime.strftime(payment_due_date, "%d %B %Y")
                day = month_of_year.split()[0]
                month = month_of_year.split()[1][0:3]
                year = month_of_year.split()[2]
                status_code = get_payment_status_code_grab_intellix(
                    payment_due_date, payment_dict_outer[payment_due_date]['due_amount'])
                value = day + ' ' + month + ' ' + year + "; " + str(status_code) + "; " + str(
                    payment_dict_outer[payment_due_date]['due_amount'])
                others['%s_status_tagihan' % str(idx + 1)] = value
            outstanding_amount += payment_dict_outer[payment_due_date]['due_amount']

        # If less than 15 status tagihan, Pad remaining values
        if final_idx < INTELIX_MAX_CAPACITY:
            for idx in range(final_idx, INTELIX_MAX_CAPACITY - 1):
                others['%s_status_tagihan' % str(idx + 1)] = ''

    return others, last_pay_details, outstanding_amount


def record_intelix_log_grab_improved(objects, bucket, dialer_task):
    if not objects:
        return
    sent_to_dialers = []

    for _object in objects:
        payment = Payment.objects.get(pk=_object.payment_id)
        sent_to_dialer = dict(
            account=payment.loan.account,
            payment=payment,
            bucket=bucket,
            sorted_by_collection_model=True if _object.sort_order else False,
            sort_rank=_object.sort_order,
            dialer_task=dialer_task,
            loan=payment.loan
        )
        sent_to_dialers.append(SentToDialer(**sent_to_dialer))

    SentToDialer.objects.bulk_create(sent_to_dialers, batch_size=500)


def get_angsuran_for_intelix_grab(payment):
    if not payment:
        return 0
    if payment.__class__ is Payment:
        loan = payment.loan
        account = loan.account
        active_loans = account.loan_set.filter(
            loan_status_id__in=LoanStatusCodes.grab_above_90_dpd()
        )
        total_installment_amount = 0
        for loan_obj in active_loans:
            total_installment_amount += loan_obj.installment_amount
        return total_installment_amount
    elif payment.__class__ is AccountPayment:
        return payment.due_amount


def get_late_fee_amount_intelix_grab(payment):
    if not payment:
        return 0
    if payment.__class__ is Payment:
        loan = payment.loan
        account = loan.account
        prefetched_loan_set = account.loan_set.all()
        late_fee_amount = 0
        for loan_obj in prefetched_loan_set:
            payments = loan_obj.payment_set.normal().order_by('payment_number')
            for payment_iter in payments:
                if payment_iter.due_date == payment.due_date:
                    late_fee_amount += payment_iter.late_fee_amount
        return late_fee_amount
    elif payment.__class__ is AccountPayment:
        return payment.due_amount


def get_jumlah_pinjaman_intelix_grab(payment):
    if not payment:
        return 0

    if payment.__class__ is Payment:
        loan = payment.loan
        account = loan.account
        active_loans = account.loan_set.filter(
            loan_status_id__in=LoanStatusCodes.grab_above_90_dpd()
        )
        total_loan_amount = 0
        for loan_obj in active_loans:
            total_loan_amount += loan_obj.loan_amount
        return total_loan_amount
    elif payment.__class__ is AccountPayment:
        account = payment.account
        sum_details = account.loan_set.filter(
            loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            loan_status_id__gt=LoanStatusCodes.INACTIVE).aggregate(Sum('loan_amount'))
        return sum_details['loan_amount__sum']


def update_payment_dict(payment_dict, payment):
    if payment.due_date in set(payment_dict.keys()):
        return update_payment_data_dict(payment_dict, payment)

    payment_dict[payment.due_date] = format_payment_data(payment)
    return payment_dict


def update_payment_data_dict(my_dict_outer, payment):
    my_dict = my_dict_outer[payment.due_date]
    my_dict['due_amount'] += payment.due_amount
    my_dict['paid_amount'] += payment.paid_amount
    my_dict['installment_principal'] += payment.installment_principal
    my_dict['installment_interest'] += payment.installment_interest
    my_dict['paid_principal'] += payment.paid_principal
    my_dict['paid_interest'] += payment.paid_interest
    my_dict['late_fee_amount'] += payment.late_fee_amount
    my_dict['paid_late_fee'] += payment.paid_late_fee
    my_dict['payment_ids'].add(payment.id)
    if not my_dict['paid_date']:
        my_dict['paid_date'] = payment.paid_date
    elif payment.paid_date and my_dict['paid_date'] < payment.paid_date:
        my_dict['paid_date'] = payment.paid_date
    my_dict_outer[payment.due_date] = my_dict
    return my_dict_outer


def format_payment_data(payment):
    my_dict = dict()
    my_dict['due_amount'] = payment.due_amount
    my_dict['paid_amount'] = payment.paid_amount
    my_dict['installment_principal'] = payment.installment_principal
    my_dict['installment_interest'] = payment.installment_interest
    my_dict['paid_principal'] = payment.paid_principal
    my_dict['paid_interest'] = payment.paid_interest
    my_dict['late_fee_amount'] = payment.late_fee_amount
    my_dict['paid_late_fee'] = payment.paid_late_fee
    my_dict['payment_ids'] = {payment.id}
    my_dict['paid_date'] = payment.paid_date
    return my_dict


def get_payment_status_code_grab_intellix(due_date, due_amount):
    DUE_SOON_DAYS = 3
    if not due_date or int(due_amount) == 0:
        dpd = 0
    else:
        time_delta = date.today() - due_date
        dpd = time_delta.days
    if due_amount == 0:
        return PaymentStatusCodes.PAID_ON_TIME
    if dpd < -DUE_SOON_DAYS:
        return PaymentStatusCodes.PAYMENT_NOT_DUE
    elif dpd < -1:
        return PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS
    elif dpd < 0:
        return PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS
    elif dpd == 0:
        return PaymentStatusCodes.PAYMENT_DUE_TODAY
    elif dpd < 5:
        return PaymentStatusCodes.PAYMENT_1DPD
    elif dpd < 30:
        return PaymentStatusCodes.PAYMENT_5DPD
    elif dpd < 60:
        return PaymentStatusCodes.PAYMENT_30DPD
    elif dpd < 90:
        return PaymentStatusCodes.PAYMENT_60DPD
    elif dpd < 120:
        return PaymentStatusCodes.PAYMENT_90DPD
    elif dpd < 150:
        return PaymentStatusCodes.PAYMENT_120DPD
    elif dpd < 180:
        return PaymentStatusCodes.PAYMENT_150DPD
    elif dpd >= 180:
        return PaymentStatusCodes.PAYMENT_180DPD


def get_grab_phone_numbers_filter_by_intelix_blacklist(application):
    phone_numbers = dict(
        company_phone_number=str(application.company_phone_number),
        kin_mobile_phone=str(application.kin_mobile_phone),
        spouse_mobile_phone=str(application.spouse_mobile_phone),
        mobile_phone_1=str(application.mobile_phone_1),
        mobile_phone_2=str(application.mobile_phone_2)
    )
    if application.is_grab():
        today = timezone.localtime(timezone.now()).date()
        intelix_blacklist_data = (
            intelixBlacklist.objects.filter(skiptrace__customer=application.customer)
            .filter(Q(expire_date__gte=today) | Q(expire_date__isnull=True))
            .select_related('skiptrace')
        )

        for intelix_blacklist in intelix_blacklist_data.iterator():
            for index in phone_numbers:
                if format_e164_indo_phone_number(
                    phone_numbers[index]
                ) == format_e164_indo_phone_number(intelix_blacklist.skiptrace.phone_number):
                    phone_numbers[index] = ''
                    break

    return phone_numbers


def check_grab_customer_bucket_type(payment):
    dpd = payment.due_late_days

    payment_dict_outer = defaultdict()
    for loan_obj in payment.loan.account.loan_set.all():
        payments = loan_obj.payment_set.normal().order_by('payment_number')
        for payment_iter in payments:
            payment_dict_outer = update_payment_dict(payment_dict_outer, payment_iter)

    payment_due_dates = list(payment_dict_outer.keys())
    payment_due_dates.sort()
    previous_paid_payment_due_dates = list()
    for payment_due_date in payment_due_dates:
        due_amount = payment_dict_outer[payment_due_date]['due_amount']
        if due_amount == 0:
            previous_paid_payment_due_dates.append(payment_due_date)

    status = get_payment_status_code_grab_intellix(
        payment.due_date, payment_dict_outer[payment.due_date]['due_amount'])
    if payment.is_paid and status == PaymentStatusCodes.PAID_ON_TIME:
        return 'NA'
    if dpd <= 0 and not payment.is_paid:
        return 'NA'
    current_payment_bucket = get_bucket_status(dpd)
    biggest_entered_bucket = 0
    for previous_payment_due_date in previous_paid_payment_due_dates:
        paid_date = payment_dict_outer[previous_payment_due_date]['paid_date']
        due_date = previous_payment_due_date
        if not paid_date:
            paid_date = timezone.localtime(timezone.now()).date()
        calculate_pay_on_dpd = paid_date - due_date
        dpd_when_paid = calculate_pay_on_dpd.days
        previous_bucket = get_bucket_status(dpd_when_paid)
        if previous_bucket > biggest_entered_bucket:
            biggest_entered_bucket = previous_bucket

    if current_payment_bucket <= biggest_entered_bucket:
        return 'Stabilized'

    return 'Fresh'


def get_redis_data_temp_table(
        redis_key, operating_param='get_list'):
    """
        Used for Dialer tasks.
        Use cases:
        1. Getting data from temporary table and redis

        Table used:
        ops.temporary_storage_dialer
    """
    redis_client = get_redis_client()
    logger.info({
        "action": "get_redis_data_temp_table_started",
        "key": redis_key,
        "operating_param": operating_param
    })
    if operating_param not in {'get_list', 'get'}:
        logger.info({
            "action": "get_redis_data_temp_table_invalid_operating_param",
            "key": redis_key,
            "operating_param": operating_param
        })
        raise Exception("Illegal operating parameter used {}".format(operating_param))
    get_data = None
    if redis_client:
        get_data = eval('redis_client.{}(redis_key)'.format(operating_param))

    if get_data:
        logger.info({
            "action": "get_redis_data_temp_table_captured_from_redis",
            "key": redis_key
        })
        if operating_param == 'get':
            data = ast.literal_eval(get_data)
            if not data:
                raise Exception("data not constructed on redis for send data {}".format(redis_key))
        else:
            data = list(map(int, get_data))
        logger.info({
            "action": "get_redis_data_temp_table_returning",
            "key": redis_key
        })
        return data

    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    temporary_data = TemporaryStorageDialer.objects.filter(
        key=redis_key, cdate__range=(today_min, today_max)).last()
    if not temporary_data:
        logger.info({
            "action": "get_redis_data_temp_table",
            "error": "No Data found",
            "key": redis_key
        })
        return
    data_from_db = json.loads(temporary_data.temp_values)
    logger.info({
        "action": "get_redis_data_temp_table_returning",
        "key": redis_key
    })
    return data_from_db


def set_redis_data_temp_table(
        redis_key, data, expiry_time, write_to_redis=True, operating_param='set_list'):
    """
        Used for Dialer tasks.
        Use cases:
        1. Storing data from temporary table and redis

        Table used:
        ops.temporary_storage_dialer
    """
    redis_client = get_redis_client()
    logger.info({
        "action": "set_redis_data_temp_table_started",
        "key": redis_key,
        "operating_param": operating_param,
        "write_to_redis": write_to_redis
    })
    if operating_param not in {'set_list', 'set'}:
        logger.info({
            "action": "set_redis_data_temp_table_invalid_operating_param",
            "key": redis_key,
            "operating_param": operating_param
        })
        raise Exception("Illegal operating parameter used {}".format(operating_param))
    if write_to_redis:
        eval('redis_client.{}(redis_key, data, expiry_time)'.format(operating_param))
        logger.info({
            "action": "set_redis_data_temp_table_wrote_to_redis",
            "key": redis_key,
            "operating_param": operating_param
        })
    TemporaryStorageDialer.objects.create(
        key=redis_key, temp_values=json.dumps(data, cls=DialerEncoder))
    logger.info({
        "action": "set_redis_data_temp_table_writing_to_db",
        "key": redis_key,
        "operating_param": operating_param
    })


def get_starting_and_ending_index_temp_data(bucket_name):
    current_time = timezone.localtime(timezone.now())
    today_min = datetime.combine(current_time, time.min)
    today_max = datetime.combine(current_time, time.max)
    grab_collection_dialer_temp_data_list = GrabCollectionDialerTemporaryData.objects.filter(
        team=bucket_name, cdate__range=(today_min, today_max)).values_list('id', flat=True)
    total_data = grab_collection_dialer_temp_data_list.count()

    return total_data, grab_collection_dialer_temp_data_list


def remove_duplicate_data_with_lower_rank():
    """
    Remove Duplicate Data with lower rank from GrabollectionDialerTemporaryData records
    """
    duplicate_ids_data = []
    distincted_data = GrabCollectionDialerTemporaryData.objects.values_list(
        'customer_id', flat=True).distinct()
    for customer_id in distincted_data.iterator():
        dups_data = GrabCollectionDialerTemporaryData.objects.filter(
            customer_id=customer_id).order_by('sort_order', '-dpd')[1:]
        dups_data_list = [data.id for data in dups_data]
        duplicate_ids_data.extend(dups_data_list)

    # bulk delete
    GrabCollectionDialerTemporaryData.objects.filter(
        id__in=duplicate_ids_data
    ).delete()


def get_not_paid_loan_in_last_2_days(restructured_loan, num_of_days):
    cut_off_dpd_date = timezone.localtime(timezone.now() - timedelta(days=num_of_days)).date()
    """
    this ORM below is based on this query
    https://docs.google.com/document/d/11zSKtbVOxaZpWXTaHavFWB45zT50cE6YUjCX0ceJsFw/edit#heading=h.abcjqvih8v8i
    """

    fully_paid_loan_in_last_2_days = PaymentEvent.objects.values(
        'payment__loan_id'
    ).annotate(
        total_payment=Sum('event_payment'),
        loan_installment=ExpressionWrapper(num_of_days * F('payment__loan__installment_amount'),
                                           output_field=IntegerField())
    ).filter(
        payment__loan_id__in=restructured_loan.values_list('loan_id', flat=True),
        cdate__date__gte=cut_off_dpd_date,
        total_payment=F('loan_installment')
    ).order_by()

    if fully_paid_loan_in_last_2_days:
        filtered_restructure_loan_ids = [data.get('payment__loan_id') for data in
                                         fully_paid_loan_in_last_2_days]
        restructured_loan = restructured_loan.exclude(
            loan_id__in=filtered_restructure_loan_ids
        )

    return restructured_loan


def get_not_paid_loan_in_last_2_days_custom(restructured_loan_ids, num_of_days):
    cut_off_dpd_date = timezone.localtime(timezone.now() - timedelta(days=num_of_days)).date()
    """
    this ORM below is based on this query
    https://docs.google.com/document/d/11zSKtbVOxaZpWXTaHavFWB45zT50cE6YUjCX0ceJsFw/edit#heading=h.abcjqvih8v8i
    """

    fully_paid_loan_in_last_2_days = PaymentEvent.objects.values(
        'payment__loan_id'
    ).annotate(
        total_payment=Sum('event_payment'),
        loan_installment=ExpressionWrapper(num_of_days * F('payment__loan__installment_amount'),
                                           output_field=IntegerField())
    ).filter(
        payment__loan_id__in=restructured_loan_ids,
        cdate__date__gte=cut_off_dpd_date,
        total_payment=F('loan_installment')
    )

    if fully_paid_loan_in_last_2_days:
        filtered_restructure_loan_ids = [data.get('payment__loan_id') for data in
                                         fully_paid_loan_in_last_2_days]
        restructured_loan_ids = [loan_id for loan_id in restructured_loan_ids if
                             loan_id not in filtered_restructure_loan_ids]

    return restructured_loan_ids


def get_loans_based_on_c_score(rank):
    grab_intelix_c_score_data = GrabIntelixCScore.objects.all()
    if rank in {1, 2}:
        cscore_range = (200, 449)
    elif rank in {3, 4}:
        cscore_range = (450, 599)
    elif rank in {5, 6}:
        cscore_range = (600, 800)
    else:
        return None
    loan_ids_based_on_c_score = []
    if grab_intelix_c_score_data:
        loan_ids_based_on_c_score = grab_intelix_c_score_data.filter(
            cscore__range=cscore_range).values_list('loan_xid', flat=True)
    return loan_ids_based_on_c_score


def get_loan_xids_based_on_c_score(grab_intellix_cscore_obj, rank, loan_xid=[]):
    if rank in {1, 2}:
        cscore_range = (200, 449)
    elif rank in {3, 4}:
        cscore_range = (450, 599)
    elif rank in {5, 6}:
        cscore_range = (600, 800)
    elif rank in {7, 8}:
        cscore_range = (200, 800)
    else:
        return []

    loan_ids_based_on_c_score = []
    if grab_intellix_cscore_obj:
        loan_ids_based_on_c_score = grab_intellix_cscore_obj.filter(cscore__range=cscore_range)
        if loan_xid:
            loan_ids_based_on_c_score = loan_ids_based_on_c_score.filter(loan_xid__in=loan_xid)

        loan_ids_based_on_c_score = loan_ids_based_on_c_score.values_list('loan_xid', flat=True)
    return loan_ids_based_on_c_score


def get_grab_active_ptp_account_ids(account_ids):
    today = timezone.localtime(timezone.now()).date()
    return PTP.objects.filter(
        ptp_status=None,
        ptp_date__gte=today,
        account_id__isnull=False,
        account_id__in=account_ids
    ).values_list('account_id', flat=True)


def grab_record_not_sent_to_intelix(payments, dialer_task, bucket_name):
    not_sent_data = []
    for payment in payments.iterator():
        loan = payment.loan
        is_paid_off = False
        paid_off_timestamp = None

        not_sent_data.append(NotSentToDialer(
            account=loan.account,
            loan=loan,
            payment=payment,
            bucket=bucket_name,
            dpd=payment.due_late_days,
            is_excluded_from_bucket=True,
            is_paid_off=is_paid_off,
            paid_off_timestamp=paid_off_timestamp,
            unsent_reason="Account is PTP Active",
            dialer_task=dialer_task
        ))
    NotSentToDialer.objects.bulk_create(not_sent_data, batch_size=30)


def get_max_dpd_intellix_on_loan_level(
        payment_obj, loan_oldest_payment_loan_list, loan_oldest_payment_mapping):
    """
    Get max dpd of loan by payment queryset

    parameters:
        - payment_obj: Payment Queryset Object = Payment object

    return:
        - days: int = days of dpd
    """
    days = 0
    loan_account_halt_info = list()
    loan = payment_obj.loan
    if not loan:
        raise GrabLogicException("The Loan was not found for Payment")
    loan_id = loan.id
    if loan_id not in loan_oldest_payment_loan_list:
        logger.info({
            "task": "get_max_dpd_intellix_on_loan_level",
            "loan_id": loan_id,
            "loan_oldest_payment_loan_list": loan_oldest_payment_loan_list
        })
        raise GrabLogicException("Loan Not found in Raw Query")
    oldest_due_date = loan_oldest_payment_mapping[loan_id]['oldest_due_date']
    grab_loan_data = loan.grab_loan_data_set
    account_halt_info = None
    if grab_loan_data:
        first_grab_loan_data = grab_loan_data[0]
        account_halt_info = first_grab_loan_data.account_halt_info
    base_date = date.today()
    time_delta = base_date - oldest_due_date
    if account_halt_info:
        if isinstance(account_halt_info, str):
            loaded_account_halt_info = json.loads(account_halt_info)
        else:
            loaded_account_halt_info = account_halt_info

        for account_halt_details in loaded_account_halt_info:
            account_halt_date = datetime.strptime(
                account_halt_details['account_halt_date'], '%Y-%m-%d').date()
            account_resume_date = datetime.strptime(
                account_halt_details['account_resume_date'], '%Y-%m-%d').date()
            account_halt_dict = {
                'account_halt_date': account_halt_date,
                'account_resume_date': account_resume_date
            }
            loan_account_halt_info.append(account_halt_dict)

        if loan.loan_status_id == LoanStatusCodes.HALT and loan_account_halt_info:
            raise GrabLogicException("Loan is in halted state")
        else:
            days_gap = 0
            for account_halt_data in loan_account_halt_info:
                if oldest_due_date < account_halt_data['account_halt_date']:
                    days_gap += (account_halt_data['account_resume_date']
                                 - account_halt_data['account_halt_date']).days
            time_delta = (base_date - oldest_due_date) - timedelta(days=days_gap)

    days = time_delta.days
    logger.debug({
        'task': 'get_max_dpd_intellix_on_loan_level',
        'due_date': oldest_due_date,
        'dpd': days,
        'loan_id': loan_id
    })
    return days

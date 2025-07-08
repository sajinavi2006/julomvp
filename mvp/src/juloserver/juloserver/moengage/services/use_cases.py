from ast import literal_eval
from builtins import str
from builtins import map
import logging
import time
from datetime import datetime, timedelta
from typing import List, Tuple

from django.utils import timezone
from django.db import transaction
from celery import task
from django.db.models import Max, F
from juloserver.account.models import AccountLimit
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    Payment,
    Loan,
    FeatureSetting,
    Customer,
    ExperimentSetting,
)
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.julo.exceptions import JuloException
from juloserver.qris.models import QrisPartnerLinkage
from ..models import (MoengageUpload, MoengageUploadBatch)
from juloserver.moengage.clients import get_julo_moengage_client
from juloserver.moengage.utils import (
    SendToMoengageManager,
    chunks,
    exception_captured,
)
from juloserver.julo.statuses import (
    JuloOneCodes,
    PaymentStatusCodes,
    LoanStatusCodes,
    CreditCardCodes,
)
from juloserver.moengage.services.data_constructors import (
    construct_data_for_account_status_change,
    construct_data_for_loan_payment_reminders_event,
    construct_data_for_payment_reminders_event,
    construct_data_for_loan_status_reminders_event,
    construct_data_for_hi_season_reminders_event,
    construct_data_for_loan_status_reminders,
    construct_data_for_application_status_reminders,
    construct_data_for_application_status_change_in_100,
    construct_data_for_application_status_change_in_105,
    construct_data_for_application_status_change_in_106,
    construct_application_status_change_event_data_for_j1_customer,
    construct_data_for_loan_status_change_j1_event,
    construct_event_attributes_for_fraud_ato_device_change,
    construct_julo_financing_event_data,
    construct_moengage_event_data,
    construct_qris_linkage_status_change_event_data,
    construct_user_attributes_customer_level,
    construct_user_attributes_customer_level_cashback_expiry,
    construct_user_attributes_for_realtime_basis,
    construct_base_data_for_account_payment_status_change,
    construct_user_attributes_for_realtime_basis_wl_url,
    construct_user_attributes_account_level_available_limit_change,
    construct_user_attributes_account_level,
    construct_user_attributes_customer_level_referral_change,
    construct_user_attributes_for_comms_blocked,
    construct_update_user_attributes_for_j1,
    construct_data_for_referral_event,
    APPLICATION_EVENT_STATUS_CONSTRUCTORS,
    construct_event_attributes_for_promo_code_usage,
    construct_user_attributes_with_linking_status,
    construct_data_for_julo_card_status_change_event,
    construct_data_for_rpc_sales_ops,
    construct_data_for_rpc_sales_ops_pds,
    construct_data_for_balance_consolidation_verification,
    construct_data_for_balance_consolidation_submit_form_id,
    construct_data_for_cfs_mission_verification_change,
    construct_data_for_jstarter_limit_approved,
    construct_data_for_early_limit_release,
    construct_data_for_typo_calls_unsuccessful,
    construct_data_for_change_lender,
    construct_data_for_idfy_verification_success,
    construct_data_for_idfy_completed_data,
    construct_data_for_customer_reminder_vkyc,
    construct_data_to_send_churn_users_to_moengage,
    construct_user_attributes_for_submit_bank_statement,
    construct_data_for_cashback_freeze_unfreeze,
    construct_user_attributes_for_graduation_downgrade,
    construct_data_for_active_julo_care,
    construct_user_attributes_for_customer_suspended_unsuspended,
    construct_user_attributes_for_active_platforms_rule,
    construct_data_for_emergency_consent_received,
    construct_customer_segment_data,
    construct_data_moengage_user_attributes,
    construct_customer_segment_data,
    construct_user_attributes_for_goldfish,
    construct_data_moengage_event_data,
    construct_event_data_for_gtl,
    construct_event_data_loyalty_mission_to_moengage,
    construct_user_attributes_loyalty_total_point_to_moengage,
    construct_data_julo_financing_verification,
    construct_data_for_customer_agent_assisted,
    construct_data_for_balcon_punishment,
    construct_data_for_cashback_delay_disbursement,
)
from juloserver.moengage.constants import (
    MoengageEventType,
    MoengageTaskStatus,
    MAX_EVENT,
    DELAY_FOR_MOENGAGE_EVENTS,
    DAYS_ON_STATUS,
    MAX_LIMIT,
    MoengageLoanStatusEventType,
    DAYS_ON_STATUS,
    MoengageAccountStatusEventType,
    UpdateFields,
    MoengageJuloCardStatusEventType,
)
from juloserver.julo.constants import FeatureNameConst, ApplicationStatusCodes, WorkflowConst
from juloserver.julo.partners import PartnerConstant
from datetime import timedelta
from django.conf import settings
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.services2 import get_redis_client
from juloserver.minisquad.constants import RedisKey
from juloserver.account.models import (
    Account,
    AccountStatusHistory,
    ExperimentGroup,
)
from juloserver.fraud_security.models import FraudFlag
from juloserver.sales_ops.models import (
    SalesOpsAgentAssignment,
    SalesOpsAccountSegmentHistory,
    SalesOpsRMScoring,
    SalesOpsLineup,
)
from juloserver.sales_ops.services import sales_ops_services
from juloserver.balance_consolidation.models import (
    BalanceConsolidationVerification,
    BalanceConsolidationVerificationHistory,
)
from juloserver.cfs.models import CfsAssignmentVerification
from juloserver.ana_api.models import PdChurnModelResult
from juloserver.loan.models import LoanJuloCare
from juloserver.loan.constants import JuloCareStatusConst
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.account_payment.services.earning_cashback import get_cashback_experiment
from juloserver.promo.models import PromoCode
from juloserver.streamlined_communication.models import Holiday
from juloserver.julo_financing.models import JFinancingVerification
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.moengage.exceptions import MoengageTypeNotFound
from juloserver.loyalty.models import LoyaltyPoint
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object


from juloserver.ana_api.models import CustomerSegmentationComms, QrisFunnelLastLog

logger = logging.getLogger(__name__)


@task(name='send_to_moengage', queue=settings.MOENGAGE_IO_HIGH_QUEUE)
def send_to_moengage(moengage_upload_ids, data_to_send, caller_name=None):
    logger_data = {
        'action': 'send_to_moengage',
        'caller_name': caller_name,
    }

    # Removes empty data_to_send to prevent API error to MoEngage
    # Side effect: Associated moengage_upload is still considered success even if data is removed.
    index = 0
    for _ in range(len(data_to_send)):
        if not data_to_send[index]:
            logger.info(
                {
                    'message': 'reject sending due to missing data',
                    'moengage_upload_ids': moengage_upload_ids[index],
                    **logger_data,
                }
            )
            del data_to_send[index]

            continue
        index += 1

    if not data_to_send:
        logger.info(
            {
                'message': 'data_to_send is empty',
                **logger_data,
            }
        )
        return

    moengage_client = get_julo_moengage_client()
    now = timezone.localtime(timezone.now())

    logger.info(
        {
            'action': 'send_to_moengage',
            'caller_name': caller_name,
            'message': 'sending data to moengage',
            'total_sent': len(data_to_send),
            'moengage_upload_ids': moengage_upload_ids,
        }
    )
    response = moengage_client.send_event(data_to_send)
    status = response.get('status')
    error = response.get('error')
    update_data_after_send_to_moengage.delay(moengage_upload_ids, status, error, now)


@task(name='update_data_after_send_to_moengage', queue='moengage_low')
def update_data_after_send_to_moengage(moengage_upload_ids, status, error, time_sent):
    moengage_uploads = MoengageUpload.objects.filter(
        id__in=moengage_upload_ids)
    for moengage_upload in moengage_uploads:
        fields_to_update = dict(
            status=status,
            time_sent=time_sent
        )
        if status != MoengageTaskStatus.SUCCESS:
            fields_to_update['error'] = error
        moengage_upload.update_safely(**fields_to_update)


@task(queue='moengage_io_skrtp_regeneration_queue')
def send_to_moengage_for_skrtp_regeneration(moengage_upload_ids, data_to_send):
    moengage_client = get_julo_moengage_client()
    now = timezone.localtime(timezone.now())

    logger.info({
        'message': 'sending data to moengage',
        'action': 'send_to_moengage',
        'total_sent': len(data_to_send),
        'moengage_upload_ids': moengage_upload_ids,
    })
    response = moengage_client.send_event(data_to_send)
    status = response.get('status')
    error = response.get('error')
    update_data_after_send_to_moengage_for_skrtp_regeneration.delay(moengage_upload_ids, status, error, now)


@task(queue='send_event_for_skrtp_regeneration_queue')
def update_data_after_send_to_moengage_for_skrtp_regeneration(moengage_upload_ids, status, error, time_sent):
    moengage_uploads = MoengageUpload.objects.filter(
        id__in=moengage_upload_ids)
    for moengage_upload in moengage_uploads:
        fields_to_update = dict(
            status=status,
            time_sent=time_sent
        )
        if status != MoengageTaskStatus.SUCCESS:
            fields_to_update['error'] = error
        moengage_upload.update_safely(**fields_to_update)


def get_eligible_oldest_payment():
    loans = Loan.objects\
        .filter(loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lt=LoanStatusCodes.RENEGOTIATED,
                application__customer__can_notify=True,
                application_id__isnull=False)\
        .values_list('id', flat=True)

    moengage_upload_data = Payment.objects.filter(
        loan_id__in=loans,
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME).exclude(
        loan__application__partner__name__in=PartnerConstant.form_partner()).exclude(
            is_restructured=True).exclude(
                loan__application_id__isnull=True).order_by(
                    'loan', 'id').distinct('loan').values_list(
                        'id', 'loan_id', 'loan__application_id')

    return moengage_upload_data


def update_moengage_for_scheduled_events():
    payment_ids = get_eligible_oldest_payment()

    if not payment_ids:
        return

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.LOAN_PAYMENT_REMINDER,
        data_count=len(payment_ids))
    update_moengage_for_loan_payment_reminders_event_bulk.\
        apply_async((payment_ids, moengage_upload_batch.id), countdown=DELAY_FOR_MOENGAGE_EVENTS)

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.PAYMENT_REMINDER,
        data_count=len(payment_ids))
    update_moengage_for_payment_reminders_event_bulk.\
        apply_async((payment_ids, moengage_upload_batch.id),
                    countdown=DELAY_FOR_MOENGAGE_EVENTS * 2)

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.LOAN_STATUS_CHANGE,
        data_count=len(payment_ids))
    update_moengage_for_loan_status_reminders_event_bulk.\
        apply_async((payment_ids, moengage_upload_batch.id),
                    countdown=DELAY_FOR_MOENGAGE_EVENTS * 3)

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.HI_SEASON_LOTTERY_REMINDER,
        data_count=len(payment_ids))
    update_moengage_for_hi_season_reminders_event_bulk.\
        apply_async((payment_ids, moengage_upload_batch.id),
                    countdown=DELAY_FOR_MOENGAGE_EVENTS * 4)


def update_moengage_for_scheduled_application_status_change_events():
    update_moengage_for_application_status_change_event.apply_async(
        (ApplicationStatusCodes.FORM_CREATED,
         DAYS_ON_STATUS[ApplicationStatusCodes.FORM_CREATED]),
        countdown=DELAY_FOR_MOENGAGE_EVENTS)

    update_moengage_for_application_status_change_event.apply_async(
        (ApplicationStatusCodes.FORM_PARTIAL,
         DAYS_ON_STATUS[ApplicationStatusCodes.FORM_PARTIAL]),
        countdown=DELAY_FOR_MOENGAGE_EVENTS * 2)

    update_moengage_for_application_status_change_event.apply_async(
        (ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
         DAYS_ON_STATUS[ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED]),
        countdown=DELAY_FOR_MOENGAGE_EVENTS * 3)

    update_moengage_for_application_status_change_event.apply_async(
        (ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
         DAYS_ON_STATUS[ApplicationStatusCodes.DIGISIGN_FACE_FAILED]),
        countdown=DELAY_FOR_MOENGAGE_EVENTS * 4)

    update_moengage_for_application_status_change_event.apply_async(
        (ApplicationStatusCodes.LOC_APPROVED,
         DAYS_ON_STATUS[ApplicationStatusCodes.LOC_APPROVED]),
        countdown=DELAY_FOR_MOENGAGE_EVENTS * 5)


@task(name='update_moengage_for_loan_payment_reminders_event_bulk')
def update_moengage_for_loan_payment_reminders_event_bulk(payment_ids,
                                                          moengage_upload_batch_id):

    max_event = MAX_EVENT
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MOENGAGE_EVENT, is_active=True).last()
    if active_feature:
        max_event = active_feature.parameters['loan_payment_reminder_max_event']

    for chunked_payment_ids in chunks(payment_ids, max_event):
        moengage_upload_ids = []
        data_to_send = []

        with transaction.atomic():
            for payment_id in chunked_payment_ids:
                moengage_upload = MoengageUpload.objects.create(
                    type=MoengageEventType.LOAN_PAYMENT_REMINDER,
                    payment_id=payment_id,
                    moengage_upload_batch_id=moengage_upload_batch_id)
                with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                    user_attributes, event_data, loan_id, application_id = \
                        construct_data_for_loan_payment_reminders_event(payment_id)
                    data_to_send.append(user_attributes)
                    data_to_send.append(event_data)
                    moengage_upload.update_safely(
                        loan_id=loan_id,
                        application_id=application_id,
                    )
                    moengage_upload_ids.append(moengage_upload.id)
            send_to_moengage.delay(moengage_upload_ids, data_to_send)

    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.\
            select_for_update().get(id=moengage_upload_batch_id)
        moengage_upload_batch.update_safely(status="all_dispatched")


@task(name='update_moengage_for_payment_reminders_event_bulk')
def update_moengage_for_payment_reminders_event_bulk(payment_ids, moengage_upload_batch_id):

    max_event = MAX_EVENT
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MOENGAGE_EVENT, is_active=True).last()
    if active_feature:
        max_event = active_feature.parameters['payment_reminder_max_event']

    for chunked_payment_ids in chunks(payment_ids, max_event):
        moengage_upload_ids = []
        data_to_send = []

        with transaction.atomic():
            for payment_id in chunked_payment_ids:
                moengage_upload = MoengageUpload.objects.create(
                    type=MoengageEventType.PAYMENT_REMINDER,
                    payment_id=payment_id,
                    moengage_upload_batch_id=moengage_upload_batch_id)
                with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                    user_attributes, event_data, loan_id, application_id = \
                        construct_data_for_payment_reminders_event(payment_id)
                    data_to_send.append(user_attributes)
                    data_to_send.append(event_data)
                    moengage_upload.update_safely(
                        loan_id=loan_id,
                        application_id=application_id,
                    )

                    moengage_upload_ids.append(moengage_upload.id)
            send_to_moengage.delay(moengage_upload_ids, data_to_send)

    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.select_for_update().get(
            id=moengage_upload_batch_id)
        moengage_upload_batch.update_safely(status="all_dispatched")


@task(name='update_moengage_for_loan_status_reminders_event_bulk')
def update_moengage_for_loan_status_reminders_event_bulk(moengage_upload_batch_id):
    max_event = MAX_EVENT
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MOENGAGE_EVENT, is_active=True).last()
    if active_feature:
        max_event = active_feature.parameters['loan_status_reminder_max_event']

    moengage_upload_ids = MoengageUpload.objects.filter(
        moengage_upload_batch_id=moengage_upload_batch_id
    ).values_list('id', 'payment_id').order_by('id')

    for chunked_moengage_upload in chunks(moengage_upload_ids, max_event):
        prepare_data_for_moengage.apply_async(
            (chunked_moengage_upload,),
            queue='lower',
            routing_key='lower')


@task(name='update_moengage_for_hi_season_reminders_event_bulk')
def update_moengage_for_hi_season_reminders_event_bulk(payment_ids, moengage_upload_batch_id):

    max_event = MAX_EVENT
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MOENGAGE_EVENT, is_active=True).last()
    if active_feature:
        max_event = active_feature.parameters['hi_season_reminder_max_event']

    for chunked_payment_ids in chunks(payment_ids, max_event):
        moengage_upload_ids = []
        data_to_send = []
        with transaction.atomic():
            for payment_id in chunked_payment_ids:
                moengage_upload = MoengageUpload.objects.create(
                    type=MoengageEventType.HI_SEASON_LOTTERY_REMINDER,
                    payment_id=payment_id,
                    moengage_upload_batch_id=moengage_upload_batch_id)
                with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                    user_attributes, event_data, loan_id, application_id = \
                        construct_data_for_hi_season_reminders_event(payment_id)
                    data_to_send.append(user_attributes)
                    data_to_send.append(event_data)
                    moengage_upload.update_safely(
                        loan_id=loan_id,
                        application_id=application_id,
                    )
                    moengage_upload_ids.append(moengage_upload.id)

            send_to_moengage.delay(moengage_upload_ids, data_to_send)

    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.select_for_update().get(
            id=moengage_upload_batch_id)
        moengage_upload_batch.update_safely(status="all_dispatched")


def update_moengage_for_loan_status_change(loan_id):
    from juloserver.julo.services import get_oldest_payment_due
    loan = Loan.objects.select_related("application").get(id=loan_id)
    if not loan:
        raise JuloException("loan: %s not found" % loan_id)
    customer = loan.customer
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.LOAN_STATUS_CHANGE,
        loan_id=loan_id,
        application_id=loan.application_id
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_loan_status_reminders(loan)
        data_to_send = []
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        send_to_moengage.delay([moengage_upload.id], data_to_send)

    oldest_payment_due = get_oldest_payment_due(loan)
    if oldest_payment_due:
        moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.LOAN_PAYMENT_REMINDER,
            loan_id=loan_id,
            application_id=loan.application_id
        )
        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            _, event_data, loan_id, application_id = \
                construct_data_for_loan_payment_reminders_event(oldest_payment_due.id)
            data_to_send = []
            user_attributes = dict()
            existing_customer = MoengageUpload.objects.filter(
                customer=customer
            )
            if not existing_customer:
                user_attributes = construct_user_attributes_for_realtime_basis(customer)
            else:
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer,
                    update_field='loan_status_code')
            data_to_send.append(user_attributes)
            data_to_send.append(event_data)
            send_to_moengage.delay([moengage_upload.id], data_to_send)


def update_moengage_for_application_status_change(application_id, new_status_code):
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        raise JuloException("application: %s not found" % application_id)
    customer = application.customer
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.APPLICATION_STATUS_CHANGE,
        application_id=application_id
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_application_status_reminders(
            application, new_status_code)
        data_to_send = []
        user_attributes = dict()
        existing_customer = MoengageUpload.objects.filter(
            customer=customer
        )
        if not existing_customer:
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
        else:
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer,
                update_field='application_status_code')
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        send_to_moengage.apply_async((
            [moengage_upload.id], data_to_send))


def update_moengage_for_payment_status_change(payment_id):
    payment = Payment.objects.select_related("loan__application").get(id=payment_id)
    application = payment.loan.application
    if application is None:
        return
    customer = application.customer
    if not payment:
        raise JuloException("payment: %s not found" % payment_id)
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.PAYMENT_REMINDER,
        payment_id=payment.id,
        loan_id=payment.loan_id,
        application_id=payment.loan.application_id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        _, event_data, loan_id, application_id = \
            construct_data_for_payment_reminders_event(payment_id)
        data_to_send = []
        user_attributes = dict()
        existing_customer = MoengageUpload.objects.filter(
            customer=customer
        )
        if not existing_customer:
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
        else:
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer,
                update_field='payment_status')
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        send_to_moengage.delay([moengage_upload.id], data_to_send)


def update_moengage_for_payment_due_amount_change(payment_id, payment_order):
    sleep_time = payment_order * settings.TIME_SLEEP_PAYMENT
    payment = Payment.objects.get_or_none(id=payment_id)
    customer = payment.loan.customer
    if not payment:
        raise JuloException("payment: %s not found" % payment_id)
    application = payment.loan.application
    if application is None:
        return
    time.sleep(sleep_time)

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.PAYMENT_REMINDER,
        payment_id=payment.id,
        loan_id=payment.loan_id,
        application_id=payment.loan.application_id
    )

    existing_customer = MoengageUpload.objects.filter(
        customer=customer
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        _, event_data, loan_id, application_id = \
            construct_data_for_payment_reminders_event(payment_id)
        user_attributes = dict()

        if not existing_customer:
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
        else:
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer,
                update_field='payment_status')

        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        send_to_moengage.delay([moengage_upload.id], data_to_send)

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.LOAN_PAYMENT_REMINDER,
        loan_id=payment.loan_id,
        payment_id=payment.id,
        application_id=payment.loan.application_id
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        _, event_data, loan_id, application_id = \
            construct_data_for_loan_payment_reminders_event(payment_id)
        data_to_send = []

        user_attributes = dict()
        if not existing_customer:
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
        else:
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer,
                update_field='loan_status_code')

        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        send_to_moengage.delay([moengage_upload.id], data_to_send)

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.HI_SEASON_LOTTERY_REMINDER,
        loan_id=payment.loan_id,
        payment_id=payment.id,
        application_id=payment.loan.application_id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data, loan_id, application_id = \
            construct_data_for_hi_season_reminders_event(payment_id)
        data_to_send = []
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        send_to_moengage.delay([moengage_upload.id], data_to_send)


def update_moengage_for_refinancing_request_status_change(loan_refinancing_request_id):
    from juloserver.julo.services import get_oldest_payment_due
    loan_refinancing = LoanRefinancingRequest.objects.filter(pk=loan_refinancing_request_id).last()

    if not loan_refinancing:
        raise JuloException("loan refinancing request: %s not found" % loan_refinancing_request_id)
    if loan_refinancing.account:
        return

    application = loan_refinancing.loan.application
    if application is None:
        return

    oldest_payment_due = get_oldest_payment_due(loan_refinancing.loan)
    if oldest_payment_due:
        moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.HI_SEASON_LOTTERY_REMINDER,
            loan_id=oldest_payment_due.loan_id,
            payment_id=oldest_payment_due.id,
            application_id=oldest_payment_due.loan.application_id
        )
        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            user_attributes, event_data, loan_id, application_id = \
                construct_data_for_hi_season_reminders_event(oldest_payment_due.id)
            data_to_send = []
            data_to_send.append(user_attributes)
            data_to_send.append(event_data)
            send_to_moengage.delay([moengage_upload.id], data_to_send)


# For J1 loan_status_change
def data_import_moengage_for_loan_status_change_event(loan_id, loan_status):
    loan = Loan.objects.get_or_none(id=loan_id)
    if not loan:
        raise JuloException("loan: %s not found" % loan_id)

    # This condition is to avoid sending the update on changing the status to 220 after fund
    # transferred. loan_status is also checked to avoid entry from any delayed status to 250
    if LoanStatusCodes.CURRENT in (loan.status, loan_status):
        now = timezone.localtime(timezone.now())
        if loan.fund_transfer_ts and (now - loan.fund_transfer_ts).days > 0:
            return
    event_type = 'STATUS_' +  str(loan_status)
    event_name = getattr(MoengageLoanStatusEventType, event_type)

    moengage_upload = MoengageUpload.objects.create(
        type=event_name,
        loan_id=loan.id,
        application_id=loan.application_id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        _, event_data = construct_data_for_loan_status_change_j1_event(
            loan, event_name)
        data_to_send = []
        user_attributes = dict()
        customer = loan.customer

        existing_customer = MoengageUpload.objects.filter(customer=customer)
        if not existing_customer:
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
        else:
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer,
                update_field='loan_status_code')

        experiment_group = get_cashback_experiment(customer.account.id)
        if experiment_group:
            user_attributes['attributes'].update(
                dict(cashback_new_scheme_experiment_group="experiment")
            )
        else:
            user_attributes['attributes'].update(
                dict(cashback_new_scheme_experiment_group="control")
            )

        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info({
            'action': 'send_data_to_moengage_for_loan_status_change_event',
            'customer_id': customer.id,
            'data_to_send': data_to_send
        })
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(name='update_moengage_for_application_status_change_event')
def update_moengage_for_application_status_change_event(
    status,
    days_on_status=None,
    application_id=None
):
    if application_id:
        data_to_send = []
        application = Application.objects.get(id=application_id)
        customer = application.customer
        if not application:
            raise JuloException("application: %s not found" % application_id)
        moengage_upload = MoengageUpload.objects.create(
            type=APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['event_type'],
            application_id=application.id
        )
        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            _, event_attributes = \
                APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['construct_data'](application_id)
            event_name = APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['event_type']
            event_data = construct_application_status_change_event_data_for_j1_customer(
                event_name,
                application_id,
                event_attributes
            )
            existing_customer = MoengageUpload.objects.filter(
                customer=customer
            )
            if not existing_customer:
                user_attributes = construct_user_attributes_for_realtime_basis(customer)
            else:
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer,
                    update_field='application_status_code')

            data_to_send.append(user_attributes)
            data_to_send.append(event_data)
            send_to_moengage.delay([moengage_upload.id], data_to_send)
    elif APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['scheduled'] and days_on_status:
        max_event = MAX_EVENT
        cdates = [datetime.today().date() - timedelta(days=d) for d in days_on_status]
        application_ids = ApplicationHistory.objects.filter(
            status_new=status,
            cdate__date__in=cdates,
            application__workflow__name=WorkflowConst.JULO_ONE,
            application__application_status_id=status).values_list('application_id', flat=True)

        if not application_ids:
            return
        moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['event_type'],
            data_count=len(application_ids))

        for chunked_application_ids in chunks(application_ids, max_event):
            moengage_upload_ids = []
            data_to_send = []

            with transaction.atomic():
                for application_id in chunked_application_ids:
                    moengage_upload = MoengageUpload.objects.create(
                        type=APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['event_type'],
                        application_id=application_id,
                        moengage_upload_batch_id=moengage_upload_batch.id)
                    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                        user_attributes, event_attributes = APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['construct_data'](application_id)
                        event_name = APPLICATION_EVENT_STATUS_CONSTRUCTORS[status]['event_type']
                        event_data = construct_application_status_change_event_data_for_j1_customer(
                            event_name,
                            application_id,
                            event_attributes
                        )
                        data_to_send.append(user_attributes)
                        data_to_send.append(event_data)
                        moengage_upload_ids.append(moengage_upload.id)
                send_to_moengage.apply_async(
                    (moengage_upload_ids, data_to_send))

        with transaction.atomic():
            moengage_upload_batch = MoengageUploadBatch.objects.\
                select_for_update().get(id=moengage_upload_batch.id)
            moengage_upload_batch.update_safely(status="all_dispatched")


def update_moengage_for_account_status_change(account_status_history_id):
    """
    Update account status and send the event triggered for account status change.
    The account status must be registered in MoengageAccountStatusEventType.

    Args:
        account_status_history_id (integer): The primary key of AccountStatusHistory

    Returns:
        None
    """
    account_status_history = AccountStatusHistory.objects.get(id=account_status_history_id)
    event_type = 'STATUS_' + str(account_status_history.status_new_id)
    event_name = getattr(
        MoengageAccountStatusEventType,
        event_type,
        MoengageEventType.ACCOUNT_STATUS_CHANGE,
    )

    moengage_upload = MoengageUpload.objects.create(
        type=event_name,
        customer_id=account_status_history.account.customer_id,
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=True):
        user_attributes, event_data = construct_data_for_account_status_change(
            account_status_history,
        )
        data_to_send = [user_attributes]
        if event_data:
            data_to_send.append(event_data)
        send_to_moengage.delay([moengage_upload.id], data_to_send)


# J1 customers
def bulk_update_moengage_for_scheduled_loan_status_change_210():
    days_on_status = [1, 2, 3]
    cdates = [datetime.today().date() - timedelta(days=d) for d in days_on_status]
    loan_ids = Loan.objects.filter(
        loan_status__status_code=LoanStatusCodes.INACTIVE,
        cdate__date__in=cdates,
        account__isnull=False).values_list('id', flat=True)

    if loan_ids:
        max_event = MAX_EVENT
        event_name = MoengageLoanStatusEventType.STATUS_210
        moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=event_name,
            data_count=len(loan_ids))

        for chunked_loan_ids in chunks(loan_ids, max_event):
            moengage_upload_ids = []
            data_to_send = []

            with transaction.atomic():
                for loan_id in chunked_loan_ids:
                    moengage_upload = MoengageUpload.objects.create(
                        type=event_name,
                        loan_id=loan_id,
                        moengage_upload_batch_id=moengage_upload_batch.id)
                    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                        loan = Loan.objects.get(id=loan_id)
                        customer = loan.customer
                        _, event_data = \
                            construct_data_for_loan_status_change_j1_event(loan, event_name)
                        user_attributes = dict()
                        existing_customer = MoengageUpload.objects.filter(
                            customer=customer
                        )

                        if not existing_customer:
                            user_attributes = construct_user_attributes_for_realtime_basis(customer)
                        else:
                            user_attributes = construct_user_attributes_for_realtime_basis(
                                customer,
                                update_field='loan_status_code')

                        data_to_send.append(user_attributes)
                        data_to_send.append(event_data)
                        moengage_upload_ids.append(moengage_upload.id)
                send_to_moengage.delay(moengage_upload_ids, data_to_send)

        with transaction.atomic():
            moengage_upload_batch = MoengageUploadBatch.objects.\
                select_for_update().get(id=moengage_upload_batch.id)
            moengage_upload_batch.update_safely(status="all_dispatched")


def bulk_create_moengage_upload():
    max_upload_data = 1000
    moengage_upload_data = get_eligible_oldest_payment()

    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=MoengageEventType.LOAN_STATUS_CHANGE,
            data_count=moengage_upload_data.count())
        moengage_upload_batch_id = moengage_upload_batch.id

        for chunked_moengage_upload_data in chunks(moengage_upload_data, max_upload_data):
            moengage_upload_list = []
            for payment_id, loan_id, application_id in chunked_moengage_upload_data:
                data = MoengageUpload(
                    type=MoengageEventType.LOAN_STATUS_CHANGE,
                    payment_id=payment_id,
                    moengage_upload_batch_id=moengage_upload_batch_id,
                    loan_id=loan_id,
                    application_id=application_id
                )
                moengage_upload_list.append(data)

            MoengageUpload.objects.bulk_create(moengage_upload_list)

        moengage_upload_batch.update_safely(status="all_dispatched")

    return moengage_upload_batch_id


@task(name='prepare_data_for_moengage')
def prepare_data_for_moengage(chunked_moengage_upload):
    if not chunked_moengage_upload:
        return
    moengage_upload_ids = []
    data_to_send = []
    for moengage_upload_id, payment_id in chunked_moengage_upload:
        with exception_captured(moengage_upload_id,
                                "construct_data_failed", reraise=False):
            event_data = construct_data_for_loan_status_reminders_event(payment_id)
            payment = Payment.objects.get(pk=payment_id)
            customer = payment.loan.customer
            user_attributes = dict()
            existing_customer = MoengageUpload.objects.filter(
                customer=customer
            )

            if not existing_customer:
                user_attributes = construct_user_attributes_for_realtime_basis(customer)
            else:
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer,
                    update_field='loan_status_code')
            data_to_send.append(user_attributes)
            data_to_send.append(event_data)
            moengage_upload_ids.append(moengage_upload_id)
    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(name='send_user_attributes_to_moengage_for_realtime_basis', queue='moengage_high')
def send_user_attributes_to_moengage_for_realtime_basis(
    customer_id,
    update_field=None,
    daily_update=False,
    moengage_upload_batch_id=None
):
    customer = Customer.objects.get(pk=customer_id)
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer_id=customer.id,
        moengage_upload_batch_id=moengage_upload_batch_id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_for_realtime_basis(
            customer, update_field=update_field, daily_update=daily_update)

        logger.info({
            'action': 'send_user_attributes_to_moengage_for_realtime_basis',
            'customer_id': customer.id,
            'user_attributes': user_attributes
        })
        data_to_send = [user_attributes]
        send_to_moengage.apply_async((
            [moengage_upload.id], data_to_send))


@task(queue='moengage_high')
def send_churn_users_to_moengage_in_bulk_daily(churn_ids: list, moengage_upload_batch_id: int):
    data_to_send = []
    moengage_upload_ids = []
    customers = PdChurnModelResult.objects.filter(id__in=churn_ids)
    for customer in customers:
        moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.IS_CHURN_EXPERIMENT,
            customer_id=customer.customer_id,
            moengage_upload_batch_id=moengage_upload_batch_id,
        )

        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            user_attributes, event_data = construct_data_to_send_churn_users_to_moengage(customer)
            logger.info(
                {
                    'action': 'send_churn_users_to_moengage_in_bulk_daily',
                    'customer_id': customer.customer_id,
                    'user_attributes': user_attributes,
                }
            )

            moengage_upload_ids.append(moengage_upload.id)
            data_to_send.append(user_attributes)
            data_to_send.append(event_data)

    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(queue='moengage_high')
def send_customer_segment_moengage_bulk(customer_ids: List[int], upload_batch_id: int):
    data_to_send = []
    moengage_upload_ids = []
    customer_segs = CustomerSegmentationComms.objects.filter(customer_id__in=customer_ids)
    # construct data for each customer segment
    for customer_seg in customer_segs:
        moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.CUSTOMER_SEGMENTATION,
            customer_id=customer_seg.customer_id,
            moengage_upload_batch_id=upload_batch_id,
        )

        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            user_attributes = construct_customer_segment_data(customer_seg)
            logger.info(
                {
                    'action': 'send_customer_segment_moengage_bulk',
                    'customer_id': customer_seg.customer_id,
                    'user_attributes': user_attributes,
                }
            )
            moengage_upload_ids.append(moengage_upload.id)
            data_to_send.append(user_attributes)

    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(queue='moengage_high')
def send_qris_master_agreement_data_moengage_bulk(customer_ids: List[int], upload_batch_id: int):
    data_to_send = []
    moengage_upload_ids = []
    qris_funnel_logs = QrisFunnelLastLog.objects.filter(customer_id__in=customer_ids)
    for qris_funnel_log in qris_funnel_logs:
        moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.QRIS_READ_SIGN_MASTER_AGREEMENT,
            customer_id=qris_funnel_log.customer_id,
            moengage_upload_batch_id=upload_batch_id,
        )

        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            user_attributes = construct_data_moengage_user_attributes(
                qris_funnel_log.customer_id,
                read_master_agreement_date=(
                    qris_funnel_log.read_master_agreement_date.isoformat()
                    if qris_funnel_log.read_master_agreement_date else None
                ),
                sign_master_agreement_date=(
                    qris_funnel_log.sign_master_agreement_date.isoformat()
                    if qris_funnel_log.sign_master_agreement_date else None
                )
            )

            logger.info(
                {
                    'action': 'send_qris_master_agreement_data_moengage_bulk',
                    'customer_id': qris_funnel_log.customer_id,
                    'user_attributes': user_attributes,
                }
            )
            moengage_upload_ids.append(moengage_upload.id)
            data_to_send.append(user_attributes)

    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(name='send_user_attributes_to_moengage_in_bulk_daily')
def send_user_attributes_to_moengage_in_bulk_daily(
    customer_list: Tuple, moengage_upload_batch_id: int
):
    """
    Processes a list of customer based on id. These customers will have their attributes in MoEngage
    updated.

    Args:
        customer_list (Tuple): A tuple of customers' ids.
        moengage_upload_batch_id (int): The id of MoengageUploadBatch that runs this process.
    """
    data_to_send = []
    moengage_upload_ids = []

    for customer_id in customer_list:
        customer = Customer.objects.get(pk=customer_id)

        moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.REALTIME_BASIS,
            customer_id=customer_id,
            moengage_upload_batch_id=moengage_upload_batch_id,
        )

        is_today_religious_holiday = Holiday.check_is_religious_holiday()

        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer, daily_update=True, is_religious_holiday=is_today_religious_holiday
            )

            logger.info(
                {
                    'action': 'send_user_attributes_to_moengage_in_bulk_daily',
                    'customer_id': customer_id,
                    'user_attributes': user_attributes,
                }
            )

            moengage_upload_ids.append(moengage_upload.id)
            data_to_send.append(user_attributes)

    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(name='send_user_attributes_to_moengage_for_block_comms')
def send_user_attributes_to_moengage_for_block_comms(
    customer,
    account_payment
):
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer_id=customer.id)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_for_comms_blocked(
            customer, account_payment)
        logger.info({
            'action': 'send_user_attributes_to_moengage_for_comms_block',
            'customer_id': customer.id,
            'user_attributes': user_attributes
        })
        data_to_send = []
        data_to_send.append(user_attributes)
        send_to_moengage.apply_async((
            [moengage_upload.id], data_to_send))


@task(name='update_moengage_for_account_payment_status_change')
def update_moengage_for_account_payment_status_change(status_history, status):
    account_payment = status_history.account_payment
    account = account_payment.account
    customer = account.customer
    if account_payment:
        data_to_send = []
        event_name = 'BEx' + str(status)
        last_application = account_payment.account.last_application
        moengage_upload = MoengageUpload.objects.create(
            type=event_name,
            application_id=last_application.id
        )
        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            _, event_attributes = \
                construct_base_data_for_account_payment_status_change(account_payment,
                                                                 status_history.cdate)
            event_data = construct_application_status_change_event_data_for_j1_customer(
                event_name,
                last_application.id,
                event_attributes
            )
            existing_customer = MoengageUpload.objects.filter(
                customer=customer
            )
            user_attributes = dict()
            if not existing_customer:
                user_attributes = construct_user_attributes_for_realtime_basis(customer)
            else:
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer,
                    update_field='due_amount')
            data_to_send.append(user_attributes)
            data_to_send.append(event_data)
            send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(name='update_moengage_for_wl_url_data')
def update_moengage_for_wl_url_data(customer, wl_url=None, mtl=False):
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer_id=customer.id)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_for_realtime_basis_wl_url(
            customer, wl_url, mtl)
        logger.info({
            'action': 'update_moengage_for_wl_url_data',
            'customer_id': customer.id,
            'user_attributes': user_attributes
        })
        data_to_send = []
        data_to_send.append(user_attributes)
        send_to_moengage.apply_async((
            [moengage_upload.id], data_to_send))


def get_customer_for_retargeting_campaign():
    moengage_upload_data = Customer.objects.annotate(last_app_id=Max('application__id')). \
        filter(application__id=F('last_app_id'), application__address_provinsi__isnull=False,
        loan__loan_status_id=250, can_reapply=True).values_list('id', flat=True)
    return moengage_upload_data


def bulk_create_moengage_retargeting_campaign():
    max_upload_data = 1000
    moengage_upload_data = get_customer_for_retargeting_campaign()
    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=MoengageEventType.REALTIME_BASIS,
            data_count=moengage_upload_data.count())
        moengage_upload_batch_id = moengage_upload_batch.id

        for chunked_moengage_upload_data in chunks(moengage_upload_data, max_upload_data):
            moengage_upload_list = []
            for customer_id in chunked_moengage_upload_data:
                data = MoengageUpload(
                    type=MoengageEventType.REALTIME_BASIS,
                    customer_id=customer_id,
                    moengage_upload_batch_id=moengage_upload_batch_id,
                )
                moengage_upload_list.append(data)
            MoengageUpload.objects.bulk_create(moengage_upload_list)
        moengage_upload_batch.update_safely(status="all_dispatched")
    return moengage_upload_batch_id


@task(name='prepare_data_for_moengage_retargeting_campaign')
def prepare_data_for_moengage_retargeting_campaign(chunked_moengage_upload):
    if not chunked_moengage_upload:
        return
    moengage_upload_ids = []
    data_to_send = []
    for moengage_upload_id, customer_id in chunked_moengage_upload:
        with exception_captured(moengage_upload_id,
                                "construct_data_failed", reraise=False):
            customer = Customer.objects.get(id=customer_id)
            user_attributes = dict()
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
            data_to_send.append(user_attributes)
            moengage_upload = MoengageUpload.objects.get(id=moengage_upload_id)
            moengage_upload_ids.append(moengage_upload_id)
    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(name='update_moengage_for_retargeting_campaign')
def update_moengage_for_retargeting_campaign(moengage_upload_batch_id):
    moengage_upload_ids = MoengageUpload.objects.filter(
        moengage_upload_batch_id=moengage_upload_batch_id
    ).values_list('id', 'customer_id').order_by('id')

    for chunked_moengage_upload in chunks(moengage_upload_ids, MAX_EVENT):
        prepare_data_for_moengage_retargeting_campaign.apply_async(
            (chunked_moengage_upload,),
            queue='lower',
            routing_key='lower')


@task(name='send_user_attributes_to_moengage_for_available_limit_created')
def send_user_attributes_to_moengage_for_available_limit_created(
        customer, account, available_limit, graduation_flow=None):
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer_id=customer.id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_account_level_available_limit_change(
            customer, account, available_limit)
        logger.info({
            'action': 'send_user_attributes_to_moengage_for_available_limit',
            'customer_id': customer.id,
            'user_attributes': user_attributes
        })
        data_to_send = []
        data_to_send.append(user_attributes)
        send_to_moengage.apply_async((
            [moengage_upload.id], data_to_send))


@task(name='send_user_attributes_to_moengage_for_self_referral_code_change')
def send_user_attributes_to_moengage_for_self_referral_code_change(customer_id):
    customer = Customer.objects.get(id=customer_id)
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer_id=customer.id)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_customer_level_referral_change(
            customer, 'self_referral_code')
        logger.info({
            'action': 'send_user_attributes_to_moengage_for_self_referral_code',
            'customer_id': customer.id,
            'user_attributes': user_attributes
        })
        data_to_send = []
        data_to_send.append(user_attributes)
        send_to_moengage.apply_async((
            [moengage_upload.id], data_to_send))

@task(name='send_user_attributes_to_moengage_for_va_change')
def send_user_attributes_to_moengage_for_va_change(customer_id):
    customer = Customer.objects.get(id=customer_id)
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer_id=customer.id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_update_user_attributes_for_j1(
            customer,
            ['payment_methods', 'primary_va'],
        )

        logger.info({
            'action': 'send_user_attributes_to_moengage_for_va_change',
            'customer_id': customer.id,
            'user_attributes': user_attributes
        })

        data_to_send = []
        data_to_send.append(user_attributes)

        send_to_moengage.delay([moengage_upload.id], data_to_send)



def bulk_create_moengage_upload_customer_update_j1(update_data, upload_data=None):
    max_upload_data = 1000
    moengage_upload_data = []
    if ('partner_name' in update_data) or ('payment_methods' in update_data):
        moengage_upload_data = Customer.objects.\
            annotate(last_app_id=Max('application__id')).\
            filter(application__product_line_id=ProductLineCodes.J1, application__partner_id__isnull=False).\
            values_list('id', flat=True)
    elif 'next_cashback_expiry_date' and 'next_cashback_expiry_total_amount' in update_data:
        moengage_upload_data = upload_data
    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=MoengageEventType.REALTIME_BASIS,
            data_count=moengage_upload_data.count())
        moengage_upload_batch_id = moengage_upload_batch.id

        for chunked_moengage_upload_data in chunks(moengage_upload_data, max_upload_data):
            moengage_upload_list = []
            for customer_id in chunked_moengage_upload_data:
                data = MoengageUpload(
                    type=MoengageEventType.REALTIME_BASIS,
                    customer_id=customer_id,
                    moengage_upload_batch_id=moengage_upload_batch_id,
                )
                moengage_upload_list.append(data)
            MoengageUpload.objects.bulk_create(moengage_upload_list)
        moengage_upload_batch.update_safely(status="all_dispatched")
    return moengage_upload_batch_id


@task(name='update_moengage_for_user_attribute_j1', queue='moengage_low')
def update_moengage_for_user_attribute_j1(moengage_upload_batch_id, update_data=[]):
    if not update_data:
        return

    moengage_upload_ids = MoengageUpload.objects.filter(
        moengage_upload_batch_id=moengage_upload_batch_id
    ).values_list('id', 'customer_id').order_by('id')

    for chunked_moengage_upload in chunks(moengage_upload_ids, MAX_EVENT):
        prepare_data_for_moengage_j1_user_attribute_update.apply_async(
            (chunked_moengage_upload, update_data))


@task(name='prepare_data_for_moengage_j1_user_attribute_update', queue='moengage_low')
def prepare_data_for_moengage_j1_user_attribute_update(chunked_moengage_upload, update_data=[]):
    if not chunked_moengage_upload and not update_data:
        return
    moengage_upload_ids = []
    data_to_send = []
    for moengage_upload_id, customer_id in chunked_moengage_upload:
        with exception_captured(moengage_upload_id,
                                "construct_data_failed", reraise=False):
            customer = Customer.objects.get(id=customer_id)
            user_attributes = dict()
            if 'next_cashback_expiry_date' and 'next_cashback_expiry_total_amount' in update_data:
                update_field = UpdateFields.CASHBACK
                user_attributes = construct_user_attributes_customer_level_cashback_expiry(customer, update_field)
            else:
                user_attributes = construct_update_user_attributes_for_j1(customer, update_data)
            logger.info({
                'action': 'prepare_data_for_moengage_j1_user_attribute_update',
                'customer_id': customer.id,
                'user_attributes': user_attributes
            })
            data_to_send.append(user_attributes)
            moengage_upload_ids.append(moengage_upload_id)
    send_to_moengage.delay(moengage_upload_ids, data_to_send)


@task(name="update_moengage_referral_event", queue="collection_normal")
def update_moengage_referral_event(customer, event_type, cashback_earned=None):
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer.id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_referral_event(
            customer,
            event_type,
            cashback_earned,
        )
        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)

        logger.info({
            'action': 'update_moengage_referral_event',
            'data': data_to_send
        })
        send_to_moengage.apply_async(
            ([moengage_upload.id], data_to_send)
        )


@task(queue='moengage_low')
def send_event_moengage_cashback_injection(
    customer_id, loan_id, promo_code_string, cashback_earned=None
):
    event_type = MoengageEventType.CASHBACK_INJECTION_FOR_PROMO + promo_code_string

    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer_id)

    event_time = timezone.localtime(timezone.now())
    customer = Customer.objects.get(pk=customer_id)
    account = customer.account
    event_attributes = {}
    device_id = ''

    if account:
        application = account.application_set.last()

    if application.device:
        device_id = application.device.gcm_reg_id

    event_attributes['loan_id'] = loan_id
    event_attributes['account_id'] = account.id
    event_attributes['customer_id'] = customer.id
    event_attributes['cashback_earned'] = cashback_earned

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_moengage_event_data(
            customer.id, device_id, event_type, event_attributes, event_time
        )

        data_to_send.append(event_data)

        logger.info({'action': 'send_event_moengage_cashback_injection', 'data': data_to_send})
        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))


# For J1 account status change
@task(name='async_moengage_events_for_j1_account_status_change')
def async_moengage_events_for_j1_account_status_change(loan_id, account_status_new):
    if account_status_new != JuloOneCodes.ACTIVE:
        return
    loan = Loan.objects.get_or_none(id=loan_id)
    if not loan:
        raise JuloException("loan: %s not found" % loan_id)

    event_type = 'STATUS_' +  str(account_status_new)
    event_name = getattr(MoengageAccountStatusEventType, event_type)

    moengage_upload = MoengageUpload.objects.create(
        type=event_name,
        loan_id=loan.id,
        customer_id=loan.customer_id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        _, event_data = construct_data_for_loan_status_change_j1_event(
            loan, event_name)
        data_to_send = []
        user_attributes = dict()
        customer = loan.customer
        existing_customer = MoengageUpload.objects.filter(
            customer=customer
        )
        if not existing_customer:
            user_attributes = construct_user_attributes_for_realtime_basis(customer)
        else:
            user_attributes = construct_user_attributes_for_realtime_basis(
                customer,
                update_field='loan_status_code')
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info({
            'action': 'async_moengage_events_for_j1_account_status_change',
            'customer_id': customer.id,
            'data_to_send': data_to_send
        })
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='collection_normal')
def send_user_attributes_to_moengage_for_tailor_exp(moengage_upload_batch_id):
    redis_client = get_redis_client()
    experiment_data = redis_client.get(RedisKey.TAILOR_EXPERIMENT_DATA)
    if not experiment_data:
        return

    experiment_data = literal_eval(experiment_data)
    with SendToMoengageManager() as moengage_manager:
        for item in experiment_data:
            account_payment = AccountPayment.objects.get_or_none(pk=item['account_payment'])
            if not account_payment:
                continue

            customer = account_payment.account.customer
            moengage_upload = MoengageUpload.objects.create(
                type=MoengageEventType.ATTRIBUTE_FOR_COLLECTION_TAILOR,
                customer_id=customer.id,
                moengage_upload_batch_id=moengage_upload_batch_id
            )

            with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer, daily_update=True)
                user_attributes['attributes'].update(dict(collection_segment=item['segment']))
                logger.info({
                    'action': 'send_user_attributes_to_moengage_for_tailor_exp',
                    'customer_id': customer.id,
                    'user_attributes': user_attributes
                })
                moengage_manager.add(moengage_upload.id, [user_attributes])


@task(queue='moengage_low')
def send_event_for_active_loan_to_moengage(loan_id, loan_status, event_type):
    if loan_status != LoanStatusCodes.CURRENT:
        return
    loan = Loan.objects.get(id=loan_id)

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        loan_id=loan.id,
        customer_id=loan.customer_id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        event_data = dict()
        if event_type == MoengageEventType.PROMO_CODE_USAGE:
            event_data = construct_event_attributes_for_promo_code_usage(loan, event_type)
        data_to_send = []
        customer = loan.customer
        data_to_send.append(event_data)
        logger.info({
            'action': 'send_event_for_active_loan_to_moengage',
            'customer_id': customer.id,
            'data_to_send': data_to_send
        })
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def update_moengage_for_user_linking_status(account_id, partner_origin_id, partner_loan_request_id=''):
    account = Account.objects.filter(id=account_id).last()
    if not account:
        return False

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS,
        customer=account.customer
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        user_attributes = construct_user_attributes_with_linking_status(account,
                                                                        partner_origin_id,
                                                                        partner_loan_request_id)
        data_to_send.append(user_attributes)
        logger.info({
            'action': 'update_moengage_for_user_linking_status',
            'event_type': 'realtime_basis',
            'data': data_to_send
        })
        send_to_moengage.apply_async(
            ([moengage_upload.id], data_to_send)
        )


@task(queue='moengage_low')
def send_fraud_ato_device_change_event(fraud_flag_id):
    fraud_flag = FraudFlag.objects.blocked_loan_device_change().get(id=fraud_flag_id)
    loan = Loan.objects.get(id=fraud_flag.flag_source_id)

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.FRAUD_ATO_DEVICE_CHANGE,
        customer_id=loan.customer_id
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_attributes = construct_event_attributes_for_fraud_ato_device_change(
            fraud_flag=fraud_flag,
            loan=loan,
        )
        data_to_send.append(event_attributes)
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_event_moengage_for_julo_card_status_change_event(
    credit_card_application_history_id: int
) -> None:
    from juloserver.credit_card.models import CreditCardApplicationHistory

    credit_card_application_history = CreditCardApplicationHistory.objects.filter(
        pk=credit_card_application_history_id
    ).last()
    if not credit_card_application_history:
        raise JuloException("credit_card_application_history: %s not found"
                            % credit_card_application_history_id)

    if credit_card_application_history.status_new_id not in {
        CreditCardCodes.CARD_APPLICATION_SUBMITTED,
        CreditCardCodes.CARD_ON_SHIPPING,
        CreditCardCodes.CARD_RECEIVED_BY_USER,
        CreditCardCodes.CARD_ACTIVATED
    }:
        return

    event_type = 'STATUS_' + str(credit_card_application_history.status_new_id)
    event_name = getattr(MoengageJuloCardStatusEventType, event_type)
    moengage_upload = MoengageUpload.objects.create(
        type=event_name,
        customer_id=credit_card_application_history.credit_card_application.account.customer_id,
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        event_data = construct_data_for_julo_card_status_change_event(
            credit_card_application_history, event_name
        )
        user_attributes = construct_user_attributes_for_realtime_basis(
            credit_card_application_history.credit_card_application.account.customer
        )
        data_to_send = []
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info({
            'action': 'send_event_moengage_for_julo_card_status_change_event',
            'credit_card_application_history_id': credit_card_application_history_id,
            'data_to_send': data_to_send
        })
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_event_moengage_for_rpc_sales_ops(agent_assignment_id):
    agent_assignment = SalesOpsAgentAssignment.objects.filter(id=agent_assignment_id).last()
    event_type = MoengageEventType.IS_SALES_OPS_RPC
    lineup_id = agent_assignment.lineup_id
    lineup = SalesOpsLineup.objects.get(pk=lineup_id)
    application = lineup.latest_application
    customer = application.customer

    account_segment_history = SalesOpsAccountSegmentHistory.objects.filter(
        account_id=application.account_id
    ).last()
    r_score = SalesOpsRMScoring.objects.get(id=account_segment_history.r_score_id).score
    promo_code = sales_ops_services.get_promotion_mapping_by_agent(agent_assignment.agent_id)
    if not promo_code:
        return

    is_valid = sales_ops_services.validate_promo_code_by_r_score(promo_code, r_score)
    if not is_valid:
        return

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer.id,
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        event_data = construct_data_for_rpc_sales_ops(
            application,
            event_type,
            agent_assignment,
            r_score,
            promo_code.promo_code.upper(),
            sales_ops_services.get_minimum_transaction_promo_code(promo_code)
        )
        logger.info({
            'action': 'send_event_moengage_for_rpc_sales_ops',
            'agent_assignment_id': agent_assignment_id,
            'data_to_send': [event_data]
        })
        send_to_moengage.delay([moengage_upload.id], [event_data])


@task(queue='moengage_low')
def send_event_moengage_for_rpc_sales_ops_pds(agent_assignment_id, promo_code_id):
    agent_assignment = SalesOpsAgentAssignment.objects.filter(
        id=agent_assignment_id
    ).last()
    promo_code = PromoCode.objects.filter(id=promo_code_id).last()

    event_type = MoengageEventType.IS_SALES_OPS_RPC_PDS
    lineup = SalesOpsLineup.objects.get(pk=agent_assignment.lineup_id)
    application = lineup.latest_application
    customer = application.customer

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.IS_SALES_OPS_RPC_PDS,
        customer_id=customer.id,
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        promotion_code = promo_code.promo_code.upper()
        minimum_transaction = sales_ops_services.get_minimum_transaction_promo_code(promo_code)
        event_data = construct_data_for_rpc_sales_ops_pds(
            application=application,
            event_type=event_type,
            agent_assignment=agent_assignment,
            promotion_code=promotion_code,
            minimum_transaction=minimum_transaction
        )
        logger.info({
            'action': 'send_event_moengage_for_rpc_sales_ops_pds',
            'agent_assignment_id': agent_assignment_id,
            'data_to_send': [event_data]
        })
        send_to_moengage.delay([moengage_upload.id], [event_data])


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_balance_consolidation_verification(
    customer_id, verification_id
):
    balance_consolidation_verification = BalanceConsolidationVerification.objects.get(
        id=verification_id
    )
    verification_history = BalanceConsolidationVerificationHistory.objects.filter(
        balance_consolidation_verification_id=verification_id,
        field_name='validation_status',
    ).last()
    status_new = balance_consolidation_verification.validation_status
    change_reason = getattr(verification_history, 'change_reason', '') or ''
    agent_id = balance_consolidation_verification.locked_by_id
    event_time = balance_consolidation_verification.udate

    event_type = MoengageEventType.BALANCE_CONSOLIDATION
    application = Application.objects.filter(customer_id=customer_id).last()

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_balance_consolidation_verification(
            application, status_new, change_reason, event_time, agent_id, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_balance_consolidation',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_balance_consolidation_submit_ids(customer_id):
    event_time = timezone.localtime(timezone.now())
    event_type = MoengageEventType.BALANCE_CONSOLIDATION_SUBMIT_FORM + \
        event_time.strftime('%Y-%m-%d_%-H%p')

    application = Application.objects.filter(customer_id=customer_id).last()

    data_to_send = []
    moengage_upload = MoengageUpload.objects.create(
        type=event_type, customer_id=application.customer_id
    )
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_balance_consolidation_submit_form_id(
            application.id, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)

        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_balance_consolidation_submit_id',
                'balance_consolidation_submit_form_batch_id': event_type,
                'data_to_send': data_to_send,
            }
        )

    send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_cfs_mission_change(customer_id, agent_assignment_id):
    assignment_verification = CfsAssignmentVerification.objects.get(id=agent_assignment_id)
    event_type = MoengageEventType.CFS_AGENT_CHANGE_MISSION
    application = Application.objects.filter(customer_id=customer_id).last()

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_cfs_mission_verification_change(
            application, assignment_verification, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_cfs_mission_change',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_jstarter_limit_approved(application_id, js_workflow):
    application = Application.objects.filter(id=application_id).last()

    customer_id = application.customer.id
    event_type = MoengageEventType.JULO_STARTER_LIMIT_APPROVED
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_jstarter_limit_approved(
            application, event_type, js_workflow
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_jstarter_limit_approved',
                'customer_id': application.customer.id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_early_limit_release(customer_id, limit_release_amount,
                                                             status):
    event_type = MoengageEventType.EARLY_LIMIT_RELEASE
    application = Application.objects.filter(customer_id=customer_id).last()

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_early_limit_release(
            application, limit_release_amount, event_type, status
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info({
            'action': 'send_user_attributes_to_moengage_for_early_limit_release',
            'customer_id': customer_id,
            'data_to_send': data_to_send
        })
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_typo_calls_unsuccessful(application_id, workflow_name):
    application = Application.objects.filter(id=application_id).last()
    customer_id = application.customer.id
    event_type = MoengageEventType.TYPO_CALLS_UNSUCCESSFUL
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
        application_id=application_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_typo_calls_unsuccessful(
            application, event_type, workflow_name
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_typo_calls_unsuccessful',
                'customer_id': application.customer.id,
                'application_id': application_id,
                'workflow_name': workflow_name,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_high')
def send_user_attributes_to_moengage_for_change_lender(loan_id):
    loan = Loan.objects.get_or_none(id=loan_id)
    if not loan:
        raise JuloException("loan: %s not found" % loan_id)

    # only trigger this event on loan status x220
    if loan.loan_status_id != LoanStatusCodes.CURRENT:
        return

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.BEx220_CHANNELING_LOAN,
        loan_id=loan.id,
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        customer_id = loan.customer.id
        user_attributes, event_data = construct_data_for_change_lender(
            event_type=MoengageEventType.BEx220_CHANNELING_LOAN,
            loan=loan,
            customer_id=customer_id,
        )
        data_to_send = [user_attributes, event_data]

        logger.info(
            {
                'action': 'send_data_to_moengage_for_change_lender_event',
                'customer_id': customer_id,
                'data_to_send': data_to_send
            }
        )

        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='collection_normal')
def send_user_attributes_to_moengage_for_late_fee_earlier_exp(moengage_upload_batch_id):
    from juloserver.minisquad.constants import ExperimentConst
    logger.info({
        'action': 'send_user_attributes_to_moengage_for_late_fee_earlier_exp',
        'state': 'start'
    })
    experiment_setting = ExperimentSetting.objects.filter(
        code=ExperimentConst.LATE_FEE_EARLIER_EXPERIMENT).last()
    if not experiment_setting:
        return

    experiment_data = ExperimentGroup.objects.filter(
        experiment_setting=experiment_setting
    ).select_related('account').prefetch_related('account__customer').only(
        'account', 'group')

    with SendToMoengageManager() as moengage_manager:
        for item in experiment_data.iterator():
            account = item.account
            if not account:
                continue

            customer = account.customer
            moengage_upload = MoengageUpload.objects.create(
                type=MoengageEventType.USERS_ATTRIBUTE_FOR_LATE_FEE_EXPERIMENT,
                customer_id=customer.id,
                moengage_upload_batch_id=moengage_upload_batch_id
            )

            with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer, daily_update=True)
                if experiment_setting.is_active:
                    user_attributes['attributes'].update(
                        dict(late_fee_experiment_group=item.group))
                else:
                    user_attributes['attributes'].update(
                        dict(late_fee_experiment_group="control"))

                moengage_manager.add(moengage_upload.id, [user_attributes])

    logger.info({
        'action': 'send_user_attributes_to_moengage_for_late_fee_earlier_exp',
        'state': 'finish'
    })


@task(queue='collection_normal')
def send_user_attributes_to_moengage_for_cashback_new_scheme_exp(account_ids):
    logger.info(
        {'action': 'send_user_attributes_to_moengage_for_cashback_new_scheme_exp', 'state': 'start'}
    )

    with SendToMoengageManager() as moengage_manager:
        for account_id in account_ids:
            account = Account.objects.get_or_none(pk=account_id)
            if not account:
                continue

            customer = account.customer
            moengage_upload = MoengageUpload.objects.create(
                type=MoengageEventType.USERS_ATTRIBUTE_FOR_CASHBACK_NEW_SCHEME_EXPERIMENT,
                customer_id=customer.id,
            )

            with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                user_attributes = construct_user_attributes_for_realtime_basis(
                    customer, daily_update=True
                )
                experiment_group = get_cashback_experiment(account.id)
                if experiment_group:
                    user_attributes['attributes'].update(
                        dict(cashback_new_scheme_experiment_group="experiment")
                    )
                else:
                    user_attributes['attributes'].update(
                        dict(cashback_new_scheme_experiment_group="control")
                    )

                moengage_manager.add(moengage_upload.id, [user_attributes])

    logger.info(
        {
            'action': 'send_user_attributes_to_moengage_for_cashback_new_scheme_exp',
            'state': 'finish',
        }
    )


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_idfy_verification_success(application_id):
    application = Application.objects.filter(id=application_id).last()
    customer_id = application.customer.id
    event_type = MoengageEventType.IDFY_VERIFICATION_SUCCESS
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
        application_id=application_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_idfy_verification_success(
            application, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_idfy_verification_success',
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_idfy_completed_data(application_id):
    application = Application.objects.filter(id=application_id).last()
    customer_id = application.customer.id
    event_type = MoengageEventType.IDFY_COMPLETED_DATA
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
        application_id=application_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_idfy_completed_data(
            application, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_idfy_completed_data',
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_customer_reminder_vkyc(application_id):

    from juloserver.application_form.services.idfy_service import has_identity_images

    application = Application.objects.filter(id=application_id).last()

    if not application:
        logger.error({
            'message': 'Application not found',
            'process': 'send_user_attributes_to_moengage_for_customer_reminder_vkyc',
            'application': application_id
        })
        return

    if (
            not application.is_julo_one()
            or application.application_status_id != ApplicationStatusCodes.FORM_CREATED
    ):
        logger.error({
            'message': 'Send reminder is rejected only for J1 and x100',
            'process': 'send_user_attributes_to_moengage_for_customer_reminder_vkyc',
            'application': application_id,
            'status': application.application_status_id
        })
        return

    # check already have the identity image or not
    if has_identity_images(application_id):
        logger.info({
            'message': 'Send reminder is rejected because have identity images',
            'process': 'send_user_attributes_to_moengage_for_customer_reminder_vkyc',
            'application': application_id,
        })
        return

    customer_id = application.customer.id
    event_type = MoengageEventType.CUSTOMER_REMINDER_VKYC
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
        application_id=application_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_customer_reminder_vkyc(
            application, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_video_kyc_notification',
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_after_graduation_downgrade(
        account_limit_id, new_set_limit, old_set_limit, is_graduated, graduation_flow=None,
        graduation_date=None):
    account_limit = AccountLimit.objects.get_or_none(id=account_limit_id)
    account = account_limit.account
    customer = account.customer
    _type = MoengageEventType.GRADUATION if is_graduated else MoengageEventType.DOWNGRADE

    moengage_upload = MoengageUpload.objects.create(type=_type, customer_id=customer.id)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_user_attributes_for_graduation_downgrade(
            customer, account, new_set_limit, old_set_limit, _type, graduation_flow,
            graduation_date)
        logger.info({
            'action': 'send_user_attributes_to_moengage_after_graduation/downgrade',
            'customer_id': customer.id,
            'user_attributes': user_attributes,
            'type': _type
        })
        data_to_send = [user_attributes, event_data]
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_submit_bank_statement(
    application_id, submission_url, is_available_bank_statement
):
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
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REALTIME_BASIS, customer_id=application.customer.id
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_for_submit_bank_statement(
            application, submission_url, is_available_bank_statement
        )
        data_to_send.append(user_attributes)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_submit_bank_statement',
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))


@task(queue='moengage_low')
def trigger_moengage_after_freeze_unfreeze_cashback(list_data, is_freeze=True):
    '''
    Parameters:
        list_data: [data0, data1]
            referee_data: {
                customer_id: 123,
                cashback_earned: 140000,
                referral_type: referrer/referee
            }
        is_freeze: True => freeze, False => unfreeze
    '''
    status = 'freeze' if is_freeze else 'unfreeze'
    for data in list_data:
        send_user_attributes_to_moengage_after_freeze_unfreeze_cashback.delay(
            data['customer_id'], data['cashback_earned'], data['referral_type'], status
        )


@task(queue='moengage_low')
def send_user_attributes_to_moengage_after_freeze_unfreeze_cashback(
    customer_id, cashback_earned, referral_type, status
):
    account = Account.objects.select_related('customer').filter(customer_id=customer_id).last()
    customer = account.customer
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.REFERRAL_CASHBACK, customer_id=customer.id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_cashback_freeze_unfreeze(
            customer, account, referral_type, status, cashback_earned
        )
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_after_freeze_unfreeze_cashback',
                'customer_id': customer.id,
                'user_attributes': user_attributes,
            }
        )
        data_to_send = [user_attributes, event_data]
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_high')
def send_user_attributes_to_moengage_for_activate_julo_care(loan_id):
    loan = Loan.objects.get_or_none(id=loan_id)
    if not loan:
        raise JuloException("loan: %s not found" % loan_id)

    # only trigger this event on loan status x220
    if loan.loan_status_id != LoanStatusCodes.CURRENT:
        raise JuloException("loan: %s status not match" % loan_id)

    loan_julo_care = LoanJuloCare.objects.filter(
        loan=loan, status=JuloCareStatusConst.ACTIVE
    ).last()
    if not loan_julo_care:
        raise JuloException("loan: %s not related" % loan_id)

    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.BEx220_ACTIVE_JULO_CARE,
        loan_id=loan.id,
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        customer_id = loan.customer.id
        user_attributes, event_data = construct_data_for_active_julo_care(
            event_type=MoengageEventType.BEx220_ACTIVE_JULO_CARE,
            loan=loan,
            customer_id=customer_id,
        )
        data_to_send = [user_attributes, event_data]

        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_activate_julo_care',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
            }
        )

        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_to_moengage_customer_suspended_unsuspended(customer_id, is_suspended, reason):
    customer = Customer.objects.prefetch_related('account_set').filter(id=customer_id).last()
    account = customer.account_set.last()
    event_type = MoengageEventType.CUSTOMER_SUSPENDED

    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer_id)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_user_attributes_for_customer_suspended_unsuspended(
            customer, account, event_type, is_suspended, reason)
        logger.info({
            'action': 'send_user_attributes_to_moengage_customer_suspended/unsuspended',
            'customer_id': customer_id,
            'user_attributes': user_attributes,
            'type': event_type,
        })
        data_to_send = [user_attributes, event_data]
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_high')
def send_user_attributes_to_moengage_for_active_platforms_rule(customer_id, is_eligible):
    event_type = MoengageEventType.ACTIVE_PLATFORMS
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer_id)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_user_attributes_for_active_platforms_rule(
            event_type, customer_id, is_eligible
        )
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_active_platforms_rule',
                'customer_id': customer_id,
                'user_attributes': user_attributes,
                'type': event_type,
            }
        )
        data_to_send = [user_attributes, event_data]
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_update_user_attributes_to_moengage(event_name, limit=None, filter_dict={}):
    logger.info({'action': 'send_update_user_attributes_to_moengage', 'state': 'start'})

    all_customer_segmentation = CustomerSegmentationComms.objects.values()
    if filter_dict:
        all_customer_segmentation = all_customer_segmentation.filter(**filter_dict)
    if limit:
        all_customer_segmentation = all_customer_segmentation[:limit]

    for customer_segmentation in all_customer_segmentation:
        customer_id = customer_segmentation.get('customer_id', None)
        if not customer_id:
            continue

        customer_segmentation.pop('id')
        customer_segmentation.pop('cdate')
        customer_segmentation.pop('udate')

        moengage_upload = MoengageUpload.objects.create(
            type=event_name,
            customer_id=customer_id,
        )
        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            send_to_moengage.delay(
                [moengage_upload.id],
                [
                    {
                        "type": "customer",
                        "customer_id": customer_id,
                        "attributes": customer_segmentation,
                    }
                ]
            )

    logger.info({
        'action': 'send_update_user_attributes_to_moengage',
        'state': 'finish',
        'total_data': len(all_customer_segmentation),
    })


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_consent_received(application_id, consent_value):

    process_name = 'send_user_attributes_to_moengage_for_consent_received'
    logger.info({
        'message': 'Execute Moengage consent received',
        'process': process_name,
        'application_id': application_id,
        'consent_value': consent_value,
    })

    application = Application.objects.filter(id=application_id).last()
    if not application:
        logger.error({
            'message': 'Application not found',
            'process': process_name,
            'application': application_id
        })
        return

    customer_id = application.customer.id
    event_type = MoengageEventType.EMERGENCY_CONSENT_RECEIVED
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
        application_id=application_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_emergency_consent_received(
            application, event_type, consent_value=consent_value,
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'process': process_name,
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue="moengage_low")
def send_user_attributes_to_moengage_for_goldfish(application_id: int, value: bool):
    application = Application.objects.select_related(
        "customer", "device", "product_line", "workflow"
    ).get(pk=application_id)
    moengage_upload = MoengageUpload.objects.create(
        application_id=application.id,
        customer_id=application.customer.id,
    )
    data = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_user_attributes_for_goldfish(application, value)
        data.append(user_attributes)
        logger.info(
            {
                'action': 'send_user_attributes_to_moengage_for_goldfish',
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data,
            }
        )
        send_to_moengage.apply_async(([moengage_upload.id], data))


@task(queue='moengage_low')
def send_gtl_event_to_moengage(customer_id, event_type, event_attributes):
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer_id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes = construct_data_moengage_user_attributes(customer_id)
        event_data = construct_event_data_for_gtl(event_type, customer_id, event_attributes)
        logger.info(
            {
                'action': 'send_gtl_event_to_moengage',
                'customer_id': customer_id,
                'user_attributes': user_attributes,
                'type': event_type,
            }
        )
        data_to_send = [user_attributes, event_data]
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
@transaction.atomic
def send_gtl_event_to_moengage_bulk(customer_ids, event_type, event_attributes):
    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=event_type,
        data_count=len(customer_ids),
    )

    for chunked_customer_ids in chunks(customer_ids, MAX_EVENT):
        moengage_upload_ids = []
        data_to_send = []

        for customer_id in chunked_customer_ids:
            moengage_upload = MoengageUpload.objects.create(
                type=event_type,
                customer_id=customer_id,
                moengage_upload_batch=moengage_upload_batch,
            )

            with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                moengage_upload_ids.append(moengage_upload.id)

                user_attributes = construct_data_moengage_user_attributes(customer_id)
                data_to_send.append(user_attributes)
                event_data = construct_event_data_for_gtl(event_type, customer_id, event_attributes)
                data_to_send.append(event_data)

        logger.info(
            {
                'action': 'send_gtl_event_to_moengage_bulk',
                'customer_ids': chunked_customer_ids,
                'type': event_type,
            }
        )
        execute_after_transaction_safely(
            lambda moengage_upload_ids=moengage_upload_ids, data_to_send=data_to_send: send_to_moengage.delay(  # noqa
                moengage_upload_ids=moengage_upload_ids,
                data_to_send=data_to_send,
            )
        )

    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_high')
def send_transaction_status_event_to_moengage(
    customer_id: int, loan_xid: int, loan_status_code: int
):
    event_type = MoengageEventType.LOAN_TRANSACTION_STATUS

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    event_attributes = {
        'loan_xid': loan_xid,
        'loan_status_code': loan_status_code,
    }
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=True):
        user_attributes = construct_data_moengage_user_attributes(customer_id)
        event_data = construct_moengage_event_data(
            event_type=event_type,
            customer_id=customer_id,
            event_attributes=event_attributes,
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_transaction_status_event_to_moengage',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_loyalty_mission_progress_data_event_to_moengage(
    customer_id, mission_progress_data
):
    event_type = MoengageEventType.LOYALTY_MISSION
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    customer = Customer.objects.get(id=customer_id)

    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        for data in mission_progress_data:
            event_data = construct_event_data_loyalty_mission_to_moengage(
                customer, data
            )
            data_to_send.append(event_data)

        logger.info({
            'action': 'send_loyalty_mission_progress_data_event_to_moengage',
            'customer_id': customer_id,
            'data_to_send': data_to_send,
            'type': event_type,
        })

        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_user_attributes_loyalty_total_point_to_moengage(sub_customer_ids):
    event_type = MoengageEventType.LOYALTY_TOTAL_POINT
    loyalty_points = LoyaltyPoint.objects.filter(customer_id__in=sub_customer_ids)
    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=event_type,
        data_count=len(sub_customer_ids),
    )
    moengage_upload_ids = []
    data_to_send = []

    for loyalty_point in loyalty_points:
        customer_id = loyalty_point.customer_id
        total_point = loyalty_point.total_point
        moengage_upload = MoengageUpload.objects.create(
            type=event_type,
            customer_id=customer_id,
        )
        with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
            user_attributes = construct_user_attributes_loyalty_total_point_to_moengage(
                customer_id, total_point
            )
            data_to_send.append(user_attributes)
            moengage_upload_ids.append(moengage_upload.id)

            logger.info({
                'action': 'send_user_attributes_loyalty_total_point_to_moengage',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
                'type': event_type,
            })

    send_to_moengage.delay(
        moengage_upload_ids=moengage_upload_ids,
        data_to_send=data_to_send,
    )
    with transaction.atomic():
        moengage_upload_batch = MoengageUploadBatch.objects.\
            select_for_update().get(id=moengage_upload_batch.id)
        moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_low')
def send_julo_financing_event_to_moengage_bulk(customer_ids: List[int]):
    """
    Send to moengage event for julo financing
    """
    event_type = MoengageEventType.JULO_FINANCING

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=event_type,
        data_count=len(customer_ids),
    )

    for chunked_customer_ids in chunks(customer_ids, MAX_EVENT):
        moengage_upload_ids = []
        data_to_send = []

        for customer_id in chunked_customer_ids:
            moengage_upload = MoengageUpload.objects.create(
                type=event_type,
                customer_id=customer_id,
                moengage_upload_batch_id=moengage_upload_batch.id,
            )

            with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
                user_attributes, event_data = construct_julo_financing_event_data(
                    customer_id=customer_id,
                    event_type=event_type,
                )
                data_to_send.append(user_attributes)
                data_to_send.append(event_data)
                moengage_upload_ids.append(moengage_upload.id)

        logger.info(
            {
                'action': 'send_julo_financing_event_to_moengage_bulk',
                'customer_ids': chunked_customer_ids,
                'type': event_type,
            }
        )

        send_to_moengage.delay(
            moengage_upload_ids=moengage_upload_ids,
            data_to_send=data_to_send,
        )

    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_low')
def send_user_attributes_to_moengage_for_customer_agent_assisted(application_id):
    from juloserver.application_flow.services import is_agent_assisted_submission_flow

    function_name = 'send_user_attributes_to_moengage_for_customer_agent_assisted'

    application = Application.objects.filter(id=application_id).last()
    if not application:
        logger.error(
            {
                'message': 'Application not found',
                'process': function_name,
                'application': application_id,
            }
        )
        return

    if (
        not application.is_julo_one()
        or application.application_status_id != ApplicationStatusCodes.FORM_PARTIAL
    ):
        logger.error(
            {
                'message': 'Send reminder is rejected only for J1 and x105',
                'process': function_name,
                'application': application_id,
                'status': application.application_status_id,
            }
        )
        return

    if not is_agent_assisted_submission_flow(application):
        logger.info(
            {
                'message': 'Send reminder is rejected not in criteria',
                'process': function_name,
                'application': application_id,
            }
        )
        return

    customer_id = application.customer.id
    event_type = MoengageEventType.IS_AGENT_ASSISTED_SUBMISSION
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
        application_id=application_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_for_customer_agent_assisted(
            application, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': function_name,
                'customer_id': application.customer.id,
                'application_id': application_id,
                'data_to_send': data_to_send,
                'user_attribute': user_attributes,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_event_jfinancing_verification_status_change(customer_id: int, verification_id: int):
    verification = JFinancingVerification.objects.get(id=verification_id)

    if verification.validation_status == JFinancingStatus.ON_REVIEW:
        event_type = MoengageEventType.JFINANCING_TRANSACTION
    elif verification.validation_status == JFinancingStatus.ON_DELIVERY:
        event_type = MoengageEventType.JFINANCING_DELIVERY
    elif verification.validation_status == JFinancingStatus.COMPLETED:
        event_type = MoengageEventType.JFINANCING_COMPLETED
    else:
        logger.error(
            {
                'action': 'send_event_jfinancing_verification_status_change',
                'customer_id': customer_id,
                'verification_id': verification.pk,
                'validation_status': verification.validation_status,
                'message': "event_type not found",
            }
        )
        raise MoengageTypeNotFound

    customer = Customer.objects.get(pk=customer_id)
    application = customer.account.get_active_application()
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )
    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_data_julo_financing_verification(
            application, verification, event_type
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'construct_data_julo_financing_verification',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_low')
def send_event_moengage_for_balcon_punishment(
    customer_id, limit_deducted, fintech_id, fintech_name
):
    event_type = MoengageEventType.IS_BALANCE_CONSOLIDATION_PUNISHMENT
    customer = Customer.objects.get(pk=customer_id)
    application = customer.account.get_active_application()
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        event_data = construct_data_for_balcon_punishment(
            application=application,
            event_type=event_type,
            limit_deducted=limit_deducted,
            fintech_id=fintech_id,
            fintech_name=fintech_name
        )
        logger.info({
            'action': 'send_event_moengage_for_balcon_punishment',
            'customer_id': customer_id,
            'data_to_send': [event_data]
        })
        send_to_moengage.delay([moengage_upload.id], [event_data])


@task(queue='moengage_high')
def send_moengage_for_cashback_delay_disbursement(loan_id:int):
    logger.info(
        {
            'action': 'send_moengage_for_cashback_delay_disbursement',
            'message': 'starting upload moengage for cashback delay disbursement',
            'loan_id': str(loan_id),
            'MoengageEventType': MoengageEventType.BEx220_CASHBACK_DELAY_DISBURSEMENT,
        }
    )
    moengage_upload = MoengageUpload.objects.create(
        type=MoengageEventType.BEx220_CASHBACK_DELAY_DISBURSEMENT,
        loan_id=loan_id,
    )
    loan = Loan.objects.get_or_none(id=loan_id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        customer_id = loan.customer.id
        user_attributes, event_data = construct_data_for_cashback_delay_disbursement(
            event_type=MoengageEventType.BEx220_CASHBACK_DELAY_DISBURSEMENT,
            loan=loan,
            customer_id=customer_id,
        )
        data_to_send = [user_attributes, event_data]

        logger.info(
            {
                'action': 'send_moengage_for_cashback_delay_disbursement',
                'message': 'construct data for cashback delay disbursement',
                'loan_id': str(loan.id),
                'customer_id': str(customer_id),
                'MoengageEventType': MoengageEventType.BEx220_CASHBACK_DELAY_DISBURSEMENT,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_high')
def send_qris_linkage_status_change_to_moengage(linkage_id: int):
    linkage = QrisPartnerLinkage.objects.get(pk=linkage_id)

    customer_id = linkage.customer_id
    partner_id = linkage.partner_id

    event_type = MoengageEventType.QRIS_LINKAGE_STATUS

    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer_id,
    )

    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        user_attributes, event_data = construct_qris_linkage_status_change_event_data(
            customer_id=customer_id,
            partner_id=partner_id,
            event_type=event_type,
        )
        data_to_send.append(user_attributes)
        data_to_send.append(event_data)
        logger.info(
            {
                'action': 'send_qris_linkage_status_change_to_moengage',
                'customer_id': customer_id,
                'data_to_send': data_to_send,
            }
        )
        send_to_moengage.delay([moengage_upload.id], data_to_send)


@task(queue='send_event_for_skrtp_regeneration_queue')
def send_event_attributes_for_skrtp_regeneration(loan_id):
    loan = Loan.objects.get(pk=loan_id)
    customer = loan.customer
    event_type = MoengageEventType.SKRTP_REGENERATION
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer.pk,
    )

    data_to_send = []
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        application = customer.account.get_active_application()
        event_time = timezone.localtime(timezone.now())
        device_id = None
        if application and application.device:
            device_id = application.device.gcm_reg_id

        event_attributes = {
            'customer_id': customer.id,
            'loan_id': loan_id,
        }

        event_data = construct_data_moengage_event_data(
            customer.id, device_id, event_type, event_attributes, event_time
        )
        data_to_send.append(event_data)

        logger.info({
            'action': 'send_event_attributes_for_skrtp_regeneration',
            'customer_id': customer.pk,
            'data_to_send': data_to_send,
            'type': event_type,
        })

        send_to_moengage_for_skrtp_regeneration.delay([moengage_upload.id], data_to_send)


@task(queue='moengage_high')
def send_customer_risk_segment_bulk(customers, moengage_upload_batch_id):
    moengage_uploads = [
        MoengageUpload(
            type=MoengageEventType.REALTIME_BASIS,
            customer_id=entry["customer_id"],
            moengage_upload_batch_id=moengage_upload_batch_id,
        )
        for entry in customers
    ]

    moengage_uploads = MoengageUpload.objects.bulk_create(moengage_uploads)

    data_to_send = []
    moengage_upload_ids = []

    for upload, entry in zip(moengage_uploads, customers):
        moengage_upload_ids.append(upload.id)
        data_to_send.append(
            construct_data_moengage_user_attributes(
                entry["customer_id"], risk_segment=entry["risk_segment"]
            )
        )

    logger.info(
        {
            'action': 'send_customer_risk_segment_bulk',
            'data_to_send': data_to_send,
        }
    )

    send_to_moengage.delay(moengage_upload_ids, data_to_send)

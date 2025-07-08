import uuid
from builtins import str

from django.db.models.signals import pre_save

from juloserver.cashback.constants import CashbackChangeReason
from juloserver.cfs.services.core_services import (
    get_activity_based_on_payment_history,
)
from juloserver.cfs.constants import CfsActionPointsActivity
import logging
import semver
import datetime
import inspect
import functools
import six

from datetime import timedelta
from django.db.models import signals
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.db import transaction

from juloserver.loan.constants import LoanStatusChangeReason, LoanFeatureNameConst

from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    Workflow,
    Offer,
    LoanPurpose,
    ApplicationFieldChange,
    PTP,
    Agent,
    FeatureSetting,
    Customer,
    PaymentMethod,
    PTP,
    SkiptraceHistory,
    LoanHistory,
    PaymentHistory,
    CustomerWalletHistory,
    DjangoAdminLogChanges,
    MobileFeatureSetting,
    PaybackTransaction,
)
from juloserver.partnership.constants import PartnershipAccountLookup

from .services import (
    update_flag_is_broken_ptp_plus_1,
    remove_character_by_regex,
    handle_notify_moengage_after_payment_method_change,
)
from juloserver.julo.clients import (
    get_julo_pn_client,
    get_julo_sentry_client,
)
from ..crm.constants import AGENT_USER_GROUP
from juloserver.julo.tasks2.agent_tasks import send_email_agent_password_regenerated
from juloserver.julo.utils import generate_agent_password
from juloserver.julo.models import (PaymentEvent, Payment, Loan)
from juloserver.moengage.tasks import async_moengage_events_for_j1_loan_status_change
from juloserver.moengage.services.use_cases \
    import update_moengage_for_application_status_change_event
from juloserver.julo.constants import (FeatureNameConst,
                                       WorkflowConst,
                                       ApplicationStatusCodes)
from juloserver.moengage.models import MoengageUpload
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.models import AccountingCutOffDate, CustomerFieldChange
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_realtime_basis
)
from django.conf import settings

from juloserver.merchant_financing.tasks import (task_va_payment_notification_to_partner,
                                                 task_disbursement_status_change_notification_to_partner)
from juloserver.julo.partners import (PartnerConstant,)
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_self_referral_code_change,
    send_user_attributes_to_moengage_for_va_change,
)
from juloserver.julo.tasks import (send_realtime_ptp_notification,update_skiptrace_number)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.cfs.tasks import update_graduate_entry_level, \
    tracking_transaction_case_for_action_points, tracking_repayment_case_for_action_points
from juloserver.customer_module.tasks.customer_related_tasks import sync_customer_data_with_application
from juloserver.geohash.services import save_address_geolocation_geohash
from juloserver.loan.services.loan_one_click_repeat import invalidate_one_click_repeat_cache
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.workflows2.tasks import appsflyer_update_status_task
from juloserver.cashback.services import (
    generate_cashback_overpaid_case,
    get_referral_cashback_action,
)
from juloserver.cashback.tasks import unfreeze_referrer_and_referree_cashback_task
from juloserver.cashback.constants import ReferralCashbackEventType, ReferralCashbackAction

from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.utils import format_mobile_phone
from juloserver.pii_vault.collection.tasks import mask_phone_numbers
from juloserver.payback.tasks import send_email_payment_success_task

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def suspendingreceiver(signal, **decorator_kwargs):
    def our_wrapper(func):
        @receiver(signal, **decorator_kwargs)
        @functools.wraps(func)
        def fake_receiver(sender, **kwargs):
            if getattr(settings, 'SUSPEND_SIGNALS_FOR_MOENGAGE', False):
                return
            return func(sender, **kwargs)
        return fake_receiver
    return our_wrapper


@receiver(signals.pre_save, sender=Application)
def update_status_on_creation(sender, instance=None, **kwargs):
    """A signal is caught before an application has been submitted."""

    application = instance

    # This check indicates whether the application is being created for the
    # first time or already exists and being updated. True means created.
    if application._state.adding:
        if application.app_version:
            is_new_app_version = semver.match(application.app_version, ">=2.0.0")
            if is_new_app_version:
                status = ApplicationStatusCodes.NOT_YET_CREATED
            if application.is_julo_one_ios():
                status = ApplicationStatusCodes.NOT_YET_CREATED
        elif application.web_version:
            status = ApplicationStatusCodes.NOT_YET_CREATED
        elif application.partner:
            status = ApplicationStatusCodes.NOT_YET_CREATED
        else:
            status = ApplicationStatusCodes.FORM_SUBMITTED
        application.application_status_id = status
        logger.info("Set application for ktp=%s to status=%s" % (
            application.ktp, status))


@receiver(signals.pre_save, sender=Application)
def send_gcm_after_appstatus_changed(
        sender, instance=None, **kwargs):
    """
    send notification when documents have been uploaded
    or sphp has been signed.
    """
    application_to_save = instance
    if application_to_save.is_julo_one() or application_to_save.is_grab():
        return
    if application_to_save.is_document_submitted:
        # Get the data already saved in DB
        application_saved = Application.objects.get_or_none(id=application_to_save.id)
        if not application_saved.is_document_submitted:
            # When is_document_submitted is being set to true
            # Send notification
            julo_pn_client = get_julo_pn_client()
            julo_pn_client.inform_docs_submitted(
                application_saved.device.gcm_reg_id,
                application_saved.id)
    if application_to_save.is_sphp_signed:
        # Get the data already saved in DB
        application_saved = Application.objects.get_or_none(id=application_to_save.id)
        if not application_saved.is_sphp_signed:
            # When is_sphp_signed is being set to true
            # Send notification
            julo_pn_client = get_julo_pn_client()
            julo_pn_client.inform_sphp_signed(
                application_saved.device.gcm_reg_id,
                application_saved.id)


@receiver(signals.pre_save, sender=Application)
def before_save_application(sender, instance=None, **kwargs):
    application = instance
    if application.job_industry == "Staf rumah tangga":
        application.job_industry = application.job_industry.title()

    if application.loan_purpose_desc is not None:
        application.loan_purpose_desc = remove_character_by_regex(
            application.loan_purpose_desc, '[^\x20-\x7E]'
        )

    # Due problem in loan withdrawal in short form we must patch the
    # company into empty string instead of leave it to None.
    if application.company_name is None:
        application.company_name = ''


# Dragon Ball Project
@receiver(signals.post_save, sender=Application)
def run_application_customer_sync_task(sender, instance=None, created=False, **kwargs):
    """
    A signal is caught after there is a CRUD operation happening on table `ops.application`.
    This is part of Dragon Ball project
    """

    logger.info(
        {
            "message": "Signal is triggerred for table `ops.application`",
            "action": "sync_customer_data_with_application",
        }
    )

    application = instance
    if application != None and application.customer != None:
        # Only run the below method after we are sure that:
        # 1. If the created/modified application has an association with customer (meaning that the customer id is not null)
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.TECH_DRAGON_BALL,
            is_active=True,
        ).last()

        if (feature_setting):
            execute_after_transaction_safely(
                            lambda: sync_customer_data_with_application.delay(application.customer.id))


# @receiver(signals.post_save, sender=Application)
# def application_handler(sender, instance=None, created=False, **kwargs):
#     """
#     A signal is caught after an application has been submitted
#     to update data phone and name on customer table.
#     """
#
#     application = instance
#     if created:
#         update_customer_data(application)
#         workflow = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
#         if not workflow:
#             return
#         application.workflow = workflow
#         application.save()
#         application.customer.can_reapply = False
#         application.customer.save()


@receiver(signals.pre_save, sender=Offer)
def update_timestamp_on_accepting_offer(sender, instance=None, **kwargs):
    """
    A signal catching when offer is to be accepted. Update timestamp.
    Note: this does a DB lookup.
    """

    offer_to_save = instance

    if not offer_to_save.is_accepted:
        return
    offer_saved = Offer.objects.get_or_none(id=offer_to_save.id)
    if not offer_saved:
        return

    if not offer_saved.is_accepted:
        now = timezone.localtime(timezone.now())
        logger.info({
            'status': 'offer_not_yet_accepted',
            'action': 'accepting_offer',
            'timestamp': now
        })
        offer_to_save.offer_accepted_ts = now


@receiver(signals.pre_save, sender=LoanPurpose)
def update_version_sequence_on_creation(sender, instance=None, **kwargs):
    """A signal is caught before loan purpose has been submitted for fill up version."""

    last_purpose = LoanPurpose.objects.last()
    current_version = last_purpose.version if last_purpose else '1.0.0'
    int_value = int(current_version.replace('.', ''))
    int_value += 1
    str_value = str(int_value)
    instance.version = '%s.%s.%s' % (str_value[0:len(str_value) - 2], str_value[-2], str_value[-1])


@receiver(signals.m2m_changed, sender=User.groups.through)
def groups_changed(sender, **kwargs):
    """this signal for handle freelance agent"""
    if kwargs['action'] == 'post_add':
        user = kwargs['instance']
        if user.is_active:
            groups_added = Group.objects.filter(
                id__in=kwargs['pk_set']).values_list('name', flat=True)
            # If any of the added groups is an agent user group (the 2 lists intersect)
            if len(list(set(groups_added) & set(AGENT_USER_GROUP))) > 0:
                if Agent.objects.filter(user=user).first() is None:
                    Agent.objects.create(user=user, user_extension=user.username)
            if 'freelance' in groups_added:
                password = generate_agent_password()
                user.set_password(password)
                user.save()
                send_email_agent_password_regenerated(user.username, password, user.email)


@receiver(signals.post_init, sender=PaymentEvent)
def include_stored_accounting_date(sender, instance=None, **kwargs):
    instance.__stored_accounting_date = instance.accounting_date


@receiver(signals.pre_save, sender=PaymentEvent)
def add_accounting_date_on_creation(sender, instance=None, **kwargs):
    payment_event = instance

    # This check indicates whether the application is being created for the
    # first time or already exists and being updated. True means created.
    if not payment_event._state.adding:

        # Forbidding accounting date from being updated without update_fields
        if payment_event.__stored_accounting_date != payment_event.accounting_date:
            payment_event.accounting_date = payment_event.__stored_accounting_date
        return
    accounting_cutoff_date = AccountingCutOffDate.objects.all().last()
    if not accounting_cutoff_date:
        return
    cutoff_date = accounting_cutoff_date.cut_off_date.day
    today = timezone.localtime(timezone.now()).date()
    if isinstance(payment_event.event_date, six.string_types):
        event_date = datetime.datetime.strptime(payment_event.event_date, "%Y-%m-%d").date()
    elif isinstance(payment_event.event_date, datetime.datetime):
        event_date = payment_event.event_date.date()
    else:
        event_date = payment_event.event_date

    first_day_of_this_month = today.replace(day=1)
    if first_day_of_this_month > event_date:
        if today.day > cutoff_date:
            payment_event.accounting_date = today
        else:
            last_day_of_previous_month = first_day_of_this_month - datetime.timedelta(days=1)
            payment_event.accounting_date = last_day_of_previous_month
    else:
        payment_event.accounting_date = today
    payment_event.__stored_accounting_date = payment_event.accounting_date


@receiver(signals.post_init, sender=Payment)
def get_data_before_payment_updation(sender, instance=None, **kwargs):
    instance.__stored_payment_status_id = instance.payment_status_id
    instance.__stored_due_amount = instance.due_amount
    instance.__stored_cashback_earned = instance.cashback_earned


@suspendingreceiver(signals.post_save, sender=Payment)
def get_data_after_payment_updation(sender, instance=None, created=False, **kwargs):
    payment = instance
    customer = payment.loan.customer
    if not payment._state.adding:
        if payment.__stored_payment_status_id != payment.payment_status_id:
            if customer:
                send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                    customer.id, 'payment_status',),
                    countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                logger.info({
                    'action': 'get_data_after_account_payment_updation',
                    'payment_id': payment.id,
                    'old_payment_status': payment.__stored_payment_status_id,
                    'new_payment_status': payment.payment_status_id
                })

        elif payment.__stored_due_amount != payment.due_amount:
            if customer:
                send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                    customer.id, 'payment_due_amount',),
                    countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                logger.info({
                    'action': 'get_data_after_account_payment_updation',
                    'payment_id': payment.id,
                    'old_due_amount': payment.__stored_due_amount,
                    'new_due_amount': payment.due_amount
                })

        elif payment.__stored_cashback_earned != payment.cashback_earned:
            if customer:
                send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                    customer.id, 'cashback_amount',),
                    countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                logger.info({
                    'action': 'get_data_after_account_payment_updation',
                    'payment_id': payment.id,
                    'old_cashback_earned': payment.__stored_cashback_earned,
                    'new_cashback_earned': payment.cashback_earned
                })


@receiver(signals.post_init, sender=Loan)
def get_data_before_loan_updation(sender, instance=None, **kwargs):
    instance.__stored_loan_status_id = instance.loan_status_id


@suspendingreceiver(signals.post_save, sender=Loan)
def get_data_after_loan_updation(sender, instance=None, created=False, **kwargs):
    loan = instance
    if not loan._state.adding:
        if loan.__stored_loan_status_id != loan.loan_status_id:
            if loan.loan_status_id == LoanStatusCodes.PAID_OFF:
                customer = loan.customer
                customer.ever_entered_250 = True
                customer.save()
        if loan.account and loan.account.account_lookup.name != PartnershipAccountLookup.DANA:
            application = Application.objects.filter(account=loan.account).last()
            if application:
                if application.is_axiata_flow():
                    if loan.__stored_loan_status_id != loan.loan_status_id:
                        if loan.loan_status_id == LoanStatusCodes.CURRENT:
                            # callback axiata for disbursement status
                            if application.partner.name == PartnerConstant.AXIATA_PARTNER:
                                task_disbursement_status_change_notification_to_partner.delay(
                                    loan.id)
                elif application.is_julo_one_or_starter() or application.is_grab():
                    if (created == True and loan.loan_status_id == LoanStatusCodes.INACTIVE) or \
                            loan.__stored_loan_status_id != loan.loan_status_id:
                        # J1 event handling for moengage
                        execute_after_transaction_safely(
                            lambda: async_moengage_events_for_j1_loan_status_change.apply_async(
                                (loan.id, loan.loan_status_id,), countdown=settings.DELAY_FOR_REALTIME_EVENTS))


@receiver(signals.pre_save, sender=Customer)
def update_moengage_for_can_reapply_changes_in_106(sender, instance=None, **kwargs):
    application_status = [ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                          ApplicationStatusCodes.APPLICATION_DENIED]
    application = instance.application_set.order_by('cdate').filter(
        workflow__name=WorkflowConst.JULO_ONE,
        application_status_id__in=application_status).last()
    old_instance = Customer.objects.get_or_none(id=instance.id)

    if not old_instance or not application:
        return

    if inspect.stack()[5][3] == 'process_customer_may_reapply_action' and \
       application.application_status_id is ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
        return

    if old_instance.can_reapply != instance.can_reapply:
        update_moengage_for_application_status_change_event.delay(status=application.status,
                                                                  application_id=application.id)


@receiver(signals.post_init, sender=Customer)
def get_data_before_customer_updation(sender, instance=None, **kwargs):
    instance.__stored_fullname = instance.fullname
    instance.__stored_gender = instance.gender
    instance.__stored_email = instance.email
    instance.__stored_can_reapply = instance.can_reapply
    instance.__stored_ever_entered_250 = instance.ever_entered_250
    instance.__stored_self_referral_code = instance.self_referral_code


@suspendingreceiver(signals.post_save, sender=Customer)
def get_data_after_customer_updation(sender, instance=None, created=False, **kwargs):
    customer = instance
    try:
        with transaction.atomic():
            if created:
                execute_after_transaction_safely(
                    lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                        customer.id, 'can_reapply',),
                        countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                )
                logger.info({
                    'action': 'get_data_after_customer_updation',
                    'customer_id': customer.id,
                    'created': created,
                    'can_reapply': customer.can_reapply})
            else:
                if customer.__stored_fullname != customer.fullname:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            customer.id, 'first_name',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    )
                    logger.info({
                        'action': 'get_data_after_customer_updation',
                        'customer_id': customer.id,
                        'old_fullname': customer.__stored_fullname,
                        'new_fullname': customer.fullname
                    })

                elif customer.__stored_gender != customer.gender:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            customer.id, 'gender',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    )
                    logger.info({
                        'action': 'get_data_after_customer_updation',
                        'customer_id': customer.id,
                        'old_gender': customer.__stored_gender,
                        'new_gender': customer.gender
                    })
                elif customer.__stored_email != customer.email:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            customer.id, 'email',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    )
                    logger.info({
                        'action': 'get_data_after_customer_updation',
                        'customer_id': customer.id,
                        'old_email': customer.__stored_email,
                        'new_email': customer.email
                    })

                elif customer.__stored_can_reapply != customer.can_reapply:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            customer.id, 'can_reapply',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    )
                    logger.info({
                        'action': 'get_data_after_customer_updation',
                        'customer_id': customer.id,
                        'old_can_reapply': customer.__stored_can_reapply,
                        'new_can_reapply': customer.can_reapply
                    })
                elif customer.__stored_ever_entered_250 != customer.ever_entered_250:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            customer.id, 'ever_entered_250',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    )
                    logger.info({
                        'action': 'get_data_after_customer_updation',
                        'customer_id': customer.id,
                        'old_ever_entered_250': customer.__stored_ever_entered_250,
                        'new_ever_entered_250': customer.ever_entered_250
                    })
                if customer.__stored_self_referral_code != customer.self_referral_code:
                    execute_after_transaction_safely(
                        lambda: (
                            send_user_attributes_to_moengage_for_self_referral_code_change.delay(
                                customer.id
                            )
                        )
                    )

    except Exception as e:
        logger.info({
            'action': 'get_data_after_customer_updation',
            'customer_id': customer.id,
            'error_message': e
        })


@suspendingreceiver(signals.post_save, sender=PaymentMethod)
def notify_moengage_after_payment_method_change(sender, instance=None, created=False, **kwargs):
    payment_method = instance
    handle_notify_moengage_after_payment_method_change(payment_method)


@receiver(signals.post_init, sender=Application)
def get_data_before_application_updation(sender, instance=None, **kwargs):
    instance.__stored_bank_name = instance.bank_name
    instance.__stored_bank_account_number = instance.bank_account_number
    instance.__stored_product_line_id = instance.product_line_id
    instance.__stored_is_fdc_risky = instance.is_fdc_risky
    instance.__stored_monthly_income = instance.monthly_income
    instance.__stored_loan_purpose = instance.loan_purpose
    instance.__stored_job_type = instance.job_type
    instance.__stored_job_industry = instance.job_industry
    instance.__stored_mobile_phone_1 = instance.mobile_phone_1
    instance.__stored_dob = instance.dob
    instance.__stored_address_kabupaten = instance.address_kabupaten
    instance.__stored_address_provinsi = instance.address_provinsi
    instance.__stored_partner_id = instance.partner_id
    instance.__stored_application_status_id = instance.application_status_id
    instance.__stored_app_version = instance.app_version
    instance.__stored_referral_code = instance.referral_code


@suspendingreceiver(signals.post_save, sender=Application)
def get_data_after_application_updation(sender, instance=None, created=False, **kwargs):
    application = instance
    try:
        with transaction.atomic():
            if not created:
                if application.__stored_bank_name != application.bank_name:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'bank_name',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_bank_name': application.__stored_bank_name,
                        'new_bank_name': application.bank_name
                    })

                elif application.__stored_bank_account_number != application.bank_account_number:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'bank_account_number',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_bank_account_number': application.__stored_bank_account_number,
                        'new_bank_account_number': application.bank_account_number
                    })
                elif application.__stored_product_line_id != application.product_line_id:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'product_type',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_product_line': application.__stored_product_line_id,
                        'new_product_line': application.product_line_id
                    })
                elif application.__stored_is_fdc_risky != application.is_fdc_risky:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'is_fdc_risky',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_is_fdc_risky': application.__stored_is_fdc_risky,
                        'new_is_fdc_risky': application.is_fdc_risky
                    })
                elif application.__stored_monthly_income != application.monthly_income:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'monthly_income',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_monthly_income': application.__stored_monthly_income,
                        'new_monthly_income': application.monthly_income
                    })
                elif application.__stored_loan_purpose != application.loan_purpose:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'loan_purpose',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_loan_purpose': application.__stored_loan_purpose,
                        'new_loan_purpose': application.loan_purpose
                    })
                elif application.__stored_job_type != application.job_type:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'job_type',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_job_type': application.__stored_job_type,
                        'new_job_type': application.job_type
                    })
                elif application.__stored_job_industry != application.job_industry:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'job_industry',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_job_type': application.__stored_job_type,
                        'new_job_type': application.job_type
                    })
                elif application.__stored_mobile_phone_1 != application.mobile_phone_1:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'mobile_phone_1',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_mobile_phone_1': application.__stored_mobile_phone_1,
                        'new_mobile_phone_1': application.mobile_phone_1
                    })
                elif application.__stored_dob != application.dob:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'dob',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_dob': application.__stored_dob,
                        'new_dob': application.dob
                    })
                elif application.__stored_address_kabupaten != application.address_kabupaten:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'city',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_city': application.__stored_address_kabupaten,
                        'new_city': application.address_kabupaten
                    })
                elif application.__stored_address_provinsi != application.address_provinsi:
                    if application.customer.application_set.last() == application:
                        execute_after_transaction_safely(
                            lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                                application.customer.id, 'address_provinsi',),
                                countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                        logger.info({
                            'action': 'get_data_after_application_updation',
                            'application_id': application.id,
                            'old_address_provinsi': application.__stored_address_provinsi,
                            'new_address_provinsi': application.address_provinsi
                        })
                elif application.__stored_partner_id != application.partner_id:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                            application.customer.id, 'partner_name',),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS))
                    logger.info({
                        'action': 'get_data_after_application_updation',
                        'application_id': application.id,
                        'old_partner_id': application.__stored_partner_id,
                        'new_partner_id': application.partner_id
                    })

    except Exception as e:
        logger.info({
            'action': 'get_data_after_application_updation',
            'application_id': application.id,
            'error_message': e

        })


@receiver(pre_save, sender=Application)
def update_app_version_to_moengage(sender, instance, **kwargs):
    """
    Executes a user attribute update to MoEngage if app_version changes are detected in
    Application.
    """
    try:
        if instance.__stored_app_version != instance.app_version:
            execute_after_transaction_safely(
                lambda: send_user_attributes_to_moengage_for_realtime_basis.delay(
                    instance.customer.id,
                    update_field='app_version'
                )
            )

            logger.info({
                'action': 'update_app_version_to_moengage',
                'type': 'pre_save signal',
                'model': 'Application',
                'message': 'Updating app_version attribute to MoEngage.'
            })
    except Exception as e:
        sentry_client.captureException()
        logger.exception({
            'action': 'update_app_version_to_moengage',
            'type': 'pre_save signal',
            'model': 'Application',
            'message': e
        })


@receiver(signals.post_init, sender=PaymentMethod)
def get_data_before_payment_method_updation(sender, instance=None, **kwargs):
    instance.__stored_payment_method_name = instance.payment_method_name
    instance.__stored_virtual_account = instance.virtual_account


@suspendingreceiver(signals.post_save, sender=PaymentMethod)
def get_data_after_payment_method_updation(sender, instance=None, created=False, **kwargs):
    payment_method = instance
    try:
        with transaction.atomic():
            if not payment_method._state.adding:
                if payment_method.__stored_payment_method_name != payment_method.payment_method_name:
                    send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                        payment_method.customer.id, 'va_number',),
                        countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    logger.info({
                        'action': 'get_data_after_account_payment_updation',
                        'payment_method_id': payment_method.id,
                        'old_payment_method_name': payment_method.__stored_payment_method_name,
                        'new_payment_method_name': payment_method.payment_method_name
                    })

                elif payment_method.__stored_virtual_account != payment_method.virtual_account:
                    send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                        payment_method.customer.id, 'va_method_name',),
                        countdown=settings.DELAY_FOR_REALTIME_EVENTS)
                    logger.info({
                        'action': 'get_data_after_account_payment_updation',
                        'payment_method_id': payment_method.id,
                        'old_virtual_account': payment_method.__stored_virtual_account,
                        'new_virtual_account': payment_method.virtual_account
                    })

    except Exception as e:
        logger.info({
            'action': 'get_data_after_payment_method_updation',
            'payment_method_id': payment_method.id,
            'error_message': e
        })


def suspendingreceiver(signal, **decorator_kwargs):
    def our_wrapper(func):
        @receiver(signal, **decorator_kwargs)
        @functools.wraps(func)
        def fake_receiver(sender, **kwargs):
            if getattr(settings, 'SUSPEND_SIGNALS', False):
                return
            return func(sender, **kwargs)
        return fake_receiver
    return our_wrapper


# repayment callback to partner  when payment event created
@suspendingreceiver(signals.post_save, sender=PaymentEvent)
def callback_for_repayment(sender, instance=None, created=False, **kwargs):
    payment_event = instance
    if created:
        if payment_event.event_type in ['payment']:
            account_payment = payment_event.payment.account_payment
            if account_payment:
                application = account_payment.account.application_set.last()
                if application.is_axiata_flow():
                    if application.partner.name == PartnerConstant.AXIATA_PARTNER:
                        task_va_payment_notification_to_partner.apply_async((
                            payment_event,), countdown=3)
                        logger.info({
                            'action': 'repayment_axiata_callback',
                            'timestamp': payment_event.id
                        })


@receiver(signals.post_save, sender=PTP)
def ptp_post_save_actions(sender, instance=None, created=False, **kwargs):
    ptp = instance
    if created:
        # this is to handle the streamline comm for ptp='real_time' based on platform SMS/PN/EMAIL
        execute_after_transaction_safely(
            lambda: send_realtime_ptp_notification.apply_async(
                (ptp.id,), countdown=settings.DELAY_FOR_REALTIME_EVENTS)
        )

        # flag turn  is_broken_ptp_plus_1
        turn_off_broken_ptp_plus_1 = True
        if ptp.account_payment:
            payment_or_account_payment = ptp.account_payment
            is_account_payment = True
            is_broken_ptp_plus_1 = payment_or_account_payment.account.is_broken_ptp_plus_1
        else:
            payment_or_account_payment = ptp.payment
            is_account_payment = False
            is_broken_ptp_plus_1 = payment_or_account_payment.loan.is_broken_ptp_plus_1

        if payment_or_account_payment:
            if ptp.ptp_status is not "Partial" and is_broken_ptp_plus_1:
                update_flag_is_broken_ptp_plus_1(payment_or_account_payment,
                                                 is_account_payment,
                                                 turn_off_broken_ptp_plus_1=True)
                logger.info({
                    'action': 'is_broken_ptp_plus_1',
                    'sub-action': 'turn_off_broken_ptp_plus_1',
                    'payment_id': payment_or_account_payment.id,
                    'ptp': ptp.id,
                    'is_account_payment': is_account_payment
                })


@receiver(signals.post_save, sender=SkiptraceHistory)
def skiptrace_history_after_save_actions(sender, instance=None, created=False, **kwargs):
    from juloserver.julo.services import update_flag_is_5_days_unreachable_and_sendemail

    signals.post_save.disconnect(skiptrace_history_after_save_actions, sender=SkiptraceHistory)
    skiptrace_history = instance
    if created:
        application = skiptrace_history.application
        if application:
            payment_or_account_payment = None
            if application.account:
                payment_or_account_payment = application.account.get_oldest_unpaid_account_payment()
                is_account_payment = True
            elif hasattr(application, 'loan'):
                payment_or_account_payment = application.loan.get_oldest_unpaid_payment()
                is_account_payment = False

            if payment_or_account_payment:
                is_real_time = True
                update_flag_is_5_days_unreachable_and_sendemail(
                    payment_or_account_payment.id, is_account_payment, is_real_time)
                logger.info({
                    'action': 'is_5_days_unreachable',
                    'sub-action': 'signal-update_flag_is_5_days_unreachable_and_sendemail',
                    'payment_id': payment_or_account_payment.id,
                    'skiptrace': skiptrace_history.id
                })
            else:
                logger.info({
                    'action': 'is_5_days_unreachable',
                    'sub-action': 'signal-update_flag_is_5_days_unreachable_and_sendemail',
                    'payment_id': "Not available",
                    'skiptrace': skiptrace_history.id
                })

    if skiptrace_history.notes:
        mask_phone_numbers.delay(
            skiptrace_history.notes, 'notes', SkiptraceHistory, skiptrace_history.id, False
        )
    signals.post_save.connect(skiptrace_history_after_save_actions, sender=SkiptraceHistory)


@receiver(signals.post_save, sender=LoanHistory)
def track_transact_for_action_points(sender, instance, created, **kwargs):
    # if loan is activated (status 220), we --
    # record_action_points_and_update_total()
    if created:
        loan_history = instance
        loan = loan_history.loan
        if (loan_history.status_new == LoanStatusCodes.CURRENT
                and loan_history.change_reason == LoanStatusChangeReason.ACTIVATED):
            if loan.get_application.eligible_for_cfs:
                execute_after_transaction_safely(
                    lambda: tracking_transaction_case_for_action_points.delay(
                        loan.id, CfsActionPointsActivity.TRANSACT
                    )
                )


@receiver(signals.post_save, sender=PaymentHistory)
def track_repayment_for_action_points(sender, instance, created, **kwargs):
    if created:
        payment_history = instance
        payment = payment_history.payment
        activity_id = get_activity_based_on_payment_history(payment_history)
        if activity_id:
            if payment.loan.get_application.eligible_for_cfs:
                execute_after_transaction_safely(
                    lambda: tracking_repayment_case_for_action_points.delay(
                        payment.id, activity_id
                    )
                )


@receiver(signals.post_save, sender=Payment)
def update_graduate_entry_level_payment_changed(sender, instance=None, created=False, **kwargs):
    if created:
        return
    tracker = instance.tracker
    old_values_dict = tracker.changed()

    new_values_dict = {}
    for field_name in old_values_dict.keys():
        new_values_dict[field_name] = getattr(instance, field_name)

    account = instance.loan.account
    if not account:
        return

    _update_graduate_entry_level(account)


@receiver(signals.post_save, sender=Loan)
def update_graduate_entry_level_loan_changed(sender, instance=None, created=False, **kwargs):
    if created:
        return
    status_old = instance.tracker.previous('loan_status_id')
    status_new = getattr(instance, 'loan_status_id')
    if status_old == status_new or status_new < LoanStatusCodes.CURRENT:
        return

    account = instance.account
    if not account:
        return

    _update_graduate_entry_level(account)


def _update_graduate_entry_level(account):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CFS,
        is_active=True
    ).last()
    if not feature_setting:
        return

    is_active_graduation = feature_setting.parameters.get('is_active_graduation', False)
    if not is_active_graduation:
        return

    account_property = account.accountproperty_set.last()
    is_entry_level = account_property.is_entry_level
    last_graduation_date = account_property.last_graduation_date

    if not is_entry_level or last_graduation_date:
        if is_entry_level and last_graduation_date:
            logger.error({
                'action': 'juloserver.julo.signals._update_graduate_entry_level',
                'is_entry_level': is_entry_level,
                'last_graduation_date': last_graduation_date
            })
        return

    graduation_rules = feature_setting.parameters['graduation_rules']
    execute_after_transaction_safely(
        lambda: update_graduate_entry_level.delay(
            account_id=account.id,
            graduation_rules=graduation_rules,
        )
    )


@receiver(signals.post_save, sender=CustomerWalletHistory)
def create_overpaid_case(sender, instance, created, **kwargs):
    if created:
        wallet_history = instance
        if wallet_history.change_reason == CashbackChangeReason.CASHBACK_OVER_PAID:
            generate_cashback_overpaid_case(wallet_history)


@receiver(signals.post_init, sender=MobileFeatureSetting)
@receiver(signals.post_init, sender=FeatureSetting)
def document_data_change_when_model_init(sender, instance=None, created=False, **kwargs):
    """
    Purpose: when models are instantiated, take the values of the fields in those models and store
    into a dictionary. This step is a starting point before comparing to values changed
    """
    fields = sender._meta.fields
    instance.__old_values = {}

    for field in fields:
        if field.name not in ['cdate', 'udate']:
            instance.__old_values[field.name] = getattr(instance, field.name)


@receiver(signals.post_save, sender=MobileFeatureSetting)
@receiver(signals.post_save, sender=FeatureSetting)
def document_data_change_after_model_update(sender, instance=None, created=False, **kwargs):
    """
    Purpose: Detect data update from Django Admin for Apps (sender). Document all the fields that
    were updated, 1 row per field, into the table DjangoAdminLogChanges.
    """
    if created:
        return

    group_uuid = uuid.uuid4().hex
    changed_list = []

    fields = sender._meta.fields
    for field in fields:
        if field.name not in ['cdate', 'udate']:
            if instance.__old_values[field.name] != getattr(instance, field.name):
                changed_list.append(DjangoAdminLogChanges(
                    group_uuid=group_uuid,
                    model_name=sender.__name__,
                    item_changed=field.name,
                    old_value=instance.__old_values[field.name],
                    new_value=getattr(instance, field.name)))
                instance.__old_values[field.name] = getattr(instance, field.name)

    DjangoAdminLogChanges.objects.bulk_create(changed_list)


@receiver(signals.post_save, sender=AddressGeolocation)
def fill_address_geolocation_geohash(sender, instance=None, created=False, **kwargs):
    if not created or instance is None:
        return

    save_address_geolocation_geohash(instance)


@receiver(signals.post_save, sender=Loan)
def invalidate_quick_transaction_cache(sender, created=False, instance=None, **kwargs):
    if not created and instance.loan_status_id == LoanStatusCodes.CURRENT:
        fs = FeatureSetting.objects.filter(
            feature_name=LoanFeatureNameConst.ONE_CLICK_REPEAT, is_active=True
        ).last()
        if not fs:
            return

        invalidate_one_click_repeat_cache(instance.customer)


@receiver(signals.post_save, sender=ApplicationFieldChange)
def update_skiptrace(sender, created=False, instance=None, **kwargs):
    logger.info(
        {
            'action': 'julo.signals.update_skiptrace',
            'application_field_change_id': instance.id,
        }
    )
    if created:
        if 'mobile_phone_1' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'mobile_phone_1', instance.application.mobile_phone_1)
            )

        if 'mobile_phone_2' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'mobile_phone_2', instance.application.mobile_phone_2)
            )
        if 'landlord_mobile_phone' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'landlord_mobile_phone', instance.application.landlord_mobile_phone)
            )
        if 'kin_mobile_phone' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'kin_mobile_phone', instance.application.kin_mobile_phone)
            )
        if 'close_kin_mobile_phone' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'close_kin_mobile_phone', instance.application.close_kin_mobile_phone)
            )
        if 'spouse_mobile_phone' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'spouse_mobile_phone', instance.application.spouse_mobile_phone)
            )
        if 'company_phone_number' == instance.field_name:
            execute_after_transaction_safely(
                lambda: update_skiptrace_number.delay(
                    instance.application.id, 'company_phone_number', instance.application.company_phone_number)
            )


@receiver(signals.post_save, sender=Payment)
def send_event_after_payment_changed(sender, instance=None, created=False, **kwargs):
    if created:
        return

    status_old = instance.tracker.previous('payment_status_id')
    status_new = getattr(instance, 'payment_status_id')
    if status_old == status_new or status_new != PaymentStatusCodes.PAID_ON_TIME:
        return

    account = instance.loan.account
    if not account:
        return

    application = account.get_active_application()
    if not application:
        return

    if not application.is_julo_one_or_starter():
        return

    payment_event = "x330"
    extra_params = {
        "installment_principal": instance.installment_principal,
        "credit_limit_balance": instance.loan.loan_disbursement_amount
    }

    send_event_to_ga_task_async.apply_async(
        kwargs={
            'customer_id': account.customer_id,
            'event': payment_event,
            'extra_params': extra_params
        })

    appsflyer_update_status_task.delay(
        application.id, payment_event, extra_params=extra_params)


@receiver(signals.post_save, sender=Payment)
def unfreeze_customer_referral_cashback(sender, instance=None, created=False, **kwargs):
    if created:
        return

    if not instance.payment_number == 1:
        return

    if not instance.payment_status.status_code >= PaymentStatusCodes.PAID_ON_TIME:
        return

    action = get_referral_cashback_action(event_type=ReferralCashbackEventType.FIRST_REPAYMENT)
    if action == ReferralCashbackAction.UNFREEZE:
        unfreeze_referrer_and_referree_cashback_task.delay(instance.loan.customer_id)


@receiver(signals.post_save, sender=Application)
def update_user_timezone_application_level(sender, instance, **kwargs):
    if ((not instance.tracker.has_changed('address_kodepos')
         and not instance.tracker.has_changed('account_id'))
            or not instance.address_kodepos or not instance.account_id):
        return
    # for handle save without using account but using account_id instead
    account = instance.account
    if not account:
        instance.refresh_from_db()
        account = instance.account

    from juloserver.account.tasks.account_task import update_user_timezone_async
    update_user_timezone_async.delay(instance.account.id)


@receiver(signals.post_save, sender=Application)
def update_dana_wallet_virtual_account_when_phone_number_change(
    sender, instance=None, created=False, **kwargs
):
    if created:
        return
    application = instance
    if application.__stored_mobile_phone_1 == application.mobile_phone_1:
        return
    payment_method = PaymentMethod.objects.filter(
        payment_method_code=PaymentMethodCodes.DANA_BILLER,
        customer=application.customer
    )
    if not payment_method:
        return
    payment_method.update(
        virtual_account=PaymentMethodCodes.DANA_BILLER + format_mobile_phone(
            application.mobile_phone_1
        )
    )


@receiver(signals.post_save, sender=Payment)
def mask_ptp_robocall_phone_number_post_save(sender, instance=None, created=False, **kwargs):
    signals.post_save.disconnect(mask_ptp_robocall_phone_number_post_save, sender=Payment)
    if instance.ptp_robocall_phone_number:
        mask_phone_numbers.delay(
            instance.ptp_robocall_phone_number,
            'ptp_robocall_phone_number',
            Payment,
            instance.id,
            False,
        )

    signals.post_save.connect(mask_ptp_robocall_phone_number_post_save, sender=Payment)

from __future__ import absolute_import

import logging
from celery import task
from collections import defaultdict
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q, Max
from django.db.models.expressions import RawSQL

from juloserver.account.services.account_related import (
    update_account_status_based_on_account_payment,
    register_accounts_late_fee_experiment,
)
from juloserver.account_payment.models import AccountPayment, CheckoutRequest
from juloserver.account_payment.services.account_payment_history import (
    update_account_payment_status_history,
)
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.account_payment.services.collection_related import (
    ptp_update_for_j1,
    primary_ptp_update_for_j1,
)
from juloserver.julo.services import (
    update_flag_is_broken_ptp_plus_1,
    update_late_fee_amount,
)
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account.constants import (
    AccountConstant,
    ImageSource
)
from juloserver.julo.models import (
    ExperimentSetting,
    Image,
    Customer,
    Device,
    PotentialCashbackHistory,
    Payment,
    FeatureSetting,
)
from juloserver.account.models import Account, ExperimentGroup
from juloserver.julo.constants import ExperimentConst, CheckoutExperienceExperimentGroup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.collops_qa_automation.utils import delete_local_file_after_upload
from juloserver.julo.clients import (
    get_julo_pn_client,
    get_julo_sentry_client,
)
from juloserver.julo.services2.experiment import get_experiment_setting_by_code
from juloserver.minisquad.services2.google_drive import get_data_google_drive_api_client
from juloserver.account_payment.models import LateFeeRule
from juloserver.account_payment.services.account_payment_related import new_update_late_fee
from juloserver.account_payment.constants import FeatureNameConst

logger = logging.getLogger(__name__)


@task(queue="update_account_payment")
def update_account_payment_status():
    """
    update account payment status every night regarding to the worst payment status
    """

    unpaid_account_payments = AccountPayment.objects.status_tobe_update()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EXCLUDE_GRAB_FROM_UPDATE_PAYMENT_STATUS,
        is_active=True,
    ).exists()
    if feature_setting:
        unpaid_account_payments = unpaid_account_payments.exclude(
            account__account_lookup__name=GRAB_ACCOUNT_LOOKUP_NAME
        )

    for unpaid_account_payments_id in unpaid_account_payments.values_list("id", flat=True):
        update_account_payment_status_subtask.delay(unpaid_account_payments_id)


@task(queue="update_account_payment",
      bind=True,
      max_retries=5,
      soft_time_limit=20
      )
def update_account_payment_status_subtask(self, account_payments_id):
    from juloserver.account.tasks.scheduled_tasks import \
        update_account_transaction_for_late_fee_event
    from juloserver.julo.tasks import update_payment_status_subtask

    try:
        with transaction.atomic():
            account_payment = (
                AccountPayment.objects.select_for_update()
                .select_related('account')
                .get(pk=account_payments_id)
            )
            if account_payment.status_id in PaymentStatusCodes.paid_status_codes():
                return

            payments_id = account_payment.payment_set.not_paid_active().values_list('id', flat=True)

            new_status_code = account_payment.get_status_based_on_due_date()
            with update_account_payment_status_history(
                account_payment, new_status_code, reason='update_based_on_dpd'
            ):
                # update account status
                # Make accounts with x440,441,442 stays  even though they passed the dpd
                if account_payment.account.status_id not in \
                        AccountConstant.NO_CHANGE_BY_DPD_STATUSES:
                    update_account_status_based_on_account_payment(account_payment)
                account_payment.update_safely(status_id=new_status_code, refresh=False)

            for payment_id in payments_id:
                update_late_fee_amount(payment_id)
                update_account_transaction_for_late_fee_event(payment_id)
                if account_payment.account and account_payment.account.account_lookup \
                        and account_payment.account.account_lookup.name \
                        != GRAB_ACCOUNT_LOOKUP_NAME:
                    execute_after_transaction_safely(
                        lambda id=payment_id:
                        update_payment_status_subtask.apply_async((id,),
                                                                  queue='update_account_payment')
                    )

            logger.info(
                {
                    "task": "update_account_payment_status_subtask",
                    "account_payment_id": account_payment.id,
                    "new_status_code": new_status_code
                }
            )
    except Exception as exc:
        self.retry(countdown=5, exc=exc)
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
        logger.error(
            {
                "task": "update_account_payment_status_subtask",
                "account_payment_id": account_payment.id,
                "error": str(exc)
            }
        )


@task(name='run_ptp_update_for_j1')
def run_ptp_update_for_j1():
    """
    scheduled to update ptp table for not paid status in reference to AccountPayment table
    """
    yesterday = timezone.localtime(timezone.now()).date() - timedelta(days=1)
    account_payments = AccountPayment.objects.filter(ptp_date=yesterday, paid_amount=0)
    for payment in account_payments:
        ptp_update_for_j1(payment.id, payment.ptp_date)
        primary_ptp_update_for_j1(payment.id, payment.ptp_date)
        # flag is_broken_ptp_plus_1
        update_flag_is_broken_ptp_plus_1(payment, is_account_payment=True)


@task(name='run_broken_ptp_flag_update_j1')
def run_broken_ptp_flag_update_j1():
    """
    scheduled  task to turn off flag is_broken_ptp_plus_1
    """
    range_2days_ago = timezone.localtime(timezone.now()).date() - timedelta(days=2)
    account_payments = AccountPayment.objects.filter(ptp_date=range_2days_ago,
                                                     account__is_broken_ptp_plus_1=True)
    for payment in account_payments:
        # turn off  is_broken_ptp_plus_1 on ptp+2
        update_flag_is_broken_ptp_plus_1(payment, is_account_payment=True,
                                         turn_off_broken_ptp_plus_1=True)


@task(queue='collection_normal')
def update_checkout_request_status_to_expired():
    """
    update checkout request status every exceed expired time
    """

    checkout_requests = CheckoutRequest.objects.status_tobe_update_expired()
    if checkout_requests:
        # why we send the PN first, its because if we put it after the status updated to expired
        # the query bellow will []
        send_checkout_experience_pn.delay(
            list(checkout_requests.values_list('account_id__customer_id', flat=True)),
            CheckoutRequestCons.EXPIRED,
        )
        for checkout_request in checkout_requests:
            update_va_bni_transaction.delay(
                checkout_request.account_id.id,
                'account_payment.tasks.scheduled_tasks.update_checkout_request_status_to_expired',
            )
        checkout_requests.update(status=CheckoutRequestCons.EXPIRED)


@task(queue='collection_normal')
def update_checkout_request_status_to_finished(checkout_request_id):
    """
    update checkout request status after status redeemed
    """
    with transaction.atomic():
        checkout_request = CheckoutRequest.objects.select_for_update().get(pk=checkout_request_id)
        if checkout_request.status == CheckoutRequestCons.REDEEMED:
            checkout_request.update_safely(status=CheckoutRequestCons.FINISH)


@task(queue='collection_normal')
def process_remaining_bulk_create_receipt_image_checkout_request(
    image_id, account_payment_ids, checkout_id
):
    from juloserver.julo.tasks import upload_image_julo_one

    upload_image_julo_one(image_id, True, ImageSource.ACCOUNT_PAYMENT)
    if not account_payment_ids:
        return

    images = []
    image_data = Image.objects.get(
        pk=image_id
    )
    for account_payment in account_payment_ids:
        image = Image.objects.create(
            image_source=int(account_payment),
            image_type=image_data.image_type,
            image_status=image_data.image_status,
            url=image_data.url,
            thumbnail_url=image_data.thumbnail_url,
            service=image_data.service
        )
        images.append(image.id)

    checkout = CheckoutRequest.objects.get(
        pk=checkout_id
    )
    checkout.receipt_ids += images
    checkout.save()


@task(queue='collection_normal')
def process_create_data_for_checkout_experience_experiment():
    today_date = timezone.localtime(timezone.now()).date()
    checkout_experiment = ExperimentSetting.objects.filter(
        is_active=True, code=ExperimentConst.CHECKOUT_EXPERIENCE_EXPERIMENT
    ).filter(
        (Q(start_date__date__lte=today_date) & Q(end_date__date__gte=today_date))
        | Q(is_permanent=True)
    ).last()
    if not checkout_experiment:
        logger.info(
            {
                "task": "process_create_data_for_checkout_experience_experiment",
                "message": "checkout experiment setting not found or not active",
            }
        )
        return
    process_insert_data_for_checkout_experience_experiment.delay(checkout_experiment.id)


@task(queue='collection_normal')
def process_insert_data_for_checkout_experience_experiment(checkout_experiment_id):
    # handle to not insert account for existing data
    checkout_experiment = ExperimentSetting.objects.get(pk=checkout_experiment_id)
    account_experiment = Account.objects.all()
    exist_experiment = ExperimentGroup.objects.filter(
        experiment_setting=checkout_experiment
    ).values_list('account_id', flat=True)

    with transaction.atomic():
        # get data account, and get account id tail criteria
        account_experiment = account_experiment.exclude(pk__in=exist_experiment)
        checkout_group_criteria = checkout_experiment.criteria['account_id_tail']
        control_group_criteria = tuple(
            list(map(str, checkout_group_criteria['control_group'])))
        experiment_group_1_criteria = tuple(
            list(map(str, checkout_group_criteria['experiment_group_1'])))
        experiment_group_2_criteria = tuple(
            list(map(str, checkout_group_criteria['experiment_group_2'])))
        # filter account id tail by checkout expriment criteria
        control_group_ids = []
        test_experiment_group_1_ids = []
        test_experiment_group_2_ids = []
        if control_group_criteria:
            control_group_ids = account_experiment.extra(
                where=["right(account.account_id::text, 1) in %s"], params=[control_group_criteria]
            ).values_list('id', flat=True)
            account_experiment = account_experiment.exclude(pk__in=control_group_ids)
        if experiment_group_1_criteria:
            test_experiment_group_1_ids = account_experiment.extra(
                where=["right(account.account_id::text, 1) in %s"],
                params=[experiment_group_1_criteria],
            ).values_list('id', flat=True)
            account_experiment = account_experiment.exclude(pk__in=test_experiment_group_1_ids)
        if experiment_group_2_criteria:
            test_experiment_group_2_ids = account_experiment.extra(
                where=["right(account.account_id::text, 1) in %s"],
                params=[experiment_group_2_criteria],
            ).values_list('id', flat=True)
            account_experiment = account_experiment.exclude(pk__in=test_experiment_group_2_ids)
        test_control_group_data = []
        test_experiment_group_1_data = []
        test_experiment_group_2_data = []
        # insert "control group"
        if control_group_ids:
            for test_control_group_id in control_group_ids:
                test_control_group_data.append(
                    ExperimentGroup(
                        account_id=test_control_group_id,
                        experiment_setting=checkout_experiment,
                        group=CheckoutExperienceExperimentGroup.CONTROL_GROUP,
                    )
                )
            ExperimentGroup.objects.bulk_create(test_control_group_data, batch_size=2000)
        # insert "experiment group 1"
        if test_experiment_group_1_ids:
            for test_experiment_group_1_id in test_experiment_group_1_ids:
                test_experiment_group_1_data.append(
                    ExperimentGroup(
                        account_id=test_experiment_group_1_id,
                        experiment_setting=checkout_experiment,
                        group=CheckoutExperienceExperimentGroup.EXPERIMENT_GROUP_1,
                    )
                )
            ExperimentGroup.objects.bulk_create(test_experiment_group_1_data, batch_size=2000)
        # insert "experiment group 2"
        if test_experiment_group_2_ids:
            for test_experiment_group_2_id in test_experiment_group_2_ids:
                test_experiment_group_2_data.append(
                    ExperimentGroup(
                        account_id=test_experiment_group_2_id,
                        experiment_setting=checkout_experiment,
                        group=CheckoutExperienceExperimentGroup.EXPERIMENT_GROUP_2,
                    )
                )
            ExperimentGroup.objects.bulk_create(test_experiment_group_2_data, batch_size=2000)


@task(queue='collection_normal')
def send_checkout_experience_pn(
    customer_ids,
    checkout_request_status,
    actual_paid_amount=0,
    checkout_request_id=None,
    total_payment_before_updated=0,
):
    template_code = ''
    customers = Customer.objects.filter(id__in=customer_ids)
    if not customers:
        return
    checkout_commit_amount = 0
    # the first if can be multiple so we use customer_ids rather than customer_id
    if checkout_request_status == CheckoutRequestCons.EXPIRED:
        template_code = 'pn_checkout_expired'
    elif checkout_request_status == CheckoutRequestCons.CANCELED:
        template_code = 'pn_checkout_cancelled'
    elif (
        checkout_request_status == CheckoutRequestCons.PAID_CHECKOUT
        and checkout_request_id is not None
    ):
        checkout_request = CheckoutRequest.objects.get_or_none(pk=checkout_request_id)
        if not checkout_request:
            return
        checkout_commit_amount = checkout_request.checkout_amount
        remaining_checkout_amount = actual_paid_amount - total_payment_before_updated
        if remaining_checkout_amount == 0:
            template_code = 'pn_checkout_payfull'
        elif remaining_checkout_amount < 0:
            template_code = 'pn_checkout_paylessfull'
        elif remaining_checkout_amount > 0:
            template_code = 'pn_checkout_paymorefull'

    if not template_code:
        return

    julo_pn_client = get_julo_pn_client()
    gcm_reg_ids = (
        Device.objects.filter(customer_id__in=customer_ids)
        .order_by('customer_id', '-cdate')
        .distinct('customer_id')
        .values_list('gcm_reg_id', flat=True)
    )
    for gcm_reg_id in gcm_reg_ids:
        julo_pn_client.checkout_notification(
            gcm_reg_id, template_code, commitment_amount=checkout_commit_amount
        )


@task(queue='collection_normal')
def send_early_repayment_experience_pn(account_payment_payments, account_id):
    julo_pn_client = get_julo_pn_client()
    account = Account.objects.get_or_none(pk=account_id)

    if not account:
        return

    customer_id = account.customer_id
    device = account.last_application.device

    if not device or not device.gcm_reg_id:
        logger.info(
            {
                "action": "send_early_repayment_experience_pn",
                "account_id": account.id,
                "message": "customer did not have device",
            }
        )
        return

    account_payment_ids = []
    loan_ids = []

    for i, (key, values) in enumerate(account_payment_payments.items()):
        account_payment = AccountPayment.objects.get_or_none(pk=key)

        if not account_payment:
            continue

        for payment_obj in account_payment.payment_set.filter(id__in=values['payments']):
            loan = payment_obj.loan

            if payment_obj.status < 330:
                continue

            PotentialCashbackHistory.objects.create(
                account_payment=account_payment,
                loan=loan,
                payment=payment_obj,
                amount=payment_obj.cashback_earned,
            )

            if key not in account_payment_ids:
                account_payment_ids.append(key)

            if loan.loan_status.status_code == LoanStatusCodes.PAID_OFF:
                if loan.id in loan_ids:
                    continue
                loan_ids.append(loan.id)

    if loan_ids:
        julo_pn_client.pn_cashback_for_early_repayment(
            device.gcm_reg_id,
            'pn_cashback_claim',
            customer_id,
            loan_ids=loan_ids
        )

    julo_pn_client.pn_cashback_for_early_repayment(
        device.gcm_reg_id,
        'pn_cashback_potential',
        customer_id,
        account_payment_ids=account_payment_ids,
    )


@task(queue='repayment_high')
def register_late_fee_experiment():
    from juloserver.moengage.tasks import trigger_send_user_attribute_late_fee_earlier_experiment
    fn_name = 'register_late_fee_experiment'
    retries = register_late_fee_experiment.request.retries
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    late_fee_experiment = get_experiment_setting_by_code(
        MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT)
    if not late_fee_experiment:
        logger.warning({
            'action': fn_name,
            'message': 'late fee experiment inactive'
        })
        return
    path_file = ''
    try:
        criteria = late_fee_experiment.criteria if late_fee_experiment.criteria else dict()
        folder_id = criteria.get('folder_id', None)
        if not folder_id:
            logger.warning({
                'action': fn_name,
                'message': 'gdrive folder_id not declare on experiment setting'
            })
            return
        gdrive = get_data_google_drive_api_client()
        path_file = gdrive.find_file_on_folder_by_id(folder_id)
        if not path_file:
            raise Exception('There issue during downloading file from gdrive')
        logger.warning({
            'action': fn_name,
            'message': 'processing data to experiment group'
        })
        register_accounts_late_fee_experiment(path_file, late_fee_experiment)
        delete_local_file_after_upload(path_file)
        trigger_send_user_attribute_late_fee_earlier_experiment.delay()
    except Exception as error:
        logger.error({
            'action': fn_name,
            'retries': retries,
            'message': str(error)
        })
        if retries >= register_late_fee_experiment.max_retries:
            get_julo_sentry_client().captureException()
            delete_local_file_after_upload(path_file)
            return

        raise register_late_fee_experiment.retry(
            countdown=300, exc=error, max_retries=3)

    logger.warning({
        'action': fn_name,
        'message': 'task finish'
    })


@task(queue='update_account_payment')
def new_late_fee_generation_task():
    logger.info(
        {
            "action": "juloserver.account_payment.tasks."
            "scheduled_tasks.new_late_fee_generation_task",
            "message": "new_late_fee_generation_task started",
        }
    )
    late_fee_rules = LateFeeRule.objects.all()
    late_fee_rules_dpd_ranges = late_fee_rules.aggregate(max_dpd=Max('dpd'))
    late_fee_rule_counts_dict = defaultdict(dict)
    late_fee_rules_annotated = late_fee_rules.annotate(
        late_fee_count=RawSQL("RANK() OVER (PARTITION BY product_code ORDER BY dpd ASC)", [])
    )
    for late_fee_rule in late_fee_rules_annotated.values(
        'product_lookup_id', 'dpd', 'late_fee_count'
    ):
        late_fee_rule_counts_dict[late_fee_rule['product_lookup_id']][
            late_fee_rule['late_fee_count']
        ] = late_fee_rule['dpd']
    max_late_fee_rule_count = max(late_fee_rules_annotated.values_list('late_fee_count', flat=True))
    today = timezone.localtime(timezone.now()).date()
    max_due_date = today + timedelta(days=late_fee_rules_dpd_ranges['max_dpd'])
    unpaid_payments = (
        Payment.objects.not_paid_active_overdue().
        filter(
            due_date__lte=max_due_date,
            loan__product_id__in=late_fee_rule_counts_dict.keys(),
            late_fee_applied__lt=max_late_fee_rule_count,
        )
        .select_related('loan')
        .only('id', 'loan_id', 'loan__product_id', 'late_fee_applied', 'payment_status', 'due_date')
    )
    generation_attempt = 0
    for payment in unpaid_payments.iterator():
        product_late_fee_rules = late_fee_rule_counts_dict.get(payment.loan.product_id)
        if (
            product_late_fee_rules
            and product_late_fee_rules.get(payment.late_fee_applied + 1)
            and product_late_fee_rules.get(payment.late_fee_applied + 1) <= payment.get_dpd
        ):
            new_late_fee_generation_subtask.delay(payment.id)
            generation_attempt += 1

    logger.info(
        {
            "action": "juloserver.account_payment.tasks."
            "scheduled_tasks.new_late_fee_generation_task",
            "message": "new_late_fee_generation_task finished",
            "generation_attempt_count": generation_attempt,
        }
    )


@task(queue='update_account_payment')
def new_late_fee_generation_subtask(payment_id):
    from juloserver.account.tasks.scheduled_tasks import (
        update_account_transaction_for_late_fee_event,
    )
    with transaction.atomic():
        new_update_late_fee(payment_id)
        update_account_transaction_for_late_fee_event(payment_id)

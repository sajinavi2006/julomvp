from builtins import map
from builtins import str
import logging
import math
import numpy as np
from celery.canvas import chain

from datetime import datetime, timedelta, time

from django.conf import settings
from django.utils import timezone
from django.db.models import F, Q
from django.utils.timezone import make_aware

from juloserver.julo.models import (
    Payment,
    CootekRobocall,
    Partner,
    Loan,
    VendorDataHistory,
    ExperimentSetting,
    SkiptraceHistory,
    SkiptraceResultChoice,
    FeatureSetting,
    Application,
    Customer,
)
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.julo.services2 import get_redis_client
from juloserver.cootek.models import (CootekConfiguration,
                                      CootekRobot)
from juloserver.cootek.clients import get_julo_cootek_client
from juloserver.julo.clients import get_julo_centerix_client
from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.minisquad.constants import (
    RedisKey,
    ReasonNotSentToDialer,
    IntelixTeam,
    DialerTaskStatus,
    DialerServiceTeam,
    BTTCExperiment,
)
from juloserver.minisquad.services import (
    get_oldest_payment_ids_loans,
    filter_intelix_blacklist_for_t0,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.constants import (
    ExperimentConst,
    ProductLineCodes,
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.minisquad.services import get_upload_centerix_data_params
from juloserver.cootek.utils import convert_gender
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    format_valid_e164_indo_phone_number,
)
from juloserver.paylater.models import Statement
from juloserver.cootek.constants import (
    CootekAIRobocall,
    CootekProductLineCodeName,
    JuloGoldFilter,
)
from juloserver.paylater.models import TransactionOne, LoanOne
from juloserver.paylater.constants import PaylaterConst

from juloserver.loan_refinancing.models import LoanRefinancingOffer
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.cootek.utils import add_minutes_to_datetime
from juloserver.account_payment.services.pause_reminder import \
    check_account_payment_is_blocked_comms
from juloserver.julo.services import check_payment_is_blocked_comms
from juloserver.julo.services2.voice import (
    excluding_autodebet_account_payment_dpd_minus,
    excluding_risky_account_payment_dpd_minus,
)

from .constants import CriteriaChoices
from ..account.constants import AccountConstant
from ..account_payment.models import AccountPayment
from juloserver.dana.collection.services import get_dana_oldest_unpaid_account_payment_ids
from juloserver.minisquad.models import (
    SentToDialer,
    NotSentToDialer,
    DialerTask,
    AIRudderPayloadTemp,
)
from juloserver.minisquad.tasks2.intelix_task import (
    delete_paid_payment_from_intelix_if_exists_async_for_j1,
    record_not_sent_to_intelix_task,
)
from juloserver.streamlined_communication.services import (
    exclude_experiment_excellent_customer_from_robocall
)
from juloserver.streamlined_communication.tasks import record_customer_excellent_experiment
from juloserver.ana_api.models import PdCustomerSegmentModelResult
from ..streamlined_communication.constant import RobocallType
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.minisquad.services2.intelix import (
    create_history_dialer_task_event,
    set_redis_data_temp_table,
    construct_data_for_intelix,
    record_intelix_log_for_j1,
)
from juloserver.minisquad.tasks2.intelix_task2 import send_data_to_intelix_with_retries_mechanism
from juloserver.julo.services2.experiment import get_experiment_setting_by_code
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.account.models import ExperimentGroup
from juloserver.minisquad.tasks2.dialer_system_task import (
    delete_paid_payment_from_dialer,
)
from juloserver.minisquad.services2.growthbook import get_experiment_setting_data_on_growthbook
from juloserver.credgenics.constants.feature_setting import CommsType
from juloserver.credgenics.services.utils import is_comms_block_active, get_credgenics_account_ids
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    get_exclusion_omnichannel_account_ids,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting
from juloserver.pii_vault.constants import PiiSource
from juloserver.minisquad.utils import collection_detokenize_sync_primary_object_model_in_bulk
from juloserver.minisquad.constants import FeatureNameConst as MinisquadFeatureNameConst
from juloserver.minisquad.services2.dialer_related import exclude_bttc_t0_bucket_from_other_comms

logger = logging.getLogger(__name__)


def change_field_from_previous_cootek_for_first_round_in_cootek():
    cootek_for_bl = CootekConfiguration.objects.filter(
        partner__name='bukalapak_paylater', is_active=True
    ).order_by('task_type', 'time_to_start').distinct('task_type')
    cootek_for_normal_payment = CootekConfiguration.objects.filter(
        partner__isnull=True,
        is_active=True
    ).order_by('task_type', 'time_to_start').distinct('task_type')
    for config in cootek_for_bl:
        config.update_safely(from_previous_cootek_result=False)
    for config in cootek_for_normal_payment:
        config.update_safely(from_previous_cootek_result=False)


def create_task_to_send_data_customer_to_cootek(cootek_record, start_time, end_time=None):
    try:
        experiment_setting = check_cootek_experiment(
            start_time,
            cootek_record.is_bl_paylater(),
        )
        if (
            not experiment_setting
            and not cootek_record.is_allowed_product
            and not cootek_record.is_unconnected_late_dpd
        ):
            return
        experiment_setting = None if cootek_record.is_unconnected_late_dpd else experiment_setting
        dpd_config = None if not experiment_setting else experiment_setting.criteria.get('dpd')
        is_object_skiptrace = False
        if not end_time:
            end_time = start_time + timedelta(hours=1)
        if cootek_record.is_unconnected_late_dpd:
            is_object_skiptrace = True
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.COOTEK_LATE_DPD_SETTING, is_active=True
            ).last()
            if feature_setting:
                criteria_end_time = feature_setting.parameters[
                    cootek_record.unconnected_late_dpd_time
                ]
                end_time = start_time + timedelta(minutes=criteria_end_time)

        payment_filter = cootek_record.get_payment_filter(
            dpd_config, is_object_skiptrace=is_object_skiptrace
        )

        today = start_time.strftime("%b_%d_%Y")
        hour = start_time.strftime("%H")

        task_key = cootek_record.task_type + "_" + hour
        task_name = task_key + "_" + today
        # since task name between production and staging cannot be same
        # and because we dont have any sandbox env, then name of task cannot be same
        if settings.ENVIRONMENT != 'prod':
            task_name = settings.ENVIRONMENT + "_" + task_name
        repeat_number = int(cootek_record.number_of_attempts)

        details = get_payment_details_for_cootek_data(
            cootek_record, experiment_setting, payment_filter
        )
        cootek_client = get_julo_cootek_client()

        if not details:
            logger.info(
                {
                    'action': 'create_task_to_send_data_customer_to_cootek',
                    'message': 'data is not provided',
                    'start_time': start_time,
                    'end_time': end_time,
                    'cootek_configuration_id': cootek_record.id,
                    'time_execute': timezone.localtime(timezone.now()),
                }
            )
            return

        task_id = cootek_client.create_task(
            task_name=task_name,
            start_time=start_time,
            end_time=end_time,
            robot=cootek_record.cootek_robot,
            attempts=repeat_number,
            task_details=details,
        )

        if task_id:
            insert_cootek_data(task_id, task_name, cootek_record, details, repeat_number)
    except Exception as err:
        logger.error(
            {
                'action': 'create_task_to_send_data_customer_to_cootek',
                'message': str(err),
                'start_time': start_time,
                'end_time': end_time,
                'cootek_configuration_id': cootek_record.id,
                'time_execute': timezone.localtime(timezone.now()),
            }
        )
        get_julo_sentry_client().captureException()


def get_payment_details_for_cootek(called_at, experiment_setting, payment_filter, product):
    query_set = Payment.objects.normal()
    product_lines = []
    if product in ("mtl", "stl"):
        product_lines = ProductLineCodes.mtl()
        if product == "stl":
            product_lines = ProductLineCodes.stl()
        query_set = query_set.filter(
            loan__application__product_line__in=product_lines
        )
    exclude_partner_ids = Partner.objects.filter(name__in=PartnerConstant.form_partner())\
        .values_list('id', flat=True)
    query_set = query_set.exclude(loan__application__partner__id__in=exclude_partner_ids)
    redis_client = get_redis_client()
    cached_oldest_payment_ids = redis_client.get_list(RedisKey.OLDEST_PAYMENT_IDS)

    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()

        if oldest_payment_ids:
            redis_client.set_list(RedisKey.OLDEST_PAYMENT_IDS,
                                  oldest_payment_ids, timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    payments = query_set.bucket_cootek([])
    payments = payments.filter(**payment_filter)
    payments = payments.filter(id__in=oldest_payment_ids)
    payments = check_loan_for_creating_cootek_data(payments, called_at, experiment_setting)
    return payments


def check_cootek_experiment(start_time, is_paylater=False, is_experiment_late_dpd=False):
    if is_experiment_late_dpd:
        today = timezone.localtime(timezone.now()).date()
        return ExperimentSetting.objects.filter(
            is_active=True, code=ExperimentConst.COOTEK_LATE_DPD_J1
        ).filter(
            (Q(start_date__date__lte=today) & Q(end_date__date__gte=today))
            | Q(is_permanent=True)
        ).last()

    exp_code = ExperimentConst.COOTEK_BL_PAYLATER
    if not is_paylater:
        exp_code = ExperimentConst.COOTEK_AI_ROBOCALL_TRIAL_V5
    return ExperimentSetting.objects.get_or_none(
        code=exp_code,
        is_active=True,
        type="payment",
        start_date__lte=start_time,
        end_date__gte=start_time,
    )


def check_statement_experiment(statements, experiment_setting):
    if experiment_setting:
        return statements
    return []


def check_loan_for_creating_cootek_data(data, dpd, experiment_setting):
    if experiment_setting and (dpd in experiment_setting.criteria['dpd']):
        criteria = experiment_setting.criteria
        items = criteria['loan_id'].split(':')
        criteria_ids = items[2].split(',')

        data_to_return = data.annotate(last_digit=F('loan_id') % 10) \
                             .filter(last_digit__in=tuple(criteria_ids))
        return data_to_return.values_list('id', flat=True)

    logger.info({
        'action': 'check_loan_for_creating_cootek_data',
        'error': 'can not get loan for cootek experiment'
    })
    return []


# get payment for dpd = [0, -1, -2] for cootek data
def get_payment_details_for_cootek_data(cootek_record, experiment_setting, payment_filter):

    is_comms_blocked_enabled = is_comms_block_active(CommsType.TWO_WAY_ROBOCALL)
    omnichannel_comms_blocked = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.TWO_WAY_ROBOCALL,
    )

    # Bulakapak Paylater Logic (Deprecated by business)
    if cootek_record.partner is not None and cootek_record.partner.name == 'bukalapak_paylater':
        statements = []

        if cootek_record.from_previous_cootek_result:
            previous_cootek_results, statements = get_payment_with_specific_intention_from_cootek(
                cootek_record.tag_status, cootek_record.task_type, 'statement',
                cootek_record.time_to_start)

            statements = Statement.objects.filter(pk__in=statements)

            if not statements and previous_cootek_results:
                return

        if not statements:
            statements = Statement.objects.filter(**payment_filter)

        statements = statements.exclude(
            statement_status__in=PaymentStatusCodes.paylater_paid_status_codes()
        )

        payment_details = [
            {
                'Debtor': statement.customer_credit_limit.customer.fullname,
                'Mobile': format_e164_indo_phone_number(
                    str(statement.customer_credit_limit.customer.phone)),
                'LoanDate': statement.cdate.strftime("%Y-%m-%d"),
                'DueDate': statement.statement_due_date.strftime("%Y-%m-%d"),
                'LoanAmount': statement.statement_due_amount,
                # # arrears can not be zero, zero means payment already paid_off
                'Arrears': statement.statement_due_amount,
                'Unit': CootekAIRobocall.UNIT_RUPIAH,
                'Platform': CootekAIRobocall.PLATFORM_JULO,
                'Comments': statement.id,
                'Gender': convert_gender(statement.customer_credit_limit.customer.gender)
            }
            for statement in statements
            if (
                statement.statement_due_amount is not None
                and statement.statement_due_amount > 0
                and statement.customer_credit_limit.customer.phone
            )
        ]
        return payment_details

    if cootek_record.partner and cootek_record.partner.name == CootekProductLineCodeName.DANA:
        account_payments = AccountPayment.objects.none()
        if cootek_record.from_previous_cootek_result:
            previous_cootek_results, account_payment_ids = \
                get_payment_with_specific_intention_from_cootek(
                    cootek_record.tag_status, cootek_record.task_type, 'account_payment',
                    cootek_record.product, cootek_record.time_to_start
                )
            account_payments = AccountPayment.objects.not_paid_active().filter(
                id__in=list(account_payment_ids))
            if not account_payments and previous_cootek_results:
                return

        if not account_payments:
            account_payments = get_dana_account_payment_for_cootek(payment_filter)

        account_payments = account_payments.select_related('account__dana_customer_data')
        account_payment_details = []
        failed_account_payment = []
        # construct data for sending to cootek
        for account_payment in account_payments.iterator():
            try:
                if not account_payment.account.dana_customer_data.mobile_number:
                    raise Exception("dana account dont have mobile number")
                # we have rule that loanDate should be < then DueDate even though we not using
                # loan level
                loan_date = account_payment.due_date - timedelta(days=1)
                data_for_cootek = {
                    'Debtor': account_payment.account.dana_customer_data.full_name,
                    'Mobile': format_valid_e164_indo_phone_number(
                        account_payment.account.dana_customer_data.mobile_number),
                    'LoanDate': loan_date.strftime("%Y-%m-%d"),
                    'DueDate': account_payment.due_date.strftime("%Y-%m-%d"),
                    'LoanAmount': account_payment.due_amount,
                    'Arrears': account_payment.due_amount,
                    'Unit': CootekAIRobocall.UNIT_RUPIAH,
                    'Platform': CootekAIRobocall.PLATFORM_DANA,
                    'Comments': account_payment.id,
                    'Gender': 'male'
                }
                account_payment_details.append(data_for_cootek)
            except Exception as e:
                failed_account_payment.append(
                    dict(account_payment_id=account_payment.id, reason=str(e))
                )
        if failed_account_payment:
            logger.warning({
                'message': 'some of account payment not eligible',
                'action': 'get_payment_details_for_cootek_data',
                'cootek_record_id': cootek_record.id,
                'skipped_data': failed_account_payment
            })
        return account_payment_details

    # Refinancing Pending criteria
    if cootek_record.criteria == CriteriaChoices.REFINANCING_PENDING:
        last_4_days = timezone.localtime(timezone.now()) - timedelta(4)
        loan_refinancing_offer = []

        if cootek_record.from_previous_cootek_result:
            previous_cootek_results, loan_refinancing_offer = get_payment_with_specific_intention_from_cootek(
                cootek_record.tag_status, cootek_record.task_type, 'loan_refinancing_offer',
                cootek_record.time_to_start
            )

            if not loan_refinancing_offer and previous_cootek_results:
                return

            loan_refinancing_offer = LoanRefinancingOffer.objects.filter(
                pk__in=loan_refinancing_offer,
                loan_refinancing_request__status='Approved',
                offer_accepted_ts__date=last_4_days,
                is_accepted=True,
            )

        if not loan_refinancing_offer:
            loan_refinancing_offer = get_loan_refinancing_offer_for_cootek(last_4_days)

        payment_details = [
            {
                'Debtor': loan_offer.loan_refinancing_request.loan.application.fullname,
                'Mobile': format_e164_indo_phone_number(
                    str(loan_offer.loan_refinancing_request.loan.application.mobile_phone_1)),
                'LoanDate': (loan_offer.cdate).strftime("%Y-%m-%d"),
                'DueDate': (
                    loan_offer.offer_accepted_ts +
                    timedelta(
                        loan_offer.loan_refinancing_request.expire_in_days
                    )).strftime("%Y-%m-%d"),
                'LoanAmount': loan_offer.prerequisite_amount,
                # arrears can not be zero, zero means payment already paid_off
                'Arrears': loan_offer.prerequisite_amount,
                'Unit': CootekAIRobocall.UNIT_RUPIAH,
                'Platform': CootekAIRobocall.PLATFORM_JULO,
                'Comments': loan_offer.id,
                'Gender': convert_gender(
                    loan_offer.loan_refinancing_request.loan.application.gender)
            }
            for loan_offer in loan_refinancing_offer
            if (
                loan_offer.prerequisite_amount is not None
                and loan_offer.prerequisite_amount > 0
                and loan_offer.loan_refinancing_request.loan.application.mobile_phone_1
            )
        ]
        return payment_details

    # J1 Reminder
    if cootek_record.is_julo_one_product:
        account_payments = []
        if cootek_record.is_unconnected_late_dpd:
            items = get_j1_turbo_late_dpd_account_payment_for_cootek(
                payment_filter, cootek_record
            )
            account_payment_ids = [item.account_payment.id for item in items]
            account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids)
        else:
            if cootek_record.from_previous_cootek_result:
                previous_cootek_results, account_payments = \
                    get_payment_with_specific_intention_from_cootek(
                        cootek_record.tag_status, cootek_record.task_type, 'account_payment',
                        cootek_record.product, cootek_record.time_to_start
                    )

                if not account_payments and previous_cootek_results:
                    return

                account_payments = AccountPayment.objects.filter(id__in=account_payments)
                account_payments = account_payments.exclude(
                    status__in=PaymentStatusCodes.paylater_paid_status_codes()
                )

            if not account_payments:
                account_payments = get_j1_account_payment_for_cootek(payment_filter)

            # Exclude JULO Gold
            if cootek_record.julo_gold:
                logger.info(
                    {
                        'action': 'get_payment_details_for_cootek_data',
                        'cootek_configuration_id': cootek_record.id,
                        'julo_gold': cootek_record.julo_gold,
                    }
                )
                account_payments = filter_julo_gold(cootek_record, account_payments)

            if cootek_record.exclude_risky_customer:
                account_payments = excluding_risky_account_payment_dpd_minus(account_payments)

            if cootek_record.exclude_autodebet:
                account_payments = excluding_autodebet_account_payment_dpd_minus(account_payments)

            if cootek_record.product == "J1" and cootek_record.called_at in (0, -2, -1):
                account_payments = excluding_risky_account_payment_dpd_minus(account_payments)
                record_experiment_key = "{}_{}".format(RobocallType.COOTEK_J1, cootek_record.id)
                account_payments = exclude_experiment_excellent_customer_from_robocall(
                    account_payments, record_type=record_experiment_key)
                record_customer_excellent_experiment.apply_async(
                    (record_experiment_key,), countdown=5)

            account_payments = account_payments.exclude(
                account__status_id=AccountConstant.STATUS_CODE.sold_off
            )

            # if omnichannel comms block activated exclude the user
            if is_comms_blocked_enabled:
                account_ids = get_credgenics_account_ids()
                account_payments = account_payments.exclude(account__in=list(account_ids))
            if omnichannel_comms_blocked.is_excluded:
                account_ids = get_exclusion_omnichannel_account_ids(omnichannel_comms_blocked)
                account_payments = account_payments.exclude(account__in=list(account_ids))

            # handle late fee earlier experiment
            account_payments = filtering_late_fee_earlier_experiment_for_cootek(
                cootek_record, account_payments)

            # handle cashback new scheme experiment
            account_payments = filtering_cashback_new_scheme_experiment_for_cootek(
                cootek_record, account_payments)

        payment_details = []
        if not account_payments:
            return payment_details

        # exclude BTTC
        if cootek_record.called_at == 0:
            account_payments = exclude_bttc_t0_bucket_from_other_comms(account_payments)

        customer_ids = list(account_payments.values_list('account__customer__id', flat=True))
        customers = Customer.objects.filter(pk__in=customer_ids).only('fullname', 'phone')
        fs_detokenized = FeatureSetting.objects.filter(
            feature_name=MinisquadFeatureNameConst.DIALER_IN_BULK_DETOKENIZED_METHOD, is_active=True
        ).last()
        max_detokenized_row = 100
        if fs_detokenized:
            max_detokenized_row = fs_detokenized.parameters.get('detokenize_row', 100)
        # split data depend on how many fields we want to detokenized
        # "2" here is how may field we want to detokenized
        split_into = math.ceil((len(customers) * 2) / max_detokenized_row)
        divided_customers_per_batch = np.array_split(customers, split_into)
        detokenized_customers = dict()
        for customers_per_part in divided_customers_per_batch:
            detokenized_customers_per_part = (
                collection_detokenize_sync_primary_object_model_in_bulk(
                    PiiSource.CUSTOMER,
                    customers_per_part,
                    ['fullname', 'phone'],
                )
            )
            detokenized_customers.update(detokenized_customers_per_part)
        for account_payment in account_payments:
            try:
                if (
                    check_account_payment_is_blocked_comms(account_payment, 'cootek')
                    or account_payment.due_amount is None
                    or account_payment.due_amount <= 0
                ):
                    continue

                account = account_payment.account
                customer = account.customer
                customer_xid = customer.customer_xid
                application = account.application_set.filter(
                    workflow__name=WorkflowConst.JULO_ONE
                ).last()
                customer_detokenized = detokenized_customers.get(customer_xid)
                mobile_phone_1 = getattr(customer_detokenized, 'phone', None) or customer.phone
                fullname = getattr(customer_detokenized, 'fullname', None) or customer.fullname
                if not mobile_phone_1:
                    logger.warning(
                        {
                            'message': 'There is no phone number for the application.',
                            'action': 'get_payment_details_for_cootek_data',
                            'application_id': application.id,
                            'account_payment_id': account_payment.id,
                            'cootek_record_id': cootek_record.id,
                            'customer_id': customer.id,
                        }
                    )
                    continue

                # not used anymore at J1 but the field is mandatory
                loan = account_payment.payment_set.order_by('cdate').last().loan
                payment_details.append(
                    {
                        'Debtor': fullname,
                        'Mobile': format_e164_indo_phone_number(str(mobile_phone_1)),
                        'LoanDate': loan.cdate.strftime("%Y-%m-%d"),
                        'DueDate': account_payment.due_date.strftime("%Y-%m-%d"),
                        'LoanAmount': loan.loan_amount,
                        # arrears can not be zero, zero means payment already paid_off
                        'Arrears': account_payment.due_amount,
                        'Unit': CootekAIRobocall.UNIT_RUPIAH,
                        'Platform': CootekAIRobocall.PLATFORM_JULO,
                        'Comments': account_payment.id,
                        'Gender': convert_gender(application.gender),
                        # ExtraA = cashback counter
                        'ExtraA': account.cashback_counter_for_customer,
                    }
                )
            except Exception as err:
                logger.warning(
                    {
                        'action': 'get_payment_details_for_cootek_data',
                        'account_payment_id': account_payment.id,
                        'cootek_record_id': cootek_record.id,
                        'message': str(err),
                    }
                )
                continue

        return payment_details

    # STL/MTL Reminder
    if cootek_record.product in (CootekProductLineCodeName.STL, CootekProductLineCodeName.MTL):
        payments = []
        if cootek_record.from_previous_cootek_result:
            previous_cootek_results, payments = get_payment_with_specific_intention_from_cootek(
                cootek_record.tag_status, cootek_record.task_type, 'payment',
                cootek_record.product, cootek_record.time_to_start
            )

            if not payments and previous_cootek_results:
                return

        if not payments:
            payments = get_payment_details_for_cootek(
                cootek_record.called_at, experiment_setting, payment_filter,
                cootek_record.product)
            loan_id_filter = cootek_record.get_loan_id_filter()

            if payments and loan_id_filter:
                payments = payments.annotate(**loan_id_filter['annotate']) \
                    .filter(**loan_id_filter['filter']).values_list('id', flat=True)

        risk_payment_data = []
        if cootek_record.exclude_risky_customer:
            payments, risk_payment_data = PdCollectionModelResult.objects.filter_risky_payment_on_dpd_minus(payments)

        from juloserver.nexmo.tasks import store_risk_payment_data
        if not cootek_record.from_previous_cootek_result and risk_payment_data:
            store_risk_payment_data.delay(risk_payment_data)

        sent_payments = Payment.objects.filter(
            pk__in=payments,
            payment_status__lt=PaymentStatusCodes.PAID_ON_TIME)

        sent_payment_dicts = sent_payments.values(
            'id', 'due_date',
            'due_amount',
            'loan__cdate', 'loan__loan_status', 'loan__loan_amount',
            'loan__application__fullname', 'loan__application__mobile_phone_1',
            'loan__application__gender')
        payment_lookup = {payment.id: payment for payment in sent_payments}

        payment_details = [
            {
                'Debtor': payment['loan__application__fullname'],
                'Mobile': format_e164_indo_phone_number(str(payment['loan__application__mobile_phone_1'])),
                'LoanDate': (payment['loan__cdate']).strftime("%Y-%m-%d"),
                'DueDate': (payment['due_date']).strftime("%Y-%m-%d"),
                'LoanAmount': payment['loan__loan_amount'],
                # arrears can not be zero, zero means payment already paid_off
                'Arrears': payment['due_amount'],
                'Unit': CootekAIRobocall.UNIT_RUPIAH,
                'Platform': CootekAIRobocall.PLATFORM_JULO,
                'Comments': payment['id'],
                'Gender': convert_gender(payment['loan__application__gender'])
            }
            for payment in sent_payment_dicts
            if (
                payment['due_amount'] is not None
                and payment['due_amount'] > 0
                and payment['loan__application__mobile_phone_1']
                and not check_payment_is_blocked_comms(payment_lookup[payment['id']], 'cootek')
            )
        ]
        return payment_details

    # JTurbo reminder
    if cootek_record.is_julo_turbo_product:
        account_payments = []
        if cootek_record.is_unconnected_late_dpd:
            items = get_j1_turbo_late_dpd_account_payment_for_cootek(
                payment_filter, cootek_record, is_jturbo=True)
            account_payment_ids = [item.account_payment.id for item in items]
            account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids)
        else:
            if cootek_record.from_previous_cootek_result:
                """
                this still using J1 function, since already handle by 'cootek_record.product' parameter
                """
                previous_cootek_results, account_payments = \
                    get_payment_with_specific_intention_from_cootek(
                        cootek_record.tag_status, cootek_record.task_type, 'account_payment',
                        cootek_record.product, cootek_record.time_to_start
                    )

                if not account_payments and previous_cootek_results:
                    return

                account_payments = AccountPayment.objects.not_paid_active().filter(
                    id__in=account_payments
                ).get_julo_turbo_payments().exclude(
                    status__in=PaymentStatusCodes.paylater_paid_status_codes())

            if not account_payments:
                account_payments = get_jturbo_account_payment_for_cootek(
                    payment_filter
                ).exclude(status__in=PaymentStatusCodes.paylater_paid_status_codes())

            if cootek_record.exclude_risky_customer:
                account_payments = excluding_risky_account_payment_dpd_minus(account_payments)

            if cootek_record.exclude_autodebet:
                account_payments = excluding_autodebet_account_payment_dpd_minus(account_payments)

            if cootek_record.product == "JTurbo" and cootek_record.called_at in (0, -2, -1):
                account_payments = excluding_risky_account_payment_dpd_minus(account_payments)
                record_experiment_key = "{}_{}".format(RobocallType.COOTEK_JTURBO, cootek_record.id)
                account_payments = exclude_experiment_excellent_customer_from_robocall(
                    account_payments, record_type=record_experiment_key)
                record_customer_excellent_experiment.apply_async(
                    (record_experiment_key,), countdown=5)

            account_payments = account_payments.exclude(
                account__status_id=AccountConstant.STATUS_CODE.sold_off
            )

            # if omnichannel comms block activated exclude the user
            if is_comms_blocked_enabled:
                account_ids = get_credgenics_account_ids()
                account_payments = account_payments.exclude(account__in=list(account_ids))

            if omnichannel_comms_blocked.is_excluded:
                account_ids = get_exclusion_omnichannel_account_ids(
                    omnichannel_comms_blocked,
                )
                account_payments = account_payments.exclude(account__in=list(account_ids))

            # handle late fee earlier experiment
            account_payments = filtering_late_fee_earlier_experiment_for_cootek(
                cootek_record, account_payments)

        payment_details = []
        if not account_payments:
            return payment_details

        # exclude BTTC
        if cootek_record.called_at == 0:
            account_payments = exclude_bttc_t0_bucket_from_other_comms(account_payments)

        customer_ids = list(account_payments.values_list('account__customer__id', flat=True))
        customers = Customer.objects.filter(pk__in=customer_ids).only('fullname', 'phone')
        fs_detokenized = FeatureSetting.objects.filter(
            feature_name=MinisquadFeatureNameConst.DIALER_IN_BULK_DETOKENIZED_METHOD, is_active=True
        ).last()
        max_detokenized_row = 100
        if fs_detokenized:
            max_detokenized_row = fs_detokenized.parameters.get('detokenize_row', 100)
        # split data depend on how many fields we want to detokenized
        # "2" here is how may field we want to detokenized
        split_into = math.ceil((len(customers) * 2) / max_detokenized_row)
        divided_customers_per_batch = np.array_split(customers, split_into)
        detokenized_customers = dict()
        for customers_per_part in divided_customers_per_batch:
            detokenized_customers_per_part = (
                collection_detokenize_sync_primary_object_model_in_bulk(
                    PiiSource.CUSTOMER,
                    customers_per_part,
                    ['fullname', 'phone'],
                )
            )
            detokenized_customers.update(detokenized_customers_per_part)
        for account_payment in account_payments:
            try:
                if (
                    check_account_payment_is_blocked_comms(account_payment, 'cootek')
                    or account_payment.due_amount is None
                    or account_payment.due_amount <= 0
                ):
                    continue

                account = account_payment.account
                customer = account.customer
                customer_xid = customer.customer_xid
                application = account.application_set.filter(
                    workflow__name=WorkflowConst.JULO_STARTER
                ).last()
                customer_detokenized = detokenized_customers.get(customer_xid)
                mobile_phone_1 = getattr(customer_detokenized, 'phone', None) or customer.phone
                fullname = getattr(customer_detokenized, 'fullname', None) or customer.fullname
                if not mobile_phone_1:
                    logger.warning(
                        {
                            'message': 'There is no phone number for the application.',
                            'action': 'get_payment_details_for_cootek_data',
                            'application_id': application.id,
                            'account_payment_id': account_payment.id,
                            'cootek_record_id': cootek_record.id,
                            'customer_id': customer.id,
                        }
                    )
                    continue

                # not used anymore at JTURBO but the field is mandatory
                loan = account_payment.payment_set.order_by('cdate').last().loan
                payment_details.append(
                    {
                        'Debtor': fullname,
                        'Mobile': format_e164_indo_phone_number(str(mobile_phone_1)),
                        'LoanDate': loan.cdate.strftime("%Y-%m-%d"),
                        'DueDate': account_payment.due_date.strftime("%Y-%m-%d"),
                        'LoanAmount': loan.loan_amount,
                        # arrears can not be zero, zero means payment already paid_off
                        'Arrears': account_payment.due_amount,
                        'Unit': CootekAIRobocall.UNIT_RUPIAH,
                        'Platform': CootekAIRobocall.PLATFORM_JULO,
                        'Comments': account_payment.id,
                        'Gender': convert_gender(application.gender),
                    }
                )
            except Exception as err:
                logger.warning(
                    {
                        'action': 'get_payment_details_for_cootek_data',
                        'account_payment_id': account_payment.id,
                        'cootek_record_id': cootek_record.id,
                        'message': str(err),
                    }
                )
                continue

        return payment_details

    logger.error({
        'message': 'Unhandled cootek configuration',
        'module': 'cootek',
        'action': 'get_payment_details_for_cootek_data',
        'cootek_record_id': cootek_record.id,
        'experiment_setting': experiment_setting,
    })
    raise Exception('Unhandled cootek configuration configuration')


def get_details_task_from_cootek(cootek_record, start_time, retries_times=0, mock_url=None):
    is_bl_paylater = cootek_record.is_bl_paylater()
    is_julo_one_product = cootek_record.is_allowed_product
    experiment_setting = check_cootek_experiment(
        start_time, is_bl_paylater)
    if not experiment_setting and not is_julo_one_product \
            and not cootek_record.is_unconnected_late_dpd:
        return

    task_id = get_task_id_from_cootek(cootek_record.task_type, cootek_record.time_to_start)
    if not task_id:
        logger.info({
            'action': 'get_details_task_from_cootek',
            'message': 'cannot get task_id from db'
        })
        return

    cootek_client = get_julo_cootek_client()
    task_details = cootek_client.get_task_details(
        task_id, retries_times=retries_times, mock_url=mock_url)

    if not task_details:
        logger.info({
            'action': 'get_details_task_from_cootek',
            'message': 'cannot get task_details from db'
        })
        raise Exception('cannot get task_details from db for cootek config {}'.format(
            cootek_record.id))

    update_cootek_data(task_details, cootek_record.criteria, is_bl_paylater, is_julo_one_product)


# taskID to get detail of task from cootek
def get_task_id_from_cootek(task_type, time_to_start):
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)
    task = CootekRobocall.objects.filter(
        task_type=task_type,
        time_to_start=time_to_start,
        cdate__range=(today_min, today_max)
    ).last()

    if task:
        task_id = task.task_id
        return task_id

    logger.info({
        'action': 'get_task_id_from_cootek',
        'error': 'task_id is None'
    })
    return None


# to filter out customer with good intention
def get_payment_with_specific_intention_from_cootek(intention_filter, task_type, key_field,
                                                    product=None, time_to_start=None):
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)
    if time_to_start:
        time_to_start = add_minutes_to_datetime(time_to_start, -120)

    cootek_ids = CootekRobocall.objects.distinct(key_field)\
        .filter(task_type=task_type,
                cdate__range=(today_min, today_max),
                product=product)\
        .exclude(call_status__isnull=True)\
        .order_by(key_field, '-id').values_list('id', flat=True)
    result = CootekRobocall.objects.filter(
        time_to_start=time_to_start,
        id__in=cootek_ids, intention__in=intention_filter) \
        .values_list(key_field, flat=True) if cootek_ids else []

    return cootek_ids, result


def get_today_data_with_specific_cootek_intention(
    intention_list,
    task_type,
    key_field,
    product=None,
):
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)

    query = CootekRobocall.objects.distinct(key_field).filter(
        task_type=task_type,
        cdate__range=(today_min, today_max),
        intention__in=intention_list,
        call_status__isnull=False,
    )
    if product is not None:
        query = query.filter(product=product)

    return list(query.values_list(key_field, flat=True))


def get_loan_refinancing_offer_for_cootek(last_4_days):
    """get loan refinancing with status in approved + 4"""
    return LoanRefinancingOffer.objects.filter(
        loan_refinancing_request__status='Approved',
        offer_accepted_ts__date=last_4_days,
        is_accepted=True,
    ).distinct('loan_refinancing_request')


def insert_cootek_data(
        task_id, task_name, cootek_record, details, repeat_number):
    cootek_robocall_array = []
    called_at = cootek_record.called_at
    robot = cootek_record.cootek_robot

    if not robot:
        logger.info({
            'action': 'insert_cootek_data',
            'error': 'robot is None',
            'cootek_config_id': cootek_record.id
        })

    is_unconnected_late_dpd = cootek_record.criteria == CriteriaChoices.UNCONNECTED_LATE_DPD
    for detail in details:
        payment_id = None
        account_payment_id = None
        statement_id = None
        loan_status_code_id = None
        payment_status_code_id = None
        loan_refinancing_offer_id = None
        called_at_params = called_at
        if cootek_record.is_bl_paylater():
            statement_id = int(detail['Comments'])
            statement = Statement.objects.get(pk=statement_id)
            transaction_one = TransactionOne.objects.filter(statement=statement).last()
            loan_one = LoanOne.objects.filter(transaction=transaction_one).last()
            if loan_one:
                loan_status_code_id = loan_one.loan_one_status_id
            payment_status_code_id = statement.statement_status.status_code

            event_type = "bl_dpd_" + str(called_at)
            if 30 <= called_at <= 90:
                event_type = "bl_dpd30+"
            if called_at > 90:
                event_type = "bl_dpd_90"
            if called_at < 30:
                event_type = "bl_dpd"
            if called_at < 0:
                event_type = "bl_reminder"

        elif cootek_record.criteria == CriteriaChoices.REFINANCING_PENDING:
            event_type = 'loan_refinancing'
            loan_refinancing_offer_id = int(detail['Comments'])
        elif cootek_record.is_julo_one_product or is_unconnected_late_dpd \
                or cootek_record.is_allowed_product:
            account_payment_id = int(detail['Comments'])
            account_payment = AccountPayment.objects.filter(pk=account_payment_id).last()
            payment_status_code_id = account_payment.status_id
            event_type = "payment_reminder"
            if is_unconnected_late_dpd:
                called_at_params = account_payment.dpd
        else:
            payment_id = int(detail['Comments'])
            payment = Payment.objects.filter(pk=payment_id).values(
                'id', 'payment_status_id', 'loan__id',
                'loan__loan_status_id').last()
            loan_status_code_id = payment['loan__loan_status_id']
            payment_status_code_id = payment['payment_status_id']
            event_type = "payment_reminder"
        data = CootekRobocall(
            task_id=task_id,
            campaign_or_strategy=task_name,
            payment_id=payment_id,
            statement_id=statement_id,
            arrears=detail['Arrears'],
            loan_status_code_id=loan_status_code_id,
            payment_status_code_id=payment_status_code_id,
            cootek_event_type=event_type,
            call_to=detail['Mobile'],
            round=repeat_number,
            called_at=called_at_params,
            cootek_robot=robot,
            task_type=cootek_record.task_type,
            time_to_start=cootek_record.time_to_start,
            loan_refinancing_offer_id=loan_refinancing_offer_id,
            partner=cootek_record.partner,
            product=cootek_record.product,
            account_payment_id=account_payment_id,
            time_to_end=cootek_record.time_to_end,
        )

        logger.info(data)
        cootek_robocall_array.append(data)

    CootekRobocall.objects.bulk_create(cootek_robocall_array)


def update_cootek_data(
        task_details, criteria, is_bl_paylater=False,
        is_julo_one_product=False):
    task_id = task_details['TaskID']
    task_status = task_details['Status']
    is_late_dpd_configuration = criteria == CriteriaChoices.UNCONNECTED_LATE_DPD
    for detail in task_details['detail']:
        loan_status_code_id = None
        payment_status_code_id = None
        account = None
        account_payment = None
        if is_bl_paylater:
            statement_id = int(detail['Comments'])
            statement = Statement.objects.get(pk=statement_id)
            transaction_one = TransactionOne.objects.filter(statement=statement).last()
            loan_one = LoanOne.objects.filter(transaction=transaction_one).last()
            if loan_one:
                loan_status_code_id = loan_one.loan_one_status_id
            payment_status_code_id = statement.statement_status.status_code
            robocall = CootekRobocall.objects.filter(
                task_id=task_id,
                statement_id=statement_id).last()
        elif criteria == CriteriaChoices.REFINANCING_PENDING:
            loan_refinancing_offer_id = int(detail['Comments'])
            robocall = CootekRobocall.objects.filter(
                task_id=task_id,
                loan_refinancing_offer_id=loan_refinancing_offer_id).last()
        elif is_julo_one_product or is_late_dpd_configuration:
            account_payment_id = int(detail['Comments'])
            account_payment = AccountPayment.objects.filter(pk=account_payment_id).last()
            account = account_payment.account
            payment_status_code_id = account_payment.status_id
            robocall = CootekRobocall.objects.filter(
                task_id=task_id, account_payment_id=account_payment_id).last()
        else:
            payment_id = int(detail['Comments'])
            payment = Payment.objects.filter(pk=payment_id).values(
                'id', 'payment_status_id',
                'loan__id', 'loan__loan_status_id').last()
            loan_status_code_id = payment['loan__loan_status_id']
            payment_status_code_id = payment['payment_status_id']
            robocall = CootekRobocall.objects.filter(task_id=task_id, payment_id=payment_id).last()

        if robocall is None:
            continue

        call_status = detail['Status']
        if call_status == 'cancelled':
            duration = 0
        elif task_status == 'pending':
            duration = 0
        else:
            duration = (
                datetime.strptime(str(detail['CallEndTime']), "%Y-%m-%dT%H:%M:%SZ") -
                datetime.strptime(str(detail['CallStartTime']), "%Y-%m-%dT%H:%M:%SZ"))
            duration = duration.total_seconds()
        intention = detail['Intention']
        robocall.update_safely(
            task_status=task_status,
            loan_status_code_id=loan_status_code_id,
            payment_status_code_id=payment_status_code_id,
            ring_type=detail['RingType'],
            intention=intention,
            duration=duration,
            hang_type=detail['HangupType'],
            call_status=call_status,
            exact_robot_id=detail['RobotID'],
            multi_intention=detail.get('Multi_intention'),
        )
        called_at_param = robocall.called_at \
            if not is_late_dpd_configuration else account_payment.dpd

        vendor_data = dict(
            reminder_type="robocall",
            vendor="cootek",
            called_at=called_at_param,
            customer=None,
            loan=None,
            template_code=None,
            payment_status_code=None,
            loan_status_code=None,
            product=None
        )

        if is_bl_paylater:
            partner = Partner.objects.filter(name=PaylaterConst.PARTNER_NAME).last()
            update_vendor_data = dict(
                statement_id=statement_id,
                payment_status_code=payment_status_code_id,
                partner=partner,
                payment=None,
            )
        elif criteria == CriteriaChoices.REFINANCING_PENDING:
            update_vendor_data = dict()
            loan_refinancing_request = LoanRefinancingRequest.objects.get_or_none(
                pk=loan_refinancing_offer_id)
            if loan_refinancing_request:
                loan = loan_refinancing_request.loan
                application = loan.application
                payment = loan.payment_set.normal().not_paid_active()\
                    .order_by('payment_number').first()

                payment_status_code_id = None
                if payment:
                    payment_status_code_id = payment.payment_status_id

                update_vendor_data = dict(
                    customer=application.customer,
                    loan=loan,
                    loan_status_code=loan.loan_status_id,
                    payment=payment,
                    payment_status_code=payment_status_code_id,
                    partner=application.partner,
                    product=application.product_line
                )
        elif is_julo_one_product or is_late_dpd_configuration:
            application = account.application_set.last()
            update_vendor_data = dict(
                customer=application.customer,
                account_payment=account_payment,
                payment_status_code=payment_status_code_id,
                partner=None,
                product=application.product_line
            )
        else:
            loan = Loan.objects.get(pk=payment['loan__id'])
            application = loan.application
            update_vendor_data = dict(
                customer=application.customer,
                loan=loan,
                loan_status_code=loan_status_code_id,
                payment_id=payment_id,
                payment_status_code=payment_status_code_id,
                partner=application.partner,
                product=application.product_line
            )
        vendor_data.update(update_vendor_data)
        VendorDataHistory.objects.create(**vendor_data)
        if intention not in CootekAIRobocall.NOT_DELETE_INTELIX_QUEUE_INTENTION \
                and is_late_dpd_configuration:
            delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(
                account_payment.id
            )
            delete_paid_payment_from_dialer.delay(account_payment.id)


def get_payment_details_cootek_for_centerix(dpd):
    intention_filter = ['B', 'E', 'F', 'G', 'H', 'I']
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)

    cootek_ids = CootekRobocall.objects.distinct('payment') \
        .filter(called_at=dpd, cdate__range=(today_min, today_max)) \
        .exclude(call_status='cancelled') \
        .exclude(call_status__isnull=True) \
        .order_by('payment', '-id').values_list('id', flat=True)

    return CootekRobocall.objects.filter(
        id__in=cootek_ids, intention__in=intention_filter) \
        .values_list('payment', flat=True) if cootek_ids else []


def upload_payment_details(data, campaign):
    # if data:
    #     params_list = []
    #     for item in data:
    #         payment = Payment.objects.get(pk=item)
    #         params = get_upload_centerix_data_params(payment)
    #         params_list.append(params)
    #
    #     centerix_client = get_julo_centerix_client()
    #     response = centerix_client.upload_centerix_data(campaign, params_list)
    #     return response
    # else:
    return 'No data to upload to centerix'


def get_payment_details_cootek_for_intelix(
        dpd, loan_ids=None, for_intelix=False, is_jturbo=False):
    # all intension we have, especially for T0
    # ['A', 'B', 'C', 'D' , 'E', 'F', 'G', 'H' , 'I', '--']
    intention_filter = ['B', 'E', 'F', 'G', 'H', 'I']
    if dpd == 0 and for_intelix:
        intention_filter.append('--')
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)
    loan_id_filter = {}
    if loan_ids:
        loan_id_filter = {'campaign_or_strategy__contains': loan_ids}

    product_exclude = [CootekProductLineCodeName.DANA, CootekProductLineCodeName.JTURBO]
    if is_jturbo:
        product_exclude = [CootekProductLineCodeName.DANA, CootekProductLineCodeName.J1]

    account_payment_cootek_ids = CootekRobocall.objects.distinct('account_payment'
    ).filter(
        called_at=dpd,
        cdate__range=(today_min, today_max),
        payment_id__isnull=True,
        **loan_id_filter
    ).exclude(call_status='cancelled'
    ).exclude(call_status__isnull=True
    ).exclude(product__in=product_exclude
    ).order_by('account_payment', '-id'
    ).values_list('id', flat=True)

    if dpd == 0 and for_intelix:
        account_payment_level_cootek_robocalls = CootekRobocall.objects.filter(
            id__in=account_payment_cootek_ids
        ).filter(Q(intention__in=intention_filter) | Q(intention__isnull=True))
    else:
        account_payment_level_cootek_robocalls = CootekRobocall.objects.filter(
            id__in=account_payment_cootek_ids, intention__in=intention_filter
        )
    not_sent_payment_level_cootek_robocalls = []
    not_sent_account_payment_level_cootek_robocalls = []
    if for_intelix:
        not_sent_account_payment_level_cootek_robocalls = CootekRobocall.objects.filter(
            id__in=account_payment_cootek_ids,
        ).exclude(intention__in=intention_filter).exclude(account_payment__due_amount=0).exclude(
            id__in=account_payment_level_cootek_robocalls.values_list('id', flat=True)
        ).extra(
            select={'reason': ReasonNotSentToDialer.UNSENT_REASON['T0_CRITERIA_COOTEK_CALLING']}
        ).values("account_payment_id", "reason")

    payments = []
    account_payments = []
    account_payment_ids = []
    if account_payment_level_cootek_robocalls:
        for cootek in account_payment_level_cootek_robocalls:
            account_payments.append(cootek.account_payment)
            account_payment_ids.append(cootek.account_payment.id)
    if for_intelix:
        if dpd == 0:
            account_payment_ids = merge_cootek_robocall_data_and_oldest_t0(account_payment_ids, is_jturbo=is_jturbo)
        filter_paid_account_payments = AccountPayment.objects.filter(
            pk__in=account_payment_ids).exclude(due_amount=0)
        account_payment_ids = list(filter_paid_account_payments.values_list('id', flat=True))
        account_payments = list(filter_paid_account_payments)
        # autodebet customer exclude from intelix call for dpd zero
        exclude_autodebet_turned_on = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            is_active=True
        )
        if exclude_autodebet_turned_on:
            # validation for check parameter dpd zero is active
            if exclude_autodebet_turned_on.parameters.get('dpd_zero'):
                base_account_payments = AccountPayment.objects.filter(
                    pk__in=account_payment_ids
                )
                excluded_autodebet_customers = base_account_payments.filter(
                    Q(account__autodebetaccount__is_use_autodebet=True) &
                    Q(account__autodebetaccount__is_deleted_autodebet=False)
                )
                if excluded_autodebet_customers:
                    base_account_payments = base_account_payments.exclude(
                        pk__in=excluded_autodebet_customers
                    )
                    account_payments = list(base_account_payments)
                    excluded_autodebet_customers = list(excluded_autodebet_customers.extra(
                        select={'reason': ReasonNotSentToDialer.UNSENT_REASON['EXCLUDED_DUE_TO_AUTODEBET']}
                    ).values("id", "reason"))

                    not_sent_account_payment_level_cootek_robocalls = \
                        list(not_sent_account_payment_level_cootek_robocalls) + excluded_autodebet_customers

        return payments, account_payments, list(not_sent_payment_level_cootek_robocalls),\
               list(not_sent_account_payment_level_cootek_robocalls)

    return payments, account_payments


def get_payment_details_for_intelix(dpd, loan_ids):
    today = timezone.localtime(timezone.now()).date()
    cootek_record = CootekConfiguration.objects.filter(
        called_at=dpd,
        strategy_name__contains=loan_ids).last()
    experiment_setting = check_cootek_experiment(today, cootek_record.is_bl_paylater())
    dpd_config = experiment_setting.criteria.get('dpd') if experiment_setting.criteria else None
    payment_filter = cootek_record.get_payment_filter(dpd_config)
    payments = get_payment_details_for_cootek(
        dpd, experiment_setting,
        payment_filter, cootek_record.product)
    loan_id_filter = cootek_record.get_loan_id_filter()
    if payments and loan_id_filter:
        payments = payments.annotate(**loan_id_filter['annotate']) \
            .filter(**loan_id_filter['filter']).values_list('id', flat=True)
    return Payment.objects.filter(id__in=payments)


def get_j1_account_payment_for_cootek(account_payment_filter):
    oldest_account_payment_ids = (AccountPayment.objects.oldest_account_payment()
                                  .exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
                                  .values_list('id', flat=True))
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM,
        is_active=True
    ).last()
    exclude_partner_end = dict()
    if feature_setting:
        partner_blacklist_config = feature_setting.parameters
        partner_config_end = []
        for key, value in partner_blacklist_config.items():
            if value != 'end':
                continue
            partner_config_end.append(key)
        if partner_config_end:
            exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

    query_set = (
        AccountPayment.objects.not_paid_active()
        .get_julo_one_payments()
        .exclude(**exclude_partner_end)
    )

    account_payments = query_set\
        .filter(**account_payment_filter)\
        .filter(pk__in=oldest_account_payment_ids)
    return account_payments


def get_j1_turbo_late_dpd_account_payment_for_cootek(
        account_payment_filter, cootek_record, is_jturbo=False
):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COOTEK_LATE_DPD_SETTING,
        is_active=True
    ).last()

    if not feature_setting:
        return []

    date_today = timezone.localtime(timezone.now())
    today_min = datetime.combine(date_today, time.min)
    today_max = datetime.combine(date_today, time.max)
    today_min_utc = timezone.make_aware(today_min, timezone.get_current_timezone()).astimezone(
        timezone.utc
    )
    exclude_account_payments = []
    account_tail_ids = []

    if cootek_record.unconnected_late_dpd_time == 'evening':
        account_payment_from_cootek_robocall = (
            CootekRobocall.objects.filter(**account_payment_filter)
            .filter(
                intention__in=['A', 'C'],
                cdate__range=(today_min, today_max),
                partner_id__isnull=True,
            )
            .distinct('account_payment_id')
            .values_list('account_payment', flat=True)
        )

        exclude_account_payments.extend(account_payment_from_cootek_robocall)

        for account_payment_id in account_payment_from_cootek_robocall:
            # still can using j1 function, since only delete queue for intelix
            delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(account_payment_id)
            delete_paid_payment_from_dialer.delay(account_payment_id)

    excluded_call_status_ids = (
        SkiptraceResultChoice.objects.excluded_from_late_dpd_experiment_result_choice_ids()
    )

    exclude_account_payment_from_skiptrace_history = (
        SkiptraceHistory.objects.filter(**account_payment_filter)
        .filter(cdate__gte=today_min_utc, account__isnull=False)
        .filter(account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
        .filter(call_result_id__in=excluded_call_status_ids)
        .distinct('account_payment_id')
        .values_list('account_payment', flat=True)
    )

    exclude_account_payments.extend(exclude_account_payment_from_skiptrace_history)

    if cootek_record.is_exclude_b3_vendor and cootek_record.is_bucket_3_unconnected_late_dpd:
        exclude_b3_vendor_account_payments = (
            NotSentToDialer.objects.filter(
                cdate__gte=today_min_utc,
                unsent_reason='sending b3 to vendor',
                account_payment__isnull=False,
            )
            .distinct('account_payment_id')
            .values_list('account_payment', flat=True)
        )

        exclude_account_payments.extend(exclude_b3_vendor_account_payments)

    cootek_control_group = cootek_record.cootek_control_group
    if cootek_control_group and cootek_record.is_unconnected_late_dpd:
        account_tail_ids = cootek_control_group.account_tail_ids

    workflow = WorkflowConst.JULO_ONE
    if is_jturbo:
        workflow = WorkflowConst.JULO_STARTER

    return (
        SentToDialer.objects.filter(**account_payment_filter)
        .filter(
            cdate__gte=today_min_utc,
            account__isnull=False,
        )
        .filter(account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME)
        .filter(account_payment__account__account_lookup__workflow__name=workflow)
        .annotate(last_digit_account_id=F('account_id') % 10)
        .exclude(last_digit_account_id__in=account_tail_ids)
        .exclude(account_payment__in=exclude_account_payments)
        .exclude(
            account_payment__account__application__product_line_id__in=[ProductLineCodes.EFISHERY]
        )
        .exclude(account__ever_entered_B5=True)
        .exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
        .exclude(
            bucket__in=(
                IntelixTeam.DANA_B1,
                IntelixTeam.DANA_B2,
                IntelixTeam.DANA_B3,
                IntelixTeam.DANA_B4,
                IntelixTeam.DANA_B5,
                IntelixTeam.DANA_T0,
            )
        )
        .distinct('account_payment_id')
        .select_related('account_payment')
    )


def get_dana_account_payment_for_cootek(account_payment_filter):
    account_payments = AccountPayment.objects.filter(
        pk__in=get_dana_oldest_unpaid_account_payment_ids()).not_paid_active().filter(
        **account_payment_filter)
    return account_payments


def merge_cootek_robocall_data_and_oldest_t0(account_payment_cobocall_ids, is_jturbo=False):
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)
    filter_dict = dict(due_date=today)
    account_payments_oldest_t0 = get_j1_account_payment_for_cootek(filter_dict)
    if is_jturbo:
        account_payments_oldest_t0 = get_jturbo_account_payment_for_cootek(filter_dict)
    account_payments_oldest_t0_ids = list(account_payments_oldest_t0.values_list('id', flat=True))
    account_payment_exclude_intention_ids = CootekRobocall.objects.filter(
        account_payment__in=account_payments_oldest_t0_ids, intention__in=['A', 'C', 'D'],
        cdate__range=(today_min, today_max)
    ).values_list('account_payment_id', flat=True)
    account_payments_oldest_t0_ids = list(
        account_payments_oldest_t0.exclude(pk__in=account_payment_exclude_intention_ids).values_list('id', flat=True))
    merge_account_payment_robocall_and_oldest_t0 = list(set(account_payment_cobocall_ids + account_payments_oldest_t0_ids))

    return merge_account_payment_robocall_and_oldest_t0


def process_upload_j1_jturbo_t0_to_intelix(
        bucket_name, dialer_type, function_str, split_threshold, is_jturbo=False):
    from juloserver.cootek.tasks import upload_jturbo_t0_cootek_data_to_intelix

    task_list = []
    try:
        dialer_task = DialerTask.objects.create(type=dialer_type)
        create_history_dialer_task_event(dict(dialer_task=dialer_task))

        payments, account_payments, _, not_sent_account_payments = \
            get_payment_details_cootek_for_intelix(dpd=0, for_intelix=True, is_jturbo=is_jturbo)
        account_payments, not_sent_account_payments = filter_intelix_blacklist_for_t0(
            account_payments, not_sent_account_payments)
        data_count = len(payments) + len(account_payments)
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.QUERIED,
            data_count=data_count
        ))
        if not_sent_account_payments:
            redis_key = RedisKey.NOT_SENT_DIALER_JULO_T0 if not is_jturbo else RedisKey.NOT_SENT_DIALER_JTURBO_T0
            set_redis_data_temp_table(
                redis_key,
                not_sent_account_payments,
                timedelta(hours=5),
                operating_param='set',
            )
            record_not_sent_to_intelix_task.delay(
                redis_key, dialer_task.id, bucket_name, is_julo_one=True
            )

        if data_count == 0:
            logger.error({
                "action": function_str,
                "error": "error upload t0 data to intelix because data is not exist"
            })
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task,
                    status=DialerTaskStatus.FAILURE,
                ),
                error_message='data for upload to intelix not exist'
            )
            if not is_jturbo:
                upload_jturbo_t0_cootek_data_to_intelix.delay()
            return

        # process to split data base on feature setting
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESS
            )
        )

        account_payment_ids = [account_payment.id for account_payment in account_payments]
        split_into = math.ceil(data_count / split_threshold)
        divided_account_payment_ids_per_batch = np.array_split(
            account_payment_ids, split_into
        )
        total_batch = len(divided_account_payment_ids_per_batch)
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.BATCHING_PROCESSED,
                data_count=split_into
            )
        )

        # construct for intelix
        for index in range(total_batch):
            account_payments_batch = AccountPayment.objects.filter(
                id__in=divided_account_payment_ids_per_batch[index]
            )
            page = index + 1
            data = construct_data_for_intelix(payments, account_payments_batch, bucket_name)
            if not data:
                create_history_dialer_task_event(
                    dict(
                        dialer_task=dialer_task,
                        status=DialerTaskStatus.FAILURE_BATCH.format(page),
                        data_count=len(data),
                    ),
                    error_message="dont have any data after construction",
                )
                if not is_jturbo:
                    upload_jturbo_t0_cootek_data_to_intelix.delay()
                return
            set_redis_data_temp_table(
                RedisKey.CONSTRUCTED_DATA_BATCH_FOR_SEND_TO_INTELIX.format(bucket_name, page),
                data,
                timedelta(hours=15),
                operating_param='set',
            )
            create_history_dialer_task_event(
                dict(
                    dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED_BATCH.format(page)
                )
            )

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.CONSTRUCTED)
        )
        # record to sent to dialer
        record_intelix_log_for_j1(account_payments, bucket_name, dialer_task)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.STORED, data_count=data_count)
        )
        # sent data to intelix
        for batch_number in range(1, total_batch + 1):
            is_last=False
            if bucket_name == IntelixTeam.JULO_T0 and batch_number == total_batch:
                is_last=True
            task_list.append(
                send_data_to_intelix_with_retries_mechanism.si(
                    dialer_task_id=dialer_task.id,
                    bucket_name=bucket_name,
                    page_number=batch_number,
                    is_last=is_last
                )
            )

        # trigger chain sent data to intelix
        task_list = tuple(task_list)
        chain(task_list).apply_async()
        logger.info({
            "action": function_str,
            "info": "task finish"
        })
    except Exception as e:
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE,
            ),
            error_message=str(e)
        )
        get_julo_sentry_client().captureException()
        if not is_jturbo:
            upload_jturbo_t0_cootek_data_to_intelix.delay()


def get_jturbo_account_payment_for_cootek(account_payment_filter):
    oldest_account_payment_ids = (AccountPayment.objects.oldest_account_payment()
                                  .exclude(account__status_id=AccountConstant.STATUS_CODE.sold_off)
                                  .values_list('id', flat=True))
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DIALER_PARTNER_DISTRIBUTION_SYSTEM,
        is_active=True
    ).last()
    exclude_partner_end = dict()
    if feature_setting:
        partner_blacklist_config = feature_setting.parameters
        partner_config_end = []
        for key, value in partner_blacklist_config.items():
            if value != 'end':
                continue
            partner_config_end.append(key)
        if partner_config_end:
            exclude_partner_end = dict(account__application__partner_id__in=partner_config_end)

    query_set = AccountPayment.objects\
        .not_paid_active()\
        .get_julo_turbo_payments()\
        .exclude(**exclude_partner_end)

    account_payments = query_set\
        .filter(**account_payment_filter)\
        .filter(pk__in=oldest_account_payment_ids)

    return account_payments


def filtering_late_fee_earlier_experiment_for_cootek(cootek_record, account_payments):
    late_fee_experiment = get_experiment_setting_by_code(
        MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT)
    is_cootek_late_fee = True if cootek_record.criteria and \
        cootek_record.criteria.lower() == CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT \
            else False

    if not late_fee_experiment and not is_cootek_late_fee:
        return account_payments

    if late_fee_experiment and is_cootek_late_fee:
        # will sent account_payment registered on experiment_group
        account_ids = list(ExperimentGroup.objects.filter(
            experiment_setting=late_fee_experiment.id,
            group='experiment').values_list('account_id', flat=True))
        account_payments = account_payments.filter(account__in=account_ids)
        return account_payments

    if not late_fee_experiment and is_cootek_late_fee:
        # experiment inactive and cootek config is for late fee
        # need return none object so account_payment will not sent to cootek
        return AccountPayment.objects.none()

    if late_fee_experiment and not is_cootek_late_fee:
        # will exclude account_payment registred on experiment_group
        account_ids = list(ExperimentGroup.objects.filter(
            experiment_setting=late_fee_experiment.id,
            group='experiment').values_list('account_id', flat=True))
        account_payments = account_payments.exclude(account__in=account_ids)
        return account_payments


def filtering_cashback_new_scheme_experiment_for_cootek(cootek_record, account_payments):
    cashback_new_scheme_experiment_id = get_experiment_setting_data_on_growthbook(
        MinisquadExperimentConstants.CASHBACK_NEW_SCHEME
    )
    is_cootek_cashback_new_scheme = True if cootek_record.criteria and \
        cootek_record.criteria.lower() == CriteriaChoices.CASHBACK_NEW_SCHEME \
            else False

    if not cashback_new_scheme_experiment_id and not is_cootek_cashback_new_scheme:
        return account_payments

    if cashback_new_scheme_experiment_id and is_cootek_cashback_new_scheme:
        # will sent account_payment registered on experiment_group
        account_ids = list(ExperimentGroup.objects.filter(
            experiment_setting=cashback_new_scheme_experiment_id,
            group='experiment').values_list('account_id', flat=True))
        account_payments = account_payments.filter(account__in=account_ids)
        return account_payments

    if not cashback_new_scheme_experiment_id and is_cootek_cashback_new_scheme:
        # experiment inactive and cootek config is for late fee
        # need return none object so account_payment will not sent to cootek
        return AccountPayment.objects.none()

    if cashback_new_scheme_experiment_id and not is_cootek_cashback_new_scheme:
        # will exclude account_payment registred on experiment_group
        account_ids = list(ExperimentGroup.objects.filter(
            experiment_setting=cashback_new_scheme_experiment_id,
            group='experiment').values_list('account_id', flat=True))
        account_payments = account_payments.exclude(account__in=account_ids)
        return account_payments


def get_good_intention_from_cootek(
        dpd, account_payment_ids):
    # all intension we have, especially for T0
    # ['A', 'B', 'C', 'D' , 'E', 'F', 'G', 'H' , 'I', '--']
    bad_intention_filter = eval('CootekAIRobocall.DPD_{}'.format(dpd))
    today = timezone.localtime(timezone.now())
    today_min = datetime.combine(today, time.min)
    today_max = datetime.combine(today, time.max)

    cootek_account_ids = CootekRobocall.objects.filter(
        called_at=dpd,
        cdate__range=(today_min, today_max),
        payment_id__isnull=True,
        account_payment__in=account_payment_ids
    ).exclude(call_status='cancelled'
    ).exclude(call_status__isnull=True
    ).exclude(intention__in=bad_intention_filter
    ).exclude(intention__isnull=True
    ).order_by('account_payment', '-id'
    ).values_list('account_payment__account_id', flat=True)

    return cootek_account_ids


def filter_julo_gold(cootek_configuration: CootekConfiguration, account_payments):
    if not cootek_configuration.is_bucket_0():
        return account_payments

    now = timezone.localtime(timezone.now()).date()
    qs = PdCustomerSegmentModelResult.objects.extra(
        where=["customer_segment ILIKE %s"], params=["%julogold%"]
    )
    customer_ids = list(qs.filter(partition_date=now).values_list("customer_id", flat=True))

    if len(customer_ids) == 0:
        customer_ids = list(
            qs.filter(partition_date=(now - timedelta(days=1))).values_list(
                "customer_id", flat=True
            )
        )

    if cootek_configuration.julo_gold == JuloGoldFilter.EXCLUDE.value:
        action = "exclude"
    elif cootek_configuration.julo_gold == JuloGoldFilter.ONLY.value:
        action = "filter"
    else:
        raise ValueError("Julo Gold value is not expected.")

    account_payments = getattr(account_payments, action)(account__customer_id__in=customer_ids)

    return account_payments

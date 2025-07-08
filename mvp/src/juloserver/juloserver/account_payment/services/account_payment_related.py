import logging
from dateutil.relativedelta import relativedelta
from typing import Union

from django.db.models import (
    Sum,
    Q,
    F,
)
from django.utils import timezone
from datetime import timedelta
from django.db import transaction

from juloserver.account_payment.models import (
    AccountPayment,
    CheckoutRequest,
    CRMCustomerDetail,
    LateFeeBlock,
    CashbackClaimPayment,
)
from juloserver.apiv2.models import SdDeviceApp
from juloserver.cashback.models import CashbackEarned
from juloserver.julo.banks import BankCodes
from juloserver.julo.constants import (
    FeatureNameConst,
    ExperimentConst,
    CheckoutExperienceExperimentGroup,
    NewCashbackConst,
)
from juloserver.julo.models import (
    Image,
    Loan,
    Payment,
    PaymentEvent,
    SepulsaTransaction,
    FeatureSetting,
    PaymentMethodLookup,
    ExperimentSetting,
    LoanHistory,
    PTP,
    CashbackCounterHistory,
    StatusLookup,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.services2.payment_event import PaymentEventServices
from juloserver.julo.utils import display_rupiah
from juloserver.minisquad.models import NotSentToDialer
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.account.models import Account, AccountTransaction, ExperimentGroup
from juloserver.account.constants import (
    VoidTransactionType,
    LDDEReasonConst,
    AccountConstant,
    CheckoutPaymentType,
)
from juloserver.payment_point.models import Vendor, SpendTransaction
from django.contrib.contenttypes.models import ContentType
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.services.loan_related import compute_first_payment_installment_julo_one
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.account_payment.utils import (
    generate_checkout_xid,
    get_expired_date_checkout_request,
)
from juloserver.account_payment.constants import (
    CheckoutRequestCons,
    LateFeeBlockReason,
    CashbackClaimConst,
)
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.autodebet.services.account_services import update_deduction_fields_to_new_cycle_day
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.account_payment.models import RepaymentRecallLog
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.account_payment.services.earning_cashback import (
    get_paramters_cashback_new_scheme,
)
from juloserver.account.services.account_related import (
    get_experiment_group_data,
    create_account_cycle_day_history,
)
from juloserver.account_payment.services.collection_related import (
    get_cashback_claim_experiment,
)
from juloserver.payback.services.waiver import automate_late_fee_waiver
from juloserver.julocore.python2.utils import py2round
from juloserver.julo.models import (
    PaymentMethod,
    PaybackTransaction,
)
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.portal.core.templatetags.unit import format_rupiahs

logger = logging.getLogger(__name__)


def get_image_by_account_payment_id(account_payment_id):
    image = Image.objects.filter(
        image_source=account_payment_id,
        image_type=ImageUploadType.LATEST_PAYMENT_PROOF,
        image_status=0,
    ).last()

    return image


def construct_loan_in_account_payment_list(account_payment_id, paid_off):
    payment_query_set = Payment.objects.filter(
        account_payment_id=account_payment_id)
    if paid_off:
        payment_query_set = payment_query_set.paid()
    else:
        payment_query_set = payment_query_set.not_paid()

    loan_ids = payment_query_set.values_list(
        'loan', flat=True).distinct('loan_id')
    last_payments = Payment.objects.select_related('loan').only(
        'id', 'payment_number', 'installment_principal', 'installment_interest', 'paid_amount',
        'late_fee_amount', 'due_date', 'paid_date', 'payment_status_id', 'account_payment_id',
        'due_amount', 'loan_id', 'loan__fund_transfer_ts', 'loan__loan_xid', 'loan__loan_amount',
        'loan__loan_status_id',
    ).filter(
        loan_id__in=loan_ids, payment_number=F('loan__loan_duration')
    ).order_by('loan_id', 'payment_number')
    current_payments = Payment.objects.select_related('loan').filter(
        loan_id__in=loan_ids, account_payment_id=account_payment_id
    ).order_by('loan_id', 'payment_number').values(
        'id', 'payment_number', 'installment_principal', 'installment_interest', 'paid_amount',
        'late_fee_amount', 'due_date', 'paid_date', 'payment_status_id', 'account_payment_id',
        'due_amount', 'loan_id',
    )
    loan_data = []
    for last_payment in last_payments.iterator():
        disbursement_date = timezone.localtime(
            last_payment.loan.fund_transfer_ts)
        current_payment = next(
            filter(
                lambda item: item.get(
                    'account_payment_id') == account_payment_id
                and item.get('loan_id') == last_payment.loan_id, current_payments
            ), None
        )
        if not current_payment:
            current_payment = last_payment.__dict__
        installment_number = '{}/{}'.format(
            current_payment['payment_number'], last_payment.payment_number
        )
        installment_amount = (
            current_payment['installment_principal']
            + current_payment['installment_interest']
            + current_payment['late_fee_amount']
        )
        loan_data.append(
            {
                "loan_xid": last_payment.loan.loan_xid,
                "loan_amount": last_payment.loan.loan_amount,
                "installment_amount": installment_amount,
                "disbursement_date": disbursement_date,
                "loan_status": last_payment.loan.loan_status_label_julo_one.lower().capitalize(),
                "total_paid_installment": current_payment['paid_amount'],
                "remaining_installment_amount": current_payment['due_amount'],
                "installment_number": installment_number,
                "payment_status": get_payment_status(
                    current_payment['payment_status_id'], current_payment['due_date'],
                    current_payment['paid_date']
                ),
            }
        )

    return loan_data


def construct_loan_in_account_payment_listv2(account_payment_id, paid_off):
    payment_query_set = Payment.objects.filter(account_payment_id=account_payment_id)
    if paid_off:
        payment_query_set = payment_query_set.paid()
    else:
        payment_query_set = payment_query_set.not_paid()

    loan_ids = payment_query_set.values_list('loan', flat=True).distinct('loan_id')
    last_payments = (
        Payment.objects.select_related('loan')
        .only(
            'id',
            'payment_number',
            'installment_principal',
            'installment_interest',
            'paid_amount',
            'late_fee_amount',
            'due_date',
            'paid_date',
            'payment_status_id',
            'account_payment_id',
            'due_amount',
            'loan_id',
            'loan__fund_transfer_ts',
            'loan__loan_xid',
            'loan__loan_amount',
            'loan__loan_status_id',
        )
        .filter(loan_id__in=loan_ids, payment_number=F('loan__loan_duration'))
        .order_by('loan_id', 'payment_number')
    )
    current_payments = (
        Payment.objects.select_related('loan')
        .filter(loan_id__in=loan_ids, account_payment_id=account_payment_id)
        .order_by('loan_id', 'payment_number')
        .values(
            'id',
            'payment_number',
            'installment_principal',
            'installment_interest',
            'paid_amount',
            'late_fee_amount',
            'due_date',
            'paid_date',
            'payment_status_id',
            'account_payment_id',
            'due_amount',
            'loan_id',
        )
    )
    loan_data = []
    for last_payment in last_payments.iterator():
        disbursement_date = timezone.localtime(last_payment.loan.fund_transfer_ts)
        current_payment = next(
            filter(
                lambda item: item.get('account_payment_id') == account_payment_id
                and item.get('loan_id') == last_payment.loan_id,
                current_payments,
            ),
            None,
        )
        if not current_payment:
            current_payment = last_payment.__dict__
        installment_number = '{}/{}'.format(
            current_payment['payment_number'], last_payment.payment_number
        )
        transaction_method = last_payment.loan.transaction_method
        loan_data.append(
            {
                "loan_xid": last_payment.loan.loan_xid,
                "loan_amount": last_payment.loan.loan_amount,
                "payment_amount": current_payment['due_amount'],
                "name": transaction_method.fe_display_name if transaction_method else "",
                "icon_url": transaction_method.foreground_icon_url if transaction_method else "",
                "installment_number": installment_number,
                "disbursement_date": disbursement_date,
            }
        )

    return loan_data


def get_unpaid_account_payment(account_id):
    qs = AccountPayment.objects.filter(account_id=account_id)
    return qs.not_paid_active().order_by('due_date')


def is_account_loan_paid_off(account):
    unpaid_loans = account.loan_set.filter(
        loan_status_id__lt=LoanStatusCodes.PAID_OFF,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
    )
    if unpaid_loans:
        return False

    return True


def get_account_payment_events_transaction_level(account_payment, user, user_groups):
    list_detail = {'payment_events': [],
                   'dropdown_event': [], 'status_event': False}
    account_transaction_ids = account_payment.account.accounttransaction_set.all().values_list(
        'id', flat=True
    )
    payment_events = (
        PaymentEvent.objects.select_related(
            'account_transaction', 'payment_method')
        .filter(
            payment__account_payment=account_payment,
            account_transaction_id__in=account_transaction_ids,
        )
        .order_by('-account_transaction_id', '-id')
        .distinct('account_transaction_id')
    )

    payments = list(account_payment.payment_set.all())

    payment_event_service = PaymentEventServices()
    list_detail['payment_events'] = payment_event_service.get_status_reverse(
        payment_events, user_groups
    )
    list_detail['dropdown_event'] = payment_event_service.get_dropdown_event(
        user_groups, payment=payments
    )

    # override dropdown since the only functional is payment event
    if list_detail['dropdown_event']:
        list_detail['dropdown_event'] = [
            {'value': 'payment', 'desc': 'Payment'}]

    list_detail['status_event'] = payment_event_service.get_status_event(
        payment_events, user, user_groups
    )
    return list_detail


def void_ppob_transaction(loan):
    payments = (
        loan.payment_set.normal()
        .filter(payment_status__lt=PaymentStatusCodes.PAID_ON_TIME, is_restructured=False)
        .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.grab())
        .order_by('payment_number')
    )
    transaction_amount = loan.loan_amount
    with transaction.atomic():
        for payment in payments:
            account_payment = (
                AccountPayment.objects.select_for_update()
                .filter(account=loan.account, id=payment.account_payment_id)
                .last()
            )
            due_amount_after_void = account_payment.due_amount - payment.due_amount
            payment.update_safely(account_payment=None)

            account_payment.update_safely(
                due_amount=due_amount_after_void,
                principal_amount=account_payment.principal_amount - payment.installment_principal,
                interest_amount=account_payment.interest_amount - payment.installment_interest,
            )
            if due_amount_after_void == 0:
                last_history = account_payment.accountpaymentstatushistory_set.last()
                if last_history:
                    history_data = {
                        'status_old': account_payment.status,
                        'change_reason': 'Transaction Failed',
                    }
                    account_payment.change_status(last_history.status_old_id)
                    account_payment.save(update_fields=['status'])
                    account_payment.create_account_payment_status_history(
                        history_data)

        sepulsa_transaction = SepulsaTransaction.objects.filter(
            loan=loan).last()
        vendor = Vendor.objects.filter(
            vendor_name=PartnerConstant.SEPULSA_PARTNER).last()
        spend_transaction = SpendTransaction.objects.filter(
            spend_product_id=sepulsa_transaction.id,
            spend_product_content_type=ContentType.objects.get_for_model(
                sepulsa_transaction).id,
            vendor=vendor,
        ).last()
        AccountTransaction.objects.create(
            account=loan.account,
            payback_transaction=None,
            disbursement_id=loan.disbursement_id,
            transaction_date=loan.fund_transfer_ts,
            transaction_amount=transaction_amount,
            transaction_type=VoidTransactionType.PPOB_VOID,
            towards_principal=transaction_amount,
            towards_interest=0,
            towards_latefee=0,
            spend_transaction=spend_transaction,
            can_reverse=False,
        )


def update_payment_installment(account_payment, new_due_date, simulate=False):
    payments = account_payment.payment_set.all()
    new_due_amount_payment, new_interest, new_due_amount_account_payment = 0, 0, 0
    for idx, payment in enumerate(payments):
        paid_installments = payment.loan.payment_set.all().paid()
        if paid_installments:
            latest_paid = paid_installments.order_by('-due_date').first()
            payment_start = latest_paid.due_date
        elif payment.loan.sphp_sent_ts:
            payment_start = payment.loan.sphp_sent_ts.date()
        else:
            payment_start = timezone.localtime(timezone.now()).date()

        principal = payment.installment_principal
        interest = payment.installment_principal

        if not payment.is_paid:
            (
                new_principal,
                new_interest,
                new_installment,
            ) = compute_first_payment_installment_julo_one(
                payment.loan.loan_amount,
                payment.loan.loan_duration,
                payment.loan.interest_rate_monthly,
                payment_start,
                new_due_date,
            )
            new_due_amount_payment = new_installment - \
                payment.paid_amount + payment.late_fee_amount
            principal = new_principal
            interest = new_interest

            new_due_amount_account_payment += new_due_amount_payment

        if not simulate:
            with transaction.atomic():
                orig_due_amount = payment.due_amount
                if not payment.is_paid:
                    payment.due_amount = new_due_amount_payment
                    payment.installment_interest = new_interest
                    payment.save(update_fields=[
                                 'due_amount', 'installment_interest', 'udate'])
                    change_amount = orig_due_amount - payment.due_amount

                    PaymentEvent.objects.create(
                        payment=payment,
                        event_payment=change_amount,
                        event_due_amount=orig_due_amount,
                        event_date=timezone.localtime(timezone.now()).date(),
                        event_type='due_date_adjustment',
                    )

                account_payment = payment.account_payment
                if idx == 0:
                    account_payment.due_amount = payment.due_amount
                    account_payment.interest_amount = payment.installment_interest
                else:
                    account_payment.due_amount += payment.due_amount
                    account_payment.interest_amount += payment.installment_interest
                account_payment.save(
                    update_fields=['due_amount', 'interest_amount', 'udate'])

            logger.info(
                {
                    'status': 'update_payment_installment_julo_one',
                    'new_principal': principal,
                    'new_interest': interest,
                    'new_due_amount': new_due_amount_account_payment,
                    'loan': payment.loan.id,
                    'payment_number': payment.payment_number,
                    'payment': payment.id,
                    'account_payment': account_payment.id,
                }
            )
    return new_due_amount_account_payment


def change_due_dates(account_payment, new_next_due_date):
    # importing here due to circular import issue
    from juloserver.autodebet.services.task_services import (
        disable_gopay_autodebet_account_subscription_if_change_in_due_date)

    unpaid_account_payments = get_unpaid_account_payment(
        account_payment.account.id)
    new_cycle_day = new_next_due_date.day
    months = 0

    for unpaid_account_payment in unpaid_account_payments:
        with transaction.atomic():
            new_due_date = new_next_due_date + relativedelta(months=months)
            months += 1
            old_due_date = unpaid_account_payment.due_date

            logger.info(
                {
                    'action': 'changing_due_date',
                    'account_payment': unpaid_account_payment.id,
                    'old_due_date': old_due_date,
                    'new_due_date': new_due_date,
                }
            )

            unpaid_account_payment.due_date = new_due_date
            unpaid_account_payment.save(update_fields=['due_date', 'udate'])
            if unpaid_account_payment.due_date != old_due_date:
                disable_gopay_autodebet_account_subscription_if_change_in_due_date(
                    unpaid_account_payment)

            payments = unpaid_account_payment.payment_set.not_paid_active()
            payments.update(due_date=new_due_date)

            logger.info(
                {
                    'status': 'due_dates_changed',
                    'action': 'updating_cycle_day',
                    'new_cycle_day': new_cycle_day,
                    'account_payment': unpaid_account_payment.id,
                }
            )
            loans = (
                unpaid_account_payment.account.loan_set.get_queryset()
                .all_active_julo_one()
                .exclude(cycle_day=new_cycle_day)
            )
            loans.update(cycle_day=new_cycle_day)

            account = account_payment.account
            if account.cycle_day != new_cycle_day:
                old_cycle_day = account.cycle_day
                account.cycle_day = new_cycle_day
                account.save()

                update_deduction_fields_to_new_cycle_day(account_payment)

                application = account.get_active_application()
                if application.is_julo_one_or_starter():
                    create_account_cycle_day_history(
                        {}, account, LDDEReasonConst.Manual, old_cycle_day, application.pk)


def is_crm_sms_email_locking_active():
    return FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.LOCK_EMAIL_SMS_BUTTON_SETTING
    ).exists()


def get_cashback_earned_dict_by_account_payment_ids(account_payment_ids):
    queryset = (
        Payment.objects.filter(account_payment_id__in=account_payment_ids)
        .values('account_payment_id')
        .annotate(total_cashback_earned=Sum('cashback_earned'))
    )

    return {
        payment['account_payment_id']: payment['total_cashback_earned']
        for payment in queryset.iterator()
    }


def void_transaction(loan: Loan) -> None:
    if loan.status != LoanStatusCodes.CURRENT:
        return
    payments = loan.payment_set.normal().filter(
        payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
        is_restructured=False,
        account_payment__isnull=False
    ).order_by('payment_number')
    transaction_amount = loan.loan_amount
    with transaction.atomic():
        for payment in payments:
            account_payment = AccountPayment.objects.select_for_update().filter(
                account=loan.account,
                id=payment.account_payment_id
            ).last()
            due_amount_after_void = account_payment.due_amount - payment.due_amount
            payment.update_safely(account_payment=None)

            account_payment.update_safely(
                due_amount=due_amount_after_void,
                principal_amount=account_payment.principal_amount - payment.installment_principal,
                interest_amount=account_payment.interest_amount - payment.installment_interest
            )
            if due_amount_after_void == 0:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'Transaction Failed'
                }
                account_payment.change_status(PaymentStatusCodes.PAID_ON_TIME)
                account_payment.save(update_fields=['status'])
                account_payment.create_account_payment_status_history(
                    history_data)
        transaction_type = get_void_transaction_type_by_transaction_method(
            loan.transaction_method_id
        )
        AccountTransaction.objects.create(
            account=loan.account,
            payback_transaction=None,
            disbursement_id=loan.disbursement_id,
            transaction_date=loan.fund_transfer_ts,
            transaction_amount=transaction_amount,
            transaction_type=transaction_type,
            towards_principal=transaction_amount,
            towards_interest=0,
            towards_latefee=0,
            can_reverse=False
        )


def get_void_transaction_type_by_transaction_method(
    transaction_method_id: int
) -> Union[str, None]:
    void_transaction_type = None
    if transaction_method_id == TransactionMethodCode.CREDIT_CARD.code:
        void_transaction_type = VoidTransactionType.CREDIT_CARD_VOID
    elif transaction_method_id in TransactionMethodCode.payment_point():
        void_transaction_type = VoidTransactionType.PPOB_VOID

    return void_transaction_type


def get_potential_cashback_by_account_payment(
    account_payment,
    cashback_counter,
    is_eligible_android_version=True,
    is_return_with_experiment_status=False,
    cashback_parameters=dict(),
):
    """calculate potential cashback amount for an account payment.
    args:
        account_payment: the AccountPayment object
        cashback_counter: counter for cashback calculations
        is_eligible_android_version: whether user has eligible Android version
        is_return_with_experiment_status: flag to determine return value format
        cashback_parameters: Dictionary containing cashback calculation parameters
    returns:
        if is_return_with_experiment_status=False (default):
            int: The potential cashback amount
        if is_return_with_experiment_status=True:
            tuple: (potential_cashback_amount, is_eligible_new_cashback)
                - potential_cashback_amount (int): the potential cashback amount
                - is_eligible_new_cashback (bool): whether user is eligible for new cashback scheme
    """
    today = timezone.localtime(timezone.now()).date()
    potential_cashback = 0
    is_eligible_new_cashback = False
    if account_payment.due_date < today:
        if is_return_with_experiment_status:
            return potential_cashback, is_eligible_new_cashback
        return potential_cashback

    account_status = cashback_parameters.get('account_status')
    if is_eligible_android_version and account_status != AccountConstant.STATUS_CODE.suspended:
        is_eligible_new_cashback = cashback_parameters.get('is_eligible_new_cashback', False)

    paid_date_3_days_earlier = account_payment.due_date - timedelta(days=3)
    paid_date_2_days_earlier = account_payment.due_date - timedelta(days=2)
    due_date = cashback_parameters.get('due_date', -3)
    percentage_mapping = cashback_parameters.get('percentage_mapping', {})
    paid_date_earlier_cashback_new_scheme = account_payment.due_date - timedelta(days=abs(due_date))
    for payment in account_payment.payment_set.not_paid_active():
        loan = payment.loan
        if not loan:
            continue
        # check if loan is_restructured(refinancing already active)
        if loan.is_restructured:
            continue

        tmp_potential_cashback = 0
        if is_eligible_new_cashback:
            counter = cashback_counter
            if paid_date_earlier_cashback_new_scheme >= today:
                if counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
                    counter += 1
                else:
                    counter = NewCashbackConst.MAX_CASHBACK_COUNTER
                new_cashback_percentage = percentage_mapping.get(str(counter), 0)
                tmp_potential_cashback = loan.new_cashback_monthly(new_cashback_percentage)
        else:
            tmp_potential_cashback = loan.cashback_monthly
            if tmp_potential_cashback:
                if today > payment.due_date:
                    tmp_potential_cashback = 0
                    continue

                if paid_date_3_days_earlier <= today <= paid_date_2_days_earlier:
                    tmp_potential_cashback *= 2
                elif paid_date_3_days_earlier > today:
                    tmp_potential_cashback *= 3

        tmp_potential_cashback = min(tmp_potential_cashback, payment.maximum_cashback)
        potential_cashback += tmp_potential_cashback
    if is_return_with_experiment_status:
        return potential_cashback, is_eligible_new_cashback
    return potential_cashback


def get_late_fee_amount_by_account_payment(account_payment, is_paid_off_account_payment):
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LATE_FEE_GRACE_PERIOD,
        is_active=True,
    )

    dpd = account_payment.dpd
    days_applied = 5

    if feature_setting:
        days_applied = feature_setting.parameters.get('grade_period', days_applied)

    today = timezone.localtime(timezone.now()).date()

    # for checkout riwayat page
    if is_paid_off_account_payment:
        return account_payment.late_fee_amount, 0

    late_fee_earlier_exp, experiment_data = get_experiment_group_data(
        MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
        account_payment.account_id)
    if experiment_data and experiment_data.group == 'experiment':
        days_applied = late_fee_earlier_exp.criteria.get(
            'days_applied_for_checkout', 1)

    date_applied = account_payment.due_date + relativedelta(days=days_applied)

    if dpd >= days_applied or account_payment.late_fee_applied:
        return account_payment.late_fee_amount - account_payment.paid_late_fee, 0
    elif dpd > 0 and dpd < days_applied:
        late_fee = 0
        grace_period = (date_applied - today).days

        if grace_period < 0:
            grace_period = 0

        for payment in account_payment.payment_set.not_paid_active():
            loan = payment.loan
            if not loan:
                continue

            late_fee += get_new_late_fee_calculation(payment.id)

        return late_fee, grace_period
    else:
        return 0, 0


def get_late_fee_amount_by_account_payment_v2(account_payment, is_paid_off_account_payment):
    """get_late_fee_amount_by_account_payment_v2
    Parameter :
        account_payment: AccountPayment
        is_paid_off_account_payment: Boolean
    Returning :
        actual_late_fee: Int -> remaining late fee from account_payment
        potential_late_fee: Int -> potential late fee for account_payment after grace period
        late_fee: Int -> amount of late fee that have to be paid after grace late fee
        late_due_date: Date ->  deadline for grace period
    Description :
        To determine the amount of late fees that's already generated,
        late fee that could be generated after grace period,
        the amount of late_fee that have to be paid if due_date still in grace period,
        and the maximum grace due date.
    """
    dpd = account_payment.dpd

    actual_late_fee = account_payment.late_fee_amount
    potential_late_fee = actual_late_fee
    # for checkout riwayat page
    if is_paid_off_account_payment:
        return actual_late_fee, potential_late_fee, None
    actual_late_fee -= account_payment.paid_late_fee
    potential_late_fee = actual_late_fee

    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LATE_FEE_GRACE_PERIOD,
        is_active=True,
    )
    if not feature_setting:
        return actual_late_fee, potential_late_fee, None
    days_applied = feature_setting.parameters.get('grade_period')
    date_applied = account_payment.due_date + relativedelta(days=days_applied)

    if dpd >= days_applied or account_payment.late_fee_applied:
        return actual_late_fee, potential_late_fee, date_applied
    elif dpd > 0 and dpd < days_applied:
        for payment in account_payment.payment_set.not_paid_active():
            loan = payment.loan
            if not loan:
                continue
            potential_late_fee += get_new_late_fee_calculation(payment.id)

        return actual_late_fee, potential_late_fee, date_applied
    else:
        return 0, 0, None


def create_checkout_request(account_payments, payment_method, data):
    checkout = 0
    total_payments = 0
    with transaction.atomic():
        checkout_xid = generate_checkout_xid()
        # in feature pahse, expired date will be hanlde by django admin
        expired_date = get_expired_date_checkout_request()
        refinancing_id = data.get('refinancing_id', None)

        if refinancing_id:
            total_payments = refinancing_id.prerequisite_amount
            account = refinancing_id.account
        else:
            for account_payment in account_payments:
                total_payments += account_payment.due_amount
            account = account_payments[0].account

        if not data.get('account_payment_id'):
            account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')
            data['account_payment_id'] = [account_payments.first().id]

        checkout = CheckoutRequest.objects.create(
            account_id=account,
            checkout_request_xid=checkout_xid,
            status=CheckoutRequestCons.ACTIVE,
            total_payments=total_payments,
            checkout_amount=total_payments,
            account_payment_ids=data['account_payment_id'],
            checkout_payment_method_id=payment_method,
            expired_date=expired_date,
            session_id=data.get('sessionId'),
            type=CheckoutPaymentType.REFINANCING
            if refinancing_id
            else CheckoutPaymentType.CHECKOUT,
            loan_refinancing_request=refinancing_id,
            total_late_fee_discount=data.get('total_late_fee_discount'),
        )

        if payment_method:
            if payment_method.bank_code == BankCodes.BNI:
                update_va_bni_transaction.delay(
                    account.id,
                    'account_payment.services.account_payment_related.create_checkout_request',
                    total_payments,
                )

    return checkout


def construct_last_checkout_request(checkout_request,
                                    payment_method, is_new_cashback=False):
    total_bonus_cashback = 0
    payment_method_dict = None
    if payment_method:
        payment_method_data = PaymentMethodLookup.objects.filter(
            name=payment_method.payment_method_name
        ).first()
        payment_method_dict = {
            'id': payment_method.id,
            'bank_name': payment_method.payment_method_name,
            'method_icn': payment_method_data.image_logo_url,
            'method_VA': payment_method.virtual_account
        }
        if payment_method.payment_method_name == 'GoPay Tokenization':
            payment_method_dict['bank_name'] = 'Gopay'

    receipt = None
    if checkout_request.receipt_ids:
        image = get_image_by_account_payment_id(
            checkout_request.account_payment_ids[0])
        receipt = image.image_url if image and image.image_url else None
    (
        total_installment_amount,
        total_late_fee_amount,
        total_paid_amount,
        total_remaining_due_amount,
    ) = summary_amount_checkout_request(checkout_request.account_payment_ids)
    total_potential_late_fee_amount = total_late_fee_amount
    if is_new_cashback:
        total_amount = calculation_new_cashback_earned(
            checkout_request.account_payment_ids)
        total_bonus_cashback = total_amount if total_amount else 0
    grace_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LATE_FEE_GRACE_PERIOD,
        is_active=True,
    )
    if grace_fs and checkout_request.total_late_fee_discount:
        if grace_fs.parameters.get('daily_late_fee'):
            total_late_fee_amount -= checkout_request.total_late_fee_discount
            total_remaining_due_amount -= checkout_request.total_late_fee_discount
        else:
            total_potential_late_fee_amount += checkout_request.total_late_fee_discount

    checkout_request_data = {
        'status': checkout_request.status,
        'update_date': timezone.localtime(checkout_request.udate),
        'expired_date': timezone.localtime(checkout_request.expired_date),
        'checkout_id': checkout_request.id,
        'checkout_xid': checkout_request.checkout_request_xid,
        'payment_method': payment_method_dict,
        'checkout_receipt': receipt,
        'total_cashback_amount': checkout_request.cashback_used,
        'total_installment_amount': total_installment_amount,
        'total_late_fee_amount': total_late_fee_amount,
        'total_potential_late_fee_amount': total_potential_late_fee_amount,
        'total_paid_amount': total_paid_amount,
        'total_remaining_due_amount': total_remaining_due_amount,
        'total_checkout_amount': checkout_request.checkout_amount,
        'total_bonus_cashback': total_bonus_cashback,
    }

    return checkout_request_data


def summary_amount_checkout_request(account_payments):
    total_installment_amount = 0
    total_late_fee_amount = 0
    total_paid_amount = 0
    total_remaining_due_amount = 0
    account_payment_amounts = AccountPayment.objects.only(
        'due_amount', 'late_fee_amount', 'paid_amount', 'paid_late_fee'
    ).filter(pk__in=account_payments)
    for account_payment_amount in account_payment_amounts:
        total_installment_amount += account_payment_amount.sum_total_installment_amount()
        total_late_fee_amount += (
            account_payment_amount.late_fee_amount - account_payment_amount.paid_late_fee
        )
        total_paid_amount += account_payment_amount.paid_amount
        total_remaining_due_amount += account_payment_amount.due_amount

    return (
        total_installment_amount,
        total_late_fee_amount,
        total_paid_amount,
        total_remaining_due_amount,
    )


def get_checkout_xid_by_paid_off_accout_payment(is_paid_off_account_payment, account_payment):
    # if is_paid_off_account_payment == True it's mean, this will using for Checkout riwayat page
    if not is_paid_off_account_payment:
        return None
    account_payment_arr = [account_payment.id]
    checkout_request = CheckoutRequest.objects.filter(
        account_id=account_payment.account_id,
        account_payment_ids__contains=account_payment_arr
    ).last()
    if not checkout_request or not checkout_request.payment_event_ids:
        return None
    # for validation payment event is paid off by account payment
    payment_event = (
        PaymentEvent.objects.filter(
            id__in=checkout_request.payment_event_ids,
            payment__payment_status__gte=PaymentStatusCodes.PAID_ON_TIME,
            payment__payment_status__lte=PaymentStatusCodes.PAID_LATE,
            payment__account_payment=account_payment,
        )
        .exclude(payment__payment_status=PaymentStatusCodes.SELL_OFF)
        .exists()
    )

    if payment_event:
        return checkout_request.checkout_request_xid

    return None


def get_checkout_experience_setting(account_id):
    """
    This function will first check to "experiment setting" table
    and then to "feature setting" table.
    First return boolean for show/hide "Bayar Sekarang" button,
    second return boolean for show/hide "Payment Method" section.
    """
    # check have processed loan refinancing
    loan_refinancing = get_on_processed_loan_refinancing_by_account_id(
        account_id)
    if loan_refinancing:
        return False, True

    today_date = timezone.localtime(timezone.now()).date()
    checkout_request_experiment = (
        ExperimentSetting.objects.filter(
            is_active=True, code=ExperimentConst.CHECKOUT_EXPERIENCE_EXPERIMENT
        )
        .filter(
            (Q(start_date__date__lte=today_date)
             & Q(end_date__date__gte=today_date))
            | Q(is_permanent=True)
        )
        .last()
    )
    if not checkout_request_experiment:
        # get configuration for show or hide button "bayar sekarang"
        # to feature setting experience
        return get_checkout_experience_feature_setting(), True

    group = ExperimentGroup.objects.get_or_none(
        experiment_setting=checkout_request_experiment.id, account=account_id
    )
    if not group:
        # if account not exist will create the new row
        group = create_checkout_experiment_for_not_existing_data(
            account_id, checkout_request_experiment
        )

    return check_checkout_experience_experiment_group(group)


def get_checkout_experience_feature_setting():
    checkout_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.CHECKOUT_EXPERIENCE
    )
    if not checkout_feature_setting:
        return False

    return checkout_feature_setting.is_active


def create_checkout_experiment_for_not_existing_data(account_id, checkout_request_experiment):
    # get account id tail criteria
    checkout_group_criteria = checkout_request_experiment.criteria['account_id_tail']
    control_group_criteria = list(
        map(int, checkout_group_criteria['control_group']))
    experiment_group_1_criteria = list(
        map(int, checkout_group_criteria['experiment_group_1']))
    experiment_group_2_criteria = list(
        map(int, checkout_group_criteria['experiment_group_2']))
    last_digit = int(repr(account_id)[-1])
    # selecting group name
    group = None
    group_name = None
    if last_digit in control_group_criteria:
        group_name = CheckoutExperienceExperimentGroup.CONTROL_GROUP
    elif last_digit in experiment_group_1_criteria:
        group_name = CheckoutExperienceExperimentGroup.EXPERIMENT_GROUP_1
    elif last_digit in experiment_group_2_criteria:
        group_name = CheckoutExperienceExperimentGroup.EXPERIMENT_GROUP_2
    # if group name already selected then insert to experiment_group table
    if group_name:
        account = Account.objects.get(pk=account_id)
        group = ExperimentGroup.objects.create(
            experiment_setting=checkout_request_experiment, account=account, group=group_name
        )

    return group


def check_checkout_experience_experiment_group(experiment_group):
    # default variable
    show_button = False
    show_payment_method = True
    # if experiment group is None
    if not experiment_group:
        show_button = get_checkout_experience_feature_setting()
        return show_button, show_payment_method
    # check condition for exist experiment group
    if experiment_group.group == CheckoutExperienceExperimentGroup.EXPERIMENT_GROUP_1:
        show_button = True
        return show_button, show_payment_method
    elif experiment_group.group == CheckoutExperienceExperimentGroup.EXPERIMENT_GROUP_2:
        show_button = True
        show_payment_method = False
        return show_button, show_payment_method
    else:
        return show_button, show_payment_method


def get_on_processed_loan_refinancing_by_account_id(account_id):
    return LoanRefinancingRequest.objects.filter(
        account=account_id, status__in=CovidRefinancingConst.LOAN_REFINANCING_ON_PROCESSED
    ).exists()


def update_checkout_experience_status_to_cancel(account_id):
    checkout_request = CheckoutRequest.objects.filter(
        account_id=account_id, status='active')

    if checkout_request:
        account = checkout_request.last().account_id
        checkout_request.update(status='canceled')
        update_va_bni_transaction.delay(
            account.id,
            'account_payment.views.views_api_v2.UpdateCheckoutRequestStatus',
        )


def store_experiment(experiment_code: str, customer_id: int, group: str) -> None:
    experiment_setting = ExperimentSetting.objects.get_or_none(code=experiment_code, is_active=True)
    if not experiment_setting:
        logger.warning(
            {
                "action": "juloserver.account_payment.services."
                          "account_payment_related.store_experiment",
                "experiment_code": experiment_code,
                "customer_id": customer_id,
                "group": group,
                "message": "experiment setting turned off",
            }
        )
        return

    last_experiment_group = ExperimentGroup.objects.filter(
        experiment_setting=experiment_setting,
        customer_id=customer_id,
    ).values_list('group', flat=True).last()
    if last_experiment_group == group:
        logger.warning(
            {
                "action": "juloserver.account_payment.services."
                          "account_payment_related.store_experiment",
                "experiment_code": experiment_code,
                "customer_id": customer_id,
                "group": group,
                "message": "experiment group already stored",
            }
        )
        return

    ExperimentGroup.objects.create(
        experiment_setting=experiment_setting,
        customer_id=customer_id,
        group=group,
    )


def store_repayment_recall_log(customer_id, payback_transactions):
    if not payback_transactions:
        RepaymentRecallLog.objects.create(
            customer_id=customer_id
        )
        return
    repayment_recall_log_data = []
    for payback_transaction in payback_transactions:
        repayment_recall_log_data.append(
            RepaymentRecallLog(
                customer_id=customer_id,
                payback_transaction_id=payback_transaction.id,
            )
        )
    RepaymentRecallLog.objects.bulk_create(
        repayment_recall_log_data, batch_size=30)


def get_payment_status(payment_status_code, due_date, paid_date):
    today = timezone.localtime(timezone.now()).date()
    timedelta_days = (today - due_date).days
    if payment_status_code >= PaymentStatusCodes.PAID_ON_TIME:
        if paid_date and (paid_date - due_date).days > 0:
            return 'Terbayar terlambat'
        elif payment_status_code > PaymentStatusCodes.PAID_ON_TIME:
            return 'Terbayar terlambat'

        return 'Terbayar tepat waktu'
    else:
        if timedelta_days == 0:
            return 'Jatuh tempo hari ini'
        if timedelta_days > 0:
            return 'Terlambat'

        return 'Belum jatuh tempo'


def get_potential_and_total_cashback(account_payment, cashback_counter, customer_id):
    due_date, percentage_mapping = get_paramters_cashback_new_scheme()
    cashback_parameters = dict(
        is_eligible_new_cashback=account_payment.account.is_cashback_new_scheme,
        due_date=due_date,
        percentage_mapping=percentage_mapping,
        account_status=account_payment.account.status_id,
    )
    # Get potential cashback
    potensi_cashback = get_potential_cashback_by_account_payment(
        account_payment=account_payment,
        cashback_counter=cashback_counter,
        cashback_parameters=cashback_parameters,
    )
    # Get total cashback earned
    total_cashback_earned = CashbackEarned.objects.filter(
        verified=True,
        customerwallethistory__customer_id=account_payment.account.customer_id
    ).aggregate(total_current_balance=Sum('current_balance'))['total_current_balance'] or 0

    return potensi_cashback, total_cashback_earned


def calculation_new_cashback_earned(account_payment_ids):
    total_amount = (
        Payment.objects.filter(
            account_payment_id__in=account_payment_ids).aggregate(
                total_bonus_cashback=Sum('cashback_earned'))
    )
    return total_amount['total_bonus_cashback']


def get_potential_cashback_for_crm(account_payment):
    # Get potential cashback
    account = account_payment.account
    cashback_counter = 0 if not hasattr(account, "cashback_counter") else account.cashback_counter
    params = dict(account_payment=account_payment)
    if hasattr(account, "cashback_counter"):
        params['cashback_counter'] = cashback_counter

    due_date, percentage_mapping = get_paramters_cashback_new_scheme()
    cashback_parameters = dict(
        is_eligible_new_cashback=account.is_cashback_new_scheme,
        due_date=due_date,
        percentage_mapping=percentage_mapping,
        account_status=account.status_id,
    )
    params['cashback_parameters'] = cashback_parameters

    return display_rupiah(get_potential_cashback_by_account_payment(**params))


def get_percentage_potential_cashback_for_crm(account_payment):
    account = account_payment.account
    if account_payment.is_paid or \
            account.last_application.product_line_id not in \
            ProductLineCodes.julo_product():
        return '-'

    if account_payment.payment_set.is_not_paid_active_with_refinancing():
        return '-'

    cashback_percentage = 0
    dpd = account_payment.dpd
    if account.is_cashback_new_scheme:
        due_date, percentage_mapping = get_paramters_cashback_new_scheme()
        if dpd <= due_date:
            cashback_counter = account.cashback_counter_for_customer
            cashback_percentage = percentage_mapping.get(str(cashback_counter), 0)
        return '{}%'.format(cashback_percentage)

    if dpd <= -4:
        cashback_percentage = 3
    elif dpd in [-3, -2]:
        cashback_percentage = 2
    elif dpd in [-1, 0]:
        cashback_percentage = 1

    return '{}%'.format(cashback_percentage)


def get_total_cashback_earned_for_crm(account_payment):
    total_cashback_earned = CashbackEarned.objects.filter(
        verified=True,
        customerwallethistory__customer_id=account_payment.account.customer_id
    ).aggregate(total_current_balance=Sum('current_balance'))['total_current_balance'] or 0
    return display_rupiah(total_cashback_earned)


def is_account_installed_apps(account_payment, apps_name):
    customer = account_payment.account.customer

    app_rules = {
        'WhatsApp': {
            'attribute': 'is_use_whatsapp',
            'query_type': 'in',
        },
        'Telegram': {
            'attribute': 'is_use_telegram',
            'query_type': '=',
        },
    }

    for app_name, rules in app_rules.items():
        if app_name in apps_name:
            if getattr(customer, rules['attribute']):
                return True

            if rules['query_type'] == 'in':
                app_exists = SdDeviceApp.objects.filter(
                    customer_id=customer.id, app_name__in=apps_name
                ).exists()
            else:
                app_exists = SdDeviceApp.objects.filter(
                    customer_id=customer.id, app_name=app_name
                ).exists()

            setattr(customer, rules['attribute'], app_exists)
            customer.save()

            return app_exists

    return False


def is_account_payment_blocked_for_call(account_payment):
    return NotSentToDialer.objects.filter(
        account_id=account_payment.account_id,
        cdate__gte=timezone.localtime(timezone.now()).date()).exists()


def extract_crm_customer_parameter(crm_customer_detail, model, user=None):
    import importlib
    from babel.dates import format_date

    params = crm_customer_detail.parameter_model_value
    default_value = {
        'title': crm_customer_detail.attribute_name, 'result': '<strong> - </strong>'
    }
    try:
        final_value = default_value
        additional_value = ''
        model_identifier = params['models'].get(type(model).__name__.lower())
        if not model_identifier:
            return default_value
        execution_mode = params.get('execution_mode', '')
        if execution_mode not in {'execute_function', 'only_execute', 'query'}:
            return default_value

        model_identifier = eval(model_identifier)
        if execution_mode == 'only_execute':
            final_value = model_identifier
        elif execution_mode == 'execute_function':
            schema_module = importlib.import_module(params['function_path'])
            function_name = getattr(schema_module, params['function_name'])
            if not function_name:
                return default_value
            function_expression = params.get('function')
            if not function_expression:
                return default_value

            final_value = eval(function_expression)
        elif execution_mode == 'query':
            schema_module = importlib.import_module(params['orm_path'])
            orm_object = getattr(schema_module, params['orm_object'])  # noqa
            query_expression = params.get('query')
            query_identifier_results = params.get('identifier')
            if not query_expression:
                return default_value

            query = eval(query_expression)  # noqa will useed on final_value param
            if query:
                if crm_customer_detail.attribute_name == 'FDC Risky Customer' and final_value:
                    additional_value = format_date(
                        eval('query.udate'), "d MMM yyyy", locale="id_ID")
                final_value = eval(query_identifier_results)
            else:
                final_value = None

        dom_format = params.get('dom')
        final_value = params.get('default_value', '-') if final_value is None else final_value
        results = '<strong> {} </strong>'.format(final_value)
        if dom_format and type(dom_format) == str:
            results = dom_format.format(final_value)
        elif dom_format and type(dom_format) == dict:
            dom_identifier = final_value if type(final_value) is not bool \
                else str(final_value).lower()
            if not dom_format.get(dom_identifier, None):
                dom_identifier = True if final_value != '-' else False
                dom_identifier = str(dom_identifier).lower()

            if additional_value:
                final_value = additional_value
            results = dom_format.get(dom_identifier, default_value['result']).format(final_value)
            if crm_customer_detail.attribute_name == 'Memenuhi Syarat Refinancing':
                results = results.replace('<<account_id>>', str(model.account_id))

        default_value['result'] = results
        return default_value

    except Exception:
        return default_value


def process_crm_customer_detail_list(model_data, user=None):
    crm_customer_details = (CRMCustomerDetail.objects.all()
                            .order_by('section', 'sort_order', '-udate'))
    data = []
    for crm_customer_detail in crm_customer_details:
        section = crm_customer_detail.section
        if not crm_customer_detail.parameter_model_value:
            continue

        section_data = {
            "header_title": section,
            "attributes": [extract_crm_customer_parameter(crm_customer_detail, model_data, user)]
        }

        # Check if the section is already in the data list
        existing_section = next((item for item in data if item["header_title"] == section), None)

        if existing_section:
            existing_section["attributes"].append(
                extract_crm_customer_parameter(crm_customer_detail, model_data, user))
        else:
            data.append(section_data)
    return data


def get_payment_status_for_crm(account_payment):
    loan_ids = account_payment.payment_set.exclude(
        loan__loan_status_id__in=LoanStatusCodes.loan_status_not_active()
    ).values_list('loan_id', flat=True)
    if not loan_ids:
        return '-'

    loan_histories = LoanHistory.objects.filter(
        loan_id__in=loan_ids, status_new__in=LoanStatusCodes.loan_status_due()
    ).order_by('status_new').last()
    if not loan_histories:
        return '-'

    if loan_histories.status_new == LoanStatusCodes.LOAN_1DPD:
        return 'FPD'
    elif loan_histories.status_new in {
        LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD, LoanStatusCodes.LOAN_60DPD,
        LoanStatusCodes.LOAN_90DPD, LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
        LoanStatusCodes.LOAN_180DPD
    }:
        return 'FPG'

    return '-'


def new_update_late_fee(payment_id):
    logger.info(
        {
            "action": "juloserver.account_payment.services."
                      "account_payment_related.new_update_late_fee",
            "payment_id": payment_id,
        }
    )
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.status in PaymentStatusCodes.paid_status_codes():
            logger.warning(
                {
                    "action": "juloserver.account_payment.services."
                              "account_payment_related.new_update_late_fee",
                    "message": "payment in paid status",
                    "payment_id": payment_id,
                }
            )
            return
        late_fee_rules = payment.loan.product.latefeerule_set.all().order_by('dpd').values(
            'dpd', 'late_fee_pct'
        )
        if late_fee_rules and payment.late_fee_applied >= len(late_fee_rules):
            logger.warning({
                "action": "juloserver.account_payment.services."
                          "account_payment_related.new_update_late_fee",
                'warning': 'late fee applied maximum times',
                'late_fee_applied': payment.late_fee_applied,
                'payment_id': payment.id,
            })
            return
        today = timezone.localtime(timezone.now()).date()
        late_fee_block = LateFeeBlock.objects.filter(
            payment_id=payment_id, valid_until__gte=today
        ).last()
        if late_fee_block:
            # Update logged data when customer
            # Create ptp and status is Paid but not fully paid off
            if late_fee_block.ptp and late_fee_block.ptp.ptp_status == "Paid":
                late_fee_block.update_safely(valid_until=today - timedelta(days=1))
            else:
                logger.warning(
                    {
                        "action": "juloserver.account_payment.services."
                        "account_payment_related.new_update_late_fee",
                        'warning': 'late fee block',
                        'payment_id': payment.id,
                        'reason': late_fee_block.block_reason,
                    }
                )
                return

        ptp = (
            PTP.objects.select_related('account_payment')
            .filter(
                ptp_date__gte=today,
                account=payment.loan.account,
                account_payment_id__isnull=False,
                ptp_parent__isnull=True,
            )
            .exclude(ptp_status__in=["Paid", "Paid after ptp date", "Not Paid"])
            .last()
        )
        if ptp:
            late_fee_block = LateFeeBlock.objects.create(
                payment=payment,
                dpd=payment.get_dpd,
                block_reason=LateFeeBlockReason.ACTIVE_PTP,
                valid_until=ptp.ptp_date,
                ptp=ptp,
            )
            logger.warning(
                {
                    "action": "juloserver.account_payment.services."
                    "account_payment_related.new_update_late_fee",
                    'warning': 'late fee block',
                    'payment_id': payment.id,
                    'reason': late_fee_block.block_reason,
                }
            )
            return

        late_fee_applied = payment.late_fee_applied
        total_late_fee = 0
        while late_fee_applied < len(late_fee_rules):
            late_fee_rule = late_fee_rules[late_fee_applied]
            if today < payment.due_date + timedelta(days=late_fee_rule['dpd']):
                logger.warning(
                    {
                        "action": "juloserver.account_payment.services."
                        "account_payment_related.new_update_late_fee",
                        'warning': 'date is not eligible for generate late fee',
                        'late_fee_applied': payment.late_fee_applied,
                        'payment_id': payment.id,
                    }
                )
                return
            loan = payment.loan
            # freeze late fee for sold off loan
            if loan.status == LoanStatusCodes.SELL_OFF:
                logger.warning(
                    {
                        "action": "juloserver.account_payment.services."
                        "account_payment_related.new_update_late_fee",
                        "message": "loan is sell off status",
                        "payment_id": payment_id,
                    }
                )
                return

            old_late_fee_amount = payment.late_fee_amount

            late_fee = py2round((late_fee_rule['late_fee_pct'] * payment.remaining_principal), -2)
            if late_fee <= 0:
                return
            due_amount_before = payment.due_amount
            late_fee, status_max_late_fee = loan.get_status_max_late_fee(late_fee)
            if status_max_late_fee:
                logger.warning(
                    {
                        "action": "juloserver.account_payment.services."
                        "account_payment_related.new_update_late_fee",
                        "message": "payment in status max late fee",
                        "payment_id": payment_id,
                    }
                )
                return
            payment.apply_late_fee(late_fee)
            payment.refresh_from_db()
            PaymentEvent.objects.create(
                payment=payment,
                event_payment=-late_fee,
                event_due_amount=due_amount_before,
                event_date=today,
                event_type='late_fee',
            )

            late_fee_applied = payment.late_fee_applied
            total_late_fee += late_fee
            logger.info(
                {
                    "action": "juloserver.account_payment.services."
                    "account_payment_related.new_update_late_fee",
                    "message": "success",
                    'payment_id': payment.id,
                    'old_late_fee': old_late_fee_amount,
                    'late_fee_amount_added': late_fee,
                }
            )

        if late_fee_applied > 2:
            customer = loan.customer
            customer.can_reapply = False
            customer.save(update_fields=['can_reapply'])

        if not payment.account_payment:
            automate_late_fee_waiver(payment, total_late_fee, today)


def update_latest_payment_method(payback_transaction_id: int) -> None:
    exclude_latest_payment_method_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EXCLUDE_LATEST_PAYMENT_METHOD,
        is_active=True,
    ).last()

    exclude_latest_payment_method_list = []
    if exclude_latest_payment_method_feature and exclude_latest_payment_method_feature.parameters:
        exclude_latest_payment_method_list = exclude_latest_payment_method_feature.parameters.get(
            'payment_method_name'
        )

    payback_transaction = PaybackTransaction.objects.exclude(
        payment_method__payment_method_name__in=exclude_latest_payment_method_list
    ).filter(
        pk=payback_transaction_id,
        account__isnull=False,
        account__account_lookup__name__in={'JULO1', 'JULOSTARTER'},
        payment_method__isnull=False,
    ).first()
    if not payback_transaction:
        logger.warning({
            "action": "juloserver.account_payment.services."
                      "account_payment_related.update_primary_payment_method",
            "message": "payback transaction not found",
            "payback_transaction_id": payback_transaction_id,
        })
        return
    payment_method = payback_transaction.payment_method
    account = payback_transaction.account
    latest_payment_method = PaymentMethod.objects.filter(
        customer=payback_transaction.customer,
        is_latest_payment_method=True,
    )
    if latest_payment_method.filter(pk=payback_transaction.payment_method_id).exists():
        logger.warning({
            "action": "juloserver.account_payment.services."
                      "account_payment_related.update_primary_payment_method",
            "message": "already latest payment method",
            "account_id": account.id,
            "payback_transaction_id": payback_transaction_id,
        })
        return
    if payment_method.payment_method_code == PaymentMethodCodes.DANA_BILLER:
        payment_method = PaymentMethod.objects.filter(
            payment_method_code=PaymentMethodCodes.DANA,
            customer=payback_transaction.customer
        ).last()
        if not payment_method:
            logger.warning({
                "action": "juloserver.account_payment.services."
                          "account_payment_related.update_primary_payment_method",
                "message": "dana payment method not found",
                "account_id": account.id,
                "payback_transaction_id": payback_transaction_id,
            })
            return
    payment_method.update_safely(is_latest_payment_method=True)
    latest_payment_method.exclude(pk=payment_method.id).update(is_latest_payment_method=False)


def get_cashback_new_scheme_banner(account: Account, version=1) -> dict:
    banner_data = dict()
    cashback_new_scheme_params = get_paramters_cashback_new_scheme(True)
    if not cashback_new_scheme_params:
        return None

    due_date_cashback = cashback_new_scheme_params.get('due_date', -3)
    safe_due_date_cashback = cashback_new_scheme_params.get('safe_due_date', -5)
    cashback_banners = cashback_new_scheme_params.get('cashback_banners', {})

    break_at_level = 0
    incoming_level = account.cashback_incoming_level
    if account.cashback_counter == 0:
        last_cashback_history = (
            CashbackCounterHistory.objects.filter(account_payment__account__id=account.id)
            .only('counter')
            .order_by('-cdate')[:2]
        )
        if len(last_cashback_history) == 2:
            break_at_level = last_cashback_history[1].counter

    banner_data['break_at_level'] = break_at_level
    banner_data['incoming_level'] = incoming_level
    banner_data['dpd_param'] = dict(
        current=account.dpd,
        safe_threshold=abs(safe_due_date_cashback),
        warning_threshold=abs(due_date_cashback),
    )

    assets = []
    for i in range(1, 7):
        level = i
        name = '{}x'.format(i)
        banner_index = i
        if i > 5:
            level = i
            name = '>{}x'.format(i - 1)
            banner_index = i - 1
        cashback_banner = cashback_banners.get(str(banner_index), {})
        asset = dict(
            level=level,
            name=name,
            active_icon=cashback_banner.get('active_icon', ''),
            inactive_icon=cashback_banner.get('inactive_icon', ''),
            incoming_icon=cashback_banner.get('incoming_icon', ''),
        )
        assets.append(asset)
    banner_data['asset'] = assets

    if version >= 2:
        banner_data['maximum_potential_cashback'] = get_maximum_potential_cashback_new_scheme(
            account
        )

    return banner_data


def get_maximum_potential_cashback_new_scheme(account: Account):
    account_payments = account.accountpayment_set.order_by("due_date")

    _, percentage_mapping = get_paramters_cashback_new_scheme()
    _, is_cashback_experiment = get_cashback_claim_experiment(account=account)

    # SIMULATE MAXIMUM CASHBACK
    cashback_counter = account.cashback_counter or 0  # start from current streak
    maximum_potential_cashback = 0
    for account_payment in account_payments:

        potential_cashback = 0
        new_cashback_calculated = False  # flag if there's any cashback in future
        payment_ids = list(account_payment.payment_set.values_list('id', flat=True))

        for payment_id in payment_ids:
            payment = Payment.objects.get_or_none(pk=payment_id)
            if not payment:
                continue

            loan = payment.loan

            if not loan or loan.loan_status_id not in LoanStatusCodes.loan_status_active():
                continue
            # check if loan is_restructured(refinancing already active)
            if loan.is_restructured:
                continue

            # Payment paid => getting cashback from history instead
            if payment.payment_status_id >= StatusLookup.PAID_ON_TIME_CODE:
                potential_cashback += payment.cashback_earned
                if is_cashback_experiment:
                    cashback_claim_payment = CashbackClaimPayment.objects.filter(
                        payment_id=payment.id,
                        status__in=[
                            CashbackClaimConst.STATUS_PENDING,
                            CashbackClaimConst.STATUS_ELIGIBLE,
                        ],
                    ).last()
                    potential_cashback += (
                        cashback_claim_payment.cashback_amount if cashback_claim_payment else 0
                    )
            else:
                # Payment hasn't been paid => getting cashback calculation
                new_cashback_calculated = True
                tmp_potential_cashback = 0
                counter = cashback_counter
                if counter < NewCashbackConst.MAX_CASHBACK_COUNTER:
                    counter += 1
                else:
                    counter = NewCashbackConst.MAX_CASHBACK_COUNTER
                new_cashback_percentage = percentage_mapping.get(str(counter))
                tmp_potential_cashback = loan.new_cashback_monthly(new_cashback_percentage)
                potential_cashback += tmp_potential_cashback

        maximum_potential_cashback += potential_cashback

        if new_cashback_calculated:
            # has new cashback => continue streak progress
            cashback_counter += 1

    return maximum_potential_cashback


def process_crm_unpaid_loan_account_details_list(account_payment):
    payments = Payment.objects.select_related(
        'loan',
        'loan__lender'
    ).filter(account_payment=account_payment).normal()
    result = []
    if not payments:
        return result

    count = 1
    data = []
    for payment_obj in payments:
        loan = payment_obj.loan
        if loan and loan.oldest_unpaid_payment:
            fe_display_name = '-'
            transaction_date = '-'
            due_date = '-'
            loan_amount = '-'
            calculated_overdue_unpaid_amount = '-'
            calculated_total_due_amount = '-'
            transaction_method = payment_obj.loan.transaction_method
            if transaction_method and transaction_method.fe_display_name:
                fe_display_name = transaction_method.fe_display_name
            if loan.fund_transfer_ts:
                transaction_date = loan.fund_transfer_ts.strftime('%d %b %Y')
            if loan.oldest_unpaid_payment.due_date:
                due_date = loan.oldest_unpaid_payment.due_date.strftime('%d %b %Y')
            if loan.oldest_unpaid_payment.payment_number:
                installment_count = str(loan.oldest_unpaid_payment.payment_number)
            else:
                installment_count = '-'
            if loan.total_installment_count:
                installment_count += "/" + str(loan.total_installment_count)
            else:
                installment_count += "/-"
            if loan.loan_amount:
                loan_amount = format_rupiahs(loan.loan_amount, "no")
            if loan.calculated_overdue_unpaid_amount:
                calculated_overdue_unpaid_amount = format_rupiahs(
                    loan.calculated_overdue_unpaid_amount, "no"
                )
            if loan.calculated_total_due_amount:
                calculated_total_due_amount = format_rupiahs(loan.calculated_total_due_amount, "no")
            section_data = {
                "count": count,
                "transaction_method": fe_display_name,
                "transaction_date": transaction_date,
                "due_date": due_date,
                "installment_count": installment_count,
                "loan_amount": loan_amount,
                "calculated_overdue_unpaid_amount": calculated_overdue_unpaid_amount,
                "calculated_total_due_amount": calculated_total_due_amount,
                "loan_id": loan.id,
                "total_paid_amount": loan.calculated_total_paid_amount
                if loan.calculated_total_paid_amount
                else '-',
            }

            count += 1
            data.append(section_data)
    if data:
        result.append({"attributes": data})

    return result


def get_new_late_fee_calculation(payment_id):
    payment = Payment.objects.get_or_none(pk=payment_id)
    total_late_fee = 0

    if not payment:
        return 0

    if payment.status in PaymentStatusCodes.paid_status_codes():
        logger.warning(
            {
                "action": "juloserver.account_payment.services."
                "account_payment_related.get_new_late_fee_calculation",
                "message": "payment in paid status",
                "payment_id": payment_id,
            }
        )
        return total_late_fee

    late_fee_rules = (
        payment.loan.product.latefeerule_set.all().order_by('dpd').values('dpd', 'late_fee_pct')
    )

    if late_fee_rules and payment.late_fee_applied >= len(late_fee_rules):
        logger.warning(
            {
                "action": "juloserver.account_payment.services."
                "account_payment_related.get_new_late_fee_calculation",
                'warning': 'late fee applied maximum times',
                'late_fee_applied': payment.late_fee_applied,
                'payment_id': payment.id,
            }
        )
        return total_late_fee

    today = timezone.localtime(timezone.now()).date()
    late_fee_applied = payment.late_fee_applied

    while late_fee_applied < len(late_fee_rules):
        late_fee_rule = late_fee_rules[late_fee_applied]
        if today < payment.due_date + timedelta(days=late_fee_rule['dpd']):
            late_fee = py2round((late_fee_rule['late_fee_pct'] * payment.remaining_principal), -2)
            total_late_fee += late_fee
            return total_late_fee

        loan = payment.loan
        # freeze late fee for sold off loan
        if loan.status == LoanStatusCodes.SELL_OFF:
            logger.warning(
                {
                    "action": "juloserver.account_payment.services."
                    "account_payment_related.get_new_late_fee_calculation",
                    "message": "loan is sell off status",
                    "payment_id": payment_id,
                }
            )
            return total_late_fee

        late_fee = py2round((late_fee_rule['late_fee_pct'] * payment.remaining_principal), -2)

        if late_fee <= 0:
            return total_late_fee

        late_fee, status_max_late_fee = loan.get_status_max_late_fee(late_fee)

        if status_max_late_fee:
            return total_late_fee

        late_fee_applied += 1
        total_late_fee += late_fee

    return total_late_fee


def check_lender_eligible_for_paydate_change(account_payment):
    feature_setting = (
        FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.LENDER_ID_NOT_ELIGIBLE_FOR_PAYDATE_CHANGE,
            is_active=True,
        )
        .only("parameters")
        .first()
    )

    # If not active, all are eligible
    if not feature_setting:
        return True

    lender_ids_not_eligible = set(feature_setting.parameters.get('lender_ids', []))
    loan = (
        account_payment.account.loan_set.select_related('lender')
        .only("lender__id")
        .order_by('-id')
        .first()
    )

    return not (loan and loan.lender and loan.lender.id in lender_ids_not_eligible)

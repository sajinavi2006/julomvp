import logging

from django.conf import settings
from django.db import transaction
from django.db import DatabaseError
from django.utils import timezone
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.forms.models import model_to_dict
from django.db.models import Sum, F

from juloserver.julocore.python2.utils import py2round
from juloserver.julo.models import StatusLookup, FeatureSetting
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.exceptions import JuloException

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountTransaction, Account
from juloserver.account.services.credit_limit import store_account_property_history
from juloserver.account.services.account_related import process_change_account_status

from juloserver.account_payment.models import AccountPayment, AccountPaymentPreRefinancing
from juloserver.account_payment.services.reversal import (
    process_account_transaction_reversal,
    transfer_payment_after_reversal,
)
from juloserver.loan_refinancing.constants import (
    CovidRefinancingConst,
    LoanRefinancingConst,
    Campaign
)
from juloserver.loan_refinancing.models import (
    RefinancingTenor,
    LoanRefinancingRequest,
    LoanRefinancingMainReason,
    LoanRefinancingOffer,
    WaiverRequest,
    WaiverPaymentRequest,
    LoanRefinancingRequestCampaign,
    LoanRefinancingApproval,
)
from juloserver.loan_refinancing.services.loan_related import (
    construct_tenure_probabilities,
    mark_old_payments_as_restructured,
    store_payments_restructured_to_payment_pre_refinancing,
    update_payments_after_restructured,
    create_loan_refinancing_payments_based_on_new_tenure,
    get_unpaid_account_payments_after_restructure,
    create_payment_event_for_R3_as_late_fee,
    get_unpaid_payments,
)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    construct_new_payments_for_r2,
    construct_new_payments_for_r3,
    generate_unique_uuid,
    generate_short_url_for_proactive_webview,
    generate_timestamp,
)
from juloserver.loan_refinancing.services.comms_channels import (
    send_loan_refinancing_request_activated_notification,
    send_sos_refinancing_request_activated_notification,
)

from juloserver.waiver.services.loan_refinancing_related import (
    get_j1_loan_refinancing_request,
    check_eligibility_of_j1_loan_refinancing,
)
from juloserver.loan_refinancing.tasks import (
    send_email_covid_refinancing_approved,
    send_email_covid_refinancing_opt,
    send_slack_notification_for_refinancing_approver,
)
from juloserver.loan_refinancing.services.comms_channels import (
    send_loan_refinancing_request_approved_notification,
)
from juloserver.loan_refinancing.utils import get_partner_product
from juloserver.moengage.tasks import async_update_moengage_for_refinancing_request_status_change
from juloserver.account_payment.services.account_payment_related import get_unpaid_account_payment
from juloserver.waiver.models import WaiverAccountPaymentRequest
from juloserver.waiver.services.waiver_related import get_partial_account_payments_by_program
from juloserver.waiver.services.account_related import can_account_get_refinancing
from juloserver.payback.models import WaiverTemp, WaiverPaymentTemp
from juloserver.apiv2.models import LoanRefinancingScoreJ1
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
    ProductLineCodes,
    PaymentEventConst,
)

logger = logging.getLogger(__name__)


def j1_refinancing_activation(payback_trx, account_payment, transaction_date):
    if not account_payment:
        return

    loan_refinancing_request = get_j1_loan_refinancing_request(account_payment.account)
    if not loan_refinancing_request:
        return

    partially_paid_prerequisite_amount = 0
    account = payback_trx.account
    today = timezone.localtime(timezone.now())
    partially_paid_prerequisite_amount += get_partial_account_payments_by_program(
        loan_refinancing_request
    )

    total_paid_amount = payback_trx.amount + partially_paid_prerequisite_amount
    due_amount = \
        loan_refinancing_request.prerequisite_amount - total_paid_amount

    update_va_bni_transaction.delay(
        account.id,
        'refinancing.services.j1_refinancing_activation',
        due_amount
    )

    if not check_eligibility_of_j1_loan_refinancing(
            loan_refinancing_request, transaction_date.date(), total_paid_amount):
        return

    with transaction.atomic():
        do_reversal = False
        if loan_refinancing_request.is_reactive and partially_paid_prerequisite_amount > 0:
            do_reversal = True
            date_approved = timezone.localtime(loan_refinancing_request.cdate)
            loan_refinancing_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(
                is_accepted=True
            ).last()
            if loan_refinancing_offer:
                date_approved = timezone.localtime(loan_refinancing_offer.offer_accepted_ts)
            account_transactions = AccountTransaction.objects.filter(
                transaction_type__in=[PaymentEventConst.PAYMENT, PaymentEventConst.CUSTOMER_WALLET],
                cdate__gte=date_approved,
                transaction_date__date__gte=date_approved.date(),
                transaction_date__date__lte=today.date(),
                account=account,
                can_reverse=True,
            ).order_by('-id')

            note = "partial payment refinancing"
            account_transaction_voids = dict()
            for account_transaction in account_transactions:
                account_transaction_voids[
                    account_transaction.id
                ] = process_account_transaction_reversal(
                    account_transaction, note=note, refinancing_reversal=True
                )

        j1_loan_refinancing_factory = J1LoanRefinancing(account_payment, loan_refinancing_request)
        if not j1_loan_refinancing_factory.activate():
            raise JuloException('failed to activate covid loan refinancing',
                                'gagal aktivasi covid loan refinancing')

        if do_reversal:
            account_transaction_void_objs = AccountTransaction.objects.filter(
                id__in=account_transaction_voids.keys()
            ).order_by('id')

            for account_transaction in account_transaction_void_objs:
                account_transaction_void = account_transaction_voids[account_transaction.id]
                if account_transaction_void:
                    transfer_payment_after_reversal(
                        account_transaction_void.original_transaction,
                        account_transaction_void.account,
                        account_transaction_void,
                        from_refinancing=True,
                    )


def mark_old_account_payments_as_restructured(unpaid_payments, unpaid_account_payments):
    status_code = StatusLookup.objects.get_or_none(
        status_code=PaymentStatusCodes.PARTIAL_RESTRUCTURED)
    for unpaid_account_payment in unpaid_account_payments:
        updated_data = {'is_restructured': True}
        if unpaid_account_payment.paid_amount > 0:
            updated_data['status'] = status_code
        unpaid_account_payment.update_safely(**updated_data)
        mark_old_payments_as_restructured(unpaid_payments[unpaid_account_payment.id])


def store_account_payments_restructured_to_account_payment_pre_refinancing(
        unpaid_payments, unpaid_account_payments, loan_refinancing_request):
    payments_restructured = []
    for account_payment in unpaid_account_payments:
        payment_data = dict(
            account_payment_id=account_payment.id,
            account_id=account_payment.account.id,
            status_code=account_payment.status,
            due_date=account_payment.due_date,
            ptp_date=account_payment.ptp_date,
            is_ptp_robocall_active=account_payment.is_ptp_robocall_active,
            due_amount=account_payment.due_amount,
            principal_amount=account_payment.principal_amount,
            interest_amount=account_payment.interest_amount,
            paid_date=account_payment.paid_date,
            paid_amount=account_payment.paid_amount,
            late_fee_amount=account_payment.late_fee_amount,
            late_fee_applied=account_payment.late_fee_applied,
            is_robocall_active=account_payment.is_robocall_active,
            is_success_robocall=account_payment.is_success_robocall,
            is_collection_called=account_payment.is_collection_called,
            is_reminder_called=account_payment.is_reminder_called,
            paid_interest=account_payment.paid_interest,
            paid_principal=account_payment.paid_principal,
            paid_late_fee=account_payment.paid_late_fee,
            ptp_amount=account_payment.ptp_amount,
            is_restructured=account_payment.is_restructured,
            loan_refinancing_request=loan_refinancing_request,
        )
        payments_restructured.append(AccountPaymentPreRefinancing(**payment_data))
        store_payments_restructured_to_payment_pre_refinancing(
            unpaid_payments[account_payment.id], loan_refinancing_request
        )

    AccountPaymentPreRefinancing.objects.bulk_create(payments_restructured)


def update_account_payments_after_restructured(
        payments_restructured, account_payments_restructured):
    for account_payment in account_payments_restructured:
        if account_payment.paid_amount > 0:
            new_calculation = update_calculation_for_account_payment_partial_restructured(
                account_payment)
            new_installment_principal = new_calculation['principal']
            new_installment_interest = new_calculation['interest']
            new_late_fee_amount = new_calculation['late_fee']

        else:
            new_installment_principal = 0
            new_installment_interest = 0
            new_late_fee_amount = 0

        account_payment.update_safely(
            late_fee_applied=0,
            due_amount=0,
            principal_amount=new_installment_principal,
            paid_principal=new_installment_principal,
            interest_amount=new_installment_interest,
            paid_interest=new_installment_interest,
            late_fee_amount=new_late_fee_amount,
            paid_late_fee=new_late_fee_amount
        )
        update_payments_after_restructured(payments_restructured[account_payment.id])


def update_calculation_for_account_payment_partial_restructured(account_payment):
    payment_dict = {}

    payment_dict['principal'] = account_payment.paid_principal
    payment_dict['interest'] = account_payment.paid_interest
    payment_dict['late_fee'] = account_payment.paid_late_fee

    return payment_dict


def create_loan_refinancing_account_payments_based_on_new_tenure(
        new_installments, account, new_payment_struct_by_loan):
    status_code = StatusLookup.objects.get_or_none(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
    account_payment_list = []
    for new_installment in new_installments:
        account_payment = AccountPayment.objects.create(
            account=account,
            due_date=new_installment['due_date'],
            due_amount=new_installment['due_amount'],
            late_fee_amount=new_installment['late_fee'] if 'late_fee' in new_installment else 0,
            principal_amount=new_installment['principal_amount'],
            interest_amount=new_installment['interest_amount'],
            status=status_code,
        )
        account_payment_list.append(account_payment.id)
    store_new_payment_structure(account, account_payment_list, new_payment_struct_by_loan)


def create_account_transaction_for_R3_as_late_fee(account_id, tenure_extension):
    account_payments = AccountPayment.objects.filter(
        account_id=account_id,
        status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(is_restructured=True).order_by('due_date')[:tenure_extension]

    for account_payment in account_payments:
        late_fee = account_payment.late_fee_amount
        AccountTransaction.objects.create(
            account=account_payment.account,
            transaction_date=timezone.localtime(timezone.now()),
            transaction_amount=-late_fee,
            transaction_type=LoanRefinancingConst.LOAN_REFINANCING_ADMIN_FEE_TYPE,
            towards_latefee=late_fee,
            can_reverse=False,
        )
    account = Account.objects.get(pk=account_id)
    for loan in account.get_all_active_loan():
        create_payment_event_for_R3_as_late_fee(loan.id, tenure_extension)


def create_account_transaction_to_waive_late_fee(account_payment, loan_refinancing_request):
    AccountTransaction.objects.create(
        account=account_payment.account,
        transaction_date=timezone.localtime(timezone.now()),
        transaction_amount=-loan_refinancing_request.total_latefee_discount,
        transaction_type=LoanRefinancingConst.LOAN_REFINANCING_WAIVE_LATE_FEE_TYPE,
        towards_latefee=loan_refinancing_request.total_latefee_discount,
        can_reverse=False,
    )


def generate_new_payment_structure(
        account, loan_refinancing_request,
        chosen_loan_duration=None, count_unpaid_account_payments=0,
        is_with_latefee_discount=False
):
    new_payment_struct_by_loan = dict()
    total_payment_level_late_fee = 0
    is_program_r3 = loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r3
    total_late_fee_discount = 0
    for loan in account.get_all_active_loan():
        unpaid_payments = get_unpaid_payments(loan, order_by='payment_number')
        if loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r1:
            new_payment_struct = construct_tenure_probabilities(
                unpaid_payments, chosen_loan_duration)
            total_late_fee_discount += new_payment_struct['late_fee_amount']
            new_payment_struct = new_payment_struct[chosen_loan_duration]
            new_payment_struct[0]['due_date'] = loan_refinancing_request.request_date + \
                timedelta(days=loan_refinancing_request.expire_in_days)
        if loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r2:
            new_payment_struct = construct_new_payments_for_r2(
                loan_refinancing_request, unpaid_payments, loans=[loan],
                number_of_unpaid_payment=count_unpaid_account_payments
            )
        if is_program_r3:
            new_payment_struct = construct_new_payments_for_r3(
                loan_refinancing_request, unpaid_payments,
                number_of_unpaid_payment=count_unpaid_account_payments
            )
            new_payment_struct = new_payment_struct['payments']

            # adjust late_fee rounding (odd when active loan is 7 ) on last payment
            total_payment_level_late_fee += new_payment_struct[0]['late_fee']
            if total_payment_level_late_fee > LoanRefinancingConst.R3_ADMIN_FEE:
                tenor_extension = len(new_payment_struct) - count_unpaid_account_payments
                for index in range(0, tenor_extension):
                    deviation = total_payment_level_late_fee - LoanRefinancingConst.R3_ADMIN_FEE
                    new_payment_struct[index]['late_fee'] -= deviation
                    new_payment_struct[index]['due_amount'] = new_payment_struct[index]['late_fee']

        new_payment_struct_by_loan[loan.id] = new_payment_struct
        tenor_key = "%s_tenor" % loan.id
        new_payment_struct_by_loan[tenor_key] = len(new_payment_struct) - len(unpaid_payments)

    account_payments = []
    active_loan = account.get_all_active_loan()
    first_loan_id = active_loan.first().id
    is_program_r2 = loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r2
    for index in list(range(0, len(new_payment_struct_by_loan[first_loan_id]))):
        interest_amount = 0
        principal_amount = 0
        late_fee_amount = 0
        due_amount = 0
        due_date = new_payment_struct_by_loan[first_loan_id][index]['due_date']
        for loan in active_loan:
            loan_id = loan.id
            if is_program_r2:
                interest_amount += new_payment_struct_by_loan[loan_id][index][
                    'installment_interest']
                principal_amount += new_payment_struct_by_loan[loan_id][index][
                    'installment_principal']
            else:
                interest_amount += new_payment_struct_by_loan[loan_id][index]['interest_amount']
                principal_amount += new_payment_struct_by_loan[loan_id][index]['principal_amount']
                late_fee_amount += new_payment_struct_by_loan[loan_id][index]['late_fee'] \
                    if 'late_fee' in new_payment_struct_by_loan[loan_id][index] else 0
            due_amount += new_payment_struct_by_loan[loan_id][index]['due_amount']

        account_payments.append({
            'principal_amount': principal_amount,
            'interest_amount': interest_amount,
            'due_amount': due_amount,
            'due_date': due_date,
            'payment_number': index + 1,
            'late_fee': late_fee_amount,
            'account_payment_id': index + 1,
            'payment_status_id': PaymentStatusCodes.PAYMENT_NOT_DUE,
        })

    if is_with_latefee_discount:
        return new_payment_struct_by_loan, account_payments, total_late_fee_discount

    if is_program_r3:
        account_payments = dict(
            payments=account_payments,
        )
    return new_payment_struct_by_loan, account_payments


def store_new_payment_structure(account, account_payment_list, new_payment_struct_by_loan):
    for loan in account.get_all_active_loan():
        new_payment_struct = new_payment_struct_by_loan[loan.id]
        for index, new_payment in enumerate(new_payment_struct):
            new_payment['account_payment_id'] = account_payment_list[index]
            if 'principal_amount' not in new_payment:
                new_payment['principal_amount'] = new_payment['installment_principal']
            if 'interest_amount' not in new_payment:
                new_payment['interest_amount'] = new_payment['installment_interest']
            new_payment_struct[index] = new_payment
        create_loan_refinancing_payments_based_on_new_tenure(new_payment_struct, loan)


def store_refinancing_tenor(loan_refinancing_request, additional_tenor):
    refinancing_tenor_data = []
    for loan in loan_refinancing_request.account.get_all_active_loan():
        refinancing_tenor_data.append(
            RefinancingTenor(
                loan=loan,
                loan_refinancing_request=loan_refinancing_request,
                additional_tenor=additional_tenor["%s_tenor" % loan.id],
            )
        )
    if refinancing_tenor_data:
        RefinancingTenor.objects.bulk_create(refinancing_tenor_data)


def update_account_for_refinancing(account):
    process_change_account_status(
        account, AccountConstant.STATUS_CODE.suspended, "refinancing activated")
    update_account_property_for_refinancing(
        account, dict(ever_refinanced=True, refinancing_ongoing=True))


def update_account_property_for_refinancing(account, input_params):
    account_property = account.accountproperty_set.last()
    if not account_property:
        return

    current_account_property = model_to_dict(account.accountproperty_set.last())
    account_property.update_safely(**input_params)
    store_account_property_history(
        input_params, account_property, current_account_property)


class J1LoanRefinancing(object):
    def __init__(self, account_payment, loan_refinancing_request):
        self._account_payment = account_payment
        self._loan_refinancing_request = loan_refinancing_request
        self._loan_refinancing_product = loan_refinancing_request.product_type
        self._account = loan_refinancing_request.account
        self._loan_duration = loan_refinancing_request.loan_duration

    def activate(self):
        loan_refinancing_method = self._get_loan_refinancing_product_method()
        with transaction.atomic():
            try:
                if self._loan_refinancing_product in CovidRefinancingConst.reactive_products():
                    self._account.update_safely(is_restructured=True)
                    self._account.get_all_active_loan().update(is_restructured=True)
                return loan_refinancing_method()
            except DatabaseError:
                logger.info({
                    'method': 'activate_covid_loan_refinancing',
                    'payment_id': self._account_payment.id,
                    'error': 'failed do adjustment and split the payments'
                })
                return False

    def _get_loan_refinancing_product_method(self):
        if self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.r1:
            if self._loan_refinancing_request.loanrefinancingrequestcampaign_set.filter(
                    campaign_name=Campaign.R1_SOS_REFINANCING_23).exists():
                return self._activate_sos_loan_refinancing_r1
            else:
                return self._activate_loan_refinancing_r1
        if self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.r2:
            return self._activate_loan_refinancing_r2
        if self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.r3:
            return self._activate_loan_refinancing_r3
        if self._loan_refinancing_product in CovidRefinancingConst.waiver_products():
            return self._activate_loan_refinancing_waiver
        raise ValueError('product is not found')

    def _activate_loan_refinancing_r1(self):
        with ActivateJ1RefinancingRequest(
            self._loan_refinancing_request, self._account_payment
        ) as (unpaid_payments, unpaid_account_payments):
            chosen_loan_duration = unpaid_account_payments.count() + self._loan_duration
            new_payment_struct_by_loan, new_payment_struct = generate_new_payment_structure(
                self._account, self._loan_refinancing_request,
                chosen_loan_duration=chosen_loan_duration)
            new_payment_struct[0]['due_date'] = self._loan_refinancing_request.request_date +\
                timedelta(days=self._loan_refinancing_request.expire_in_days)
            mark_old_account_payments_as_restructured(unpaid_payments, unpaid_account_payments)
            store_account_payments_restructured_to_account_payment_pre_refinancing(
                unpaid_payments, unpaid_account_payments, self._loan_refinancing_request)
            update_account_payments_after_restructured(unpaid_payments, unpaid_account_payments)
            create_loan_refinancing_account_payments_based_on_new_tenure(
                new_payment_struct, self._account, new_payment_struct_by_loan)
            store_refinancing_tenor(self._loan_refinancing_request, new_payment_struct_by_loan)
        return True

    def _activate_loan_refinancing_r2(self):
        with ActivateJ1RefinancingRequest(
            self._loan_refinancing_request, self._account_payment
        ) as (unpaid_payments, unpaid_account_payments):
            new_payment_struct_by_loan, new_payments = generate_new_payment_structure(
                self._account, self._loan_refinancing_request,
                count_unpaid_account_payments=len(unpaid_account_payments),
            )
            mark_old_account_payments_as_restructured(unpaid_payments, unpaid_account_payments)
            store_account_payments_restructured_to_account_payment_pre_refinancing(
                unpaid_payments, unpaid_account_payments, self._loan_refinancing_request)
            update_account_payments_after_restructured(unpaid_payments, unpaid_account_payments)
            account_payment_list = []
            for payment in new_payments:
                account_payment = AccountPayment.objects.create(
                    account=self._account,
                    due_date=payment["due_date"],
                    due_amount=payment["due_amount"],
                    principal_amount=payment["principal_amount"],
                    interest_amount=payment["interest_amount"],
                    status_id=payment["payment_status_id"],
                    paid_interest=0,
                    paid_principal=0,
                    paid_amount=0,
                )
                account_payment_list.append(account_payment.id)

            store_new_payment_structure(
                self._account, account_payment_list, new_payment_struct_by_loan)
            store_refinancing_tenor(self._loan_refinancing_request, new_payment_struct_by_loan)
        return True

    def _activate_loan_refinancing_r3(self):
        with ActivateJ1RefinancingRequest(
            self._loan_refinancing_request, self._account_payment
        ) as (unpaid_payments, unpaid_account_payments):
            new_payment_struct_by_loan, new_payment_struct = generate_new_payment_structure(
                self._account, self._loan_refinancing_request,
                count_unpaid_account_payments=len(unpaid_account_payments),
            )
            mark_old_account_payments_as_restructured(unpaid_payments, unpaid_account_payments)
            store_account_payments_restructured_to_account_payment_pre_refinancing(
                unpaid_payments, unpaid_account_payments, self._loan_refinancing_request)
            update_account_payments_after_restructured(unpaid_payments, unpaid_account_payments)
            create_loan_refinancing_account_payments_based_on_new_tenure(
                new_payment_struct['payments'], self._account, new_payment_struct_by_loan)
            create_account_transaction_for_R3_as_late_fee(self._account.id, self._loan_duration)
            store_refinancing_tenor(self._loan_refinancing_request, new_payment_struct_by_loan)
        return True

    def _activate_loan_refinancing_waiver(self):
        self._loan_refinancing_request.change_status(CovidRefinancingConst.STATUSES.activated)
        self._loan_refinancing_request.offer_activated_ts = timezone.localtime(timezone.now())
        self._loan_refinancing_request.save()
        send_loan_refinancing_request_activated_notification(self._loan_refinancing_request)
        if self._loan_refinancing_product != CovidRefinancingConst.PRODUCTS.r4:
            change_reason = "Refinancing activated"
        else:
            change_reason = "R4 cool off period"
        process_change_account_status(
            self._account, AccountConstant.STATUS_CODE.suspended, change_reason
        )
        return True

    def _activate_sos_loan_refinancing_r1(self):
        with ActivateJ1RefinancingRequest(
            self._loan_refinancing_request, self._account_payment, True
        ) as (unpaid_payments, unpaid_account_payments):
            loan_refinancing_campaign = self._loan_refinancing_request.\
                loanrefinancingrequestcampaign_set.filter(
                    campaign_name=Campaign.R1_SOS_REFINANCING_23).last()
            chosen_loan_duration = unpaid_account_payments.count() + 1
            new_payment_struct_by_loan, new_payment_struct = generate_new_payment_structure(
                self._account, self._loan_refinancing_request,
                chosen_loan_duration=chosen_loan_duration)
            new_payment_struct[0]['due_date'] = loan_refinancing_campaign.expired_at
            mark_old_account_payments_as_restructured(unpaid_payments, unpaid_account_payments)
            store_account_payments_restructured_to_account_payment_pre_refinancing(
                unpaid_payments, unpaid_account_payments, self._loan_refinancing_request)
            update_account_payments_after_restructured(unpaid_payments, unpaid_account_payments)
            create_loan_refinancing_account_payments_based_on_new_tenure(
                new_payment_struct, self._account, new_payment_struct_by_loan)
            store_refinancing_tenor(self._loan_refinancing_request, new_payment_struct_by_loan)
            update_va_bni_transaction.delay(
                self._account.id,
                'refinancing.services.J1LoanRefinancing._activate_sos_loan_refinancing_r1',
                new_payment_struct[0]['due_amount']
            )
        return True


class ActivateJ1RefinancingRequest(object):
    def __init__(self, loan_refinancing_request, account_payment, is_sos_refinancing=False):
        self._loan_refinancing_request = loan_refinancing_request
        self._account = loan_refinancing_request.account
        self._account_payment = account_payment
        self._ordered_unpaid_account_payments = get_unpaid_account_payments_after_restructure(
            self._account, order_by='due_date')
        self._is_sos_refinancing = is_sos_refinancing

    def __enter__(self):
        unpaid_payments = dict()
        for account_payment in self._ordered_unpaid_account_payments:
            unpaid_payments[account_payment.id] = account_payment.payment_set.filter(
                payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
            ).exclude(is_restructured=True).order_by('payment_number')
        return unpaid_payments, self._ordered_unpaid_account_payments

    def __exit__(self, exc_type, exc_value, traceback):
        from juloserver.minisquad.tasks2.intelix_task import \
            delete_paid_payment_from_intelix_if_exists_async_for_j1
        from juloserver.minisquad.tasks2.dialer_system_task import delete_paid_payment_from_dialer
        if not exc_value:
            create_account_transaction_to_waive_late_fee(
                self._account_payment, self._loan_refinancing_request)
            update_account_for_refinancing(self._account)
            if self._is_sos_refinancing:
                send_sos_refinancing_request_activated_notification(self._loan_refinancing_request)
            else:
                send_loan_refinancing_request_activated_notification(self._loan_refinancing_request)
            self._loan_refinancing_request.change_status(CovidRefinancingConst.STATUSES.activated)
            self._loan_refinancing_request.offer_activated_ts = timezone.localtime(timezone.now())
            self._loan_refinancing_request.save()
            # delete queue intelix
            delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(
                self._account_payment.id
            )
            delete_paid_payment_from_dialer.delay(self._account_payment.id)


def j1_validate_proactive_refinancing_data(data_reader):
    return_data = {
        'invalid_accounts': [],
        'invalid_products': [],
        'data_incomplete': [],
        'loan_refinancing_request_exist': [],
        'invalid_lenders': [],
    }
    valid_data = []
    proactive_product = CovidRefinancingConst.proactive_products()
    product_list = list(CovidRefinancingConst.PRODUCTS.__dict__.values())
    proactive_status_list = list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values())
    expired_status_list = list(CovidRefinancingConst.STATUSES.expired)
    for data in data_reader:
        account_id = data['account_id']
        account_exists = Account.objects.filter(
            pk=account_id, application__customer__email=data['email_address']
        ).exists()
        allow_refinancing_program, _ = can_account_get_refinancing(account_id)
        if not allow_refinancing_program:
            return_data['invalid_lenders'].append(data)
        elif j1_proactive_validation(data):
            if not account_exists:
                return_data['invalid_accounts'].append(data)
            elif LoanRefinancingRequest.objects.filter(account_id=account_id)\
                    .exclude(product_type__in=proactive_product)\
                    .exclude(status__in=proactive_status_list + expired_status_list).exists():
                return_data['loan_refinancing_request_exist'].append(data)
            else:
                valid_data.append(data)

        elif data['covid_product'] and data['covid_product'] not in product_list:
            return_data['invalid_products'].append(data)

        elif not data['new_affordability'] and (not data['new_income'] or not data['new_expense']):
            return_data['data_incomplete'].append(data)

        elif not account_exists:
            return_data['invalid_accounts'].append(data)

        elif LoanRefinancingRequest.objects.filter(account_id=account_id)\
                .exclude(product_type__in=proactive_product)\
                .exclude(status__in=proactive_status_list).exists():
            return_data['loan_refinancing_request_exist'].append(data)

        else:
            valid_data.append(data)

    is_valid = not any((return_data.values()))
    return_data.update({"valid_data": valid_data})
    return is_valid, return_data


def j1_proactive_validation(data):
    return (data['email_address'] and data['account_id']) and not data['covid_product'] \
        and not data['tenure_extension'] and not data['new_income'] and not data['new_expense'] \
        and not data['new_employment_status'] and not data['new_affordability']


def store_j1_proactive_refinancing_data(valid_data, feature_params):
    row_count = 0
    propose_email_status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
    mapping_main_reason = LoanRefinancingConst.MAPPING_LOAN_REFINANCING_MAIN_REASON
    for data in valid_data:
        account = Account.objects.select_related('customer').get(pk=data['account_id'])
        if not data['new_affordability']:
            app = account.last_application
            new_net_income = app.monthly_income - app.monthly_expenses
            if data['new_income'] and data['new_expense']:
                new_net_income = int(data['new_income']) - int(data['new_expense'])
            previous_net_income = app.monthly_income - app.monthly_expenses
            new_affordability = float(new_net_income) / float(previous_net_income)
        else:
            new_affordability = float(data['new_affordability']) / float(100)

        unpaid_payments = get_unpaid_account_payment(account.id)
        max_extension = 3 if len(unpaid_payments) >= 6 \
            else feature_params['tenure_extension_rule']['J1_%s' % len(unpaid_payments)]
        tenure_extension = int(data['tenure_extension']) if data['tenure_extension'] else 0
        extension = tenure_extension if tenure_extension < max_extension else max_extension

        loan_refinancing_req = LoanRefinancingRequest.objects.filter(account=account)\
            .exclude(status=CovidRefinancingConst.STATUSES.expired).last()
        loan_refinancing_main_reason = data['new_employment_status'] if \
            data['new_employment_status'].lower() not in mapping_main_reason \
            else mapping_main_reason[data['new_employment_status'].lower()]
        loan_ref_req_data = dict(
            account_id=data['account_id'],
            affordability_value=new_affordability,
            product_type=data['covid_product'],
            expire_in_days=feature_params['email_expire_in_days'],
            loan_duration=extension,
            new_income=int(data['new_income'] or 0),
            new_expense=int(data['new_expense'] or 0),
            request_date=generate_timestamp().date(),
            form_submitted_ts=None,
            loan_refinancing_main_reason=LoanRefinancingMainReason.objects.filter(
                reason__icontains=loan_refinancing_main_reason, is_active=True).last(),
            comms_channel_1="Email",
        )
        row_count += 1
        if not data['covid_product']:
            loan_ref_req_data['status'] = propose_email_status
            loan_ref_req_data['uuid'] = generate_unique_uuid()
            loan_ref_req_data['url'] = \
                generate_short_url_for_proactive_webview(loan_ref_req_data['uuid'])

        if loan_refinancing_req:
            loan_refinancing_req.update_safely(**loan_ref_req_data)
        else:
            loan_refinancing_req = LoanRefinancingRequest.objects.create(**loan_ref_req_data)
            async_update_moengage_for_refinancing_request_status_change.apply_async(
                (loan_refinancing_req.id,), countdown=settings.DELAY_FOR_MOENGAGE_API_CALL
            )

        if loan_refinancing_req.product_type:
            send_email_covid_refinancing_approved.delay(loan_refinancing_req.id)

        elif loan_refinancing_req.status == propose_email_status:
            loan_refinancing_req.update_safely(channel=CovidRefinancingConst.CHANNELS.proactive)
            send_email_covid_refinancing_opt.delay(loan_refinancing_req.id)

    return row_count


def j1_automate_refinancing_offer(serializer_data, loan_refinancing_req):
    today = timezone.localtime(timezone.now())
    offer_id = int(serializer_data["product_id_1"])
    if "product_id_2" in serializer_data and int(serializer_data["product_id_2"]) != 0:
        offer_id = int(serializer_data["product_id_2"])
    customer = loan_refinancing_req.account.last_application.customer
    loan_refinancing_offer = LoanRefinancingOffer.objects.get(pk=offer_id)
    loan_refinancing_offer.update_safely(
        is_accepted=True,
        offer_accepted_ts=today,
        selected_by=customer.user,
    )

    other_offer = LoanRefinancingOffer.objects.filter(
        loan_refinancing_request=loan_refinancing_req,
        product_type=loan_refinancing_offer.product_type,
        prerequisite_amount=loan_refinancing_offer.prerequisite_amount,
        loan_duration=loan_refinancing_offer.loan_duration,
        generated_by=loan_refinancing_offer.generated_by,
        latefee_discount_percentage=loan_refinancing_offer.latefee_discount_percentage,
        interest_discount_percentage=loan_refinancing_offer.interest_discount_percentage,
        principal_discount_percentage=loan_refinancing_offer.principal_discount_percentage
    ).exclude(id=offer_id).last()

    target_channel = CovidRefinancingConst.CHANNELS.proactive
    if other_offer and not other_offer.is_proactive_offer:
        target_channel = CovidRefinancingConst.CHANNELS.reactive

    loan_refinancing_req.update_safely(
        status=CovidRefinancingConst.STATUSES.offer_selected,
        product_type=loan_refinancing_offer.product_type,
        prerequisite_amount=loan_refinancing_offer.prerequisite_amount,
        total_latefee_discount=loan_refinancing_offer.total_latefee_discount,
        loan_duration=loan_refinancing_offer.loan_duration,
        channel=target_channel
    )
    if serializer_data["product_type"] in CovidRefinancingConst.waiver_products():
        account = loan_refinancing_req.account
        application = account.last_application
        loan_refinancing_score = LoanRefinancingScoreJ1.objects.filter(account=account).last()
        unpaid_payments = get_unpaid_account_payment(account.id)
        account_payment = unpaid_payments.first()
        last_account_payment = unpaid_payments.last()
        bucket_name = 'Bucket {}'.format(account_payment.bucket_number)
        if serializer_data["product_type"] in CovidRefinancingConst.waiver_without_r4():
            overdue_account_payment = AccountPayment.objects.filter(account=account)\
                .overdue().filter(is_restructured=False).order_by('-due_date').first()
            if overdue_account_payment:
                last_account_payment = overdue_account_payment
            else:
                last_account_payment = account_payment
            unpaid_payments = AccountPayment.objects.filter(
                pk__gte=account_payment.id, pk__lte=last_account_payment.id
            )

        remaining_late_fee = unpaid_payments.aggregate(
            total_late_fee=Sum(F('late_fee_amount') - F('paid_late_fee')))['total_late_fee'] or 0
        remaining_interest = unpaid_payments.aggregate(
            total_interest=Sum(F('interest_amount') - F('paid_interest')))['total_interest'] or 0
        remaining_principal = unpaid_payments.aggregate(
            total_principal=Sum(F('principal_amount') - F('paid_principal'))
        )['total_principal'] or 0

        total_discount = loan_refinancing_offer.total_latefee_discount + \
            loan_refinancing_offer.total_interest_discount + \
            loan_refinancing_offer.total_principal_discount
        outstanding_amount = loan_refinancing_offer.prerequisite_amount + total_discount
        if serializer_data["product_type"] in (
                CovidRefinancingConst.PRODUCTS.r5, CovidRefinancingConst.PRODUCTS.r6):
            remaining_principal = 0
            if serializer_data["product_type"] == CovidRefinancingConst.PRODUCTS.r5:
                remaining_interest = 0

        waiver_validity_date = today + relativedelta(days=loan_refinancing_offer.validity_in_days)
        product_line_code = application.product_line_code
        requested_late_fee_percentage = loan_refinancing_offer.latefee_discount_percentage
        requested_interest_percentage = loan_refinancing_offer.interest_discount_percentage
        requested_principal_percentage = loan_refinancing_offer.principal_discount_percentage
        waiver_request_dict = dict(
            account=loan_refinancing_req.account,
            is_j1=True,
            first_waived_account_payment=account_payment,
            last_waived_account_payment=last_account_payment,
            agent_name=None,
            bucket_name=bucket_name,
            program_name=serializer_data["product_type"].lower(),
            is_covid_risky=loan_refinancing_score.is_covid_risky_boolean,
            outstanding_amount=outstanding_amount,
            unpaid_principal=remaining_principal,
            unpaid_interest=remaining_interest,
            unpaid_late_fee=remaining_late_fee,
            requested_late_fee_waiver_percentage=requested_late_fee_percentage,
            requested_late_fee_waiver_amount=loan_refinancing_offer.total_latefee_discount,
            requested_interest_waiver_percentage=requested_interest_percentage,
            requested_interest_waiver_amount=loan_refinancing_offer.total_interest_discount,
            requested_principal_waiver_percentage=requested_principal_percentage,
            requested_principal_waiver_amount=loan_refinancing_offer.total_principal_discount,
            waiver_validity_date=waiver_validity_date,
            reason=loan_refinancing_req.loan_refinancing_main_reason.reason,
            ptp_amount=loan_refinancing_offer.prerequisite_amount,
            is_need_approval_tl=False,
            is_need_approval_supervisor=False,
            is_need_approval_colls_head=False,
            is_need_approval_ops_head=False,
            is_automated=True,
            partner_product=get_partner_product(product_line_code)
        )

        waiver_request = WaiverRequest.objects.create(**waiver_request_dict)
        waiver_account_payment_request_data = []
        waiver_request.waiver_account_payment_request.all().delete()
        waiver_payment_request_data = []
        account_payments_dict = dict()
        for loan in account.get_all_active_loan():
            payments = loan.payment_set.not_paid_active().order_by('due_date')
            for payment in payments:
                late_fee = payment.late_fee_amount
                interest = payment.installment_interest
                principal = payment.installment_principal
                account_payment_id = payment.account_payment_id
                if account_payment_id in account_payments_dict.keys():
                    account_payment_dict = account_payments_dict[account_payment_id]
                    account_payments_dict[account_payment_id] = {
                        'late_fee': account_payment_dict['late_fee'] + late_fee,
                        'interest': account_payment_dict['interest'] + interest,
                        'principal': account_payment_dict['principal'] + principal,
                    }
                else:
                    account_payments_dict[account_payment_id] = {
                        'late_fee': late_fee,
                        'interest': interest,
                        'principal': principal,
                    }

                calculated_late_fee = py2round(
                    (float(requested_late_fee_percentage.replace('%', '')) / float(100)) * float(
                        late_fee))
                calculated_interest = py2round(
                    (float(requested_interest_percentage.replace('%', '')) / float(100)) * float(
                        interest))
                calculated_principal = py2round(
                    (float(requested_principal_percentage.replace('%', '')) / float(100)) * float(
                        principal))
                total = calculated_late_fee + calculated_interest + calculated_principal
                waiver_payment_dict = dict(
                    waiver_request=waiver_request,
                    payment=payment,
                    account_payment_id=account_payment.id,
                    outstanding_late_fee_amount=0,
                    outstanding_interest_amount=0,
                    outstanding_principal_amount=0,
                    total_outstanding_amount=payment.due_amount,
                    requested_late_fee_waiver_amount=calculated_late_fee,
                    requested_interest_waiver_amount=calculated_interest,
                    requested_principal_waiver_amount=calculated_principal,
                    total_requested_waiver_amount=total,
                    remaining_late_fee_amount=0,
                    remaining_interest_amount=0,
                    remaining_principal_amount=0,
                    total_remaining_amount=0,
                    is_paid_off_after_ptp=True,
                )
                waiver_payment_request_data.append(WaiverPaymentRequest(**waiver_payment_dict))
        WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)
        for account_payment_id in account_payments_dict:
            account_payment_dict = account_payments_dict[account_payment_id]
            late_fee = py2round(
                (float(requested_late_fee_percentage.replace('%', '')) / float(100)) * float(
                    account_payment_dict['late_fee']))
            interest = py2round(
                (float(requested_interest_percentage.replace('%', '')) / float(100)) * float(
                    account_payment_dict['interest']))
            principal = py2round(
                (float(requested_principal_percentage.replace('%', '')) / float(100)) * float(
                    account_payment_dict['principal']))
            total = late_fee + interest + principal
            waiver_account_payment_request_data.append(
                WaiverAccountPaymentRequest(
                    waiver_request=waiver_request,
                    account_payment_id=account_payment_id,
                    outstanding_late_fee_amount=0,
                    outstanding_interest_amount=0,
                    outstanding_principal_amount=0,
                    total_outstanding_amount=0,
                    requested_late_fee_waiver_amount=late_fee,
                    requested_interest_waiver_amount=interest,
                    requested_principal_waiver_amount=principal,
                    total_requested_waiver_amount=total,
                    remaining_late_fee_amount=0,
                    remaining_interest_amount=0,
                    remaining_principal_amount=0,
                    total_remaining_amount=0,
                )
            )
        WaiverAccountPaymentRequest.objects.bulk_create(waiver_account_payment_request_data)

        waiver_temp = WaiverTemp.objects.create(
            account=loan_refinancing_req.account,
            late_fee_waiver_amt=loan_refinancing_offer.total_latefee_discount,
            interest_waiver_amt=loan_refinancing_offer.total_interest_discount,
            principal_waiver_amt=loan_refinancing_offer.total_principal_discount,
            need_to_pay=loan_refinancing_offer.prerequisite_amount,
            waiver_date=today.date(),
            late_fee_waiver_note="Loan Refinancing Proactive",
            interest_waiver_note="Loan Refinancing Proactive",
            principal_waiver_note="Loan Refinancing Proactive",
            valid_until=today + timedelta(days=loan_refinancing_offer.validity_in_days),
            waiver_request=waiver_request,
        )
        waiver_payment_temp_data = []
        for account_payment in unpaid_payments:
            late_fee = py2round(
                (float(requested_late_fee_percentage.replace('%', '')) / float(100)) * float(
                    account_payment.late_fee_amount))
            interest = py2round(
                (float(requested_interest_percentage.replace('%', '')) / float(100)) * float(
                    account_payment.interest_amount))
            principal = py2round(
                (float(requested_principal_percentage.replace('%', '')) / float(100)) * float(
                    account_payment.principal_amount))
            waiver_payment_temp_data.append(
                WaiverPaymentTemp(
                    waiver_temp=waiver_temp,
                    account_payment=account_payment,
                    late_fee_waiver_amount=late_fee,
                    interest_waiver_amount=interest,
                    principal_waiver_amount=principal,
                )
            )
        WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)


def check_account_id_is_for_cohort_campaign(account_id):
    campaign_request = LoanRefinancingRequestCampaign.objects.filter(
        account_id=account_id,
        campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
        expired_at__gte=timezone.now().date(),
        status='Success'
    ).last()

    return campaign_request


def update_requested_status_refinancing_to_expired_for_cohort_campaign(
        campaign_request, loan_refinancing_request, is_unsuitable_offer=True):
    loan_refinancing_to_expired_status = LoanRefinancingRequest.objects.filter(
        pk=campaign_request.loan_refinancing_request.id
    ).last()
    loan_refinancing_to_expired_status.update_safely(
        status=CovidRefinancingConst.STATUSES.expired,
        udate=timezone.localtime(timezone.now())
    )
    if is_unsuitable_offer:
        """
        Unsuitable offer here means, if offering from agent different with initial agreement,
        let's say campaign program is R56, but in the end agent offering other refinancing (R1234)
        And why need update the status to be 'Failed', for system not mistaken while separate data,
        between normal bucket and cohort campaign bucket
        """
        reasons = {
            'reason': 'unsuitable offer'
        }
        campaign_request.update_safely(
            status='Failed',
            extra_data=reasons,
            udate=timezone.localtime(timezone.now())
        )
    else:
        campaign_request.update_safely(
            loan_refinancing_request=loan_refinancing_request,
            udate=timezone.localtime(timezone.now())
        )


def get_monthly_expenses(account, application):
    app_monthly_expenses = 0
    if account and (application.product_line_code == ProductLineCodes.TURBO
                    or account.account_lookup.workflow.name == WorkflowConst.JULO_STARTER):
        sphinx_threshold = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.SPHINX_THRESHOLD,
            is_active=True
        ).last()
        affordability_formula = 0.2
        if sphinx_threshold:
            affordability_formula = sphinx_threshold.parameters.get('affordability_formula', 0.2)
        app_monthly_expenses = application.monthly_income * affordability_formula
    else:
        app_monthly_expenses = application.monthly_expenses

    return int(app_monthly_expenses)


def process_loan_refinancing_approval(data, next_approval=None):
    loan_refinancing_request = data['loan_refinancing_request']
    loan_refinancing_approval = data['loan_refinancing_approval']
    with transaction.atomic():
        now = timezone.localtime(timezone.now())
        loan_refinancing_approval.update_safely(
            is_accepted=data['is_accepted'],
            approver_reason=data['reason'],
            approver_notes=data['notes'],
            approver_ts=now,
            approver=data['user'],
        )
        if data['is_accepted']:
            if next_approval:
                approval = LoanRefinancingApproval.objects.create(
                    loan_refinancing_request=loan_refinancing_request,
                    bucket_name=loan_refinancing_approval.bucket_name,
                    approval_type=next_approval,
                    requestor_reason=data['reason'],
                    requestor_notes=data['notes'],
                    extra_data=data['extra_data'],
                    requestor=data['user'],
                )
                loan_refinancing_approval.update_safely(extra_data=None)
                send_slack_notification_for_refinancing_approver.delay(approval.id)
            else:
                if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.offer_selected:
                    raise Exception("Refinacing status is not offer_selected, Approval not allowed")
                loan_refinancing_request.update_safely(
                    status=CovidRefinancingConst.STATUSES.approved
                )
                send_loan_refinancing_request_approved_notification(loan_refinancing_request)
            return 'Loan refinancing berhasil diapprove'
        else:
            loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.rejected)
            return 'Loan refinancing berhasil reject'
